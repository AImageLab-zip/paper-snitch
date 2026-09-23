import hashlib
import re

from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views import View
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.utils.decorators import method_decorator

from annotator.models import Document
from workflow_engine.models import WorkflowRun

from .models import DemoScenario
from .timeline import build_timeline

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _active_scenarios():
    return DemoScenario.objects.filter(is_active=True).select_related("paper", "workflow_run")


def _stem(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").rsplit("/", 1)[-1].rsplit(".", 1)[0].lower())


class DemoLandingView(View):
    """Upload page with sample-paper cards."""

    def get(self, request):
        scenarios = list(_active_scenarios())
        return render(
            request,
            "demo/landing.html",
            {"scenarios": scenarios, "kiosk": request.GET.get("kiosk") == "1"},
        )


class DemoUploadView(View):
    """
    Recognise an uploaded PDF as one of the demo papers (by content hash, then
    by file name). The upload is only hashed in memory and never stored.
    """

    def post(self, request):
        upload = request.FILES.get("pdf_file")
        if not upload:
            return JsonResponse({"matched": False, "error": "No file received."}, status=400)
        if upload.size > MAX_UPLOAD_BYTES:
            return JsonResponse({"matched": False, "error": "File too large."}, status=400)

        digest = hashlib.sha256()
        head = b""
        for chunk in upload.chunks():
            if not head:
                head = chunk[:5]
            digest.update(chunk)
        if head != b"%PDF-":
            return JsonResponse({"matched": False, "error": "This does not look like a PDF."}, status=400)

        scenarios = list(_active_scenarios())
        scenario = next((s for s in scenarios if s.pdf_sha256 == digest.hexdigest()), None)
        if scenario is None:
            stem = _stem(upload.name)
            scenario = next(
                (
                    s
                    for s in scenarios
                    if stem and (stem == _stem(s.paper.file.name) or stem == _stem(s.paper.title))
                ),
                None,
            )
        if scenario is None:
            return JsonResponse({"matched": False})
        return JsonResponse(
            {
                "matched": True,
                "scenario_id": scenario.id,
                "title": scenario.paper.title,
                "replay_url": reverse("demo:replay", args=[scenario.id]),
            }
        )


class DemoReplayView(View):
    def get(self, request, scenario_id):
        scenario = get_object_or_404(_active_scenarios(), id=scenario_id)
        next_scenario = None
        if request.GET.get("kiosk") == "1":
            ids = [s.id for s in _active_scenarios()]
            next_scenario = ids[(ids.index(scenario.id) + 1) % len(ids)]
        return render(
            request,
            "demo/replay.html",
            {
                "scenario": scenario,
                "kiosk": request.GET.get("kiosk") == "1",
                "next_scenario": next_scenario,
                "report_url": reverse("demo:report", args=[scenario.workflow_run_id]),
            },
        )


class DemoTimelineView(View):
    """Everything the replay page needs, in one payload (no polling during the demo)."""

    def get(self, request, scenario_id):
        scenario = get_object_or_404(_active_scenarios(), id=scenario_id)
        data = build_timeline(scenario.workflow_run, scenario.target_duration_s, scenario)
        return JsonResponse(data)


class DemoReportView(View):
    """Full report for any completed workflow run, with the highlighted paper."""

    def get(self, request, run_id):
        run = get_object_or_404(
            WorkflowRun.objects.select_related("paper", "workflow_definition"), id=run_id
        )
        if run.status != "completed" or not run.nodes.filter(node_id="final_aggregation").exists():
            raise Http404("This run has no final assessment.")
        has_pdf_html = Document.objects.filter(
            paper=run.paper, conversion_status="success"
        ).exclude(html_file="").exists()
        return render(
            request,
            "demo/report.html",
            {
                "run": run,
                "paper": run.paper,
                "data": build_timeline(run),
                "has_pdf_html": has_pdf_html,
            },
        )


@method_decorator(xframe_options_sameorigin, name="dispatch")
class DemoPaperHtmlView(View):
    """The pdf2htmlEX rendering of a paper, framed by the report page."""

    def get(self, request, paper_id):
        document = (
            Document.objects.filter(paper_id=paper_id, conversion_status="success")
            .exclude(html_file="")
            .first()
        )
        if document is None:
            raise Http404("No HTML rendering for this paper. Run prepare_demo first.")
        try:
            with open(document.html_file.path, "r", encoding="utf-8") as f:
                html = f.read()
        except OSError:
            raise Http404("HTML rendering missing on disk.")
        return HttpResponse(html, content_type="text/html; charset=utf-8")
