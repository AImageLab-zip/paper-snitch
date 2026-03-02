"""
Code Availability Only Workflow - Single Node Pipeline

This module implements a single-node workflow for checking code availability:
- Node: Code Availability Check (check database, text, and online for code repositories)

This workflow is independent and doesn't require paper type classification.
Useful for quickly checking code availability across all papers.
"""

import os
import logging

from typing import Dict, Any, Optional

from django.utils import timezone

from langgraph.graph import StateGraph, END
from openai import OpenAI

from workflow_engine.services.async_orchestrator import async_ops

from webApp.services.nodes.code_availability_check import code_availability_check_node

from ..graphs_state import PaperProcessingState
from .base_workflow_graph import (
    BaseWorkflowGraph,
    _workflow_semaphore,
    get_active_workflow_count,
    _register_workflow,
    _unregister_workflow,
    MAX_CONCURRENT_WORKFLOWS,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Workflow Class Definition
# ============================================================================


class CodeOnlyWorkflow(BaseWorkflowGraph):
    """
    Single-node workflow for code availability checking.

    Nodes:
    1. code_availability_check: Check code availability (database, text, online search)
    """

    WORKFLOW_NAME = "code_only_pipeline"
    WORKFLOW_VERSION = "1"
    NODE_ORDER = ["code_availability_check"]

    def build_workflow(self) -> StateGraph:
        """
        Build the LangGraph workflow for code availability checking only.

        Workflow structure (single node):
        - Node: code_availability_check

        Flow:
        1. code_availability_check runs and completes the workflow
        """

        workflow = StateGraph(PaperProcessingState)

        # Add node
        workflow.add_node("code_availability_check", code_availability_check_node)

        # Set entry point and end
        workflow.set_entry_point("code_availability_check")
        workflow.add_edge("code_availability_check", END)

        return workflow.compile()

    async def _get_workflow_node_order(self) -> list:
        """Return the ordered list of node IDs."""
        return self.NODE_ORDER

    async def _load_node_dependencies(
        self, node, workflow_run, state: PaperProcessingState
    ) -> PaperProcessingState:
        """Load dependencies for a specific node from previous nodes."""
        # code_availability_check has no dependencies in this workflow
        return state

    async def _execute_node_function(
        self, node_id: str, state: PaperProcessingState
    ) -> Dict[str, Any]:
        """Execute the function for a specific node."""

        if node_id == "code_availability_check":
            return await code_availability_check_node(state)

        raise ValueError(f"Unknown node ID: {node_id}")

    async def _load_artifacts_into_state(
        self, node, state: PaperProcessingState
    ) -> PaperProcessingState:
        """Load artifacts from a completed node into the state."""

        artifacts = await async_ops.get_node_artifacts(node)

        for artifact in artifacts:
            if node.node_id == "code_availability_check" and artifact.name == "result":
                from ..pydantic_schemas import CodeAvailabilityCheck

                state["code_availability_result"] = CodeAvailabilityCheck(
                    **artifact.inline_data
                )
                logger.info(
                    f"Loaded code_availability_result: code_available={state['code_availability_result'].code_available}"
                )

        return state


    async def execute_workflow(
        self,
        paper_id: int,
        force_reprocess: bool = False,
        openai_api_key: Optional[str] = None,
        model: str = "gpt-5",
    ) -> Dict[str, Any]:
        """
        Execute the code-only workflow for a paper.

        Args:
            paper_id: Database ID of paper to process
            force_reprocess: If True, reprocess even if already analyzed
            openai_api_key: OpenAI API key (uses env var if not provided)
            model: OpenAI model to use

        Returns:
            Dictionary with workflow results and statistics
        """
        logger.info(f"Starting code-only workflow for paper ID {paper_id}")

        # Acquire semaphore (blocks until available)
        _workflow_semaphore.acquire()
        active_count = await get_active_workflow_count()
        logger.info(
            f"Acquired workflow slot for paper {paper_id}. Active: {active_count + 1}/{MAX_CONCURRENT_WORKFLOWS}"
        )

        try:
            # Get or create workflow definition
            workflow_def = await async_ops.get_or_create_workflow_definition(
                name="code_only_pipeline",
                version=1,
                description="Single-node workflow: code availability check only",
                dag_structure={
                    "workflow_handler": {
                        "module": "webApp.services.graphs.code_only_workflow",
                        "function": "execute_workflow",
                    },
                    "nodes": [
                        {
                            "id": "code_availability_check",
                            "type": "python",
                            "handler": "webApp.services.nodes.code_availability_check.code_availability_check_node",
                            "description": "Check if code repository exists (database/text/online search)",
                            "config": {},
                        },
                    ],
                    "edges": [],
                },
            )

            # Create workflow run
            config = {
                "force_reprocess": force_reprocess,
                "model": model,
                "max_retries": 3,
            }
            workflow_run = await async_ops.create_workflow_run_with_paper_id(
                workflow_name=self.WORKFLOW_NAME,
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
                "code_embedding_result": None,
                "code_reproducibility_result": None,
                "errors": [],
            }

            # Build and run workflow
            workflow = self.build_workflow()

            final_state = await workflow.ainvoke(initial_state)

            # Check for errors
            if final_state.get("errors"):
                error_msg = "; ".join(final_state["errors"])
                logger.error(f"Code-only workflow failed for paper {paper_id}: {error_msg}")
                await async_ops.update_workflow_run_status(
                    workflow_run.id,
                    "failed",
                    completed_at=timezone.now(),
                    error_message=error_msg,
                )
                return {
                    "status": "failed",
                    "error": error_msg,
                    "workflow_run_id": str(workflow_run.id),
                }

            # Mark workflow as completed
            await async_ops.update_workflow_run_status(
                workflow_run.id, "completed", completed_at=timezone.now()
            )

            logger.info(f"Code-only workflow completed for paper {paper_id}")

            return {
                "status": "completed",
                "workflow_run_id": str(workflow_run.id),
                "code_availability_result": final_state.get("code_availability_result"),
            }

        except Exception as e:
            logger.error(
                f"Code-only workflow failed for paper {paper_id}: {e}", exc_info=True
            )
            try:
                await async_ops.update_workflow_run_status(
                    workflow_run.id,
                    "failed",
                    completed_at=timezone.now(),
                    error_message=str(e),
                )
            except:
                pass

            return {
                "status": "failed",
                "error": str(e),
                "workflow_run_id": str(workflow_run.id) if workflow_run else None,
            }

        finally:
            # Unregister workflow and release sempahore
            await _unregister_workflow(paper_id)
            _workflow_semaphore.release()


# ============================================================================
# Singleton Instance
# ============================================================================


_workflow_instance = CodeOnlyWorkflow()


# ============================================================================
# Workflow Execution Function (Entry Point)
# ============================================================================


async def execute_workflow(
    paper_id: int,
    force_reprocess: bool = False,
    openai_api_key: Optional[str] = None,
    model: str = "gpt-5",
) -> Dict[str, Any]:
    """
    Execute the code-only workflow for a paper.

    Args:
        paper_id: Database ID of the paper to process
        force_reprocess: If True, reprocess even if already analyzed
        openai_api_key: Optional OpenAI API key (uses env var if not provided)
        model: OpenAI model to use for analysis

    Returns:
        Dict containing code_availability_result and workflow execution status
    """
    return await _workflow_instance.execute_workflow(
        paper_id, force_reprocess, openai_api_key, model
    )
