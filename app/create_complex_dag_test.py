#!/usr/bin/env python
"""
Create a more complex workflow with diamond patterns and multiple convergence points.
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

# Create a more complex workflow with multiple patterns:
# - Diamond pattern (split and reconverge)
# - Multiple parallel paths with dependencies
# - Mixed fan-out and fan-in
workflow_def, created = WorkflowDefinition.objects.get_or_create(
    name="complex_analysis_workflow",
    defaults={
        'version': 1,
        'description': 'Complex analysis workflow with multiple convergence points',
        'dag_structure': {
            'nodes': [
                {'id': 'init', 'name': 'Initialize', 'task_type': 'init'},
                {'id': 'download_pdf', 'name': 'Download PDF', 'task_type': 'download'},
                {'id': 'extract_text', 'name': 'Extract Text', 'task_type': 'extraction'},
                {'id': 'extract_images', 'name': 'Extract Images', 'task_type': 'extraction'},
                
                # Parallel text processing branch
                {'id': 'tokenize', 'name': 'Tokenize', 'task_type': 'nlp'},
                {'id': 'parse_citations', 'name': 'Parse Citations', 'task_type': 'parsing'},
                {'id': 'extract_entities', 'name': 'Extract Entities', 'task_type': 'nlp'},
                
                # Parallel image processing branch
                {'id': 'classify_images', 'name': 'Classify Images', 'task_type': 'ml'},
                {'id': 'detect_charts', 'name': 'Detect Charts', 'task_type': 'ml'},
                {'id': 'ocr_images', 'name': 'OCR Images', 'task_type': 'ocr'},
                
                # First convergence: text analysis
                {'id': 'text_summary', 'name': 'Text Summary', 'task_type': 'aggregation'},
                
                # Parallel analysis after text summary
                {'id': 'sentiment', 'name': 'Sentiment Analysis', 'task_type': 'nlp'},
                {'id': 'topics', 'name': 'Topic Modeling', 'task_type': 'ml'},
                
                # Second convergence: image analysis
                {'id': 'image_summary', 'name': 'Image Summary', 'task_type': 'aggregation'},
                
                # Final convergence and output
                {'id': 'merge_all', 'name': 'Merge Analysis', 'task_type': 'aggregation'},
                {'id': 'generate_insights', 'name': 'Generate Insights', 'task_type': 'reporting'},
                {'id': 'save_results', 'name': 'Save Results', 'task_type': 'storage'},
            ],
            'edges': [
                # Initial sequence
                {'from': 'init', 'to': 'download_pdf'},
                {'from': 'download_pdf', 'to': 'extract_text'},
                {'from': 'download_pdf', 'to': 'extract_images'},
                
                # Text processing parallel paths
                {'from': 'extract_text', 'to': 'tokenize'},
                {'from': 'extract_text', 'to': 'parse_citations'},
                {'from': 'extract_text', 'to': 'extract_entities'},
                
                # Text paths converge
                {'from': 'tokenize', 'to': 'text_summary'},
                {'from': 'parse_citations', 'to': 'text_summary'},
                {'from': 'extract_entities', 'to': 'text_summary'},
                
                # Text summary splits again
                {'from': 'text_summary', 'to': 'sentiment'},
                {'from': 'text_summary', 'to': 'topics'},
                
                # Image processing parallel paths
                {'from': 'extract_images', 'to': 'classify_images'},
                {'from': 'extract_images', 'to': 'detect_charts'},
                {'from': 'extract_images', 'to': 'ocr_images'},
                
                # Image paths converge
                {'from': 'classify_images', 'to': 'image_summary'},
                {'from': 'detect_charts', 'to': 'image_summary'},
                {'from': 'ocr_images', 'to': 'image_summary'},
                
                # Final convergence
                {'from': 'sentiment', 'to': 'merge_all'},
                {'from': 'topics', 'to': 'merge_all'},
                {'from': 'image_summary', 'to': 'merge_all'},
                
                # Final sequence
                {'from': 'merge_all', 'to': 'generate_insights'},
                {'from': 'generate_insights', 'to': 'save_results'},
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
    input_data={'test_mode': True, 'complex_dag': True}
)
print(f"Created workflow run: {workflow_run.id}")

# Create nodes with varied statuses to show the DAG behavior
nodes_config = [
    ('init', 'completed', None, None),
    ('download_pdf', 'completed', 'Downloaded 2.3 MB PDF', None),
    ('extract_text', 'completed', 'Extracted 12,543 words', None),
    ('extract_images', 'completed', 'Found 8 images (5 figures, 3 tables)', None),
    
    # Text processing - mixed states
    ('tokenize', 'completed', 'Generated 15,234 tokens', None),
    ('parse_citations', 'completed', 'Found 42 citations', None),
    ('extract_entities', 'running', None, None),
    
    # Image processing - mixed states
    ('classify_images', 'completed', 'Classified: 3 charts, 2 diagrams, 3 photos', None),
    ('detect_charts', 'failed', 'Chart detection model error', 'Model inference timeout'),
    ('ocr_images', 'running', None, None),
    
    # Convergence points
    ('text_summary', 'pending', None, None),
    ('sentiment', 'pending', None, None),
    ('topics', 'pending', None, None),
    ('image_summary', 'pending', None, None),
    ('merge_all', 'pending', None, None),
    ('generate_insights', 'pending', None, None),
    ('save_results', 'pending', None, None),
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

print(f"\n✅ Complex workflow created successfully!")
print(f"View at: http://paper-snitch.ing.unimore.it:8000/paper/{paper.id}/")
print(f"\nThis workflow demonstrates:")
print(f"  • Diamond pattern: download_pdf → [extract_text, extract_images] → converge")
print(f"  • Multiple fan-out: extract_text → 3 parallel tasks")
print(f"  • Multiple fan-in: 3 tasks → text_summary")
print(f"  • Nested splits: text_summary → [sentiment, topics]")
print(f"  • Complex convergence: [sentiment, topics, image_summary] → merge_all")
print(f"  • Total nodes: {len(nodes_config)}")
print(f"  • Total edges: {len(workflow_def.dag_structure['edges'])}")
