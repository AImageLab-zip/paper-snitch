"""
Celery tasks for workflow orchestration and execution.
"""
import logging
import traceback
from typing import Dict, Any

from celery import shared_task
from django.db import transaction

from workflow_engine.models import WorkflowNode, WorkflowRun
from workflow_engine.services.orchestrator import (
    WorkflowOrchestrator,
    NodeExecutor
)

logger = logging.getLogger(__name__)


def update_workflow_run_status():
    """
    Check and update status of running workflow runs.
    
    Updates runs to 'completed' or 'failed' when all nodes are finished.
    
    Returns:
        Number of workflow runs updated
    """
    from django.db.models import Count, Q
    
    # Get all running workflow runs
    running_runs = WorkflowRun.objects.filter(status='running')
    
    updated_count = 0
    
    for run in running_runs:
        # Get node status counts
        nodes = run.nodes.aggregate(
            total=Count('id'),
            completed=Count('id', filter=Q(status='completed')),
            failed=Count('id', filter=Q(status='failed')),
            skipped=Count('id', filter=Q(status='skipped')),
            running=Count('id', filter=Q(status__in=['running', 'claimed'])),
            pending=Count('id', filter=Q(status__in=['ready', 'pending']))
        )
        
        # Check if all nodes are in a terminal state
        terminal_nodes = nodes['completed'] + nodes['failed'] + nodes['skipped']
        
        if terminal_nodes == nodes['total']:
            # All nodes are done - determine final status
            if nodes['failed'] > 0:
                run.status = 'failed'
                logger.info(f"Workflow run {run.id} marked as failed ({nodes['failed']} failed nodes)")
            else:
                run.status = 'completed'
                logger.info(f"Workflow run {run.id} marked as completed")
            
            run.save(update_fields=['status'])
            updated_count += 1
    
    return updated_count


@shared_task(bind=True, max_retries=0)
def workflow_scheduler_task(self):
    """
    Periodic task that claims ready tasks and dispatches them to workers.
    
    This should be run via Celery Beat on a schedule (e.g., every 10 seconds).
    """
    orchestrator = WorkflowOrchestrator()
    
    # First, update status of any completed/failed workflow runs
    updated_runs = update_workflow_run_status()
    
    # Claim and dispatch up to 100 ready tasks
    dispatched_count = 0
    max_dispatch = 100
    
    while dispatched_count < max_dispatch:
        # Claim a ready task
        node = orchestrator.claim_ready_task(claim_duration_minutes=30)
        
        if not node:
            break  # No more ready tasks
        
        # Dispatch to execution task
        execute_node_task.delay(str(node.id))
        dispatched_count += 1
    
    if dispatched_count > 0:
        logger.info(f"Dispatched {dispatched_count} workflow tasks")
    
    return {
        'dispatched_count': dispatched_count,
        'updated_runs': updated_runs
    }


@shared_task(bind=True, max_retries=3, autoretry_for=(Exception,))
def execute_node_task(self, node_id: str):
    """
    Execute a single workflow node.
    
    Args:
        node_id: UUID of the WorkflowNode to execute
    """
    try:
        node = WorkflowNode.objects.get(id=node_id)
    except WorkflowNode.DoesNotExist:
        logger.error(f"WorkflowNode {node_id} not found")
        return
    
    orchestrator = WorkflowOrchestrator()
    
    # Mark as running
    orchestrator.mark_node_running(node, celery_task_id=self.request.id)
    
    try:
        # Execute the node
        executor = NodeExecutor(node)
        output_data = executor.execute()
        
        # Mark as completed
        orchestrator.mark_node_completed(node, output_data=output_data)
        
        logger.info(f"Successfully executed node {node.node_id}")
        
        return {
            'node_id': node.node_id,
            'status': 'completed',
            'output': output_data
        }
        
    except Exception as e:
        error_msg = str(e)
        error_trace = traceback.format_exc()
        
        logger.error(
            f"Node {node.node_id} failed: {error_msg}\n{error_trace}"
        )
        
        # Mark as failed (will retry if applicable)
        orchestrator.mark_node_failed(
            node,
            error_message=error_msg,
            error_traceback=error_trace,
            retry=True
        )
        
        # Re-raise to trigger Celery retry if configured
        raise


@shared_task
def start_workflow_task(workflow_name: str, paper_id: int, input_data: Dict[str, Any] = None, user_id: int = None):
    """
    Start a new workflow run.
    
    Args:
        workflow_name: Name of the workflow definition
        paper_id: ID of the Paper to process
        input_data: Optional input parameters
        user_id: Optional user ID who initiated the workflow
    """
    from webApp.models import Paper
    from django.contrib.auth.models import User
    
    try:
        paper = Paper.objects.get(id=paper_id)
    except Paper.DoesNotExist:
        logger.error(f"Paper {paper_id} not found")
        return {'error': 'Paper not found'}
    
    user = None
    if user_id:
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            pass
    
    orchestrator = WorkflowOrchestrator()
    
    try:
        workflow_run = orchestrator.create_workflow_run(
            workflow_name=workflow_name,
            paper=paper,
            input_data=input_data,
            user=user
        )
        
        # Update workflow status to running
        workflow_run.status = 'running'
        workflow_run.started_at = timezone.now()
        workflow_run.save(update_fields=['status', 'started_at'])
        
        logger.info(f"Started workflow run {workflow_run.id} for paper {paper.id}")
        
        return {
            'workflow_run_id': str(workflow_run.id),
            'status': 'started'
        }
        
    except Exception as e:
        logger.error(f"Failed to start workflow: {str(e)}")
        return {
            'error': str(e)
        }


@shared_task
def cleanup_stale_claims_task():
    """
    Cleanup stale task claims (tasks claimed but not completed).
    
    This should run periodically via Celery Beat.
    """
    from django.utils import timezone
    
    stale_nodes = WorkflowNode.objects.filter(
        status='claimed',
        claim_expires_at__lt=timezone.now()
    )
    
    count = stale_nodes.count()
    
    if count > 0:
        # Reset stale claims to ready
        stale_nodes.update(
            status='ready',
            claimed_by=None,
            claimed_at=None,
            claim_expires_at=None
        )
        
        logger.warning(f"Reset {count} stale task claims")
    
    return {
        'stale_claims_reset': count
    }


# Import timezone at the top if not already imported
from django.utils import timezone
