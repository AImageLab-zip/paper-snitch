"""
Management command to register workflow definitions in the database.

This command registers:
1. code_only_pipeline (1-node workflow - code availability check only)
2. code_availability_pipeline (2-node workflow - paper type + code availability)
3. reduced_paper_processing_pipeline (5-node workflow - full pipeline)
"""
from django.core.management.base import BaseCommand
from workflow_engine.models import WorkflowDefinition


class Command(BaseCommand):
    help = 'Register workflow definitions in the database'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--workflow',
            type=str,
            choices=['code_only', 'code_availability', 'full_pipeline', 'all'],
            default='all',
            help='Which workflow to register (default: all)'
        )
    
    def handle(self, *args, **options):
        """Register workflow definitions."""
        
        workflow_choice = options['workflow']
        
        if workflow_choice in ['code_only', 'all']:
            self.register_code_only_workflow()
        
        if workflow_choice in ['code_availability', 'all']:
            self.register_code_availability_workflow()
        
        if workflow_choice in ['full_pipeline', 'all']:
            self.register_full_pipeline_workflow()
    
    def register_code_only_workflow(self):
        """Register the 1-node code-only workflow."""
        
        self.stdout.write(self.style.MIGRATE_HEADING('Registering code_only_pipeline...'))
        
        dag_structure = {
            'workflow_handler': {
                'module': 'webApp.services.graphs.code_only_workflow',
                'function': 'execute_workflow',
            },
            'nodes': [
                {
                    'id': 'code_availability_check',
                    'type': 'python',
                    'handler': 'webApp.services.nodes.code_availability_check.code_availability_check_node',
                    'description': 'Check if code repository exists (database/text/online search)',
                    'config': {},
                },
            ],
            'edges': [],
        }
        
        workflow, created = WorkflowDefinition.objects.get_or_create(
            name='code_only_pipeline',
            version=1,
            defaults={
                'description': 'Single-node workflow: code availability check only',
                'dag_structure': dag_structure,
                'is_active': True
            }
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS(
                f'✓ Created code_only_pipeline (v1)'
            ))
        else:
            # Update the DAG structure if it already exists
            workflow.dag_structure = dag_structure
            workflow.description = 'Single-node workflow: code availability check only'
            workflow.is_active = True
            workflow.save()
            self.stdout.write(self.style.WARNING(
                f'⟳ Updated code_only_pipeline (v1) - already existed'
            ))
        
        self.stdout.write(f'  Nodes: {len(dag_structure["nodes"])}')
        self.stdout.write(f'  Edges: {len(dag_structure["edges"])}')

    def register_code_availability_workflow(self):
        """Register the 2-node code availability workflow."""
        
        self.stdout.write(self.style.MIGRATE_HEADING('Registering code_availability_pipeline...'))
        
        dag_structure = {
            'workflow_handler': {
                'module': 'webApp.services.graphs.process_code_availability',
                'function': 'execute_workflow',
            },
            'nodes': [
                {
                    'id': 'paper_type_classification',
                    'type': 'python',
                    'handler': 'webApp.services.nodes.paper_type_classification.paper_type_classification_node',
                    'description': 'Classify paper type (dataset/method/both/theoretical/unknown)',
                    'config': {},
                },
                {
                    'id': 'code_availability_check',
                    'type': 'python',
                    'handler': 'webApp.services.nodes.code_availability_check.code_availability_check_node',
                    'description': 'Check if code repository exists (database/text/online search)',
                    'config': {},
                },
            ],
            'edges': [
                {
                    'from': 'paper_type_classification',
                    'to': 'code_availability_check',
                    'type': 'sequential',
                },
            ],
        }
        
        workflow, created = WorkflowDefinition.objects.get_or_create(
            name='code_availability_pipeline',
            version=1,
            defaults={
                'description': 'Two-node workflow: paper type classification and code availability check',
                'dag_structure': dag_structure,
                'is_active': True
            }
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS(
                f'✓ Created code_availability_pipeline (v1)'
            ))
        else:
            # Update the DAG structure if it already exists
            workflow.dag_structure = dag_structure
            workflow.description = 'Two-node workflow: paper type classification and code availability check'
            workflow.is_active = True
            workflow.save()
            self.stdout.write(self.style.WARNING(
                f'⟳ Updated code_availability_pipeline (v1) - already existed'
            ))
        
        self.stdout.write(f'  Nodes: {len(dag_structure["nodes"])}')
        self.stdout.write(f'  Edges: {len(dag_structure["edges"])}')
        self.stdout.write('')
    
    def register_full_pipeline_workflow(self):
        """Register the 5-node full processing pipeline."""
        
        self.stdout.write(self.style.MIGRATE_HEADING('Registering reduced_paper_processing_pipeline...'))
        
        dag_structure = {
            'workflow_handler': {
                'module': 'webApp.services.graphs.paper_processing_workflow',
                'function': 'execute_workflow',
            },
            'nodes': [
                {
                    'id': 'paper_type_classification',
                    'type': 'python',
                    'handler': 'webApp.services.nodes.paper_type_classification.paper_type_classification_node',
                    'description': 'Classify paper type (dataset/method/both/theoretical/unknown)',
                    'config': {},
                },
                {
                    'id': 'section_embeddings',
                    'type': 'python',
                    'handler': 'webApp.services.nodes.section_embeddings.section_embeddings_node',
                    'description': 'Compute and store vector embeddings for paper sections',
                    'config': {},
                },
                {
                    'id': 'code_availability_check',
                    'type': 'python',
                    'handler': 'webApp.services.nodes.code_availability_check.code_availability_check_node',
                    'description': 'Check if code repository exists (database/text/online search)',
                    'config': {},
                },
                {
                    'id': 'code_embedding',
                    'type': 'python',
                    'handler': 'webApp.services.nodes.code_embedding.code_embedding_node',
                    'description': 'Ingest and embed code repository files (conditional)',
                    'config': {},
                },
                {
                    'id': 'code_repository_analysis',
                    'type': 'python',
                    'handler': 'webApp.services.nodes.code_repository_analysis.code_repository_analysis_node',
                    'description': 'Analyze repository and compute reproducibility score (conditional)',
                    'config': {},
                },
            ],
            'edges': [
                {
                    'from': 'paper_type_classification',
                    'to': 'section_embeddings',
                    'type': 'sequential',
                },
                {
                    'from': 'section_embeddings',
                    'to': 'code_availability_check',
                    'type': 'sequential',
                },
                {
                    'from': 'code_availability_check',
                    'to': 'code_embedding',
                    'type': 'conditional',
                    'condition': 'code_available',
                },
                {
                    'from': 'code_embedding',
                    'to': 'code_repository_analysis',
                    'type': 'sequential',
                },
            ],
        }
        
        workflow, created = WorkflowDefinition.objects.get_or_create(
            name='reduced_paper_processing_pipeline',
            version=4,
            defaults={
                'description': 'Five-node workflow: paper type classification, section embeddings, code availability check, code embedding, and conditional code repository analysis',
                'dag_structure': dag_structure,
                'is_active': True
            }
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS(
                f'✓ Created reduced_paper_processing_pipeline (v4)'
            ))
        else:
            # Update the DAG structure if it already exists
            workflow.dag_structure = dag_structure
            workflow.description = 'Five-node workflow: paper type classification, section embeddings, code availability check, code embedding, and conditional code repository analysis'
            workflow.is_active = True
            workflow.save()
            self.stdout.write(self.style.WARNING(
                f'⟳ Updated reduced_paper_processing_pipeline (v4) - already existed'
            ))
        
        self.stdout.write(f'  Nodes: {len(dag_structure["nodes"])}')
        self.stdout.write(f'  Edges: {len(dag_structure["edges"])}')
        self.stdout.write('')
