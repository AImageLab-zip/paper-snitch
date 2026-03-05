import tempfile
import os
import sys
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.views import LoginView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib import messages
from django.http import JsonResponse, FileResponse
import json
from django.views import View
from django.core.paginator import Paginator
from django.db.models import (
    Q,
    Count,
    Prefetch,
    Sum,
    Subquery,
    OuterRef,
    Avg,
    StdDev,
    Count,
)
from webApp.models import (
    Operations,
    Analysis,
    BugReport,
    Paper,
    Conference,
    LLMModelConfig,
)
from django.core.paginator import Paginator

from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.utils import timezone
import time
from django.shortcuts import render, redirect
from .functions import get_pdf_content
import pymupdf

from django.utils import timezone
import logging
import asyncio
import threading
from datetime import timedelta

from .tasks import (
    run_analysis_celery_task,
    get_task_status,
    create_analysis_task,
    cleanup_task,
    get_available_models,
)

# Import workflow models
from workflow_engine.models import (
    WorkflowRun,
    WorkflowNode,
    WorkflowDefinition,
    NodeArtifact,
)


def compute_conference_token_statistics(conferences):
    """
    Compute token statistics for conferences based on latest workflow run per paper.
    Optimized to compute all aggregations natively inside the database.
    """
    if not conferences:
        return

    conference_ids = [c.id for c in conferences]

    # 1. Subquery to find the ID of the latest completed run for each paper
    latest_run_sq = (
        WorkflowRun.objects.filter(paper_id=OuterRef("paper_id"), status="completed")
        .order_by("-created_at")
        .values("id")[:1]
    )

    # 2. Query to aggregate stats grouped directly by conference_id
    # We filter WorkflowRun to only include those latest runs for the current page of conferences
    stats = (
        WorkflowRun.objects.filter(
            paper__conference_id__in=conference_ids,
            status="completed",
            id=Subquery(latest_run_sq),
        )
        .values("paper__conference_id")
        .annotate(
            avg_input=Avg("total_input_tokens"),
            stddev_input=StdDev("total_input_tokens", sample=True),
            avg_output=Avg("total_output_tokens"),
            stddev_output=StdDev("total_output_tokens", sample=True),
            avg_total=Avg("total_tokens"),
            stddev_total=StdDev("total_tokens", sample=True),
            sum_total=Sum("total_tokens"),
        )
    )

    # 3. Create a quick lookup dictionary mapping conference_id -> stats
    stats_dict = {item["paper__conference_id"]: item for item in stats}

    # 4. Attach the computed numbers to the conference objects in memory
    for conference in conferences:
        conf_stats = stats_dict.get(conference.id, {})

        # Input
        conference.avg_input_tokens = conf_stats.get("avg_input")
        if conference.avg_input_tokens is not None:
            # MariaDB returns None for StdDev if there's only 1 row. We default to 0.0 like your original code.
            conference.stddev_input_tokens = (
                conf_stats.get("stddev_input")
                if conf_stats.get("stddev_input") is not None
                else 0.0
            )
        else:
            conference.stddev_input_tokens = None

        # Output
        conference.avg_output_tokens = conf_stats.get("avg_output")
        if conference.avg_output_tokens is not None:
            conference.stddev_output_tokens = (
                conf_stats.get("stddev_output")
                if conf_stats.get("stddev_output") is not None
                else 0.0
            )
        else:
            conference.stddev_output_tokens = None

        # Total
        conference.avg_total_tokens = conf_stats.get("avg_total")
        if conference.avg_total_tokens is not None:
            conference.stddev_total_tokens = (
                conf_stats.get("stddev_total")
                if conf_stats.get("stddev_total") is not None
                else 0.0
            )
        else:
            conference.stddev_total_tokens = None

        # Sum of latest-run tokens per paper (replaces the old annotation)
        conference.total_tokens = conf_stats.get("sum_total")


def compute_node_statistics(conference_id):
    """
    Compute per-node token statistics for a conference based on latest workflow runs.
    Optimized to compute all aggregations natively inside the database.
    """
    # 1. Subquery to find the ID of the latest completed run for each paper
    latest_run_sq = (
        WorkflowRun.objects.filter(paper_id=OuterRef("paper_id"), status="completed")
        .order_by("-created_at")
        .values("id")[:1]
    )

    # 2. Get the actual list of run IDs for this conference using the subquery
    latest_run_ids = WorkflowRun.objects.filter(
        paper__conference_id=conference_id,
        status="completed",
        id=Subquery(latest_run_sq),
    ).values_list("id", flat=True)

    if not latest_run_ids:
        return {}

    # 3. Filter nodes belonging to those runs and compute math natively in the DB.
    # Exclude nodes with zero or null total_tokens (e.g. cached runs that tracked
    # no tokens) so that they do not artificially deflate averages and inflate stddev.
    # sample=True maps to STDDEV_SAMP, matching Python's statistics.stdev()
    node_stats = (
        WorkflowNode.objects.filter(
            workflow_run_id__in=latest_run_ids,
            total_tokens__gt=0,
        )
        .values("node_id")
        .annotate(
            avg_input=Avg("input_tokens"),
            stddev_input=StdDev("input_tokens", sample=True),
            avg_output=Avg("output_tokens"),
            stddev_output=StdDev("output_tokens", sample=True),
            avg_total=Avg("total_tokens"),
            stddev_total=StdDev("total_tokens", sample=True),
            node_count=Count("id"),
        )
    )

    # 4. Format the result to match the exact JSON dictionary expected by your view
    result = {}
    for stat in node_stats:
        result[stat["node_id"]] = {
            "avg_input_tokens": stat["avg_input"],
            "stddev_input_tokens": (
                stat["stddev_input"] if stat["stddev_input"] is not None else 0.0
            ),
            "avg_output_tokens": stat["avg_output"],
            "stddev_output_tokens": (
                stat["stddev_output"] if stat["stddev_output"] is not None else 0.0
            ),
            "avg_total_tokens": stat["avg_total"],
            "stddev_total_tokens": (
                stat["stddev_total"] if stat["stddev_total"] is not None else 0.0
            ),
            "count": stat["node_count"],
        }

    return result


class PaperSnitchLoginView(LoginView):

    template_name = "registration/login.html"


class SignUpView(View):
    """View for user registration."""

    template_name = "registration/signup.html"

    def get(self, request):
        if request.user.is_authenticated:
            return redirect("analyze")
        form = UserCreationForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("analyze")
        return render(request, self.template_name, {"form": form})


class HomePageView(View):
    template_name = "home.html"

    def get(self, request):
        operations = Operations.objects.all()
        operation = [ct.name for ct in operations]

        return render(request, self.template_name, {"operations": operation})


class CheckPastAnalysesView(LoginRequiredMixin, View):
    """View for checking past analyses for a PDF paper."""

    login_url = "/accounts/login/"

    def post(self, request):
        """Handle PDF upload and check for past analyses."""
        if "pdf_file" not in request.FILES:
            return JsonResponse({"error": "No PDF file provided"}, status=400)

        pdf_file = request.FILES["pdf_file"]

        # Validate file type
        if not pdf_file.name.endswith(".pdf"):
            return JsonResponse({"error": "File must be a PDF"}, status=400)

        # Read first bytes to check if it's a valid PDF
        first_bytes = pdf_file.read(4)
        pdf_file.seek(0)  # Reset file pointer

        if not first_bytes.startswith(b"%PDF"):
            return JsonResponse(
                {"error": "Downloaded file is not a valid PDF"}, status=400
            )

        # Extract text and get title

        try:
            # Save PDF to a temporary file and pass the path
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                for chunk in pdf_file.chunks():
                    tmp_file.write(chunk)
                tmp_path = tmp_file.name

            try:
                title, text, sections = get_pdf_content(tmp_path)
            finally:
                # Clean up temporary file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

            # Validate that we got title and text
            if title is None or text is None:
                return JsonResponse(
                    {
                        "error": "Failed to extract text from PDF. The PDF processing service may be unavailable."
                    },
                    status=503,
                )

        except Exception as e:
            return JsonResponse(
                {"error": f"Failed to extract text from PDF: {str(e)}"}, status=400
            )

        # Find existing paper by title
        papers = Paper.objects.filter(title=title)
        print(len(papers), "papers found with title:", title)
        past_analyses = []
        pdf_url = None
        paper_id = None
        match_status = "no_match"
        multiple_papers = []

        if not papers.exists():  # No match found
            # Case 0: Create new paper immediately
            match_status = "no_match"

            # Delete an existing file with the same name if exists
            upload_path = Paper._meta.get_field("file").upload_to
            filename = title + ".pdf"
            full_path = os.path.join(upload_path, filename)

            if default_storage.exists(full_path):
                default_storage.delete(full_path)

            # Save new paper
            pdf_file.seek(0)
            pdf_content = ContentFile(pdf_file.read(), name=filename)

            paper = Paper.objects.create(
                title=title, text=text, sections=sections, file=pdf_content
            )
            paper.save()

            paper_id = paper.id
            pdf_url = paper.file.url if paper.file else None

        elif papers.count() == 1:  # Single match
            match_status = "single_match"
            paper = papers.first()
            paper_id = paper.id
            pdf_url = paper.file.url if paper.file else None

            # Get analyses for this paper
            analyses = (
                Analysis.objects.filter(paper=paper)
                .select_related("user")
                .order_by("-created_at")
            )
            for analysis in analyses:
                past_analyses.append(
                    {
                        "id": analysis.id,
                        "model_name": analysis.model_name,
                        "model_key": analysis.model_key,
                        "created_at": analysis.created_at.strftime("%b %d, %Y %H:%M"),
                        "duration": analysis.duration,
                        "input_tokens": analysis.input_tokens,
                        "output_tokens": analysis.output_tokens,
                        "user": (
                            analysis.user.username if analysis.user else "Anonymous"
                        ),
                        "has_error": bool(analysis.error),
                    }
                )

        else:  # Multiple matches
            match_status = "multiple_matches"

            for p in papers:
                p_analyses = []
                # Get latest analyses for each paper to show context
                # Limit to 5 per paper to avoid payload bloat
                analyses = (
                    Analysis.objects.filter(paper=p)
                    .select_related("user")
                    .order_by("-created_at")[:5]
                )

                for analysis in analyses:
                    p_analyses.append(
                        {
                            "id": analysis.id,
                            "model_name": analysis.model_name,
                            "created_at": analysis.created_at.strftime(
                                "%b %d, %Y %H:%M"
                            ),
                            "user": (
                                analysis.user.username if analysis.user else "Anonymous"
                            ),
                        }
                    )

                multiple_papers.append(
                    {
                        "id": p.id,
                        "title": p.title,
                        "pdf_url": p.file.url if p.file else None,
                        "last_update": (
                            p.last_update.strftime("%b %d, %Y %H:%M")
                            if hasattr(p, "last_update")
                            else ""
                        ),
                        "past_analyses": p_analyses,
                    }
                )
        # save the text extracted by grobid locally to avoid rerunning grobid when i have to save the paper in analyzePaperView
        tmp_text_path = None
        if papers.count() != 0:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp_text:
                tmp_text.write(text.encode("utf-8"))
                tmp_text_path = tmp_text.name
        return JsonResponse(
            {
                "title": title,
                "past_analyses": past_analyses,
                "pdf_url": pdf_url,
                "paper_id": paper_id,
                "match_status": match_status,
                "papers": multiple_papers,
                "tmp_text_path": tmp_text_path,
            }
        )


class AnalysisDetailView(LoginRequiredMixin, View):
    """API view to get analysis details for modal display."""

    login_url = "/accounts/login/"

    def get(self, request, analysis_id):
        """Get analysis details as JSON."""
        try:
            # TODO Analisi non deve dipendere dall'user, retrieve di analisi globali
            analysis = Analysis.objects.select_related("paper").get(
                id=analysis_id, user=request.user
            )
        except Analysis.DoesNotExist:
            return JsonResponse({"error": "Analysis not found"}, status=404)

        data = {
            "id": analysis.id,
            "paper_title": analysis.paper.title,
            "model_name": analysis.model_name,
            "model_key": analysis.model_key,
            "created_at": analysis.created_at.strftime("%b %d, %Y %H:%M"),
            "duration": analysis.duration,
            "input_tokens": analysis.input_tokens,
            "output_tokens": analysis.output_tokens,
            "error": analysis.error,
            "result": analysis.raw_response,
            "final_score": analysis.final_score(),
        }

        return JsonResponse(data)


class AnalyzePaperView(View):
    """View for uploading and analyzing PDF papers."""

    template_name = "webApp/analyze.html"

    def get(self, request):
        """Display the upload form with available models."""
        from annotator.models import AnnotationCategory

        available_models = get_available_models()

        categories = AnnotationCategory.objects.select_related("parent").all()
        categories_metadata = {}
        for cat in categories:
            categories_metadata[cat.name] = {
                "parent": cat.parent.name if cat.parent else None,
                "color": cat.color,
                "description": cat.description,
                "order": cat.order,
            }

        return render(
            request,
            self.template_name,
            {
                "available_models": available_models,
                "categories_metadata": json.dumps(categories_metadata),
            },
        )

    def post(self, request):
        """Handle PDF upload and start analysis. Requires login."""
        if not request.user.is_authenticated:
            return JsonResponse(
                {"error": "You must be logged in to analyze papers"}, status=401
            )

        # Get selected models from request
        selected_models = request.POST.getlist("models")
        if not selected_models:
            return JsonResponse(
                {"error": "Please select at least one model"}, status=400
            )

        paper = None
        paper_id = request.POST.get("paper_id")

        if paper_id:
            paper = get_object_or_404(Paper, id=paper_id)

        elif "pdf_file" in request.FILES:
            # Create new paper (Collision handling)
            pdf_file = request.FILES["pdf_file"]
            title = request.POST.get("title")

            # Check for conflict and rename
            base_title = title
            counter = 2
            while Paper.objects.filter(title=title).exists():
                title = f"{base_title} ({counter})"
                counter += 1

                # Get the text saved previously when we extracted the title for the matching
                tmp_text_path = request.POST.get("tmp_text_path")
                with open(tmp_text_path, "r", encoding="utf-8") as f:
                    text = f.read()

                # Save new paper
                pdf_file.seek(0)
                pdf_content = ContentFile(pdf_file.read(), name=title + ".pdf")
                paper = Paper.objects.create(
                    title=base_title, text=text, sections=sections, file=pdf_content
                )

        else:
            # Fallback to title lookup
            title = request.POST.get("title")
            papers = Paper.objects.filter(title=title)
            if papers.exists():
                paper = papers.first()
            else:
                return JsonResponse(
                    {"error": "Paper not found and no file provided"}, status=400
                )

        # Create analysis task with selected models and user
        task_id = create_analysis_task(paper, selected_models, user_id=request.user.id)

        # Start background analysis
        # run_analysis_task(task_id)
        run_analysis_celery_task.delay(task_id)

        return JsonResponse({"task_id": task_id})


class AnalysisStatusView(LoginRequiredMixin, View):
    """View for checking analysis task status. Requires login."""

    login_url = "/accounts/login/"

    def get(self, request, task_id):
        """Get the status of an analysis task."""
        status = get_task_status(task_id)

        if status is None:
            return JsonResponse({"error": "Task not found"}, status=404)

        return JsonResponse(status)


class AnalysisCleanupView(LoginRequiredMixin, View):
    """View for cleaning up completed analysis tasks. Requires login."""

    login_url = "/accounts/login/"

    def post(self, request, task_id):
        """Clean up a completed task."""
        cleanup_task(task_id)
        return JsonResponse({"success": True})


class ProfileView(LoginRequiredMixin, View):
    """View for user profile with analysis history."""

    template_name = "webApp/profile.html"
    login_url = "/accounts/login/"

    def get(self, request):
        """Display analysis history grouped by paper."""

        # Get all analyses for this user
        analyses = Analysis.objects.select_related("paper").order_by("-created_at")

        # Group analyses by paper
        papers_dict = {}
        for analysis in analyses:
            paper_id = analysis.paper.id
            if paper_id not in papers_dict:
                papers_dict[paper_id] = {
                    "paper": analysis.paper,
                    "analyses": [],
                    "latest_analysis": analysis.created_at,
                }
            papers_dict[paper_id]["analyses"].append(analysis)

        # Convert to list and sort by latest analysis date
        papers_with_analyses = sorted(
            papers_dict.values(), key=lambda x: x["latest_analysis"], reverse=True
        )

        context = {
            "papers_with_analyses": papers_with_analyses,
            "total_analyses": analyses.count(),
        }

        return render(request, self.template_name, context)


class AnalysisDetailView(LoginRequiredMixin, View):
    """API view to get analysis details for modal display."""

    login_url = "/accounts/login/"

    def get(self, request, analysis_id):
        """Get analysis details as JSON."""
        try:
            analysis = Analysis.objects.select_related("paper").get(
                id=analysis_id, user=request.user
            )
        except Analysis.DoesNotExist:
            return JsonResponse({"error": "Analysis not found"}, status=404)

        data = {
            "id": analysis.id,
            "paper_title": analysis.paper.title,
            "model_name": analysis.model_name,
            "model_key": analysis.model_key,
            "created_at": analysis.created_at.strftime("%b %d, %Y %H:%M"),
            "duration": analysis.duration,
            "input_tokens": analysis.input_tokens,
            "output_tokens": analysis.output_tokens,
            "error": analysis.error,
            "result": analysis.raw_response,
            "final_score": analysis.final_score(),
        }

        return JsonResponse(data)


class BugReportView(View):
    """View for submitting bug reports and suggestions."""

    template_name = "webApp/bug_report.html"

    def get(self, request):
        """Display the feedback form."""
        return render(request, self.template_name)

    def post(self, request):
        """Handle feedback submission."""
        report_type = request.POST.get("report_type", "bug")
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        steps_to_reproduce = request.POST.get("steps_to_reproduce", "").strip()
        expected_behavior = request.POST.get("expected_behavior", "").strip()
        actual_behavior = request.POST.get("actual_behavior", "").strip()
        priority = request.POST.get("priority", "medium")
        browser_info = request.POST.get("browser_info", "").strip()
        screenshot = request.FILES.get("screenshot")

        # Validate required fields
        if not title or not description:
            messages.error(request, "Title and description are required.")
            return render(request, self.template_name)

        # Create feedback report
        bug_report = BugReport(
            user=request.user if request.user.is_authenticated else None,
            report_type=report_type,
            title=title,
            description=description,
            steps_to_reproduce=steps_to_reproduce or None,
            expected_behavior=expected_behavior or None,
            actual_behavior=actual_behavior or None,
            priority=priority,
            browser_info=browser_info or None,
            screenshot=screenshot,
        )
        bug_report.save()

        # Custom success message based on report type
        type_messages = {
            "bug": "Thank you! Your bug report has been submitted. We will review it and work on a fix.",
            "suggestion": "Thank you! Your suggestion has been submitted. We appreciate your ideas!",
        }
        messages.success(request, type_messages.get(report_type, type_messages["bug"]))
        return redirect("bug_report")


class AnnotatePaperView(LoginRequiredMixin, View):
    """View for annotating a paper's PDF as HTML."""

    login_url = "/accounts/login/"

    def get(self, request, paper_id):

        paper = get_object_or_404(Paper, id=paper_id)

        # Check if paper has an associated document
        try:
            document = paper.document
        except Paper.document.RelatedObjectDoesNotExist:
            messages.error(request, "No document associated with this paper yet.")
            return redirect("profile")

        # Redirect to the annotator view
        return redirect("annotate_document", pk=document.pk)


class ConferenceListView(View):
    """View for listing all conferences (public, no auth required)."""

    template_name = "webApp/conference_list.html"

    def get(self, request):
        """Display conferences with search and pagination."""

        search_query = request.GET.get("q", "").strip()

        # Start with all conferences
        conferences = Conference.objects.all()

        # Annotate with paper count only; total_tokens is computed per-latest-run
        # inside compute_conference_token_statistics() below.
        conferences = conferences.annotate(
            paper_count=Count("papers", distinct=True),
        )

        # Apply search filter
        if search_query:
            conferences = conferences.filter(
                Q(name__icontains=search_query) | Q(year__icontains=search_query)
            )

        # Order by year (latest first), then by name
        conferences = conferences.order_by("-year", "name")

        # Pagination
        paginator = Paginator(conferences, 20)  # 20 conferences per page
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        # Compute token statistics based on latest run per paper
        # This adds avg_input_tokens, stddev_input_tokens, etc. to each conference
        compute_conference_token_statistics(list(page_obj))

        context = {
            "conferences": page_obj,
            "page_obj": page_obj,
            "search_query": search_query,
        }

        return render(request, self.template_name, context)


class ConferenceDetailView(View):
    """View for conference details with papers list (public, no auth required)."""

    template_name = "webApp/conference_detail.html"

    def get(self, request, conference_id):
        """Display conference with its papers, search, and pagination."""

        conference = get_object_or_404(Conference, id=conference_id)
        search_query = request.GET.get("q", "").strip()

        # Get total paper count for this conference (optimized)
        total_papers = Paper.objects.filter(conference=conference).count()

        # Prefetch latest workflow run for each paper (single additional query)
        latest_workflow_prefetch = Prefetch(
            "workflow_runs",
            queryset=WorkflowRun.objects.order_by("-created_at").only(
                "id", "status", "created_at"
            )[:1],
            to_attr="latest_workflow_list",
        )

        # Subquery to get token count from latest completed workflow run
        latest_completed_tokens_subquery = Subquery(
            WorkflowRun.objects.filter(paper_id=OuterRef("pk"), status="completed")
            .order_by("-created_at")
            .values("total_tokens")[:1]
        )

        # Get papers for this conference with workflow stats annotated
        # Use only() to fetch only required fields for better performance
        papers = (
            Paper.objects.filter(conference=conference)
            .select_related("conference")
            .prefetch_related(latest_workflow_prefetch)
            .only("id", "title", "doi", "authors", "conference__id", "conference__name")
            .annotate(
                workflow_count=Count("workflow_runs"),
                latest_run_tokens=latest_completed_tokens_subquery,
            )
        )

        # Compute per-node statistics for this conference
        node_statistics = compute_node_statistics(conference_id)

        # Apply search filter
        if search_query:
            papers = papers.filter(
                Q(title__icontains=search_query)
                | Q(doi__icontains=search_query)
                | Q(authors__icontains=search_query)
            )

        # Order by title
        papers = papers.order_by("title")

        # Pagination - paginate BEFORE accessing the data
        paginator = Paginator(papers, 25)  # 25 papers per page
        page_number = request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)

        context = {
            "conference": conference,
            "papers": page_obj,
            "page_obj": page_obj,
            "search_query": search_query,
            "total_papers": total_papers,  # Pre-calculated count
            "node_statistics": node_statistics,  # Per-node token statistics
        }

        return render(request, self.template_name, context)


class ConferencePaperStatusView(View):
    """API view to get current status of papers in a conference (for auto-refresh)."""

    def get(self, request, conference_id):
        """Return current workflow statuses for papers in the conference."""

        conference = get_object_or_404(Conference, id=conference_id)

        # Get paper IDs from query parameter (for pagination support)
        paper_ids_param = request.GET.get("paper_ids", "")

        # Prefetch latest workflow run for each paper
        latest_workflow_prefetch = Prefetch(
            "workflow_runs",
            queryset=WorkflowRun.objects.order_by("-created_at").only(
                "id", "status", "created_at"
            )[:1],
            to_attr="latest_workflow_list",
        )

        # Get papers for this conference
        papers = (
            Paper.objects.filter(conference=conference)
            .prefetch_related(latest_workflow_prefetch)
            .only("id")
            .annotate(workflow_count=Count("workflow_runs"))
        )

        # Filter by paper IDs if provided
        if paper_ids_param:
            try:
                paper_ids = [
                    int(id.strip()) for id in paper_ids_param.split(",") if id.strip()
                ]
                papers = papers.filter(id__in=paper_ids)
            except ValueError:
                pass  # Ignore invalid paper IDs

        # Build status response
        statuses = {}
        for paper in papers:
            status = "none"
            workflow_count = paper.workflow_count

            if paper.latest_workflow_list:
                status = paper.latest_workflow_list[0].status

            statuses[str(paper.id)] = {
                "status": status,
                "workflow_count": workflow_count,
            }

        return JsonResponse({"statuses": statuses})


class ConferenceNodeStatisticsView(View):
    """API view to get per-node token statistics for a conference (for auto-refresh)."""

    def get(self, request, conference_id):
        """Return current node statistics for the conference."""
        try:
            conference = get_object_or_404(Conference, id=conference_id)
        except Conference.DoesNotExist:
            return JsonResponse({"error": "Conference not found"}, status=404)

        # Compute node statistics
        node_statistics = compute_node_statistics(conference_id)

        # Format for JSON response
        stats_json = {}
        for node_id, stats in node_statistics.items():
            stats_json[node_id] = {
                "avg_input_tokens": (
                    float(stats["avg_input_tokens"])
                    if stats["avg_input_tokens"] is not None
                    else None
                ),
                "stddev_input_tokens": (
                    float(stats["stddev_input_tokens"])
                    if stats["stddev_input_tokens"] is not None
                    else None
                ),
                "avg_output_tokens": (
                    float(stats["avg_output_tokens"])
                    if stats["avg_output_tokens"] is not None
                    else None
                ),
                "stddev_output_tokens": (
                    float(stats["stddev_output_tokens"])
                    if stats["stddev_output_tokens"] is not None
                    else None
                ),
                "avg_total_tokens": (
                    float(stats["avg_total_tokens"])
                    if stats["avg_total_tokens"] is not None
                    else None
                ),
                "stddev_total_tokens": (
                    float(stats["stddev_total_tokens"])
                    if stats["stddev_total_tokens"] is not None
                    else None
                ),
                "count": stats["count"],
            }

        return JsonResponse({"node_statistics": stats_json})


class ActiveWorkflowsView(View):
    """API view to get currently active workflows (for monitoring concurrency)."""

    def get(self, request):
        """Return current active workflow count and limit."""
        from asgiref.sync import async_to_sync
        from webApp.services.graphs.base_workflow_graph import (
            get_active_workflow_count,
            get_active_workflows,
            MAX_CONCURRENT_WORKFLOWS,
            cleanup_stale_workflows,
        )

        # Clean up stale workflows (older than 30 minutes) - now async
        async_to_sync(cleanup_stale_workflows)(max_age_minutes=30)

        # Get counts and workflows - now async
        active_count = async_to_sync(get_active_workflow_count)()
        active_workflows = async_to_sync(get_active_workflows)()

        return JsonResponse(
            {
                "active_count": active_count,
                "max_concurrent": MAX_CONCURRENT_WORKFLOWS,
                "available_slots": MAX_CONCURRENT_WORKFLOWS - active_count,
                "workflows": active_workflows,
            }
        )


class PaperDetailView(View):
    """View for paper details with workflow visualization (public, no auth required)."""

    template_name = "webApp/paper_detail.html"

    def get(self, request, paper_id):
        """Display paper with workflow diagram and run history."""
        paper = get_object_or_404(Paper, id=paper_id)

        # 1. Fetch all runs AND prefetch all their nodes!
        workflow_runs = list(
            WorkflowRun.objects.filter(paper=paper)
            .select_related("workflow_definition", "created_by")
            .prefetch_related("nodes")  # <-- THIS SAVES YOUR DATABASE
            .order_by("-created_at")
        )

        # 2. Add progress to each run safely (0 extra DB queries)
        for run in workflow_runs:
            run.progress = run.get_progress()

        # 3. Determine which workflow to display in the main view
        workflow_run_id = request.GET.get("workflow_run")
        selected_workflow = None

        if workflow_run_id:
            selected_workflow = next(
                (run for run in workflow_runs if str(run.id) == workflow_run_id), None
            )

        if not selected_workflow and workflow_runs:
            selected_workflow = workflow_runs[0]

        latest_workflow = workflow_runs[0] if workflow_runs else None

        workflow_nodes_json = {}
        workflow_edges = []

        if selected_workflow:
            # Get the nodes for the selected workflow directly from the prefetched list!
            nodes = list(selected_workflow.nodes.all())

            # Build the DAG and Mermaid dictionaries
            dag_structure = selected_workflow.workflow_definition.dag_structure
            workflow_edges = dag_structure.get("edges", [])

            # Create an instant O(1) lookup dictionary
            dag_nodes_dict = {n["id"]: n for n in dag_structure.get("nodes", [])}

            for node in nodes:
                node_def = dag_nodes_dict.get(node.node_id)
                display_name = (
                    node_def.get("name")
                    if node_def and "name" in node_def
                    else node.node_id.replace("_", " ").title()
                )

                workflow_nodes_json[node.node_id] = {
                    "id": str(node.id),
                    "node_id": node.node_id,
                    "display_name": display_name,
                    "status": node.status,
                    "node_type": node.node_type,
                }

        import json

        context = {
            "paper": paper,
            "workflow_runs": workflow_runs,
            "latest_workflow": latest_workflow,
            "selected_workflow": selected_workflow,
            "workflow_nodes_json": json.dumps(workflow_nodes_json),
            "workflow_edges": json.dumps(workflow_edges),
        }

        return render(request, self.template_name, context)


class RerunWorkflowView(View):
    """API view to trigger workflow rerun for a paper."""

    def get(self, request, paper_id):
        """Get available workflows for this paper from database."""
        try:
            paper = Paper.objects.get(id=paper_id)
        except Paper.DoesNotExist:
            return JsonResponse({"error": "Paper not found"}, status=404)

        # Query all active workflow definitions from database
        active_workflows = WorkflowDefinition.objects.filter(is_active=True).order_by(
            "name"
        )

        # Build workflows dict from database
        workflows = {}
        default_workflow_id = None

        for idx, workflow_def in enumerate(active_workflows):
            # Check if workflow has handler information in dag_structure
            handler_info = workflow_def.dag_structure.get("workflow_handler")
            if not handler_info:
                continue  # Skip workflows without handler info

            workflow_id = str(workflow_def.id)
            workflows[workflow_id] = {
                "name": workflow_def.description or workflow_def.name,
                "workflow_name": workflow_def.name,
                "version": workflow_def.version,
                "default": idx == 0,  # First workflow is default
            }

            if idx == 0:
                default_workflow_id = workflow_id

        # Query active LLM model configurations
        active_llm_models = [
            {"model": cfg.model, "visual_name": cfg.visual_name}
            for cfg in LLMModelConfig.objects.filter(is_active=True).order_by(
                "visual_name"
            )
        ]

        return JsonResponse(
            {
                "paper_id": paper_id,
                "paper_title": paper.title,
                "workflows": workflows,
                "default_workflow": default_workflow_id,
                "llm_models": active_llm_models,
            }
        )

    def post(self, request, paper_id):
        """Trigger workflow rerun for the specified paper."""

        logger = logging.getLogger(__name__)

        try:
            paper = Paper.objects.get(id=paper_id)
        except Paper.DoesNotExist:
            return JsonResponse({"error": "Paper not found"}, status=404)

        # Get workflow ID, force_reprocess flag, and model key from request
        workflow_id = request.POST.get("workflow_type")
        force_reprocess = request.POST.get("force_reprocess", "true").lower() == "true"
        model = request.POST.get("model", "")

        if not workflow_id:
            return JsonResponse(
                {"error": "workflow_type is required"},
                status=400,
            )

        # Get workflow definition from database
        try:
            workflow_definition = WorkflowDefinition.objects.get(
                id=workflow_id, is_active=True
            )
        except WorkflowDefinition.DoesNotExist:
            return JsonResponse(
                {"error": f"Workflow not found or not active"},
                status=404,
            )

        # Get handler information from dag_structure
        handler_info = workflow_definition.dag_structure.get("workflow_handler")
        if not handler_info:
            return JsonResponse(
                {"error": "Workflow does not have handler information configured"},
                status=500,
            )

        # Check if there's already a running workflow (with timeout check)
        running_workflow = WorkflowRun.objects.filter(
            paper=paper, status__in=["running", "pending"]
        ).first()

        if running_workflow:
            # Check how long it's been in this status
            last_update = running_workflow.started_at or running_workflow.created_at
            time_since_update = timezone.now() - last_update
            timeout_minutes = 5  # Allow rerun if stuck for more than 5 minutes

            if time_since_update < timedelta(minutes=timeout_minutes):
                minutes_remaining = timeout_minutes - (
                    time_since_update.total_seconds() / 60
                )
                return JsonResponse(
                    {
                        "error": f"A workflow is currently {running_workflow.status}. If stuck, wait {int(minutes_remaining)} more minute(s) and try again.",
                        "workflow_run_id": str(running_workflow.id),
                        "status": running_workflow.status,
                    },
                    status=400,
                )
            else:
                # Workflow is stuck, mark it as failed and allow rerun
                logger.warning(
                    f"Workflow run {running_workflow.id} has been {running_workflow.status} for {time_since_update}. "
                    f"Marking as failed and allowing rerun."
                )
                running_workflow.status = "failed"
                running_workflow.completed_at = timezone.now()
                running_workflow.error_message = (
                    f"Workflow timeout after {time_since_update}"
                )
                running_workflow.save()

                # Also mark all running/pending nodes as failed
                stuck_nodes = WorkflowNode.objects.filter(
                    workflow_run=running_workflow, status__in=["running", "pending"]
                )
                for node in stuck_nodes:
                    node.status = "failed"
                    node.completed_at = timezone.now()
                    node.error_message = f"Node timeout after {time_since_update}"
                    node.save()
                    logger.info(
                        f"Marked stuck node {node.id} ({node.node_id}) as failed"
                    )

        # Enqueue workflow as Celery task (non-blocking, queued for processing)
        try:
            from webApp.tasks import process_paper_workflow_task

            # Resolve model string from model_key.
            # TODO: refactor process_paper_workflow_task (and all downstream node functions)
            # TODO: to accept a full model config dict (model, temperature, reasoning_effort,
            # TODO: api_key_env_var, base_url, …) instead of a plain model name string,
            # TODO: so all settings from LLMModelConfig can be forwarded without hard-coding.
            resolved_model = "gpt-5-nano"  # fallback default
            if model:
                try:
                    llm_cfg = LLMModelConfig.objects.get(model=model, is_active=True)
                    resolved_model = llm_cfg.model
                except LLMModelConfig.DoesNotExist:
                    logger.warning(
                        f"model '{model}' not found or inactive, falling back to default model"
                    )

            # Submit task to Celery queue with selected workflow
            task = process_paper_workflow_task.delay(
                paper_id=paper_id,
                force_reprocess=force_reprocess,
                model=resolved_model,
                workflow_id=workflow_id,  # Pass the selected workflow ID
            )

            logger.info(
                f"Workflow task enqueued for paper {paper_id}, "
                f"workflow: {workflow_definition.description or workflow_definition.name}, "
                f"task_id: {task.id}"
            )

            return JsonResponse(
                {
                    "success": True,
                    "message": f"{workflow_definition.description or workflow_definition.name} queued successfully",
                    "task_id": task.id,
                    "paper_id": paper_id,
                    "workflow_id": str(workflow_definition.id),
                    "workflow_name": workflow_definition.name,
                }
            )

        except Exception as e:
            logger.error(f"Failed to enqueue workflow: {e}", exc_info=True)
            return JsonResponse(
                {"error": f"Failed to queue workflow: {str(e)}", "success": False},
                status=500,
            )


class WorkflowStatusView(View):
    """API view for getting workflow run status (for polling)."""

    def get(self, request, workflow_run_id):
        """Get workflow run status and nodes as JSON."""
        try:
            workflow_run = WorkflowRun.objects.get(id=workflow_run_id)
        except WorkflowRun.DoesNotExist:
            return JsonResponse({"error": "Workflow run not found"}, status=404)

        # Get DAG structure
        dag_structure = workflow_run.workflow_definition.dag_structure

        # Get all nodes
        nodes = WorkflowNode.objects.filter(workflow_run=workflow_run)
        nodes_data = {}

        for node in nodes:
            node_def = next(
                (n for n in dag_structure.get("nodes", []) if n["id"] == node.node_id),
                None,
            )
            display_name = (
                node_def["name"]
                if node_def and "name" in node_def
                else node.node_id.replace("_", " ").title()
            )

            nodes_data[node.node_id] = {
                "id": str(node.id),
                "node_id": node.node_id,
                "display_name": display_name,
                "status": node.status,
                "node_type": node.node_type,
            }

        return JsonResponse(
            {
                "status": workflow_run.status,
                "nodes": nodes_data,
                "updated_at": (
                    workflow_run.started_at or workflow_run.created_at
                ).isoformat(),
            }
        )


class LatestWorkflowStatusView(View):
    """API view for getting the latest workflow run for a paper."""

    def get(self, request, paper_id):
        """Get latest workflow run ID for a paper."""
        try:
            paper = Paper.objects.get(id=paper_id)
        except Paper.DoesNotExist:
            return JsonResponse({"error": "Paper not found"}, status=404)

        # Get the most recent workflow run for this paper
        latest_run = (
            WorkflowRun.objects.filter(paper=paper).order_by("-created_at").first()
        )

        if latest_run:
            return JsonResponse(
                {
                    "workflow_run_id": str(latest_run.id),
                    "status": latest_run.status,
                    "created_at": latest_run.created_at.isoformat(),
                }
            )
        else:
            return JsonResponse(
                {"workflow_run_id": None, "status": None, "created_at": None}
            )


class WorkflowNodeDetailView(View):
    """API view for getting workflow node details (public, no auth required)."""

    def get(self, request, node_id):
        """Get node execution details as JSON."""
        try:
            node = WorkflowNode.objects.get(id=node_id)
        except WorkflowNode.DoesNotExist:
            return JsonResponse({"error": "Node not found"}, status=404)
        except Exception as e:
            return JsonResponse({"error": f"Server error: {str(e)}"}, status=500)

        try:
            # Get node logs
            logs = node.logs.all().order_by("timestamp")
            logs_data = [
                {
                    "level": log.level,
                    "message": log.message,
                    "context": log.context,
                    "timestamp": log.timestamp.isoformat(),
                }
                for log in logs
            ]

            # Get node artifacts
            artifacts = node.artifacts.all()
            artifacts_data = {}
            for artifact in artifacts:
                if artifact.artifact_type == "inline":
                    inline_data = artifact.inline_data

                    # For code_embedding node's result artifact, exclude embedded_files to reduce size
                    # (embeddings are stored in DB, not needed for display)
                    if (
                        node.node_id == "code_embedding"
                        and artifact.name == "result"
                        and inline_data
                    ):
                        inline_data = inline_data.copy()
                        if "embedded_files" in inline_data:
                            inline_data["embedded_files"] = []

                    artifacts_data[artifact.name] = inline_data
                else:
                    artifacts_data[artifact.name] = {
                        "type": artifact.artifact_type,
                        "file_path": artifact.file_path,
                        "url": artifact.url,
                        "mime_type": artifact.mime_type,
                        "size_bytes": artifact.size_bytes,
                        "metadata": artifact.metadata,
                    }

            data = {
                "id": str(node.id),
                "node_id": node.node_id,
                "node_type": node.node_type,
                "handler": node.handler,
                "status": node.status,
                "attempt_count": node.attempt_count,
                "max_retries": node.max_retries,
                "input_data": node.input_data,
                "output_data": node.output_data,
                "artifacts": artifacts_data,
                "error_message": node.error_message,
                "error_traceback": node.error_traceback,
                "celery_task_id": node.celery_task_id,
                "started_at": node.started_at.isoformat() if node.started_at else None,
                "completed_at": (
                    node.completed_at.isoformat() if node.completed_at else None
                ),
                "duration": node.duration,
                "logs": logs_data,
            }

            return JsonResponse(data)
        except Exception as e:
            return JsonResponse(
                {"error": f"Error serializing data: {str(e)}"}, status=500
            )


class RerunSingleNodeView(View):
    """API view to rerun a single node."""

    def post(self, request, node_id):
        """Rerun a single node."""

        logger = logging.getLogger(__name__)

        try:
            node = WorkflowNode.objects.get(id=node_id)
        except WorkflowNode.DoesNotExist:
            return JsonResponse({"error": "Node not found"}, status=404)

        # Check if node is already running (with timeout check)
        if node.status in ["running", "pending"]:
            # Check how long it's been in this status
            last_update = node.started_at or node.created_at
            time_since_update = timezone.now() - last_update
            timeout_minutes = 2  # Allow rerun if stuck for more than 2 minutes

            if time_since_update < timedelta(minutes=timeout_minutes):
                minutes_remaining = timeout_minutes - (
                    time_since_update.total_seconds() / 60
                )
                return JsonResponse(
                    {
                        "error": f"Node is currently {node.status}. If stuck, wait {int(minutes_remaining)} more minute(s) and try again.",
                        "node_id": str(node.id),
                        "status": node.status,
                        "seconds_elapsed": int(time_since_update.total_seconds()),
                    },
                    status=400,
                )
            else:
                # Node is stuck, log warning and allow rerun
                logger.warning(
                    f"Node {node.id} ({node.node_id}) has been {node.status} for {time_since_update}. "
                    f"Allowing force rerun."
                )

        # Update workflow run status to running (since we're rerunning a node)
        workflow_run = node.workflow_run
        original_status = workflow_run.status
        if original_status in ["completed", "failed"]:
            workflow_run.status = "running"
            workflow_run.completed_at = None
            workflow_run.error_message = None
            workflow_run.save(update_fields=["status", "completed_at", "error_message"])
            logger.info(
                f"Workflow run {workflow_run.id} status reset from '{original_status}' to 'running'"
            )

        # Update node status to pending immediately (synchronously)
        node.status = "pending"
        node.started_at = None
        node.completed_at = None
        node.error_message = None
        node.error_traceback = None
        node.save(
            update_fields=[
                "status",
                "started_at",
                "completed_at",
                "error_message",
                "error_traceback",
            ]
        )

        # Clear previous logs and artifacts
        node.logs.all().delete()
        node.artifacts.all().delete()

        logger.info(
            f"Node {node.id} ({node.node_id}) status set to pending, starting background execution"
        )

        # Import here to avoid circular imports
        from webApp.services.graphs.paper_processing_workflow import (
            _workflow_instance,
        )

        def run_node_in_background():
            """Run node in background thread."""

            try:
                logger.info(
                    f"=== Background thread started for node {node.id} ({node.node_id}) ==="
                )
                logger.info(f"Python version: {sys.version}")
                logger.info(f"Starting asyncio event loop...")

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                logger.info(f"Event loop created, executing node...")
                result = loop.run_until_complete(
                    _workflow_instance.execute_a_node(
                        node_uuid=str(node.id), force_reprocess=True, model="gpt-5"
                    )
                )
                logger.info(f"Node execution completed with result: {result}")
                loop.close()
                logger.info(f"=== Background thread finished for node {node.id} ===")
            except Exception as e:
                logger.error(
                    f"=== Background node execution failed: {e} ===", exc_info=True
                )
                # Ensure node status is updated to failed
                try:
                    # Get a fresh connection
                    from django.db import connection

                    connection.close_if_unusable_or_obsolete()

                    failed_node = WorkflowNode.objects.get(id=node.id)
                    failed_node.status = "failed"
                    failed_node.completed_at = timezone.now()
                    failed_node.error_message = f"Background execution failed: {str(e)}"
                    failed_node.save()
                    logger.info(
                        f"Node {node.id} status updated to 'failed' after exception"
                    )
                except Exception as inner_e:
                    logger.error(
                        f"Failed to update node status after error: {inner_e}",
                        exc_info=True,
                    )

        # Start node execution in background thread
        logger.info(
            f"Starting background thread for node {node.id} ({node.node_id})..."
        )
        node_thread = threading.Thread(target=run_node_in_background, daemon=True)
        node_thread.start()
        logger.info(
            f"Background thread started successfully, thread name: {node_thread.name}"
        )

        return JsonResponse(
            {
                "success": True,
                "message": "Node execution started",
                "node_id": str(node.id),
                "node_name": node.node_id,
            }
        )


class RerunFromNodeView(View):
    """API view to rerun workflow starting from a specific node."""

    def post(self, request, node_id):
        """Rerun workflow from the specified node onwards."""

        logger = logging.getLogger(__name__)

        # Get force_reprocess flag from request (default to True)
        force_reprocess = True
        try:
            body = json.loads(request.body) if request.body else {}
            force_reprocess = body.get("force_reprocess", True)
        except json.JSONDecodeError:
            pass

        try:
            node = WorkflowNode.objects.get(id=node_id)
        except WorkflowNode.DoesNotExist:
            return JsonResponse({"error": "Node not found"}, status=404)

        # Get the paper from the workflow run
        paper = node.workflow_run.paper

        # Check if there's already a running workflow for this paper
        running_workflow = WorkflowRun.objects.filter(
            paper=paper, status__in=["running", "pending"]
        ).first()

        if running_workflow:
            return JsonResponse(
                {
                    "error": "A workflow is already running for this paper",
                    "workflow_run_id": str(running_workflow.id),
                },
                status=400,
            )

        logger.info(
            f"Starting workflow rerun from node {node.id} ({node.node_id}) for paper {paper.id}"
        )

        # Import here to avoid circular imports
        from webApp.services.graphs.paper_processing_workflow import (
            _workflow_instance,
        )

        def run_workflow_from_node_in_background():
            """Run workflow from node in background thread."""
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(
                    _workflow_instance.execute_from_node(
                        node_uuid=str(node.id),
                        model="gpt-5",
                        force_reprocess=force_reprocess,
                    )
                )
                loop.close()
            except Exception as e:
                logger.error(
                    f"Background workflow execution failed: {e}", exc_info=True
                )

        # Start workflow in background thread
        workflow_thread = threading.Thread(
            target=run_workflow_from_node_in_background, daemon=True
        )
        workflow_thread.start()

        # Wait briefly for workflow run to be created
        time.sleep(0.5)

        # Get the latest workflow run
        latest_run = (
            WorkflowRun.objects.filter(paper=paper).order_by("-created_at").first()
        )

        if latest_run:
            return JsonResponse(
                {
                    "success": True,
                    "message": f"Workflow started from node {node.node_id}",
                    "workflow_run_id": str(latest_run.id),
                    "run_number": latest_run.run_number,
                    "started_from_node": node.node_id,
                }
            )
        else:
            return JsonResponse(
                {
                    "success": True,
                    "message": f"Workflow started from node {node.node_id}",
                    "workflow_run_id": None,
                    "run_number": None,
                    "started_from_node": node.node_id,
                }
            )


class GenerateHighlightedPDFView(View):
    """API view to generate highlighted PDF with evidence from workflow run."""

    # Color mapping for different criterion categories
    CATEGORY_COLORS = {
        "models": (1.0, 0.8, 0.0),  # Yellow
        "datasets": (0.0, 0.8, 1.0),  # Cyan
        "code": (0.8, 0.0, 1.0),  # Purple
        "reproducibility": (1.0, 0.5, 0.0),  # Orange
        "experiments": (0.0, 1.0, 0.5),  # Green
        "default": (1.0, 1.0, 0.0),  # Yellow (fallback)
    }

    def get(self, request, workflow_run_id):
        """Generate or retrieve highlighted PDF for workflow run."""

        logger = logging.getLogger(__name__)

        try:
            workflow_run = WorkflowRun.objects.get(id=workflow_run_id)
        except WorkflowRun.DoesNotExist:
            return JsonResponse({"error": "Workflow run not found"}, status=404)

        paper = workflow_run.paper

        # Check if paper has a PDF file
        if not paper.file:
            return JsonResponse(
                {"error": "No PDF file available for this paper"}, status=404
            )

        # Check if highlighted PDF artifact already exists in any of the workflow nodes
        existing_artifact = NodeArtifact.objects.filter(
            node__workflow_run=workflow_run,
            name="highlighted_pdf",
            artifact_type="file",
        ).first()

        if existing_artifact and existing_artifact.file:
            # Return the existing highlighted PDF URL
            return JsonResponse(
                {"success": True, "pdf_url": existing_artifact.file.url, "cached": True}
            )

        # Generate the highlighted PDF
        try:
            # Try to get evaluation details from workflow run output_data first
            evaluation_details = workflow_run.output_data.get("evaluation_details", {})

            # If not in output_data, try to find it in NodeArtifacts
            if not evaluation_details:
                # Look for artifacts containing evaluation details in workflow nodes
                artifacts = NodeArtifact.objects.filter(
                    node__workflow_run=workflow_run, artifact_type="inline"
                ).order_by("-created_at")

                for artifact in artifacts:
                    if artifact.inline_data and isinstance(artifact.inline_data, dict):
                        if "evaluation_details" in artifact.inline_data:
                            evaluation_details = artifact.inline_data[
                                "evaluation_details"
                            ]
                            break
                        # Check if the artifact itself is the evaluation details
                        elif "paper_checklist" in artifact.inline_data:
                            evaluation_details = artifact.inline_data
                            break

            if not evaluation_details:
                return JsonResponse(
                    {
                        "error": "No evaluation details found in workflow output or artifacts"
                    },
                    status=400,
                )

            paper_checklist = evaluation_details.get("paper_checklist", {})
            criteria_obj = paper_checklist.get("criteria", {})

            # Handle both direct array and {value: [...]} structures
            if isinstance(criteria_obj, dict):
                criteria = criteria_obj.get("value", [])
            else:
                criteria = criteria_obj if isinstance(criteria_obj, list) else []

            if not criteria:
                return JsonResponse(
                    {"error": "No evaluation criteria found in workflow output"},
                    status=400,
                )

            # Prepare text to highlight with colors
            text_color_map = []
            total_evidence_count = 0
            all_criteria = []
            for criterion in criteria:
                all_criteria.append(criterion.get("criterion_name", "unknown"))
                evidence_text = criterion.get("evidence_text", "")
                category = criterion.get("category", "default")

                # Skip empty evidence
                if not evidence_text or evidence_text.strip() == "":
                    continue

                # Get color for this category
                color = self.CATEGORY_COLORS.get(
                    category, self.CATEGORY_COLORS["default"]
                )
                text_color_map.append((evidence_text, color))
                total_evidence_count += 1
            if not text_color_map:
                return JsonResponse(
                    {"error": "No evidence text found to highlight"}, status=400
                )

            # Generate highlighted PDF
            input_pdf_path = paper.file.path
            output_filename = f"highlighted_{workflow_run.id}.pdf"
            output_pdf_path = os.path.join(tempfile.gettempdir(), output_filename)

            # Open the document
            doc = pymupdf.open(input_pdf_path)
            total_instances = 0
            highlighted_crit = []
            for text_to_search, color in text_color_map:
                for page in doc:
                    # Find the coordinates (quads) of the text to search
                    instances = page.search_for(text_to_search)

                    if len(instances) != 0:
                        total_instances += 1

                    # Apply highlight for each occurrence found
                    for inst in instances:
                        annot = page.add_highlight_annot(inst)
                        annot.set_colors(stroke=color)
                        annot.update()

            # Save the result
            doc.save(output_pdf_path)
            doc.close()

            logger.info(
                f"Generated highlighted PDF with {total_instances} highlights for workflow run {workflow_run.id}"
            )

            # Save as NodeArtifact
            # Find a suitable node to attach the artifact to (prefer last completed node)
            target_node = (
                workflow_run.nodes.filter(status="completed")
                .order_by("-completed_at")
                .first()
            )

            if not target_node:
                # Fallback to any node if no completed nodes
                target_node = workflow_run.nodes.first()

            if not target_node:
                return JsonResponse(
                    {"error": "No nodes found in workflow run to attach artifact"},
                    status=400,
                )

            # Read file content
            with open(output_pdf_path, "rb") as f:
                file_content = f.read()

            # Create NodeArtifact with FileField
            artifact = NodeArtifact.objects.create(
                node=target_node,
                artifact_type="file",
                name="highlighted_pdf",
                mime_type="application/pdf",
                size_bytes=len(file_content),
                metadata={
                    "highlights_found": f"{total_instances}/{total_evidence_count}",
                    "generated_at": timezone.now().isoformat(),
                    "paper_id": paper.id,
                    "workflow_run_id": str(workflow_run.id),
                },
            )

            # Save file to the artifact's file field
            artifact.file.save(output_filename, ContentFile(file_content), save=True)

            # Clean up temp file
            os.remove(output_pdf_path)

            file_url = artifact.file.url

            return JsonResponse(
                {
                    "success": True,
                    "pdf_url": file_url,
                    "cached": False,
                    "highlights_count": total_instances,
                }
            )

        except Exception as e:
            logger.error(f"Error generating highlighted PDF: {e}", exc_info=True)
            return JsonResponse(
                {"error": f"Failed to generate highlighted PDF: {str(e)}"}, status=500
            )


class BulkRerunPreviewView(View):
    """API view to preview papers that will be affected by bulk rerun."""

    def post(self, request, conference_id):
        """Return list of papers that would be affected by bulk rerun."""

        try:
            conference = Conference.objects.get(id=conference_id)
        except Conference.DoesNotExist:
            return JsonResponse({"error": "Conference not found"}, status=404)

        # Parse request data
        limit = None
        if request.body:
            try:
                data = json.loads(request.body)
                limit = data.get("limit")
                if limit:
                    limit = int(limit)
            except (json.JSONDecodeError, ValueError):
                pass

        # Get papers for this conference with latest workflow status
        latest_workflow_prefetch = Prefetch(
            "workflow_runs",
            queryset=WorkflowRun.objects.order_by("-created_at").only(
                "id", "status", "created_at"
            )[:1],
            to_attr="latest_workflow_list",
        )

        papers = (
            Paper.objects.filter(conference=conference)
            .prefetch_related(latest_workflow_prefetch)
            .order_by("id")
        )

        # Apply limit if specified
        if limit and limit > 0:
            papers = papers[:limit]

        # Build paper list
        paper_list = []
        for paper in papers:
            status = "none"
            if paper.latest_workflow_list:
                status = paper.latest_workflow_list[0].status

            paper_list.append(
                {
                    "id": paper.id,
                    "title": paper.title,
                    "authors": (
                        paper.authors[:100] + "..."
                        if paper.authors and len(paper.authors) > 100
                        else paper.authors
                    ),
                    "status": status,
                }
            )

        return JsonResponse(
            {"success": True, "papers": paper_list, "total": len(paper_list)}
        )


class BulkRerunWorkflowsView(View):
    """API view to trigger workflow reruns for all papers in a conference."""

    def post(self, request, conference_id):
        """Trigger workflow reruns for all papers in the specified conference."""

        logger = logging.getLogger(__name__)

        try:
            conference = Conference.objects.get(id=conference_id)
        except Conference.DoesNotExist:
            return JsonResponse({"error": "Conference not found"}, status=404)

        # Parse request data
        limit = None
        workflow_id = None
        force_reprocess = True  # Default to True for backward compatibility
        if request.body:
            try:
                data = json.loads(request.body)
                limit = data.get("limit")
                if limit:
                    limit = int(limit)
                workflow_id = data.get("workflow_id")
                force_reprocess = data.get("force_reprocess", True)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"Failed to parse request data: {e}")

        # Validate workflow_id is provided
        if not workflow_id:
            return JsonResponse({"error": "workflow_id is required"}, status=400)

        # Validate workflow exists and is active
        try:
            workflow_definition = WorkflowDefinition.objects.get(
                id=workflow_id, is_active=True
            )
        except WorkflowDefinition.DoesNotExist:
            return JsonResponse(
                {"error": f"Workflow not found or not active"}, status=404
            )

        # Get papers for this conference
        papers = Paper.objects.filter(conference=conference)

        # Apply limit if specified
        if limit and limit > 0:
            papers = papers[:limit]

        papers = list(papers)  # Convert to list for iteration
        total_papers = len(papers)

        if total_papers == 0:
            return JsonResponse(
                {"error": "No papers found for this conference"}, status=400
            )

        # Clean up ALL running/pending workflows for these papers (forced cleanup for bulk rerun)
        stuck_workflows_cleaned = 0
        for paper in papers:
            # Get ALL running or pending workflows for this paper
            running_workflows = WorkflowRun.objects.filter(
                paper=paper, status__in=["running", "pending"]
            )

            for running_workflow in running_workflows:
                last_update = running_workflow.started_at or running_workflow.created_at
                time_since_update = timezone.now() - last_update

                # Force cleanup for bulk rerun (mark as cancelled regardless of time)
                logger.warning(
                    f"Cancelling workflow {running_workflow.id} for paper {paper.id} "
                    f"(time since update: {time_since_update}) for bulk rerun"
                )
                running_workflow.status = "failed"
                running_workflow.completed_at = timezone.now()
                running_workflow.error_message = f"Workflow cancelled for bulk rerun"
                running_workflow.save()

                # Also mark all running/pending nodes as failed
                stuck_nodes = WorkflowNode.objects.filter(
                    workflow_run=running_workflow,
                    status__in=["running", "pending"],
                )
                for node in stuck_nodes:
                    node.status = "failed"
                    node.completed_at = timezone.now()
                    node.error_message = "Node cancelled for bulk rerun"
                    node.save()

                stuck_workflows_cleaned += 1

        # Enqueue all workflow tasks to Celery (they'll be processed when workers are available)
        from webApp.tasks import process_paper_workflow_task

        paper_ids = [p.id for p in papers]
        logger.info(
            f"Enqueueing {total_papers} workflow tasks for conference {conference_id}: {paper_ids} "
            f"(workflow: {workflow_definition.name} v{workflow_definition.version})"
        )

        task_ids = []
        for idx, paper in enumerate(papers, 1):
            try:
                task = process_paper_workflow_task.delay(
                    paper_id=paper.id,
                    force_reprocess=force_reprocess,
                    model="gpt-5",
                    workflow_id=workflow_id,  # Pass the selected workflow ID
                )
                task_ids.append(str(task.id))
                logger.info(
                    f"[{idx}/{total_papers}] Enqueued workflow task for paper {paper.id}: {task.id} (workflow: {workflow_id})"
                )
            except Exception as e:
                logger.error(
                    f"[{idx}/{total_papers}] Failed to enqueue task for paper {paper.id}: {e}",
                    exc_info=True,
                )

        logger.info(
            f"Successfully enqueued {len(task_ids)} workflow tasks for conference {conference_id} "
            f"(workflow: {workflow_definition.name} v{workflow_definition.version})"
        )

        message = f"{len(task_ids)} workflow task{'s' if len(task_ids) != 1 else ''} queued for processing"
        message += (
            f" using '{workflow_definition.description or workflow_definition.name}'"
        )
        if limit and limit > 0:
            message += f" (limited to {limit})"

        # Get concurrency info
        from webApp.services.graphs.paper_processing_workflow import (
            MAX_CONCURRENT_WORKFLOWS,
        )

        message += (
            f". Celery workers will process {MAX_CONCURRENT_WORKFLOWS} at a time."
        )

        return JsonResponse(
            {
                "success": True,
                "message": message,
                "total_papers": total_papers,
                "tasks_enqueued": len(task_ids),
                "task_ids": task_ids,
                "stuck_cleaned": stuck_workflows_cleaned,
                "limit": limit,
                "max_concurrent": MAX_CONCURRENT_WORKFLOWS,
            }
        )


class BulkStopWorkflowsView(View):
    """API view to stop all running workflows for a conference."""

    def post(self, request, conference_id):
        """Stop all running and pending workflows for the specified conference."""
        from celery import current_app

        logger = logging.getLogger(__name__)

        try:
            conference = Conference.objects.get(id=conference_id)
        except Conference.DoesNotExist:
            return JsonResponse({"error": "Conference not found"}, status=404)

        # Get all papers for this conference
        papers = Paper.objects.filter(conference=conference)
        paper_ids = list(papers.values_list("id", flat=True))

        if not paper_ids:
            return JsonResponse(
                {"error": "No papers found for this conference"}, status=400
            )

        # Cancel all running/pending workflows for these papers
        cancelled_workflows = 0
        running_workflows = WorkflowRun.objects.filter(
            paper__in=papers, status__in=["running", "pending"]
        )

        for running_workflow in running_workflows:
            logger.info(
                f"Cancelling workflow {running_workflow.id} for paper {running_workflow.paper.id}"
            )
            running_workflow.status = "failed"
            running_workflow.completed_at = timezone.now()
            running_workflow.error_message = "Workflow cancelled by user (bulk stop)"
            running_workflow.save()

            # Also mark all running/pending nodes as failed
            stuck_nodes = WorkflowNode.objects.filter(
                workflow_run=running_workflow,
                status__in=["running", "pending"],
            )
            for node in stuck_nodes:
                node.status = "failed"
                node.completed_at = timezone.now()
                node.error_message = "Node cancelled (bulk stop)"
                node.save()

            cancelled_workflows += 1

        # Purge all pending tasks from Celery queue
        try:
            purged_count = current_app.control.purge()
            logger.info(f"Purged {purged_count} pending tasks from Celery queue")
        except Exception as e:
            logger.error(f"Failed to purge Celery queue: {e}", exc_info=True)
            purged_count = 0

        message = f"Successfully stopped {cancelled_workflows} workflow{'s' if cancelled_workflows != 1 else ''}"
        if purged_count > 0:
            message += f" and removed {purged_count} pending task{'s' if purged_count != 1 else ''} from queue"

        logger.info(
            f"Bulk stop completed for conference {conference_id}: "
            f"{cancelled_workflows} workflows cancelled, {purged_count} tasks purged"
        )

        return JsonResponse(
            {
                "success": True,
                "message": message,
                "cancelled_workflows": cancelled_workflows,
                "purged_tasks": purged_count,
                "conference_id": conference_id,
            }
        )
