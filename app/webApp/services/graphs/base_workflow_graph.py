"""
Base Workflow Graph Class

Abstract base class for LangGraph-based workflows integrated with the workflow engine.
Provides common functionality for node execution and workflow orchestration.

Subclasses must implement:
- build_workflow(): Build the LangGraph workflow structure
- execute_workflow(): Execute the complete workflow from start
"""

import os
import logging
import threading
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

from django.utils import timezone
from asgiref.sync import sync_to_async
from openai import OpenAI

from workflow_engine.services.async_orchestrator import async_ops
from ..graphs_state import PaperProcessingState

logger = logging.getLogger(__name__)


# ============================================================================
# Global Concurrency Control
# ============================================================================

# Global semaphore to limit concurrent workflow executions (per worker process)
# This prevents system overload when multiple workflows are triggered simultaneously
MAX_CONCURRENT_WORKFLOWS = 8
_workflow_semaphore = threading.Semaphore(MAX_CONCURRENT_WORKFLOWS)


@sync_to_async
def get_active_workflow_count() -> int:
    """Get the current number of active workflows by querying database."""
    # Import here to avoid circular imports
    from workflow_engine.models import WorkflowRun
    
    # Count workflows with running or pending status
    return WorkflowRun.objects.filter(status__in=['running', 'pending']).count()


@sync_to_async
def get_active_workflows() -> Dict[int, Dict[str, Any]]:
    """Get information about currently active workflows from database."""
    from workflow_engine.models import WorkflowRun
    
    active_runs = WorkflowRun.objects.filter(
        status__in=['running', 'pending']
    ).select_related('paper').values(
        'paper__id', 'id', 'status', 'started_at', 'created_at'
    )
    
    workflows = {}
    for run in active_runs:
        paper_id = run['paper__id']
        workflows[paper_id] = {
            'workflow_run_id': str(run['id']),
            'status': run['status'],
            'started_at': (run['started_at'] or run['created_at']).isoformat(),
        }
    
    return workflows


async def _register_workflow(paper_id: int, workflow_run_id: str):
    """Register a workflow as active (logging only, tracking via DB)."""
    active_count = await get_active_workflow_count()
    logger.info(f"Workflow started for paper {paper_id}. Active workflows: {active_count}/{MAX_CONCURRENT_WORKFLOWS}")


async def _unregister_workflow(paper_id: int):
    """Unregister a workflow (logging only, tracking via DB)."""
    active_count = await get_active_workflow_count()
    logger.info(f"Workflow finished for paper {paper_id}. Active workflows: {active_count}/{MAX_CONCURRENT_WORKFLOWS}")


@sync_to_async
def cleanup_stale_workflows(max_age_minutes: int = 30):
    """Clean up workflows that have been active for too long (likely crashed)."""
    from datetime import timedelta
    from workflow_engine.models import WorkflowRun, WorkflowNode
    
    cutoff_time = timezone.now() - timedelta(minutes=max_age_minutes)
    
    # Find stale workflows
    stale_runs = WorkflowRun.objects.filter(
        status__in=['running', 'pending'],
        started_at__lt=cutoff_time
    )
    
    stale_count = 0
    for run in stale_runs:
        logger.warning(
            f"Marking stale workflow {run.id} for paper {run.paper_id} as failed "
            f"(started: {run.started_at})"
        )
        run.status = 'failed'
        run.completed_at = timezone.now()
        run.error_message = f'Workflow timeout after {max_age_minutes} minutes'
        run.save()
        
        # Also mark running/pending nodes as failed
        WorkflowNode.objects.filter(
            workflow_run=run,
            status__in=['running', 'pending']
        ).update(
            status='failed',
            completed_at=timezone.now(),
            error_message=f'Node timeout after {max_age_minutes} minutes'
        )
        
        stale_count += 1
    
    if stale_count > 0:
        logger.info(f"Cleaned up {stale_count} stale workflows")
    
    return stale_count


class BaseWorkflowGraph(ABC):
    """
    Abstract base class for workflow graphs.

    Provides implementations for:
    - execute_a_node: Re-execute a single node within its workflow run
    - execute_from_node: Create new run and execute from a specific node onwards

    Requires subclasses to implement:
    - build_workflow: Build the LangGraph workflow structure
    - execute_workflow: Execute the complete workflow
    """

    @abstractmethod
    def build_workflow(self):
        """
        Build and return the compiled LangGraph workflow.

        Returns:
            Compiled StateGraph workflow
        """
        pass

    @abstractmethod
    async def execute_workflow(
        self,
        paper_id: int,
        force_reprocess: bool = False,
        openai_api_key: Optional[str] = None,
        model: str = "gpt-4o",
    ) -> Dict[str, Any]:
        """
        Execute the complete workflow for a paper.

        Args:
            paper_id: Database ID of the paper to process
            force_reprocess: If True, bypass cache and reprocess all nodes
            openai_api_key: OpenAI API key (uses env var if not provided)
            model: OpenAI model to use

        Returns:
            Dictionary with workflow results
        """
        pass

    async def execute_a_node(
        self,
        node_uuid: str,
        force_reprocess: bool = True,
        openai_api_key: Optional[str] = None,
        model: str = "gpt-4o",
    ) -> Dict[str, Any]:
        """
        Execute a single node in isolation by re-running it within its existing workflow run.

        Args:
            node_uuid: UUID of the node to re-execute
            force_reprocess: If True, reprocess even if already completed (default True)
            openai_api_key: OpenAI API key (uses env var if not provided)
            model: OpenAI model to use

        Returns:
            Dictionary with execution results
        """
        logger.info(f"Re-executing single node {node_uuid}")

        try:
            # Get the node
            node = await async_ops.get_node_by_uuid(node_uuid)
            if not node:
                raise ValueError(f"Node {node_uuid} not found")

            workflow_run = node.workflow_run
            paper_id = workflow_run.paper.id

            logger.info(
                f"Node {node_uuid} current status: {node.status}, node_id: {node.node_id}"
            )

            # Initialize OpenAI client
            api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
            client = OpenAI(api_key=api_key)

            # Build state for this node execution
            state: PaperProcessingState = {
                "workflow_run_id": str(workflow_run.id),
                "paper_id": paper_id,
                "current_node_id": node.node_id,
                "client": client,
                "model": model,
                "force_reprocess": force_reprocess,
                "paper_type_result": None,
                "code_availability_result": None,
                "code_reproducibility_result": None,
                "errors": [],
            }

            logger.info(f"Loading dependencies for node {node.node_id}")

            # Load previous node results - subclass should override this method to customize
            state = await self._load_node_dependencies(node, workflow_run, state)

            # Execute the specific node function
            logger.info(f"Executing node function: {node.node_id}")
            state["current_node_id"] = node.node_id

            # Execute node - subclass should override this method to handle node execution
            result = await self._execute_node_function(node.node_id, state)

            # Merge results into state
            if result:
                for key, value in result.items():
                    if key == "errors" and "errors" in state:
                        state["errors"].extend(value)
                    else:
                        state[key] = value

            # Check for errors
            errors = state.get("errors", [])
            success = len(errors) == 0

            logger.info(
                f"Single node execution completed. Success: {success}, Errors: {errors}"
            )

            # Check if all nodes in the workflow are completed to update workflow run status
            try:
                # Get all nodes in this workflow run
                all_nodes = await async_ops.get_workflow_nodes(str(workflow_run.id))

                # Check statuses
                all_completed_or_failed = all(
                    n.status in ["completed", "failed"] for n in all_nodes
                )
                any_failed = any(n.status == "failed" for n in all_nodes)

                if all_completed_or_failed:
                    # All nodes finished, update workflow run status
                    workflow_status = "failed" if any_failed else "completed"
                    await async_ops.update_workflow_run_status(
                        workflow_run.id, workflow_status, completed_at=timezone.now()
                    )
                    logger.info(
                        f"Workflow run {workflow_run.id} updated to status: {workflow_status}"
                    )
            except Exception as e:
                logger.warning(
                    f"Failed to update workflow run status after node execution: {e}"
                )

            return {
                "success": success,
                "node_id": node.node_id,
                "node_uuid": str(node.id),
                "workflow_run_id": str(workflow_run.id),
                "errors": errors,
            }

        except Exception as e:
            logger.error(f"Failed to execute single node: {e}", exc_info=True)
            # Try to update node status to failed
            try:
                node = await async_ops.get_node_by_uuid(node_uuid)
                if node:
                    await async_ops.update_node_status(
                        node,
                        "failed",
                        completed_at=timezone.now(),
                        error_message=str(e),
                    )
                    await async_ops.create_node_log(
                        node, "ERROR", f"Node execution failed: {str(e)}"
                    )

                    # Also check if workflow should be marked as failed
                    try:
                        all_nodes = await async_ops.get_workflow_nodes(
                            str(node.workflow_run.id)
                        )
                        all_completed_or_failed = all(
                            n.status in ["completed", "failed"] for n in all_nodes
                        )
                        if all_completed_or_failed:
                            await async_ops.update_workflow_run_status(
                                node.workflow_run.id,
                                "failed",
                                completed_at=timezone.now(),
                                error_message=str(e),
                            )
                            logger.info(
                                f"Workflow run {node.workflow_run.id} updated to 'failed'"
                            )
                    except Exception as inner_inner_e:
                        logger.error(
                            f"Failed to update workflow status: {inner_inner_e}"
                        )
            except Exception as inner_e:
                logger.error(
                    f"Failed to update node status after error: {inner_e}",
                    exc_info=True,
                )

            return {"success": False, "error": str(e)}

    async def execute_from_node(
        self,
        node_uuid: str,
        openai_api_key: Optional[str] = None,
        model: str = "gpt-4o",
    ) -> Dict[str, Any]:
        """
        Execute workflow from a specific node onwards using the original workflow run.

        This does NOT create a new workflow run. Instead, it:
        1. Resets the target node and all downstream nodes to 'pending'
        2. Executes from the target node onwards in the same workflow run
        3. Preserves all upstream completed nodes

        Args:
            node_uuid: UUID of the node to start from
            openai_api_key: OpenAI API key (uses env var if not provided)
            model: OpenAI model to use

        Returns:
            Dictionary with execution results
        """
        logger.info(f"Executing workflow from node {node_uuid}")

        try:
            # Get the target node
            target_node = await async_ops.get_node_by_uuid(node_uuid)
            if not target_node:
                raise ValueError(f"Node {node_uuid} not found")

            workflow_run = target_node.workflow_run
            paper_id = workflow_run.paper.id

            logger.info(
                f"Executing from node {target_node.node_id} in workflow run {workflow_run.id}"
            )

            # Get workflow definition to understand node order
            workflow_def = await self._get_workflow_node_order()

            # Find target node index
            try:
                target_index = workflow_def.index(target_node.node_id)
            except ValueError:
                raise ValueError(
                    f"Node {target_node.node_id} not found in workflow definition"
                )

            # Reset target node and all downstream nodes to pending
            all_nodes = await async_ops.get_workflow_nodes(str(workflow_run.id))
            for node in all_nodes:
                try:
                    node_index = workflow_def.index(node.node_id)
                    if node_index >= target_index:
                        # Reset this node
                        await async_ops.update_node_status(
                            node,
                            "pending",
                            started_at=None,
                            completed_at=None,
                            error_message=None,
                        )
                        logger.info(f"Reset node {node.node_id} to pending")
                except ValueError:
                    logger.warning(f"Node {node.node_id} not in workflow definition")

            # Update workflow run to running
            await async_ops.update_workflow_run_status(
                workflow_run.id, "running", started_at=timezone.now()
            )

            # Initialize OpenAI client
            api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
            client = OpenAI(api_key=api_key)

            # Build initial state
            state: PaperProcessingState = {
                "workflow_run_id": str(workflow_run.id),
                "paper_id": paper_id,
                "current_node_id": None,
                "client": client,
                "model": model,
                "force_reprocess": False,
                "paper_type_result": None,
                "code_availability_result": None,
                "code_reproducibility_result": None,
                "errors": [],
            }

            # Load results from completed upstream nodes
            state = await self._load_upstream_results(workflow_run, target_index, state)

            # Execute nodes from target onwards
            for i in range(target_index, len(workflow_def)):
                node_id = workflow_def[i]
                state["current_node_id"] = node_id

                logger.info(f"Executing node: {node_id}")

                result = await self._execute_node_function(node_id, state)

                if result:
                    for key, value in result.items():
                        if key == "errors" and "errors" in state:
                            state["errors"].extend(value)
                        else:
                            state[key] = value

            # Check for errors
            errors = state.get("errors", [])
            success = len(errors) == 0

            # Update workflow run status
            await async_ops.update_workflow_run_status(
                workflow_run.id,
                "completed" if success else "failed",
                completed_at=timezone.now(),
                error_message="; ".join(errors) if errors else None,
            )

            return {
                "success": success,
                "workflow_run_id": str(workflow_run.id),
                "paper_id": paper_id,
                "errors": errors,
            }

        except Exception as e:
            logger.error(f"Failed to execute workflow from node: {e}", exc_info=True)

            # Try to mark workflow as failed
            try:
                if "workflow_run" in locals():
                    await async_ops.update_workflow_run_status(
                        workflow_run.id,
                        "failed",
                        completed_at=timezone.now(),
                        error_message=str(e),
                    )
            except Exception as inner_e:
                logger.error(f"Failed to update workflow status: {inner_e}")

            return {"success": False, "error": str(e)}

    # Helper methods that subclasses can override

    @abstractmethod
    async def _get_workflow_node_order(self) -> list:
        """
        Return the ordered list of node IDs in the workflow.

        Returns:
            List of node_id strings in execution order
        """
        pass

    @abstractmethod
    async def _load_node_dependencies(
        self, node, workflow_run, state: PaperProcessingState
    ) -> PaperProcessingState:
        """
        Load dependencies for a specific node from previous nodes.

        Args:
            node: The node to execute
            workflow_run: The workflow run
            state: Current state dictionary

        Returns:
            Updated state with dependencies loaded
        """
        pass

    @abstractmethod
    async def _execute_node_function(
        self, node_id: str, state: PaperProcessingState
    ) -> Dict[str, Any]:
        """
        Execute the function for a specific node.

        Args:
            node_id: ID of the node to execute
            state: Current state dictionary

        Returns:
            Dictionary with node execution results
        """
        pass

    async def _load_upstream_results(
        self, workflow_run, target_index: int, state: PaperProcessingState
    ) -> PaperProcessingState:
        """
        Load results from all completed nodes before the target index.

        Args:
            workflow_run: The workflow run
            target_index: Index of the target node in workflow definition
            state: Current state dictionary

        Returns:
            Updated state with upstream results loaded
        """
        workflow_def = await self._get_workflow_node_order()

        for i in range(target_index):
            node_id = workflow_def[i]
            node = await async_ops.get_workflow_node(str(workflow_run.id), node_id)

            if node and node.status == "completed":
                artifacts = await async_ops.get_node_artifacts(node)
                # Subclass should implement proper artifact loading
                state = await self._load_artifacts_into_state(node_id, artifacts, state)

        return state

    async def _load_artifacts_into_state(
        self, node_id: str, artifacts, state: PaperProcessingState
    ) -> PaperProcessingState:
        """
        Load artifacts from a node into the state.
        Override this in subclass to customize artifact loading.

        Args:
            node_id: ID of the node
            artifacts: List of artifacts
            state: Current state

        Returns:
            Updated state
        """
        # Default implementation - subclass should override
        return state
