"""
Paper Processing Workflow - Integrated with Workflow Engine

This module implements a five-node workflow for analyzing papers:
- Node A: Paper Type Classification (dataset vs method vs both)
- Node D: Section Embeddings (compute vector embeddings for paper sections)
- Node B: Code Availability Check (agentic analysis of code availability and quality)
- Node F: Code Embedding (ingest repository and compute embeddings for code files)
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

from typing import Optional, Dict, Any, List

from django.utils import timezone

from langgraph.graph import StateGraph, END
from openai import OpenAI

from workflow_engine.services.async_orchestrator import async_ops

from webApp.services.nodes.paper_type_classification import (
    paper_type_classification_node,
)
from webApp.services.nodes.section_embeddings import section_embeddings_node
from webApp.services.nodes.code_repository_analysis import code_repository_analysis_node
from webApp.services.nodes.code_availability_check import code_availability_check_node
from webApp.services.nodes.code_embedding import code_embedding_node

from ..pydantic_schemas import (
    PaperTypeClassification,
    CodeAvailabilityCheck,
    CodeEmbeddingResult,
)
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


class PaperProcessingWorkflow(BaseWorkflowGraph):
    """
    Five-node workflow for comprehensive paper processing with conditional routing.

    Nodes:
    1. paper_type_classification (A): Classify paper type
    2. section_embeddings (D): Compute embeddings for paper sections
    3. code_availability_check (B): Check code availability
    4. code_embedding (F): Ingest and embed code repository (conditional)
    5. code_repository_analysis (C): Comprehensive code analysis (conditional)
    """

    WORKFLOW_NAME = "reduced_paper_processing_pipeline"
    WORKFLOW_VERSION = "4"
    NODE_ORDER = [
        "paper_type_classification",
        "section_embeddings",
        "code_availability_check",
        "code_embedding",
        "code_repository_analysis",
    ]

    def build_workflow(self) -> StateGraph:
        """
        Build the LangGraph workflow for paper processing with conditional routing.

        Workflow structure (sequential with conditional routing):
        - Node A (paper_type_classification): Classify paper type
        - Node D (section_embeddings): Compute embeddings for paper sections
        - Node B (code_availability_check): Check code availability and verify accessibility
        - Node F (code_embedding): Ingest repository and compute code file embeddings (conditional)
        - Node C (code_repository_analysis): Comprehensive code analysis (conditional)

        Flow:
        1. paper_type_classification runs first
        2. section_embeddings runs second (computes embeddings for sections)
        3. code_availability_check runs third (for all non-theoretical papers)
        4. After code_availability_check, route to:
           * Node F (code_embedding) if code is available
           * END if no code found
        5. After code_embedding, route to:
           * Node C (code_repository_analysis) for full analysis
           * END if embedding failed
        """

        workflow = StateGraph(PaperProcessingState)

        # Add nodes
        workflow.add_node("paper_type_classification", paper_type_classification_node)
        workflow.add_node("section_embeddings", section_embeddings_node)
        workflow.add_node("code_availability_check", code_availability_check_node)
        workflow.add_node("code_embedding", code_embedding_node)
        workflow.add_node("code_repository_analysis", code_repository_analysis_node)

        # Define routing function after paper type classification
        def route_after_classification(state: PaperProcessingState) -> str:
            """
            Route after paper type classification.

            Returns:
                - END if paper is theoretical
                - "section_embeddings" otherwise
            """
            paper_type_result = state.get("paper_type_result")

            if paper_type_result and paper_type_result.paper_type == "theoretical":
                logger.info("Ending workflow early for theoretical paper")
                return END

            return "section_embeddings"

        # Define routing function after code availability check
        def route_after_availability(state: PaperProcessingState) -> str:
            """
            Route after code availability check.

            Returns:
                - "code_embedding" if code is available
                - END if no code found
            """
            code_availability = state.get("code_availability_result")

            # Skip if no code available
            if not code_availability or not code_availability.code_available:
                logger.info("Ending workflow - no code available")
                return END

            # Proceed to code embedding for papers with code
            logger.info("Proceeding to code embedding")
            return "code_embedding"

        # Define routing function after code embedding
        def route_after_embedding(state: PaperProcessingState) -> str:
            """
            Route after code embedding.

            Returns:
                - "code_repository_analysis" if embedding succeeded
                - END if embedding failed (unlikely but defensive)
            """
            code_embedding = state.get("code_embedding_result")

            if not code_embedding:
                logger.warning("Code embedding result missing - ending workflow")
                return END

            # Always proceed to repository analysis after embedding
            logger.info("Proceeding to code repository analysis")
            return "code_repository_analysis"

        # Set entry point and conditional flow
        workflow.set_entry_point("paper_type_classification")

        # Conditional routing after classification - end early for theoretical papers
        workflow.add_conditional_edges(
            "paper_type_classification",
            route_after_classification,
            {
                "section_embeddings": "section_embeddings",
                END: END,
            },
        )

        workflow.add_edge("section_embeddings", "code_availability_check")

        # Conditional routing after availability check
        workflow.add_conditional_edges(
            "code_availability_check",
            route_after_availability,
            {
                "code_embedding": "code_embedding",
                END: END,
            },
        )

        # Conditional routing after code embedding
        workflow.add_conditional_edges(
            "code_embedding",
            route_after_embedding,
            {
                "code_repository_analysis": "code_repository_analysis",
                END: END,
            },
        )

        # Code repository analysis always ends
        workflow.add_edge("code_repository_analysis", END)

        return workflow.compile()

    async def _get_workflow_node_order(self) -> list:
        """Return the ordered list of node IDs."""
        return self.NODE_ORDER

    async def _load_node_dependencies(
        self, node, workflow_run, state: PaperProcessingState
    ) -> PaperProcessingState:
        """Load dependencies for a specific node from previous nodes."""

        if node.node_id == "section_embeddings":
            # Need paper_type_result from previous node (though not strictly required)
            prev_node = await async_ops.get_workflow_node(
                str(workflow_run.id), "paper_type_classification"
            )
            if prev_node and prev_node.status == "completed":
                artifacts = await async_ops.get_node_artifacts(prev_node)
                for artifact in artifacts:
                    if artifact.name == "result":
                        state["paper_type_result"] = PaperTypeClassification(
                            **artifact.inline_data
                        )
                        break

        elif node.node_id == "code_availability_check":
            # Need paper_type_result from previous node
            prev_node = await async_ops.get_workflow_node(
                str(workflow_run.id), "paper_type_classification"
            )
            if prev_node and prev_node.status == "completed":
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

        elif node.node_id == "code_embedding":
            # Need code_availability_result from previous node
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

        elif node.node_id == "code_repository_analysis":
            # Need paper_type_result, code_availability_result, and code_embedding_result
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

            code_embedding_node = await async_ops.get_workflow_node(
                str(workflow_run.id), "code_embedding"
            )
            if code_embedding_node and code_embedding_node.status == "completed":
                artifacts = await async_ops.get_node_artifacts(code_embedding_node)
                for artifact in artifacts:
                    if artifact.name == "result":
                        state["code_embedding_result"] = CodeEmbeddingResult(
                            **artifact.inline_data
                        )
                        logger.info(
                            f"Loaded code_embedding_result: {state['code_embedding_result'].total_files} files embedded"
                        )
                        break

        return state

    async def _execute_node_function(
        self, node_id: str, state: PaperProcessingState
    ) -> Dict[str, Any]:
        """Execute the function for a specific node."""

        if node_id == "paper_type_classification":
            return await paper_type_classification_node(state)
        elif node_id == "section_embeddings":
            return await section_embeddings_node(state)
        elif node_id == "code_availability_check":
            return await code_availability_check_node(state)
        elif node_id == "code_embedding":
            return await code_embedding_node(state)
        elif node_id == "code_repository_analysis":
            return await code_repository_analysis_node(state)
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
                elif node_id == "section_embeddings":
                    # Section embeddings result is typically a dict with embedding info
                    state["section_embeddings_result"] = artifact.inline_data
                elif node_id == "code_availability_check":
                    state["code_availability_result"] = CodeAvailabilityCheck(
                        **artifact.inline_data
                    )
                elif node_id == "code_embedding":
                    state["code_embedding_result"] = CodeEmbeddingResult(
                        **artifact.inline_data
                    )
                # Note: code_repository_analysis result is stored as code_reproducibility_result

        return state

    async def _mark_cancelled_nodes(
        self, workflow_run_id: str, final_state: PaperProcessingState
    ) -> None:
        """
        Mark nodes as cancelled when they were intentionally skipped due to workflow routing decisions.
        
        Nodes are marked as cancelled when:
        - Node B (code_availability_check) determines no code is available -> mark F and C as cancelled
        - Node F (code_embedding) fails or is skipped -> mark C as cancelled
        """
        # Check if code_availability_check ran and determined no code available
        code_availability = final_state.get("code_availability_result")
        paper_type = final_state.get("paper_type_result")
        code_embedding = final_state.get("code_embedding_result")
        
        # If paper is theoretical, mark section_embeddings, code_availability_check, code_embedding, and code_repository_analysis as cancelled
        if paper_type and paper_type.paper_type == "theoretical":
            for node_id in ["section_embeddings", "code_availability_check", "code_embedding", "code_repository_analysis"]:
                node = await async_ops.get_workflow_node(workflow_run_id, node_id)
                if node and node.status == "pending":
                    await async_ops.update_node_status(node, "cancelled")
                    logger.info(f"Marked node {node_id} as cancelled (theoretical paper)")
        
        # If no code available, mark code_embedding and code_repository_analysis as cancelled
        elif code_availability and not code_availability.code_available:
            for node_id in ["code_embedding", "code_repository_analysis"]:
                node = await async_ops.get_workflow_node(workflow_run_id, node_id)
                if node and node.status == "pending":
                    await async_ops.update_node_status(node, "cancelled")
                    logger.info(f"Marked node {node_id} as cancelled (no code available)")
        
        # If code_embedding didn't produce results, mark code_repository_analysis as cancelled
        elif not code_embedding:
            node = await async_ops.get_workflow_node(workflow_run_id, "code_repository_analysis")
            if node and node.status == "pending":
                await async_ops.update_node_status(node, "cancelled")
                logger.info("Marked code_repository_analysis as cancelled (code embedding failed)")

    async def execute_workflow(
        self,
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
        logger.info(
            f"Acquired workflow slot for paper {paper_id}. Active: {active_count + 1}/{MAX_CONCURRENT_WORKFLOWS}"
        )

        try:
            # Get or create workflow definition
            workflow_def = await async_ops.get_or_create_workflow_definition(
                name="reduced_paper_processing_pipeline",
                version=4,  # Version 4 with 5-node architecture including code embedding
                description="Five-node workflow: paper type classification, section embeddings, code availability check, code embedding, and conditional code repository analysis",
                dag_structure={
                    "workflow_handler": {
                        "module": "webApp.services.graphs.paper_processing_workflow",
                        "function": "execute_workflow",
                    },
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
                            "id": "code_embedding",
                            "type": "python",
                            "handler": "webApp.services.paper_processing_workflow.code_embedding_node",
                            "description": "Ingest and embed code repository files (conditional)",
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
                            "to": "code_embedding",
                            "type": "conditional",
                            "condition": "code_available",
                        },
                        {
                            "from": "code_embedding",
                            "to": "code_repository_analysis",
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
            errors = final_state.get("errors", [])
            success = len(errors) == 0
            
            # Mark unexecuted nodes as cancelled based on workflow routing decisions
            await self._mark_cancelled_nodes(workflow_run.id, final_state)
            
            # Aggregate token counts from all nodes
            await async_ops.aggregate_workflow_run_tokens(workflow_run.id)

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
                    "code_embedding": (
                        final_state.get("code_embedding_result").model_dump()
                        if final_state.get("code_embedding_result")
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
            
            # Reload workflow_run to get aggregated token counts
            workflow_run = await async_ops.get_workflow_run(workflow_run.id)

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
                "code_embedding": final_state.get("code_embedding_result"),
                "code_reproducibility": final_state.get("code_reproducibility_result"),
                "total_input_tokens": workflow_run.total_input_tokens,
                "total_output_tokens": workflow_run.total_output_tokens,
                "total_tokens": workflow_run.total_tokens,
                "errors": errors,
            }

            logger.info(
                f"Workflow run {workflow_run.id} completed. Status: {'success' if success else 'failed'}"
            )
            logger.info(f"Tokens used: {workflow_run.total_input_tokens} input, {workflow_run.total_output_tokens} output")

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
            logger.info(
                f"Released workflow slot for paper {paper_id}. Active: {active_count}/{MAX_CONCURRENT_WORKFLOWS}"
            )


# ============================================================================
# Singleton Instance & Convenience Functions
# ============================================================================

# Create singleton instance
_workflow_instance = PaperProcessingWorkflow()


async def execute_workflow(
    paper_id: int,
    force_reprocess: bool = False,
    openai_api_key: Optional[str] = None,
    model: str = "gpt-4o",
) -> Dict[str, Any]:
    """
    Execute the complete paper processing workflow.

    Convenience function for workflow_handler - uses the singleton workflow instance.
    Note: This matches the naming convention in process_code_availability.py
    """
    return await _workflow_instance.execute_workflow(
        paper_id, force_reprocess, openai_api_key, model
    )


async def process_paper_workflow(
    paper_id: int,
    force_reprocess: bool = False,
    openai_api_key: Optional[str] = None,
    model: str = "gpt-4o",
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Execute the complete paper processing workflow.

    Convenience function that uses the singleton workflow instance.
    Kept for backward compatibility.
    """
    return await _workflow_instance.execute_workflow(
        paper_id, force_reprocess, openai_api_key, model, user_id
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
    force_reprocess: bool = True,
) -> Dict[str, Any]:
    """
    Execute workflow from a specific node onwards.

    Convenience function that uses the singleton workflow instance.
    """
    return await _workflow_instance.execute_from_node(node_uuid, openai_api_key, model, force_reprocess)


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
