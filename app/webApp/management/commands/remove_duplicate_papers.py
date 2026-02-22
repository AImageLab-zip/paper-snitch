"""Remove duplicate papers based on title, keeping the latest version."""
from django.core.management.base import BaseCommand
from django.db.models import Count, Max
from django.db import connection
from webApp.models import Paper, Conference


class Command(BaseCommand):
    help = 'Remove duplicate papers for a conference, keeping only the latest version by title'

    def add_arguments(self, parser):
        parser.add_argument(
            '--conference-id',
            type=int,
            help='Conference ID to deduplicate papers for'
        )
        parser.add_argument(
            '--conference-name',
            type=str,
            help='Conference name to deduplicate papers for (e.g., "MICCAI 2021")'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting'
        )

    def handle(self, *args, **options):
        conference_id = options.get('conference_id')
        conference_name = options.get('conference_name')
        dry_run = options.get('dry_run', False)

        # Get conference
        if conference_id:
            try:
                conference = Conference.objects.get(id=conference_id)
            except Conference.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Conference with ID {conference_id} not found'))
                return
        elif conference_name:
            try:
                conference = Conference.objects.get(name=conference_name)
            except Conference.DoesNotExist:
                self.stdout.write(self.style.ERROR(f'Conference "{conference_name}" not found'))
                return
        else:
            self.stdout.write(self.style.ERROR('Please provide either --conference-id or --conference-name'))
            return

        self.stdout.write(f'\nDeduplicating papers for: {conference.name} (ID: {conference.id})')
        self.stdout.write(f'Dry run: {dry_run}\n')

        # Find all papers for this conference
        papers = Paper.objects.filter(conference=conference)
        total_papers = papers.count()
        self.stdout.write(f'Total papers: {total_papers}')

        # Find duplicate titles
        duplicates = (
            papers.values('title')
            .annotate(count=Count('id'))
            .filter(count__gt=1)
        )

        duplicate_count = duplicates.count()
        self.stdout.write(f'Found {duplicate_count} titles with duplicates\n')

        if duplicate_count == 0:
            self.stdout.write(self.style.SUCCESS('No duplicates found!'))
            return

        total_to_delete = 0
        total_to_keep = 0
        papers_to_delete_ids = []
        
        # Process each duplicate title
        for dup in duplicates:
            title = dup['title']
            count = dup['count']
            
            # Get all papers with this title, ordered by last_update (newest first), then by id (highest first)
            duplicate_papers = papers.filter(title=title).order_by('-last_update', '-id')
            
            # Keep the first one (most recent)
            paper_to_keep = duplicate_papers.first()
            papers_to_delete = duplicate_papers[1:]
            
            total_to_keep += 1
            total_to_delete += len(papers_to_delete)
            
            # Collect IDs to delete
            for paper in papers_to_delete:
                papers_to_delete_ids.append(paper.id)
            
            self.stdout.write(f'\n{"="*80}')
            self.stdout.write(f'Title: {title[:70]}...' if len(title) > 70 else f'Title: {title}')
            self.stdout.write(f'Duplicates: {count}')
            
            self.stdout.write(self.style.SUCCESS(f'\n  KEEPING: Paper ID {paper_to_keep.id}'))
            self.stdout.write(f'    Last updated: {paper_to_keep.last_update}')
            self.stdout.write(f'    Has DOI: {bool(paper_to_keep.doi)}')
            self.stdout.write(f'    Has abstract: {bool(paper_to_keep.abstract)}')
            self.stdout.write(f'    Has text: {bool(paper_to_keep.text)}')
            self.stdout.write(f'    Paper URL: {paper_to_keep.paper_url}')
            
            for paper in papers_to_delete:
                self.stdout.write(self.style.WARNING(f'\n  DELETING: Paper ID {paper.id}'))
                self.stdout.write(f'    Last updated: {paper.last_update}')
                self.stdout.write(f'    Has DOI: {bool(paper.doi)}')
                self.stdout.write(f'    Has abstract: {bool(paper.abstract)}')
                self.stdout.write(f'    Has text: {bool(paper.text)}')
                self.stdout.write(f'    Paper URL: {paper.paper_url}')

        # Perform bulk deletion if not dry run
        if not dry_run and papers_to_delete_ids:
            self.stdout.write(f'\n\nPerforming bulk deletion of {len(papers_to_delete_ids)} papers...')
            
            # Use raw SQL with foreign key checks disabled to bypass cascade issues
            try:
                with connection.cursor() as cursor:
                    # Disable foreign key checks temporarily
                    cursor.execute("SET FOREIGN_KEY_CHECKS=0;")
                    
                    # Convert IDs to comma-separated string for SQL
                    ids_str = ','.join(str(id) for id in papers_to_delete_ids)
                    
                    # Delete papers directly with SQL
                    cursor.execute(f"DELETE FROM webApp_paper WHERE id IN ({ids_str});")
                    deleted_count = cursor.rowcount
                    
                    # Re-enable foreign key checks
                    cursor.execute("SET FOREIGN_KEY_CHECKS=1;")
                    
                self.stdout.write(self.style.SUCCESS(f'Successfully deleted {deleted_count} papers'))
            except Exception as e:
                # Re-enable foreign key checks even if deletion fails
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SET FOREIGN_KEY_CHECKS=1;")
                except:
                    pass
                self.stdout.write(self.style.ERROR(f'Error during bulk deletion: {e}'))
                return

        self.stdout.write(f'\n{"="*80}')
        self.stdout.write(f'\nSummary:')
        self.stdout.write(f'  Papers to keep: {total_to_keep}')
        self.stdout.write(f'  Papers to delete: {total_to_delete}')
        self.stdout.write(f'  Final paper count: {total_papers - total_to_delete}')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN - No papers were actually deleted'))
            self.stdout.write('Run without --dry-run to perform the deletion')
        else:
            self.stdout.write(self.style.SUCCESS(f'\n✓ Successfully removed {total_to_delete} duplicate papers!'))
            self.stdout.write(f'Remaining papers: {papers.count()}')
