"""
Async wrappers for workflow orchestration.

Provides async versions of WorkflowOrchestrator methods for use in
async workflows (e.g., LangGraph-based workflows).

For sync workflows (Celery), use workflow_engine.services.orchestrator directly.
"""
import logging
from typing import Dict, Any, Optional, List
from asgiref.sync import sync_to_async
from django.utils import timezone
from django.db import transaction

from workflow_engine.models import (
    WorkflowDefinition,
    WorkflowRun,
    WorkflowNode,
    NodeArtifact,
    NodeLog,
)
from workflow_engine.services.orchestrator import WorkflowOrchestrator

logger = logging.getLogger(__name__)


class AsyncWorkflowOperations:
    """
    Async wrapper around WorkflowOrchestrator for LangGraph and other async workflows.
    
    All workflow management logic stays in the sync WorkflowOrchestrator.
    These are just async-friendly wrappers for database operations.
    """
    
    def __init__(self):
        self.orchestrator = WorkflowOrchestrator()
    
    @sync_to_async
    def get_or_create_workflow_definition(
        self,
        name: str,
        dag_structure: Dict[str, Any],
        description: str = "",
        version: int = 1
    ) -> WorkflowDefinition:
        """
        Get or create a workflow definition.
        
        Args:
            name: Unique workflow name
            dag_structure: DAG structure with nodes and edges
            description: Workflow description
            version: Version number
            
        Returns:
            WorkflowDefinition instance
        """
        workflow, created = WorkflowDefinition.objects.get_or_create(
            name=name,
            defaults={
                "version": version,
                "description": description,
                "dag_structure": dag_structure,
                "is_active": True
            }
        )
        
        if created:
            logger.info(f"Created new workflow definition: {name}")
        
        return workflow
    
    @sync_to_async
    def create_workflow_run_with_paper_id(
        self,
        workflow_name: str,
        paper_id: int,
        input_data: Dict[str, Any] = None,
        user = None
    ) -> WorkflowRun:
        """
        Create a workflow run using paper_id instead of paper object.
        
        Convenience method that fetches paper and delegates to orchestrator.
        
        Args:
            workflow_name: Name of workflow definition
            paper_id: Paper database ID
            input_data: Input parameters
            user: User initiating workflow
            
        Returns:
            WorkflowRun instance
        """
        from webApp.models import Paper
        paper = Paper.objects.get(id=paper_id)
        
        return self.orchestrator.create_workflow_run(
            workflow_name=workflow_name,
            paper=paper,
            input_data=input_data,
            user=user
        )
    
    # ========================================================================
    # Workflow Run Management
    # ========================================================================
    
    @sync_to_async
    def create_workflow_run(
        self,
        name: str,
        dag_structure: Dict[str, Any],
        description: str = "",
        version: int = 1
    ) -> WorkflowDefinition:
        """
        Get or create a workflow definition.
        
        Args:
            name: Unique workflow name
            dag_structure: DAG structure with nodes and edges
            description: Workflow description
            version: Version number
            
        Returns:
            WorkflowDefinition instance
        """
        workflow, created = WorkflowDefinition.objects.get_or_create(
            name=name,
            defaults={
                "version": version,
                "description": description,
                "dag_structure": dag_structure,
                "is_active": True
            }
        )
        
        if created:
            logger.info(f"Created new workflow definition: {name}")
        
        return workflow
    
    # ========================================================================
    # Workflow Run Management
    # ========================================================================
    
    @sync_to_async
    def create_workflow_run(
        self,
        workflow_name: str,
        paper,
        input_data: Dict[str, Any] = None,
        user = None
    ) -> WorkflowRun:
        """
        Create a new workflow run.
        
        Delegates to WorkflowOrchestrator.create_workflow_run.
        
        Args:
            workflow_name: Name of workflow definition
            paper: Paper instance
            input_data: Input parameters
            user: User initiating workflow
            
        Returns:
            WorkflowRun instance
        """
        return self.orchestrator.create_workflow_run(
            workflow_name=workflow_name,
            paper=paper,
            input_data=input_data,
            user=user
        )
    
    @sync_to_async
    def update_workflow_run_status(
        self,
        workflow_run_id: str,
        status: str,
        **kwargs
    ):
        """
        Update workflow run status and other fields.
        
        Args:
            workflow_run_id: UUID of workflow run
            status: New status (pending, running, completed, failed, cancelled)
            **kwargs: Additional fields to update (started_at, completed_at, error_message, etc.)
        """
        workflow_run = WorkflowRun.objects.get(id=workflow_run_id)
        workflow_run.status = status
        
        for key, value in kwargs.items():
            setattr(workflow_run, key, value)
        
        workflow_run.save()
        logger.info(f"Workflow run {workflow_run_id} status updated to: {status}")
    
    # ========================================================================
    # Node Management
    # ========================================================================
    
    @sync_to_async
    def get_workflow_node(self, workflow_run_id: str, node_id: str) -> WorkflowNode:
        """
        Get a workflow node by ID.
        
        Args:
            workflow_run_id: UUID of workflow run
            node_id: Node identifier (e.g., 'paper_type_classification')
            
        Returns:
            WorkflowNode instance
        """
        return WorkflowNode.objects.select_related('workflow_run').get(
            workflow_run_id=workflow_run_id,
            node_id=node_id
        )
    
    @sync_to_async
    def update_node_status(
        self,
        node: WorkflowNode,
        status: str,
        **kwargs
    ):
        """
        Update workflow node status and other fields.
        
        Args:
            node: WorkflowNode instance
            status: New status (pending, ready, claimed, running, completed, failed, skipped)
            **kwargs: Additional fields to update (started_at, completed_at, error_message, etc.)
        """
        node.status = status
        
        for key, value in kwargs.items():
            setattr(node, key, value)
        
        node.save()
        logger.info(f"Node {node.node_id} status updated to: {status}")
    
    @sync_to_async
    def mark_node_running(self, node: WorkflowNode, celery_task_id: str = None):
        """
        Mark a node as running.
        
        Delegates to WorkflowOrchestrator.mark_node_running.
        """
        self.orchestrator.mark_node_running(node, celery_task_id)
    
    @sync_to_async
    def mark_node_completed(
        self,
        node: WorkflowNode,
        output_data: Dict[str, Any] = None
    ):
        """
        Mark a node as completed.
        
        Delegates to WorkflowOrchestrator.mark_node_completed which also:
        - Updates downstream dependencies
        - Checks workflow completion
        """
        self.orchestrator.mark_node_completed(node, output_data)
    
    @sync_to_async
    def mark_node_failed(
        self,
        node: WorkflowNode,
        error_message: str,
        error_traceback: str = None,
        retry: bool = True
    ):
        """
        Mark a node as failed.
        
        Delegates to WorkflowOrchestrator.mark_node_failed which handles:
        - Retry logic
        - Skipping dependent nodes
        - Workflow failure propagation
        """
        self.orchestrator.mark_node_failed(
            node,
            error_message,
            error_traceback,
            retry
        )
    
    # ========================================================================
    # Artifact Management
    # ========================================================================
    
    @sync_to_async
    def create_node_artifact(
        self,
        node: WorkflowNode,
        name: str,
        data: Any,
        artifact_type: str = 'inline',
        **kwargs
    ) -> NodeArtifact:
        """
        Create a node artifact.
        
        Args:
            node: WorkflowNode instance
            name: Artifact name/key
            data: Artifact data (dict for inline, path for file, etc.)
            artifact_type: Type of artifact ('inline', 'file', 'url', 'database')
            **kwargs: Additional fields (mime_type, size_bytes, metadata, etc.)
            
        Returns:
            NodeArtifact instance
        """
        # Convert Pydantic models to dict
        if hasattr(data, 'model_dump'):
            inline_data = data.model_dump()
        elif hasattr(data, 'dict'):
            inline_data = data.dict()
        elif isinstance(data, dict):
            inline_data = data
        else:
            inline_data = {"value": data}
        
        artifact = NodeArtifact.objects.create(
            node=node,
            artifact_type=artifact_type,
            name=name,
            inline_data=inline_data if artifact_type == 'inline' else None,
            **kwargs
        )
        
        logger.info(f"Created artifact '{name}' for node {node.node_id}")
        return artifact
    
    @sync_to_async
    def get_node_artifact(
        self,
        node: WorkflowNode,
        name: str
    ) -> Optional[NodeArtifact]:
        """
        Get a specific artifact from a node.
        
        Args:
            node: WorkflowNode instance
            name: Artifact name
            
        Returns:
            NodeArtifact instance or None
        """
        try:
            return NodeArtifact.objects.get(node=node, name=name)
        except NodeArtifact.DoesNotExist:
            return None
    
    # ========================================================================
    # Logging
    # ========================================================================
    
    @sync_to_async
    def create_node_log(
        self,
        node: WorkflowNode,
        level: str,
        message: str,
        context: Dict[str, Any] = None
    ):
        """
        Create a structured log entry for a node.
        
        Args:
            node: WorkflowNode instance
            level: Log level ('DEBUG', 'INFO', 'WARNING', 'ERROR')
            message: Log message
            context: Additional context data
        """
        NodeLog.objects.create(
            node=node,
            level=level,
            message=message,
            context=context or {}
        )
    
    # ========================================================================
    # Query Helpers
    # ========================================================================
    
    @sync_to_async
    def get_paper(self, paper_id: int):
        """Get paper from database."""
        from webApp.models import Paper
        return Paper.objects.get(id=paper_id)
    
    @sync_to_async
    def check_previous_analysis(
        self,
        paper_id: int,
        node_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Check if paper has been analyzed before and return latest result.
        
        Args:
            paper_id: Paper ID
            node_id: Node identifier to check
            
        Returns:
            Dict with run_id, completed_at, and result data, or None
        """
        try:
            # Get most recent successful run for this paper
            latest_run = WorkflowRun.objects.filter(
                paper_id=paper_id,
                status='completed'
            ).order_by('-completed_at').first()
            
            if not latest_run:
                return None
            
            # Get the node from that run
            node = WorkflowNode.objects.filter(
                workflow_run=latest_run,
                node_id=node_id,
                status='completed'
            ).first()
            
            if not node:
                return None
            
            # Get the artifact
            artifact = NodeArtifact.objects.filter(
                node=node,
                name='result'
            ).first()
            
            if artifact and artifact.inline_data:
                return {
                    'run_id': str(latest_run.id),
                    'completed_at': latest_run.completed_at,
                    'result': artifact.inline_data
                }
            
            return None
            
        except Exception as e:
            logger.warning(f"Error checking previous analysis: {e}")
            return None
    
    @sync_to_async
    def get_token_stats(self, workflow_run_id: str) -> tuple[int, int]:
        """
        Get token usage statistics for a workflow run.
        
        Args:
            workflow_run_id: UUID of workflow run
            
        Returns:
            Tuple of (input_tokens, output_tokens)
        """
        nodes = WorkflowNode.objects.filter(workflow_run_id=workflow_run_id)
        total_input = 0
        total_output = 0
        
        for node in nodes:
            token_artifact = node.artifacts.filter(name='token_usage').first()
            if token_artifact and token_artifact.inline_data:
                total_input += token_artifact.inline_data.get('input_tokens', 0)
                total_output += token_artifact.inline_data.get('output_tokens', 0)
        
        return total_input, total_output


# Convenience singleton instance
async_ops = AsyncWorkflowOperations()
