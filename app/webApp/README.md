# webApp (Django)

### What you can do

- **Browse conferences**: see a list of conferences that have been ingested.
- **Browse papers**: open a conference to view its papers.
- **Open a paper page**: view the paper metadata and the current workflow runs (analysis history and progress).
- **Run / re-run analysis** (if enabled for your account): start an analysis workflow on a paper and watch progress.

If you are an **admin**, you can also:

- **Create a conference and scrape it**: ingest papers and PDFs from a “papers list” website.
- **Monitor scraping**: see whether scraping is running and read the scraping log.

### Typical user flows

#### A) “I want to browse what’s already in the system”

1. Go to the **conference list** (homepage).
2. Click a conference to open the **conference detail**.
3. Click a paper to open the **paper detail** page.

#### B) “I want to analyze a paper and see results”

1. Open the **paper detail** page.
2. Trigger a **workflow run** (re-run) from the page.
3. Watch the workflow progress on the same page:

- each workflow step (node) has a status like `pending`, `running`, `completed`, `failed`, or `skipped`.

4. Click into a node to see more details (logs and artifacts/output), if exposed by the UI.

What to expect:

- Some workflows can take minutes (LLM calls, embedding creation, code ingestion).
- If the system is busy, your run may wait in a queue before it starts.

#### C) (Admin) “I want to scrape a new conference”

1. Create a new conference with its “papers URL”.
2. Start scraping.
3. Monitor progress via the scraping **status** and **log** endpoints exposed in the admin UI.

Important note about “Stop scraping”:

- The stop action marks scraping as stopped in the database and writes a log entry, but it may not kill the underlying scraping subprocess immediately.

### Behind the scenes (simple mental model)

- **Database** stores conferences, papers, PDFs, and workflow history.
- **Scraping** fills the database by reading a public “papers website”, downloading PDFs, and extracting text.
- **Workflows** are long-running background jobs composed of multiple steps (nodes). Each node can write logs and outputs.
- **The UI updates live** by polling status endpoints.

### “Analyze a single uploaded PDF” (planned)

There is an upload flow in the project, but the specific feature “upload one PDF and run the same workflow used for scraped papers” is documented as **planned** (see §6 for the intended minimal approach).

---

## Zoomed-out overview

### What this app is responsible for

The Django `webApp` provides:

1. **Conference scraping UI + APIs** (admin-only) to ingest paper metadata and PDFs into the database.
2. **Website navigation** (public pages) to browse conferences and papers, plus view workflow run histories.
3. **Workflow orchestration entrypoints** (public APIs + Celery integration) to run LangGraph-based analysis pipelines against papers stored in the DB.

### Key data flow (“happy paths”)

#### A) Scrape a conference → browse papers

1. Admin triggers scraping using HTTP endpoints in `webApp/scraping_views.py`.
2. A background thread runs a management command inside the running Docker container:

   ```bash
   docker exec django-web-${STACK_SUFFIX} \
     python manage.py scrape_conference "<conference name>" "<papers url>" \
     --sync --conference-id <id> [--limit N]
   ```

3. Scraping logic (`webApp/services/conference_scraper.py`) crawls the list page, then each paper page, downloads PDFs, and stores:
   - `Conference`
   - `Paper`
   - `Dataset` relations (when present)
   - PDF files
   - extracted `Paper.text` / `Paper.sections` via Grobid-backed text extraction

4. Users browse:
   - conference list → conference detail → paper detail.

#### B) Trigger a workflow run → view progress/results

1. A user triggers workflow execution from the paper page via `RerunWorkflowView`.
2. The view enqueues `process_paper_workflow_task` (Celery), passing `paper_id`, `workflow_id`, `model`, and `force_reprocess`.
3. The Celery task dynamically imports the workflow handler specified in `WorkflowDefinition.dag_structure.workflow_handler`.
4. The LangGraph workflow runs (graph definition in `webApp/services/graphs/*`) and persists its node-level execution in the `workflow_engine` tables.
5. The paper page uses polling endpoints (workflow status + node detail) to update the UI.

#### C) Upload a single PDF → analyze “as if scraped”

The intended flow is:

- upload PDF → create a `Paper` row → extract text/sections → run the same LangGraph workflow → visualize results on the existing paper detail page.

### Where things live

```
app/
  webApp/
    views.py                 # public pages + workflow control/status APIs
    scraping_views.py        # scraping control APIs (admin-only)
    models.py                # Conference/Paper/Dataset + legacy Analysis models
    tasks.py                 # Celery tasks (scraping + workflow enqueue)
    services/
      conference_scraper.py  # crawl4ai-based scraper + DB persistence
      graphs/                # LangGraph graph definitions
      nodes/                 # Node implementations executed by LangGraph
      pydantic_schemas.py    # structured result types
      graphs_state.py        # TypedDict state schema

  workflow_engine/
    models.py                # WorkflowRun/WorkflowNode/NodeArtifact/NodeLog
    services/                # DB-backed orchestrator + async DB helpers
    tasks.py                 # engine-level scheduler/worker tasks (separate model)
```

---

## Core concepts and data model

### Web-domain models (webApp)

- **Conference** (`webApp.models.Conference`)
  - contains scraping configuration and scraping status fields:
    - `papers_url`, `scraping_schema` (JSON)
    - `is_scraping`, `last_scrape_start/end/status`, `scraping_log_file`

- **Paper** (`webApp.models.Paper`)
  - can be created via scraping or via upload flows.
  - key fields used by scraping + workflows:
    - `paper_url`, `pdf_url`, `code_url`, `authors`, `abstract`
    - `file` (downloaded or uploaded PDF)
    - `text`, `sections` (extracted from PDF)

- **Dataset** (`webApp.models.Dataset`)
  - linked to papers via M2M (`Paper.datasets`).

### Workflow persistence models (workflow_engine)

These live in `app/workflow_engine/models.py` and are the “source of truth” for workflow execution state:

- **WorkflowDefinition**: stored DAG structure (`nodes`, `edges`, and `workflow_handler`).
- **WorkflowRun**: one execution instance for a paper (`status`, token totals, `input_data`/`output_data`).
- **WorkflowNode**: per-node state and metadata for a run (`status`, timestamps, tokens, errors).
- **NodeArtifact**: node outputs (inline JSON or files).
- **NodeLog**: structured logs per node.

---

## Feature: Conference scraping

### HTTP endpoints

Routing is defined in `webApp/urls.py`. Views are in `webApp/scraping_views.py`.

- `POST /conference/create-and-scrape/`
  - `CreateAndScrapeConferenceView`: create a `Conference` row, optionally save a schema, and start scraping.

- `POST /conference/<conference_id>/scrape/start/`
  - `StartScrapingView`: start scraping for an existing conference.
  - accepts JSON body with optional `{ "limit": <int> }`.

- `GET /conference/<conference_id>/scrape/status/`
  - `ScrapingStatusView`: returns `is_scraping`, last status timestamps, log filename, and current paper count.

- `GET /conference/<conference_id>/scrape/log/?stream=true|false`
  - `ScrapingLogView`: returns log content. If `stream=true` and scraping is active, returns a `StreamingHttpResponse` and follows the file.

- `POST /conference/<conference_id>/scrape/stop/`
  - `StopScrapingView`: marks the conference as not scraping and writes a “cancelled” log message.
  - **Important:** this does _not_ kill the underlying subprocess; it only updates DB state.

### How scraping is executed (thread + docker exec)

The scraping views do not call the Celery task directly. They:

1. mark the `Conference` status as `running` and set up `scraping_log_file` under `/app/scraping_logs/...`.
2. start a **background Python thread** in the Django process.
3. that thread spawns a subprocess that runs the management command inside the running container:
   - container name is derived from env var `STACK_SUFFIX`:
     - `django-web-${STACK_SUFFIX}`

This approach is convenient for interactive UI scraping, but keep in mind:

- It couples scraping to a live container name.
- It couples scraping to the web process lifecycle (thread hosted by Django web worker).
- It requires the Django container to have access to the Docker CLI and permission to `docker exec`.

### Schema generation and caching

Scraping uses a JSON “extraction schema” to drive crawl4ai’s CSS extraction.

Priority order (implemented in `webApp/services/conference_scraper.py`):

1. **Database schema**: `Conference.scraping_schema` (if present)
2. **File schema**: `app/webApp/fixtures/scraper_schemas/<conference>_schema.json`
3. **LLM generation** (fallback): `JsonCssExtractionStrategy.generate_schema(...)`

**LLM provider:** the code uses `openai/gpt-5` and reads `OPENAI_API_KEY`.

### The scraper service (ConferenceScraper)

Implementation: `webApp/services/conference_scraper.py`

Main responsibilities:

1. Crawl the **paper list** page with `crawl4ai.AsyncWebCrawler` using the JSON schema.
2. For each paper:
   - normalize/repair paper URLs (relative URLs are joined against the conference URL)
   - crawl the paper page and extract sections from crawl4ai’s markdown output
   - clean/normalize data (`_clean_paper_data`)
   - download PDFs (main paper + supplementary) when URLs are present
3. Persist to DB (`save_paper_to_db`)
   - `Paper.objects.update_or_create(paper_url=..., defaults=...)`
   - unexpected scraped fields are stored in `Paper.metadata`
   - PDFs are stored into Django `FileField`s
4. Extract `Paper.text` and `Paper.sections` from stored PDFs using Grobid-backed extraction via `get_pdf_content`.

Concurrency controls:

- `MAX_CONCURRENT_CRAWLS` limits concurrent HTTP crawls.
- `MAX_CONCURRENT_GROBID` limits concurrent PDF text extraction.
- `SCRAPER_BATCH_SIZE` batches paper processing to control memory use.

### Runbook / debugging scraping

- Scraping logs are written inside the container at:
  - `/app/scraping_logs/<Conference>_scrape_<timestamp>.log`

- The web UI can stream these logs via `ScrapingLogView`.

- Known documentation mismatch:
  - `app/CONFERENCE_SCRAPING.md` currently references `GEMINI_API_KEY` and a different schema cache location; treat the source of truth as `webApp/services/conference_scraper.py`.

---

## Feature: Website navigation (browse + status APIs)

Routes are defined in `webApp/urls.py`. Main views are in `webApp/views.py`.

### Primary pages

- `GET /` and `GET /conferences/`
  - `ConferenceListView`
  - search + pagination
  - enriches the conference objects with token statistics using `compute_conference_token_statistics`.

- `GET /conference/<conference_id>/`
  - `ConferenceDetailView`
  - paginated papers (25/page)
  - shows per-paper “latest workflow status” and token count annotations.

- `GET /paper/<paper_id>/`
  - `PaperDetailView`
  - shows a paper’s workflow run history and a DAG visualization payload:
    - `workflow_nodes_json`: per-node status and display name
    - `workflow_edges`: edges from `WorkflowDefinition.dag_structure`

The paper page selects a run to display using the query parameter:

- `?workflow_run=<uuid>`

### Polling / JSON endpoints used by the UI

These APIs enable the front-end to refresh status without reloading the whole page:

- `GET /conference/<conference_id>/paper-statuses/`
  - `ConferencePaperStatusView`: latest workflow status per paper.

- `GET /conference/<conference_id>/node-statistics/`
  - `ConferenceNodeStatisticsView`: per-node token statistics for the conference.

- `GET /workflows/active/`
  - `ActiveWorkflowsView`: shows active count and max concurrency.

- `GET /workflow/status/<workflow_run_id>/`
  - `WorkflowStatusView`: node statuses for a run (for polling).

- `GET /workflow/status/<paper_id>/latest/`
  - `LatestWorkflowStatusView`: latest run for a paper.

- `GET /workflow/node/<node_id>/`
  - `WorkflowNodeDetailView`: includes logs + artifacts (with special-size handling for `code_embedding`).

### Performance patterns worth preserving

`webApp/views.py` uses several “avoid N+1” and “compute in SQL” patterns:

- `select_related` + `prefetch_related` on workflow runs/nodes.
- `Subquery`/`OuterRef` to fetch “latest completed run” token totals per paper.
- DB-native aggregates for averages and stddev (conference and node token stats).

---

## Feature: LangGraph workflows (services/) and workflow execution

This section is about how the Django app _invokes_ the workflows and how the graphs are structured.

### Layers (mental model)

- `webApp/services/graphs/*` and `webApp/services/nodes/*`
  - define the **LangGraph** graphs and the async node implementations.

- `workflow_engine/*`
  - defines the **DB-backed workflow persistence** (runs/nodes/artifacts/logs)
  - provides async DB helpers (`workflow_engine/services/async_orchestrator.py`) used by the LangGraph nodes.

### Main graph: PaperProcessingWorkflow

Implementation: `webApp/services/graphs/paper_processing_workflow.py`

- Graph builder: `PaperProcessingWorkflow.build_workflow()`
- Entrypoint: `PaperProcessingWorkflow.execute_workflow(paper_id, force_reprocess, model, ...)`

The graph is a fan-out/fan-in pipeline:

1. `paper_type_classification`
2. `section_embeddings`
3. fan-out into:
   - `reproducibility_checklist`
   - `dataset_documentation_check` (skipped if method-only; and not routed for theoretical)
   - `code_availability_check` → `code_embedding` → `code_repository_analysis`
4. converge into `final_aggregation`

**Conditional routing**

- After `section_embeddings`, theoretical papers route only to `reproducibility_checklist`.
- “Progressive skipping” is applied at the end of the run by `_mark_skipped_nodes(...)`.
  - theoretical: skip dataset + code branch nodes
  - method-only: skip dataset documentation
  - no code: skip `code_embedding` and `code_repository_analysis`

### How a workflow run is started (from the web UI)

- The paper page triggers a POST to:
  - `POST /paper/<paper_id>/rerun-workflow/`

Handler:

- `RerunWorkflowView.post` (in `webApp/views.py`)

This view:

1. resolves `workflow_id` to a `WorkflowDefinition`.
2. validates handler info exists in `WorkflowDefinition.dag_structure["workflow_handler"]`.
3. enqueues the Celery task:
   - `webApp.tasks.process_paper_workflow_task.delay(paper_id, force_reprocess, model, workflow_id)`

### Celery task: dynamic handler loading

Implementation: `webApp/tasks.py`

`process_paper_workflow_task`:

- if `workflow_id` is provided:
  - loads `WorkflowDefinition` and imports `handler_info["module"]`
  - calls `handler_info["function"]` in an asyncio event loop
- else:
  - runs the default `process_paper_workflow` convenience function.

This indirection makes it possible to keep multiple workflow versions active in the DB and select them at runtime.

### Node outputs, logs, artifacts

The UI queries node details via `WorkflowNodeDetailView`, which includes:

- node fields: status, handler, attempt count, errors, token counts
- node logs: `node.logs.all()`
- node artifacts: `node.artifacts.all()`

Node functions typically:

- update status to `running`
- store a structured output artifact named `result`
- write logs during the process

For deeper docs on the workflow engine persistence model and task scheduler, see:

- `app/workflow_engine/README.md`

---

## Feature: Analyze a single paper

### What “planned-only” means

A single PDF is analyzed using the _same pipeline_ as a scraped paper, without requiring a conference scrape first.

### Implementation approach behavior

1. Upload a PDF (and optionally supply title/doi metadata).
2. Create a `Paper` row with `file` set (no conference required).
3. Extract `text` and `sections`.
4. Trigger `process_paper_workflow_task` with the chosen workflow definition.
5. Redirect user to the existing paper detail page (`/paper/<paper_id>/`) to visualize the workflow run.
