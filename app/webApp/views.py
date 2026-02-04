import tempfile
import os
from django.shortcuts import render
from django.contrib.auth.views import LoginView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib import messages
from django.http import JsonResponse
from django.views import View
from webApp.models import Operations, Analysis, BugReport, Paper

from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import time
from django.shortcuts import render, redirect
from .functions import get_pdf_content

from .tasks import run_analysis_celery_task

from webApp.services.llm_analysis import (
    create_analysis_task,
    get_task_status,
    cleanup_task,
    get_available_models,
)


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
                title, text = get_pdf_content(tmp_path)
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
        paper = Paper.objects.filter(title=title).first()

        past_analyses = []

        pdf_url = None

        if paper:

            # Send the URL of the existing PDF so user can check it
            if paper.file:
                pdf_url = paper.file.url

            # Get all analyses for this paper (not just user's)
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

        else:

            # Delete an exsisting file with the same name if exists
            upload_path = Paper._meta.get_field("file").upload_to
            filename = title + ".pdf"
            full_path = os.path.join(upload_path, filename)

            if default_storage.exists(full_path):
                default_storage.delete(full_path)

            # Save new paper
            pdf_file.seek(0)  # Reset file pointer for saving
            pdf_content = ContentFile(pdf_file.read(), name=filename)

            paper = Paper.objects.create(title=title, text=text, file=pdf_content)
            paper.save()

        return JsonResponse(
            {
                "title": title,
                "has_past_analyses": len(past_analyses) > 0,
                "past_analyses": past_analyses,
                "pdf_url": pdf_url,
            }
        )


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


class AnalyzePaperView(View):
    """View for uploading and analyzing PDF papers."""

    template_name = "webApp/analyze.html"

    def get(self, request):
        """Display the upload form with available models."""
        available_models = get_available_models()
        return render(
            request, self.template_name, {"available_models": available_models}
        )

    def post(self, request):
        action = request.POST.get("action")
        """Handle PDF upload and start analysis. Requires login."""
        if not request.user.is_authenticated:
            return JsonResponse(
                {"error": "You must be logged in to analyze papers"}, status=401
            )
        # if "pdf_file" not in request.FILES:
        #     return JsonResponse({"error": "No PDF file provided"}, status=400)

        # pdf_file = request.FILES["pdf_file"]

        # # Validate file type
        # if not pdf_file.name.endswith(".pdf"):
        #     return JsonResponse({"error": "File must be a PDF"}, status=400)

        # Get selected models from request
        selected_models = request.POST.getlist("models")
        if not selected_models:
            return JsonResponse(
                {"error": "Please select at least one model"}, status=400
            )

        # Save the uploaded file
        # paper = upload_pdf(pdf_file)
        # if paper is None:
        #     return JsonResponse({"error": "Failed to upload PDF"}, status=500)

        # Create analysis task with selected models and user

        paper = Paper.objects.get(title=request.POST.get("title"))

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
        from django.shortcuts import get_object_or_404

        paper = get_object_or_404(Paper, id=paper_id)

        # Check if paper has an associated document
        try:
            document = paper.document
        except Paper.document.RelatedObjectDoesNotExist:
            messages.error(request, "No document associated with this paper yet.")
            return redirect("profile")

        # Redirect to the annotator view
        return redirect("annotate_document", pk=document.pk)
