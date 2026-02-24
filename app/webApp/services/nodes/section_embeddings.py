"""
Node D: Paper Section Embeddings

Computes vector embeddings for paper sections using OpenAI's embedding API.
Stores embeddings in the database for later similarity analysis.
"""

import json
import logging
import re
from typing import Dict, Any, List, Tuple

from django.utils import timezone
from asgiref.sync import sync_to_async
from workflow_engine.services.async_orchestrator import async_ops

from webApp.services.graphs_state import PaperProcessingState

logger = logging.getLogger(__name__)


def extract_paper_sections(paper_text: str) -> List[Tuple[str, str]]:
    """
    This is just a fall back if sections are not already in the database.
    Extract sections from paper text. It uses simple regex patterns to identify common section headers and extract text between them.
    
    Args:
        paper_text: Full paper text
        
    Returns:
        List of tuples (section_type, section_text)
    """
    sections = []
    
    # Common section headers (case-insensitive)
    section_patterns = [
        (r'\n\s*(abstract|ABSTRACT)\s*\n', 'abstract'),
        (r'\n\s*(\d+\.?\s*)?(introduction|INTRODUCTION)\s*\n', 'introduction'),
        (r'\n\s*(\d+\.?\s*)?(related\s+work|RELATED\s+WORK|background|BACKGROUND)\s*\n', 'related_work'),
        (r'\n\s*(\d+\.?\s*)?(method|METHOD|methods|METHODS|methodology|METHODOLOGY|approach|APPROACH)\s*\n', 'methods'),
        (r'\n\s*(\d+\.?\s*)?(experiment|EXPERIMENT|experiments|EXPERIMENTS|evaluation|EVALUATION)\s*\n', 'experiments'),
        (r'\n\s*(\d+\.?\s*)?(result|RESULT|results|RESULTS)\s*\n', 'results'),
        (r'\n\s*(\d+\.?\s*)?(discussion|DISCUSSION)\s*\n', 'discussion'),
        (r'\n\s*(\d+\.?\s*)?(conclusion|CONCLUSION|conclusions|CONCLUSIONS)\s*\n', 'conclusion'),
    ]
    
    # Find all section boundaries
    boundaries = []
    for pattern, section_type in section_patterns:
        for match in re.finditer(pattern, paper_text):
            boundaries.append((match.start(), section_type))
    
    # Sort by position
    boundaries.sort(key=lambda x: x[0])
    
    # Extract text between boundaries
    for i, (start, section_type) in enumerate(boundaries):
        if i < len(boundaries) - 1:
            end = boundaries[i + 1][0]
        else:
            end = len(paper_text)
        
        section_text = paper_text[start:end].strip()
        
        # Clean up: remove section header and limit length
        section_text = re.sub(r'^\s*\d+\.?\s*[A-Z][a-z\s]+\n', '', section_text, flags=re.MULTILINE)
        
        # Only include if substantial (>100 chars) and not too long
        if len(section_text) > 100:
            # Limit to ~8000 chars per section for embedding (text-embedding-3-small can handle 8191 tokens)
            section_text = section_text[:8000]
            sections.append((section_type, section_text))
    
    return sections


async def compute_embedding(client, text: str, model: str = "text-embedding-3-small") -> List[float]:
    """
    Compute embedding for text using OpenAI API.
    
    Args:
        client: OpenAI client
        text: Text to embed
        model: OpenAI embedding model
        
    Returns:
        List of floats representing the embedding
    """
    try:
        # OpenAI embedding API is synchronous, wrap for async
        response = await sync_to_async(
            lambda: client.embeddings.create(
                model=model,
                input=text,
                encoding_format="float"
            )
        )()
        
        embedding = response.data[0].embedding
        return embedding
    
    except Exception as e:
        logger.error(f"Error computing embedding: {e}")
        raise


async def section_embeddings_node(state: PaperProcessingState) -> Dict[str, Any]:
    """
    Node D: Compute and store embeddings for paper sections.
    
    This node:
    1. Extracts sections from paper text
    2. Computes OpenAI embeddings for each section
    3. Stores embeddings in database
    
    Args:
        state: Workflow state containing paper_id, client, model
        
    Returns:
        Updated state with section_embeddings_result
    """
    node_id = "section_embeddings"
    logger.info(
        f"Node D: Starting section embeddings computation for paper {state['paper_id']}"
    )

    # Get workflow node
    node = await async_ops.get_workflow_node(state["workflow_run_id"], node_id)

    # Update node status to running
    await async_ops.update_node_status(node, "running", started_at=timezone.now())
    await async_ops.create_node_log(node, "INFO", "Starting section embeddings computation")

    try:
        # Check for force_reprocess flag
        force_reprocess = state.get("force_reprocess", False)

        # Get paper from database
        paper = await async_ops.get_paper(state["paper_id"])
        
        # Check if paper has sections or text
        has_sections = paper.sections and isinstance(paper.sections, dict) and len(paper.sections) > 0
        has_text = paper.text and len(paper.text.strip()) > 0
        
        if not has_sections and not has_text:
            logger.warning(f"Paper {state['paper_id']} has no sections or text, skipping embeddings")
            await async_ops.create_node_log(
                node, "WARNING", "Paper has no sections or text content, skipping"
            )
            await async_ops.update_node_status(
                node, "completed", completed_at=timezone.now()
            )
            return {"section_embeddings_result": {"sections_processed": 0, "skipped": True}}

        # Check if embeddings already exist
        if not force_reprocess:
            from webApp.models import PaperSectionEmbedding
            
            existing_count = await sync_to_async(
                PaperSectionEmbedding.objects.filter(paper_id=state["paper_id"]).count
            )()
            
            if existing_count > 0:
                logger.info(f"Found {existing_count} existing embeddings")
                await async_ops.create_node_log(
                    node, "INFO", f"Using {existing_count} cached embeddings"
                )
                
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
                return {
                    "section_embeddings_result": {
                        "sections_processed": existing_count,
                        "cached": True
                    }
                }

        # Get sections from database (preferred) or fallback to extraction
        sections = []
        
        if paper.sections and isinstance(paper.sections, dict):
            # Use pre-extracted sections from database
            await async_ops.create_node_log(
                node, "INFO", f"Using {len(paper.sections)} sections from database"
            )
            logger.info(f"Using {len(paper.sections)} sections from Paper.sections field")
            
            # Convert dict to list of tuples
            for section_name, section_text in paper.sections.items():
                if section_text and len(str(section_text).strip()) > 100:
                    # Normalize section name (lowercase, replace spaces with underscores)
                    normalized_name = section_name.lower().replace(' ', '_').replace('-', '_')
                    # Truncate to 50 chars to fit database column limit
                    normalized_name = normalized_name[:50]
                    # Limit to ~8000 chars per section
                    text = str(section_text).strip()[:8000]
                    sections.append((normalized_name, text))
        
        elif paper.text:
            # Fallback: extract sections from full text
            await async_ops.create_node_log(
                node, "INFO", "Sections not in database, extracting from full text"
            )
            logger.warning(f"Paper {state['paper_id']} has no sections field, falling back to extraction")
            sections = extract_paper_sections(paper.text)
        
        if not sections:
            logger.warning(f"No sections available for paper {state['paper_id']}")
            await async_ops.create_node_log(
                node, "WARNING", "No sections available for processing"
            )
            await async_ops.update_node_status(
                node, "completed", completed_at=timezone.now()
            )
            return {"section_embeddings_result": {"sections_processed": 0, "no_sections": True}}

        await async_ops.create_node_log(
            node, "INFO", f"Extracted {len(sections)} sections"
        )

        # Get OpenAI client from state
        client = state["client"]
        embedding_model = "text-embedding-3-small"
        
        # Compute embeddings for each section
        total_tokens = 0
        processed_sections = []
        
        from webApp.models import PaperSectionEmbedding
        
        for section_type, section_text in sections:
            try:
                await async_ops.create_node_log(
                    node, "INFO", f"Computing embedding for {section_type} section"
                )
                
                # Compute embedding
                embedding = await compute_embedding(client, section_text, embedding_model)
                
                # Estimate tokens (rough: ~4 chars per token)
                estimated_tokens = len(section_text) // 4
                total_tokens += estimated_tokens
                
                # Store in database
                await sync_to_async(
                    PaperSectionEmbedding.objects.update_or_create
                )(
                    paper_id=state["paper_id"],
                    section_type=section_type,
                    embedding_model=embedding_model,
                    defaults={
                        'section_text': section_text,
                        'embedding': embedding,
                        'embedding_dimension': len(embedding)
                    }
                )
                
                processed_sections.append(section_type)
                logger.info(f"Stored embedding for {section_type} ({len(embedding)} dimensions)")
                
            except Exception as e:
                logger.error(f"Error processing {section_type} section: {e}")
                await async_ops.create_node_log(
                    node, "ERROR", f"Failed to process {section_type}: {str(e)}"
                )
                # Continue with other sections

        # Create result
        result = {
            "sections_processed": len(processed_sections),
            "section_types": processed_sections,
            "embedding_model": embedding_model,
            "embedding_dimension": 1536,
            "estimated_tokens": total_tokens
        }

        # Store as artifact
        await async_ops.create_node_artifact(node, "result", result)
        await async_ops.create_node_artifact(node, "token_usage", {
            "input_tokens": total_tokens,
            "output_tokens": 0  # Embeddings don't produce output tokens
        })
        
        # Update node token fields in database
        await async_ops.update_node_tokens(
            node,
            input_tokens=total_tokens,
            output_tokens=0,
            was_cached=False
        )

        # Mark node as completed
        await async_ops.update_node_status(
            node, "completed", completed_at=timezone.now()
        )

        logger.info(
            f"Node D: Section embeddings completed. Processed {len(processed_sections)} sections, "
            f"{total_tokens} tokens"
        )
        
        # Immediately mark skipped nodes based on paper type (progressive skipping)
        # This ensures downstream nodes can become 'ready' as soon as dependencies are met
        paper_type_result = state.get("paper_type_result")
        if paper_type_result:
            workflow_run_id = state.get("workflow_run_id")
            if paper_type_result.paper_type == "theoretical":
                # Theoretical papers skip all code and dataset analysis
                skipped_nodes = [
                    "dataset_documentation_check",
                    "code_availability_check",
                    "code_embedding",
                    "code_repository_analysis",
                ]
                for node_id in skipped_nodes:
                    skip_node = await async_ops.get_workflow_node(workflow_run_id, node_id)
                    if skip_node and skip_node.status == "pending":
                        await async_ops.update_node_status(skip_node, "skipped")
                        await async_ops.create_node_log(
                            skip_node, "INFO", "Skipped (theoretical paper - no code/dataset analysis)"
                        )
                        logger.info(f"Marked {node_id} as skipped (theoretical paper)")
            elif paper_type_result.paper_type == "method":
                # Method-only papers skip dataset documentation
                skip_node = await async_ops.get_workflow_node(workflow_run_id, "dataset_documentation_check")
                if skip_node and skip_node.status == "pending":
                    await async_ops.update_node_status(skip_node, "skipped")
                    await async_ops.create_node_log(
                        skip_node, "INFO", "Skipped (method-only paper - no dataset)"
                    )
                    logger.info("Marked dataset_documentation_check as skipped (method-only paper)")

        return {"section_embeddings_result": result}

    except Exception as e:
        logger.exception(f"Error in section embeddings node: {e}")
        await async_ops.create_node_log(node, "ERROR", str(e))
        await async_ops.update_node_status(
            node, "failed", completed_at=timezone.now(), error_message=str(e)
        )
        raise
