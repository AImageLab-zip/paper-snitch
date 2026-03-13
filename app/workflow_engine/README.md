# Workflow Engine

A database-backed DAG workflow orchestration system for Django, designed to run complex multi-step paper analysis pipelines using Celery, MySQL row-level locking, and LangGraph.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
  - [Core Concepts](#core-concepts)
  - [Data Model](#data-model)
  - [Execution Flow](#execution-flow)
  - [Distributed Task Claiming](#distributed-task-claiming)
  - [Dependency Resolution and Parallelism](#dependency-resolution-and-parallelism)
  - [Conditional Routing and Progressive Skipping](#conditional-routing-and-progressive-skipping)
  - [Error Handling, Retries, and Fail-Fast](#error-handling-retries-and-fail-fast)
  - [Token Usage Tracking](#token-usage-tracking)
  - [LangGraph Integration](#langgraph-integration)
  - [Caching and Reprocessing](#caching-and-reprocessing)
- [Components Reference](#components-reference)
- [Setup and Installation](#setup-and-installation)
  - [Prerequisites](#prerequisites)
  - [Environment Configuration](#environment-configuration)
  - [Running with Docker Compose (Recommended)](#running-with-docker-compose-recommended)
  - [Database Migrations](#database-migrations)
  - [Creating the Workflow Definition](#creating-the-workflow-definition)
  - [Celery Configuration](#celery-configuration)
- [Usage](#usage)
  - [Starting a Workflow](#starting-a-workflow)
  - [Checking Workflow Status](#checking-workflow-status)
  - [Batch Processing](#batch-processing)
  - [Programmatic Usage](#programmatic-usage)
- [Monitoring and Administration](#monitoring-and-administration)
- [Creating Custom Workflows](#creating-custom-workflows)
- [Utility Functions](#utility-functions)

---

## Overview

The Workflow Engine is a Django app (`workflow_engine`) that orchestrates multi-step analysis pipelines as directed acyclic graphs (DAGs). Each workflow is defined as a graph of nodes (tasks) with edges (dependencies), stored in MySQL, and executed by Celery workers.

The primary use case is the **Paper Processing Pipeline**: given a scientific paper, the engine runs a sequence of analysis steps — type classification, embedding computation, multiple evaluations, and final scoring — coordinating parallel branches, conditional logic, and LLM-powered nodes through a single unified execution framework.

Key design goals:

- **Reliability**: All state persisted in MySQL. Workers can crash and recover without losing progress.
- **Scalability**: Multiple Celery workers claim tasks via `SELECT ... FOR UPDATE SKIP LOCKED`, preventing duplicate execution.
- **Observability**: Every node execution produces structured logs, artifacts, and token usage metrics.
- **Flexibility**: Workflows are defined as JSON DAG structures, supporting both synchronous Celery tasks and asynchronous LangGraph agents.

---

## Features

- **DAG-based workflow definitions** — Define workflows as directed acyclic graphs with nodes and edges, stored as JSON in the database.
- **Distributed execution** — MySQL row-level locking (`SELECT ... FOR UPDATE SKIP LOCKED`) ensures safe multi-worker task claiming with no duplicate work.
- **Parallel branch execution** — Nodes without dependencies run concurrently across workers.
- **Conditional routing** — Workflow paths adapt based on intermediate results (e.g., skip code analysis for theoretical papers).
- **Progressive skipping** — When a branch determines downstream work is unnecessary, it marks subsequent nodes as `skipped` without failing.
- **Automatic retries** — Failed nodes are retried up to a configurable `max_retries` limit before permanent failure.
- **Fail-fast propagation** — On permanent failure, sibling and downstream nodes are cancelled immediately.
- **Full audit trail** — Structured logs (`NodeLog`), artifacts (`NodeArtifact`), and per-node token usage tracking.
- **Multiple runs per paper** — Re-run workflows on the same paper with auto-incremented `run_number`.
- **LangGraph integration** — Async LangGraph `StateGraph` workflows run within the engine's lifecycle management.
- **Token usage aggregation** — Track LLM input/output tokens per node and per workflow run.
- **Result caching** — Nodes can reuse results from previous runs, copying token counts to preserve cost accounting.
- **Auto-generated DAG diagrams** — Graphviz visualizations generated on workflow definition save via Django signals.

---

## Architecture

### Core Concepts

| Concept                | Description                                                                                                |
| ---------------------- | ---------------------------------------------------------------------------------------------------------- |
| **WorkflowDefinition** | A reusable template that describes a DAG of nodes and edges. Versioned and toggleable.                     |
| **WorkflowRun**        | A single execution of a workflow for a specific `Paper`. Tracks status, timing, token usage, and I/O data. |
| **WorkflowNode**       | An individual task within a run. Tracks execution state, retry count, worker claims, and results.          |
| **NodeArtifact**       | An output produced by a node — inline JSON data, file references, URLs, or database record pointers.       |
| **NodeLog**            | A structured log entry tied to a specific node                                                             |

### Data Model

```
WorkflowDefinition (template)
 ├── dag_structure: JSON { nodes: [...], edges: [...] }
 ├── version, is_active
 └── dag_diagram (auto-generated PNG)

WorkflowRun (instance)
 ├── workflow_definition (FK)
 ├── paper (FK → Paper)
 ├── status: pending | running | completed | failed | cancelled
 ├── run_number (auto-incremented per paper)
 ├── input_data / output_data (JSON)
 ├── total_input_tokens / total_output_tokens
 └── nodes → [WorkflowNode, ...]

WorkflowNode (task)
 ├── node_id, node_type, handler (dotted Python path)
 ├── status: pending | ready | claimed | running | completed | failed | skipped | cancelled
 ├── attempt_count / max_retries
 ├── claimed_by / claimed_at / claim_expires_at
 ├── input_data / output_data (JSON)
 ├── input_tokens / output_tokens
 ├── artifacts → [NodeArtifact, ...]
 └── logs → [NodeLog, ...]
```

### Execution Flow

```
1. A WorkflowRun is created for a Paper
        ↓
2. All nodes are initialized from the WorkflowDefinition's dag_structure
        ↓
3. Nodes with no upstream dependencies are marked as READY
        ↓
4. Celery Beat triggers workflow_scheduler_task every 10 seconds
        ↓
5. The scheduler claims READY nodes via SELECT ... FOR UPDATE SKIP LOCKED
        ↓
6. Each claimed node is dispatched as a Celery task (execute_node_task)
        ↓
7. The NodeExecutor loads the handler, prepares input context, and runs it
        ↓
8. On success: node marked COMPLETED, downstream dependencies checked,
   newly-ready nodes marked READY → cycle continues
        ↓
9. On failure: retry if attempts remain, otherwise mark FAILED,
   cancel siblings, skip dependents
        ↓
10. When all nodes reach terminal states: WorkflowRun marked
    COMPLETED or FAILED
```

### Distributed Task Claiming

The engine uses MySQL's `SELECT ... FOR UPDATE SKIP LOCKED` to safely distribute work across multiple Celery workers:

1. The `workflow_scheduler_task` (run by Celery Beat every 10s) scans for nodes in `ready` status.
2. It uses `select_for_update(skip_locked=True)` inside a transaction — the database locks the selected row and skips any rows already locked by other transactions.
3. The claimed node's status is updated to `claimed`, with the worker hostname and an expiration timestamp.
4. If a worker crashes and its claim expires, the node reverts to `ready` on the next scheduler pass or via the `cleanup_stale_claims_task`.

This ensures **exactly-once execution** semantics without external coordination services.

### Dependency Resolution and Parallelism

When a node completes, the orchestrator scans all `pending` nodes in the same run. For each, it checks whether all upstream dependencies (derived from the DAG edges) are in `completed` or `skipped` status. If so, the node transitions to `ready` and becomes claimable.

This means independent branches of the DAG naturally execute in parallel across workers. For example, in the paper processing pipeline:

```
section_embeddings
      ↓ (fan-out)
      ├── dataset_documentation_check
      ├── reproducibility_checklist
      └── code_availability_check
            ↓
      (fan-in → final_aggregation)
```

All three evaluation branches start as soon as `section_embeddings` completes, and `final_aggregation` waits until all branches finish.

### Conditional Routing and Progressive Skipping

The LangGraph integration supports conditional routing. For example, after computing section embeddings, the paper type determines which branches activate:

- **Theoretical papers**: Only `reproducibility_checklist` runs. Dataset and code branches are skipped.
- **Method papers**: Both `reproducibility_checklist` and the code branch runs. Only the dataset branch is skipped
- **Dataset papers**: Both `reproducibility_checklist` and the dataset branch runs. Only the code branch is skipped

Within branches, nodes can implement **progressive skipping**: if `code_availability_check` finds no code, it marks `code_embedding` and `code_repository_analysis` as `skipped` rather than failing, so the workflow continues to `final_aggregation`.

### Error Handling, Retries, and Fail-Fast

Each `WorkflowNode` has a `max_retries` setting (typically 2-3). When a node fails:

1. If `attempt_count < max_retries`, the node resets to `ready` for another attempt.
2. If retries are exhausted, the node is permanently `failed`.
3. On permanent failure, **fail-fast** kicks in:
   - All sibling nodes (running, claimed, ready, pending) in the same run are `cancelled`.
   - All downstream dependent nodes are recursively marked `skipped`.
   - The `WorkflowRun` status is set to `failed`.

### Token Usage Tracking

Every node tracks LLM token consumption:

- `input_tokens` / `output_tokens` on each `WorkflowNode`.
- `was_cached` flag indicates if tokens were copied from a previous run's result.
- On workflow completion, `aggregate_workflow_run_tokens()` sums all node tokens into the `WorkflowRun` totals.

### LangGraph Integration

The engine supports two execution modes:

1. **Sync handlers** (Celery tasks) — Standard Python functions invoked directly by `NodeExecutor`.
2. **Async handlers** (LangGraph) — Async functions run via `asyncio.run()`. The `PaperProcessingWorkflow` class builds a LangGraph `StateGraph`, compiles it, and runs it asynchronously. The `AsyncWorkflowOperations` class wraps all database operations with `sync_to_async` for thread-safe DB access.

The `PaperProcessingState` carries data between LangGraph nodes, including the `workflow_run_id`, `paper_id`, OpenAI client, and accumulated results from upstream nodes.

### Caching and Reprocessing

Nodes can check for cached results from previous successful runs of the same paper (via `AsyncWorkflowOperations.check_previous_analysis()`). When reusing cached data:

- The node copies output data from the previous run.
- Token counts are copied with `was_cached=True`.
- Set `force_reprocess=True` in workflow input data to bypass caching.

---

## Components Reference

### File Structure

```
workflow_engine/
├── models.py                  # Data models (WorkflowDefinition, WorkflowRun, WorkflowNode, NodeArtifact, NodeLog)
├── tasks.py                   # Celery tasks (scheduler, executor, cleanup, start_workflow)
├── handlers.py                # Example/placeholder node handlers
├── admin.py                   # Django admin configuration with rich UI
├── signals.py                 # Auto-generate DAG diagrams on WorkflowDefinition save
├── utils.py                   # Utility functions (get/create runs, retry, stats, cleanup, visualization)
├── apps.py                    # Django AppConfig
├── examples.py                # Integration examples (views, signals, shell usage)
├── requirements.txt           # Optional dependencies (graphviz, flower, langgraph)
├── services/
│   ├── orchestrator.py        # WorkflowOrchestrator (sync) and NodeExecutor
│   ├── async_orchestrator.py  # AsyncWorkflowOperations (async wrappers for LangGraph)
│   └── langgraph_integration.py  # LangGraph base classes and helpers
├── management/commands/
│   ├── create_workflow.py     # Create/update the default workflow definition
│   ├── start_workflow.py      # Start a workflow for a single paper
│   ├── start_workflow_batch.py  # Start workflows for multiple papers
│   └── workflow_status.py     # Check status of a workflow run
└── migrations/                # Database migrations
```

### Celery Tasks

| Task                        | Schedule                | Purpose                                                       |
| --------------------------- | ----------------------- | ------------------------------------------------------------- |
| `workflow_scheduler_task`   | Every 10 seconds (Beat) | Claims ready nodes and dispatches them to `execute_node_task` |
| `execute_node_task`         | On-demand (dispatched)  | Executes a single node via `NodeExecutor`                     |
| `start_workflow_task`       | On-demand               | Creates a workflow run and sets it to `running`               |
| `cleanup_stale_claims_task` | Every 5 minutes (Beat)  | Resets nodes whose claims have expired back to `ready`        |

### Services

| Class                     | Module (services/)      | Purpose                                                                                      |
| ------------------------- | ----------------------- | -------------------------------------------------------------------------------------------- |
| `WorkflowOrchestrator`    | `orchestrator.py`       | Workflow lifecycle: create runs, claim tasks, mark completion/failure, dependency resolution |
| `NodeExecutor`            | `orchestrator.py`       | Execute a node's handler function with input context preparation                             |
| `AsyncWorkflowOperations` | `async_orchestrator.py` | Async wrappers for DB operations (used by LangGraph nodes)                                   |

---

## Setup and Installation

### Creating the Workflow Definition

Before starting any workflow, register the DAG definition in the database:

```bash
docker compose -f compose.dev.yml exec django-web-dev uv run python manage.py
```

This creates the `pdf_analysis_pipeline` workflow definition with 10 nodes and their dependency edges. A DAG diagram (PNG) is auto-generated if Graphviz is installed (it is included in the Docker image).

The actual production workflow (`paper_processing_with_reproducibility`, v9) is registered dynamically by the `PaperProcessingWorkflow` class in `webApp/services/graphs/paper_processing_workflow.py` when workflows are first executed.

### Celery Configuration

The Celery Beat schedule is already configured in `web/celery.py`:

```python
app.conf.beat_schedule = {
    'workflow-scheduler': {
        'task': 'workflow_engine.tasks.workflow_scheduler_task',
        'schedule': 10.0,  # Every 10 seconds
    },
    'cleanup-stale-claims': {
        'task': 'workflow_engine.tasks.cleanup_stale_claims_task',
        'schedule': crontab(minute='*/5'),  # Every 5 minutes
    },
}
```

Both the worker and beat scheduler start automatically as separate Docker containers. No additional configuration is needed.

---

## Usage

### Starting a Workflow

**Single paper** via management command:

```bash
docker compose -f compose.dev.yml exec django-web-dev \
  uv run python manage.py start_workflow paper_processing_with_reproducibility <paper_id>
```

The command checks for already-running workflows on the paper and prevents duplicates. Optional `--input` flag accepts a JSON string of parameters.

**Via Celery task** (programmatic):

```python
from workflow_engine.tasks import start_workflow_task

result = start_workflow_task.delay(
    workflow_name='paper_processing_with_reproducibility',
    paper_id=123,
    input_data={'force_reprocess': True},
    user_id=1
)
```

### Checking Workflow Status

```bash
docker compose -f compose.dev.yml exec django-web-dev \
  uv run python manage.py workflow_status <workflow_run_uuid>
```

Output includes:

- Workflow run metadata (status, paper, timestamps, duration)
- Progress summary (total/completed/running/pending/failed nodes)
- Per-node status with individual durations and error messages

**Programmatic check:**

```python
from workflow_engine.models import WorkflowRun

run = WorkflowRun.objects.get(id='<uuid>')
progress = run.get_progress()
print(f"Progress: {progress['percentage']}%")
print(f"Status: {run.status}")
```

### Batch Processing

Start workflows for multiple papers at once:

```bash
# All papers
docker compose -f compose.dev.yml exec django-web-dev \
  uv run python manage.py start_workflow_batch paper_processing_with_reproducibility --all

# Specific papers
docker compose -f compose.dev.yml exec django-web-dev \
  uv run python manage.py start_workflow_batch paper_processing_with_reproducibility --paper-ids "1,2,3,42"

# By conference
docker compose -f compose.dev.yml exec django-web-dev \
  uv run python manage.py start_workflow_batch paper_processing_with_reproducibility --conference "MICCAI 2024"

# Dry run (preview without executing)
docker compose -f compose.dev.yml exec django-web-dev \
  uv run python manage.py start_workflow_batch paper_processing_with_reproducibility --all --dry-run
```

Options:

- `--skip-running` (default: True): Skip papers that already have a running workflow.
- `--dry-run`: Show which papers would be processed without starting any workflows.

### Programmatic Usage

**Create and start a workflow:**

```python
from workflow_engine.services.orchestrator import WorkflowOrchestrator
from webApp.models import Paper

paper = Paper.objects.get(id=123)
orchestrator = WorkflowOrchestrator()

workflow_run = orchestrator.create_workflow_run(
    workflow_name='pdf_analysis_pipeline',
    paper=paper,
    input_data={'force_reprocess': False},
    user=request.user
)

workflow_run.status = 'running'
workflow_run.started_at = timezone.now()
workflow_run.save(update_fields=['status', 'started_at'])
```

**Get or reuse an existing workflow:**

```python
from workflow_engine.utils import get_or_create_workflow_for_paper

# Returns existing running workflow or creates a new one
workflow_run = get_or_create_workflow_for_paper(paper, force_new=False)
```

**Access results:**

```python
from workflow_engine.utils import get_workflow_results

results = get_workflow_results(workflow_run)
print(results['final_score'])
print(results['node_outputs']['compute_score']['output'])
```

**Retry failed nodes:**

```python
from workflow_engine.utils import retry_failed_nodes

count = retry_failed_nodes(workflow_run)
print(f"Reset {count} nodes for retry")
```

---

## Monitoring and Administration

### Django Admin

Access the admin at `/admin/workflow_engine/`. The admin interface provides:

- **WorkflowDefinition**: View DAG structure, node count, text/image DAG visualization.
- **WorkflowRun**: Status badges (color-coded), progress bars, paper links, duration, highlighted PDF links.
- **WorkflowNode**: Per-node status, attempt counts, claimed worker, input/output data, error details.
- **NodeArtifact**: Browse artifacts with size display and node links.
- **NodeLog**: Filterable logs with level badges and timestamps.

### System Statistics

```python
from workflow_engine.utils import get_workflow_statistics

stats = get_workflow_statistics()
# Returns: total_runs, active_runs, completed_runs, failed_runs,
#          last_24h activity, node counts, avg_duration_seconds
```

### Active Workflows

```python
from workflow_engine.utils import get_active_workflows

active = get_active_workflows(limit=10)
# Or filter by paper:
active = get_active_workflows(paper=my_paper)
```

---

## Creating Custom Workflows

### 1. Define Handler Functions

Create handler functions that accept a context dict and return a result dict:

```python
# my_app/handlers.py

def my_custom_handler(context):
    """
    Handler function for a workflow node.

    Args:
        context: dict with keys:
            - node: WorkflowNode instance
            - paper: Paper instance
            - node_input: Node-specific input data
            - upstream_outputs: Dict of outputs from dependency nodes
            - workflow_input: Workflow-level input data

    Returns:
        dict: Output data stored on the node
    """
    paper = context['paper']
    upstream = context.get('upstream_outputs', {})

    result = do_analysis(paper)

    # Optionally create artifacts
    from workflow_engine.models import NodeArtifact
    NodeArtifact.objects.create(
        node=context['node'],
        artifact_type='inline',
        name='analysis_result',
        inline_data=result
    )

    return result
```

### 2. Define the DAG Structure

```python
from workflow_engine.models import WorkflowDefinition

dag_structure = {
    'nodes': [
        {
            'id': 'step_a',
            'type': 'celery',
            'handler': 'my_app.handlers.my_custom_handler',
            'max_retries': 3,
            'description': 'First analysis step'
        },
        {
            'id': 'step_b',
            'type': 'celery',
            'handler': 'my_app.handlers.another_handler',
            'max_retries': 2,
            'description': 'Second step (depends on A)'
        },
        {
            'id': 'step_c',
            'type': 'celery',
            'handler': 'my_app.handlers.third_handler',
            'max_retries': 2,
            'description': 'Third step (depends on A, parallel with B)'
        },
        {
            'id': 'merge',
            'type': 'celery',
            'handler': 'my_app.handlers.merge_handler',
            'max_retries': 1,
            'description': 'Merge results from B and C'
        }
    ],
    'edges': [
        {'from': 'step_a', 'to': 'step_b'},
        {'from': 'step_a', 'to': 'step_c'},
        {'from': 'step_b', 'to': 'merge'},
        {'from': 'step_c', 'to': 'merge'}
    ]
}

WorkflowDefinition.objects.create(
    name='my_custom_workflow',
    version=1,
    description='Custom analysis workflow',
    dag_structure=dag_structure,
    is_active=True
)
```

The engine validates that the graph is acyclic on save.

### 3. Register as a Management Command

Create `my_app/management/commands/create_my_workflow.py` following the pattern in `workflow_engine/management/commands/create_workflow.py` for repeatable, version-controlled workflow registration.

---

## Utility Functions

The `workflow_engine/utils.py` module provides common operations:

| Function                             | Purpose                                                         |
| ------------------------------------ | --------------------------------------------------------------- |
| `get_or_create_workflow_for_paper()` | Get existing running workflow or create a new one               |
| `get_workflow_results()`             | Extract all node outputs and final results from a completed run |
| `retry_failed_nodes()`               | Reset failed nodes for retry and resume the workflow            |
| `get_active_workflows()`             | List currently running workflows, optionally filtered by paper  |
| `get_workflow_statistics()`          | System-wide stats (counts, durations, 24h activity)             |
| `visualize_workflow()`               | Text-based DAG visualization                                    |
| `generate_dag_diagram()`             | Generate Graphviz PNG diagram for a workflow definition         |
| `cleanup_old_workflows()`            | Delete completed workflows older than N days                    |
