"""
Node E: Dataset Documentation Check (Multi-Step Process)

Evaluates 10 dataset documentation criteria for dataset/both papers.
Uses multi-step process similar to Node G:
1. Load criteria from database with embeddings
2. For each criterion: retrieve relevant sections → LLM analysis  
3. Aggregate results programmatically (no LLM aggregation)

Categories:
- Data Collection (3 criteria): process, acquisition parameters, study cohort
- Annotation (4 criteria): protocol, annotators, inter-rater agreement, quality control
- Ethics & Availability (3 criteria): IRB approval, availability statement, license
"""

import json
import logging
import re
from typing import Dict, Any, List, Tuple, Optional
import numpy as np

from django.utils import timezone
from asgiref.sync import sync_to_async
from workflow_engine.services.async_orchestrator import async_ops

from webApp.models import DatasetDocumentationCriterion, PaperSectionEmbedding
from webApp.services.pydantic_schemas import (
    SingleDatasetCriterionAnalysis,
    AggregatedDatasetDocumentationAnalysis,
)
from webApp.services.graphs_state import PaperProcessingState

logger = logging.getLogger(__name__)


# Category weights for overall score computation
CATEGORY_WEIGHTS = {
    "data_collection": 0.35,      # Critical for understanding data origins
    "annotation": 0.40,           # Most critical for labeled datasets
    "ethics_availability": 0.25,  # Important for access and ethics
}


async def dataset_documentation_check_node(
    state: PaperProcessingState,
) -> Dict[str, Any]:
    """
    Node E: Multi-step dataset documentation analysis.
    
    Process:
    1. Load 10 criteria from database (with embeddings)
    2. For each criterion:
       - Find most relevant paper sections via cosine similarity
       - Analyze with LLM (SingleDatasetCriterionAnalysis)
    3. Aggregate programmatically (no LLM call)
    4. Compute category scores and overall score
    
    Returns:
        Dict with dataset_documentation_result
    """
    node_id = "dataset_documentation_check"
    logger.info(
        f"Node E: Starting multi-step dataset documentation check for paper {state['paper_id']}"
    )

    # Get workflow node
    node = await async_ops.get_workflow_node(state["workflow_run_id"], node_id)

    # Update node status to running
    await async_ops.update_node_status(node, "running", started_at=timezone.now())
    await async_ops.create_node_log(
        node, "INFO", "Starting multi-step dataset documentation analysis (10 criteria)"
    )

    try:
        # Check paper type - only run for dataset or both papers
        paper_type_result = state.get("paper_type_result")
        if not paper_type_result:
            msg = "Paper type classification not found in state"
            logger.error(msg)
            await async_ops.create_node_log(node, "ERROR", msg)
            await async_ops.update_node_status(
                node, "failed", completed_at=timezone.now()
            )
            return {"error": msg}

        paper_type = paper_type_result.paper_type
        logger.info(f"Paper type: {paper_type}")

        # Skip if not a dataset paper
        if paper_type not in ["dataset", "both"]:
            msg = f"Skipping dataset documentation check for paper type: {paper_type}"
            logger.info(msg)
            await async_ops.create_node_log(node, "INFO", msg)
            await async_ops.update_node_status(
                node, "completed", completed_at=timezone.now()
            )
            return {
                "dataset_documentation_result": None,
                "skipped": True,
                "reason": f"Not applicable for paper type: {paper_type}",
            }

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

                result = AggregatedDatasetDocumentationAnalysis(**previous["result"])

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

                return {"dataset_documentation_result": result}

        # Get paper and client from state
        paper = await async_ops.get_paper(state["paper_id"])
        client = state["client"]
        model = state["model"]

        # Step 1: Load criteria from database
        await async_ops.create_node_log(
            node, "INFO", "Loading 10 dataset documentation criteria from database"
        )
        
        criteria_models = await sync_to_async(
            lambda: list(DatasetDocumentationCriterion.objects.filter(
                embedding_model="text-embedding-3-small"
            ).order_by('criterion_number'))
        )()
        
        if len(criteria_models) != 10:
            error_msg = f"Expected 10 criteria, found {len(criteria_models)}. Run 'python manage.py initialize_dataset_criteria_embeddings'"
            logger.error(error_msg)
            await async_ops.create_node_log(node, "ERROR", error_msg)
            raise ValueError(error_msg)
        
        logger.info(f"Loaded {len(criteria_models)} criteria from database")
        
        # Step 2: Analyze each criterion individually
        criterion_analyses = []
        total_input_tokens = 0
        total_output_tokens = 0
        
        # Extract dataset name/size if available from abstract
        dataset_name = None
        dataset_size = None
        download_link = None
        
        for i, criterion_model in enumerate(criteria_models, 1):
            logger.info(
                f"Analyzing criterion {i}/10: {criterion_model.criterion_name}"
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
            system_prompt = f"""You are evaluating a single dataset documentation criterion for a dataset paper.

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
6. Importance level for dataset papers: 'critical', 'important', or 'optional'"""

            # Call LLM
            try:
                response = client.beta.chat.completions.parse(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format=SingleDatasetCriterionAnalysis,
                    temperature=0.1,
                )
                
                analysis = response.choices[0].message.parsed
                
                # Ensure criterion fields are set correctly
                analysis_dict = analysis.model_dump()
                analysis_dict["criterion_id"] = criterion_model.criterion_id
                analysis_dict["criterion_number"] = criterion_model.criterion_number
                analysis_dict["criterion_name"] = criterion_model.criterion_name
                analysis_dict["category"] = criterion_model.category
                analysis = SingleDatasetCriterionAnalysis(**analysis_dict)
                
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
        
        logger.info(f"Completed individual criterion analyses: {len(criterion_analyses)}/10")
        
        if len(criterion_analyses) == 0:
            error_msg = "No criteria were successfully analyzed"
            logger.error(error_msg)
            await async_ops.create_node_log(node, "ERROR", error_msg)
            raise ValueError(error_msg)
        
        # Step 3: Aggregate results programmatically
        await async_ops.create_node_log(
            node, "INFO", f"Aggregating {len(criterion_analyses)} criterion analyses programmatically"
        )
        
        aggregated_result = await _aggregate_criterion_analyses(
            criterion_analyses=criterion_analyses,
            paper_type=paper_type,
            paper_title=paper.title,
            paper_abstract=paper.abstract
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
            f"Dataset documentation analysis complete. Overall: {aggregated_result.overall_score:.1f}. "
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
            output_summary=f"Dataset documentation: {aggregated_result.overall_score:.1f}/100. {aggregated_result.summary}",
        )

        return {"dataset_documentation_result": aggregated_result}

    except Exception as e:
        logger.error(f"Error in dataset documentation check: {e}", exc_info=True)
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


def _extract_dataset_metadata(
    criterion_analyses: List[SingleDatasetCriterionAnalysis],
    paper_title: str,
    paper_abstract: Optional[str] = None
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Extract optional dataset metadata from criterion analyses.
    
    Extracts:
    1. dataset_name: From title, abstract, or evidence text
    2. dataset_size: Parse patterns like "1000 images", "500 patients", "2TB data"
    3. download_link: Extract URLs from Availability Statement criterion
    
    Args:
        criterion_analyses: List of criterion analyses
        paper_title: Paper title
        paper_abstract: Paper abstract (optional)
        
    Returns:
        (dataset_name, dataset_size, download_link)
    """
    dataset_name = None
    dataset_size = None
    download_link = None
    
    # Pattern to extract dataset names from titles (e.g., "ImageNet", "COCO", "MIMIC-III")
    # Look for capitalized words that might be dataset names
    title_dataset_pattern = r'\b([A-Z][A-Za-z0-9\-]*(?:\s+[A-Z][A-Za-z0-9\-]*)?)\s*(?:dataset|Dataset|corpus|Corpus|benchmark|Benchmark)\b'
    title_match = re.search(title_dataset_pattern, paper_title)
    if title_match:
        dataset_name = title_match.group(1).strip()
    
    # Pattern to extract dataset sizes (e.g., "1000 images", "500 patients", "2.5TB")
    size_patterns = [
        r'(\d+[\.,]?\d*\s*(?:TB|GB|MB|terabyte|gigabyte|megabyte)s?)',  # Storage sizes
        r'(\d+[\.,]?\d*[KMB]?\s+(?:images?|samples?|patients?|subjects?|instances?|examples?|records?))',  # Count-based
        r'(?:contains?|includes?|comprises?)\s+(\d+[\.,]?\d*[KMB]?\s+\w+)',  # Contextual counts
    ]
    
    # Pattern to extract URLs
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    
    # Check Availability Statement criterion (usually criterion #8 in ethics_availability)
    availability_criterion = None
    for analysis in criterion_analyses:
        if 'availability' in analysis.criterion_name.lower():
            availability_criterion = analysis
            break
    
    # Extract download link from Availability Statement
    if availability_criterion and availability_criterion.evidence_text:
        urls = re.findall(url_pattern, availability_criterion.evidence_text)
        if urls:
            # Prefer GitHub, Zenodo, or domain-specific repositories
            priority_domains = ['github.com', 'zenodo.org', 'kaggle.com', 'huggingface.co', 
                               'physionet.org', 'archive.ics.uci.edu']
            for url in urls:
                url_lower = url.lower()
                if any(domain in url_lower for domain in priority_domains):
                    download_link = url
                    break
            if not download_link and urls:
                download_link = urls[0]  # Take first URL if no priority match
    
    # Search all evidence texts for dataset size
    all_evidence = []
    for analysis in criterion_analyses:
        if analysis.evidence_text:
            all_evidence.append(analysis.evidence_text)
    
    combined_evidence = ' '.join(all_evidence)
    
    for pattern in size_patterns:
        matches = re.findall(pattern, combined_evidence, re.IGNORECASE)
        if matches:
            # Take the first substantial match
            for match in matches:
                # Clean up the match
                size_text = match.strip()
                # Validate it looks like a reasonable size
                if re.search(r'\d', size_text):
                    dataset_size = size_text
                    break
            if dataset_size:
                break
    
    # If no dataset name from title, try to extract from evidence
    if not dataset_name:
        # Look for quoted names or capitalized dataset references
        name_patterns = [
            r'["\']([A-Z][A-Za-z0-9\-\s]+(?:dataset|Dataset|corpus|Corpus))["\']',
            r'\b([A-Z][A-Z\-]+)\s+(?:dataset|corpus)\b',  # Acronyms like "MIMIC-III dataset"
        ]
        
        for pattern in name_patterns:
            match = re.search(pattern, combined_evidence)
            if match:
                dataset_name = match.group(1).strip()
                break
    
    logger.debug(f"Extracted metadata: name={dataset_name}, size={dataset_size}, link={download_link}")
    
    return dataset_name, dataset_size, download_link


def _generate_programmatic_assessment(
    criterion_analyses: List[SingleDatasetCriterionAnalysis],
    data_collection_score: float,
    annotation_score: float,
    ethics_availability_score: float,
    overall_score: float,
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
    by_category = {"data_collection": [], "annotation": [], "ethics_availability": []}
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
    score_interpretation = "excellent" if overall_score >= 80 else "good" if overall_score >= 60 else "moderate" if overall_score >= 40 else "limited"
    
    satisfied_count = len(present_criteria)
    total_count = len(criterion_analyses)
    satisfaction_rate = (satisfied_count / total_count * 100) if total_count > 0 else 0
    
    # Identify strongest and weakest categories
    category_scores_map = {
        "data_collection": data_collection_score,
        "annotation": annotation_score,
        "ethics_availability": ethics_availability_score
    }
    strongest_cat = max(category_scores_map, key=category_scores_map.get)
    weakest_cat = min(category_scores_map, key=category_scores_map.get)
    
    summary = (
        f"This {paper_type} paper demonstrates {score_interpretation} dataset documentation "
        f"with an overall score of {overall_score:.1f}/100. "
        f"{satisfied_count} of {total_count} documentation criteria ({satisfaction_rate:.0f}%) are satisfied. "
        f"The strongest category is {strongest_cat.replace('_', ' ')} ({category_scores_map[strongest_cat]:.1f}/100), "
        f"while {weakest_cat.replace('_', ' ')} ({category_scores_map[weakest_cat]:.1f}/100) needs improvement. "
    )
    
    if len(critical_gaps) > 0:
        summary += f"{len(critical_gaps)} critical documentation criteria are missing."
    else:
        summary += "All critical documentation requirements are met."
    
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
        strengths.append("Paper includes basic dataset information")
    
    # Extract weaknesses
    weaknesses = []
    
    # Prioritize critical gaps first
    for analysis in critical_gaps[:3]:
        weaknesses.append(
            f"Missing {analysis.criterion_name} (critical for dataset papers)"
        )
    
    # Then add other significant gaps
    for analysis in sorted(absent_criteria, key=lambda a: 0 if a.importance == "important" else 1)[:7-len(weaknesses)]:
        if analysis.notes:
            weaknesses.append(f"{analysis.criterion_name}: {analysis.notes[:80]}")
        else:
            weaknesses.append(f"{analysis.criterion_name} not documented")
    
    if len(weaknesses) == 0:
        weaknesses.append("Comprehensive documentation with minor gaps")
    
    # Generate recommendations programmatically
    recommendations = []
    
    # Category-specific recommendations
    if data_collection_score < 50:
        recommendations.append(
            "Provide complete data collection documentation: acquisition parameters, study cohort, and collection methodology"
        )
    
    if annotation_score < 50:
        recommendations.append(
            "Improve annotation documentation: add annotation protocol, annotator qualifications, and inter-rater agreement metrics"
        )
    
    if ethics_availability_score < 50:
        recommendations.append(
            "Add ethics approval statement, data availability declaration, and usage license information"
        )
    
    # Specific recommendations from critical gaps
    for analysis in critical_gaps[:3]:
        recommendations.append(
            f"Add {analysis.criterion_name} ..."
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
            "Continue maintaining comprehensive dataset documentation"
        )
    
    return summary, strengths[:7], weaknesses[:7], recommendations[:7]


async def _aggregate_criterion_analyses(
    criterion_analyses: List[SingleDatasetCriterionAnalysis],
    paper_type: str,
    paper_title: str,
    paper_abstract: Optional[str] = None
) -> AggregatedDatasetDocumentationAnalysis:
    """
    Aggregate individual criterion analyses into final assessment.
    
    Fully programmatic - computes all scores and generates all text deterministically:
    1. Compute category scores from criteria
    2. Extract dataset metadata (name, size, download link)
    3. Generate summary, strengths, weaknesses programmatically
    4. Compute overall weighted score
    
    Args:
        criterion_analyses: List of individual criterion analyses
        paper_type: Paper type for context
        paper_title: Paper title for context
        paper_abstract: Paper abstract for metadata extraction
        
    Returns:
        AggregatedDatasetDocumentationAnalysis
    """
    # Group analyses by category
    by_category = {"data_collection": [], "annotation": [], "ethics_availability": []}
    for analysis in criterion_analyses:
        if analysis.category in by_category:
            by_category[analysis.category].append(analysis)
    
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
    
    data_collection_score = category_scores.get("data_collection", 0.0)
    annotation_score = category_scores.get("annotation", 0.0)
    ethics_availability_score = category_scores.get("ethics_availability", 0.0)
    
    # Compute overall weighted score
    overall_score = round(
        data_collection_score * CATEGORY_WEIGHTS["data_collection"] +
        annotation_score * CATEGORY_WEIGHTS["annotation"] +
        ethics_availability_score * CATEGORY_WEIGHTS["ethics_availability"],
        1
    )
    
    # Generate all qualitative text programmatically (no LLM call)
    logger.info("Generating assessment text programmatically (no LLM aggregation call)...")
    
    summary, strengths, weaknesses, recommendations = _generate_programmatic_assessment(
        criterion_analyses=criterion_analyses,
        data_collection_score=data_collection_score,
        annotation_score=annotation_score,
        ethics_availability_score=ethics_availability_score,
        overall_score=overall_score,
        paper_type=paper_type,
        paper_title=paper_title
    )
    
    # Extract dataset metadata from analyses (optional)
    logger.info("Extracting dataset metadata from criterion analyses...")
    dataset_name, dataset_size, download_link = _extract_dataset_metadata(
        criterion_analyses=criterion_analyses,
        paper_title=paper_title,
        paper_abstract=paper_abstract
    )
    
    if dataset_name or dataset_size or download_link:
        logger.info(
            f"Extracted metadata: name={dataset_name}, size={dataset_size}, "
            f"link={'found' if download_link else 'not found'}"
        )
    
    # Build final result with all programmatically computed values
    final_result = AggregatedDatasetDocumentationAnalysis(
        dataset_name=dataset_name,
        dataset_size=dataset_size,
        download_link=download_link,
        data_collection_score=data_collection_score,
        annotation_score=annotation_score,
        ethics_availability_score=ethics_availability_score,
        overall_score=overall_score,
        summary=summary,
        strengths=strengths,
        weaknesses=weaknesses,
        recommendations=recommendations
    )
    
    logger.info(f"Programmatic assessment complete: {len(strengths)} strengths, {len(weaknesses)} weaknesses, {len(recommendations)} recommendations")
    
    return final_result
