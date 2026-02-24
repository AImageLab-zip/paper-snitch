"""
Management command to register workflow definitions in the database.

This command registers:
1. code_only_pipeline (1-node workflow - code availability check only)
2. code_availability_pipeline (2-node workflow - paper type + code availability)
3. reduced_paper_processing_pipeline (5-node workflow - full pipeline)
4. paper_processing_with_reproducibility (8-node workflow - parallel reproducibility evaluation)
"""
from django.core.management.base import BaseCommand
from workflow_engine.models import WorkflowDefinition


class Command(BaseCommand):
    help = 'Register workflow definitions in the database'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--workflow',
            type=str,
            choices=['code_only', 'code_availability', 'full_pipeline', 'reproducibility', 'all'],
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
        
        if workflow_choice in ['reproducibility', 'all']:
            self.register_reproducibility_workflow()
    
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
    
    def register_reproducibility_workflow(self):
        """Register the 8-node reproducibility evaluation workflow with parallel execution."""
        
        self.stdout.write(self.style.MIGRATE_HEADING('Registering paper_processing_with_reproducibility...'))
        
        dag_structure = {
            'workflow_handler': {
                'module': 'webApp.services.graphs.paper_processing_workflow',
                'function': 'execute_workflow',
            },
            'nodes': [
                {
                    'id': 'paper_type_classification',
                    'type': 'python',
                    'name': 'Paper Type',
                    'handler': 'webApp.services.nodes.paper_type_classification.paper_type_classification_node',
                    'description': 'Classify paper type (dataset/method/both/theoretical/unknown)',
                    'config': {},
                },
                {
                    'id': 'section_embeddings',
                    'type': 'python',
                    'name': 'Section Embeddings',
                    'handler': 'webApp.services.nodes.section_embeddings.section_embeddings_node',
                    'description': 'Compute and store vector embeddings for paper sections',
                    'config': {},
                },
                {
                    'id': 'dataset_documentation_check',
                    'type': 'python',
                    'name': 'Dataset Analysis',
                    'handler': 'webApp.services.nodes.dataset_documentation_check.dataset_documentation_check_node',
                    'description': 'Evaluate dataset documentation completeness (for dataset/both papers)',
                    'config': {},
                },
                {
                    'id': 'reproducibility_checklist',
                    'type': 'python',
                    'name': 'Paper Analysis',
                    'handler': 'webApp.services.nodes.reproducibility_checklist.reproducibility_checklist_node',
                    'description': 'Evaluate MICCAI reproducibility checklist (26 criteria)',
                    'config': {},
                },
                {
                    'id': 'code_availability_check',
                    'type': 'python',
                    'name': 'Code Availability',
                    'handler': 'webApp.services.nodes.code_availability_check.code_availability_check_node',
                    'description': 'Check if code repository exists (database/text/online search)',
                    'config': {},
                },

                {
                    'id': 'code_embedding',
                    'type': 'python',
                    'name': 'Code Embeddings',
                    'handler': 'webApp.services.nodes.code_embedding.code_embedding_node',
                    'description': 'Ingest and embed code repository files (conditional)',
                    'config': {},
                },
                {
                    'id': 'code_repository_analysis',
                    'type': 'python',
                    'name': 'Code Analysis',
                    'handler': 'webApp.services.nodes.code_repository_analysis.code_repository_analysis_node',
                    'description': 'Analyze repository and compute reproducibility score (conditional)',
                    'config': {},
                },
                {
                    'id': 'final_aggregation',
                    'type': 'python',
                    'name': 'Final Aggregation',
                    'handler': 'webApp.services.nodes.final_aggregation.final_aggregation_node',
                    'description': 'Merge findings from all evaluation nodes into final assessment',
                    'config': {},
                },
            ],
            'edges': [
                {
                    'from': 'paper_type_classification',
                    'to': 'section_embeddings',
                    'type': 'sequential',
                },
                # Parallel fan-out from section_embeddings to three analysis paths
                {
                    'from': 'section_embeddings',
                    'to': 'reproducibility_checklist',
                    'type': 'parallel',
                },
                {
                    'from': 'section_embeddings',
                    'to': 'code_availability_check',
                    'type': 'parallel',
                },
                {
                    'from': 'section_embeddings',
                    'to': 'dataset_documentation_check',
                    'type': 'conditional',
                    'condition': 'has_dataset',
                },
                # Paper Analysis path (direct to final aggregation)
                {
                    'from': 'reproducibility_checklist',
                    'to': 'final_aggregation',
                    'type': 'sequential',
                },
                # Code path (availability → embeddings → analysis → final aggregation)
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
                {
                    'from': 'code_repository_analysis',
                    'to': 'final_aggregation',
                    'type': 'sequential',
                },
                # Direct path to final_aggregation when code is not available
                {
                    'from': 'code_availability_check',
                    'to': 'final_aggregation',
                    'type': 'conditional',
                    'condition': 'code_not_available',
                },
                # Dataset Analysis path (direct to final aggregation)
                {
                    'from': 'dataset_documentation_check',
                    'to': 'final_aggregation',
                    'type': 'sequential',
                },
            ],
        }
        
        workflow, created = WorkflowDefinition.objects.get_or_create(
            name='paper_processing_with_reproducibility',
            version=6,
            defaults={
                'description': 'Eight-node workflow: paper type → section embeddings → parallel branches (reproducibility checklist, code availability check→embeddings→analysis, dataset documentation) → all converge at final aggregation. Theoretical papers only go to reproducibility checklist.',
                'dag_structure': dag_structure,
                'is_active': True
            }
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS(
                f'✓ Created paper_processing_with_reproducibility (v6)'
            ))
        else:
            # Update the DAG structure if it already exists
            workflow.dag_structure = dag_structure
            workflow.description = 'Eight-node workflow: paper type → section embeddings → parallel branches (reproducibility checklist, code availability check→embeddings→analysis, dataset documentation) → all converge at final aggregation. Theoretical papers only go to reproducibility checklist.'
            workflow.is_active = True
            workflow.save()
            self.stdout.write(self.style.WARNING(
                f'⟳ Updated paper_processing_with_reproducibility (v6) - already existed'
            ))
        
        self.stdout.write(f'  Nodes: {len(dag_structure["nodes"])}')
        self.stdout.write(f'  Edges: {len(dag_structure["edges"])}')
        self.stdout.write('')
