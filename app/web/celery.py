# web/celery.py
import os
from celery import Celery

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "web.settings")

app = Celery("web")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django app configs.
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
