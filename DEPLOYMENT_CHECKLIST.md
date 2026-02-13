# Workflow Engine - Deployment Checklist

## Pre-Deployment Verification

- [ ] Review installation summary: `WORKFLOW_ENGINE_DELIVERY.md`
- [ ] Read quick start guide: `app/workflow_engine/QUICKSTART.md`
- [ ] Understand architecture: `app/workflow_engine/IMPLEMENTATION_SUMMARY.md`

## Database Setup

- [ ] **Create migrations**
  ```bash
  cd /home/administrator/papersnitch/app
  python3 manage.py makemigrations workflow_engine
  ```
  Expected: Creates `0001_initial.py` migration

- [ ] **Apply migrations**
  ```bash
  python3 manage.py migrate workflow_engine
  ```
  Expected: Creates 6 tables (workflow_engine_*)

- [ ] **Verify tables created**
  ```bash
  python3 manage.py dbshell
  ```
  ```sql
  SHOW TABLES LIKE 'workflow_engine_%';
  -- Should show 6 tables
  ```

## Celery Configuration

- [ ] **Update web/celery.py**
  
  Add after `app.autodiscover_tasks()`:
  
  ```python
  from celery.schedules import crontab
  
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

- [ ] **Verify Celery config**
  ```bash
  python3 manage.py shell
  ```
  ```python
  from web.celery import app
  print(app.conf.beat_schedule.keys())
  # Should include 'workflow-scheduler' and 'cleanup-stale-claims'
  ```

## Workflow Definition

- [ ] **Create default workflow**
  ```bash
  python3 manage.py create_workflow
  ```
  Expected: Creates `pdf_analysis_pipeline` workflow

- [ ] **Verify workflow created**
  ```bash
  python3 manage.py shell
  ```
  ```python
  from workflow_engine.models import WorkflowDefinition
  wf = WorkflowDefinition.objects.get(name='pdf_analysis_pipeline')
  print(f"Nodes: {len(wf.dag_structure['nodes'])}")  # Should be 10
  print(f"Active: {wf.is_active}")  # Should be True
  ```

## Celery Services

- [ ] **Start Celery Worker** (Terminal 1)
  ```bash
  cd /home/administrator/papersnitch/app
  celery -A web worker -l info
  ```
  Watch for: "ready" message and tasks registered

- [ ] **Start Celery Beat** (Terminal 2)
  ```bash
  cd /home/administrator/papersnitch/app
  celery -A web beat -l info
  ```
  Watch for: Scheduler started, tasks scheduled

- [ ] **Verify services running**
  ```bash
  ps aux | grep celery
  # Should show both worker and beat processes
  ```

## Testing

- [ ] **Run verification script**
  ```bash
  cd /home/administrator/papersnitch
  python3 verify_workflow_installation.py
  ```
  Expected: All checks pass

- [ ] **Test with a paper**
  ```bash
  cd /home/administrator/papersnitch/app
  python3 manage.py shell
  ```
  ```python
  from webApp.models import Paper
  from workflow_engine.tasks import start_workflow_task
  
  # Get a test paper
  paper = Paper.objects.first()
  print(f"Testing with: {paper.title}")
  
  # Start workflow
  result = start_workflow_task.delay(
      workflow_name='pdf_analysis_pipeline',
      paper_id=paper.id
  )
  print(f"Task started: {result.id}")
  ```

- [ ] **Monitor workflow execution**
  ```bash
  # In shell, wait a few seconds then:
  from workflow_engine.models import WorkflowRun
  run = WorkflowRun.objects.filter(paper=paper).latest('created_at')
  
  # Check progress
  progress = run.get_progress()
  print(f"Status: {run.status}")
  print(f"Progress: {progress['percentage']}%")
  print(f"Nodes: {progress['completed']}/{progress['total']}")
  ```

- [ ] **Check node execution**
  ```python
  # See which nodes are running/completed
  for node in run.nodes.all():
      print(f"{node.node_id}: {node.status}")
  ```

- [ ] **Verify in admin**
  - Visit: `http://your-domain/admin/workflow_engine/workflowrun/`
  - Check: Workflow run appears
  - Check: Nodes are progressing
  - Check: Progress bar shows percentage

## Production Deployment (If using Docker)

- [ ] **Update docker-compose.yml**
  
  Add Celery services:
  ```yaml
  celery_worker:
    build: ./app
    command: celery -A web worker -l info --concurrency=4
    # ... (see SETUP.md for full config)
  
  celery_beat:
    build: ./app
    command: celery -A web beat -l info
    # ... (see SETUP.md for full config)
  ```

- [ ] **Start services**
  ```bash
  docker-compose up -d celery_worker celery_beat
  ```

- [ ] **Check logs**
  ```bash
  docker-compose logs -f celery_worker
  docker-compose logs -f celery_beat
  ```

## Customization (Optional)

- [ ] **Review example handlers**
  - Open: `app/workflow_engine/handlers.py`
  - Understand the placeholder logic
  
- [ ] **Replace with actual logic**
  - [ ] `extract_text_handler` - PDF text extraction
  - [ ] `extract_evidence_handler` - Link extraction
  - [ ] `validate_links_handler` - URL validation
  - [ ] `fetch_repo_handler` - Git cloning
  - [ ] `ai_checks_pdf_handler` - LLM analysis
  - [ ] `ai_checks_repo_handler` - Code analysis
  - [ ] `compute_score_handler` - Scoring logic
  - [ ] `generate_report_handler` - Report generation

- [ ] **Test after customization**
  - Start new workflow run
  - Verify custom logic works
  - Check error handling

## Integration (Optional)

- [ ] **Add to existing views**
  - See: `app/workflow_engine/examples.py`
  - Example 1: Trigger from view
  - Example 2: Auto-trigger on upload
  - Example 3: API endpoints

- [ ] **Add UI for progress**
  - Create workflow status template
  - Add progress bar
  - Show node execution status

- [ ] **Add notifications**
  - Email on completion
  - Webhook on failure
  - Slack integration

## Monitoring Setup

- [ ] **Set up logging**
  - Configure Django logging for workflow_engine
  - Rotate log files
  - Set appropriate log levels

- [ ] **Monitor database**
  - Check table sizes
  - Monitor index usage
  - Set up backups for workflow tables

- [ ] **Monitor Celery**
  - Install Flower: `pip install flower`
  - Start: `celery -A web flower`
  - Access: `http://localhost:5555`

- [ ] **Set up alerts**
  - Alert on failed workflows
  - Alert on stale claims
  - Alert on high execution times

## Documentation Review

- [ ] **Team onboarding**
  - Share: `WORKFLOW_ENGINE_DELIVERY.md`
  - Share: `app/workflow_engine/QUICKSTART.md`
  - Share: `app/workflow_engine/README.md`

- [ ] **Developer guide**
  - How to add new handlers
  - How to create new workflows
  - How to debug issues

## Post-Deployment Verification

- [ ] **Run test workflows**
  - Process 5-10 test papers
  - Verify all complete successfully
  - Check execution times

- [ ] **Check performance**
  ```python
  from workflow_engine.utils import get_workflow_statistics
  stats = get_workflow_statistics()
  print(f"Average duration: {stats['avg_duration_seconds']}s")
  ```

- [ ] **Verify cleanup**
  - Wait for `cleanup_stale_claims_task` to run
  - Check no stale claims accumulate

- [ ] **Load testing** (if needed)
  - Start 10-20 workflows simultaneously
  - Verify no deadlocks
  - Check database performance

## Maintenance Schedule

- [ ] **Weekly**
  - Review failed workflows
  - Check error logs
  - Monitor execution times

- [ ] **Monthly**
  - Clean up old completed workflows
  ```python
  from workflow_engine.utils import cleanup_old_workflows
  cleanup_old_workflows(days=30)
  ```
  - Review and optimize slow nodes
  - Update workflow definitions if needed

- [ ] **Quarterly**
  - Review database indexes
  - Optimize query patterns
  - Update documentation

## Rollback Plan (If Needed)

- [ ] **Disable workflows**
  ```python
  from workflow_engine.models import WorkflowDefinition
  WorkflowDefinition.objects.update(is_active=False)
  ```

- [ ] **Stop Celery tasks**
  - Stop beat: `pkill -f "celery.*beat"`
  - Stop workers: `pkill -f "celery.*worker"`

- [ ] **Remove from INSTALLED_APPS**
  - Comment out in `web/settings/base.py`
  - Restart Django

- [ ] **Database cleanup** (if removing completely)
  ```sql
  DROP TABLE workflow_engine_langgraphcheckpoint;
  DROP TABLE workflow_engine_nodelog;
  DROP TABLE workflow_engine_nodeartifact;
  DROP TABLE workflow_engine_workflownode;
  DROP TABLE workflow_engine_workflowrun;
  DROP TABLE workflow_engine_workflowdefinition;
  ```

---

## Summary

Total checklist items: ~60

**Critical (Must Do)**:
- ✅ Database migrations (2 items)
- ✅ Celery configuration (2 items)
- ✅ Create workflow (2 items)
- ✅ Start services (2 items)
- ✅ Basic testing (4 items)

**Important (Should Do)**:
- Testing and verification (6 items)
- Admin access (1 item)
- Documentation review (3 items)

**Optional (Nice to Have)**:
- Customization (10 items)
- Integration (6 items)
- Monitoring (8 items)
- Production deployment (5 items)

---

**Status**: Ready to deploy!

**Estimated Time**: 
- Core setup: 30 minutes
- Testing: 15 minutes
- Customization: Varies (hours to days)
- Integration: Varies (hours to days)
