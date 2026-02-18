import tempfile
import os
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.views import LoginView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib import messages
from django.http import JsonResponse
from django.views import View
from django.core.paginator import Paginator
from django.db.models import Q, Count, Max, Prefetch
from webApp.models import Operations, Analysis, BugReport, Paper, Conference

from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import time
from django.shortcuts import render, redirect
from .functions import get_pdf_content

from .tasks import (
    run_analysis_celery_task,
    get_task_status,
    create_analysis_task,
    cleanup_task,
    get_available_models,
)

# Import workflow models
from workflow_engine.models import WorkflowRun, WorkflowNode


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

            paper = Paper.objects.create(title=title, text=text, sections=sections, file=pdf_content)
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
        import json

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
            from django.shortcuts import get_object_or_404

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


class ConferenceListView(View):
    """View for listing all conferences (public, no auth required)."""

    template_name = "webApp/conference_list.html"

    def get(self, request):
        """Display conferences with search and pagination."""
        search_query = request.GET.get('q', '').strip()
        
        # Start with all conferences
        conferences = Conference.objects.all()
        
        # Annotate with paper count
        conferences = conferences.annotate(paper_count=Count('papers'))
        
        # Apply search filter
        if search_query:
            conferences = conferences.filter(
                Q(name__icontains=search_query) | 
                Q(year__icontains=search_query)
            )
        
        # Order by year (latest first), then by name
        conferences = conferences.order_by('-year', 'name')
        
        # Pagination
        paginator = Paginator(conferences, 20)  # 20 conferences per page
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        
        context = {
            'conferences': page_obj,
            'page_obj': page_obj,
            'search_query': search_query,
        }
        
        return render(request, self.template_name, context)


class ConferenceDetailView(View):
    """View for conference details with papers list (public, no auth required)."""

    template_name = "webApp/conference_detail.html"

    def get(self, request, conference_id):
        """Display conference with its papers, search, and pagination."""
        from django.db.models import Count, Prefetch
        from django.core.paginator import Paginator
        
        conference = get_object_or_404(Conference, id=conference_id)
        search_query = request.GET.get('q', '').strip()
        
        # Get total paper count for this conference (optimized)
        total_papers = Paper.objects.filter(conference=conference).count()
        
        # Prefetch latest workflow run for each paper (single additional query)
        latest_workflow_prefetch = Prefetch(
            'workflow_runs',
            queryset=WorkflowRun.objects.order_by('-created_at').only('id', 'status', 'created_at')[:1],
            to_attr='latest_workflow_list'
        )
        
        # Get papers for this conference with workflow stats annotated
        # Use only() to fetch only required fields for better performance
        papers = Paper.objects.filter(
            conference=conference
        ).select_related(
            'conference'
        ).prefetch_related(
            latest_workflow_prefetch
        ).only(
            'id', 'title', 'doi', 'authors', 'conference__id', 'conference__name'
        ).annotate(
            workflow_count=Count('workflow_runs')
        )
        
        # Apply search filter
        if search_query:
            papers = papers.filter(
                Q(title__icontains=search_query) |
                Q(doi__icontains=search_query) |
                Q(authors__icontains=search_query)
            )
        
        # Order by title
        papers = papers.order_by('title')
        
        # Pagination - paginate BEFORE accessing the data
        paginator = Paginator(papers, 25)  # 25 papers per page
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        
        context = {
            'conference': conference,
            'papers': page_obj,
            'page_obj': page_obj,
            'search_query': search_query,
            'total_papers': total_papers,  # Pre-calculated count
        }
        
        return render(request, self.template_name, context)


class PaperDetailView(View):
    """View for paper details with workflow visualization (public, no auth required)."""

    template_name = "webApp/paper_detail.html"

    def get(self, request, paper_id):
        """Display paper with workflow diagram and run history."""
        paper = get_object_or_404(Paper, id=paper_id)
        
        # Get all workflow runs for this paper
        workflow_runs = WorkflowRun.objects.filter(paper=paper).select_related(
            'workflow_definition', 'created_by'
        ).order_by('-created_at')
        
        # Add progress to each run
        for run in workflow_runs:
            run.progress = run.get_progress()
        
        # Get the workflow run to display (from URL parameter or latest)
        workflow_run_id = request.GET.get('workflow_run')
        if workflow_run_id:
            try:
                selected_workflow = WorkflowRun.objects.get(id=workflow_run_id, paper=paper)
            except WorkflowRun.DoesNotExist:
                # If invalid ID, fall back to latest
                selected_workflow = workflow_runs.first()
        else:
            selected_workflow = workflow_runs.first()
        
        # Get latest workflow run for comparison for comparison
        latest_workflow = workflow_runs.first()
        workflow_nodes_json = {}
        workflow_edges = []
        
        if selected_workflow:
            # Get the DAG structure from the workflow definition
            dag_structure = selected_workflow.workflow_definition.dag_structure
            workflow_edges = dag_structure.get('edges', [])
            
            # Get all nodes for this workflow run
            nodes = WorkflowNode.objects.filter(workflow_run=selected_workflow)
            
            # Build nodes dictionary for Mermaid
            for node in nodes:
                # Get display name from DAG structure
                node_def = next(
                    (n for n in dag_structure.get('nodes', []) if n['id'] == node.node_id),
                    None
                )
                display_name = node_def['name'] if node_def and 'name' in node_def else node.node_id.replace('_', ' ').title()
                
                workflow_nodes_json[node.node_id] = {
                    'id': str(node.id),
                    'node_id': node.node_id,
                    'display_name': display_name,
                    'status': node.status,
                    'node_type': node.node_type,
                }
        
        import json
        context = {
            'paper': paper,
            'workflow_runs': workflow_runs,
            'latest_workflow': latest_workflow,
            'selected_workflow': selected_workflow,
            'workflow_nodes_json': json.dumps(workflow_nodes_json),
            'workflow_edges': json.dumps(workflow_edges),
        }
        
        return render(request, self.template_name, context)


class RerunWorkflowView(View):
    """API view to trigger workflow rerun for a paper."""

    def post(self, request, paper_id):
        """Trigger workflow rerun for the specified paper."""
        from django.utils import timezone
        from datetime import timedelta
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            paper = Paper.objects.get(id=paper_id)
        except Paper.DoesNotExist:
            return JsonResponse({'error': 'Paper not found'}, status=404)
        
        # Import here to avoid circular imports
        from webApp.services.paper_processing_workflow import process_paper_workflow
        import asyncio
        
        # Check if there's already a running workflow (with timeout check)
        running_workflow = WorkflowRun.objects.filter(
            paper=paper,
            status__in=['running', 'pending']
        ).first()
        
        if running_workflow:
            # Check how long it's been in this status
            last_update = running_workflow.started_at or running_workflow.created_at
            time_since_update = timezone.now() - last_update
            timeout_minutes = 5  # Allow rerun if stuck for more than 5 minutes
            
            if time_since_update < timedelta(minutes=timeout_minutes):
                minutes_remaining = timeout_minutes - (time_since_update.total_seconds() / 60)
                return JsonResponse({
                    'error': f'A workflow is currently {running_workflow.status}. If stuck, wait {int(minutes_remaining)} more minute(s) and try again.',
                    'workflow_run_id': str(running_workflow.id),
                    'status': running_workflow.status
                }, status=400)
            else:
                # Workflow is stuck, mark it as failed and allow rerun
                logger.warning(
                    f"Workflow run {running_workflow.id} has been {running_workflow.status} for {time_since_update}. "
                    f"Marking as failed and allowing rerun."
                )
                running_workflow.status = 'failed'
                running_workflow.completed_at = timezone.now()
                running_workflow.error_message = f"Workflow timeout after {time_since_update}"
                running_workflow.save()
                
                # Also mark all running/pending nodes as failed
                stuck_nodes = WorkflowNode.objects.filter(
                    workflow_run=running_workflow,
                    status__in=['running', 'pending']
                )
                for node in stuck_nodes:
                    node.status = 'failed'
                    node.completed_at = timezone.now()
                    node.error_message = f"Node timeout after {time_since_update}"
                    node.save()
                    logger.info(f"Marked stuck node {node.id} ({node.node_id}) as failed")
        
        # Trigger workflow in background (non-blocking)
        try:
            import threading
            
            def run_workflow_in_background():
                """Run workflow in background thread."""
                try:
                    logger.info(f"Starting background workflow for paper {paper_id}")
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(
                        process_paper_workflow(
                            paper_id=paper_id,
                            force_reprocess=True,
                            model='gpt-4o'
                        )
                    )
                    loop.close()
                    logger.info(f"Background workflow completed for paper {paper_id}")
                except Exception as e:
                    logger.error(f"Background workflow execution failed: {e}", exc_info=True)
            
            # Start workflow in background thread
            workflow_thread = threading.Thread(target=run_workflow_in_background, daemon=True)
            workflow_thread.start()
            logger.info(f"Background workflow thread started for paper {paper_id}")
            
            # Get the workflow run that will be created (wait a moment for it to be created)
            import time
            time.sleep(0.5)  # Brief wait for workflow run to be created
            
            # Get the latest workflow run (should be the one we just started)
            latest_run = WorkflowRun.objects.filter(paper=paper).order_by('-created_at').first()
            
            if latest_run:
                return JsonResponse({
                    'success': True,
                    'message': 'Workflow started successfully',
                    'workflow_run_id': str(latest_run.id),
                    'run_number': latest_run.run_number
                })
            else:
                return JsonResponse({
                    'success': True,
                    'message': 'Workflow started successfully',
                    'workflow_run_id': None,
                    'run_number': None
                })
                
        except Exception as e:
            logger.error(f"Failed to start workflow: {e}", exc_info=True)
            return JsonResponse({
                'error': f'Failed to start workflow: {str(e)}',
                'success': False
            }, status=500)


class WorkflowStatusView(View):
    """API view for getting workflow run status (for polling)."""

    def get(self, request, workflow_run_id):
        """Get workflow run status and nodes as JSON."""
        try:
            workflow_run = WorkflowRun.objects.get(id=workflow_run_id)
        except WorkflowRun.DoesNotExist:
            return JsonResponse({'error': 'Workflow run not found'}, status=404)
        
        # Get DAG structure
        dag_structure = workflow_run.workflow_definition.dag_structure
        
        # Get all nodes
        nodes = WorkflowNode.objects.filter(workflow_run=workflow_run)
        nodes_data = {}
        
        for node in nodes:
            node_def = next(
                (n for n in dag_structure.get('nodes', []) if n['id'] == node.node_id),
                None
            )
            display_name = node_def['name'] if node_def and 'name' in node_def else node.node_id.replace('_', ' ').title()
            
            nodes_data[node.node_id] = {
                'id': str(node.id),
                'node_id': node.node_id,
                'display_name': display_name,
                'status': node.status,
                'node_type': node.node_type,
            }
        
        return JsonResponse({
            'status': workflow_run.status,
            'nodes': nodes_data,
            'updated_at': (workflow_run.started_at or workflow_run.created_at).isoformat(),
        })


class WorkflowNodeDetailView(View):
    """API view for getting workflow node details (public, no auth required)."""

    def get(self, request, node_id):
        """Get node execution details as JSON."""
        try:
            node = WorkflowNode.objects.get(id=node_id)
        except WorkflowNode.DoesNotExist:
            return JsonResponse({'error': 'Node not found'}, status=404)
        except Exception as e:
            return JsonResponse({'error': f'Server error: {str(e)}'}, status=500)
        
        try:
            # Get node logs
            logs = node.logs.all().order_by('timestamp')
            logs_data = [
                {
                    'level': log.level,
                    'message': log.message,
                    'context': log.context,
                    'timestamp': log.timestamp.isoformat()
                }
                for log in logs
            ]
            
            # Get node artifacts
            artifacts = node.artifacts.all()
            artifacts_data = {}
            for artifact in artifacts:
                if artifact.artifact_type == 'inline':
                    artifacts_data[artifact.name] = artifact.inline_data
                else:
                    artifacts_data[artifact.name] = {
                        'type': artifact.artifact_type,
                        'file_path': artifact.file_path,
                        'url': artifact.url,
                        'mime_type': artifact.mime_type,
                        'size_bytes': artifact.size_bytes,
                        'metadata': artifact.metadata
                    }
            
            data = {
                'id': str(node.id),
                'node_id': node.node_id,
                'node_type': node.node_type,
                'handler': node.handler,
                'status': node.status,
                'attempt_count': node.attempt_count,
                'max_retries': node.max_retries,
                'input_data': node.input_data,
                'output_data': node.output_data,
                'artifacts': artifacts_data,
                'error_message': node.error_message,
                'error_traceback': node.error_traceback,
                'celery_task_id': node.celery_task_id,
                'started_at': node.started_at.isoformat() if node.started_at else None,
                'completed_at': node.completed_at.isoformat() if node.completed_at else None,
                'duration': node.duration,
                'logs': logs_data,
            }
            
            return JsonResponse(data)
        except Exception as e:
            return JsonResponse({'error': f'Error serializing data: {str(e)}'}, status=500)


class RerunSingleNodeView(View):
    """API view to rerun a single node."""

    def post(self, request, node_id):
        """Rerun a single node."""
        from django.utils import timezone
        from datetime import timedelta
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            node = WorkflowNode.objects.get(id=node_id)
        except WorkflowNode.DoesNotExist:
            return JsonResponse({'error': 'Node not found'}, status=404)
        
        # Check if node is already running (with timeout check)
        if node.status in ['running', 'pending']:
            # Check how long it's been in this status
            last_update = node.started_at or node.created_at
            time_since_update = timezone.now() - last_update
            timeout_minutes = 2  # Allow rerun if stuck for more than 2 minutes
            
            if time_since_update < timedelta(minutes=timeout_minutes):
                minutes_remaining = timeout_minutes - (time_since_update.total_seconds() / 60)
                return JsonResponse({
                    'error': f'Node is currently {node.status}. If stuck, wait {int(minutes_remaining)} more minute(s) and try again.',
                    'node_id': str(node.id),
                    'status': node.status,
                    'seconds_elapsed': int(time_since_update.total_seconds())
                }, status=400)
            else:
                # Node is stuck, log warning and allow rerun
                logger.warning(
                    f"Node {node.id} ({node.node_id}) has been {node.status} for {time_since_update}. "
                    f"Allowing force rerun."
                )
        
        # Update workflow run status to running (since we're rerunning a node)
        workflow_run = node.workflow_run
        original_status = workflow_run.status
        if original_status in ['completed', 'failed']:
            workflow_run.status = 'running'
            workflow_run.completed_at = None
            workflow_run.error_message = None
            workflow_run.save(update_fields=['status', 'completed_at', 'error_message'])
            logger.info(f"Workflow run {workflow_run.id} status reset from '{original_status}' to 'running'")
        
        # Update node status to pending immediately (synchronously)
        node.status = 'pending'
        node.started_at = None
        node.completed_at = None
        node.error_message = None
        node.error_traceback = None
        node.save(update_fields=['status', 'started_at', 'completed_at', 'error_message', 'error_traceback'])
        
        # Clear previous logs and artifacts
        node.logs.all().delete()
        node.artifacts.all().delete()
        
        logger.info(f"Node {node.id} ({node.node_id}) status set to pending, starting background execution")
        
        # Import here to avoid circular imports
        from webApp.services.paper_processing_workflow import execute_single_node_only
        import asyncio
        import threading
        
        def run_node_in_background():
            """Run node in background thread."""
            import sys
            from django.utils import timezone
            try:
                logger.info(f"=== Background thread started for node {node.id} ({node.node_id}) ===")
                logger.info(f"Python version: {sys.version}")
                logger.info(f"Starting asyncio event loop...")
                
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                logger.info(f"Event loop created, executing node...")
                result = loop.run_until_complete(
                    execute_single_node_only(
                        node_uuid=str(node.id),
                        force_reprocess=True,
                        model='gpt-4o'
                    )
                )
                logger.info(f"Node execution completed with result: {result}")
                loop.close()
                logger.info(f"=== Background thread finished for node {node.id} ===")
            except Exception as e:
                logger.error(f"=== Background node execution failed: {e} ===", exc_info=True)
                # Ensure node status is updated to failed
                try:
                    # Get a fresh connection
                    from django.db import connection
                    connection.close_if_unusable_or_obsolete()
                    
                    failed_node = WorkflowNode.objects.get(id=node.id)
                    failed_node.status = 'failed'
                    failed_node.completed_at = timezone.now()
                    failed_node.error_message = f"Background execution failed: {str(e)}"
                    failed_node.save()
                    logger.info(f"Node {node.id} status updated to 'failed' after exception")
                except Exception as inner_e:
                    logger.error(f"Failed to update node status after error: {inner_e}", exc_info=True)
        
        # Start node execution in background thread
        logger.info(f"Starting background thread for node {node.id} ({node.node_id})...")
        node_thread = threading.Thread(target=run_node_in_background, daemon=True)
        node_thread.start()
        logger.info(f"Background thread started successfully, thread name: {node_thread.name}")
        
        return JsonResponse({
            'success': True,
            'message': 'Node execution started',
            'node_id': str(node.id),
            'node_name': node.node_id
        })


class RerunFromNodeView(View):
    """API view to rerun workflow starting from a specific node."""

    def post(self, request, node_id):
        """Rerun workflow from the specified node onwards."""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            node = WorkflowNode.objects.get(id=node_id)
        except WorkflowNode.DoesNotExist:
            return JsonResponse({'error': 'Node not found'}, status=404)
        
        # Get the paper from the workflow run
        paper = node.workflow_run.paper
        
        # Check if there's already a running workflow for this paper
        running_workflow = WorkflowRun.objects.filter(
            paper=paper,
            status__in=['running', 'pending']
        ).first()
        
        if running_workflow:
            return JsonResponse({
                'error': 'A workflow is already running for this paper',
                'workflow_run_id': str(running_workflow.id)
            }, status=400)
        
        logger.info(f"Starting workflow rerun from node {node.id} ({node.node_id}) for paper {paper.id}")
        
        # Import here to avoid circular imports
        from webApp.services.paper_processing_workflow import execute_workflow_from_node
        import asyncio
        import threading
        
        def run_workflow_from_node_in_background():
            """Run workflow from node in background thread."""
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(
                    execute_workflow_from_node(
                        node_uuid=str(node.id),
                        model='gpt-4o'
                    )
                )
                loop.close()
            except Exception as e:
                logger.error(f"Background workflow execution failed: {e}", exc_info=True)
        
        # Start workflow in background thread
        workflow_thread = threading.Thread(target=run_workflow_from_node_in_background, daemon=True)
        workflow_thread.start()
        
        # Wait briefly for workflow run to be created
        import time
        time.sleep(0.5)
        
        # Get the latest workflow run
        latest_run = WorkflowRun.objects.filter(paper=paper).order_by('-created_at').first()
        
        if latest_run:
            return JsonResponse({
                'success': True,
                'message': f'Workflow started from node {node.node_id}',
                'workflow_run_id': str(latest_run.id),
                'run_number': latest_run.run_number,
                'started_from_node': node.node_id
            })
        else:
            return JsonResponse({
                'success': True,
                'message': f'Workflow started from node {node.node_id}',
                'workflow_run_id': None,
                'run_number': None,
                'started_from_node': node.node_id
            })
