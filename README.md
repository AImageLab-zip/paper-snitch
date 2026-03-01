# PaperSnitch: Automated Research Paper Reproducibility Assessment

<div align="center">

**An AI-powered system for comprehensive, automated evaluation of research paper reproducibility**

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.2.7-green.svg)](https://www.djangoproject.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.0.6-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue.svg)](https://www.docker.com/)

</div>

---

## 📖 Table of Contents

- [Rationale & Vision](#-rationale--vision)
- [Key Features](#-key-features)
- [Architecture Overview](#-architecture-overview)
- [Prerequisites](#-prerequisites)
- [Installation & Setup](#-installation--setup)
- [Running the System](#-running-the-system)
- [How It Works](#-how-it-works)
- [Configuration](#-configuration)
- [Development Workflow](#-development-workflow)
- [Troubleshooting](#-troubleshooting)
- [Additional Documentation](#-additional-documentation)

---

## 🎯 Rationale & Vision

### The Reproducibility Crisis

The scientific community faces a **reproducibility crisis**: many published research papers cannot be independently replicated due to:

- **Missing or incomplete code repositories**
- **Unavailable or poorly documented datasets**
- **Ambiguous experimental protocols and hyperparameters**
- **Lack of detailed methodology descriptions**
- **Inconsistent reporting of statistical procedures**

Manual evaluation of paper reproducibility is:
- **Time-consuming**: Requires expert reviewers to spend hours per paper
- **Inconsistent**: Different reviewers may apply different standards
- **Not scalable**: Impossible to evaluate thousands of papers at conferences
- **Subjective**: Human bias in interpretation of criteria

### Our Solution

**PaperSnitch** automates the reproducibility assessment process using:

1. **Multi-Step Retrieval-Augmented Generation (RAG)**: Intelligently retrieves relevant paper sections for each evaluation criterion using semantic embeddings
2. **Structured LLM Analysis**: Uses gpt-5 with Pydantic schemas for deterministic, parseable outputs
3. **Programmatic Scoring**: Combines LLM-based text analysis with rules-based scoring algorithms
4. **Code Repository Analysis**: Automatically ingests, analyzes, and embeds source code to evaluate reproducibility artifacts
5. **Workflow Orchestration**: LangGraph-based DAG execution with database persistence and fault tolerance

### Research Impact

This system enables:
- **Large-scale conference analysis**: Process hundreds of papers efficiently
- **Consistent evaluation standards**: Same criteria applied uniformly
- **Actionable feedback**: Specific recommendations for improving reproducibility
- **Quantifiable metrics**: Numerical scores for comparison and benchmarking
- **Research insights**: Understanding reproducibility trends across domains

---

## ✨ Key Features

### 🤖 Intelligent Analysis
- **Paper Type Classification**: Automatically identifies papers as dataset/method/both/theoretical
- **Adaptive Scoring**: Weights criteria based on paper type (e.g., datasets more important for dataset papers)
- **Code Intelligence**: LLM-guided selection of reproducibility-critical files from repositories
- **Multi-Criterion Evaluation**: 20 reproducibility criteria + 10 dataset documentation criteria + 6 code analysis components

### 📊 Comprehensive Assessment
- **Paper-Level Analysis**: Evaluates mathematical descriptions, experimental protocols, statistical reporting
- **Code-Level Analysis**: Checks for training code, evaluation scripts, checkpoints, dependencies
- **Dataset Documentation**: Assesses data collection, annotation protocols, ethical compliance
- **Evidence-Based Scoring**: Links each evaluation to specific paper sections

### 🔄 Scalable Workflow
- **Distributed Execution**: Celery workers for parallel paper processing
- **Database-Backed**: MySQL persistence for all workflow states and results
- **Fault Tolerant**: Automatic retries, error isolation, partial result aggregation
- **Token Tracking**: Fine-grained cost accounting per workflow node

### 🌐 Web Interface
- **PDF Upload**: Direct paper upload with automatic text extraction (GROBID)
- **Conference Scraping**: Batch import papers from conference websites (MICCAI, etc.)
- **Analysis Dashboard**: View results, scores, and detailed criterion evaluations
- **User Management**: Profile-based tracking of analysis history

---

## 🏗️ Architecture Overview

### Technology Stack

```
┌─────────────────────────────────────────────────────────┐
│                     NGINX (Reverse Proxy)               │
│              Port 80/443 (SSL via Let's Encrypt)        │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┴───────────────┐
        │                            │
   ┌────▼──────┐              ┌──────▼─────┐
   │  Django   │              │   Static   │
   │   Web     │◄─────────────┤   Files    │
   │  (ASGI)   │              └────────────┘
   └─────┬─────┘
         │
    ┌────┴─────────────┬──────────────┐
    │                  │              │
┌───▼────┐      ┌──────▼──────┐  ┌───▼────────┐
│ Celery │      │   MySQL     │  │   Redis    │
│Workers │◄────►│  Database   │  │  (Broker)  │
│ (3-5)  │      │   (InnoDB)  │  └────────────┘
└───┬────┘      └─────────────┘
    │
    └──► GROBID Server (PDF → TEI-XML)
    └──► LLM APIs (OpenAI/LiteLLM)
```

### Core Components

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Web Framework** | Django 5.2.7 | HTTP server, ORM, admin interface |
| **Workflow Engine** | LangGraph 1.0.6 | DAG-based workflow orchestration |
| **Task Queue** | Celery 5.x | Distributed async task execution |
| **Message Broker** | Redis 7 | Celery task queue backend |
| **Database** | MariaDB 11.7 | Persistent storage (MySQL 8.0 compatible) |
| **Document Processing** | GROBID 0.8.0 | PDF → structured XML extraction |
| **Web Scraping** | Crawl4AI 0.7.6 | Conference website data extraction |
| **Code Ingestion** | GitIngest 0.3.1 | Repository cloning and file extraction |
| **LLM Integration** | OpenAI SDK 2.7.2 | gpt-5 API calls with structured outputs |
| **Embeddings** | text-embedding-3-small | 1536-dim semantic vectors for RAG |

### Workflow Version 8 (Current)

The analysis pipeline consists of 8 nodes executed as a directed acyclic graph (DAG):

```
                    ┌─────────────────────────────────┐
                    │ A. Paper Type Classification    │
                    │    (dataset/method/both/        │
                    │     theoretical)                │
                    └──────────────┬──────────────────┘
                                   │
                    ┌──────────────▼──────────────────┐
                    │ D. Section Embeddings           │
                    │    (text-embedding-3-small)     │
                    └──────────────┬──────────────────┘
                                   │
                ┌──────────────────┼──────────────────┐
                │                  │                  │
    ┌───────────▼──────────┐  ┌───▼────────────┐  ┌─▼─────────────────┐
    │ G. Reproducibility   │  │ H. Dataset     │  │ B. Code           │
    │    Checklist         │  │    Docs Check  │  │    Availability   │
    │    (20 criteria)     │  │    (10 crit.)  │  │    Check          │
    └───────────┬──────────┘  └───┬────────────┘  └─┬─────────────────┘
                │                  │                  │
                │                  │     ┌────────────▼──────────────┐
                │                  │     │ F. Code Embedding          │
                │                  │     │    (repo ingestion)        │
                │                  │     └────────────┬───────────────┘
                │                  │                  │
                │                  │     ┌────────────▼──────────────┐
                │                  │     │ C. Code Repository         │
                │                  │     │    Analysis               │
                │                  │     └────────────┬───────────────┘
                │                  │                  │
                └──────────────────┴──────────────────┴──────────────┐
                                                                       │
                                        ┌──────────────────────────────▼─┐
                                        │ I. Final Aggregation            │
                                        │    (weighted scoring + LLM)     │
                                        └─────────────────────────────────┘
```

**Node Responsibilities:**

- **Node A**: Classify paper type using title + abstract
- **Node B**: Search for code URLs in paper (GitHub, GitLab, etc.)
- **Node C**: Analyze code repository structure and reproducibility artifacts
- **Node D**: Generate embeddings for all paper sections
- **Node F**: Ingest code repository, select critical files, embed chunks
- **Node G**: Evaluate 20 reproducibility criteria via multi-step RAG
- **Node H**: Evaluate 10 dataset documentation criteria
- **Node I**: Aggregate scores, generate qualitative assessment

---

## 📋 Prerequisites

### Required Software

- **Docker**: 24.0+ with Docker Compose V2
- **Git**: 2.30+
- **Linux/macOS**: Tested on Ubuntu 22.04+ and macOS 13+

### API Keys

You'll need an OpenAI API key with access to:
- **gpt-5**: For structured analysis (`gpt-5-2024-11-20` or later)
- **text-embedding-3-small**: For semantic embeddings

### Hardware Recommendations

**Minimum:**
- 4 CPU cores
- 16 GB RAM
- 50 GB disk space

**Recommended:**
- 8 CPU cores
- 32 GB RAM
- 100 GB SSD storage

---

## 🚀 Installation & Setup

### Step 1: Clone the Repository

```bash
git clone https://github.com/yourusername/papersnitch.git
cd papersnitch
```

### Step 2: Environment Configuration

Create your local environment file:

```bash
cp .env.example .env.local
```

Edit `.env.local` with your settings:

```bash
# Database Configuration
MYSQL_ROOT_PASSWORD=your_secure_root_password
MYSQL_DATABASE=papersnitch
MYSQL_USER=papersnitch
MYSQL_PASSWORD=your_secure_password

# Django Configuration
DJANGO_SECRET_KEY=your_very_long_random_secret_key_here
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

# OpenAI API
OPENAI_API_KEY=sk-proj-your-api-key-here

# Celery Configuration
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# GROBID Configuration (optional - uses public server by default)
GROBID_SERVER=https://cloud.science-miner.com/grobid

# Stack Configuration (auto-generated by create-dev-stack.sh)
STACK_SUFFIX=dev
HOST_PROJECT_PATH=/home/youruser/papersnitch
```

**Security Note:** Never commit `.env.local` to version control!

### Step 3: Launch Development Stack

Use the provided script to start all services:

```bash
./create-dev-stack.sh up 8000 dev
```

**What this does:**
1. Finds available ports (8000 for Django, 3307 for MySQL, 6380 for Redis, 8071 for GROBID)
2. Creates stack-specific directories (`mysql_dev`, `media_dev`, `static_dev`)
3. Generates `.env.dev` with port configuration
4. Starts Docker Compose services:
   - `django-web-dev`: Django application server
   - `mysql`: MariaDB 11.7 database
   - `redis`: Redis message broker
   - `celery-worker`: Background task processor
   - `celery-beat`: Periodic task scheduler

**Expected output:**
```
🚀 Starting development stack: dev
📍 Base port requested: 8000

✅ Available ports found:
   Django:  8000
   MySQL:   3307
   Redis:   6380
   GROBID:  8071

✅ Created .env.dev from .env.local with port config
🐳 Starting containers...
```

### Step 4: Database Initialization

Wait for database to be healthy, then run migrations:

```bash
# Check if MySQL is ready
docker exec mysql-dev mariadb -u papersnitch -ppapersnitch -e "SELECT 1"

# Run Django migrations
docker exec django-web-dev python manage.py migrate

# Create superuser for admin access
docker exec -it django-web-dev python manage.py createsuperuser
```

### Step 5: Initialize Criteria Embeddings

Pre-compute embeddings for reproducibility criteria (one-time setup):

```bash
docker exec django-web-dev python manage.py initialize_criteria_embeddings
```

**What this does:**
- Creates embeddings for 20 reproducibility checklist criteria
- Creates embeddings for 10 dataset documentation criteria
- Stores in database for semantic retrieval during analysis

### Step 6: Verify Installation

Access the web interface:

```
http://localhost:8000
```

Check service health:

```bash
# View all running containers
docker ps

# Check Django logs
docker logs django-web-dev

# Check Celery worker logs
docker logs celery-worker-dev
```

---

## 🎮 Running the System

### Starting/Stopping Services

```bash
# Start the stack
./create-dev-stack.sh up 8000 dev

# Stop the stack (preserves data)
./create-dev-stack.sh stop 8000 dev

# Stop and remove containers (preserves data)
./create-dev-stack.sh down 8000 dev

# View logs (all services)
./create-dev-stack.sh logs 8000 dev

# View specific service logs
docker logs -f django-web-dev
docker logs -f celery-worker-dev
```

### Running Analysis

#### Option 1: Web Interface

1. Navigate to `http://localhost:8000`
2. Log in with superuser credentials
3. Upload a PDF or paste arXiv URL
4. Click "Analyze Reproducibility"
5. View results in real-time as workflow executes

#### Option 2: Django Admin

1. Navigate to `http://localhost:8000/admin`
2. Go to **Papers** → Add Paper
3. Upload PDF and fill metadata
4. Go to **Workflow Runs** → Add Workflow Run
5. Select paper and workflow definition
6. Save to trigger analysis

#### Option 3: Django Shell

```bash
docker exec -it django-web-dev python manage.py shell
```

```python
from webApp.models import Paper, WorkflowDefinition
from webApp.services.workflow_orchestrator import WorkflowOrchestrator

# Get paper and workflow
paper = Paper.objects.first()
workflow_def = WorkflowDefinition.objects.get(
    name="paper_processing_with_reproducibility", 
    version=8
)

# Create workflow run
orchestrator = WorkflowOrchestrator()
workflow_run = orchestrator.create_workflow_run(
    workflow_definition=workflow_def,
    paper=paper,
    context_data={
        "model": "gpt-5-2024-11-20",
        "force_reprocess": False
    }
)

print(f"Workflow run created: {workflow_run.id}")
```

### Monitoring Workflows

View workflow progress in Django admin at:
```
http://localhost:8000/admin/workflow_engine/workflowrun/
```

Or query the database:

```bash
docker exec -it mysql-dev mariadb -u papersnitch -ppapersnitch papersnitch

# Check workflow status
SELECT id, status, started_at, completed_at 
FROM workflow_runs 
ORDER BY created_at DESC LIMIT 10;

# Check node status
SELECT node_id, status, duration_seconds, input_tokens, output_tokens
FROM workflow_nodes 
WHERE workflow_run_id = 'your-workflow-run-id'
ORDER BY started_at;
```

---

## 🔍 How It Works

### High-Level Overview

PaperSnitch uses an **8-node DAG workflow** to comprehensively evaluate research paper reproducibility:

1. **Paper Type Classification (Node A)**: Determines if paper is dataset/method/both/theoretical using LLM analysis of title and abstract

2. **Section Embeddings (Node D)**: Generates semantic embeddings for all paper sections (abstract, intro, methods, results, etc.) using `text-embedding-3-small`

3. **Parallel Analysis**:
   - **Reproducibility Checklist (Node G)**: Evaluates 20 criteria using multi-step RAG (retrieves relevant sections per criterion, then analyzes with LLM)
   - **Dataset Documentation (Node H)**: Evaluates 10 dataset-specific criteria
   - **Code Workflow (Nodes B→F→C)**:
     - **Node B**: Searches for code repository URLs
     - **Node F**: Ingests repo, LLM selects critical files, embeds all file chunks
     - **Node C**: Analyzes repository structure, artifacts, and reproducibility

4. **Final Aggregation (Node I)**: Combines all scores with adaptive weighting, generates qualitative assessment

### Key Technical Innovations

**Multi-Step RAG for Criterion Evaluation:**
```python
# For each criterion:
1. Retrieve top-3 most relevant paper sections via cosine similarity
2. Provide sections + criterion description to LLM
3. Get structured analysis (present/absent, confidence, evidence)
4. Aggregate 20 criterion analyses → category scores → overall score
```

**Adaptive Code Scoring:**
```python
# Scoring adapts to research methodology
if methodology == "deep_learning":
    # Requires: training code + checkpoints + datasets
    max_score_components = {
        "code_completeness": 3.0,
        "artifacts": 2.5,  # Checkpoints critical
        "dataset_splits": 2.0
    }
elif methodology == "theoretical":
    # Requires: implementation code only
    max_score_components = {
        "code_completeness": 2.5,
        "artifacts": 0.5,  # Checkpoints not applicable
        "dataset_splits": 0.5
    }
```

**LLM-Guided Code File Selection:**
```python
# Instead of embedding entire repository:
1. Extract README + file tree
2. LLM selects reproducibility-critical files (within 100k token budget)
3. Only embed selected files (20k char chunks)
4. Use embeddings for evidence-based component analysis
```

For detailed technical documentation, see [TECHNICAL_DESCRIPTION_FOR_PAPER.md](TECHNICAL_DESCRIPTION_FOR_PAPER.md).

---

## ⚙️ Configuration

### Environment Variables

Key variables in `.env.local`:

```bash
# OpenAI API
OPENAI_API_KEY=sk-proj-...
DEFAULT_LLM_MODEL=gpt-5-2024-11-20
EMBEDDING_MODEL=text-embedding-3-small

# Database
MYSQL_DATABASE=papersnitch
MYSQL_USER=papersnitch
MYSQL_PASSWORD=your_password

# Celery
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_CONCURRENCY=8  # Tasks per worker
CELERY_MAX_TASKS_PER_CHILD=1  # Restart after 1 task

# Security
DJANGO_SECRET_KEY=...
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
```

### Workflow Customization

Modify criteria or scoring weights in Django admin or via shell:

```python
from webApp.models import ReproducibilityChecklistCriterion

criterion = ReproducibilityChecklistCriterion.objects.get(
    criterion_id="mathematical_description"
)
criterion.description = "Updated description..."
criterion.save()

# Regenerate embedding after modification
from openai import OpenAI
client = OpenAI()
response = client.embeddings.create(
    model="text-embedding-3-small",
    input=f"{criterion.criterion_name}\n{criterion.description}"
)
criterion.embedding = response.data[0].embedding
criterion.save()
```

---

## 👨‍💻 Development Workflow

### Running Multiple Stacks

Support for parallel development environments:

```bash
# Main dev stack on port 8000
./create-dev-stack.sh up 8000 dev

# Feature branch on port 8001
./create-dev-stack.sh up 8001 feature-x

# Personal stack on port 8002
./create-dev-stack.sh up 8002 my-name

# Each stack has isolated database, media files, and Redis
```

### Hot Reload

Django auto-reloads on code changes via Docker Compose watch mode.

### Database Migrations

```bash
# Create migration
docker exec django-web-dev python manage.py makemigrations

# Apply migrations
docker exec django-web-dev python manage.py migrate

# Rollback
docker exec django-web-dev python manage.py migrate workflow_engine 0001
```

### Running Tests

```bash
# All tests
docker exec django-web-dev python manage.py test

# Specific app
docker exec django-web-dev python manage.py test webApp.tests

# With coverage
docker exec django-web-dev coverage run manage.py test
docker exec django-web-dev coverage html
```

---

## 🐛 Troubleshooting

### Common Issues

**Port Already in Use:**
```bash
# Use different port
./create-dev-stack.sh up 8001 dev
```

**MySQL Connection Refused:**
```bash
# Check MySQL health
docker exec mysql-dev mariadb -u papersnitch -ppapersnitch -e "SELECT 1"

# Restart MySQL
docker restart mysql-dev
```

**Celery Workers Not Processing:**
```bash
# Check worker status
docker exec django-web-dev celery -A web inspect active

# Restart workers
docker restart celery-worker-dev
```

**OpenAI Rate Limits:**
```bash
# Reduce concurrency in compose.dev.yml:
command: celery -A web worker --concurrency=2
```

**Out of Memory:**
```bash
# Increase Docker memory limit (Docker Desktop → Settings → Resources)
# Or reduce Celery concurrency
command: celery -A web worker --concurrency=2 --max-tasks-per-child=1
```

### Debug Scripts

```bash
# Check retrieval for specific paper
python debug_aspect_retrieval.py --paper-id 123 --aspect methodology

# List papers with embeddings
python debug_aspect_retrieval.py --list-papers

# Verify workflow installation
python verify_workflow_installation.py
```

---

## 📚 Additional Documentation

- **[TECHNICAL_DESCRIPTION_FOR_PAPER.md](TECHNICAL_DESCRIPTION_FOR_PAPER.md)**: Complete technical specification for academic paper
- **[WORKFLOW_ENGINE_DELIVERY.md](WORKFLOW_ENGINE_DELIVERY.md)**: Workflow engine implementation details
- **[CODE_REPRODUCIBILITY_ANALYSIS.md](app/webApp/services/CODE_REPRODUCIBILITY_ANALYSIS.md)**: Code analysis node documentation
- **[DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md)**: Production deployment guide
- **[DOMAIN_SETUP_GUIDE.md](DOMAIN_SETUP_GUIDE.md)**: SSL and domain configuration

---

## 📄 License

This project is licensed under the MIT License.

---

## 🙏 Acknowledgments

- **GROBID**: PDF text extraction
- **LangGraph**: Workflow orchestration
- **OpenAI**: LLM APIs
- **Crawl4AI**: Conference scraping
- **GitIngest**: Code repository ingestion

---

<div align="center">

**Built with ❤️ for the research community**

*Making reproducibility the norm, not the exception*

</div>
