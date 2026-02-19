"""
Process Code Availability Workflow - Simplified Two-Node Pipeline

This module implements a simplified two-node workflow for analyzing papers:
- Node A: Paper Type Classification (dataset vs method vs both)
- Node B: Code Availability Check (agentic analysis of code availability and quality)

Properly integrated with the workflow_engine models for:
- History tracking
- Versioning
- Artifact storage
- Progress monitoring
"""

import os
import logging

from typing import Optional, Dict, Any

from django.utils import timezone

from langgraph.graph import StateGraph, END
from openai import OpenAI

from workflow_engine.services.async_orchestrator import async_ops

from webApp.services.nodes.paper_type_classification import (
    paper_type_classification_node,
)
from webApp.services.nodes.code_availability_check import code_availability_check_node

from ..pydantic_schemas import (
    PaperTypeClassification,
    CodeAvailabilityCheck,
)
from ..graphs_state import PaperProcessingState
from .base_workflow_graph import BaseWorkflowGraph

logger = logging.getLogger(__name__)


# ============================================================================
# Workflow Class Definition
# ============================================================================


class CodeAvailabilityWorkflow(BaseWorkflowGraph):
    """
    Two-node workflow for code availability analysis.

    Nodes:
    1. paper_type_classification: Classify paper type
    2. code_availability_check: Check code availability
    """

    WORKFLOW_NAME = "code_availability_pipeline"
    WORKFLOW_VERSION = "1"
    NODE_ORDER = ["paper_type_classification", "code_availability_check"]

    def build_workflow(self) -> StateGraph:
        """
        Build the LangGraph workflow for code availability processing.

        Workflow structure (sequential):
        - Node A (paper_type_classification): Classify paper type
        - Node B (code_availability_check): Check code availability and verify accessibility

        Flow:
        1. paper_type_classification runs first
        2. code_availability_check runs second and completes the workflow
        """

        workflow = StateGraph(PaperProcessingState)

        # Add nodes
        workflow.add_node("paper_type_classification", paper_type_classification_node)
        workflow.add_node("code_availability_check", code_availability_check_node)

        # Set entry point and sequential flow
        workflow.set_entry_point("paper_type_classification")
        workflow.add_edge("paper_type_classification", "code_availability_check")
        workflow.add_edge("code_availability_check", END)

        return workflow.compile()

    async def _get_workflow_node_order(self) -> list:
        """Return the ordered list of node IDs."""
        return self.NODE_ORDER

    async def _load_node_dependencies(
        self, node, workflow_run, state: PaperProcessingState
    ) -> PaperProcessingState:
        """Load dependencies for a specific node from previous nodes."""

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

        return state

    async def _execute_node_function(
        self, node_id: str, state: PaperProcessingState
    ) -> Dict[str, Any]:
        """Execute the function for a specific node."""

        if node_id == "paper_type_classification":
            return await paper_type_classification_node(state)
        elif node_id == "code_availability_check":
            return await code_availability_check_node(state)
        else:
            raise ValueError(f"Unknown node_id: {node_id}")

    async def _load_artifacts_into_state(
        self, node_id: str, artifacts, state: PaperProcessingState
    ) -> PaperProcessingState:
        """Load artifacts from a node into the state."""

        for artifact in artifacts:
            if artifact.name == "result":
                if node_id == "paper_type_classification":
                    state["paper_type_result"] = PaperTypeClassification(
                        **artifact.inline_data
                    )
                elif node_id == "code_availability_check":
                    state["code_availability_result"] = CodeAvailabilityCheck(
                        **artifact.inline_data
                    )

        return state

    async def execute_workflow(
        self,
        paper_id: int,
        force_reprocess: bool = False,
        openai_api_key: Optional[str] = None,
        model: str = "gpt-4o",
    ) -> Dict[str, Any]:
        """
        Execute the code availability workflow for a paper.

        Args:
            paper_id: Database ID of the paper to process
            force_reprocess: If True, bypass cache and reprocess all nodes
            openai_api_key: OpenAI API key (uses env var if not provided)
            model: OpenAI model to use (default: gpt-4o)

        Returns:
            Dictionary with workflow results including:
            - success: bool
            - workflow_run_id: UUID
            - run_number: int
            - paper_type_result: PaperTypeClassification or None
            - code_availability_result: CodeAvailabilityCheck or None
            - errors: list of error messages
        """
        logger.info(
            f"Starting code availability workflow for paper {paper_id} with force_reprocess={force_reprocess}"
        )

        try:
            # Ensure workflow definition exists
            await async_ops.get_or_create_workflow_definition(
                name=self.WORKFLOW_NAME,
                version=self.WORKFLOW_VERSION,
                description="Two-node workflow: paper type classification and code availability check",
                dag_structure={
                    "workflow_handler": {
                        "module": "webApp.services.graphs.process_code_availability",
                        "function": "execute_workflow",
                    },
                    "nodes": [
                        {
                            "id": "paper_type_classification",
                            "type": "python",
                            "handler": "webApp.services.graphs.process_code_availability.paper_type_classification_node",
                            "description": "Classify paper type (dataset/method/both/theoretical/unknown)",
                            "config": {},
                        },
                        {
                            "id": "code_availability_check",
                            "type": "python",
                            "handler": "webApp.services.graphs.process_code_availability.code_availability_check_node",
                            "description": "Check if code repository exists (database/text/online search)",
                            "config": {},
                        },
                    ],
                    "edges": [
                        {
                            "from": "paper_type_classification",
                            "to": "code_availability_check",
                            "type": "sequential",
                        },
                    ],
                },
            )

            # Create workflow run using orchestrator
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
                "code_availability_result": None,
                "code_reproducibility_result": None,
                "errors": [],
            }

            # Build and run workflow
            workflow = self.build_workflow()

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
                    "code_availability": (
                        final_state.get("code_availability_result").model_dump()
                        if final_state.get("code_availability_result")
                        else None
                    ),
                },
                error_message="; ".join(errors) if errors else None,
            )

            logger.info(
                f"Workflow completed for paper {paper_id}. Success: {success}, Run ID: {workflow_run.id}"
            )

            return {
                "success": success,
                "workflow_run_id": str(workflow_run.id),
                "run_number": workflow_run.run_number,
                "paper_id": paper_id,
                "paper_type_result": final_state.get("paper_type_result"),
                "code_availability_result": final_state.get("code_availability_result"),
                "errors": errors,
            }

        except Exception as e:
            logger.error(f"Workflow failed for paper {paper_id}: {e}", exc_info=True)

            # Try to update workflow run status to failed
            try:
                if "workflow_run" in locals():
                    await async_ops.update_workflow_run_status(
                        workflow_run.id,
                        "failed",
                        completed_at=timezone.now(),
                        error_message=str(e),
                    )
            except Exception as inner_e:
                logger.error(f"Failed to update workflow run status: {inner_e}")

            return {
                "success": False,
                "error": str(e),
                "paper_id": paper_id,
                "errors": [str(e)],
            }


# ============================================================================
# Singleton Instance & Convenience Functions
# ============================================================================

# Create singleton instance
_workflow_instance = CodeAvailabilityWorkflow()


async def execute_workflow(
    paper_id: int,
    force_reprocess: bool = False,
    openai_api_key: Optional[str] = None,
    model: str = "gpt-4o",
) -> Dict[str, Any]:
    """
    Execute the code availability workflow for a paper.

    Convenience function that uses the singleton workflow instance.
    """
    return await _workflow_instance.execute_workflow(
        paper_id, force_reprocess, openai_api_key, model
    )


async def execute_a_node(
    node_uuid: str,
    force_reprocess: bool = True,
    openai_api_key: Optional[str] = None,
    model: str = "gpt-4o",
) -> Dict[str, Any]:
    """
    Execute a single node in isolation.

    Convenience function that uses the singleton workflow instance.
    """
    return await _workflow_instance.execute_a_node(
        node_uuid, force_reprocess, openai_api_key, model
    )


async def execute_from_node(
    node_uuid: str,
    openai_api_key: Optional[str] = None,
    model: str = "gpt-4o",
) -> Dict[str, Any]:
    """
    Execute workflow from a specific node onwards.

    Convenience function that uses the singleton workflow instance.
    """
    return await _workflow_instance.execute_from_node(node_uuid, openai_api_key, model)
