#!/usr/bin/env python
"""
Create a test workflow with parallel nodes to test visualization.
"""
import os
import sys
import django

# Setup Django
sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'web.settings.dev')
django.setup()

from webApp.models import Paper
from workflow_engine.models import WorkflowDefinition, WorkflowRun, WorkflowNode
from django.utils import timezone
import uuid

# Get a paper for testing
paper = Paper.objects.get(id=25)
print(f"Using paper: {paper.title[:60]}...")

# Create or get workflow definition with parallel structure
workflow_def, created = WorkflowDefinition.objects.get_or_create(
    name="parallel_test_workflow",
    defaults={
        'version': 1,
        'description': 'Test workflow with parallel execution paths',
        'dag_structure': {
            'nodes': [
                {'id': 'start', 'name': 'Start', 'task_type': 'start'},
                {'id': 'extract_text', 'name': 'Extract Text', 'task_type': 'extraction'},
                {'id': 'parse_metadata', 'name': 'Parse Metadata', 'task_type': 'parsing'},
                {'id': 'analyze_figures', 'name': 'Analyze Figures', 'task_type': 'analysis'},
                {'id': 'extract_tables', 'name': 'Extract Tables', 'task_type': 'extraction'},
                {'id': 'nlp_processing', 'name': 'NLP Processing', 'task_type': 'nlp'},
                {'id': 'merge_results', 'name': 'Merge Results', 'task_type': 'aggregation'},
                {'id': 'generate_report', 'name': 'Generate Report', 'task_type': 'reporting'},
            ],
            'edges': [
                {'from': 'start', 'to': 'extract_text'},
                {'from': 'extract_text', 'to': 'parse_metadata'},
                {'from': 'extract_text', 'to': 'analyze_figures'},
                {'from': 'extract_text', 'to': 'extract_tables'},
                {'from': 'extract_text', 'to': 'nlp_processing'},
                {'from': 'parse_metadata', 'to': 'merge_results'},
                {'from': 'analyze_figures', 'to': 'merge_results'},
                {'from': 'extract_tables', 'to': 'merge_results'},
                {'from': 'nlp_processing', 'to': 'merge_results'},
                {'from': 'merge_results', 'to': 'generate_report'},
            ]
        }
    }
)
print(f"Workflow definition: {workflow_def.name} (created={created})")

# Create a workflow run
workflow_run = WorkflowRun.objects.create(
    workflow_definition=workflow_def,
    paper=paper,
    status='running',
    started_at=timezone.now(),
    input_data={'test_mode': True}
)
print(f"Created workflow run: {workflow_run.id}")

# Create nodes with different statuses to simulate parallel execution
nodes_config = [
    ('start', 'completed', None, None),
    ('extract_text', 'completed', None, None),
    ('parse_metadata', 'completed', 'Successfully parsed: 5 authors, 23 references, 12 keywords', None),
    ('analyze_figures', 'running', None, None),
    ('extract_tables', 'completed', 'Extracted and processed 4 tables with 156 total rows', None),
    ('nlp_processing', 'failed', 'NLP model timeout after 300s\nTraceback: ConnectionError at line 45', 'ConnectionError: Model inference server unreachable'),
    ('merge_results', 'pending', None, None),
    ('generate_report', 'pending', None, None),
]

created_nodes = {}
for node_id, status, output_msg, error_msg in nodes_config:
    node_def = next(n for n in workflow_def.dag_structure['nodes'] if n['id'] == node_id)
    
    node = WorkflowNode.objects.create(
        id=uuid.uuid4(),
        workflow_run=workflow_run,
        node_id=node_id,
        node_type=node_def['task_type'],
        handler=f'workflow_engine.tasks.{node_id}_task',
        status=status,
        output_data={'message': output_msg} if output_msg else {},
        error_message=error_msg,
        claimed_at=timezone.now() if status in ['running', 'completed', 'failed'] else None,
        started_at=timezone.now() if status in ['running', 'completed', 'failed'] else None,
        completed_at=timezone.now() if status in ['completed', 'failed'] else None,
    )
    created_nodes[node_id] = node
    print(f"  Created node: {node_def['name']} [{node_id}] ({status})")

print(f"\n✅ Test workflow created successfully!")
print(f"View at: http://paper-snitch.ing.unimore.it:8000/paper/{paper.id}/")
print(f"\nThis workflow has 4 parallel paths after 'extract_text':")
print(f"  1. extract_text → parse_metadata → merge_results")
print(f"  2. extract_text → analyze_figures → merge_results")
print(f"  3. extract_text → extract_tables → merge_results")
print(f"  4. extract_text → nlp_processing → merge_results")
print(f"All converge at 'merge_results' before going to 'generate_report'")
