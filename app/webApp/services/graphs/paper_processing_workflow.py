"""
Paper Processing Workflow - Integrated with Workflow Engine

This module implements a two-node workflow for analyzing papers:
- Node A: Paper Type Classification (dataset vs method vs both)
- Node B: Code Availability Check (agentic analysis of code availability and quality)
- Node C: Code Repository Analysis (comprehensive analysis of repository structure, documentation, and reproducibility)

Properly integrated with the workflow_engine models for:
- History tracking
- Versioning
- Artifact storage
- Progress monitoring
"""

import os
import logging
import asyncio
import threading

from typing import Optional, Dict, Any, List

from django.utils import timezone
from asgiref.sync import sync_to_async

from langgraph.graph import StateGraph, END
from openai import OpenAI

from workflow_engine.services.async_orchestrator import async_ops

from webApp.services.nodes.paper_type_classification import (
    paper_type_classification_node,
)
from webApp.services.nodes.section_embeddings import section_embeddings_node
from webApp.services.nodes.code_repository_analysis import code_repository_analysis_node
from webApp.services.nodes.code_availability_check import code_availability_check_node

from ..pydantic_schemas import (
    PaperTypeClassification,
    CodeAvailabilityCheck,
)
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
    
    #Find stale workflows
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


# ============================================================================
# Workflow Definition and Execution
# ============================================================================


def build_paper_processing_workflow() -> StateGraph:
    """
    Build the LangGraph workflow for paper processing with conditional routing.

    Workflow structure (sequential with conditional routing):
    - Node A (paper_type_classification): Classify paper type
    - Node D (section_embeddings): Compute embeddings for paper sections
    - Node B (code_availability_check): Check code availability and verify accessibility
    - Node C (code_repository_analysis): Comprehensive code analysis (conditional)

    Flow:
    1. paper_type_classification runs first
    2. section_embeddings runs second (computes embeddings for sections)
    3. code_availability_check runs third
    4. After code_availability_check, route to:
       * END if paper is 'theoretical' or 'dataset'
       * END if no code found (code_available=False)
       * code_repository_analysis if code found AND paper is 'method', 'both', or 'unknown'
    """

    workflow = StateGraph(PaperProcessingState)

    # Add nodes
    workflow.add_node("paper_type_classification", paper_type_classification_node)
    workflow.add_node("section_embeddings", section_embeddings_node)
    workflow.add_node("code_availability_check", code_availability_check_node)
    workflow.add_node("code_repository_analysis", code_repository_analysis_node)

    # Define routing function
    def route_after_checks(state: PaperProcessingState) -> str:
        """
        Route after both paper type classification and code availability check.

        Returns:
            - "code_repository_analysis" if should analyze code
            - END if should skip analysis
        """
        paper_type_result = state.get("paper_type_result")
        code_availability = state.get("code_availability_result")

        # Skip if theoretical or dataset paper
        if paper_type_result and paper_type_result.paper_type in [
            "theoretical",
            "dataset",
        ]:
            logger.info(
                f"Skipping code analysis for {paper_type_result.paper_type} paper"
            )
            return END

        # Skip if no code available
        if not code_availability or not code_availability.code_available:
            logger.info("Skipping code analysis - no code available")
            return END

        # Proceed to repository analysis for method/both/unknown papers with code
        logger.info("Proceeding to code repository analysis")
        return "code_repository_analysis"

    # Set entry point and sequential flow
    workflow.set_entry_point("paper_type_classification")
    workflow.add_edge("paper_type_classification", "section_embeddings")
    workflow.add_edge("section_embeddings", "code_availability_check")

    # Conditional routing after both checks complete
    workflow.add_conditional_edges(
        "code_availability_check",
        route_after_checks,
        {
            "code_repository_analysis": "code_repository_analysis",
            END: END,
        },
    )

    # Code repository analysis always ends
    workflow.add_edge("code_repository_analysis", END)

    return workflow.compile()


async def execute_single_node_only(
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

        # Note: Node status should already be set to 'pending' by the view
        # The node function will update it to 'running' when it starts

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

        # Load previous node results if they exist
        if node.node_id == "code_availability_check":
            # Need paper_type_result from previous node
            prev_node = await async_ops.get_workflow_node(
                str(workflow_run.id), "paper_type_classification"
            )
            if prev_node and prev_node.status == "completed":
                # Get the result artifact
                artifacts = await async_ops.get_node_artifacts(prev_node)
                for artifact in artifacts:
                    if artifact.name == "result":
                        state["paper_type_result"] = PaperTypeClassification(
                            **artifact.inline_data
                        )
                        logger.info(
                            f"Loaded paper_type_result from previous node: {state['paper_type_result'].paper_type}"
                        )
                        break

        elif node.node_id == "code_repository_analysis":
            # Need both paper_type_result and code_availability_result from previous nodes
            paper_type_node = await async_ops.get_workflow_node(
                str(workflow_run.id), "paper_type_classification"
            )
            if paper_type_node and paper_type_node.status == "completed":
                artifacts = await async_ops.get_node_artifacts(paper_type_node)
                for artifact in artifacts:
                    if artifact.name == "result":
                        state["paper_type_result"] = PaperTypeClassification(
                            **artifact.inline_data
                        )
                        logger.info(
                            f"Loaded paper_type_result: {state['paper_type_result'].paper_type}"
                        )
                        break

            code_avail_node = await async_ops.get_workflow_node(
                str(workflow_run.id), "code_availability_check"
            )
            if code_avail_node and code_avail_node.status == "completed":
                artifacts = await async_ops.get_node_artifacts(code_avail_node)
                for artifact in artifacts:
                    if artifact.name == "result":
                        state["code_availability_result"] = CodeAvailabilityCheck(
                            **artifact.inline_data
                        )
                        logger.info(
                            f"Loaded code_availability_result: code_available={state['code_availability_result'].code_available}"
                        )
                        break

        logger.info(f"Executing node function for {node.node_id}")

        # Execute the appropriate node function
        if node.node_id == "paper_type_classification":
            result = await paper_type_classification_node(state)
        elif node.node_id == "code_availability_check":
            result = await code_availability_check_node(state)
        elif node.node_id == "code_repository_analysis":
            result = await code_repository_analysis_node(state)
        else:
            raise ValueError(f"Unknown node type: {node.node_id}")

        logger.info(f"Node function executed, result keys: {result.keys()}")

        # Check for errors
        errors = result.get("errors", [])
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
                    node, "failed", completed_at=timezone.now(), error_message=str(e)
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
                    logger.error(f"Failed to update workflow status: {inner_inner_e}")
        except Exception as inner_e:
            logger.error(
                f"Failed to update node status after error: {inner_e}", exc_info=True
            )

        return {"success": False, "error": str(e)}


async def execute_workflow_from_node(
    node_uuid: str, openai_api_key: Optional[str] = None, model: str = "gpt-4o"
) -> Dict[str, Any]:
    """
    Create a new workflow run that copies results from previous nodes and executes from the specified node onwards.

    Args:
        node_uuid: UUID of the node to start from
        openai_api_key: OpenAI API key (uses env var if not provided)
        model: OpenAI model to use

    Returns:
        Dictionary with workflow results
    """
    logger.info(f"Executing workflow from node {node_uuid}")

    try:
        # Get the original node
        original_node = await async_ops.get_node_by_uuid(node_uuid)
        if not original_node:
            raise ValueError(f"Node {node_uuid} not found")

        original_workflow_run = original_node.workflow_run
        paper_id = original_workflow_run.paper.id

        # Get workflow definition
        workflow_def = original_workflow_run.workflow_definition

        # Create new workflow run
        config = {
            "force_reprocess": True,
            "model": model,
            "max_retries": 3,
            "start_from_node": original_node.node_id,
        }
        new_workflow_run = await async_ops.create_workflow_run_with_paper_id(
            workflow_name=workflow_def.name, paper_id=paper_id, input_data=config
        )

        # Update workflow run status to running
        await async_ops.update_workflow_run_status(
            new_workflow_run.id, "running", started_at=timezone.now()
        )

        # Get all nodes from the original workflow run
        original_nodes = await async_ops.get_workflow_nodes(
            str(original_workflow_run.id)
        )

        # Determine which nodes come before the target node based on DAG
        dag_structure = workflow_def.dag_structure
        nodes_order = [n["id"] for n in dag_structure.get("nodes", [])]
        target_node_index = (
            nodes_order.index(original_node.node_id)
            if original_node.node_id in nodes_order
            else -1
        )

        # Copy results from nodes that come before the target node
        for orig_node in original_nodes:
            if nodes_order.index(orig_node.node_id) < target_node_index:
                # Get new node in the new workflow run
                new_node = await async_ops.get_workflow_node(
                    str(new_workflow_run.id), orig_node.node_id
                )

                # Copy status and results
                await async_ops.update_node_status(
                    new_node,
                    orig_node.status,
                    started_at=orig_node.started_at,
                    completed_at=orig_node.completed_at,
                    output_data=orig_node.output_data,
                )

                # Copy artifacts
                orig_artifacts = await async_ops.get_node_artifacts(orig_node)
                for artifact in orig_artifacts:
                    await async_ops.create_node_artifact(
                        new_node, artifact.name, artifact.inline_data
                    )

                # Copy logs
                orig_logs = orig_node.logs.all().order_by("timestamp")
                for log in orig_logs:
                    await async_ops.create_node_log(
                        new_node, log.level, f"[COPIED] {log.message}", log.context
                    )

        # Now execute the workflow from the target node
        # Initialize OpenAI client
        api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        client = OpenAI(api_key=api_key)

        # Build state with results from copied nodes
        state: PaperProcessingState = {
            "workflow_run_id": str(new_workflow_run.id),
            "paper_id": paper_id,
            "current_node_id": None,
            "client": client,
            "model": model,
            "force_reprocess": True,
            "paper_type_result": None,
            "code_availability_result": None,
            "code_reproducibility_result": None,
            "errors": [],
        }

        # Load previous results based on which node we're starting from
        if original_node.node_id in [
            "code_availability_check",
            "code_repository_analysis",
        ]:
            # Load paper_type_result
            paper_type_node = await async_ops.get_workflow_node(
                str(new_workflow_run.id), "paper_type_classification"
            )
            if paper_type_node and paper_type_node.status == "completed":
                artifacts = await async_ops.get_node_artifacts(paper_type_node)
                for artifact in artifacts:
                    if artifact.name == "result":
                        state["paper_type_result"] = PaperTypeClassification(
                            **artifact.inline_data
                        )
                        break

        if original_node.node_id == "code_repository_analysis":
            # Also load code_availability_result
            code_avail_node = await async_ops.get_workflow_node(
                str(new_workflow_run.id), "code_availability_check"
            )
            if code_avail_node and code_avail_node.status == "completed":
                artifacts = await async_ops.get_node_artifacts(code_avail_node)
                for artifact in artifacts:
                    if artifact.name == "result":
                        state["code_availability_result"] = CodeAvailabilityCheck(
                            **artifact.inline_data
                        )
                        break

        # Execute nodes from target node onwards
        if original_node.node_id == "paper_type_classification":
            # Execute all three nodes
            result1 = await paper_type_classification_node(state)
            if "paper_type_result" in result1:
                state["paper_type_result"] = result1["paper_type_result"]
            if "errors" in result1:
                state["errors"].extend(result1["errors"])

            result2 = await code_availability_check_node(state)
            if "code_availability_result" in result2:
                state["code_availability_result"] = result2["code_availability_result"]
            if "errors" in result2:
                state["errors"].extend(result2["errors"])

            result3 = await code_repository_analysis_node(state)
            if "code_reproducibility_result" in result3:
                state["code_reproducibility_result"] = result3[
                    "code_reproducibility_result"
                ]
            if "errors" in result3:
                state["errors"].extend(result3["errors"])

        elif original_node.node_id == "code_availability_check":
            # Execute code_availability_check and code_repository_analysis
            result1 = await code_availability_check_node(state)
            if "code_availability_result" in result1:
                state["code_availability_result"] = result1["code_availability_result"]
            if "errors" in result1:
                state["errors"].extend(result1["errors"])

            result2 = await code_repository_analysis_node(state)
            if "code_reproducibility_result" in result2:
                state["code_reproducibility_result"] = result2[
                    "code_reproducibility_result"
                ]
            if "errors" in result2:
                state["errors"].extend(result2["errors"])

        elif original_node.node_id == "code_repository_analysis":
            # Execute only code_repository_analysis
            result = await code_repository_analysis_node(state)
            if "code_reproducibility_result" in result:
                state["code_reproducibility_result"] = result[
                    "code_reproducibility_result"
                ]
            if "errors" in result:
                state["errors"].extend(result["errors"])

        # Check for errors
        errors = state.get("errors", [])
        success = len(errors) == 0

        # Update workflow run status
        await async_ops.update_workflow_run_status(
            new_workflow_run.id,
            "completed" if success else "failed",
            completed_at=timezone.now(),
            output_data={
                "success": success,
                "paper_type": (
                    state.get("paper_type_result").model_dump()
                    if state.get("paper_type_result")
                    else None
                ),
                "code_availability": (
                    state.get("code_availability_result").model_dump()
                    if state.get("code_availability_result")
                    else None
                ),
                "code_reproducibility": (
                    state.get("code_reproducibility_result").model_dump()
                    if state.get("code_reproducibility_result")
                    else None
                ),
            },
            error_message="; ".join(errors) if errors else None,
        )

        return {
            "success": success,
            "workflow_run_id": str(new_workflow_run.id),
            "run_number": new_workflow_run.run_number,
            "paper_id": paper_id,
            "started_from_node": original_node.node_id,
            "errors": errors,
        }

    except Exception as e:
        logger.error(f"Failed to execute workflow from node: {e}", exc_info=True)

        # Try to update workflow run status
        try:
            if "new_workflow_run" in locals():
                await async_ops.update_workflow_run_status(
                    new_workflow_run.id,
                    "failed",
                    completed_at=timezone.now(),
                    error_message=str(e),
                )
        except:
            pass

        return {"success": False, "error": str(e)}


async def process_paper_workflow(
    paper_id: int,
    force_reprocess: bool = False,
    openai_api_key: Optional[str] = None,
    model: str = "gpt-4o",
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Execute the complete paper processing workflow using workflow_engine.

    Args:
        paper_id: Database ID of paper to process
        force_reprocess: If True, reprocess even if already analyzed
        openai_api_key: OpenAI API key (uses env var if not provided)
        model: OpenAI model to use
        user_id: Optional user ID for tracking

    Returns:
        Dictionary with workflow results and statistics
    """
    logger.info(f"Starting paper processing workflow for paper ID {paper_id}")
    
    # Acquire semaphore (blocks until available - no timeout when running in Celery)
    # This ensures worker-level concurrency control
    _workflow_semaphore.acquire()
    active_count = await get_active_workflow_count()
    logger.info(f"Acquired workflow slot for paper {paper_id}. Active: {active_count + 1}/{MAX_CONCURRENT_WORKFLOWS}")

    try:
        # Get or create workflow definition
        workflow_def = await async_ops.get_or_create_workflow_definition(
            name="reduced_paper_processing_pipeline",
            version=3,  # Version 3 with 4-node architecture including embeddings
            description="Four-node workflow: paper type classification, section embeddings, code availability check, and conditional code repository analysis",
            dag_structure={
                "nodes": [
                    {
                        "id": "paper_type_classification",
                        "type": "python",
                        "handler": "webApp.services.paper_processing_workflow.paper_type_classification_node",
                        "description": "Classify paper type (dataset/method/both/theoretical/unknown)",
                        "config": {},
                    },
                    {
                        "id": "section_embeddings",
                        "type": "python",
                        "handler": "webApp.services.paper_processing_workflow.section_embeddings_node",
                        "description": "Compute and store vector embeddings for paper sections",
                        "config": {},
                    },
                    {
                        "id": "code_availability_check",
                        "type": "python",
                        "handler": "webApp.services.paper_processing_workflow.code_availability_check_node",
                        "description": "Check if code repository exists (database/text/online search)",
                        "config": {},
                    },
                    {
                        "id": "code_repository_analysis",
                        "type": "python",
                        "handler": "webApp.services.paper_processing_workflow.code_repository_analysis_node",
                        "description": "Analyze repository and compute reproducibility score (conditional)",
                        "config": {},
                    },
                ],
                "edges": [
                    {
                        "from": "paper_type_classification",
                        "to": "section_embeddings",
                        "type": "sequential",
                    },
                    {
                        "from": "section_embeddings",
                        "to": "code_availability_check",
                        "type": "sequential",
                    },
                    {
                        "from": "code_availability_check",
                        "to": "code_repository_analysis",
                        "type": "conditional",
                        "condition": "code_available AND paper_type NOT IN (theoretical, dataset)",
                    },
                ],
            },
        )

        # Create workflow run using orchestrator
        config = {"force_reprocess": force_reprocess, "model": model, "max_retries": 3}
        workflow_run = await async_ops.create_workflow_run_with_paper_id(
            workflow_name="reduced_paper_processing_pipeline",
            paper_id=paper_id,
            input_data=config,
        )

        # Update workflow run status to running
        await async_ops.update_workflow_run_status(
            workflow_run.id, "running", started_at=timezone.now()
        )
        
        # Register this workflow as active
        await _register_workflow(paper_id, str(workflow_run.id))

        # Initialize OpenAI client
        api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        client = OpenAI(api_key=api_key)

        # Initialize state
        initial_state: PaperProcessingState = {
            "workflow_run_id": str(workflow_run.id),
            "paper_id": paper_id,
            "current_node_id": None,
            "client": client,
            "model": model,
            "force_reprocess": force_reprocess,
            "paper_type_result": None,
            "section_embeddings_result": None,
            "code_availability_result": None,
            "code_reproducibility_result": None,
            "errors": [],
        }

        # Build and run workflow
        workflow = build_paper_processing_workflow()

        final_state = await workflow.ainvoke(initial_state)

        # Check for errors
        errors = final_state.get("errors", [])
        success = len(errors) == 0

        # Update workflow run status
        await async_ops.update_workflow_run_status(
            workflow_run.id,
            "completed" if success else "failed",
            completed_at=timezone.now(),
            output_data={
                "success": success,
                "paper_type": (
                    final_state.get("paper_type_result").model_dump()
                    if final_state.get("paper_type_result")
                    else None
                ),
                "section_embeddings": final_state.get("section_embeddings_result"),
                "code_availability": (
                    final_state.get("code_availability_result").model_dump()
                    if final_state.get("code_availability_result")
                    else None
                ),
                "code_reproducibility": (
                    final_state.get("code_reproducibility_result").model_dump()
                    if final_state.get("code_reproducibility_result")
                    else None
                ),
            },
            error_message="; ".join(errors) if errors else None,
        )

        # Get token usage from artifacts
        input_tokens, output_tokens = await async_ops.get_token_stats(
            str(workflow_run.id)
        )

        # Compile results
        results = {
            "success": success,
            "workflow_run_id": str(workflow_run.id),
            "run_number": workflow_run.run_number,
            "paper_id": paper_id,
            "paper_title": (await async_ops.get_paper(paper_id)).title,
            "paper_type": final_state.get("paper_type_result"),
            "section_embeddings": final_state.get("section_embeddings_result"),
            "code_availability": final_state.get("code_availability_result"),
            "code_reproducibility": final_state.get("code_reproducibility_result"),
            "total_input_tokens": input_tokens,
            "total_output_tokens": output_tokens,
            "errors": errors,
        }

        logger.info(
            f"Workflow run {workflow_run.id} completed. Status: {'success' if success else 'failed'}"
        )
        logger.info(f"Tokens used: {input_tokens} input, {output_tokens} output")

        return results

    except Exception as e:
        logger.error(f"Workflow execution failed: {e}", exc_info=True)

        # Try to update workflow run status
        try:
            if "workflow_run" in locals():
                await async_ops.update_workflow_run_status(
                    workflow_run.id,
                    "failed",
                    completed_at=timezone.now(),
                    error_message=str(e),
                )
        except:
            pass

        return {
            "success": False,
            "paper_id": paper_id,
            "error": str(e),
            "total_input_tokens": 0,
            "total_output_tokens": 0,
        }
    finally:
        # Always unregister workflow and release semaphore
        await _unregister_workflow(paper_id)
        _workflow_semaphore.release()
        active_count = await get_active_workflow_count()
        logger.info(f"Released workflow slot for paper {paper_id}. Active: {active_count}/{MAX_CONCURRENT_WORKFLOWS}")


# ============================================================================
# Convenience Functions
# ============================================================================


async def process_multiple_papers(
    paper_ids: List[int], force_reprocess: bool = False, max_concurrent: int = 3
) -> List[Dict[str, Any]]:
    """
    Process multiple papers concurrently.

    Args:
        paper_ids: List of paper IDs to process
        force_reprocess: If True, reprocess even if already analyzed
        max_concurrent: Maximum number of concurrent processing tasks

    Returns:
        List of results for each paper
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def process_with_limit(paper_id):
        async with semaphore:
            return await process_paper_workflow(paper_id, force_reprocess)

    tasks = [process_with_limit(pid) for pid in paper_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    return results
