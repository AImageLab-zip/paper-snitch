#!/bin/bash
# Quick script to check the most recent workflow run for paper 2660

docker exec django-web-dev-bolelli python manage.py shell -c "
from workflow_engine.models import WorkflowRun, WorkflowNode

# Get the most recent run
run = WorkflowRun.objects.filter(paper_id=2660).order_by('-created_at').first()
print(f'Latest Run: {str(run.id)[:12]}...')
print(f'Version: {run.workflow_definition.version}')
print(f'Status: {run.status}')
print(f'Created: {run.created_at.strftime(\"%Y-%m-%d %H:%M:%S\")}')

# Check final_aggregation execution count
final_agg = WorkflowNode.objects.filter(workflow_run=run, node_id='final_aggregation').first()
if final_agg:
    print(f'\nFinal Aggregation:')
    print(f'  Status: {final_agg.status}')
    print(f'  Attempt count: {final_agg.attempt_count}')
    if final_agg.started_at:
        print(f'  Started: {final_agg.started_at.strftime(\"%H:%M:%S\")}')
    if final_agg.completed_at:
        print(f'  Completed: {final_agg.completed_at.strftime(\"%H:%M:%S\")}')

# Show execution timeline
print(f'\nExecution Timeline:')
nodes = WorkflowNode.objects.filter(workflow_run=run).order_by('completed_at')
for node in nodes:
    if node.completed_at:
        print(f'  {node.completed_at.strftime(\"%H:%M:%S\")} - {node.node_id}')
"
