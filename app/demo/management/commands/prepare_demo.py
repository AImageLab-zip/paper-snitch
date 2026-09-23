"""
Register a completed workflow run as a poster-demo scenario.

    python manage.py prepare_demo --list
    python manage.py prepare_demo --paper-id 322 --label "Dataset + method paper" --order 1

For the chosen paper this makes sure the pdf2htmlEX rendering exists (via the
annotator's converter), hashes the PDF so uploads can be recognised, and dry
runs the evidence matching to report how many quotes can be highlighted.
"""

import hashlib

from django.core.management.base import BaseCommand, CommandError

from annotator.models import Document
from annotator.views import convert_pdf_to_html
from demo.matching import html_to_normalized_text, locate
from demo.models import DemoScenario
from webApp.models import Paper
from workflow_engine.models import NodeArtifact, WorkflowRun

WORKFLOW_NAME = "paper_processing_with_reproducibility"


def _completed_runs(version):
    final_ok = NodeArtifact.objects.filter(
        node__node_id="final_aggregation", name="result"
    ).values("node__workflow_run_id")
    return (
        WorkflowRun.objects.filter(
            status="completed",
            workflow_definition__name=WORKFLOW_NAME,
            workflow_definition__version=version,
            id__in=final_ok,
        )
        .select_related("paper", "workflow_definition")
        .order_by("-completed_at")
    )


def _criteria(run, node_id):
    artifact = NodeArtifact.objects.filter(
        node__workflow_run=run, node__node_id=node_id, name="criterion_analyses"
    ).first()
    data = artifact.inline_data if artifact else None
    if isinstance(data, dict):
        data = data.get("value")
    return data if isinstance(data, list) else []


class Command(BaseCommand):
    help = "Prepare a completed workflow run for the poster demo replay."

    def add_arguments(self, parser):
        parser.add_argument("--list", action="store_true", help="List candidate runs and exit")
        parser.add_argument("--paper-id", type=int)
        parser.add_argument("--run-id", help="Workflow run UUID (default: latest completed run)")
        parser.add_argument(
            "--workflow-version", type=int, default=8,
            help="Workflow definition version to replay (default 8, the version in this codebase)",
        )
        parser.add_argument("--label", default="")
        parser.add_argument("--order", type=int, default=0)
        parser.add_argument("--duration", type=int, default=75, help="Replay length in seconds")
        parser.add_argument("--reconvert", action="store_true", help="Force a fresh pdf2htmlEX conversion")
        parser.add_argument("--deactivate", action="store_true", help="Hide this paper's scenario")

    def handle(self, *args, **opts):
        if opts["list"]:
            return self._list(opts["workflow_version"])
        if not opts["paper_id"]:
            raise CommandError("--paper-id is required (or use --list)")

        paper = Paper.objects.filter(id=opts["paper_id"]).first()
        if paper is None:
            raise CommandError(f"Paper {opts['paper_id']} not found")
        if not paper.file:
            raise CommandError("Paper has no PDF file")

        if opts["deactivate"]:
            n = DemoScenario.objects.filter(paper=paper).update(is_active=False)
            self.stdout.write(f"Deactivated {n} scenario(s)")
            return

        runs = _completed_runs(opts["workflow_version"]).filter(paper=paper)
        run = runs.filter(id=opts["run_id"]).first() if opts["run_id"] else runs.first()
        if run is None:
            raise CommandError("No completed run with a final assessment for this paper")
        self.stdout.write(
            f"Run {run.id} (v{run.workflow_definition.version}, run #{run.run_number}, {run.completed_at:%Y-%m-%d})"
        )

        document = self._ensure_html(paper, opts["reconvert"])

        digest = hashlib.sha256()
        with paper.file.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)

        stats = self._dry_run(run, document)

        scenario, created = DemoScenario.objects.update_or_create(
            paper=paper,
            workflow_run=run,
            defaults={
                "label": opts["label"],
                "order": opts["order"],
                "target_duration_s": opts["duration"],
                "pdf_sha256": digest.hexdigest(),
                "is_active": True,
                "match_stats": stats,
            },
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"{'Created' if created else 'Updated'} scenario {scenario.id}: /demo/replay/{scenario.id}/ "
                f"report: /demo/report/{run.id}/"
            )
        )

    def _list(self, version):
        seen = set()
        for run in _completed_runs(version)[:200]:
            if run.paper_id in seen:
                continue
            seen.add(run.paper_id)
            final = NodeArtifact.objects.filter(
                node__workflow_run=run, node__node_id="final_aggregation", name="result"
            ).first()
            result = final.inline_data or {}
            self.stdout.write(
                f"paper {run.paper_id:>5}  v{run.workflow_definition.version}  "
                f"score {result.get('overall_score', '?'):>5}  "
                f"type {result.get('paper_type', '?'):<11} "
                f"code {'y' if result.get('has_code_analysis') else 'n'} "
                f"dataset {'y' if result.get('has_dataset_analysis') else 'n'}  "
                f"{run.paper.title[:60]}"
            )

    def _ensure_html(self, paper, reconvert):
        document, _ = Document.objects.get_or_create(
            paper=paper, defaults={"title": paper.title[:255], "pdf_file": paper.file.name}
        )
        if not document.pdf_file:
            document.pdf_file = paper.file.name
            document.save()
        needs = reconvert or document.conversion_status != "success" or not document.html_file
        if not needs:
            try:
                needs = not document.html_file.storage.exists(document.html_file.name)
            except Exception:
                needs = True
        if needs:
            self.stdout.write("Converting PDF to HTML with pdf2htmlEX...")
            convert_pdf_to_html(document)
            document.refresh_from_db()
        if document.conversion_status != "success":
            raise CommandError(f"PDF conversion failed: {document.conversion_error}")
        with open(document.html_file.path, encoding="utf-8") as f:
            head = f.read(4000)
        if "pdf2htmlEX" not in head:
            self.stdout.write(
                self.style.WARNING("HTML came from the pypdf fallback, not pdf2htmlEX: layout will be plain text")
            )
        return document

    def _dry_run(self, run, document):
        with open(document.html_file.path, encoding="utf-8") as f:
            doc_norm = html_to_normalized_text(f.read())

        stats = {}
        for key, node_id in (
            ("checklist", "reproducibility_checklist"),
            ("dataset", "dataset_documentation_check"),
        ):
            criteria = [c for c in _criteria(run, node_id) if c.get("present") and c.get("evidence_text")]
            if not criteria:
                continue
            counts = {"exact": 0, "partial": 0, "missing": 0, "short": 0}
            self.stdout.write(f"\n{key}: {len(criteria)} present criteria with evidence")
            for c in criteria:
                status, coverage = locate(c["evidence_text"], doc_norm)
                counts[status] += 1
                style = self.style.SUCCESS if status == "exact" else (
                    self.style.WARNING if status == "partial" else self.style.ERROR
                )
                self.stdout.write(style(f"  {status:<7} {coverage:4.0%}  {c['criterion_name']}"))
            located = counts["exact"] + counts["partial"]
            counts["located_ratio"] = round(located / len(criteria), 3)
            stats[key] = counts
            self.stdout.write(f"  -> located {located}/{len(criteria)} ({counts['located_ratio']:.0%})")
        return stats
