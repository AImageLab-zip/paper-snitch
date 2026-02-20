"""
Aspect-Based Repository Analysis (Version 2)

Refactored version of analyze_repository_comprehensive that uses:
1. Aspect embeddings for targeted retrieval
2. Section embeddings and code embeddings from previous nodes
3. Per-aspect LLM calls with focused context
4. Final aggregation call for overall assessment
"""

import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from openai import OpenAI
from asgiref.sync import sync_to_async
from workflow_engine.services.async_orchestrator import async_ops
from webApp.models import Paper

from .aspect_based_retrieval import analyze_aspect, get_aspect_ids
from .reproducibility_aspects import get_aspect
from .shared_helpers import (
    compute_reproducibility_score,
    ResearchMethodologyAnalysis,
    RepositoryStructureAnalysis,
    CodeAvailabilityAnalysis,
    ArtifactsAnalysis,
    DatasetSplitsAnalysis,
    ReproducibilityDocumentation,
)

logger = logging.getLogger(__name__)


async def analyze_repository_with_aspects(
    code_url: str,
    paper: Paper,
    client: OpenAI,
    model: str,
    node: "WorkflowNode" = None,
) -> Dict[str, Any]:
    """
    Perform comprehensive analysis using aspect-based retrieval.
    
    This function:
    1. Verifies section and code embeddings exist (from Nodes D and F)
    2. For each aspect (0-5):
       - Retrieves relevant sections/code from database via similarity
       - Performs focused LLM analysis
    3. Aggregates results into final assessment
    4. Build structured data and compute reproducibility score
    
    All code and section data comes from database embeddings created by previous nodes.
    No repository re-fetching is needed.
    
    Parameters
    ----------
    code_url : str
        Repository URL
    paper : Paper
        Paper object
    client : OpenAI
        OpenAI client
    model : str
        LLM model name
    node : WorkflowNode
        Optional node for detailed logging
        
    Returns
    -------
    Dict[str, Any]
        Complete analysis results with all aspects
    """
    logger.info(f"Starting aspect-based repository analysis for {paper.title}")
    
    if node:
        await async_ops.create_node_log(
            node, "INFO", "Starting aspect-based repository analysis"
        )
    
    total_input_tokens = 0
    total_output_tokens = 0
    aspect_results = {}
    
    try:
        # Step 1: Verify embeddings exist
        logger.info("Verifying section and code embeddings...")
        if node:
            await async_ops.create_node_log(
                node, "INFO", "Verifying section and code embeddings exist"
            )
        
        # Check section embeddings
        from webApp.models import PaperSectionEmbedding
        section_count = await sync_to_async(
            PaperSectionEmbedding.objects.filter(paper_id=paper.id).count
        )()
        
        if section_count == 0:
            logger.warning(f"No section embeddings found for paper {paper.id}")
            if node:
                await async_ops.create_node_log(
                    node, "WARNING", "No section embeddings found - analysis may be incomplete"
                )
        else:
            logger.info(f"Found {section_count} section embeddings")
            if node:
                await async_ops.create_node_log(
                    node, "INFO", f"Found {section_count} section embeddings"
                )
        
        # Check code embeddings
        from webApp.models import CodeFileEmbedding
        code_count = await sync_to_async(
            CodeFileEmbedding.objects.filter(paper_id=paper.id, code_url=code_url).count
        )()
        
        if code_count == 0:
            logger.warning(f"No code embeddings found for paper {paper.id}")
            if node:
                await async_ops.create_node_log(
                    node, "WARNING", "No code embeddings found - will analyze from repo tree"
                )
        else:
            logger.info(f"Found {code_count} code file embeddings")
            if node:
                await async_ops.create_node_log(
                    node, "INFO", f"Found {code_count} code file embeddings"
                )
        
        # Step 2: Analyze each aspect (0-5)
        aspect_ids = get_aspect_ids()[:-1]  # Exclude 'overall' for now
        
        for aspect_id in aspect_ids:
            logger.info(f"Analyzing aspect: {aspect_id}")
            if node:
                await async_ops.create_node_log(
                    node, "INFO", f"Analyzing aspect: {aspect_id}"
                )
            
            try:
                aspect_result = await analyze_aspect(
                    aspect_id=aspect_id,
                    paper_id=paper.id,
                    code_url=code_url,
                    client=client,
                    model=model,
                    node=node
                )
                
                aspect_results[aspect_id] = json.loads(aspect_result["analysis"])
                total_input_tokens += aspect_result["input_tokens"]
                total_output_tokens += aspect_result["output_tokens"]
                
                logger.info(
                    f"Aspect {aspect_id} complete - "
                    f"used {aspect_result['sections_used']} sections, "
                    f"{aspect_result['code_files_used']} code files"
                )
                
            except Exception as e:
                logger.error(f"Error analyzing aspect {aspect_id}: {e}", exc_info=True)
                if node:
                    await async_ops.create_node_log(
                        node, "ERROR", f"Error analyzing aspect {aspect_id}: {e}"
                    )
                # Store error but continue with other aspects
                aspect_results[aspect_id] = {"error": str(e)}
        
        # Step 3: Aggregate results for overall assessment
        logger.info("Generating overall assessment from aspect analyses")
        if node:
            await async_ops.create_node_log(
                node, "INFO", "Generating overall assessment"
            )
        
        # Format aspect analyses for aggregation
        aspect_summaries = []
        for aspect_id, result in aspect_results.items():
            aspect_def = get_aspect(aspect_id)
            aspect_summaries.append(
                f"**{aspect_def.aspect_name}**:\n{json.dumps(result, indent=2)}"
            )
        
        overall_prompt = f"""Based on the following aspect analyses, provide an overall reproducibility assessment:

{chr(10).join(aspect_summaries)}

Generate a JSON with:
- overall_assessment: string (comprehensive summary of reproducibility status, key strengths, and critical weaknesses)
"""
        
        overall_response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert at synthesizing reproducibility analyses into clear assessments."
                },
                {"role": "user", "content": overall_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=1000
        )
        
        overall_result = json.loads(overall_response.choices[0].message.content)
        total_input_tokens += overall_response.usage.prompt_tokens
        total_output_tokens += overall_response.usage.completion_tokens
        
        logger.info(f"Overall assessment complete")
        if node:
            await async_ops.create_node_log(node, "INFO", "Overall assessment complete")
        
        # Step 4: Build structured data from aspect results
        structured_data = {
            "methodology": aspect_results.get("methodology", {}),
            "structure": aspect_results.get("structure", {}),
            "components": aspect_results.get("components", {}),
            "artifacts": aspect_results.get("artifacts", {}),
            "dataset_splits": aspect_results.get("dataset_splits", {}),
            "documentation": aspect_results.get("documentation", {}),
            "overall_assessment": overall_result.get("overall_assessment", "")
        }
        
        # Step 5: Create Pydantic models for structured data
        def safe_model_create(model_class, data):
            """Create Pydantic model only if data is not empty."""
            if not data or not isinstance(data, dict):
                logger.warning(f"{model_class.__name__}: No data or invalid type")
                return None

            # Check if has error
            if "error" in data:
                logger.warning(f"{model_class.__name__}: Analysis had error: {data['error']}")
                return None

            # Check if ALL values are None
            all_none = all(v is None for v in data.values())
            if all_none:
                logger.warning(f"{model_class.__name__}: All values are None")
                return None

            try:
                instance = model_class(**data)
                logger.info(f"{model_class.__name__}: Successfully created")
                return instance
            except Exception as e:
                logger.error(f"Failed to create {model_class.__name__}: {e}")
                logger.error(f"  Data was: {data}")
                return None
        
        methodology_obj = safe_model_create(
            ResearchMethodologyAnalysis, structured_data.get("methodology")
        )
        structure_obj = safe_model_create(
            RepositoryStructureAnalysis, structured_data.get("structure")
        )
        components_obj = safe_model_create(
            CodeAvailabilityAnalysis, structured_data.get("components")
        )
        artifacts_obj = safe_model_create(
            ArtifactsAnalysis, structured_data.get("artifacts")
        )
        dataset_splits_obj = safe_model_create(
            DatasetSplitsAnalysis, structured_data.get("dataset_splits")
        )
        documentation_obj = safe_model_create(
            ReproducibilityDocumentation, structured_data.get("documentation")
        )
        
        # Step 6: Compute reproducibility score
        logger.info("Computing reproducibility score...")
        if node:
            await async_ops.create_node_log(node, "INFO", "Computing reproducibility score")
        
        score, breakdown, recommendations = compute_reproducibility_score(
            methodology_obj,
            structure_obj,
            components_obj,
            artifacts_obj,
            dataset_splits_obj,
            documentation_obj,
        )
        
        logger.info(f"Computed reproducibility score: {score}/10")
        logger.info(f"Score breakdown: {breakdown}")
        
        if node:
            breakdown_text = "\n".join(f"  • {k}: {v}/10" for k, v in breakdown.items())
            await async_ops.create_node_log(
                node,
                "INFO",
                f"Reproducibility score: {score}/10\n\nBreakdown:\n{breakdown_text}",
            )
            
            if recommendations:
                rec_preview = "\n".join(f"  • {r}" for r in recommendations[:3])
                await async_ops.create_node_log(
                    node,
                    "INFO",
                    f'Top recommendations:\n{rec_preview}{"\n  ..." if len(recommendations) > 3 else ""}',
                )
        
        # Step 7: Compile final result
        result = {
            "methodology": methodology_obj,
            "structure": structure_obj,
            "components": components_obj,
            "artifacts": artifacts_obj,
            "dataset_splits": dataset_splits_obj,
            "documentation": documentation_obj,
            "reproducibility_score": score,
            "score_breakdown": breakdown,
            "overall_assessment": structured_data.get("overall_assessment", "Analysis completed"),
            "recommendations": recommendations,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "llm_analysis_text": json.dumps(aspect_results, indent=2),  # Store all aspect analyses
            "structured_data": structured_data,
        }
        
        logger.info(
            f"Aspect-based repository analysis complete - {len(aspect_results)} aspects analyzed"
        )
        return result
        
    except Exception as e:
        logger.error(f"Error in aspect-based repository analysis: {e}", exc_info=True)
        if node:
            await async_ops.create_node_log(
                node,
                "ERROR",
                f"Error in aspect-based repository analysis: {e}",
            )
        
        # Return minimal analysis on error
        return {
            "methodology": None,
            "structure": None,
            "components": None,
            "artifacts": None,
            "dataset_splits": None,
            "documentation": None,
            "reproducibility_score": 0.0,
            "score_breakdown": {},
            "overall_assessment": f"Analysis failed: {str(e)}",
            "recommendations": ["Manual review required due to analysis error"],
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
        }
