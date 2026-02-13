"""
Management command to start a workflow run.
"""
from django.core.management.base import BaseCommand, CommandError
from workflow_engine.services.orchestrator import WorkflowOrchestrator
from webApp.models import Paper


class Command(BaseCommand):
    help = 'Start a workflow run for a paper'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'workflow_name',
            type=str,
            help='Name of the workflow to run'
        )
        parser.add_argument(
            'paper_id',
            type=int,
            help='ID of the paper to process'
        )
        parser.add_argument(
            '--input',
            type=str,
            help='JSON string of input data',
            default='{}'
        )
    
    def handle(self, *args, **options):
        workflow_name = options['workflow_name']
        paper_id = options['paper_id']
        
        # Get paper
        try:
            paper = Paper.objects.get(id=paper_id)
        except Paper.DoesNotExist:
            raise CommandError(f'Paper {paper_id} does not exist')
        
        # Check for running workflows on this paper
        from workflow_engine.models import WorkflowRun
        running_workflow = WorkflowRun.objects.filter(
            paper=paper,
            status='running'
        ).first()
        
        if running_workflow:
            raise CommandError(
                f'Cannot start workflow: Paper {paper_id} already has a running workflow '
                f'(Run ID: {running_workflow.id}, Run #{running_workflow.run_number}). '
                f'Wait for it to complete or cancel it first.'
            )
        
        # Parse input data
        import json
        try:
            input_data = json.loads(options['input'])
        except json.JSONDecodeError:
            raise CommandError('Invalid JSON in --input parameter')
        
        # Create workflow run
        orchestrator = WorkflowOrchestrator()
        
        try:
            workflow_run = orchestrator.create_workflow_run(
                workflow_name=workflow_name,
                paper=paper,
                input_data=input_data
            )
            
            # Start the workflow
            workflow_run.status = 'running'
            workflow_run.save(update_fields=['status'])
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Started workflow run {workflow_run.id} for paper "{paper.title}"'
                )
            )
            
            self.stdout.write(f'\nWorkflow Run ID: {workflow_run.id}')
            self.stdout.write(f'Status: {workflow_run.status}')
            self.stdout.write(f'Nodes created: {workflow_run.nodes.count()}')
            self.stdout.write(f'Ready nodes: {workflow_run.nodes.filter(status="ready").count()}')
            
        except Exception as e:
            raise CommandError(f'Failed to start workflow: {str(e)}')
