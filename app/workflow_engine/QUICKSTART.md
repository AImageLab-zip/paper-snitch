# Quick Start Guide - Workflow Engine

## ⚡ 5-Minute Setup

### Step 1: Verify Installation
```bash
cd /home/administrator/papersnitch/app

# Check that workflow_engine app exists
ls workflow_engine/

# Verify it's in INSTALLED_APPS
grep workflow_engine web/settings/base.py
```

### Step 2: Create Migrations
```bash
python3 manage.py makemigrations workflow_engine
python3 manage.py migrate workflow_engine
```

Expected output:
```
Operations to perform:
  Apply all migrations: workflow_engine
Running migrations:
  Applying workflow_engine.0001_initial... OK
```

### Step 3: Update Celery Config

Add to `web/celery.py` (after `app.autodiscover_tasks()`):

```python
from celery.schedules import crontab

app.conf.beat_schedule = {
    'workflow-scheduler': {
        'task': 'workflow_engine.tasks.workflow_scheduler_task',
        'schedule': 10.0,
    },
    'cleanup-stale-claims': {
        'task': 'workflow_engine.tasks.cleanup_stale_claims_task',
        'schedule': crontab(minute='*/5'),
    },
}
```

### Step 4: Create Workflow Definition
```bash
python3 manage.py create_workflow
```

### Step 5: Start Celery (2 terminals)

**Terminal 1:**
```bash
cd /home/administrator/papersnitch/app
celery -A web worker -l info
```

**Terminal 2:**
```bash
cd /home/administrator/papersnitch/app
celery -A web beat -l info
```

### Step 6: Test It!

```bash
python3 manage.py shell
```

```python
from webApp.models import Paper
from workflow_engine.tasks import start_workflow_task

# Get a paper
paper = Paper.objects.first()
print(f"Testing with paper: {paper.title}")

# Start workflow
result = start_workflow_task.delay(
    workflow_name='pdf_analysis_pipeline',
    paper_id=paper.id
)

print(f"✅ Workflow started! Task ID: {result.id}")

# Check status (wait a few seconds first)
from workflow_engine.models import WorkflowRun
run = WorkflowRun.objects.filter(paper=paper).order_by('-created_at').first()
print(f"Run ID: {run.id}")
print(f"Status: {run.status}")
print(f"Progress: {run.get_progress()}")
```

### Step 7: Monitor in Admin

Open browser: `http://your-domain/admin/workflow_engine/workflowrun/`

## 🎯 What You'll See

1. **Workflow starts** - Status changes to 'running'
2. **Nodes execute** - One by one based on dependencies
3. **Progress updates** - Watch nodes turn green as they complete
4. **Final results** - Score and report generated

## 🔍 Checking Results

```python
# Get the workflow run
from workflow_engine.models import WorkflowRun
run = WorkflowRun.objects.latest('created_at')

# Check overall status
print(f"Status: {run.status}")
print(f"Progress: {run.get_progress()}")

# Get final score
score_node = run.nodes.get(node_id='compute_score')
print(f"Final Score: {score_node.output_data['final_score']}")

# Get report
report_node = run.nodes.get(node_id='generate_report')
print(f"Report: {report_node.output_data}")
```

## 📊 Check System Status

```python
from workflow_engine.utils import get_workflow_statistics
stats = get_workflow_statistics()

print(f"Total runs: {stats['total_runs']}")
print(f"Active runs: {stats['active_runs']}")
print(f"Completed: {stats['completed_runs']}")
```

## 🐛 Troubleshooting

### No tasks executing?
```bash
# Check Celery worker is running
ps aux | grep celery

# Check Celery beat is running
ps aux | grep "celery.*beat"

# Check for errors in logs
tail -f celery.log
```

### Check workflow definition:
```python
from workflow_engine.models import WorkflowDefinition
wf = WorkflowDefinition.objects.get(name='pdf_analysis_pipeline')
print(f"Nodes: {len(wf.dag_structure['nodes'])}")
print(f"Active: {wf.is_active}")
```

### Reset a failed node:
```python
from workflow_engine.utils import retry_failed_nodes
run = WorkflowRun.objects.get(id='your-run-id')
retry_failed_nodes(run)
```

## 🎨 Customization

### Modify handlers in `workflow_engine/handlers.py`

Replace placeholder logic with your actual implementation:

```python
def extract_text_handler(context):
    paper = context['paper']
    
    # YOUR ACTUAL TEXT EXTRACTION
    # e.g., using PyPDF2, pdfplumber, or your existing code
    
    return {'text': extracted_text}
```

### Create new workflow:

See `management/commands/create_workflow.py` for the pattern.

## 📚 Documentation

- **README.md** - Full documentation
- **SETUP.md** - Detailed setup instructions
- **IMPLEMENTATION_SUMMARY.md** - What was built
- **examples.py** - Integration examples

## ✅ You're Done!

You now have a production-ready workflow orchestration system running!

Next: Customize the handlers with your actual logic.
