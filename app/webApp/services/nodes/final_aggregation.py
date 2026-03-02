"""
Final Aggregation Node

Combines outputs from three parallel evaluation paths:
- Node G: Reproducibility Checklist (models, datasets, experiments - NO code)
- Node C: Code Repository Analysis (code-specific evaluation)
- Node E: Dataset Documentation Check (dataset-specific evaluation)

Generates a comprehensive final assessment merging all findings.
"""

import logging
from typing import Dict, Any, List, Optional

from django.utils import timezone
from workflow_engine.services.async_orchestrator import async_ops

from webApp.services.pydantic_schemas import (
    AggregatedReproducibilityAnalysis,
    CodeReproducibilityAnalysis,
    DatasetDocumentationCheck,
    FinalReproducibilityAssessment,
    FinalQualitativeAssessment,
)
from webApp.services.graphs_state import PaperProcessingState

logger = logging.getLogger(__name__)


def _compute_recommendations(
    repro_checklist: AggregatedReproducibilityAnalysis,
    code_analysis: Optional[CodeReproducibilityAnalysis],
    dataset_docs: Optional[DatasetDocumentationCheck],
    paper_type: str
) -> List[str]:
    """
    Compute prioritized recommendations programmatically from structured findings.
    
    Logic:
    1. Aggregate recommendations from all sources
    2. Prioritize based on:
       - Paper type relevance
       - Impact on overall score
       - Severity of gaps
    3. Deduplicate and limit to top 7
    
    Returns:
        List of prioritized recommendation strings
    """
    recommendations = []
    
    # 1. From reproducibility checklist
    if repro_checklist.recommendations:
        recommendations.extend(repro_checklist.recommendations[:3])
    
    # 2. From code analysis (if available)
    if code_analysis and code_analysis.recommendations:
        # Prioritize code recs for method papers
        if paper_type in ["method", "both"]:
            recommendations.extend(code_analysis.recommendations[:3])
        else:
            recommendations.extend(code_analysis.recommendations[:2])
    
    # 3. Add generic recommendations based on scores
    if repro_checklist.models_score < 50:
        recommendations.append(
            "Improve model documentation: add complete mathematical descriptions, hyperparameters, and training details"
        )
    
    if repro_checklist.datasets_score < 50:
        recommendations.append(
            "Strengthen dataset documentation: provide statistics, splits, availability statements, and ethics approval"
        )
    
    if repro_checklist.experiments_score < 50:
        recommendations.append(
            "Enhance experimental rigor: report variance across runs, statistical significance, and failure analysis"
        )
    
    if dataset_docs and dataset_docs.overall_score < 60:
        recommendations.append(
            "Dataset papers require comprehensive documentation: annotation protocols, quality control, and inter-rater agreement"
        )
    
    # Deduplicate while preserving order
    seen = set()
    unique_recs = []
    for rec in recommendations:
        rec_lower = rec.lower()
        if rec_lower not in seen:
            seen.add(rec_lower)
            unique_recs.append(rec)
    
    # Limit to top 7
    return unique_recs[:7]


async def final_aggregation_node(
    state: PaperProcessingState,
) -> Dict[str, Any]:
    """
    Final aggregation node: Merge findings from Nodes G, C, and E.
    
    This node runs after all three evaluation paths complete:
    - Node G (reproducibility checklist) always runs
    - Node C (code analysis) runs if code available and paper not theoretical
    - Node E (dataset docs) runs if paper type is dataset or both
    
    Generates comprehensive final assessment.
    
    Returns:
        Dict with final_assessment_result
    """
    node_id = "final_aggregation"
    logger.info(
        f"Final Aggregation: Merging reproducibility assessments for paper {state['paper_id']}"
    )

    # Get workflow node
    node = await async_ops.get_workflow_node(state["workflow_run_id"], node_id)

    # GUARD: Check if all required dependencies are ready before executing
    # LangGraph invokes this node for EACH incoming edge, so we need to wait for ALL dependencies
    
    # Debug: Log what's in the state
    logger.info(f"final_aggregation invoked. State keys: {list(state.keys())}")
    
    repro_checklist = state.get("reproducibility_checklist_result")
    code_availability = state.get("code_availability_result")
    dataset_docs_result = state.get("dataset_documentation_result")
    paper_type_result = state.get("paper_type_result")
    code_analysis = state.get("code_reproducibility_result")
    
    logger.info(f"Dependencies in state: repro_checklist={repro_checklist is not None}, "
               f"code_availability={code_availability is not None}, "
               f"dataset_docs={dataset_docs_result is not None}, "
               f"paper_type={paper_type_result is not None}, "
               f"code_analysis={code_analysis is not None}")
    
    # Check reproducibility_checklist (always required)
    if not repro_checklist:
        logger.info("final_aggregation invoked too early - reproducibility_checklist not yet complete. Returning early.")
        return {}
    
    # Determine if we need dataset_documentation based on paper type
    needs_dataset_docs = False
    if paper_type_result and paper_type_result.paper_type in ["dataset", "both"]:
        needs_dataset_docs = True
    
    # Check dataset_documentation if required
    if needs_dataset_docs and not dataset_docs_result:
        logger.info("final_aggregation invoked too early - dataset_documentation_check not yet complete. Returning early.")
        return {}
    
    # Determine if we need code_repository_analysis based on paper type and code availability
    needs_code_analysis = False
    if paper_type_result and paper_type_result.paper_type != "theoretical":
        if code_availability and code_availability.code_available:
            needs_code_analysis = True
    
    logger.info(f"Needs code analysis: {needs_code_analysis}, Has code analysis: {code_analysis is not None}")
    
    # Check code_repository_analysis if required
    if needs_code_analysis and not code_analysis:
        logger.info("final_aggregation invoked too early - code_repository_analysis not yet complete. Returning early.")
        return {}
    
    # All dependencies ready - proceed with execution
    logger.info(f"All dependencies ready. Proceeding with final_aggregation for paper {state['paper_id']}")
    
    # Check if already completed (for idempotency - shouldn't happen with proper guards)
    if node.status == "completed":
        logger.warning(f"final_aggregation already completed - returning cached result")
        existing_result = None
        if node.result:
            existing_result = FinalReproducibilityAssessment(**node.result.inline_data)
        if existing_result:
            return {"final_assessment_result": existing_result}
    
    # Update node status to running
    await async_ops.update_node_status(node, "running", started_at=timezone.now())
    await async_ops.create_node_log(
        node, "INFO", "Aggregating findings from reproducibility checklist, code analysis, and dataset documentation"
    )

    try:
        # Get results from state
        repro_checklist = state.get("reproducibility_checklist_result")
        code_analysis = state.get("code_reproducibility_result")
        dataset_docs = state.get("dataset_documentation_result")
        paper_type_result = state.get("paper_type_result")
        
        paper_type = paper_type_result.paper_type if paper_type_result else "unknown"
        
        # Validate required inputs
        if not repro_checklist:
            error_msg = "reproducibility_checklist_result not found in state"
            logger.error(error_msg)
            await async_ops.create_node_log(node, "ERROR", error_msg)
            raise ValueError(error_msg)
        
        logger.info(f"Inputs: repro_checklist={repro_checklist is not None}, "
                   f"code_analysis={code_analysis is not None}, "
                   f"dataset_docs={dataset_docs is not None}")
        
        # Check for force_reprocess flag
        force_reprocess = state.get("force_reprocess", False)

        # Check if already analyzed
        if not force_reprocess:
            previous = await async_ops.check_previous_analysis(
                state["paper_id"], node_id
            )
            if previous:
                logger.info(f"Found previous aggregation from {previous['completed_at']}")
                await async_ops.create_node_log(
                    node, "INFO", f"Using cached result from run {previous['run_id']}"
                )

                result = FinalReproducibilityAssessment(**previous["result"])

                # Copy previous node for token tracking
                previous_node = await async_ops.get_workflow_node(
                    previous["run_id"], node_id
                )

                if previous_node:
                    await async_ops.update_node_tokens(
                        node,
                        input_tokens=previous_node.input_tokens,
                        output_tokens=previous_node.output_tokens,
                        was_cached=True,
                    )

                await async_ops.update_node_status(
                    node, "completed", completed_at=timezone.now()
                )

                return {"final_assessment_result": result}

        # Get paper and client from state
        paper = await async_ops.get_paper(state["paper_id"])
        client = state["client"]
        model = state["model"]
        
        # Build summary of available analyses
        analyses_summary = []
        
        # 1. Reproducibility checklist (always present)
        analyses_summary.append(f"**REPRODUCIBILITY CHECKLIST**")
        analyses_summary.append(f"- Models/Algorithms: {repro_checklist.models_score:.1f}/100")
        analyses_summary.append(f"- Datasets: {repro_checklist.datasets_score:.1f}/100")
        analyses_summary.append(f"- Experiments: {repro_checklist.experiments_score:.1f}/100")
        analyses_summary.append(f"- Overall: {repro_checklist.overall_score:.1f}/100")
        analyses_summary.append(f"- Weighted ({paper_type}): {repro_checklist.weighted_score:.1f}/100")
        analyses_summary.append(f"- Summary: {repro_checklist.summary}")
        analyses_summary.append(f"- Strengths: {'; '.join(repro_checklist.strengths)}")
        analyses_summary.append(f"- Weaknesses: {'; '.join(repro_checklist.weaknesses)}")
        
        # 2. Code analysis (if available)
        has_code_analysis = code_analysis is not None
        code_score_normalized = None
        if has_code_analysis:
            analyses_summary.append(f"\n**CODE ANALYSIS**")
            analyses_summary.append(f"- Conde reproducibility Score: {code_analysis.reproducibility_score:.1f}/100")
            code_score_normalized = code_analysis.reproducibility_score  # Already 0-100 scale
            analyses_summary.append(f"- Score Breakdown: {', '.join(f'{k}: {v:.1f}' for k, v in code_analysis.score_breakdown.items())}")
            analyses_summary.append(f"- Assessment: {code_analysis.overall_assessment[:300]}")
            if code_analysis.recommendations:
                analyses_summary.append(f"- Recommendations: {'; '.join(code_analysis.recommendations[:3])}")
        else:
            analyses_summary.append(f"\n**CODE ANALYSIS**: Not performed (no code or theoretical paper)")
        
        # 3. Dataset documentation (if available)
        has_dataset_analysis = dataset_docs is not None
        if has_dataset_analysis:
            analyses_summary.append(f"\n**DATASET DOCUMENTATION**")
            analyses_summary.append(f"- News Dataset Score: {dataset_docs.overall_score:.1f}/100")
            analyses_summary.append(f"- Summary: {dataset_docs.summary}")
            if dataset_docs.dataset_name:
                analyses_summary.append(f"- Dataset Name: {dataset_docs.dataset_name}")
        else:
            analyses_summary.append(f"\n**DATASET DOCUMENTATION**: Not applicable (not a dataset paper)")
        
        analyses_text = "\n".join(analyses_summary)
        
        # Compute integrated scores
        # Strategy: Weighted combination based on what's available
        component_scores = []
        component_weights = []
        
        # Base reproducibility checklist (always present)
        component_scores.append(repro_checklist.weighted_score)
        
        # Code analysis (if present)
        # Dataset documentation (if present)
        
        # Assign weights based on availability (sum to 1.0)
        if has_code_analysis and has_dataset_analysis:
            # All three: 50% checklist, 20% code, 30% dataset
            component_weights.append(0.5)
            component_scores.append(code_score_normalized)
            component_weights.append(0.2)
            component_scores.append(dataset_docs.overall_score)
            component_weights.append(0.3)
        elif has_code_analysis:
            # Checklist + code: 60% checklist, 40% code
            component_weights.append(0.6)
            component_scores.append(code_score_normalized)
            component_weights.append(0.4)
        elif has_dataset_analysis:
            # Checklist + dataset: 60% checklist, 40% dataset
            component_weights.append(0.6)
            component_scores.append(dataset_docs.overall_score)
            component_weights.append(0.4)
        else:
            # Only checklist: 100%
            component_weights.append(1.0)
        
        # Weights now sum to exactly 1.0, no normalization needed
        # (kept for safety in case of future changes)
        total_weight = sum(component_weights)
        if abs(total_weight - 1.0) > 0.001:
            logger.warning(f"Component weights don't sum to 1.0 (sum={total_weight}), normalizing")
            component_weights = [w / total_weight for w in component_weights]
        
        # Compute weighted overall score
        overall_score = sum(s * w for s, w in zip(component_scores, component_weights))
        
        logger.info(
            f"Score computation: components={len(component_scores)}, "
            f"scores={[f'{s:.1f}' for s in component_scores]}, "
            f"weights={[f'{w:.2f}' for w in component_weights]}, "
            f"overall={overall_score:.1f}"
        )
        
        # Compute recommendations programmatically (like Node C)
        logger.info("Computing prioritized recommendations programmatically...")
        recommendations = _compute_recommendations(
            repro_checklist, code_analysis, dataset_docs, paper_type
        )
        
        # Call LLM ONLY for qualitative text generation (no scores)
        await async_ops.create_node_log(
            node, "INFO", "Generating qualitative assessment (summary, strengths, weaknesses)"
        )
        
        system_prompt = f"""You are writing qualitative text for a reproducibility assessment of a {paper_type} paper.

You will receive analyses and COMPUTED SCORES from multiple sources.
Your task: Generate ONLY executive summary, strengths, and weaknesses.
DO NOT generate scores or recommendations - those are computed programmatically.

Focus on synthesizing findings into coherent narrative text."""

        user_prompt = f"""Paper: {paper.title}
Paper Type: {paper_type}

COMPONENT ANALYSES:
{analyses_text}

COMPUTED SCORES (already calculated):
- Overall Score: {overall_score:.1f}/100
- Paper Checklist: {repro_checklist.weighted_score:.1f}/100 (weight: {component_weights[0]:.0%})
{f'- Code Analysis: {code_score_normalized:.1f}/100 (weight: {component_weights[1]:.0%})' if has_code_analysis else ''}
{f'- Dataset Analysis: {dataset_docs.overall_score:.1f}/100 (weight: {component_weights[-1]:.0%})' if has_dataset_analysis else ''}

Generate:
1. Executive summary (2-3 paragraphs synthesizing key findings and their implications)
2. Strengths (3-7 concrete reproducibility strengths across all dimensions)
3. Weaknesses (3-7 specific gaps or areas needing improvement)

Create a unified narrative connecting findings across all evaluation dimensions."""

        # Call LLM for text only
        response = client.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format=FinalQualitativeAssessment,
            reasoning_effort="minimal",
        #temperature=0.3,
        )
        
        qualitative = response.choices[0].message.parsed
        
        # Merge detailed evaluation criteria from all components
        evaluation_details = {}
        
        # 1. Reproducibility checklist details - retrieve individual criterion analyses from artifact
        repro_checklist_node = await async_ops.get_workflow_node(state["workflow_run_id"], "reproducibility_checklist")
        criterion_analyses_artifact = await async_ops.get_node_artifact(repro_checklist_node, "criterion_analyses")
        
        if criterion_analyses_artifact and criterion_analyses_artifact.inline_data:
            # Individual criterion analyses (20 items with present/confidence/evidence/notes)
            individual_criteria = criterion_analyses_artifact.inline_data
        else:
            logger.warning("No criterion_analyses artifact found - using empty list")
            individual_criteria = []
        
        repro_checklist_dict = repro_checklist.model_dump()
        evaluation_details["paper_checklist"] = {
            # Individual criteria (present/absent with confidence and evidence for each)
            "criteria": individual_criteria,
            # Category scores and overall assessment
            "category_scores": {
                "models": repro_checklist.models_score,
                "datasets": repro_checklist.datasets_score,
                "experiments": repro_checklist.experiments_score,
            },
            "overall_score": repro_checklist.overall_score,
            "weighted_score": repro_checklist.weighted_score,
            "paper_type_context": repro_checklist.paper_type_context,
        }
        
        # 2. Code analysis details (if available)
        if has_code_analysis:
            evaluation_details["code_analysis"] = {
                "research_methodology": code_analysis.research_methodology.model_dump() if code_analysis.research_methodology else None,
                "repository_structure": code_analysis.repository_structure.model_dump() if code_analysis.repository_structure else None,
                "code_components": code_analysis.code_components.model_dump() if code_analysis.code_components else None,
                "artifacts": code_analysis.artifacts.model_dump() if code_analysis.artifacts else None,
                "dataset_splits": code_analysis.dataset_splits.model_dump() if code_analysis.dataset_splits else None,
                "documentation": code_analysis.documentation.model_dump() if code_analysis.documentation else None,
                "reproducibility_score": code_analysis.reproducibility_score,
                "score_breakdown": code_analysis.score_breakdown,
            }
        else:
            evaluation_details["code_analysis"] = None
        
        # 3. Dataset documentation details (if available with individual criteria)
        if has_dataset_analysis:
            dataset_docs_node = await async_ops.get_workflow_node(state["workflow_run_id"], "dataset_documentation_check")
            dataset_criterion_analyses_artifact = await async_ops.get_node_artifact(dataset_docs_node, "criterion_analyses")
            
            if dataset_criterion_analyses_artifact and dataset_criterion_analyses_artifact.inline_data:
                dataset_individual_criteria = dataset_criterion_analyses_artifact.inline_data
            else:
                logger.warning("No dataset criterion_analyses artifact found - using empty list")
                dataset_individual_criteria = []
            
            evaluation_details["dataset_documentation"] = {
                "criteria": dataset_individual_criteria,
                "category_scores": dataset_docs.model_dump().get("category_scores"),
                "overall_score": dataset_docs.overall_score,
            }
        else:
            evaluation_details["dataset_documentation"] = None
        
        logger.info(f"Merged evaluation details with {len([k for k, v in evaluation_details.items() if v is not None])} components")
        
        # Build final result with programmatically computed scores + LLM text + detailed criteria
        final_result = FinalReproducibilityAssessment(
            # Scores (computed programmatically)
            paper_checklist_score=repro_checklist.weighted_score,
            code_analysis_score=code_score_normalized,
            dataset_documentation_score=dataset_docs.overall_score if has_dataset_analysis else None,
            overall_score=round(overall_score, 1),
            weighted_score=round(overall_score, 1),
            
            # Qualitative text (LLM-generated)
            executive_summary=qualitative.executive_summary,
            strengths=qualitative.strengths,
            weaknesses=qualitative.weaknesses,
            
            # Recommendations (computed programmatically)
            recommendations=recommendations,
            
            # Metadata
            has_code_analysis=has_code_analysis,
            has_dataset_analysis=has_dataset_analysis,
            paper_type=paper_type,
            
            # Detailed evaluation criteria (for human comparison)
            evaluation_details=evaluation_details
        )
        
        # Track tokens
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens
        
        await async_ops.update_node_tokens(
            node,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            was_cached=False
        )
        
        logger.info(
            f"Final assessment complete. Overall: {final_result.overall_score:.1f}/100. "
            f"Tokens: {input_tokens + output_tokens} (in: {input_tokens}, out: {output_tokens})"
        )

        # Store result as NodeArtifact
        await async_ops.create_node_artifact(node, "result", final_result)

        # Update node status
        await async_ops.update_node_status(
            node,
            "completed",
            completed_at=timezone.now(),
            output_summary=f"Final reproducibility: {final_result.overall_score:.1f}/100. {final_result.executive_summary[:200]}",
        )

        return {"final_assessment_result": final_result}

    except Exception as e:
        logger.error(f"Error in final aggregation: {e}", exc_info=True)
        await async_ops.create_node_log(node, "ERROR", f"Failed: {str(e)}")
        await async_ops.update_node_status(
            node, "failed", completed_at=timezone.now()
        )
        raise
