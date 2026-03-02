#!/bin/bash
# Sequential scraping script for multiple MICCAI conferences
# This will run each conference scrape one after the other

set -e  # Exit on error

# Check if the container suffix argument was provided
if [ -z "$1" ]; then
  echo "Error: Missing container suffix argument."
  echo "Usage: ./scrape.sh <environment-suffix>"
  echo "Example: ./scrape.sh DEV-STACK"
  exit 1
fi

CONTAINER_SUFFIX="$1"
CONTAINER_NAME="django-web-${CONTAINER_SUFFIX}"

TIMESTAMP=$(date '+%Y-%m-%d_%H-%M-%S')
LOG_DIR="/home/administrator/papersnitch/scraping_logs"
mkdir -p "$LOG_DIR"

echo "=========================================="
echo "Starting sequential conference scraping"
echo "Target Container: $CONTAINER_NAME"
echo "Started at: $(date)"
echo "=========================================="
echo ""

# Conference 1: MICCAI 2024
echo "[1/3] Starting MICCAI 2024 scrape..."
echo "URL: https://papers.miccai.org/miccai-2024/"
echo "Started at: $(date)"
sudo docker exec "$CONTAINER_NAME" python manage.py scrape_conference \
  "MICCAI 2024" \
  "https://papers.miccai.org/miccai-2024/" \
  --sync \
  2>&1 | tee "$LOG_DIR/miccai_2024_${TIMESTAMP}.log"
echo "MICCAI 2024 completed at: $(date)"
echo ""

# Conference 2: MICCAI 2023
echo "[2/3] Starting MICCAI 2023 scrape..."
echo "URL: https://conferences.miccai.org/2023/papers/"
echo "Started at: $(date)"
sudo docker exec "$CONTAINER_NAME" python manage.py scrape_conference \
  "MICCAI 2023" \
  "https://conferences.miccai.org/2023/papers/" \
  --sync \
  2>&1 | tee "$LOG_DIR/miccai_2023_${TIMESTAMP}.log"
echo "MICCAI 2023 completed at: $(date)"
echo ""

# Conference 3: MICCAI 2022
echo "[3/3] Starting MICCAI 2022 scrape..."
echo "URL: https://conferences.miccai.org/2022/papers/"
echo "Started at: $(date)"
sudo docker exec "$CONTAINER_NAME" python manage.py scrape_conference \
  "MICCAI 2022" \
  "https://conferences.miccai.org/2022/papers/" \
  --sync \
  2>&1 | tee "$LOG_DIR/miccai_2022_${TIMESTAMP}.log"
echo "MICCAI 2022 completed at: $(date)"
echo ""

echo "=========================================="
echo "All conference scraping completed!"
echo "Finished at: $(date)"
echo "=========================================="
echo ""
echo "Summary logs saved to: $LOG_DIR/"