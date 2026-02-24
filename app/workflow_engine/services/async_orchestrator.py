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
        
        When creating a new version, automatically deactivates all previous versions
        of the same workflow to ensure only the latest version is active.
        
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
            version=version,
            defaults={
                "description": description,
                "dag_structure": dag_structure,
                "is_active": True
            }
        )
        
        if created:
            # Deactivate all previous versions of this workflow
            deactivated_count = WorkflowDefinition.objects.filter(
                name=name,
                is_active=True
            ).exclude(
                version=version
            ).update(is_active=False)
            
            if deactivated_count > 0:
                logger.info(f"Created new workflow definition: {name} v{version}, deactivated {deactivated_count} previous version(s)")
            else:
                logger.info(f"Created new workflow definition: {name} v{version}")
        
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
        from django.db import connection
        connection.close_if_unusable_or_obsolete()
        
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
        from django.db import connection
        connection.close_if_unusable_or_obsolete()
        
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
            node: WorkflowNode instance (will be refetched to ensure thread-safe DB access)
            status: New status (pending, ready, claimed, running, completed, failed, skipped)
            **kwargs: Additional fields to update (started_at, completed_at, error_message, etc.)
        """
        # Refetch node from database to ensure we have a fresh connection
        # This is important when called from background threads
        from django.db import connection
        connection.close_if_unusable_or_obsolete()
        
        node_fresh = WorkflowNode.objects.get(id=node.id)
        node_fresh.status = status
        
        for key, value in kwargs.items():
            setattr(node_fresh, key, value)
        
        node_fresh.save()
        logger.info(f"Node {node_fresh.node_id} status updated to: {status}")
    
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
        from django.db import connection
        connection.close_if_unusable_or_obsolete()
        
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
    
    @sync_to_async
    def get_node_by_uuid(self, node_uuid: str) -> Optional[WorkflowNode]:
        """
        Get a workflow node by its UUID.
        
        Args:
            node_uuid: UUID of the node
            
        Returns:
            WorkflowNode instance or None if not found
        """
        from django.db import connection
        connection.close_if_unusable_or_obsolete()
        
        try:
            return WorkflowNode.objects.select_related(
                'workflow_run__paper',
                'workflow_run__workflow_definition'
            ).get(id=node_uuid)
        except WorkflowNode.DoesNotExist:
            return None
    
    @sync_to_async
    def get_workflow_nodes(self, workflow_run_id: str) -> list:
        """
        Get all nodes for a workflow run.
        
        Args:
            workflow_run_id: UUID of workflow run
            
        Returns:
            List of WorkflowNode instances
        """
        from django.db import connection
        connection.close_if_unusable_or_obsolete()
        
        return list(WorkflowNode.objects.filter(workflow_run_id=workflow_run_id).order_by('created_at'))
    
    @sync_to_async
    def get_node_artifacts(self, node: WorkflowNode) -> list:
        """
        Get all artifacts for a node.
        
        Args:
            node: WorkflowNode instance
            
        Returns:
            List of NodeArtifact instances
        """
        return list(node.artifacts.all())
    
    @sync_to_async
    def clear_node_logs(self, node: WorkflowNode):
        """
        Clear all logs for a node.
        
        Args:
            node: WorkflowNode instance
        """
        node.logs.all().delete()
    
    @sync_to_async
    def update_node_tokens(
        self,
        node: WorkflowNode,
        input_tokens: int,
        output_tokens: int,
        was_cached: bool = False
    ):
        """
        Update token counts for a node.
        
        Args:
            node: WorkflowNode instance
            input_tokens: Number of input tokens consumed
            output_tokens: Number of output tokens generated
            was_cached: Whether tokens were copied from cached result
        """
        node.input_tokens = input_tokens
        node.output_tokens = output_tokens
        node.total_tokens = input_tokens + output_tokens
        node.was_cached = was_cached
        node.save(update_fields=['input_tokens', 'output_tokens', 'total_tokens', 'was_cached'])
        
        logger.info(
            f"Updated node {node.node_id} tokens: {input_tokens} in, {output_tokens} out, "
            f"total {node.total_tokens}, cached={was_cached}"
        )
    
    @sync_to_async
    def get_most_recent_completed_node(
        self,
        paper_id: int,
        node_id: str,
        exclude_run_id: str = None
    ) -> Optional[WorkflowNode]:
        """
        Get the most recent successfully completed node for a paper.
        
        Used to copy token counts when a node is cached.
        
        Args:
            paper_id: Paper database ID
            node_id: Node ID (e.g., 'paper_type_classification')
            exclude_run_id: Workflow run ID to exclude (current run)
            
        Returns:
            WorkflowNode instance or None
        """
        query = WorkflowNode.objects.filter(
            workflow_run__paper_id=paper_id,
            node_id=node_id,
            status='completed'
        )
        
        if exclude_run_id:
            query = query.exclude(workflow_run_id=exclude_run_id)
        
        # Get most recent by workflow run creation date
        node = query.select_related('workflow_run').order_by('-workflow_run__created_at').first()
        
        if node:
            logger.info(
                f"Found previous completed node {node_id} for paper {paper_id}: "
                f"{node.input_tokens} in, {node.output_tokens} out"
            )
        
        return node
    
    @sync_to_async
    def get_workflow_run(self, workflow_run_id: str) -> WorkflowRun:
        """
        Get a workflow run by ID.
        
        Args:
            workflow_run_id: UUID of workflow run
            
        Returns:
            WorkflowRun instance
        """
        return WorkflowRun.objects.get(id=workflow_run_id)
    
    @sync_to_async
    def aggregate_workflow_run_tokens(self, workflow_run_id: str):
        """
        Aggregate token counts from all nodes and update workflow run totals.
        
        Should be called after workflow completes.
        
        Args:
            workflow_run_id: UUID of workflow run
        """
        from django.db.models import Sum
        
        workflow_run = WorkflowRun.objects.get(id=workflow_run_id)
        
        # Aggregate tokens from all nodes
        aggregated = workflow_run.nodes.aggregate(
            total_input=Sum('input_tokens'),
            total_output=Sum('output_tokens'),
            total=Sum('total_tokens')
        )
        
        workflow_run.total_input_tokens = aggregated['total_input'] or 0
        workflow_run.total_output_tokens = aggregated['total_output'] or 0
        workflow_run.total_tokens = aggregated['total'] or 0
        
        workflow_run.save(update_fields=[
            'total_input_tokens',
            'total_output_tokens',
            'total_tokens'
        ])
        
        logger.info(
            f"Aggregated tokens for workflow run {workflow_run_id}: "
            f"{workflow_run.total_input_tokens} in, {workflow_run.total_output_tokens} out, "
            f"total {workflow_run.total_tokens}"
        )


# Convenience singleton instance
async_ops = AsyncWorkflowOperations()
