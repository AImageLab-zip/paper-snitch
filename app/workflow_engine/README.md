# Workflow Engine - Database-Backed DAG Workflow System

A comprehensive, production-ready workflow orchestration system for Django applications using MySQL and Celery.

## Features

- **DAG-based Workflows**: Define complex directed acyclic graph workflows with dependencies
- **Database-Backed**: All state stored in MySQL using Django ORM
- **Distributed Execution**: MySQL row-level locking (`SELECT ... FOR UPDATE SKIP LOCKED`) for multi-worker environments
- **Idempotent Tasks**: Safe to retry and execute multiple times
- **LangGraph Integration**: Built-in support for AI agent nodes with MySQL checkpointing
- **Comprehensive Tracking**: Full audit trail with logs, artifacts, and execution history
- **Multiple Runs**: Support for multiple workflow runs per entity without conflicts

## Architecture

### Components

1. **WorkflowDefinition**: Reusable workflow templates (DAG structure)
2. **WorkflowRun**: Instances of workflow execution for specific entities (Papers)
3. **WorkflowNode**: Individual tasks within a workflow run
4. **NodeArtifact**: References to outputs/files produced by nodes
5. **NodeLog**: Structured logging for debugging and auditing
6. **LangGraphCheckpoint**: Persistent state for AI agent nodes

### Execution Flow

```
1. Create WorkflowRun for a Paper
   ↓
2. Initialize all nodes from WorkflowDefinition
   ↓
3. Mark nodes with no dependencies as READY
   ↓
4. Celery scheduler (workflow_scheduler_task) claims READY nodes
   ↓
5. Execute nodes via execute_node_task
   ↓
6. On completion, mark downstream dependencies as READY
   ↓
7. Repeat until all nodes complete or fail
```

## Installation & Setup

### 1. Install Dependencies

The workflow engine requires the following packages (already in your environment):

```bash
# Core dependencies
django>=5.2
celery>=5.3
pymysql>=1.1.2

# Optional: For LangGraph integration
# langgraph>=0.2.0  # Add to requirements.txt if using AI nodes
```

### 2. Database Migration

The app is already added to `INSTALLED_APPS`. Now create the database tables:

```bash
cd /home/administrator/papersnitch/app
python3 manage.py makemigrations workflow_engine
python3 manage.py migrate workflow_engine
```

### 3. Configure Celery Beat

Add periodic tasks to your Celery beat schedule. Update your Celery configuration:

```python
# In web/celery.py or settings
from celery.schedules import crontab

app.conf.beat_schedule = {
    'workflow-scheduler': {
        'task': 'workflow_engine.tasks.workflow_scheduler_task',
        'schedule': 10.0,  # Run every 10 seconds
    },
    'cleanup-stale-claims': {
        'task': 'workflow_engine.tasks.cleanup_stale_claims_task',
        'schedule': crontab(minute='*/5'),  # Every 5 minutes
    },
}
```

### 4. Create Workflow Definition

```bash
python3 manage.py create_workflow
```

This creates the default PDF analysis pipeline with:
- PDF ingestion
- Text extraction
- Evidence and link extraction
- Repository validation and fetching
- AI-powered PDF and repository checks
- Aggregation and scoring
- Report generation

## Usage

### Starting a Workflow

#### Via Management Command

```bash
python3 manage.py start_workflow pdf_analysis_pipeline <paper_id>
```

#### Via Python API

```python
from workflow_engine.services.orchestrator import WorkflowOrchestrator
from webApp.models import Paper

paper = Paper.objects.get(id=123)
orchestrator = WorkflowOrchestrator()

workflow_run = orchestrator.create_workflow_run(
    workflow_name='pdf_analysis_pipeline',
    paper=paper,
    input_data={'custom_param': 'value'},
    user=request.user
)

# Start the workflow
workflow_run.status = 'running'
workflow_run.save()
```

#### Via Celery Task

```python
from workflow_engine.tasks import start_workflow_task

result = start_workflow_task.delay(
    workflow_name='pdf_analysis_pipeline',
    paper_id=123,
    input_data={'custom_param': 'value'},
    user_id=1
)
```

### Checking Status

```bash
python3 manage.py workflow_status <workflow_run_id>
```

Or via Python:

```python
from workflow_engine.models import WorkflowRun

run = WorkflowRun.objects.get(id='uuid-here')
progress = run.get_progress()
print(f"Progress: {progress['percentage']}%")
print(f"Status: {run.status}")
```

### Accessing Results

```python
from workflow_engine.models import WorkflowRun, NodeArtifact

run = WorkflowRun.objects.get(id='uuid-here')

# Get final output
print(run.output_data)

# Get specific node output
score_node = run.nodes.get(node_id='compute_score')
print(score_node.output_data)

# Get artifacts
report_artifact = NodeArtifact.objects.get(
    node__workflow_run=run,
    name='final_report'
)
print(report_artifact.inline_data)
```

## Creating Custom Workflows

### 1. Define Node Handlers

Create handler functions in `workflow_engine/handlers.py`:

```python
def my_custom_handler(context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Custom node handler.
    
    Args:
        context: Contains:
            - node: WorkflowNode instance
            - paper: Paper instance
            - node_input: Node-specific input data
            - upstream_outputs: Outputs from dependency nodes
            - workflow_input: Workflow-level input data
    
    Returns:
        Output data dict
    """
    paper = context['paper']
    upstream = context['upstream_outputs']
    
    # Your logic here
    result = process_data(paper)
    
    # Create artifacts if needed
    from workflow_engine.models import NodeArtifact
    NodeArtifact.objects.create(
        node=context['node'],
        artifact_type='inline',
        name='my_output',
        inline_data=result
    )
    
    return result
```

### 2. Define Workflow Structure

Create a management command or script:

```python
from workflow_engine.models import WorkflowDefinition

dag_structure = {
    'nodes': [
        {
            'id': 'step1',
            'type': 'celery',
            'handler': 'workflow_engine.handlers.my_custom_handler',
            'max_retries': 3,
            'description': 'First step'
        },
        {
            'id': 'step2',
            'type': 'celery',
            'handler': 'workflow_engine.handlers.another_handler',
            'max_retries': 2,
            'description': 'Second step'
        }
    ],
    'edges': [
        {'from': 'step1', 'to': 'step2'}
    ]
}

WorkflowDefinition.objects.create(
    name='my_custom_workflow',
    version=1,
    description='My custom workflow',
    dag_structure=dag_structure,
    is_active=True
)
```

## LangGraph Integration

For AI agent nodes, use LangGraph with MySQL checkpointing:

```python
from workflow_engine.services.langgraph_integration import LangGraphNodeHandler

class MyAIHandler(LangGraphNodeHandler):
    def build_graph(self):
        from langgraph.graph import StateGraph
        
        # Define your LangGraph
        workflow = StateGraph(MyState)
        workflow.add_node("analyze", analyze_node)
        workflow.add_edge("analyze", END)
        
        return workflow.compile()
    
    def prepare_input(self):
        return {
            'text': self.paper.text,
            'custom_data': self.context['node_input']
        }

# Register in workflow definition
def my_ai_handler(context):
    handler = MyAIHandler(context)
    return handler.execute()
```

## Monitoring & Debugging

### Admin Interface

Access the Django admin at `/admin/workflow_engine/`:

- View all workflow runs
- Check node execution status
- Browse logs and artifacts
- Monitor progress in real-time

### Database Queries

```python
# Find stuck workflows
from workflow_engine.models import WorkflowRun
from django.utils import timezone
from datetime import timedelta

stuck = WorkflowRun.objects.filter(
    status='running',
    created_at__lt=timezone.now() - timedelta(hours=24)
)

# Find failed nodes
from workflow_engine.models import WorkflowNode

failed_nodes = WorkflowNode.objects.filter(
    status='failed'
).select_related('workflow_run', 'workflow_run__paper')

for node in failed_nodes:
    print(f"{node.node_id}: {node.error_message}")
```

### Logs

```python
from workflow_engine.models import NodeLog

# Get logs for a specific node
logs = NodeLog.objects.filter(node=my_node).order_by('timestamp')

for log in logs:
    print(f"[{log.level}] {log.timestamp}: {log.message}")
```

## Performance Considerations

### MySQL Optimization

Ensure these indexes exist (automatically created by migrations):

```sql
-- Critical for task claiming
CREATE INDEX idx_node_status_claim ON workflow_engine_workflownode(status, claim_expires_at);

-- For progress queries
CREATE INDEX idx_run_status ON workflow_engine_workflowrun(paper_id, status);
```

### Scaling

- **Multiple Workers**: Safe to run multiple Celery workers; row-level locking prevents duplicate work
- **Claim Duration**: Adjust `claim_duration_minutes` based on expected task execution time
- **Scheduler Frequency**: Tune `workflow_scheduler_task` frequency based on throughput needs
- **Database Connections**: Ensure connection pool is sized appropriately for worker count

## Troubleshooting

### Tasks Not Starting

1. Check Celery workers are running:
   ```bash
   celery -A web worker -l info
   ```

2. Check Celery beat is running:
   ```bash
   celery -A web beat -l info
   ```

3. Verify workflow definition exists and is active:
   ```python
   WorkflowDefinition.objects.filter(is_active=True)
   ```

### Stale Claims

Claims automatically expire. Force reset:

```python
from workflow_engine.tasks import cleanup_stale_claims_task
cleanup_stale_claims_task.delay()
```

### Failed Nodes

Check error details:

```python
node = WorkflowNode.objects.get(id='uuid')
print(node.error_message)
print(node.error_traceback)
print(f"Attempts: {node.attempt_count}/{node.max_retries}")
```

## API Reference

See inline documentation in:
- `workflow_engine/models.py` - Data models
- `workflow_engine/services/orchestrator.py` - Orchestration logic
- `workflow_engine/tasks.py` - Celery tasks
- `workflow_engine/services/langgraph_integration.py` - LangGraph integration

## Migration from Existing Systems

If you have existing `AnalysisTask` or similar models:

1. Create a data migration to convert old tasks to workflow runs
2. Keep both systems running in parallel during transition
3. Gradually migrate to workflow engine
4. Deprecate old system once stable

## Contributing

When adding new features:

1. Add appropriate indexes to models
2. Write handler functions with proper error handling
3. Create artifacts for important outputs
4. Log significant events using `NodeLog`
5. Test with multiple concurrent workers

## License

Internal use - Paper Snitch project
