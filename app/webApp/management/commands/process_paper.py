"""
Management command to run the paper processing workflow.

Usage:
    python manage.py process_paper <paper_id> [--force]
    python manage.py process_paper --all [--force]
    python manage.py process_paper --batch 1,2,3 [--force]
    python manage.py process_paper --history <paper_id>  # View workflow history
"""

import asyncio
import logging
from django.core.management.base import BaseCommand, CommandError
from webApp.models import Paper
from workflow_engine.models import WorkflowRun, WorkflowNode, NodeArtifact
from webApp.services.graphs.paper_processing_workflow import (
    process_paper_workflow,
    process_multiple_papers,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run paper processing workflow (paper type classification + code reproducibility analysis)"

    def add_arguments(self, parser):
        parser.add_argument("paper_id", nargs="?", type=int, help="Paper ID to process")
        parser.add_argument(
            "--all", action="store_true", help="Process all papers in database"
        )
        parser.add_argument(
            "--batch",
            type=str,
            help="Process multiple papers (comma-separated IDs: 1,2,3)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force reprocessing even if already analyzed",
        )
        parser.add_argument(
            "--model",
            type=str,
            default="gpt-5",
            help="OpenAI model to use (default: gpt-5)",
        )
        parser.add_argument(
            "--max-concurrent",
            type=int,
            default=3,
            help="Maximum concurrent papers to process (default: 3)",
        )
        parser.add_argument(
            "--history",
            action="store_true",
            help="Show workflow history for specified paper_id",
        )

    def handle(self, *args, **options):
        paper_id = options.get("paper_id")
        process_all = options.get("all")
        batch = options.get("batch")
        force = options.get("force")
        model = options.get("model")
        max_concurrent = options.get("max_concurrent")
        show_history = options.get("history")

        # Show history mode
        if show_history:
            if not paper_id:
                raise CommandError("Must specify paper_id with --history")
            self._show_history(paper_id)
            return

        # Validate arguments
        if not paper_id and not process_all and not batch:
            raise CommandError("Must specify either paper_id, --all, or --batch")

        if sum([bool(paper_id), process_all, bool(batch)]) > 1:
            raise CommandError("Can only specify one of: paper_id, --all, or --batch")

        # Determine which papers to process
        if paper_id:
            paper_ids = [paper_id]
        elif batch:
            try:
                paper_ids = [int(pid.strip()) for pid in batch.split(",")]
            except ValueError:
                raise CommandError(
                    "Invalid batch format. Use comma-separated integers: 1,2,3"
                )
        else:  # process_all
            paper_ids = list(Paper.objects.values_list("id", flat=True))
            self.stdout.write(
                self.style.WARNING(
                    f"Processing ALL {len(paper_ids)} papers. This may take a while..."
                )
            )

        # Verify papers exist
        existing_ids = set(
            Paper.objects.filter(id__in=paper_ids).values_list("id", flat=True)
        )
        missing_ids = set(paper_ids) - existing_ids
        if missing_ids:
            self.stdout.write(
                self.style.ERROR(f"Papers not found: {sorted(missing_ids)}")
            )
            paper_ids = [pid for pid in paper_ids if pid in existing_ids]
            if not paper_ids:
                raise CommandError("No valid papers to process")

        self.stdout.write(
            self.style.SUCCESS(f"Processing {len(paper_ids)} paper(s)...")
        )
        if force:
            self.stdout.write(self.style.WARNING("Force reprocessing enabled"))

        # Run workflow
        try:
            if len(paper_ids) == 1:
                # Single paper processing
                result = asyncio.run(
                    process_paper_workflow(
                        paper_ids[0], force_reprocess=force, model=model
                    )
                )
                self._display_result(result)
            else:
                # Batch processing
                results = asyncio.run(
                    process_multiple_papers(
                        paper_ids, force_reprocess=force, max_concurrent=max_concurrent
                    )
                )
                self._display_batch_results(results)

        except Exception as e:
            raise CommandError(f"Workflow execution failed: {e}")

    def _show_history(self, paper_id):
        """Show workflow execution history for a paper."""
        try:
            paper = Paper.objects.get(id=paper_id)
        except Paper.DoesNotExist:
            raise CommandError(f"Paper {paper_id} not found")

        runs = WorkflowRun.objects.filter(paper=paper).order_by("-created_at")

        if not runs:
            self.stdout.write(
                self.style.WARNING(f"No workflow runs found for paper: {paper.title}")
            )
            return

        self.stdout.write(
            self.style.SUCCESS(f"\n=== Workflow History for Paper {paper_id} ===")
        )
        self.stdout.write(f"Title: {paper.title}\n")

        for run in runs:
            self.stdout.write(f"\n--- Run #{run.run_number} ({run.status.upper()}) ---")
            self.stdout.write(f"Run ID: {run.id}")
            self.stdout.write(
                f'Created: {run.created_at.strftime("%Y-%m-%d %H:%M:%S")}'
            )
            if run.completed_at:
                duration = (
                    (run.completed_at - run.started_at).total_seconds()
                    if run.started_at
                    else None
                )
                self.stdout.write(
                    f'Completed: {run.completed_at.strftime("%Y-%m-%d %H:%M:%S")} ({duration:.1f}s)'
                    if duration
                    else f'Completed: {run.completed_at.strftime("%Y-%m-%d %H:%M:%S")}'
                )

            # Show nodes
            nodes = WorkflowNode.objects.filter(workflow_run=run)
            for node in nodes:
                status_color = (
                    self.style.SUCCESS
                    if node.status == "completed"
                    else (
                        self.style.ERROR
                        if node.status == "failed"
                        else self.style.WARNING
                    )
                )
                self.stdout.write(
                    f"  Node: {node.node_id} - {status_color(node.status.upper())}"
                )

                # Show main artifact
                result_artifact = NodeArtifact.objects.filter(
                    node=node, name="result"
                ).first()
                if result_artifact and result_artifact.inline_data:
                    if node.node_id == "paper_type_classification":
                        self.stdout.write(
                            f'    Paper Type: {result_artifact.inline_data.get("paper_type", "unknown")}'
                        )
                        self.stdout.write(
                            f'    Confidence: {result_artifact.inline_data.get("confidence", 0):.2f}'
                        )
                    elif node.node_id == "code_reproducibility_analysis":
                        code_avail = result_artifact.inline_data.get(
                            "code_availability", {}
                        )
                        self.stdout.write(
                            f'    Code Available: {code_avail.get("code_available", False)}'
                        )
                        if code_avail.get("code_url"):
                            self.stdout.write(f'    Code URL: {code_avail["code_url"]}')

    def _display_result(self, result):
        """Display single paper processing result."""
        if result.get("success"):
            self.stdout.write(self.style.SUCCESS("\n=== Processing Complete ==="))
            self.stdout.write(f"Paper: {result['paper_title']}")
            self.stdout.write(f"Workflow Run ID: {result['workflow_run_id']}")
            self.stdout.write(f"Run Number: #{result['run_number']}")

            # Paper type classification
            paper_type = result.get("paper_type")
            if paper_type:
                self.stdout.write(f"\n--- Paper Type Classification ---")
                self.stdout.write(f"Type: {paper_type.paper_type}")
                self.stdout.write(f"Confidence: {paper_type.confidence:.2f}")
                self.stdout.write(f"Reasoning: {paper_type.reasoning}")

            # Code reproducibility
            code_analysis = result.get("code_reproducibility")
            if code_analysis:
                self.stdout.write(f"\n--- Code Reproducibility Analysis ---")
                self.stdout.write(
                    f"Code Available: {code_analysis.code_availability.code_available}"
                )
                if code_analysis.code_availability.code_url:
                    self.stdout.write(
                        f"Code URL: {code_analysis.code_availability.code_url}"
                    )
                self.stdout.write(f"Assessment: {code_analysis.overall_assessment}")
                self.stdout.write(
                    f"\nReproducibility Score: {code_analysis.reproducibility_score}/10"
                )

            # Token usage
            self.stdout.write(f"\n--- Token Usage ---")
            self.stdout.write(f"Input tokens: {result['total_input_tokens']}")
            self.stdout.write(f"Output tokens: {result['total_output_tokens']}")
            self.stdout.write(
                f"Total tokens: {result['total_input_tokens'] + result['total_output_tokens']}"
            )

        else:
            self.stdout.write(self.style.ERROR("\n=== Processing Failed ==="))
            self.stdout.write(f"Error: {result.get('error', 'Unknown error')}")
            if result.get("errors"):
                for error in result["errors"]:
                    self.stdout.write(self.style.ERROR(f"  - {error}"))

    def _display_batch_results(self, results):
        """Display batch processing results."""
        successful = sum(1 for r in results if isinstance(r, dict) and r.get("success"))
        failed = len(results) - successful

        self.stdout.write(self.style.SUCCESS(f"\n=== Batch Processing Complete ==="))
        self.stdout.write(f"Successful: {successful}/{len(results)}")
        self.stdout.write(f"Failed: {failed}/{len(results)}")

        # Summary statistics
        total_input_tokens = sum(
            r.get("total_input_tokens", 0) for r in results if isinstance(r, dict)
        )
        total_output_tokens = sum(
            r.get("total_output_tokens", 0) for r in results if isinstance(r, dict)
        )

        self.stdout.write(
            f"\nTotal tokens used: {total_input_tokens + total_output_tokens}"
        )
        self.stdout.write(f"  Input: {total_input_tokens}")
        self.stdout.write(f"  Output: {total_output_tokens}")

        # Show failures
        if failed > 0:
            self.stdout.write(self.style.ERROR("\nFailed papers:"))
            for result in results:
                if isinstance(result, Exception):
                    self.stdout.write(self.style.ERROR(f"  - Exception: {result}"))
                elif isinstance(result, dict) and not result.get("success"):
                    paper_id = result.get("paper_id", "Unknown")
                    error = result.get("error", "Unknown error")
                    self.stdout.write(
                        self.style.ERROR(f"  - Paper {paper_id}: {error}")
                    )
