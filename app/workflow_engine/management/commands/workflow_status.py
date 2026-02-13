"""
Management command to check workflow run status.
"""
from django.core.management.base import BaseCommand, CommandError
from workflow_engine.models import WorkflowRun
from django.utils import timezone


class Command(BaseCommand):
    help = 'Check the status of a workflow run'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'workflow_run_id',
            type=str,
            help='UUID of the workflow run'
        )
    
    def handle(self, *args, **options):
        workflow_run_id = options['workflow_run_id']
        
        try:
            workflow_run = WorkflowRun.objects.get(id=workflow_run_id)
        except WorkflowRun.DoesNotExist:
            raise CommandError(f'Workflow run {workflow_run_id} does not exist')
        
        # Display workflow run info
        self.stdout.write(self.style.SUCCESS(f'\n=== Workflow Run {workflow_run.id} ==='))
        self.stdout.write(f'Workflow: {workflow_run.workflow_definition.name}')
        self.stdout.write(f'Paper: {workflow_run.paper.title}')
        self.stdout.write(f'Status: {workflow_run.status}')
        self.stdout.write(f'Run Number: {workflow_run.run_number}')
        self.stdout.write(f'Created: {workflow_run.created_at}')
        
        if workflow_run.started_at:
            self.stdout.write(f'Started: {workflow_run.started_at}')
        
        if workflow_run.completed_at:
            self.stdout.write(f'Completed: {workflow_run.completed_at}')
            if workflow_run.duration:
                self.stdout.write(f'Duration: {workflow_run.duration:.2f}s')
        
        if workflow_run.error_message:
            self.stdout.write(self.style.ERROR(f'\nError: {workflow_run.error_message}'))
        
        # Display progress
        progress = workflow_run.get_progress()
        self.stdout.write(f'\n=== Progress ===')
        self.stdout.write(f'Total nodes: {progress["total"]}')
        self.stdout.write(f'Completed: {progress["completed"]} ({progress["percentage"]}%)')
        self.stdout.write(f'Running: {progress["running"]}')
        self.stdout.write(f'Pending: {progress["pending"]}')
        self.stdout.write(f'Failed: {progress["failed"]}')
        
        # Display nodes
        self.stdout.write(f'\n=== Nodes ===')
        nodes = workflow_run.nodes.order_by('created_at')
        
        for node in nodes:
            status_style = {
                'completed': self.style.SUCCESS,
                'running': self.style.WARNING,
                'failed': self.style.ERROR,
                'ready': self.style.HTTP_INFO,
            }.get(node.status, lambda x: x)
            
            duration_str = f' ({node.duration:.2f}s)' if node.duration else ''
            
            self.stdout.write(
                f'  {node.node_id}: {status_style(node.status)}{duration_str}'
            )
            
            if node.error_message:
                self.stdout.write(f'    Error: {node.error_message[:100]}')
