import json
import logging

from typing import Dict, Any
from django.utils import timezone
from workflow_engine.services.async_orchestrator import async_ops

from webApp.services.pydantic_schemas import PaperTypeClassification
from webApp.services.graphs_state import PaperProcessingState

logger = logging.getLogger(__name__)


async def paper_type_classification_node(state: PaperProcessingState) -> Dict[str, Any]:
    """
    Node A: Classify paper type (dataset, method, both).

    Uses LLM to analyze paper title, abstract, and text to determine
    the type of contribution. Stores result as NodeArtifact.

    Strategy: For efficiency, we use only title + abstract for initial classification.
    This provides good accuracy while minimizing token usage. Full text is used
    only if abstract is not available.
    """
    node_id = "paper_type_classification"
    logger.info(
        f"Node A: Starting paper type classification for paper {state['paper_id']}"
    )

    # Get workflow node
    node = await async_ops.get_workflow_node(state["workflow_run_id"], node_id)

    # Update node status to running
    await async_ops.update_node_status(node, "running", started_at=timezone.now())
    await async_ops.create_node_log(node, "INFO", "Starting paper type classification")

    try:
        # Check for force_reprocess flag
        force_reprocess = state.get("force_reprocess", False)

        # Check if already classified
        if not force_reprocess:
            previous = await async_ops.check_previous_analysis(
                state["paper_id"], node_id
            )
            if previous:
                logger.info(f"Found previous analysis from {previous['completed_at']}")
                await async_ops.create_node_log(
                    node, "INFO", f"Using cached result from run {previous['run_id']}"
                )

                result = PaperTypeClassification(**previous["result"])
                await async_ops.create_node_artifact(node, "result", result)
                await async_ops.update_node_status(
                    node, "completed", completed_at=timezone.now()
                )

                return {"paper_type_result": result}

        # Get paper from database
        paper = await async_ops.get_paper(state["paper_id"])
        # TODO da fixare per avere tutto il paper

        # Use title + abstract for efficiency (or full text if abstract unavailable)
        if paper.abstract:
            paper_content = f"Title: {paper.title}\n\nAbstract: {paper.abstract}"
        elif paper.text:
            # Use first 3000 characters of full text if no abstract
            paper_content = (
                f"Title: {paper.title}\n\nText excerpt:\n{paper.text[:3000]}"
            )
        else:
            paper_content = (
                f"Title: {paper.title}\n\n(No abstract or full text available)"
            )

        # Construct LLM prompt
        system_prompt = """You are an expert scientific paper analyzer specializing in identifying paper contributions.

Your task is to classify papers into one of these categories:
1. "dataset" - Papers primarily presenting a new dataset
2. "method" - Papers presenting a new method, model, algorithm, methodology, or benchmark
3. "both" - Papers presenting both a new dataset AND a new method
4. "theoretical" - Papers with purely theoretical contributions (proofs, mathematical frameworks, surveys, position papers) where executable code is not expected
5. "unknown" - Cannot determine from available information

Guidelines:
- Focus on the PRIMARY contribution of the paper
- A paper introducing a dataset to support a new method should be classified as "both"
- A paper using existing datasets to present a new method is "method"
- A paper collecting and presenting a dataset without a novel method is "dataset"
- Classify as "theoretical" only if: mathematical proofs, theoretical analysis, survey/review, or position papers with NO empirical experiments or implementations
- Papers with empirical validation (even simple experiments) should be "method", not "theoretical"
- Be confident in your assessment - use "unknown" sparingly

Provide:
1. Classification (dataset/method/both/theoretical/unknown)
2. Confidence score (0.0 to 1.0)
3. Clear reasoning
4. Key evidence quotes from the paper"""

        user_content = f"Classify this paper:\n\n{paper_content}"

        # Log the analysis attempt
        await async_ops.create_node_log(
            node,
            "INFO",
            f'Analyzing paper with {state["model"]}',
            {
                "paper_id": state["paper_id"],
                "has_abstract": bool(paper.abstract),
                "content_length": len(paper_content),
            },
        )

        # Call OpenAI API
        response = state["client"].chat.completions.create(
            model=state["model"],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "paper_type_classification",
                    "strict": True,
                    "schema": PaperTypeClassification.model_json_schema(),
                },
            },
            temperature=0.3,
        )

        # Parse response
        result_dict = json.loads(response.choices[0].message.content)
        result = PaperTypeClassification(**result_dict)

        # Track tokens
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens

        logger.info(
            f"Classification result: {result.paper_type} (confidence: {result.confidence})"
        )
        logger.info(f"Reasoning: {result.reasoning}")

        # Store result as artifact
        await async_ops.create_node_artifact(node, "result", result)
        await async_ops.create_node_artifact(
            node,
            "token_usage",
            {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        )

        # Log success
        await async_ops.create_node_log(
            node,
            "INFO",
            f"Classification successful: {result.paper_type}",
            {
                "confidence": result.confidence,
                "tokens_used": input_tokens + output_tokens,
            },
        )

        # Update node status
        await async_ops.update_node_status(
            node,
            "completed",
            completed_at=timezone.now(),
            output_data={
                "paper_type": result.paper_type,
                "confidence": result.confidence,
            },
        )

        return {"paper_type_result": result}

    except Exception as e:
        logger.error(f"Error in paper type classification: {e}", exc_info=True)

        # Log error
        await async_ops.create_node_log(
            node, "ERROR", str(e), {"traceback": str(e.__traceback__)}
        )

        # Update node status to failed
        await async_ops.update_node_status(
            node, "failed", completed_at=timezone.now(), error_message=str(e)
        )

        return {"errors": state.get("errors", []) + [f"Node A error: {str(e)}"]}
