"""
Management command to create and register workflow definitions.
"""
import os
import tempfile
from django.core.management.base import BaseCommand
from django.core.files import File
from workflow_engine.models import WorkflowDefinition

try:
    import graphviz
    HAS_GRAPHVIZ = True
except ImportError:
    HAS_GRAPHVIZ = False


class Command(BaseCommand):
    help = 'Create the PDF analysis workflow definition'
    
    def handle(self, *args, **options):
        """Create the default PDF analysis pipeline workflow."""
        
        # Define the DAG structure
        dag_structure = {
            'nodes': [
                {
                    'id': 'ingest_pdf',
                    'type': 'celery',
                    'handler': 'workflow_engine.handlers.ingest_pdf_handler',
                    'max_retries': 3,
                    'description': 'Ingest and store PDF file'
                },
                {
                    'id': 'extract_text',
                    'type': 'celery',
                    'handler': 'workflow_engine.handlers.extract_text_handler',
                    'max_retries': 3,
                    'description': 'Extract text from PDF (OCR if needed)'
                },
                {
                    'id': 'extract_evidence',
                    'type': 'celery',
                    'handler': 'workflow_engine.handlers.extract_evidence_handler',
                    'max_retries': 3,
                    'description': 'Extract evidence and links from text'
                },
                {
                    'id': 'validate_links',
                    'type': 'celery',
                    'handler': 'workflow_engine.handlers.validate_links_handler',
                    'max_retries': 3,
                    'description': 'Validate links and find repositories'
                },
                {
                    'id': 'fetch_repo',
                    'type': 'celery',
                    'handler': 'workflow_engine.handlers.fetch_repo_handler',
                    'max_retries': 2,
                    'description': 'Clone repository and index files'
                },
                {
                    'id': 'ai_checks_pdf',
                    'type': 'langgraph',
                    'handler': 'workflow_engine.services.langgraph_integration.ai_checks_pdf_handler',
                    'max_retries': 2,
                    'description': 'Run LLM checks on PDF content'
                },
                {
                    'id': 'ai_checks_repo',
                    'type': 'langgraph',
                    'handler': 'workflow_engine.services.langgraph_integration.ai_checks_repo_handler',
                    'max_retries': 2,
                    'description': 'Run LLM checks on repository'
                },
                {
                    'id': 'aggregate_findings',
                    'type': 'celery',
                    'handler': 'workflow_engine.handlers.aggregate_findings_handler',
                    'max_retries': 1,
                    'description': 'Aggregate all findings'
                },
                {
                    'id': 'compute_score',
                    'type': 'celery',
                    'handler': 'workflow_engine.handlers.compute_score_handler',
                    'max_retries': 1,
                    'description': 'Compute final score'
                },
                {
                    'id': 'generate_report',
                    'type': 'celery',
                    'handler': 'workflow_engine.handlers.generate_report_handler',
                    'max_retries': 1,
                    'description': 'Generate final report'
                }
            ],
            'edges': [
                # Sequential flow from ingest to text extraction
                {'from': 'ingest_pdf', 'to': 'extract_text'},
                {'from': 'extract_text', 'to': 'extract_evidence'},
                {'from': 'extract_evidence', 'to': 'validate_links'},
                {'from': 'validate_links', 'to': 'fetch_repo'},
                
                # Parallel AI checks (both depend on extracted text)
                {'from': 'extract_text', 'to': 'ai_checks_pdf'},
                {'from': 'fetch_repo', 'to': 'ai_checks_repo'},
                
                # Aggregation depends on both AI checks
                {'from': 'ai_checks_pdf', 'to': 'aggregate_findings'},
                {'from': 'ai_checks_repo', 'to': 'aggregate_findings'},
                
                # Final steps
                {'from': 'aggregate_findings', 'to': 'compute_score'},
                {'from': 'compute_score', 'to': 'generate_report'}
            ]
        }
        
        # Create or update workflow definition
        workflow, created = WorkflowDefinition.objects.update_or_create(
            name='pdf_analysis_pipeline',
            defaults={
                'version': 1,
                'description': 'Comprehensive PDF analysis pipeline with repository checks',
                'dag_structure': dag_structure,
                'is_active': True
            }
        )
        
        if created:
            self.stdout.write(
                self.style.SUCCESS(f'Created workflow: {workflow.name}')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f'Updated workflow: {workflow.name}')
            )
        
        # Generate DAG diagram with graphviz
        if HAS_GRAPHVIZ:
            try:
                self.stdout.write('\nGenerating DAG diagram...')
                
                # Create graphviz digraph
                dot = graphviz.Digraph(
                    comment=workflow.name,
                    format='png',
                    engine='dot'
                )
                
                # Set graph attributes for better visualization
                dot.attr(rankdir='TB', size='10,15')
                dot.attr('node', shape='box', style='rounded,filled', 
                        fillcolor='lightblue', fontname='Arial', fontsize='10')
                dot.attr('edge', fontsize='8', color='gray40')
                
                # Add nodes with colors based on type
                node_colors = {
                    'celery': 'lightblue',
                    'langgraph': 'lightgreen',
                    'python': 'lightyellow'
                }
                
                for node in dag_structure['nodes']:
                    node_id = node['id']
                    node_type = node.get('type', 'celery')
                    description = node.get('description', '')
                    color = node_colors.get(node_type, 'lightgray')
                    
                    # Create label with node ID and description
                    label = f"{node_id}\n({node_type})\n{description}"
                    dot.node(node_id, label=label, fillcolor=color)
                
                # Add edges
                for edge in dag_structure['edges']:
                    dot.edge(edge['from'], edge['to'])
                
                # Render to temporary file
                with tempfile.TemporaryDirectory() as tmpdir:
                    output_path = os.path.join(tmpdir, 'dag')
                    dot.render(output_path, cleanup=True)
                    
                    # Save to model
                    png_path = f'{output_path}.png'
                    with open(png_path, 'rb') as f:
                        workflow.dag_diagram.save(
                            f'{workflow.name}_dag.png',
                            File(f),
                            save=True
                        )
                
                self.stdout.write(
                    self.style.SUCCESS('DAG diagram generated and saved!')
                )
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f'Failed to generate DAG diagram: {e}')
                )
        else:
            self.stdout.write(
                self.style.WARNING('graphviz not installed - skipping diagram generation')
            )
            self.stdout.write('Install with: pip install graphviz')
        
        # Print workflow summary
        self.stdout.write(f'\nWorkflow ID: {workflow.id}')
        self.stdout.write(f'Nodes: {len(dag_structure["nodes"])}')
        self.stdout.write(f'Edges: {len(dag_structure["edges"])}')
        self.stdout.write('\nNode list:')
        for node in dag_structure['nodes']:
            self.stdout.write(f'  - {node["id"]}: {node["description"]}')
