"""
Node G: Reproducibility Checklist Analysis (Multi-Step Process)

Analyzes 20 MICCAI reproducibility criteria (excludes code-related 12-17).
Uses a multi-step process similar to Node C:
1. Load criteria from database with embeddings
2. For each criterion: retrieve relevant sections → LLM analysis
3. Aggregate results with final LLM call → compute scores

Adapts evaluation weights based on paper type.
"""

import json
import logging
from typing import Dict, Any, List, Tuple
import numpy as np

from django.utils import timezone
from asgiref.sync import sync_to_async
from workflow_engine.services.async_orchestrator import async_ops

from webApp.models import ReproducibilityChecklistCriterion, PaperSectionEmbedding
from webApp.services.pydantic_schemas import (
    SingleCriterionAnalysis,
    AggregatedReproducibilityAnalysis,
)
from webApp.services.graphs_state import PaperProcessingState
from webApp.services.nodes.reproducibility_criteria import get_all_criteria

logger = logging.getLogger(__name__)


# Reproducibility criteria weights by paper type (excluding code category)
CRITERIA_WEIGHTS = {
    "dataset": {
        "models": 0.15,  # Low importance for dataset papers
        "datasets": 0.60,  # Critical for dataset papers
        "experiments": 0.25,  # Baseline experiments expected
    },
    "method": {
        "models": 0.45,  # Critical for method papers
        "datasets": 0.20,  # Using existing datasets is fine
        "experiments": 0.35,  # Experimental validation expected
    },
    "both": {
        "models": 0.35,  # High importance
        "datasets": 0.35,  # High importance
        "experiments": 0.30,
    },
    "theoretical": {
        "models": 0.55,  # Mathematical descriptions critical
        "datasets": 0.05,  # Not applicable
        "experiments": 0.40,  # Theoretical validation
    },
    "unknown": {
        # Neutral weights
        "models": 0.35,
        "datasets": 0.30,
        "experiments": 0.35,
    },
}


async def reproducibility_checklist_node(
    state: PaperProcessingState,
) -> Dict[str, Any]:
    """
    Node G: Multi-step reproducibility checklist analysis.
    
    Process:
    1. Load 20 criteria from database (with embeddings)
    2. For each criterion:
       - Find most relevant paper sections via cosine similarity
       - Analyze with LLM (SingleCriterionAnalysis)
    3. Aggregate all analyses with final LLM call
    4. Compute category scores and weighted score
    
    Returns:
        Dict with reproducibility_checklist_result
    """
    node_id = "reproducibility_checklist"
    logger.info(
        f"Node G: Starting multi-step reproducibility checklist for paper {state['paper_id']}"
    )

    # Get workflow node
    node = await async_ops.get_workflow_node(state["workflow_run_id"], node_id)

    # Update node status to running
    await async_ops.update_node_status(node, "running", started_at=timezone.now())
    await async_ops.create_node_log(
        node, "INFO", "Starting multi-step reproducibility analysis (20 criteria, excludes code)"
    )

    try:
        # Get paper type from state
        paper_type_result = state.get("paper_type_result")
        if not paper_type_result:
            paper_type = "unknown"
            logger.warning("Paper type not found in state, using 'unknown'")
        else:
            paper_type = paper_type_result.paper_type

        logger.info(f"Paper type: {paper_type}")

        # Check for force_reprocess flag
        force_reprocess = state.get("force_reprocess", False)

        # Check if already analyzed
        if not force_reprocess:
            previous = await async_ops.check_previous_analysis(
                state["paper_id"], node_id
            )
            if previous:
                logger.info(f"Found previous analysis from {previous['completed_at']}")
                await async_ops.create_node_log(
                    node, "INFO", f"Using cached result from run {previous['run_id']}"
                )

                result = AggregatedReproducibilityAnalysis(**previous["result"])

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
                    logger.info(
                        f"Copied tokens from previous execution: {previous_node.total_tokens} total"
                    )

                await async_ops.update_node_status(
                    node, "completed", completed_at=timezone.now()
                )

                return {"reproducibility_checklist_result": result}

        # Get paper and client from state
        paper = await async_ops.get_paper(state["paper_id"])
        client = state["client"]
        model = state["model"]

        # Step 1: Load criteria from database
        await async_ops.create_node_log(
            node, "INFO", "Loading 20 reproducibility criteria from database"
        )
        
        criteria_models = await sync_to_async(
            lambda: list(ReproducibilityChecklistCriterion.objects.filter(
                embedding_model="text-embedding-3-small"
            ).order_by('criterion_number'))
        )()
        
        if len(criteria_models) != 20:
            error_msg = f"Expected 20 criteria, found {len(criteria_models)}. Run 'python manage.py initialize_criteria_embeddings'"
            logger.error(error_msg)
            await async_ops.create_node_log(node, "ERROR", error_msg)
            raise ValueError(error_msg)
        
        logger.info(f"Loaded {len(criteria_models)} criteria from database")
        
        # Step 2: Analyze each criterion individually
        criterion_analyses = []
        total_input_tokens = 0
        total_output_tokens = 0
        
        for i, criterion_model in enumerate(criteria_models, 1):
            logger.info(
                f"Analyzing criterion {i}/20: {criterion_model.criterion_name}"
            )
            
            # Retrieve relevant sections using cosine similarity
            relevant_sections = await _retrieve_sections_for_criterion(
                paper_id=paper.id,
                criterion_embedding=criterion_model.embedding,
                top_k=3,
                max_chars_per_section=1500
            )
            
            if relevant_sections:
                sections_text = "\n\n".join([
                    f"=== {sec_type.upper()} (similarity: {sim:.3f}) ===\n{text}"
                    for sim, sec_type, text in relevant_sections
                ])
                logger.debug(
                    f"  Found {len(relevant_sections)} relevant sections "
                    f"(avg similarity: {np.mean([s[0] for s in relevant_sections]):.3f})"
                )
            else:
                sections_text = f"Abstract: {paper.abstract or 'N/A'}"
                logger.warning(f"  No relevant sections found, using abstract only")
            
            # Build LLM prompt for this criterion
            system_prompt = f"""You are evaluating a single MICCAI reproducibility criterion for a {paper_type} paper.

Criterion: {criterion_model.criterion_name}
Description: {criterion_model.description}
Category: {criterion_model.category}

Assess whether this criterion is satisfied based on the paper sections provided.
Be precise and evidence-based. Quote specific text when possible."""

            user_prompt = f"""Paper Title: {paper.title}
Paper Type: {paper_type}

Relevant Paper Sections:
{sections_text}

Evaluate criterion "{criterion_model.criterion_name}" for this paper.
Provide your assessment with:
1. Whether the criterion is present/satisfied (true/false)
2. Your confidence (0-1)
3. Evidence text (direct quote, max 500 chars)
4. Page/section reference
5. Additional notes if needed
6. Importance level for THIS {paper_type} paper: 'critical', 'important', or 'optional'"""

            # Call LLM
            try:
                response = client.beta.chat.completions.parse(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format=SingleCriterionAnalysis,
                    reasoning_effort="minimal",
        #temperature=0.1,
                )
                
                analysis = response.choices[0].message.parsed
                
                # Ensure criterion fields are set correctly
                analysis_dict = analysis.model_dump()
                analysis_dict["criterion_id"] = criterion_model.criterion_id
                analysis_dict["criterion_number"] = criterion_model.criterion_number
                analysis_dict["criterion_name"] = criterion_model.criterion_name
                analysis_dict["category"] = criterion_model.category
                analysis = SingleCriterionAnalysis(**analysis_dict)
                
                criterion_analyses.append(analysis)
                
                # Track tokens
                total_input_tokens += response.usage.prompt_tokens
                total_output_tokens += response.usage.completion_tokens
                
                logger.info(
                    f"  Result: present={analysis.present}, confidence={analysis.confidence:.2f}, "
                    f"importance={analysis.importance}"
                )
                
            except Exception as e:
                logger.error(f"  Error analyzing criterion {criterion_model.criterion_name}: {e}")
                await async_ops.create_node_log(
                    node, "WARNING", f"Failed criterion {criterion_model.criterion_name}: {str(e)}"
                )
                # Continue with other criteria
                continue
        
        logger.info(f"Completed individual criterion analyses: {len(criterion_analyses)}/20")
        
        if len(criterion_analyses) == 0:
            error_msg = "No criteria were successfully analyzed"
            logger.error(error_msg)
            await async_ops.create_node_log(node, "ERROR", error_msg)
            raise ValueError(error_msg)
        
        # Step 3: Aggregate results with final LLM call
        await async_ops.create_node_log(
            node, "INFO", f"Aggregating {len(criterion_analyses)} criterion analyses"
        )
        
        aggregated_result = await _aggregate_criterion_analyses(
            criterion_analyses=criterion_analyses,
            paper_type=paper_type,
            paper_title=paper.title
        )
        
        # No aggregation tokens - fully programmatic
        
        # Update node token fields
        await async_ops.update_node_tokens(
            node,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            was_cached=False
        )
        
        logger.info(
            f"Reproducibility analysis complete. Overall: {aggregated_result.overall_score:.1f}, "
            f"Weighted ({paper_type}): {aggregated_result.weighted_score:.1f}. "
            f"Tokens: {total_input_tokens + total_output_tokens} "
            f"(in: {total_input_tokens}, out: {total_output_tokens})"
        )

        # Store result as NodeArtifact
        await async_ops.create_node_artifact(node, "result", aggregated_result)
        
        # Store individual criterion analyses as artifact
        await async_ops.create_node_artifact(
            node,
            "criterion_analyses",
            [c.model_dump() for c in criterion_analyses]
        )

        # Update node status
        await async_ops.update_node_status(
            node,
            "completed",
            completed_at=timezone.now(),
            output_summary=f"Reproducibility: {aggregated_result.weighted_score:.1f}/100 ({paper_type} paper). {aggregated_result.summary}",
        )

        return {"reproducibility_checklist_result": aggregated_result}

    except Exception as e:
        logger.error(f"Error in reproducibility checklist: {e}", exc_info=True)
        await async_ops.create_node_log(node, "ERROR", f"Failed: {str(e)}")
        await async_ops.update_node_status(
            node, "failed", completed_at=timezone.now()
        )
        raise


async def _retrieve_sections_for_criterion(
    paper_id: int,
    criterion_embedding: List[float],
    top_k: int = 3,
    max_chars_per_section: int = 1500,
    min_similarity: float = 0.15
) -> List[Tuple[float, str, str]]:
    """
    Retrieve most relevant paper sections for a criterion using cosine similarity.
    
    Args:
        paper_id: Paper ID
        criterion_embedding: Criterion embedding vector
        top_k: Number of sections to retrieve
        max_chars_per_section: Max characters per section
        min_similarity: Minimum similarity threshold
        
    Returns:
        List of (similarity, section_type, text) tuples sorted by similarity descending
    """
    # Get all section embeddings for this paper
    sections = await sync_to_async(
        lambda: list(PaperSectionEmbedding.objects.filter(paper_id=paper_id))
    )()
    
    if not sections:
        logger.warning(f"No section embeddings found for paper {paper_id}")
        return []
    
    # Compute cosine similarity for each section
    similarities = []
    for section in sections:
        similarity = _compute_cosine_similarity(criterion_embedding, section.embedding)
        if similarity >= min_similarity:
            similarities.append((similarity, section))
    
    # Sort by similarity descending
    similarities.sort(key=lambda x: x[0], reverse=True)
    
    # Take top_k sections
    top_sections = similarities[:top_k]
    
    # Format results with text truncation
    results = []
    for similarity, section in top_sections:
        text = section.section_text[:max_chars_per_section]
        if len(section.section_text) > max_chars_per_section:
            text += "... [truncated]"
        results.append((similarity, section.section_type, text))
    
    return results


def _compute_cosine_similarity(embedding1: List[float], embedding2: List[float]) -> float:
    """Compute cosine similarity between two embeddings."""
    if len(embedding1) != len(embedding2):
        raise ValueError(f"Embedding dimensions must match: {len(embedding1)} vs {len(embedding2)}")
    
    a = np.array(embedding1)
    b = np.array(embedding2)
    
    dot_product = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    
    if norm_a == 0 or norm_b == 0:
        return 0.0
    
    return float(dot_product / (norm_a * norm_b))


def _generate_programmatic_assessment(
    criterion_analyses: List[SingleCriterionAnalysis],
    models_score: float,
    datasets_score: float,
    experiments_score: float,
    overall_score: float,
    weighted_score: float,
    paper_type: str,
    paper_title: str
) -> tuple[str, List[str], List[str], List[str]]:
    """
    Generate summary, strengths, weaknesses, and recommendations programmatically.
    
    This function generates all qualitative text deterministically from structured
    criterion analyses without any LLM calls.
    
    Returns:
        (summary, strengths, weaknesses, recommendations)
    """
    # Group analyses by category and result
    by_category = {"models": [], "datasets": [], "experiments": []}
    present_criteria = []
    absent_criteria = []
    critical_gaps = []
    
    for analysis in criterion_analyses:
        if analysis.category in by_category:
            by_category[analysis.category].append(analysis)
        
        if analysis.present and analysis.confidence >= 0.6:
            present_criteria.append(analysis)
        elif not analysis.present and analysis.importance == "critical":
            critical_gaps.append(analysis)
        elif not analysis.present:
            absent_criteria.append(analysis)
    
    # Generate summary
    score_interpretation = "excellent" if weighted_score >= 80 else "good" if weighted_score >= 60 else "moderate" if weighted_score >= 40 else "limited"
    
    satisfied_count = len(present_criteria)
    total_count = len(criterion_analyses)
    satisfaction_rate = (satisfied_count / total_count * 100) if total_count > 0 else 0
    
    # Identify strongest and weakest categories
    category_scores_map = {
        "models": models_score,
        "datasets": datasets_score,
        "experiments": experiments_score
    }
    strongest_cat = max(category_scores_map, key=category_scores_map.get)
    weakest_cat = min(category_scores_map, key=category_scores_map.get)
    
    summary = (
        f"This {paper_type} paper demonstrates {score_interpretation} reproducibility "
        f"with a weighted score of {weighted_score:.1f}/100. "
        f"{satisfied_count} of {total_count} MICCAI criteria ({satisfaction_rate:.0f}%) are satisfied. "
        f"The strongest category is {strongest_cat} ({category_scores_map[strongest_cat]:.1f}/100), "
        f"while {weakest_cat} ({category_scores_map[weakest_cat]:.1f}/100) requires improvement. "
    )
    
    if len(critical_gaps) > 0:
        summary += f"{len(critical_gaps)} critical reproducibility criteria are missing."
    else:
        summary += "All critical criteria for this paper type are addressed."
    
    # Extract strengths
    strengths = []
    for analysis in sorted(present_criteria, key=lambda a: a.confidence, reverse=True)[:7]:
        if analysis.evidence_text:
            evidence_preview = analysis.evidence_text[:80] + "..." if len(analysis.evidence_text) > 80 else analysis.evidence_text
            strengths.append(
                f"{analysis.criterion_name}: {evidence_preview}"
            )
        else:
            strengths.append(f"{analysis.criterion_name} is documented")
    
    if len(strengths) == 0:
        strengths.append("Paper includes basic methodological description")
    
    # Extract weaknesses
    weaknesses = []
    
    # Prioritize critical gaps first
    for analysis in critical_gaps[:3]:
        weaknesses.append(
            f"Missing {analysis.criterion_name} (critical for {paper_type} papers)"
        )
    
    # Then add other significant gaps
    for analysis in sorted(absent_criteria, key=lambda a: 0 if a.importance == "important" else 1)[:7-len(weaknesses)]:
        if analysis.notes:
            weaknesses.append(f"{analysis.criterion_name}: {analysis.notes[:80]}")
        else:
            weaknesses.append(f"{analysis.criterion_name} not found")
    
    if len(weaknesses) == 0:
        weaknesses.append("Comprehensive documentation with minor gaps")
    
    # Generate recommendations programmatically
    recommendations = []
    
    # Category-specific recommendations
    if models_score < 50:
        recommendations.append(
            "Provide complete mathematical descriptions of models/algorithms with all hyperparameters and training details"
        )
    
    if datasets_score < 50:
        recommendations.append(
            "Improve dataset documentation: add statistics, splits, availability statements, and ethics approval"
        )
    
    if experiments_score < 50:
        recommendations.append(
            "Enhance experimental rigor: report variance across multiple runs and statistical significance tests"
        )
    
    # Specific recommendations from critical gaps
    for analysis in critical_gaps[:3]:
        recommendations.append(
            f"Add {analysis.criterion_name}"
        )
    
    # Fill with important missing criteria
    for analysis in absent_criteria:
        if analysis.importance == "important" and len(recommendations) < 7:
            recommendations.append(
                f"Consider documenting {analysis.criterion_name}"
            )
    
    # Ensure we always have at least one recommendation
    if len(recommendations) == 0:
        recommendations.append(
            "Continue maintaining comprehensive documentation of methods and experiments"
        )
    
    return summary, strengths[:7], weaknesses[:7], recommendations[:7]


async def _aggregate_criterion_analyses(
    criterion_analyses: List[SingleCriterionAnalysis],
    paper_type: str,
    paper_title: str
) -> AggregatedReproducibilityAnalysis:
    """
    Aggregate individual criterion analyses into final assessment.
    
    Fully programmatic - computes all scores and generates all text deterministically:
    1. Compute category scores from criteria
    2. Generate summary, strengths, weaknesses programmatically
    3. Apply paper-type-specific weighting
    
    Args:
        criterion_analyses: List of individual criterion analyses
        paper_type: Paper type for weighting
        paper_title: Paper title for context
        client: OpenAI client
        model: Model name
        
    Returns:
        AggregatedReproducibilityAnalysis
    """
    # Group analyses by category
    by_category = {"models": [], "datasets": [], "experiments": []}
    for analysis in criterion_analyses:
        if analysis.category in by_category:
            by_category[analysis.category].append(analysis)
    
    # Build summary of analyses for LLM
    analyses_summary = []
    for category, analyses in by_category.items():
        analyses_summary.append(f"\n## {category.upper()} CRITERIA ({len(analyses)} items):")
        for a in analyses:
            present_str = "✓ PRESENT" if a.present else "✗ ABSENT"
            analyses_summary.append(
                f"  [{a.criterion_number}] {a.criterion_name}: {present_str} "
                f"(confidence: {a.confidence:.2f}, importance: {a.importance})"
            )
            if a.evidence_text:
                analyses_summary.append(f"      Evidence: {a.evidence_text[:200]}")
    
    analyses_text = "\n".join(analyses_summary)
    
    # Compute category scores (percentage of criteria present weighted by confidence)
    category_scores = {}
    for category, analyses in by_category.items():
        if len(analyses) == 0:
            category_scores[category] = 0.0
        else:
            # Score each criterion: present (1.0) or absent (0.0), weighted by confidence
            scores = []
            for a in analyses:
                score = 100.0 * a.confidence if a.present else 0.0
                scores.append(score)
            category_scores[category] = round(float(np.mean(scores)), 1)
    
    models_score = category_scores.get("models", 0.0)
    datasets_score = category_scores.get("datasets", 0.0)
    experiments_score = category_scores.get("experiments", 0.0)
    
    # Compute overall score (simple average)
    overall_score = round((models_score + datasets_score + experiments_score) / 3, 1)
    
    # Compute weighted score based on paper type
    weights = CRITERIA_WEIGHTS.get(paper_type, CRITERIA_WEIGHTS["unknown"])
    weighted_score = round(
        models_score * weights["models"] +
        datasets_score * weights["datasets"] +
        experiments_score * weights["experiments"],
        1
    )
    
    # Generate all qualitative text programmatically (no LLM call)
    logger.info("Generating assessment text programmatically (no LLM aggregation call)...")
    
    summary, strengths, weaknesses, recommendations = _generate_programmatic_assessment(
        criterion_analyses=criterion_analyses,
        models_score=models_score,
        datasets_score=datasets_score,
        experiments_score=experiments_score,
        overall_score=overall_score,
        weighted_score=weighted_score,
        paper_type=paper_type,
        paper_title=paper_title
    )
    
    # Build final result with all programmatically computed values
    final_result = AggregatedReproducibilityAnalysis(
        models_score=models_score,
        datasets_score=datasets_score,
        experiments_score=experiments_score,
        overall_score=overall_score,
        weighted_score=weighted_score,
        paper_type_context=paper_type,
        summary=summary,
        strengths=strengths,
        weaknesses=weaknesses,
        recommendations=recommendations
    )
    
    logger.info(f"Programmatic assessment complete: {len(strengths)} strengths, {len(weaknesses)} weaknesses, {len(recommendations)} recommendations")
    
    return final_result
