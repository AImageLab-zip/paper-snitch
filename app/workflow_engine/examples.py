"""
Example integration showing how to use the workflow engine
in your existing webApp views and services.
"""

# ============================================================================
# EXAMPLE 1: Trigger workflow from a view
# ============================================================================

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from webApp.models import Paper
from workflow_engine.tasks import start_workflow_task
from workflow_engine.models import WorkflowRun


@login_required
def analyze_paper_view(request, paper_id):
    """
    View to start a workflow for a paper.
    """
    paper = get_object_or_404(Paper, id=paper_id)
    
    # Check if there's already a running workflow
    existing_run = WorkflowRun.objects.filter(
        paper=paper,
        status__in=['pending', 'running']
    ).first()
    
    if existing_run:
        messages.warning(
            request,
            f'Analysis already in progress (Run ID: {existing_run.id})'
        )
        return redirect('workflow_status_view', run_id=existing_run.id)
    
    # Start new workflow
    result = start_workflow_task.delay(
        workflow_name='pdf_analysis_pipeline',
        paper_id=paper.id,
        input_data={
            'requested_by': request.user.username,
            'priority': request.POST.get('priority', 'normal'),
            'custom_options': {
                'enable_deep_analysis': True,
                'include_repo_scan': True
            }
        },
        user_id=request.user.id
    )
    
    messages.success(
        request,
        f'Analysis started! Task ID: {result.id}'
    )
    
    return redirect('paper_detail', paper_id=paper.id)


@login_required
def workflow_status_view(request, run_id):
    """
    View to show workflow status and progress.
    """
    run = get_object_or_404(WorkflowRun, id=run_id)
    
    # Get progress
    progress = run.get_progress()
    
    # Get node details
    nodes = run.nodes.select_related().order_by('created_at')
    
    context = {
        'workflow_run': run,
        'paper': run.paper,
        'progress': progress,
        'nodes': nodes,
        'is_complete': run.status in ['completed', 'failed', 'cancelled'],
    }
    
    # If completed, get results
    if run.status == 'completed':
        from workflow_engine.utils import get_workflow_results
        results = get_workflow_results(run)
        context['results'] = results
    
    return render(request, 'workflow/status.html', context)


# ============================================================================
# EXAMPLE 2: Automatic workflow trigger on paper upload
# ============================================================================

from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=Paper)
def auto_start_analysis(sender, instance, created, **kwargs):
    """
    Automatically start workflow when a new paper is uploaded.
    """
    if created and instance.file:  # New paper with PDF
        # Start workflow asynchronously
        start_workflow_task.delay(
            workflow_name='pdf_analysis_pipeline',
            paper_id=instance.id,
            input_data={
                'auto_triggered': True,
                'trigger_source': 'paper_upload'
            }
        )


# ============================================================================
# EXAMPLE 3: API endpoint for workflow management
# ============================================================================

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http_status


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def start_analysis_api(request):
    """
    API endpoint to start a workflow.
    
    POST /api/workflow/start/
    Body: {
        "paper_id": 123,
        "workflow_name": "pdf_analysis_pipeline",
        "input_data": {...}
    }
    """
    paper_id = request.data.get('paper_id')
    workflow_name = request.data.get('workflow_name', 'pdf_analysis_pipeline')
    input_data = request.data.get('input_data', {})
    
    try:
        paper = Paper.objects.get(id=paper_id)
    except Paper.DoesNotExist:
        return Response(
            {'error': 'Paper not found'},
            status=http_status.HTTP_404_NOT_FOUND
        )
    
    # Start workflow
    result = start_workflow_task.delay(
        workflow_name=workflow_name,
        paper_id=paper.id,
        input_data=input_data,
        user_id=request.user.id
    )
    
    return Response({
        'task_id': result.id,
        'message': 'Workflow started',
        'paper_id': paper.id
    }, status=http_status.HTTP_202_ACCEPTED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def workflow_status_api(request, run_id):
    """
    API endpoint to get workflow status.
    
    GET /api/workflow/status/<run_id>/
    """
    try:
        run = WorkflowRun.objects.get(id=run_id)
    except WorkflowRun.DoesNotExist:
        return Response(
            {'error': 'Workflow run not found'},
            status=http_status.HTTP_404_NOT_FOUND
        )
    
    progress = run.get_progress()
    
    data = {
        'id': str(run.id),
        'status': run.status,
        'paper': {
            'id': run.paper.id,
            'title': run.paper.title
        },
        'progress': progress,
        'created_at': run.created_at,
        'started_at': run.started_at,
        'completed_at': run.completed_at,
        'duration': run.duration,
        'error': run.error_message
    }
    
    # Include results if completed
    if run.status == 'completed':
        from workflow_engine.utils import get_workflow_results
        data['results'] = get_workflow_results(run)
    
    return Response(data)


# ============================================================================
# EXAMPLE 4: Custom workflow for specific analysis type
# ============================================================================

from workflow_engine.services.orchestrator import WorkflowOrchestrator


def run_quick_scan(paper, user=None):
    """
    Run a quick scan workflow (subset of full analysis).
    """
    orchestrator = WorkflowOrchestrator()
    
    # You would create a separate workflow definition for this
    # For now, using the same workflow but with custom input
    workflow_run = orchestrator.create_workflow_run(
        workflow_name='pdf_analysis_pipeline',
        paper=paper,
        input_data={
            'mode': 'quick_scan',
            'skip_repo_analysis': True,
            'quick_mode': True
        },
        user=user
    )
    
    # Start it
    workflow_run.status = 'running'
    workflow_run.save()
    
    return workflow_run


# ============================================================================
# EXAMPLE 5: Batch processing multiple papers
# ============================================================================

from celery import group


def batch_analyze_papers(paper_ids, user=None):
    """
    Analyze multiple papers in parallel.
    """
    # Create a group of tasks
    jobs = group(
        start_workflow_task.s(
            workflow_name='pdf_analysis_pipeline',
            paper_id=paper_id,
            input_data={'batch': True},
            user_id=user.id if user else None
        )
        for paper_id in paper_ids
    )
    
    # Execute in parallel
    result = jobs.apply_async()
    
    return {
        'job_count': len(paper_ids),
        'group_id': result.id
    }


# ============================================================================
# EXAMPLE 6: Integration with existing AnalysisTask
# ============================================================================

from webApp.models import AnalysisTask


def migrate_analysis_task_to_workflow(analysis_task_id):
    """
    Migrate an old AnalysisTask to the new workflow system.
    
    This is useful for gradual migration.
    """
    try:
        analysis_task = AnalysisTask.objects.get(id=analysis_task_id)
    except AnalysisTask.DoesNotExist:
        return {'error': 'AnalysisTask not found'}
    
    # Start equivalent workflow
    result = start_workflow_task.delay(
        workflow_name='pdf_analysis_pipeline',
        paper_id=analysis_task.paper.id,
        input_data={
            'migrated_from_analysis_task': str(analysis_task.id),
            'selected_models': analysis_task.selected_models
        },
        user_id=analysis_task.user.id if analysis_task.user else None
    )
    
    # Mark old task as migrated
    analysis_task.status = 'migrated_to_workflow'
    analysis_task.save()
    
    return {
        'old_task_id': str(analysis_task.id),
        'new_task_id': result.id,
        'status': 'migrated'
    }


# ============================================================================
# EXAMPLE 7: Webhook notification on workflow completion
# ============================================================================

from django.db.models.signals import post_save
from django.dispatch import receiver
from workflow_engine.models import WorkflowRun
import requests


@receiver(post_save, sender=WorkflowRun)
def notify_on_workflow_completion(sender, instance, **kwargs):
    """
    Send webhook when workflow completes.
    """
    if instance.status == 'completed' and instance.completed_at:
        # Get results
        from workflow_engine.utils import get_workflow_results
        results = get_workflow_results(instance)
        
        # Send webhook
        webhook_url = 'https://your-webhook-endpoint.com/workflow-complete'
        
        try:
            requests.post(webhook_url, json={
                'workflow_run_id': str(instance.id),
                'paper_id': instance.paper.id,
                'paper_title': instance.paper.title,
                'status': instance.status,
                'final_score': results.get('final_score'),
                'completed_at': instance.completed_at.isoformat()
            }, timeout=10)
        except Exception as e:
            # Log error but don't fail
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f'Webhook notification failed: {e}')


# ============================================================================
# EXAMPLE 8: Admin action to retry failed workflows
# ============================================================================

from django.contrib import admin
from workflow_engine.models import WorkflowRun
from workflow_engine.utils import retry_failed_nodes


class WorkflowRunAdmin(admin.ModelAdmin):
    actions = ['retry_failed_workflows']
    
    def retry_failed_workflows(self, request, queryset):
        """
        Admin action to retry failed workflows.
        """
        count = 0
        for workflow_run in queryset.filter(status='failed'):
            retried = retry_failed_nodes(workflow_run)
            if retried > 0:
                count += 1
        
        self.message_user(
            request,
            f'Retried {count} workflows with failed nodes.'
        )
    
    retry_failed_workflows.short_description = 'Retry failed workflows'
