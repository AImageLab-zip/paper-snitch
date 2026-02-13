# Workflow Engine Setup Guide

## Step-by-Step Installation Instructions

### 1. Prerequisites Check

Ensure you have:
- ✅ Django 5.2+ installed
- ✅ MySQL 8.0+ database
- ✅ Celery configured
- ✅ Redis or RabbitMQ for Celery broker

### 2. Install Dependencies (if needed)

```bash
cd /home/administrator/papersnitch/app

# If LangGraph is needed for AI nodes
pip install langgraph langgraph-checkpoint-mysql

# Or add to requirements.txt:
# langgraph==0.2.0
# langgraph-checkpoint-mysql==0.1.0
```

### 3. Update Celery Configuration

Edit `/home/administrator/papersnitch/app/web/celery.py`:

```python
# web/celery.py
import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "web.settings")

app = Celery("web")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Add Celery Beat schedule for workflow orchestration
from celery.schedules import crontab

app.conf.beat_schedule = {
    # Workflow scheduler - claims and dispatches ready tasks
    'workflow-scheduler': {
        'task': 'workflow_engine.tasks.workflow_scheduler_task',
        'schedule': 10.0,  # Every 10 seconds
    },
    
    # Cleanup stale task claims
    'cleanup-stale-claims': {
        'task': 'workflow_engine.tasks.cleanup_stale_claims_task',
        'schedule': crontab(minute='*/5'),  # Every 5 minutes
    },
}

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
```

### 4. Update Django Settings

Already done! The app is now in `INSTALLED_APPS` in `web/settings/base.py`.

Optionally, add workflow-specific settings:

```python
# In web/settings/base.py or development.py

# Workflow Engine Configuration
WORKFLOW_ENGINE = {
    'DEFAULT_CLAIM_DURATION_MINUTES': 30,
    'MAX_PARALLEL_TASKS': 100,
    'ENABLE_AUTO_RETRY': True,
}
```

### 5. Create Database Tables

```bash
cd /home/administrator/papersnitch/app

# Activate virtual environment if needed
# source .venv/bin/activate

# Create migrations
python3 manage.py makemigrations workflow_engine

# Apply migrations
python3 manage.py migrate workflow_engine
```

Expected output:
```
Migrations for 'workflow_engine':
  workflow_engine/migrations/0001_initial.py
    - Create model WorkflowDefinition
    - Create model WorkflowRun
    - Create model WorkflowNode
    - Create model NodeArtifact
    - Create model NodeLog
    - Create model LangGraphCheckpoint
    ... (indexes and constraints)
```

### 6. Create Default Workflow

```bash
python3 manage.py create_workflow
```

This creates the `pdf_analysis_pipeline` workflow.

### 7. Start Celery Workers

You need both a worker and beat scheduler running:

#### Terminal 1: Celery Worker
```bash
cd /home/administrator/papersnitch/app
celery -A web worker -l info --concurrency=4
```

#### Terminal 2: Celery Beat (Scheduler)
```bash
cd /home/administrator/papersnitch/app
celery -A web beat -l info
```

#### Alternative: Combined (Development Only)
```bash
celery -A web worker -B -l info
```

### 8. Verify Installation

```python
# Django shell
python3 manage.py shell

from workflow_engine.models import WorkflowDefinition
from webApp.models import Paper

# Check workflow exists
workflow = WorkflowDefinition.objects.get(name='pdf_analysis_pipeline')
print(f"Workflow: {workflow.name}")
print(f"Nodes: {len(workflow.dag_structure['nodes'])}")

# Test workflow creation (don't run yet)
from workflow_engine.services.orchestrator import WorkflowOrchestrator

paper = Paper.objects.first()
orchestrator = WorkflowOrchestrator()

run = orchestrator.create_workflow_run(
    workflow_name='pdf_analysis_pipeline',
    paper=paper
)

print(f"Created run: {run.id}")
print(f"Status: {run.status}")
print(f"Nodes: {run.nodes.count()}")
print(f"Ready nodes: {run.nodes.filter(status='ready').count()}")
```

## Production Deployment

### Docker/Compose Setup

If using Docker Compose, update your `compose.yml`:

```yaml
services:
  celery_worker:
    build:
      context: ./app
    command: celery -A web worker -l info --concurrency=4
    volumes:
      - ./app:/app
    environment:
      - DATABASE_ENGINE=mysql
      - DATABASE_NAME=${DATABASE_NAME}
      - DATABASE_USERNAME=${DATABASE_USERNAME}
      - DATABASE_PASSWORD=${DATABASE_PASSWORD}
      - DATABASE_HOST=mysql
      - DATABASE_PORT=3306
    depends_on:
      - mysql
      - redis

  celery_beat:
    build:
      context: ./app
    command: celery -A web beat -l info
    volumes:
      - ./app:/app
    environment:
      - DATABASE_ENGINE=mysql
      - DATABASE_NAME=${DATABASE_NAME}
      - DATABASE_USERNAME=${DATABASE_USERNAME}
      - DATABASE_PASSWORD=${DATABASE_PASSWORD}
      - DATABASE_HOST=mysql
      - DATABASE_PORT=3306
    depends_on:
      - mysql
      - redis

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
```

### Environment Variables

Ensure these are set:

```bash
# .env file
DATABASE_ENGINE=mysql
DATABASE_NAME=papersnitch
DATABASE_USERNAME=your_user
DATABASE_PASSWORD=your_password
DATABASE_HOST=mysql
DATABASE_PORT=3306

# Celery broker (Redis example)
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
```

### Systemd Services (Linux)

Create service files:

#### /etc/systemd/system/papersnitch-celery-worker.service
```ini
[Unit]
Description=PaperSnitch Celery Worker
After=network.target mysql.service redis.service

[Service]
Type=forking
User=www-data
Group=www-data
WorkingDirectory=/home/administrator/papersnitch/app
Environment="PATH=/home/administrator/papersnitch/app/.venv/bin"
ExecStart=/home/administrator/papersnitch/app/.venv/bin/celery -A web worker -l info --concurrency=4 --detach
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

#### /etc/systemd/system/papersnitch-celery-beat.service
```ini
[Unit]
Description=PaperSnitch Celery Beat
After=network.target mysql.service redis.service

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/home/administrator/papersnitch/app
Environment="PATH=/home/administrator/papersnitch/app/.venv/bin"
ExecStart=/home/administrator/papersnitch/app/.venv/bin/celery -A web beat -l info
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable papersnitch-celery-worker
sudo systemctl enable papersnitch-celery-beat
sudo systemctl start papersnitch-celery-worker
sudo systemctl start papersnitch-celery-beat
```

## First Workflow Execution

### 1. Choose a Paper

```bash
python3 manage.py shell
```

```python
from webApp.models import Paper

# List papers
papers = Paper.objects.all()[:5]
for p in papers:
    print(f"{p.id}: {p.title}")

# Pick one
paper = Paper.objects.get(id=1)  # Use appropriate ID
```

### 2. Start Workflow

```python
from workflow_engine.tasks import start_workflow_task

result = start_workflow_task.delay(
    workflow_name='pdf_analysis_pipeline',
    paper_id=paper.id,
    input_data={},
    user_id=None
)

print(f"Task submitted: {result.id}")
```

### 3. Monitor Progress

```python
# In shell or new script
from workflow_engine.models import WorkflowRun
from django.utils import timezone
import time

# Get latest run
run = WorkflowRun.objects.filter(paper=paper).order_by('-created_at').first()

# Monitor in loop
while run.status in ['pending', 'running']:
    run.refresh_from_db()
    progress = run.get_progress()
    
    print(f"\rStatus: {run.status} | Progress: {progress['percentage']}% "
          f"({progress['completed']}/{progress['total']})", end='')
    
    time.sleep(2)

print(f"\n\nFinal Status: {run.status}")

if run.status == 'completed':
    score_node = run.nodes.get(node_id='compute_score')
    print(f"Final Score: {score_node.output_data.get('final_score')}")
```

### 4. View Results

```bash
python3 manage.py workflow_status <workflow_run_id>
```

Or via admin:
```
http://your-domain/admin/workflow_engine/workflowrun/
```

## Integration with Existing Code

### Trigger Workflow from View

```python
# webApp/views.py
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from workflow_engine.tasks import start_workflow_task
from webApp.models import Paper

@login_required
def start_paper_analysis(request, paper_id):
    paper = get_object_or_404(Paper, id=paper_id)
    
    # Start workflow
    result = start_workflow_task.delay(
        workflow_name='pdf_analysis_pipeline',
        paper_id=paper.id,
        input_data={
            'requested_by': request.user.username,
            'priority': 'normal'
        },
        user_id=request.user.id
    )
    
    return render(request, 'analysis_started.html', {
        'paper': paper,
        'task_id': result.id
    })
```

### API Endpoint

```python
# webApp/views.py (or create workflow_engine/views.py)
from rest_framework.decorators import api_view
from rest_framework.response import Response
from workflow_engine.models import WorkflowRun

@api_view(['GET'])
def workflow_status_api(request, workflow_run_id):
    try:
        run = WorkflowRun.objects.get(id=workflow_run_id)
    except WorkflowRun.DoesNotExist:
        return Response({'error': 'Not found'}, status=404)
    
    progress = run.get_progress()
    
    return Response({
        'id': str(run.id),
        'status': run.status,
        'progress': progress,
        'paper': {
            'id': run.paper.id,
            'title': run.paper.title
        },
        'created_at': run.created_at,
        'completed_at': run.completed_at,
        'duration': run.duration
    })
```

## Next Steps

1. **Test the workflow** with a small paper
2. **Customize handlers** in `workflow_engine/handlers.py` for your specific needs
3. **Add monitoring** dashboards
4. **Create custom workflows** for different analysis types
5. **Integrate with your frontend** to show progress
6. **Set up alerts** for failed workflows

## Support & Troubleshooting

Check logs:
```bash
# Celery worker logs
tail -f celery_worker.log

# Django logs
tail -f app.log

# Database queries
python3 manage.py dbshell
```

Common issues addressed in main README.md.
