#!/bin/bash

set -e

# Function to check if a port is available
check_port() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1 || \
       netstat -tuln 2>/dev/null | grep -q ":$port " || \
       ss -tuln 2>/dev/null | grep -q ":$port "; then
        return 1  # Port is in use
    else
        return 0  # Port is available
    fi
}

# Function to find next available port starting from a base port
find_available_port() {
    local base_port=$1
    local port=$base_port
    while ! check_port $port; do
        port=$((port + 1))
    done
    echo $port
}

# Parse arguments
ACTION=${1:-"up"}
BASE_PORT=${2:-8000}
STACK_NAME=${3:-"dev"}

# Validate action
if [[ ! "$ACTION" =~ ^(up|down|logs|ps|restart|stop)$ ]]; then
    echo "Usage: $0 <up|down|logs|ps|restart|stop> [base_port] [stack_name]"
    echo ""
    echo "Examples:"
    echo "  $0 up                    # Start default stack (port 8000)"
    echo "  $0 up 8001               # Start stack on port 8001"
    echo "  $0 up 8002 feature-x     # Start 'feature-x' stack on port 8002"
    echo "  $0 down 8001             # Stop stack on port 8001"
    echo "  $0 logs 8002 feature-x   # View logs for 'feature-x' stack"
    exit 1
fi

# Use docker compose project name to isolate stacks
PROJECT_NAME="papersnitch-${STACK_NAME}"

# Find available ports only if starting up
if [ "$ACTION" = "up" ]; then
    echo "🚀 Starting development stack: $STACK_NAME"
    echo "📍 Base port requested: $BASE_PORT"
    
    DJANGO_PORT=$(find_available_port $BASE_PORT)
    MYSQL_PORT=$(find_available_port 3307)
    REDIS_PORT=$(find_available_port 6380)
    GROBID_PORT=$(find_available_port 8071)
    
    echo ""
    echo "✅ Available ports found:"
    echo "   Django:  $DJANGO_PORT"
    echo "   MySQL:   $MYSQL_PORT"
    echo "   Redis:   $REDIS_PORT"
    echo "   GROBID:  $GROBID_PORT"
    echo ""
    
    # Store port configuration for this stack
    mkdir -p .stacks
    cat > ".stacks/${STACK_NAME}.env" <<EOF
COMPOSE_PROJECT_NAME=${PROJECT_NAME}
DJANGO_PORT=${DJANGO_PORT}
MYSQL_PORT=${MYSQL_PORT}
REDIS_PORT=${REDIS_PORT}
GROBID_PORT=${GROBID_PORT}
STACK_SUFFIX=${STACK_NAME}
EOF
    
    # Create necessary directories
    mkdir -p "mysql_${STACK_NAME}/lib"
    mkdir -p "static_${STACK_NAME}"
    mkdir -p "media_${STACK_NAME}"
    
    # Copy MySQL configs if needed
    if [ ! -f "mysql_${STACK_NAME}/my.cnf" ] && [ -f "mysql/my.cnf" ]; then
        cp mysql/my.cnf "mysql_${STACK_NAME}/my.cnf"
    fi
    
    if [ ! -f "mysql_${STACK_NAME}/.client.cnf" ] && [ -f "mysql/.client.cnf" ]; then
        cp mysql/.client.cnf "mysql_${STACK_NAME}/.client.cnf"
    fi
    
    # Create/update .env file for this stack
    if [ -f ".env.local" ]; then
        # Merge .env.local with stack-specific port configuration
        cat .env.local > ".env.${STACK_NAME}"
        echo "" >> ".env.${STACK_NAME}"
        echo "# Stack-specific port configuration" >> ".env.${STACK_NAME}"
        cat ".stacks/${STACK_NAME}.env" >> ".env.${STACK_NAME}"
        echo "✅ Created .env.${STACK_NAME} from .env.local with port config"
    elif [ ! -f ".env.${STACK_NAME}" ]; then
        cp ".stacks/${STACK_NAME}.env" ".env.${STACK_NAME}"
        echo "⚠️  Created .env.${STACK_NAME} with only port config (no .env.local found)"
    fi
    
else
    # Load existing configuration
    if [ -f ".stacks/${STACK_NAME}.env" ]; then
        source ".stacks/${STACK_NAME}.env"
        # Also update the main env file to ensure ports are set
        if [ -f ".env.local" ]; then
            cat .env.local > ".env.${STACK_NAME}"
            echo "" >> ".env.${STACK_NAME}"
            echo "# Stack-specific port configuration" >> ".env.${STACK_NAME}"
            cat ".stacks/${STACK_NAME}.env" >> ".env.${STACK_NAME}"
        fi
        echo "📋 Loaded configuration for stack: $STACK_NAME"
    else
        echo "⚠️  No configuration found for stack: $STACK_NAME"
        echo "   Available stacks:"
        ls -1 .stacks/*.env 2>/dev/null | sed 's/.stacks\///g' | sed 's/.env//g' | sed 's/^/   - /'
        exit 1
    fi
fi

# Run docker compose with environment variables
export COMPOSE_PROJECT_NAME=${PROJECT_NAME}
export DJANGO_PORT
export MYSQL_PORT
export REDIS_PORT
export GROBID_PORT
export STACK_SUFFIX=${STACK_NAME}

echo ""
echo "🐳 Running: docker compose -p ${PROJECT_NAME} -f compose.dev.yml --env-file .env.${STACK_NAME} $ACTION"
echo "   DJANGO_PORT=${DJANGO_PORT}, MYSQL_PORT=${MYSQL_PORT}, REDIS_PORT=${REDIS_PORT}, GROBID_PORT=${GROBID_PORT}"
echo ""

if [ "$ACTION" = "up" ]; then
    COMPOSE_PROJECT_NAME=${PROJECT_NAME} DJANGO_PORT=${DJANGO_PORT} MYSQL_PORT=${MYSQL_PORT} REDIS_PORT=${REDIS_PORT} GROBID_PORT=${GROBID_PORT} STACK_SUFFIX=${STACK_NAME} \
        docker compose -p ${PROJECT_NAME} -f compose.dev.yml --env-file ".env.${STACK_NAME}" $ACTION -d
else
    COMPOSE_PROJECT_NAME=${PROJECT_NAME} DJANGO_PORT=${DJANGO_PORT} MYSQL_PORT=${MYSQL_PORT} REDIS_PORT=${REDIS_PORT} GROBID_PORT=${GROBID_PORT} STACK_SUFFIX=${STACK_NAME} \
        docker compose -p ${PROJECT_NAME} -f compose.dev.yml --env-file ".env.${STACK_NAME}" $ACTION
fi

if [ "$ACTION" = "up" ]; then
    echo ""
    echo "🎉 Stack '$STACK_NAME' is running!"
    echo ""
    echo "🌐 Access points:"
    echo "   Django:  http://localhost:$DJANGO_PORT"
    echo "   MySQL:   localhost:$MYSQL_PORT"
    echo "   Redis:   localhost:$REDIS_PORT"
    echo "   GROBID:  http://localhost:$GROBID_PORT"
    echo ""
    echo "📝 Useful commands:"
    echo "   Logs:    $0 logs $BASE_PORT $STACK_NAME"
    echo "   Stop:    $0 down $BASE_PORT $STACK_NAME"
    echo "   Status:  $0 ps $BASE_PORT $STACK_NAME"
    echo ""
fi
