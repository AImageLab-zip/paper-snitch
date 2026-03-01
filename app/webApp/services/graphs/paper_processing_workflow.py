"""
Paper Processing Workflow - Integrated with Workflow Engine

This module implements an eight-node workflow for analyzing papers with parallel reproducibility evaluation:

Sequential nodes:
- Node A: Paper Type Classification (dataset vs method vs both vs theoretical)
- Node D: Section Embeddings (compute vector embeddings for paper sections)

Parallel branches (execute simultaneously):
- Dataset Documentation Check: Evaluate dataset docs (for dataset/both papers)
- Reproducibility Checklist: Evaluate 26 MICCAI criteria (all papers)  
- Node B: Code Availability Check (agentic analysis of code availability)

Synchronization:
- Join Node: Consolidate results from parallel execution

Conditional code analysis:
- Node F: Code Embedding (ingest repository and compute embeddings for code files)
- Node C: Code Repository Analysis (comprehensive analysis of repository structure)

Properly integrated with the workflow_engine models for:
- History tracking
- Versioning
- Artifact storage
- Progress monitoring
- Parallel execution and synchronization
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
from webApp.services.nodes.dataset_documentation_check import (
    dataset_documentation_check_node,
)
from webApp.services.nodes.reproducibility_checklist import (
    reproducibility_checklist_node,
)
from webApp.services.nodes.code_repository_analysis import code_repository_analysis_node
from webApp.services.nodes.code_availability_check import code_availability_check_node
from webApp.services.nodes.code_embedding import code_embedding_node
from webApp.services.nodes.final_aggregation import final_aggregation_node

from ..pydantic_schemas import (
    PaperTypeClassification,
    DatasetDocumentationCheck,
    ReproducibilityChecklist,
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
    Seven-node workflow for comprehensive paper processing with parallel evaluation.

    Nodes:
    1. paper_type_classification (A): Classify paper type
    2. section_embeddings (D): Compute embeddings for paper sections
    
    Parallel branches (execute simultaneously):
    3. dataset_documentation_check: Evaluate dataset documentation (dataset/both papers)
    4. reproducibility_checklist: Evaluate reproducibility criteria (all papers)
    5. code_availability_check (B): Check code availability
    
    6. join_parallel_branches: Join results from parallel execution
    7. code_embedding (F): Ingest and embed code repository (conditional)
    8. code_repository_analysis (C): Comprehensive code analysis (conditional)
    """

    WORKFLOW_NAME = "paper_processing_with_reproducibility"
    WORKFLOW_VERSION = "8"
    NODE_ORDER = [
        "paper_type_classification",
        "section_embeddings",
        # Parallel branches
        "dataset_documentation_check",
        "reproducibility_checklist",
        "code_availability_check",
        # Conditional code analysis
        "code_embedding",
        "code_repository_analysis",
        # Final aggregation
        "final_aggregation",
    ]

    def build_workflow(self) -> StateGraph:
        """
        Build the LangGraph workflow with parallel reproducibility evaluation.

        Workflow structure (fan-out/fan-in with parallel execution):
        - Node A (paper_type_classification): Classify paper type
        - Node D (section_embeddings): Compute embeddings for paper sections
        
        PARALLEL BRANCHES (execute simultaneously):
        - dataset_documentation_check: Evaluate dataset docs (skips if not dataset/both)
        - reproducibility_checklist: Evaluate MICCAI criteria (all papers)
        - code_availability_check: Check code availability
        
        - join_parallel_branches: Consolidate parallel results
        - code_embedding: Ingest repository (conditional on code availability)
        - code_repository_analysis: Comprehensive analysis (conditional)

        Flow:
        1. paper_type_classification → section_embeddings
        2. section_embeddings fans out to 3 parallel nodes
        3. All 3 parallel nodes converge to join node
        4. join → code_embedding (if code available) OR END
        5. code_embedding → code_repository_analysis OR END
        """

        workflow = StateGraph(PaperProcessingState)

        # Add all nodes
        workflow.add_node("paper_type_classification", paper_type_classification_node)
        workflow.add_node("section_embeddings", section_embeddings_node)
        workflow.add_node("dataset_documentation_check", dataset_documentation_check_node)
        workflow.add_node("reproducibility_checklist", reproducibility_checklist_node)
        workflow.add_node("code_availability_check", code_availability_check_node)
        workflow.add_node("code_embedding", code_embedding_node)
        workflow.add_node("code_repository_analysis", code_repository_analysis_node)
        workflow.add_node("final_aggregation", final_aggregation_node)

        # Define routing function after section embeddings
        def route_after_embeddings(state: PaperProcessingState) -> List[str]:
            """
            Route after section embeddings based on paper type.

            Returns:
                - ["reproducibility_checklist"] if paper is theoretical (skip code and dataset branches)
                - ["dataset_documentation_check", "reproducibility_checklist", "code_availability_check"] otherwise
            """
            paper_type_result = state.get("paper_type_result")

            if paper_type_result and paper_type_result.paper_type == "theoretical":
                logger.info("Theoretical paper - routing to paper analysis only")
                return ["reproducibility_checklist"]

            logger.info("Non-theoretical paper - routing to all evaluation branches")
            return ["dataset_documentation_check", "reproducibility_checklist", "code_availability_check"]

        # Note: No routing function needed for code branch
        # Progressive skipping in code_availability_check marks downstream nodes as skipped when no code

        # Set entry point
        workflow.set_entry_point("paper_type_classification")

        # Paper type classification always goes to section embeddings
        workflow.add_edge("paper_type_classification", "section_embeddings")

        # Conditional fan-out after section embeddings based on paper type
        # Theoretical papers: only go to reproducibility_checklist
        # Other papers: go to all three branches
        workflow.add_conditional_edges(
            "section_embeddings",
            route_after_embeddings,
        )

        # All evaluation branches converge to final aggregation
        workflow.add_edge("dataset_documentation_check", "final_aggregation")
        workflow.add_edge("reproducibility_checklist", "final_aggregation")

        # Code branch: availability check routes to code_embedding unconditionally
        # Progressive skipping marks downstream nodes as skipped when no code is available
        workflow.add_edge("code_availability_check", "code_embedding")

        # Code embedding always goes to repository analysis
        workflow.add_edge("code_embedding", "code_repository_analysis")

        # Code repository analysis goes to final aggregation
        workflow.add_edge("code_repository_analysis", "final_aggregation")

        # Final aggregation ends the workflow
        workflow.add_edge("final_aggregation", END)

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

        elif node.node_id == "dataset_documentation_check":
            # Part of parallel branch - needs paper_type_result
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
                            f"Loaded paper_type_result for dataset_documentation_check: {state['paper_type_result'].paper_type}"
                        )
                        break

        elif node.node_id == "reproducibility_checklist":
            # Part of parallel branch - needs paper_type_result
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
                            f"Loaded paper_type_result for reproducibility_checklist: {state['paper_type_result'].paper_type}"
                        )
                        break
            
            # Also optionally load code availability result if it completed before us
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
                            "Loaded code_availability_result for reproducibility_checklist"
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

        elif node.node_id == "final_aggregation":
            # Need results from reproducibility_checklist, code_repository_analysis (if available), and dataset_documentation (if available)
            # Also need paper_type and code_availability for context
            
            # Load paper type (always needed)
            paper_type_node = await async_ops.get_workflow_node(
                str(workflow_run.id), "paper_type_classification"
            )
            if paper_type_node and paper_type_node.status == "completed":
                if paper_type_node.output_data:
                    if "paper_type_result" in paper_type_node.output_data:
                        state["paper_type_result"] = PaperTypeClassification(
                            **paper_type_node.output_data["paper_type_result"]
                        )
                        logger.info("Loaded paper_type_result for final_aggregation")
            
            # Load reproducibility checklist (always needed)
            repro_node = await async_ops.get_workflow_node(
                str(workflow_run.id), "reproducibility_checklist"
            )
            if repro_node and repro_node.status == "completed":
                if repro_node.output_data:
                    if "reproducibility_checklist_result" in repro_node.output_data:
                        from webApp.services.pydantic_schemas import AggregatedReproducibilityAnalysis
                        state["reproducibility_checklist_result"] = AggregatedReproducibilityAnalysis(
                            **repro_node.output_data["reproducibility_checklist_result"]
                        )
                        logger.info("Loaded reproducibility_checklist_result for final_aggregation")

            # Load code availability (needed to understand code analysis context)
            code_avail_node = await async_ops.get_workflow_node(
                str(workflow_run.id), "code_availability_check"
            )
            if code_avail_node and code_avail_node.status == "completed":
                if code_avail_node.output_data:
                    if "code_availability_result" in code_avail_node.output_data:
                        from webApp.services.pydantic_schemas import CodeAvailabilityAnalysis
                        state["code_availability_result"] = CodeAvailabilityAnalysis(
                            **code_avail_node.output_data["code_availability_result"]
                        )
                        logger.info("Loaded code_availability_result for final_aggregation")

            # Load code analysis (if it was executed)
            code_analysis_node = await async_ops.get_workflow_node(
                str(workflow_run.id), "code_repository_analysis"
            )
            if code_analysis_node and code_analysis_node.status == "completed":
                if code_analysis_node.output_data:
                    if "code_reproducibility_result" in code_analysis_node.output_data:
                        from webApp.services.pydantic_schemas import CodeReproducibilityAnalysis
                        state["code_reproducibility_result"] = CodeReproducibilityAnalysis(
                            **code_analysis_node.output_data["code_reproducibility_result"]
                        )
                        logger.info("Loaded code_reproducibility_result for final_aggregation")

            # Load dataset documentation (if it was executed)
            dataset_doc_node = await async_ops.get_workflow_node(
                str(workflow_run.id), "dataset_documentation_check"
            )
            if dataset_doc_node and dataset_doc_node.status == "completed":
                if dataset_doc_node.output_data:
                    if "dataset_documentation_result" in dataset_doc_node.output_data:
                        from webApp.services.pydantic_schemas import AggregatedDatasetDocumentationAnalysis
                        state["dataset_documentation_result"] = AggregatedDatasetDocumentationAnalysis(
                            **dataset_doc_node.output_data["dataset_documentation_result"]
                        )
                        logger.info("Loaded dataset_documentation_result for final_aggregation")

        return state

    async def _execute_node_function(
        self, node_id: str, state: PaperProcessingState
    ) -> Dict[str, Any]:
        """Execute the function for a specific node."""

        if node_id == "paper_type_classification":
            return await paper_type_classification_node(state)
        elif node_id == "section_embeddings":
            return await section_embeddings_node(state)
        elif node_id == "dataset_documentation_check":
            return await dataset_documentation_check_node(state)
        elif node_id == "reproducibility_checklist":
            return await reproducibility_checklist_node(state)
        elif node_id == "code_availability_check":
            return await code_availability_check_node(state)
        elif node_id == "code_embedding":
            return await code_embedding_node(state)
        elif node_id == "code_repository_analysis":
            return await code_repository_analysis_node(state)
        elif node_id == "final_aggregation":
            return await final_aggregation_node(state)
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
                elif node_id == "dataset_documentation_check":
                    state["dataset_documentation_result"] = DatasetDocumentationCheck(
                        **artifact.inline_data
                    )
                elif node_id == "reproducibility_checklist":
                    state["reproducibility_checklist_result"] = ReproducibilityChecklist(
                        **artifact.inline_data
                    )
                elif node_id == "code_availability_check":
                    state["code_availability_result"] = CodeAvailabilityCheck(
                        **artifact.inline_data
                    )
                elif node_id == "code_embedding":
                    state["code_embedding_result"] = CodeEmbeddingResult(
                        **artifact.inline_data
                    )
                elif node_id == "final_aggregation":
                    # Final aggregation result contains the complete assessment
                    state["final_aggregation_result"] = artifact.inline_data
                # Note: code_repository_analysis result is stored as code_reproducibility_result

        return state

    async def _mark_skipped_nodes(
        self, workflow_run_id: str, final_state: PaperProcessingState
    ) -> None:
        """
        Mark nodes as skipped when they were intentionally bypassed due to workflow routing decisions.
        
        Nodes are marked as skipped when:
        - Paper is theoretical -> skip dataset analysis and code branches (no dataset/code needed)
        - Paper doesn't propose dataset -> skip dataset_documentation_check
        - No code available -> skip code_embedding and code_repository_analysis
        - Code embedding fails -> skip code_repository_analysis
        """
        # Check workflow state
        code_availability = final_state.get("code_availability_result")
        paper_type = final_state.get("paper_type_result")
        code_embedding = final_state.get("code_embedding_result")
        
        # If paper is theoretical, skip dataset and code branches
        if paper_type and paper_type.paper_type == "theoretical":
            skipped_nodes = [
                "dataset_documentation_check",
                "code_availability_check",
                "code_embedding",
                "code_repository_analysis",
            ]
            for node_id in skipped_nodes:
                node = await async_ops.get_workflow_node(workflow_run_id, node_id)
                if node and node.status == "pending":
                    await async_ops.update_node_status(node, "skipped")
                    await async_ops.create_node_log(
                        node, "INFO", "Skipped (theoretical paper - no dataset/code analysis needed)"
                    )
                    logger.info(f"Marked node {node_id} as skipped (theoretical paper)")
        
        # If paper doesn't propose dataset (method only), skip dataset documentation check
        elif paper_type and paper_type.paper_type == "method":
            node = await async_ops.get_workflow_node(workflow_run_id, "dataset_documentation_check")
            if node and node.status == "pending":
                await async_ops.update_node_status(node, "skipped")
                await async_ops.create_node_log(
                    node, "INFO", "Skipped (method-only paper - no dataset proposed)"
                )
                logger.info("Marked dataset_documentation_check as skipped (method-only paper)")
        
        # If no code available, skip code embedding and analysis
        if code_availability and not code_availability.code_available:
            for node_id in ["code_embedding", "code_repository_analysis"]:
                node = await async_ops.get_workflow_node(workflow_run_id, node_id)
                if node and node.status == "pending":
                    await async_ops.update_node_status(node, "skipped")
                    await async_ops.create_node_log(
                        node, "INFO", "Skipped (no code repository available)"
                    )
                    logger.info(f"Marked node {node_id} as skipped (no code repository)")
        
        # If code_embedding didn't produce results, skip code_repository_analysis
        elif not code_embedding:
            node = await async_ops.get_workflow_node(workflow_run_id, "code_repository_analysis")
            if node and node.status == "pending":
                await async_ops.update_node_status(node, "skipped")
                await async_ops.create_node_log(
                    node, "INFO", "Skipped (code embedding failed or not executed)"
                )
                logger.info("Marked code_repository_analysis as skipped (code embedding failed)")

    async def execute_workflow(
        self,
        paper_id: int,
        force_reprocess: bool = False,
        openai_api_key: Optional[str] = None,
        model: str = "gpt-5",
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
                name="paper_processing_with_reproducibility",
                version=8,  # Version 8 - removed LangGraph conditional routing to final_aggregation, linear chain with progressive skipping
                description="Eight-node workflow: paper type → section embeddings → parallel branches (reproducibility checklist, code availability→embeddings→analysis, dataset documentation) → all converge at final aggregation. Progressive skipping marks nodes as skipped when branches are inapplicable.",
                dag_structure={
                    "workflow_handler": {
                        "module": "webApp.services.graphs.paper_processing_workflow",
                        "function": "execute_workflow",
                    },
                    "nodes": [
                        {
                            "id": "paper_type_classification",
                            "type": "python",
                            "name": "Paper Type",
                            "handler": "webApp.services.nodes.paper_type_classification.paper_type_classification_node",
                            "description": "Classify paper type (dataset/method/both/theoretical/unknown)",
                            "config": {},
                        },
                        {
                            "id": "section_embeddings",
                            "type": "python",
                            "name": "Section Embeddings",
                            "handler": "webApp.services.nodes.section_embeddings.section_embeddings_node",
                            "description": "Compute and store vector embeddings for paper sections",
                            "config": {},
                        },
                        {
                            "id": "dataset_documentation_check",
                            "type": "python",
                            "name": "Dataset Analysis",
                            "handler": "webApp.services.nodes.dataset_documentation_check.dataset_documentation_check_node",
                            "description": "Evaluate dataset documentation completeness (for dataset/both papers)",
                            "config": {},
                        },
                        {
                            "id": "reproducibility_checklist",
                            "type": "python",
                            "name": "Paper Analysis",
                            "handler": "webApp.services.nodes.reproducibility_checklist.reproducibility_checklist_node",
                            "description": "Evaluate MICCAI reproducibility checklist (26 criteria)",
                            "config": {},
                        },
                        {
                            "id": "code_availability_check",
                            "type": "python",
                            "name": "Code Availability",
                            "handler": "webApp.services.nodes.code_availability_check.code_availability_check_node",
                            "description": "Check if code repository exists (database/text/online search)",
                            "config": {},
                        },

                        {
                            "id": "code_embedding",
                            "type": "python",
                            "name": "Code Embeddings",
                            "handler": "webApp.services.nodes.code_embedding.code_embedding_node",
                            "description": "Ingest and embed code repository files (conditional)",
                            "config": {},
                        },
                        {
                            "id": "code_repository_analysis",
                            "type": "python",
                            "name": "Code Analysis",
                            "handler": "webApp.services.nodes.code_repository_analysis.code_repository_analysis_node",
                            "description": "Analyze repository and compute reproducibility score (conditional)",
                            "config": {},
                        },
                        {
                            "id": "final_aggregation",
                            "type": "python",
                            "name": "Final Aggregation",
                            "handler": "webApp.services.nodes.final_aggregation.final_aggregation_node",
                            "description": "Merge findings from all evaluation nodes into final assessment",
                            "config": {},
                        },
                    ],
                    "edges": [
                        {
                            "from": "paper_type_classification",
                            "to": "section_embeddings",
                            "type": "sequential",
                        },
                        # Parallel fan-out from section_embeddings to three analysis paths
                        {
                            "from": "section_embeddings",
                            "to": "reproducibility_checklist",
                            "type": "parallel",
                        },
                        {
                            "from": "section_embeddings",
                            "to": "code_availability_check",
                            "type": "parallel",
                        },
                        {
                            "from": "section_embeddings",
                            "to": "dataset_documentation_check",
                            "type": "conditional",
                            "condition": "has_dataset",
                        },
                        # Paper Analysis path (direct to final aggregation)
                        {
                            "from": "reproducibility_checklist",
                            "to": "final_aggregation",
                            "type": "sequential",
                        },
                        # Code path (availability → embeddings → analysis → final aggregation)
                        # Progressive skipping marks code_embedding and code_repository_analysis as skipped when no code
                        {
                            "from": "code_availability_check",
                            "to": "code_embedding",
                            "type": "sequential",
                        },
                        {
                            "from": "code_embedding",
                            "to": "code_repository_analysis",
                            "type": "sequential",
                        },
                        {
                            "from": "code_repository_analysis",
                            "to": "final_aggregation",
                            "type": "sequential",
                        },
                        # Dataset Analysis path (direct to final aggregation)
                        {
                            "from": "dataset_documentation_check",
                            "to": "final_aggregation",
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
            
            # Mark unexecuted nodes as skipped based on workflow routing decisions
            await self._mark_skipped_nodes(workflow_run.id, final_state)
            
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
    model: str = "gpt-5",
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
    model: str = "gpt-5",
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
    model: str = "gpt-5",
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
    model: str = "gpt-5",
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
