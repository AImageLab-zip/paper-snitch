# Utilities Commands (Debug & Testing)

This document collects utility/debug/test commands used during development and operations.

## 1) Root-Level Python Utilities

After recent cleanup, the root contains only one direct utility script.
Most debug/test scripts were consolidated under `app/`.

### `update_colors.py`

Update annotator category colors in fixture JSON.

```bash
python update_colors.py
```

---

## 2) Django Management Commands

## Workflow registration and execution

### `register_workflows`

Register/update workflow definitions.

```bash
python manage.py register_workflows
python manage.py register_workflows --workflow all
python manage.py register_workflows --workflow reproducibility
```

Choices for `--workflow`:

- `code_only`
- `code_availability`
- `full_pipeline`
- `reproducibility`
- `all`

### `process_paper`

Run paper workflow for one paper, all papers, or a batch.

```bash
python manage.py process_paper 123
python manage.py process_paper 123 --force --model gpt-5
python manage.py process_paper --batch 1,2,3 --max-concurrent 3
python manage.py process_paper --all --force
python manage.py process_paper 123 --history
```

Main options:

- positional `paper_id`
- `--all`
- `--batch 1,2,3`
- `--force`
- `--model <name>`
- `--max-concurrent <int>`
- `--history`

### `view_analysis`

Inspect a workflow run in formatted or JSON output.

```bash
python manage.py view_analysis 123
python manage.py view_analysis 123 --run-id <workflow_run_uuid>
python manage.py view_analysis 123 --json
```

### `start_workflow` (workflow_engine)

Start a workflow run for one paper.

```bash
python manage.py start_workflow <workflow_name> <paper_id>
python manage.py start_workflow pdf_analysis_pipeline 123 --input '{"force_reprocess": false}'
```

### `start_workflow_batch` (workflow_engine)

Start a workflow on many papers.

```bash
python manage.py start_workflow_batch <workflow_name> --all
python manage.py start_workflow_batch <workflow_name> --paper-ids 1,2,3
python manage.py start_workflow_batch <workflow_name> --conference "MICCAI 2025"
python manage.py start_workflow_batch <workflow_name> --conference 7 --dry-run
```

Main options:

- `--all`
- `--paper-ids 1,2,3`
- `--conference <id_or_name>`
- `--skip-running`
- `--dry-run`

### `workflow_status` (workflow_engine)

Check per-node status and progress of a workflow run.

```bash
python manage.py workflow_status <workflow_run_uuid>
```

## Embeddings and setup

### `initialize_criteria_embeddings`

Create/update reproducibility checklist criterion embeddings.

```bash
python manage.py initialize_criteria_embeddings
python manage.py initialize_criteria_embeddings --force
python manage.py initialize_criteria_embeddings --model text-embedding-3-small
```

### `initialize_dataset_criteria_embeddings`

Create/update dataset documentation criterion embeddings.

```bash
python manage.py initialize_dataset_criteria_embeddings
python manage.py initialize_dataset_criteria_embeddings --force
python manage.py initialize_dataset_criteria_embeddings --model text-embedding-3-small
```

## Conference scraping and task monitoring

### `scrape_conference`

Scrape a conference and store papers.

```bash
python manage.py scrape_conference "MICCAI 2025" "https://papers.miccai.org/miccai-2025"
python manage.py scrape_conference "MICCAI 2025" "https://papers.miccai.org/miccai-2025" --limit 10
python manage.py scrape_conference "MICCAI 2025" "https://papers.miccai.org/miccai-2025" --no-wait
python manage.py scrape_conference "MICCAI 2025" "https://papers.miccai.org/miccai-2025" --sync
python manage.py scrape_conference "MICCAI 2025" "https://papers.miccai.org/miccai-2025" --conference-id 12
```

Main options:

- `--year <int>`
- `--limit <int>`
- `--sync`
- `--no-wait`
- `--conference-id <int>`

### `check_task_status`

Check Celery task state and progress.

```bash
python manage.py check_task_status <task_id>
python manage.py check_task_status <task_id> --json
```

## Data maintenance

### `remove_duplicate_papers`

Deduplicate papers in one conference by title (keep latest).

```bash
python manage.py remove_duplicate_papers --conference-id 12 --dry-run
python manage.py remove_duplicate_papers --conference-id 12
python manage.py remove_duplicate_papers --conference-name "MICCAI 2021" --dry-run
```

---

## 3) Additional Ad-Hoc Scripts in `app/` (non-manage commands)

### Retrieval/debug utilities

```bash
python debug_aspect_retrieval.py --list-papers
python debug_aspect_retrieval.py --paper-id 123 --aspect methodology
python debug_scraper_flow.py
```

### Workflow/debug utilities

```bash
python create_parallel_workflow_test.py
python create_complex_dag_test.py
python generate_missing_diagrams.py
python view_analysis.py <paper_id>
python test_cache_durability.py --paper-id 123
python test_reproducibility_nodes.py --paper-id 123
```

Notes:

- `create_parallel_workflow_test.py` and `create_complex_dag_test.py` are synthetic DAG data generators for development/testing.
- Some scripts contain environment-specific settings (for example hardcoded paper IDs).
