# PaperSnitch: Automated Research Paper Reproducibility Assessment

<div align="center">

**An AI-powered system for comprehensive, automated evaluation of research paper reproducibility**

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.2.7-green.svg)](https://www.djangoproject.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.0.6-orange.svg)](https://langchain-ai.github.io/langgraph/)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue.svg)](https://www.docker.com/)

</div>

---

## Table of Contents

- [Rationale & Vision](#rationale--vision)
- [Key Features](#key-features)
- [Architecture Overview](#architecture-overview)
- [Prerequisites](#prerequisites)
- [Installation & Setup](#installation--setup)
- [Running the System](#running-the-system)
- [Configuration](#configuration)
- [Development Workflow](#development-workflow)
- [Troubleshooting](#troubleshooting)
- [Additional Documentation](#additional-documentation)
- [Acknowledgments](#acknowledgments)

---

## Rationale & Vision

### The Reproducibility Crisis

Reproducibility is a cornerstone of the scientific method, yet the research community — particularly in fields like medical image computing — faces a persistent **reproducibility crisis**. Studies have shown that a significant fraction of published results cannot be independently replicated, undermining trust in research outcomes and slowing scientific progress. At major venues like MICCAI, where hundreds of papers are accepted each year, understanding and improving reproducibility at scale is essential.

The root causes are:

- **Missing or incomplete code**: Source code is often not released, or released in an unusable state.
- **Undocumented datasets**: Training data, splits, and preprocessing steps are frequently omitted.
- **Ambiguous methodology**: Hyperparameters, architectural choices, and evaluation protocols are underspecified.
- **Inconsistent reporting**: Statistical procedures, hardware environments, and training details vary wildly in granularity.

Manual evaluation of reproducibility, such as the structured checklists adopted by MICCAI, does not scale. Human reviewers must spend considerable time per paper, assessments vary across reviewers, and the process cannot keep up with the volume of submissions at large conferences.

### Our Solution

**PaperSnitch** automates and standardizes the reproducibility assessment process. Given a research paper (PDF), the system extracts its full text via GROBID, classifies the paper type to determine which evaluation branches apply, and then runs three parallel assessment tracks — a reproducibility checklist, dataset documentation analysis, and code repository analysis — each powered by a Retrieval-Augmented Generation (RAG) pipeline that grounds every LLM judgment in evidence retrieved from the paper or codebase via semantic similarity. A final aggregation step merges all branch results into a single weighted score with a qualitative narrative.

The entire pipeline runs as an **8-node directed acyclic graph (DAG)** orchestrated by LangGraph, with database-backed state, distributed Celery workers, and full audit trails. Each node in the workflow is described in detail in the [Paper Processing Workflow](#paper-processing-workflow) section.

### Research Impact

- **Large-scale conference analysis**: Process hundreds of papers with consistent, repeatable evaluation.
- **Standardized criteria**: The same 20+10+6 criteria applied uniformly to every paper.
- **Actionable feedback**: Per-criterion evidence and specific recommendations for improving reproducibility.
- **Quantifiable metrics**: Numerical scores (overall, per-category, per-criterion) for comparison and benchmarking.
- **Research insights**: Understanding reproducibility trends across conferences, years, and research areas.

---

## Key Features

### Intelligent Analysis

- **Paper Type Classification**: Automatically classifies papers (choosing from dataset, method, both, theoretical or unknown), adapting the entire evaluation pipeline accordingly.
- **Adaptive Scoring**: Weights reproducibility categories (models, datasets, experiments) based on paper type — e.g., dataset papers weight dataset criteria at 40% and paper criteria at 60%, method papers weight code criteria at 60 and paper criteria at 40%.
- **Multi-Step RAG Evaluation**: For each of 20 reproducibility criteria, retrieves the top-3 most relevant paper sections via cosine similarity, then prompts the LLM for structured, evidence-based analysis.
- **Code Intelligence**: LLM-guided selection of reproducibility-critical files from repositories within a 100k-token budget, followed by mandatory embedding of all selected files for evidence-based code analysis.
- **Multi-Criterion Evaluation**: 20 reproducibility criteria (models, datasets, experiments) + 10 dataset documentation criteria + 6 code analysis components.

### Comprehensive Assessment

- **Paper-Level Analysis**: Evaluates mathematical descriptions, hyperparameter reporting, experimental protocols, statistical procedures, and ablation studies.
- **Code-Level Analysis**: Structured 6-component evaluation covering code completeness, dependency documentation, training code, evaluation scripts, pretrained checkpoints, and dataset split handling.
- **Dataset Documentation**: Assesses data collection methodology, annotation protocols, data format documentation, and ethical compliance.
- **Evidence-Based Scoring**: Every criterion evaluation is linked to specific paper sections (with similarity scores) or code snippets, providing full traceability.

### Scalable Workflow

- **Distributed Execution**: Celery workers running in parallel, coordinated via MySQL row-level locking (`SELECT ... FOR UPDATE SKIP LOCKED`).
- **Database-Backed**: All workflow states, node outputs, artifacts, and logs persisted in MariaDB.
- **Fault Tolerant**: Automatic retries with configurable limits, fail-fast propagation, stale claim cleanup, and progressive node skipping.
- **Token Tracking**: Per-node and per-workflow LLM token usage tracking with caching support across runs.

### Web Interface

- **PDF Upload**: Direct paper upload with automatic text extraction and section parsing via GROBID.
- **Conference Scraping**: Batch import papers from conference websites (e.g., MICCAI proceedings).
- **Analysis Dashboard**: Real-time workflow progress, per-node results, highlighted PDFs, and detailed criterion-level evaluations.
- **Admin Interface**: Rich Django admin with status badges, progress bars, DAG visualizations, artifact browsing, and structured log viewing.

---

## Architecture Overview

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

| Component               | Technology             | Purpose                                   |
| ----------------------- | ---------------------- | ----------------------------------------- |
| **Web Framework**       | Django 5.2.7           | HTTP server, ORM, admin interface         |
| **Workflow Engine**     | LangGraph 1.0.6        | DAG-based workflow orchestration          |
| **Task Queue**          | Celery 5.x             | Distributed async task execution          |
| **Message Broker**      | Redis 7                | Celery task queue backend                 |
| **Database**            | MariaDB 11.7           | Persistent storage (MySQL 8.0 compatible) |
| **Document Processing** | GROBID 0.8.0           | PDF → structured XML extraction           |
| **Web Scraping**        | Crawl4AI 0.7.6         | Conference website data extraction        |
| **Code Ingestion**      | GitIngest 0.3.1        | Repository cloning and file extraction    |
| **LLM Integration**     | OpenAI SDK 2.7.2       | gpt-5 API calls with structured outputs   |
| **Embeddings**          | text-embedding-3-small | 1536-dim semantic vectors for RAG         |

### Paper Processing Workflow

The analysis pipeline consists of 8 nodes executed as a directed acyclic graph (DAG):

```
                      ┌──────────────────────────────┐
                      │  Paper Type Classification   │
                      │  (dataset/method/both/       │
                      │   theoretical)               │
                      └──────────────┬───────────────┘
                                     │
                      ┌──────────────▼───────────────┐
                      │  Section Embeddings          │
                      │  (text-embedding-3-small)    │
                      └──────────────┬───────────────┘
                                     │
          ┌──────────────────────────┼──────────────────────────┐
          │                          │                          │
┌─────────▼──────────┐  ┌───────────▼───────────┐  ┌───────────▼────────────┐
│  Reproducibility   │  │  Dataset Docs Check   │  │  Code Availability     │
│  Checklist         │  │  (10 criteria)        │  │  Check                 │
│  (20 criteria)     │  │                       │  │                        │
└─────────┬──────────┘  └───────────┬───────────┘  └───────────┬────────────┘
          │                         │                          │
          │                         │              ┌───────────▼────────────┐
          │                         │              │  Code Embedding        │
          │                         │              │  (repo ingestion)      │
          │                         │              └───────────┬────────────┘
          │                         │                          │
          │                         │              ┌───────────▼────────────┐
          │                         │              │  Code Repository       │
          │                         │              │  Analysis (6 comp.)    │
          │                         │              └───────────┬────────────┘
          │                         │                          │
          └─────────────────────────┴──────────────────────────┘
                                    │
                     ┌──────────────▼───────────────┐
                     │  Final Aggregation           │
                     │  (weighted scoring + LLM     │
                     │   qualitative assessment)    │
                     └──────────────────────────────┘
```

**Node details:**

#### 1. Paper Type Classification

Classifies the paper into one of five categories — **dataset**, **method**, **both**, **theoretical**, or **unknown** — using LLM analysis of the full text. The model returns a structured response containing the predicted type, a confidence score, reasoning, and key evidence quotes. This classification determines all downstream routing: theoretical papers skip the dataset and code branches entirely, dataset papers skip code analysis, method papers skip dataset analysis, and unknown papers are treated as method papers.

#### 2. Section Embeddings

Extracts the paper's sections via regex-based header detection, filtering to sections between 100 and 8,000 characters. Each section is embedded as a single vector using OpenAI `text-embedding-3-small` (1,536 dimensions), and the resulting `PaperSectionEmbedding` records are stored in the database. These embeddings serve as the retrieval index for the downstream RAG-based evaluation nodes. Results are cached: if embeddings already exist from a previous run, this node returns immediately.

#### 3. Reproducibility Checklist

Evaluates **20 reproducibility criteria** (6 model criteria, 8 dataset criteria, 6 experiment criteria) adapted from the MICCAI reproducibility checklist. Each criterion has a pre-computed embedding stored in the database. For every criterion, the node performs a two-step RAG process:

1. **Retrieval** — computes cosine similarity between the criterion embedding and all paper section embeddings, selects the **top-3 sections** (minimum similarity threshold of 0.15).
2. **LLM analysis** — sends the retrieved sections along with the criterion description and paper metadata to an LLM call with a Pydantic structured output schema, producing a `present`/`absent` judgment, confidence score, evidence quote, and importance rating (`critical` / `important` / `optional`).

After all 20 LLM calls, a **programmatic aggregation** (no LLM) computes per-category scores (models, datasets, experiments) as the confidence-weighted fraction of satisfied criteria within each category, then applies **paper-type-adaptive weights** to produce a final weighted score. For example, method papers weight the datasets category at 20%, models at 45% and experiments at 35%

#### 4. Dataset Documentation Check

Evaluates **10 dataset documentation criteria** organized into three categories — Data Collection (3 criteria, weight 35%), Annotation (4 criteria, weight 40%), and Ethics & Availability (3 criteria, weight 25%). The RAG process is identical to the Reproducibility Checklist: top-3 section retrieval via cosine similarity, followed by per-criterion LLM analysis with structured output. Scores are aggregated programmatically per category with the above weights. **This node runs only for papers classified as "dataset" or "both"**.

#### 5. Code Availability Check

Searches for the paper's source code repository using a three-step strategy:

1. **Database check** — uses a previously stored `code_url` if available.
2. **Text extraction** — scans the paper text with a regex matching git repository URLs. If found, an LLM API call is performed to validate whether it's the one associated with the paper (to avoid using one just cited by the authors)
3. **LLM-powered online search** — if no URL is found in the text, we perform an LLM API call equipped with a web search tool, using the paper's title and abstract to search online for the code URL.

If URL found, verify it's actually accessible and it contains actual code by attempting to clone it.
**If no code is found, downstream code nodes are progressively skipped.** This node is skipped entirely for theoretical papers.

#### 6. Code Embedding

Clones the repository found by Code Availability Check and prepares it for evidence-based analysis:

1. **Initial ingestion** — clones the repo via GitIngest and extracts the README plus the full file tree with per-file token counts.
2. **LLM-based file selection** — the LLM receives the README and file tree, then selects a set of include patterns targeting reproducibility-critical files (e.g., main implementation, training scripts, configs) within a **100,000-token budget**, explicitly excluding comparison models, benchmarks, and visualization scripts.
3. **Selective re-ingestion** — re-clones with only the LLM-selected patterns.
4. **Chunking and embedding** — every selected file is split into chunks of up to **20,000 characters** (at word/line boundaries, no overlap), and **every chunk is mandatorily embedded** via `text-embedding-3-small` (1,536 dimensions). Embeddings are stored as `CodeFileEmbedding` records, including content hashes for integrity.

The clone is preserved on disk so that Code Repository Analysis can reuse it without re-cloning.

#### 7. Code Repository Analysis

Performs a structured **6-component analysis** of the repository using the code embeddings from the previous node as the evidence retrieval index:

1. **Research Methodology Detection** — the LLM identifies whether the project uses deep learning, machine learning, algorithmic, simulation, or data-analysis methodology and flags requirements (training, datasets, splits).
2. **Code Completeness** — checks for training code, evaluation scripts, and documented execution commands.
3. **Dependency Documentation** — checks for requirements files, environment specifications, and version pinning.
4. **Artifacts** — checks for pretrained checkpoints, model weights, and configuration files.
5. **Dataset Splits** — checks for train/validation/test split definitions and data loading code.
6. **Documentation** — checks for README quality, usage instructions, and example commands.

Each component is analyzed via a separate LLM call with Pydantic structured output. Component scores are then combined via **adaptive scoring**: maximum points per component vary based on the detected methodology (e.g., deep learning projects require training code, so `code_completeness` has a higher ceiling). The final code reproducibility score is normalized to a 0–100 scale.

#### 8. Final Aggregation

Merges all branch results into a single assessment. The node waits for all required dependencies (Reproducibility Checklist is mandatory; Code Repository Analysis and Dataset Documentation Check are optional depending on paper type and code availability), then:

1. **Weighted score computation** — combines component scores using availability-dependent weights:
   - All three components present: Checklist 50%, Code 20%, Dataset 30%.
   - Checklist + Code only: 60% / 40%.
   - Checklist + Dataset only: 60% / 40%.
   - Checklist only: 100%.
2. **Programmatic recommendation generation** — aggregates and deduplicates recommendations from all upstream nodes, prioritized by paper-type relevance and severity, limited to the top 7.
3. **LLM qualitative assessment** (single LLM call) — receives the pre-computed scores and all upstream analyses, and generates an executive summary (2–3 paragraphs), a strengths list, and a weaknesses list. The LLM is explicitly instructed not to recompute scores or generate recommendations — those are already determined programmatically.

---

## Web Interface

### Conferences

The conferences page lists all conferences that have been scraped, with aggregate statistics (number of papers, token usage, analysis completion rates).

### Conference Detail

Inside each conference: token usage statistics, a summary table of all papers with their analysis status and scores, and links to individual paper pages.

### Paper Detail

The paper page shows the DAG visualization of the selected analysis run at the top (with per-node status indicators), followed by the full list of all analysis runs performed on that paper. Completed analyses display criterion-level results, scores, and links to highlighted PDFs.

---

## Prerequisites

### Required Software

- **Docker**: 24.0+ with Docker Compose V2
- **Git**: 2.30+
- **Linux/macOS**: Tested on Ubuntu 22.04+ and macOS 13+

### API Keys

An OpenAI API key with access to:

- A **GPT model** compatible with the Responses API for structured analysis (e.g., `gpt-4o`, `gpt-5`)
- **text-embedding-3-small** for semantic embeddings (1536 dimensions)

### Hardware Recommendations

|                 | CPU     | RAM   | Disk       |
| --------------- | ------- | ----- | ---------- |
| **Minimum**     | 4 cores | 16 GB | 50 GB      |
| **Recommended** | 8 cores | 32 GB | 100 GB SSD |

---

## Installation & Setup

#### Step 1: Clone the Repository

```bash
git clone https://github.com/AImageLab-zip/papersnitch.git
cd papersnitch
```

#### Step 2: Environment Configuration

Copy `env_template` to `.env.local` and fill in passwords and API keys:

```bash
cp env_template .env.local
```

Required variables (see `env_template` for the full list):

```bash
# Django
DJANGO_SECRET_KEY=<generate-a-secret-key>
DJANGO_SETTINGS_MODULE=web.settings.development

# Database (must match MariaDB container vars)
DATABASE_PASSWORD=<choose-a-password>
MARIADB_ROOT_PASSWORD=<root-password>
MARIADB_PASSWORD=<same-as-DATABASE_PASSWORD>

# API Keys
OPENAI_API_KEY=<your-openai-key>
```

#### Step 3: Launch Development Stack

```bash
./create-dev-stack.sh up 8000 dev
```

This script:

1. Finds available ports starting from the requested base (Django, MySQL, Redis, GROBID)
2. Creates stack-isolated directories (`mysql_dev/`, `media_dev/`, `static_dev/`)
3. Generates `.env.dev` with the port configuration
4. Starts all Docker Compose services:

| Service          | Description                              |
| ---------------- | ---------------------------------------- |
| `django-web-dev` | Django development server (hot-reload)   |
| `mysql`          | MariaDB 11.7 database                    |
| `redis`          | Redis 7 (Celery broker & result backend) |
| `celery-worker`  | Celery worker (concurrency=8)            |
| `celery-beat`    | Celery Beat periodic task scheduler      |
| `grobid`         | GROBID 0.8.2 PDF parsing service         |

Database migrations and fixture loading run automatically on container startup via the entrypoint script.

#### Step 4: Create Admin User

```bash
docker exec -it django-web-dev uv run python manage.py createsuperuser
```

#### Step 5: Initialize Criteria Embeddings

Pre-compute embeddings for the reproducibility and dataset documentation criteria (one-time setup, requires OpenAI API key):

```bash
docker exec django-web-dev uv run python manage.py initialize_criteria_embeddings
```

This creates embeddings for 20 reproducibility checklist criteria and 10 dataset documentation criteria, stored in the database for semantic retrieval during analysis.

#### Step 6: Verify

Open `http://localhost:8000` in a browser. Log in with the superuser credentials. The admin interface is at `http://localhost:8000/admin/`.

---

## Running the System

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
```

### Running Analysis

#### Option 1: Web Interface

1. Navigate to `http://localhost:8000/analyze`
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

## Configuration

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

## Development Workflow

### Production Deployment

**Production mode** (Gunicorn behind Nginx with SSL):

```bash
cp env_template .env.prod
# Edit .env.prod with production values
docker compose -f compose.prod.yml up --build -d
```

Both modes automatically run database migrations and load fixtures on container startup (via the entrypoint scripts).

### Database Migrations

```bash
# Create migration
docker exec django-web-dev uv run manage.py makemigrations

# Apply migrations
docker exec django-web-dev uv run manage.py migrate

# Rollback
docker exec django-web-dev uv run manage.py migrate workflow_engine 0001
```

### Running Tests

```bash
# All tests
docker exec django-web-dev uv run manage.py test

# Specific app
docker exec django-web-dev uv run manage.py test webApp.tests

# With coverage
docker exec django-web-dev coverage run manage.py test
docker exec django-web-dev coverage html
```

---

## Troubleshooting

### Common Issues

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

## Additional Documentation

- **[Workflow implementation](WORKFLOW_ENGINE_DELIVERY.md)**
- **[Code analysis](app/webApp/services/CODE_REPRODUCIBILITY_ANALYSIS.md)**

---

## License

This project is licensed under the MIT License.

---

## Acknowledgments

- **GROBID**: PDF text extraction
- **LangGraph**: Workflow orchestration
- **OpenAI**: LLM APIs
- **Crawl4AI**: Conference scraping
- **GitIngest**: Code repository ingestion

---

<div align="center">

**Built with ❤️ for the research community**

_Making reproducibility the norm, not the exception_

</div>
