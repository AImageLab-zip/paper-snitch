"""
Workflow orchestration service.

Handles workflow lifecycle, dependency resolution, and task claiming
using MySQL row-level locking for distributed execution.
"""
import logging
import socket
from datetime import timedelta
from typing import Optional, List, Dict, Any

from django.db import transaction
from django.utils import timezone
from django.db.models import Q

from workflow_engine.models import (
    WorkflowDefinition,
    WorkflowRun,
    WorkflowNode,
    NodeLog,
)

logger = logging.getLogger(__name__)


class WorkflowOrchestrator:
    """
    Main orchestrator for workflow lifecycle management.
    """
    
    def __init__(self):
        self.hostname = socket.gethostname()
    
    def create_workflow_run(
        self,
        workflow_name: str,
        paper,
        input_data: Dict[str, Any] = None,
        user=None
    ) -> WorkflowRun:
        """
        Create a new workflow run for a paper.
        
        Args:
            workflow_name: Name of the workflow definition
            paper: Paper instance to process
            input_data: Input parameters for the workflow
            user: User initiating the workflow
            
        Returns:
            WorkflowRun instance
        """
        # Get active workflow definition
        try:
            workflow_def = WorkflowDefinition.objects.get(
                name=workflow_name,
                is_active=True
            )
        except WorkflowDefinition.DoesNotExist:
            raise ValueError(f"No active workflow found with name: {workflow_name}")
        
        with transaction.atomic():
            # Create workflow run
            workflow_run = WorkflowRun.objects.create(
                workflow_definition=workflow_def,
                paper=paper,
                input_data=input_data or {},
                created_by=user,
                status='pending'
            )
            
            # Initialize all nodes from definition
            self._initialize_nodes(workflow_run)
            
            # Mark nodes with no dependencies as ready
            self._update_ready_nodes(workflow_run)
            
            logger.info(
                f"Created workflow run {workflow_run.id} for paper {paper.id}"
            )
        
        return workflow_run
    
    def _initialize_nodes(self, workflow_run: WorkflowRun):
        """Initialize all nodes for a workflow run from the definition."""
        nodes_data = workflow_run.workflow_definition.dag_structure.get('nodes', [])
        
        for node_data in nodes_data:
            WorkflowNode.objects.create(
                workflow_run=workflow_run,
                node_id=node_data['id'],
                node_type=node_data.get('type', 'celery'),
                handler=node_data.get('handler', ''),
                max_retries=node_data.get('max_retries', 3),
                input_data=node_data.get('input', {}),
                status='pending'
            )
    
    def _update_ready_nodes(self, workflow_run: WorkflowRun):
        """Mark nodes as ready if their dependencies are met."""
        pending_nodes = workflow_run.nodes.filter(status='pending')
        
        logger.info(f"_update_ready_nodes: Found {pending_nodes.count()} pending nodes for workflow {workflow_run.id}")
        
        for node in pending_nodes:
            logger.info(f"  Checking node {node.node_id}: dependencies_met()={node.dependencies_met()}")
            if node.dependencies_met():
                node.status = 'ready'
                node.save(update_fields=['status'])
                
                logger.info(f"  -> Marked {node.node_id} as READY")
                
                NodeLog.objects.create(
                    node=node,
                    level='INFO',
                    message='Node is ready to execute'
                )
    
    def claim_ready_task(
        self,
        workflow_run_id: Optional[str] = None,
        claim_duration_minutes: int = 30
    ) -> Optional[WorkflowNode]:
        """
        Claim a ready task using MySQL SELECT ... FOR UPDATE SKIP LOCKED.
        
        This ensures only one worker claims a task in a distributed environment.
        
        Args:
            workflow_run_id: Optional specific workflow run to claim from
            claim_duration_minutes: How long the claim is valid
            
        Returns:
            WorkflowNode instance if claimed, None otherwise
        """
        claim_expires_at = timezone.now() + timedelta(minutes=claim_duration_minutes)
        
        with transaction.atomic():
            # Build query for ready tasks
            query = WorkflowNode.objects.filter(
                Q(status='ready') | 
                Q(
                    status='claimed',
                    claim_expires_at__lt=timezone.now()  # Stale claims
                )
            )
            
            if workflow_run_id:
                query = query.filter(workflow_run_id=workflow_run_id)
            
            # Use SELECT FOR UPDATE SKIP LOCKED for distributed claiming
            # This is the key to preventing duplicate work in multi-worker setups
            try:
                node = query.select_for_update(skip_locked=True).first()
            except Exception as e:
                logger.error(f"Error claiming task: {e}")
                return None
            
            if not node:
                return None
            
            # Claim the task
            node.status = 'claimed'
            node.claimed_by = self.hostname
            node.claimed_at = timezone.now()
            node.claim_expires_at = claim_expires_at
            node.save(update_fields=[
                'status', 'claimed_by', 'claimed_at', 'claim_expires_at'
            ])
            
            NodeLog.objects.create(
                node=node,
                level='INFO',
                message=f'Task claimed by {self.hostname}',
                context={'claim_expires_at': claim_expires_at.isoformat()}
            )
            
            logger.info(
                f"Claimed task {node.node_id} from workflow run {node.workflow_run.id}"
            )
        
        return node
    
    def mark_node_running(self, node: WorkflowNode, celery_task_id: str = None):
        """Mark a node as running."""
        with transaction.atomic():
            node.status = 'running'
            node.started_at = timezone.now()
            node.attempt_count += 1
            
            if celery_task_id:
                node.celery_task_id = celery_task_id
            
            node.save(update_fields=[
                'status', 'started_at', 'attempt_count', 'celery_task_id'
            ])
            
            NodeLog.objects.create(
                node=node,
                level='INFO',
                message=f'Node execution started (attempt {node.attempt_count})',
                context={'celery_task_id': celery_task_id}
            )
    
    def mark_node_completed(
        self,
        node: WorkflowNode,
        output_data: Dict[str, Any] = None
    ):
        """Mark a node as completed and trigger downstream nodes."""
        with transaction.atomic():
            # Refresh node to ensure we have latest data (async handlers may have updated it)
            node.refresh_from_db()
            
            node.status = 'completed'
            node.completed_at = timezone.now()
            
            # Only save output_data if node doesn't already have it
            # (NodeExecutor.execute() may have already saved it)
            if output_data and not node.output_data:
                # Serialize Pydantic models to dicts for JSON storage
                from pydantic import BaseModel
                serialized_output = {}
                for key, value in output_data.items():
                    if isinstance(value, BaseModel):
                        serialized_output[key] = value.model_dump()
                    else:
                        serialized_output[key] = value
                node.output_data = serialized_output
            
            node.save(update_fields=['status', 'completed_at', 'output_data'])
            
            NodeLog.objects.create(
                node=node,
                level='INFO',
                message='Node completed successfully',
                context={'duration': node.duration}
            )
            
            # Update downstream dependencies
            workflow_run = node.workflow_run
            self._update_ready_nodes(workflow_run)
            
            # Check if workflow is complete
            self._check_workflow_completion(workflow_run)
    
    def mark_node_failed(
        self,
        node: WorkflowNode,
        error_message: str,
        error_traceback: str = None,
        retry: bool = True
    ):
        """Mark a node as failed and handle retries or propagate failure."""
        with transaction.atomic():
            node.error_message = error_message
            node.error_traceback = error_traceback
            
            if retry and node.can_retry():
                # Reset to ready for retry
                node.status = 'ready'
                node.claimed_by = None
                node.claimed_at = None
                node.claim_expires_at = None
                
                NodeLog.objects.create(
                    node=node,
                    level='WARNING',
                    message=f'Node failed, will retry (attempt {node.attempt_count}/{node.max_retries})',
                    context={'error': error_message}
                )
                
                # Don't cancel siblings or mark workflow as failed yet - node will retry
                
            else:
                # Permanent failure - cancel siblings and mark as failed
                node.status = 'failed'
                node.completed_at = timezone.now()
                
                NodeLog.objects.create(
                    node=node,
                    level='ERROR',
                    message='Node failed permanently',
                    context={'error': error_message}
                )
                
                # Cancel sibling nodes (fail fast on permanent failure)
                self._cancel_sibling_nodes(node)
                
                # Mark downstream nodes as skipped
                self._skip_dependent_nodes(node)
                
                # Check if workflow failed
                self._check_workflow_completion(node.workflow_run)
            
            node.save(update_fields=[
                'status', 'error_message', 'error_traceback',
                'claimed_by', 'claimed_at', 'claim_expires_at', 'completed_at'
            ])
    
    def _cancel_sibling_nodes(self, failed_node: WorkflowNode):
        """Cancel all sibling nodes (running/pending) when a node fails."""
        workflow_run = failed_node.workflow_run
        
        # Get all nodes in the workflow that are not completed and not the failed node
        sibling_nodes = workflow_run.nodes.filter(
            status__in=['running', 'claimed', 'ready', 'pending']
        ).exclude(id=failed_node.id)
        
        for sibling in sibling_nodes:
            sibling.status = 'cancelled'
            sibling.completed_at = timezone.now()
            sibling.save(update_fields=['status', 'completed_at'])
            
            NodeLog.objects.create(
                node=sibling,
                level='WARNING',
                message=f'Node cancelled due to failure in {failed_node.node_id}'
            )
            
            logger.info(
                f"Cancelled node {sibling.node_id} (was {sibling.status}) due to failure in {failed_node.node_id}"
            )
    
    def _skip_dependent_nodes(self, node: WorkflowNode):
        """Mark all downstream nodes as skipped due to upstream failure."""
        dependents = node.get_dependents()
        
        for dependent in dependents:
            if dependent.status in ['pending', 'ready', 'cancelled']:
                dependent.status = 'skipped'
                dependent.save(update_fields=['status'])
                
                NodeLog.objects.create(
                    node=dependent,
                    level='WARNING',
                    message=f'Node skipped due to upstream failure in {node.node_id}'
                )
                
                # Recursively skip further dependents
                self._skip_dependent_nodes(dependent)
    
    def _check_workflow_completion(self, workflow_run: WorkflowRun):
        """Check if workflow is complete and update status."""
        nodes = workflow_run.nodes.all()
        
        logger.info(f"_check_workflow_completion: Checking workflow {workflow_run.id}")
        logger.info(f"  Node statuses: {[(n.node_id, n.status) for n in nodes]}")
        
        # Check if all nodes are in terminal states
        terminal_statuses = ['completed', 'failed', 'skipped', 'cancelled']
        all_terminal = all(node.status in terminal_statuses for node in nodes)
        logger.info(f"  All nodes in terminal states? {all_terminal}")
        
        if all_terminal:
            # Workflow is done
            if all(node.status == 'completed' for node in nodes):
                workflow_run.status = 'completed'
            elif any(node.status == 'failed' for node in nodes):
                workflow_run.status = 'failed'
                
                # Collect error messages
                failed_nodes = nodes.filter(status='failed')
                errors = [f"{n.node_id}: {n.error_message}" for n in failed_nodes]
                workflow_run.error_message = "\n".join(errors)
            else:
                workflow_run.status = 'completed'  # Some skipped/cancelled but no failures
            
            workflow_run.completed_at = timezone.now()
            workflow_run.save(update_fields=[
                'status', 'completed_at', 'error_message'
            ])
            
            logger.info(
                f"Workflow run {workflow_run.id} completed with status: {workflow_run.status}"
            )
    
    def get_next_tasks(
        self,
        limit: int = 10,
        workflow_run_id: Optional[str] = None
    ) -> List[WorkflowNode]:
        """
        Get ready tasks that can be executed.
        
        Args:
            limit: Maximum number of tasks to return
            workflow_run_id: Optional filter for specific workflow run
            
        Returns:
            List of ready WorkflowNode instances
        """
        query = WorkflowNode.objects.filter(status='ready')
        
        if workflow_run_id:
            query = query.filter(workflow_run_id=workflow_run_id)
        
        return list(query[:limit])
    
    def cancel_workflow_run(self, workflow_run: WorkflowRun):
        """Cancel a running workflow."""
        with transaction.atomic():
            workflow_run.status = 'cancelled'
            workflow_run.completed_at = timezone.now()
            workflow_run.save(update_fields=['status', 'completed_at'])
            
            # Cancel pending/ready nodes
            workflow_run.nodes.filter(
                status__in=['pending', 'ready', 'claimed']
            ).update(status='skipped')
            
            logger.info(f"Cancelled workflow run {workflow_run.id}")


class NodeExecutor:
    """
    Executes individual workflow nodes with proper error handling and logging.
    """
    
    def __init__(self, node: WorkflowNode):
        self.node = node
        self.orchestrator = WorkflowOrchestrator()
    
    def execute(self) -> Dict[str, Any]:
        """
        Execute the node's handler and return results.
        
        This should be called from within a Celery task.
        Handles both sync and async handler functions.
        """
        self.log('INFO', 'Starting node execution')
        
        try:
            # Get handler function
            handler_func = self._get_handler()
            
            # Prepare input context
            input_context = self._prepare_input_context()
            
            # Execute handler (handle both sync and async functions)
            import asyncio
            import inspect
            
            if inspect.iscoroutinefunction(handler_func):
                # Async handler - run with asyncio
                result = asyncio.run(handler_func(input_context))
            else:
                # Sync handler - call directly
                result = handler_func(input_context)
            
            # Save output_data if node returned something and hasn't saved it yet
            # (Async nodes mark themselves as completed but don't save output_data)
            if result and isinstance(result, dict):
                self.node.refresh_from_db()
                if not self.node.output_data:
                    # Serialize Pydantic models to dicts for JSON storage
                    from pydantic import BaseModel
                    serialized_result = {}
                    for key, value in result.items():
                        if isinstance(value, BaseModel):
                            serialized_result[key] = value.model_dump()
                        else:
                            serialized_result[key] = value
                    
                    self.node.output_data = serialized_result
                    self.node.save(update_fields=['output_data'])
                    self.log('INFO', f'Saved output_data with keys: {list(serialized_result.keys())}')
            
            self.log('INFO', 'Node execution completed successfully')
            return result
            
        except Exception as e:
            self.log('ERROR', f'Node execution failed: {str(e)}')
            raise
    
    def _get_handler(self):
        """Dynamically import and return the handler function."""
        from importlib import import_module
        
        module_path, func_name = self.node.handler.rsplit('.', 1)
        module = import_module(module_path)
        return getattr(module, func_name)
    
    def _prepare_input_context(self) -> Dict[str, Any]:
        """
        Prepare input context for the node handler.
        
        For async nodes expecting PaperProcessingState, provides:
        - workflow_run_id
        - paper_id  
        - current_node_id
        - client, model (OpenAI)
        - force_reprocess
        - Upstream node outputs (merged into state)
        """
        from openai import OpenAI
        import os
        
        workflow_run = self.node.workflow_run
        
        # Collect outputs from dependencies
        dependencies = self.node.get_dependencies()
        
        # Prepare state matching PaperProcessingState structure
        state = {
            'workflow_run_id': str(workflow_run.id),
            'paper_id': workflow_run.paper.id,
            'current_node_id': self.node.node_id,
            'client': OpenAI(api_key=os.getenv('OPENAI_API_KEY')),
            'model': os.getenv('OPENAI_MODEL', 'gpt-5'),
            'force_reprocess': workflow_run.input_data.get('force_reprocess', False),
        }
        
        # Add upstream outputs to state
        # Each node returns a dict like {'reproducibility_checklist_result': {...}}
        # We merge all these dicts into the state
        # Reconstruct Pydantic models from saved dicts
        from webApp.services.pydantic_schemas import (
            AggregatedReproducibilityAnalysis,
            CodeReproducibilityAnalysis,
            AggregatedDatasetDocumentationAnalysis,
            PaperTypeClassification,
        )
        
        for dep in dependencies:
            if dep.output_data:
                for key, value in dep.output_data.items():
                    # Reconstruct Pydantic models from dicts
                    if isinstance(value, dict):
                        if key == 'reproducibility_checklist_result':
                            state[key] = AggregatedReproducibilityAnalysis(**value)
                        elif key == 'code_reproducibility_result':
                            state[key] = CodeReproducibilityAnalysis(**value)
                        elif key == 'dataset_documentation_result':
                            state[key] = AggregatedDatasetDocumentationAnalysis(**value)
                        elif key == 'paper_type_result':
                            state[key] = PaperTypeClassification(**value)
                        else:
                            state[key] = value
                    else:
                        state[key] = value
        
        return state
    
    def log(self, level: str, message: str, context: Dict = None):
        """Create a log entry for this node."""
        NodeLog.objects.create(
            node=self.node,
            level=level,
            message=message,
            context=context or {}
        )
