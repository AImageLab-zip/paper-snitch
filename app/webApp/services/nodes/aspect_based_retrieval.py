"""
Aspect-based Embedding Retrieval for Reproducibility Analysis

Provides functions to:
1. Initialize/get aspect embeddings
2. Retrieve relevant sections and code based on similarity to aspects
3. Perform aspect-focused LLM analysis
"""

import logging
import numpy as np
from typing import List, Dict, Tuple, Any, Optional
from openai import OpenAI
from asgiref.sync import sync_to_async

from workflow_engine.services.async_orchestrator import async_ops
from webApp.models import (
    ReproducibilityAspectEmbedding,
    PaperSectionEmbedding,
    CodeFileEmbedding,
)
from .reproducibility_aspects import get_aspect, get_aspect_ids, REPRODUCIBILITY_ASPECTS
from .shared_helpers import retrieve_sections_by_embedding

logger = logging.getLogger(__name__)


# Configuration for aspect-based retrieval
ASPECT_RETRIEVAL_CONFIG = {
    "max_context_tokens": 20000,  # Total token budget per aspect
    "min_similarity_threshold": 0.2,  # Minimum similarity to include content (lowered to capture more sections)
    "section_budget_ratio": 0.4,  # 40% of budget for sections (8K tokens)
    "code_budget_ratio": 0.6,  # 60% of budget for code (12K tokens)
}


def estimate_tokens(text: str) -> int:
    """
    Estimate token count from text length.
    Rough approximation: 1 token ≈ 4 characters.
    """
    return len(text) // 4


async def get_or_create_aspect_embedding(
    aspect_id: str,
    client: OpenAI,
    model: str = "text-embedding-3-small"
) -> ReproducibilityAspectEmbedding:
    """
    Get existing aspect embedding or create if it doesn't exist.
    
    Args:
        aspect_id: ID of the aspect (methodology, structure, etc.)
        client: OpenAI client
        model: Embedding model to use
        
    Returns:
        ReproducibilityAspectEmbedding instance
    """
    # Try to get existing
    try:
        aspect_emb = await sync_to_async(
            ReproducibilityAspectEmbedding.objects.get
        )(aspect_id=aspect_id, embedding_model=model)
        logger.info(f"Using existing embedding for aspect: {aspect_id}")
        return aspect_emb
    except ReproducibilityAspectEmbedding.DoesNotExist:
        pass
    
    # Create new embedding
    aspect_def = get_aspect(aspect_id)
    
    # Combine description and prompt template as context TODO: investigate this; what is analysis_prompt_template
    context_text = f"{aspect_def.aspect_name}\n\n{aspect_def.aspect_description}\n\nAnalysis Focus:\n{aspect_def.analysis_prompt_template[:500]}"
    
    logger.info(f"Creating new embedding for aspect: {aspect_id}")
    
    # Generate embedding
    response = client.embeddings.create(
        model=model,
        input=context_text
    )
    
    embedding_vector = response.data[0].embedding
    dimension = len(embedding_vector)
    
    # Save to database
    aspect_emb = await sync_to_async(
        ReproducibilityAspectEmbedding.objects.create
    )(
        aspect_id=aspect_id,
        aspect_name=aspect_def.aspect_name,
        aspect_description=aspect_def.aspect_description,
        aspect_context=context_text,
        embedding=embedding_vector,
        embedding_model=model,
        embedding_dimension=dimension
    )
    
    logger.info(f"Created new aspect embedding: {aspect_id} ({dimension}D)")
    return aspect_emb


async def retrieve_relevant_sections(
    paper_id: int,
    aspect_embedding: ReproducibilityAspectEmbedding,
    token_budget: int,
    min_similarity: float = None
) -> List[Tuple[PaperSectionEmbedding, float]]:
    """
    Retrieve most relevant paper sections for a given aspect using token budget.
    
    Args:
        paper_id: Paper ID
        aspect_embedding: Aspect embedding to compare against
        token_budget: Maximum tokens to retrieve
        min_similarity: Minimum similarity threshold (uses config default if None)
        
    Returns:
        List of (section, similarity_score) tuples, sorted by similarity (descending)
    """
    if min_similarity is None:
        min_similarity = ASPECT_RETRIEVAL_CONFIG["min_similarity_threshold"]
    
    logger.info(
        f"retrieve_relevant_sections called: aspect={aspect_embedding.aspect_id}, "
        f"paper_id={paper_id}, token_budget={token_budget:,}, min_similarity={min_similarity}"
    )
    
    # Use shared low-level function with token budget
    results = await retrieve_sections_by_embedding(
        paper=paper_id,
        query_embedding=aspect_embedding.embedding,
        min_similarity=min_similarity,
        token_budget=token_budget
    )
    
    if not results:
        logger.warning(f"No section embeddings found for paper {paper_id}")
        return []
    
    # Log similarity statistics
    all_similarities = [similarity for _, similarity, _ in results]
    if all_similarities:
        max_sim = max(all_similarities)
        min_sim = min(all_similarities)
        avg_sim = np.mean(all_similarities)
        logger.debug(
            f"Aspect {aspect_embedding.aspect_id}: Similarity range: "
            f"min={min_sim:.3f}, max={max_sim:.3f}, avg={avg_sim:.3f}"
        )
    
    # Convert to expected format (section, similarity)
    section_similarities = [(section, similarity) for section, similarity, _ in results]
    
    logger.info(
        f"Retrieved {len(section_similarities)} sections for aspect {aspect_embedding.aspect_id} "
        f"(avg similarity: {np.mean([s[1] for s in section_similarities]):.3f})"
    )
    
    return section_similarities


async def retrieve_relevant_code(
    paper_id: int,
    code_url: str,
    aspect_embedding: ReproducibilityAspectEmbedding,
    token_budget: int,
    min_similarity: float = None
) -> List[Tuple[CodeFileEmbedding, float]]:
    """
    Retrieve most relevant code files for a given aspect using token budget.
    
    Args:
        paper_id: Paper ID
        code_url: Repository URL
        aspect_embedding: Aspect embedding to compare against
        token_budget: Maximum tokens to retrieve
        min_similarity: Minimum similarity threshold (uses config default if None)
        
    Returns:
        List of (code_file, similarity_score) tuples, sorted by similarity (descending)
    """
    if min_similarity is None:
        min_similarity = ASPECT_RETRIEVAL_CONFIG["min_similarity_threshold"]
    
    logger.info(
        f"retrieve_relevant_code called: aspect={aspect_embedding.aspect_id}, "
        f"paper_id={paper_id}, code_url={code_url}, token_budget={token_budget:,}, min_similarity={min_similarity}"
    )
    
    # Get all code embeddings for this paper and repo
    code_files = await sync_to_async(list)(
        CodeFileEmbedding.objects.filter(
            paper_id=paper_id,
            code_url=code_url,
            embedding_model=aspect_embedding.embedding_model
        )
    )
    
    if not code_files:
        logger.warning(f"No code embeddings found for paper {paper_id}, repo {code_url}")
        return []
    
    logger.info(f"Found {len(code_files)} code embeddings for paper {paper_id}, repo {code_url}")
    
    # Compute similarities using model method
    code_similarities = []
    all_code_similarities = []  # Track all similarities for debugging
    for code_file in code_files:
        similarity = code_file.compute_cosine_similarity(
            aspect_embedding.embedding
        )
        all_code_similarities.append((code_file.file_path, similarity))
        if similarity >= min_similarity:
            code_similarities.append((code_file, similarity))
    
    # Log all similarity scores for debugging
    if all_code_similarities:
        max_sim = max(s[1] for s in all_code_similarities)
        min_sim = min(s[1] for s in all_code_similarities)
        avg_sim = sum(s[1] for s in all_code_similarities) / len(all_code_similarities)
        logger.debug(
            f"Aspect {aspect_embedding.aspect_id}: Code similarity range: "
            f"min={min_sim:.3f}, max={max_sim:.3f}, avg={avg_sim:.3f}"
        )
    
    # Sort by similarity (descending)
    code_similarities.sort(key=lambda x: x[1], reverse=True)
    
    logger.info(
        f"Aspect {aspect_embedding.aspect_id}: {len(code_similarities)}/{len(code_files)} code files "
        f"passed similarity threshold {min_similarity}"
    )
    if code_similarities:
        top_similarity = code_similarities[0][1] if code_similarities else 0
        logger.debug(f"Top code similarity: {top_similarity:.3f}")
    
    # Fill until token budget exhausted
    selected_code = []
    tokens_used = 0
    
    for code_file, similarity in code_similarities:
        code_tokens = estimate_tokens(code_file.file_content)
        
        if tokens_used + code_tokens <= token_budget:
            selected_code.append((code_file, similarity))
            tokens_used += code_tokens
        else:
            # Budget exhausted
            break
    
    if selected_code:
        avg_similarity = np.mean([s[1] for s in selected_code])
        logger.info(
            f"Retrieved {len(selected_code)} code files for aspect {aspect_embedding.aspect_id} "
            f"({tokens_used:,} tokens, avg similarity: {avg_similarity:.3f})"
        )
    else:
        logger.warning(
            f"No code files met similarity threshold {min_similarity} for aspect {aspect_embedding.aspect_id}"
        )
    
    logger.debug(
        f"Aspect {aspect_embedding.aspect_id}: Total code files above threshold: {len(code_similarities)}, "
        f"selected within budget: {len(selected_code)}"
    )
    
    return selected_code


async def analyze_aspect(
    aspect_id: str,
    paper_id: int,
    code_url: str,
    client: OpenAI,
    model: str = None,
    node: "WorkflowNode" = None,
    max_context_tokens: int = None,
    section_budget_ratio: float = None,
    code_budget_ratio: float = None
) -> Dict[str, Any]:
    """
    Perform focused analysis for a single aspect using retrieved sections/code.
    
    Args:
        aspect_id: ID of aspect to analyze
        paper_id: Paper ID
        code_url: Repository URL
        client: OpenAI client
        model: LLM model to use
        node: Optional workflow node for logging
        max_context_tokens: Maximum total tokens (uses config default if None)
        section_budget_ratio: Ratio of budget for sections (uses config default if None)
        code_budget_ratio: Ratio of budget for code (uses config default if None)
        
    Returns:
        Dict with aspect analysis results and token usage
    """
    # Use config defaults if not specified
    if max_context_tokens is None:
        max_context_tokens = ASPECT_RETRIEVAL_CONFIG["max_context_tokens"]
    if section_budget_ratio is None:
        section_budget_ratio = ASPECT_RETRIEVAL_CONFIG["section_budget_ratio"]
    if code_budget_ratio is None:
        code_budget_ratio = ASPECT_RETRIEVAL_CONFIG["code_budget_ratio"]
    
    # Calculate token budgets
    section_budget = int(max_context_tokens * section_budget_ratio)
    code_budget = int(max_context_tokens * code_budget_ratio)
    
    logger.info(f"Analyzing aspect: {aspect_id} (section budget: {section_budget:,}, code budget: {code_budget:,})")
    if node:
        await async_ops.create_node_log(
            node, "INFO", 
            f"Analyzing aspect: {aspect_id} (section budget: {section_budget:,}, code budget: {code_budget:,})"
        )
    
    # Get aspect definition
    aspect_def = get_aspect(aspect_id)
    
    # Get or create aspect embedding
    aspect_emb = await get_or_create_aspect_embedding(aspect_id, client)
    
    # Retrieve relevant sections with token budget
    relevant_sections = await retrieve_relevant_sections(
        paper_id, aspect_emb, token_budget=section_budget
    )
    
    logger.info(f"Aspect {aspect_id}: Retrieved {len(relevant_sections)} sections")
    if node:
        await async_ops.create_node_log(
            node, "INFO",
            f"Aspect {aspect_id}: Retrieved {len(relevant_sections)} sections"
        )
    
    if relevant_sections:
        section_details = "\n".join([
            f"  - {section.section_type}: {len(section.section_text)} chars (similarity: {score:.3f})"
            for section, score in relevant_sections[:5]  # Show first 5
        ])
        logger.info(f"Aspect {aspect_id}: Top sections:\n{section_details}")
        if node:
            await async_ops.create_node_log(
                node, "DEBUG",
                f"Top sections:\n{section_details}"
            )
    else:
        logger.warning(f"Aspect {aspect_id}: No sections retrieved!")
        if node:
            await async_ops.create_node_log(
                node, "WARNING",
                "No sections retrieved - analysis may be incomplete"
            )
    
    # Retrieve relevant code with token budget
    relevant_code = await retrieve_relevant_code(
        paper_id, code_url, aspect_emb, token_budget=code_budget
    )
    
    logger.info(f"Aspect {aspect_id}: Retrieved {len(relevant_code)} code files")
    if node:
        await async_ops.create_node_log(
            node, "INFO",
            f"Aspect {aspect_id}: Retrieved {len(relevant_code)} code files"
        )
    
    if relevant_code:
        code_details = "\n".join([
            f"  - {code.file_path}: {len(code.file_content)} chars (similarity: {score:.3f})"
            for code, score in relevant_code[:5]  # Show first 5
        ])
        logger.info(f"Aspect {aspect_id}: Top code files:\n{code_details}")
        if node:
            await async_ops.create_node_log(
                node, "DEBUG",
                f"Top code files:\n{code_details}"
            )
    else:
        logger.warning(f"Aspect {aspect_id}: No code files retrieved!")
        if node:
            await async_ops.create_node_log(
                node, "WARNING",
                "No code files retrieved - analysis may be incomplete"
            )
    
    # Build context from retrieved sections
    sections_text = "\n\n".join([
        f"[{section.section_type.upper()} - similarity: {score:.3f}]\n{section.section_text}"
        for section, score in relevant_sections
    ]) if relevant_sections else "No relevant sections found"
    
    # Build context from retrieved code
    code_text = "\n\n".join([
        f"[{code.file_path} - similarity: {score:.3f}]\n{code.file_content}"
        for code, score in relevant_code
    ]) if relevant_code else "No relevant code found"
    
    # Log context sizes
    sections_chars = len(sections_text)
    code_chars = len(code_text)
    logger.info(
        f"Aspect {aspect_id}: Built context - sections: {sections_chars:,} chars, code: {code_chars:,} chars"
    )
    if node:
        await async_ops.create_node_log(
            node, "INFO",
            f"Context built - sections: {sections_chars:,} chars, code: {code_chars:,} chars"
        )
    
    # Format prompt
    prompt = aspect_def.analysis_prompt_template.format(
        sections_text=sections_text,
        code_text=code_text
    )
    
    # Estimate actual prompt tokens
    prompt_tokens = estimate_tokens(prompt)
    
    logger.info(f"Aspect {aspect_id}: Prompt length: {len(prompt):,} chars (~{prompt_tokens:,} tokens)")
    if node:
        await async_ops.create_node_log(
            node, "DEBUG",
            f"Prompt length: {len(prompt):,} chars (~{prompt_tokens:,} tokens)"
        )
    
    # Log preview of what's being sent to LLM
    sections_preview = sections_text[:200] + "..." if len(sections_text) > 200 else sections_text
    code_preview = code_text[:200] + "..." if len(code_text) > 200 else code_text
    logger.debug(
        f"Aspect {aspect_id}: Sections preview: {sections_preview}\n"
        f"Code preview: {code_preview}"
    )
    
    # Call LLM
    logger.info(f"Calling LLM for aspect {aspect_id} (estimated prompt: {prompt_tokens:,} tokens)...")
    if node:
        await async_ops.create_node_log(
            node, "INFO", 
            f"Calling LLM for aspect {aspect_id}: {len(relevant_sections)} sections, "
            f"{len(relevant_code)} code files (~{prompt_tokens:,} tokens)"
        )
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You are an expert code reproducibility analyst. Provide detailed, evidence-based analysis in JSON format."
            },
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=1500
    )
    
    analysis_json = response.choices[0].message.content
    input_tokens = response.usage.prompt_tokens
    output_tokens = response.usage.completion_tokens
    
    logger.info(f"Aspect {aspect_id} analysis complete (actual: {input_tokens:,} input, {output_tokens:,} output tokens)")
    if node:
        await async_ops.create_node_log(
            node, "INFO", f"Aspect {aspect_id} analysis complete ({input_tokens:,} input, {output_tokens:,} output tokens)"
        )
    
    return {
        "aspect_id": aspect_id,
        "analysis": analysis_json,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "sections_used": len(relevant_sections),
        "code_files_used": len(relevant_code)
    }
