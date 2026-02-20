import logging

from typing import Dict, Any
from datetime import datetime
from django.utils import timezone
from pathlib import Path as PathlibPath


from workflow_engine.services.async_orchestrator import async_ops
from .shared_helpers import analyze_repository_comprehensive

from webApp.services.pydantic_schemas import (
    CodeAvailabilityCheck,
    CodeReproducibilityAnalysis,
)
from webApp.services.graphs_state import PaperProcessingState

logger = logging.getLogger(__name__)


async def code_repository_analysis_node(
    state: PaperProcessingState,
) -> Dict[str, Any]:
    """
    Node C: Comprehensive code repository analysis.

    This node performs deep analysis of the code repository:
    1. Verify code accessibility (download sample)
    2. Download and analyze full repository
    3. Evaluate reproducibility components
    4. Compute reproducibility score

    Only runs if:
    - Code was found by Node B, AND
    - Paper type is 'method', 'both', or 'unknown' (not 'theoretical' or 'dataset')

    Results are stored as NodeArtifacts.
    """
    node_id = "code_repository_analysis"
    logger.info(
        f"Node C: Starting code repository analysis for paper {state['paper_id']}"
    )

    # Get workflow node
    node = await async_ops.get_workflow_node(state["workflow_run_id"], node_id)

    # Update node status to running
    await async_ops.update_node_status(node, "running", started_at=timezone.now())
    await async_ops.create_node_log(
        node, "INFO", "Starting code reproducibility analysis"
    )

    try:
        # Check for previous analysis
        force_reprocess = state.get("force_reprocess", False)
        if not force_reprocess:
            previous = await async_ops.check_previous_analysis(
                state["paper_id"], node_id
            )
            if previous:
                logger.info(
                    f"Found previous code analysis from {previous['completed_at']}"
                )
                await async_ops.create_node_log(
                    node, "INFO", f"Using cached result from run {previous['run_id']}"
                )

                result = CodeReproducibilityAnalysis(**previous["result"])
                await async_ops.create_node_artifact(node, "result", result)
                
                # Copy tokens from previous execution
                previous_node = await async_ops.get_most_recent_completed_node(
                    paper_id=state["paper_id"],
                    node_id=node_id,
                    exclude_run_id=state["workflow_run_id"]
                )
                
                if previous_node:
                    await async_ops.update_node_tokens(
                        node,
                        input_tokens=previous_node.input_tokens,
                        output_tokens=previous_node.output_tokens,
                        was_cached=True
                    )
                    logger.info(
                        f"Copied tokens from previous execution: {previous_node.total_tokens} total"
                    )
                
                await async_ops.update_node_status(
                    node, "completed", completed_at=timezone.now()
                )

                return {"code_reproducibility_result": result}

        # Get code URL from Node B (code_availability_check_node)
        code_availability = state.get("code_availability_result")
        if not code_availability or not code_availability.code_available:
            # This shouldn't happen due to routing, but handle defensively
            logger.warning(
                "Node C called without code availability - this indicates routing issue"
            )
            analysis = CodeReproducibilityAnalysis(
                analysis_timestamp=datetime.utcnow().isoformat(),
                code_availability=code_availability
                or CodeAvailabilityCheck(
                    code_available=False,
                    code_url=None,
                    found_online=False,
                    availability_notes="Code availability result missing",
                ),
                reproducibility_score=0.0,
                score_breakdown={},
                overall_assessment="Code not available - analysis skipped",
                recommendations=["Code must be available for repository analysis"],
            )

            await async_ops.create_node_artifact(node, "result", analysis)
            await async_ops.update_node_status(
                node, "completed", completed_at=timezone.now()
            )

            return {"code_reproducibility_result": analysis}

        code_url = code_availability.code_url
        paper = await async_ops.get_paper(state["paper_id"])
        client = state["client"]
        model = state["model"]

        # Check if Node B provided a local clone path (use it to avoid re-cloning)
        source = code_url  # Default to URL
        if code_availability.clone_path:
            clone_path = PathlibPath(code_availability.clone_path)
            if clone_path.exists():
                logger.info(f"Reusing clone from Node B: {clone_path}")
                await async_ops.create_node_log(
                    node, "INFO", f"Reusing verified clone from Node B: {clone_path}"
                )
                source = str(clone_path)  # Use local path instead of URL
            else:
                logger.warning(f"Clone path from Node B no longer exists: {clone_path}")
                await async_ops.create_node_log(
                    node,
                    "WARNING",
                    "Clone from Node B not found, will re-clone from URL",
                )

        logger.info(f"Analyzing repository: {source}")

        repo_analysis = await analyze_repository_comprehensive(
            source, paper, client, model, node=node
        )

        # Step 2: Compile complete analysis
        analysis = CodeReproducibilityAnalysis(
            analysis_timestamp=datetime.utcnow().isoformat(),
            code_availability=code_availability,  # Use result from Node B
            research_methodology=repo_analysis.get("methodology"),
            repository_structure=repo_analysis.get("structure"),
            code_components=repo_analysis.get("components"),
            artifacts=repo_analysis.get("artifacts"),
            dataset_splits=repo_analysis.get("dataset_splits"),
            documentation=repo_analysis.get("documentation"),
            reproducibility_score=repo_analysis.get("reproducibility_score", 0.0),
            score_breakdown=repo_analysis.get("score_breakdown", {}),
            overall_assessment=repo_analysis.get("overall_assessment", ""),
            recommendations=repo_analysis.get("recommendations", []),
            input_tokens=repo_analysis.get("input_tokens", 0),
            output_tokens=repo_analysis.get("output_tokens", 0),
        )

        # Store as artifacts

        await async_ops.create_node_artifact(node, "result", analysis)
        await async_ops.create_node_artifact(
            node,
            "token_usage",
            {
                "input_tokens": repo_analysis.get("input_tokens", 0),
                "output_tokens": repo_analysis.get("output_tokens", 0),
            },
        )
        
        # Update node token fields in database
        await async_ops.update_node_tokens(
            node,
            input_tokens=repo_analysis.get("input_tokens", 0),
            output_tokens=repo_analysis.get("output_tokens", 0),
            was_cached=False
        )

        # Store detailed LLM analysis if available
        if repo_analysis.get("llm_analysis_text"):
            await async_ops.create_node_artifact(
                node,
                "llm_analysis",
                {
                    "analysis_text": repo_analysis["llm_analysis_text"],
                    "structured_data": repo_analysis.get("structured_data", {}),
                },
            )

        # Log detailed results
        await async_ops.create_node_log(
            node,
            "INFO",
            f"Analysis complete - Score: {analysis.reproducibility_score}/10",
            {"score_breakdown": analysis.score_breakdown},
        )

        # Log detailed component availability
        components_summary = []
        if analysis.code_components:
            components_summary.append(
                f"Training code: {analysis.code_components.has_training_code}"
            )
            components_summary.append(
                f"Evaluation code: {analysis.code_components.has_evaluation_code}"
            )
            components_summary.append(
                f"Documented commands: {analysis.code_components.has_documented_commands}"
            )
        if analysis.artifacts:
            components_summary.append(
                f"Checkpoints available: {analysis.artifacts.has_checkpoints}"
            )
            components_summary.append(
                f"Dataset links: {analysis.artifacts.has_dataset_links}"
            )
        if analysis.documentation:
            components_summary.append(f"README: {analysis.documentation.has_readme}")
            components_summary.append(
                f"Results table: {analysis.documentation.has_results_table}"
            )

        if components_summary:
            await async_ops.create_node_log(
                node,
                "INFO",
                "Component availability:\n"
                + "\n".join(f"  • {item}" for item in components_summary),
            )

        # Update node status
        await async_ops.update_node_status(
            node,
            "completed",
            completed_at=timezone.now(),
            output_data={"code_available": True, "code_url": code_url},
        )

        return {"code_reproducibility_result": analysis}

    except Exception as e:
        logger.error(f"Error in code reproducibility analysis: {e}", exc_info=True)
        return {"errors": state["errors"] + [f"Node C error: {str(e)}"]}
