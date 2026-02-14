"""
Management command to check the status of a Celery task.
"""
from django.core.management.base import BaseCommand
from celery.result import AsyncResult
import json


class Command(BaseCommand):
    help = 'Check the status of a Celery task'

    def add_arguments(self, parser):
        parser.add_argument(
            'task_id',
            type=str,
            help='Task ID to check'
        )
        parser.add_argument(
            '--json',
            action='store_true',
            help='Output in JSON format',
        )

    def handle(self, *args, **options):
        task_id = options['task_id']
        json_output = options['json']

        result = AsyncResult(task_id)

        if json_output:
            output = {
                'task_id': task_id,
                'state': result.state,
                'ready': result.ready(),
                'successful': result.successful() if result.ready() else None,
            }

            if result.state == 'PROGRESS':
                output['progress'] = result.info
            elif result.ready():
                if result.successful():
                    output['result'] = result.get()
                else:
                    output['error'] = str(result.info)

            self.stdout.write(json.dumps(output, indent=2))

        else:
            self.stdout.write(f'\n📋 Task Status: {task_id}\n')
            self.stdout.write(f'   State: {result.state}')
            self.stdout.write(f'   Ready: {result.ready()}')

            if result.state == 'PROGRESS':
                meta = result.info
                current = meta.get('current', 0)
                total = meta.get('total', 0)
                status = meta.get('status', 'Processing...')

                if total > 0:
                    percent = (current / total) * 100
                    self.stdout.write(
                        f'   Progress: [{current}/{total} - {percent:.1f}%] {status}'
                    )
                else:
                    self.stdout.write(f'   Status: {status}')

            elif result.ready():
                if result.successful():
                    self.stdout.write(
                        self.style.SUCCESS('\n   ✅ Task completed successfully!')
                    )
                    task_result = result.get()
                    if isinstance(task_result, dict) and 'result' in task_result:
                        scrape_result = task_result['result']
                        self.stdout.write(f'\n   Conference: {scrape_result["conference"]}')
                        self.stdout.write(f'   Processed: {scrape_result["processed"]} papers')
                        self.stdout.write(f'   Created: {scrape_result["created"]}')
                        self.stdout.write(f'   Updated: {scrape_result["updated"]}')
                        if scrape_result['failed'] > 0:
                            self.stdout.write(
                                self.style.ERROR(f'   Failed: {scrape_result["failed"]}')
                            )
                else:
                    self.stdout.write(
                        self.style.ERROR('\n   ❌ Task failed!')
                    )
                    self.stdout.write(f'   Error: {result.info}')

            self.stdout.write('')
