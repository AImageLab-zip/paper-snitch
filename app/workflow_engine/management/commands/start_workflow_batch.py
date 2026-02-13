"""
Management command to start workflow runs for multiple papers.
"""
from django.core.management.base import BaseCommand, CommandError
from workflow_engine.services.orchestrator import WorkflowOrchestrator
from workflow_engine.models import WorkflowRun
from webApp.models import Paper


class Command(BaseCommand):
    help = 'Start a workflow run for multiple papers'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'workflow_name',
            type=str,
            help='Name of the workflow to run'
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Run workflow on all papers'
        )
        parser.add_argument(
            '--paper-ids',
            type=str,
            help='Comma-separated list of paper IDs (e.g., "1,2,3")'
        )
        parser.add_argument(
            '--conference',
            type=str,
            help='Conference ID or name to filter papers'
        )
        parser.add_argument(
            '--skip-running',
            action='store_true',
            default=True,
            help='Skip papers that already have a running workflow (default: True)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show which papers would be processed without actually starting workflows'
        )
    
    def handle(self, *args, **options):
        workflow_name = options['workflow_name']
        
        # Determine which papers to process
        if options['all']:
            papers = Paper.objects.all()
            self.stdout.write(f'Processing all {papers.count()} papers')
        elif options['paper_ids']:
            paper_ids = [int(pid.strip()) for pid in options['paper_ids'].split(',')]
            papers = Paper.objects.filter(id__in=paper_ids)
            self.stdout.write(f'Processing {papers.count()} specified papers')
        elif options['conference']:
            # Try to find conference by ID or name
            from webApp.models import Conference
            conference_filter = options['conference']
            
            try:
                # Try as ID first
                conference_id = int(conference_filter)
                conference = Conference.objects.get(id=conference_id)
            except (ValueError, Conference.DoesNotExist):
                # Try as name
                conference = Conference.objects.filter(name__icontains=conference_filter).first()
                if not conference:
                    raise CommandError(f'Conference not found: {conference_filter}')
            
            papers = Paper.objects.filter(conference=conference)
            self.stdout.write(
                f'Processing {papers.count()} papers from conference: {conference.name}'
            )
        else:
            raise CommandError('Must specify either --all, --paper-ids, or --conference')
        
        # Track results
        started = []
        skipped = []
        failed = []
        
        for paper in papers:
            # Check if paper already has a running workflow
            if options['skip_running']:
                running_workflow = WorkflowRun.objects.filter(
                    paper=paper,
                    status='running'
                ).first()
                
                if running_workflow:
                    skipped.append({
                        'paper_id': paper.id,
                        'reason': f'Already running (Run #{running_workflow.run_number})'
                    })
                    continue
            
            # Dry run - just report what would happen
            if options['dry_run']:
                self.stdout.write(
                    self.style.SUCCESS(f'[DRY RUN] Would start workflow for paper {paper.id}: {paper.title[:50]}...')
                )
                started.append(paper.id)
                continue
            
            # Actually start the workflow
            try:
                orchestrator = WorkflowOrchestrator()
                workflow_run = orchestrator.create_workflow_run(
                    workflow_name=workflow_name,
                    paper=paper,
                    input_data=None
                )
                
                workflow_run.status = 'running'
                workflow_run.save(update_fields=['status'])
                
                started.append({
                    'paper_id': paper.id,
                    'run_id': str(workflow_run.id),
                    'run_number': workflow_run.run_number
                })
                
                self.stdout.write(
                    self.style.SUCCESS(f'✓ Started workflow for paper {paper.id}: {paper.title[:50]}...')
                )
                
            except Exception as e:
                failed.append({
                    'paper_id': paper.id,
                    'error': str(e)
                })
                self.stdout.write(
                    self.style.ERROR(f'✗ Failed to start workflow for paper {paper.id}: {str(e)}')
                )
        
        # Summary
        self.stdout.write('\n' + '=' * 60)
        self.stdout.write(self.style.SUCCESS(f'Started: {len(started)}'))
        if skipped:
            self.stdout.write(self.style.WARNING(f'Skipped: {len(skipped)}'))
        if failed:
            self.stdout.write(self.style.ERROR(f'Failed: {len(failed)}'))
        
        # Detailed results
        if started and not options['dry_run']:
            self.stdout.write('\nStarted workflows:')
            for item in started[:10]:  # Show first 10
                self.stdout.write(f"  Paper {item['paper_id']}: Run #{item['run_number']} ({item['run_id']})")
            if len(started) > 10:
                self.stdout.write(f'  ... and {len(started) - 10} more')
        
        if skipped:
            self.stdout.write('\nSkipped papers:')
            for item in skipped[:5]:
                self.stdout.write(f"  Paper {item['paper_id']}: {item['reason']}")
            if len(skipped) > 5:
                self.stdout.write(f'  ... and {len(skipped) - 5} more')
        
        if failed:
            self.stdout.write('\nFailed papers:')
            for item in failed:
                self.stdout.write(f"  Paper {item['paper_id']}: {item['error']}")
