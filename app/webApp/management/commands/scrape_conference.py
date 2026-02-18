"""
Management command to scrape conference papers.
Delegates to Celery task for async processing.
"""
from django.core.management.base import BaseCommand, CommandError
from webApp.tasks import scrape_conference_task
from celery.result import AsyncResult
import time
import sys


class Command(BaseCommand):
    help = 'Scrape papers from a conference website and save to database'

    def add_arguments(self, parser):
        parser.add_argument(
            'conference_name',
            type=str,
            help='Name of the conference (e.g., "MICCAI 2025")'
        )
        parser.add_argument(
            'conference_url',
            type=str,
            help='URL of the conference papers page'
        )
        parser.add_argument(
            '--year',
            type=int,
            help='Conference year (optional)',
            default=None,
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Maximum number of papers to scrape (for testing)',
            default=None,
        )
        parser.add_argument(
            '--sync',
            action='store_true',
            help='Run synchronously instead of via Celery (not recommended for large conferences)',
        )
        parser.add_argument(
            '--no-wait',
            action='store_true',
            help='Start task and return immediately without waiting for completion',
        )
        parser.add_argument(
            '--conference-id',
            type=int,
            help='Conference ID to update (avoids creating duplicates)',
            default=None,
        )

    def handle(self, *args, **options):
        conference_name = options['conference_name']
        conference_url = options['conference_url']
        year = options['year']
        limit = options['limit']
        sync_mode = options['sync']
        no_wait = options['no_wait']
        conference_id = options['conference_id']

        self.stdout.write(
            self.style.SUCCESS(f'\n🚀 Starting conference scrape: {conference_name}')
        )
        self.stdout.write(f'   URL: {conference_url}')
        if year:
            self.stdout.write(f'   Year: {year}')
        if limit:
            self.stdout.write(f'   Limit: {limit} papers (testing mode)')
        self.stdout.write('')

        if sync_mode:
            self.stdout.write(
                self.style.WARNING(
                    '⚠️  Running in synchronous mode. This may take a while...'
                )
            )
            # Import here to avoid circular imports
            from webApp.services.conference_scraper import ConferenceScraper
            import asyncio

            scraper = ConferenceScraper(
                conference_name=conference_name,
                conference_url=conference_url,
                year=year,
                conference_id=conference_id
            )

            def progress_callback(current, total, message):
                self.stdout.write(f'   [{current}/{total}] {message}')

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    scraper.scrape_conference(
                        limit=limit,
                        progress_callback=progress_callback
                    )
                )
            finally:
                loop.close()

            self._display_results(result)

        else:
            # Async mode via Celery
            self.stdout.write('📤 Dispatching to Celery worker...')

            # Start the task
            task = scrape_conference_task.delay(
                conference_name=conference_name,
                conference_url=conference_url,
                year=year,
                limit=limit,
                conference_id=conference_id
            )

            self.stdout.write(
                self.style.SUCCESS(f'✅ Task started: {task.id}')
            )

            if no_wait:
                self.stdout.write('\n💡 Check task status with:')
                self.stdout.write(f'   python manage.py check_task_status {task.id}')
                return

            # Wait for completion and show progress
            self.stdout.write('\n⏳ Waiting for completion (Ctrl+C to stop monitoring)...\n')

            try:
                last_status = None
                while not task.ready():
                    result = AsyncResult(task.id)
                    if result.state == 'PROGRESS':
                        meta = result.info
                        current = meta.get('current', 0)
                        total = meta.get('total', 0)
                        status = meta.get('status', 'Processing...')

                        # Only print if status changed
                        if status != last_status:
                            if total > 0:
                                percent = (current / total) * 100
                                self.stdout.write(f'   [{current}/{total} - {percent:.1f}%] {status}')
                            else:
                                self.stdout.write(f'   {status}')
                            last_status = status

                    time.sleep(1)

                # Task completed
                result = task.get()
                self.stdout.write('')
                self._display_results(result['result'])

            except KeyboardInterrupt:
                self.stdout.write(
                    self.style.WARNING(
                        '\n⚠️  Monitoring stopped. Task continues in background.'
                    )
                )
                self.stdout.write(f'\n💡 Check task status with:')
                self.stdout.write(f'   python manage.py check_task_status {task.id}')

    def _display_results(self, result):
        """Display scraping results in a formatted way."""
        self.stdout.write(
            self.style.SUCCESS('\n✅ Scraping completed!')
        )
        self.stdout.write('')
        self.stdout.write(f'📊 Results for {result["conference"]}:')
        self.stdout.write(f'   Papers found:     {result["total_found"]}')
        self.stdout.write(f'   Papers processed: {result["processed"]}')
        self.stdout.write(
            self.style.SUCCESS(f'   Created:          {result["created"]}')
        )
        self.stdout.write(f'   Updated:          {result["updated"]}')

        if result['failed'] > 0:
            self.stdout.write(
                self.style.ERROR(f'   Failed:           {result["failed"]}')
            )
            if result.get('failed_papers'):
                self.stdout.write('\n⚠️  Failed papers:')
                for paper in result['failed_papers'][:10]:  # Show first 10
                    self.stdout.write(f'   - {paper}')
                if len(result['failed_papers']) > 10:
                    self.stdout.write(f'   ... and {len(result["failed_papers"]) - 10} more')

        self.stdout.write('')
