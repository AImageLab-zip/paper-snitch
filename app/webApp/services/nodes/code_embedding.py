"""
Node F: Code Repository Embedding

This node performs code repository ingestion and embedding:
1. Clone repository (or reuse from Node B if available)
2. Initial ingestion: Get README + full tree structure
3. LLM call: Determine important file patterns
4. Re-ingest with selected patterns
5. Chunk large files (>20000 chars)
6. Compute embeddings file-by-file using OpenAI text-embedding-3-small
7. Store embeddings in database and as artifacts

Only runs if code is available from Node B.
"""

import logging
import hashlib
from typing import Dict, Any, List, Tuple
from datetime import datetime
from pathlib import Path as PathlibPath

from django.utils import timezone
from asgiref.sync import sync_to_async

from workflow_engine.services.async_orchestrator import async_ops
from .shared_helpers import ingest_with_steroids
from webApp.services.pydantic_schemas import (
    CodeAvailabilityCheck,
    CodeEmbeddingResult,
    CodeFileEmbeddingInfo,
    PatternExtraction,
)
from webApp.services.graphs_state import PaperProcessingState

logger = logging.getLogger(__name__)


def chunk_text(text: str, max_chars: int = 20000) -> List[str]:
    """
    Split text into chunks if it exceeds max_chars.
    
    Args:
        text: Text to chunk
        max_chars: Maximum characters per chunk (default 20000)
        
    Returns:
        List of text chunks
    """
    if len(text) <= max_chars:
        return [text]
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + max_chars
        
        # Try to break at a newline near the end
        if end < len(text):
            # Look for newline in the last 500 chars of the chunk
            newline_pos = text.rfind('\n', end - 500, end)
            if newline_pos != -1:
                end = newline_pos + 1
        
        chunks.append(text[start:end])
        start = end
    
    return chunks


async def compute_embedding(client, text: str, model: str = "text-embedding-3-small") -> Tuple[List[float], int]:
    """
    Compute embedding for text using OpenAI API.
    
    Args:
        client: OpenAI client
        text: Text to embed
        model: OpenAI embedding model
        
    Returns:
        Tuple of (embedding vector, tokens_used)
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
        tokens_used = response.usage.total_tokens
        
        return embedding, tokens_used
    
    except Exception as e:
        logger.error(f"Error computing embedding: {e}")
        raise


async def code_embedding_node(state: PaperProcessingState) -> Dict[str, Any]:
    """
    Node F: Compute and store embeddings for code repository files.
    
    This node:
    1. Clones repository (or reuses from Node B)
    2. Ingests README + tree structure
    3. Uses LLM to select important files
    4. Re-ingests selected files
    5. Chunks large files (>20000 chars)
    6. Computes embeddings for each file/chunk
    7. Stores in database and artifacts
    
    Args:
        state: Workflow state containing paper_id, client, model, code_availability_result
        
    Returns:
        Updated state with code_embedding_result
    """
    node_id = "code_embedding"
    logger.info(
        f"Node F: Starting code embedding for paper {state['paper_id']}"
    )

    # Get workflow node
    node = await async_ops.get_workflow_node(state["workflow_run_id"], node_id)

    # Early exit if node is already marked as skipped (progressive skipping)
    if node.status == "skipped":
        logger.info(f"Node already marked as skipped - exiting early (progressive skipping)")
        # Pass through code_availability_result so downstream nodes have access to it
        return {
            "code_embedding_result": None,
            "code_availability_result": state.get("code_availability_result")
        }

    # Early exit if code is not available (should have been caught by progressive skipping)
    code_availability = state.get("code_availability_result")
    if not code_availability or not code_availability.code_available:
        logger.info(f"Code not available for paper {state['paper_id']} - marking as skipped")
        await async_ops.update_node_status(node, "skipped")
        await async_ops.create_node_log(node, "INFO", "Skipped (no code repository available)")
        # Pass through code_availability_result so downstream nodes have access to it
        return {
            "code_embedding_result": None,
            "code_availability_result": code_availability
        }

    # Update node status to running
    await async_ops.update_node_status(node, "running", started_at=timezone.now())
    await async_ops.create_node_log(
        node, "INFO", "Starting code repository embedding"
    )

    try:
        # Check for previous embedding
        force_reprocess = state.get("force_reprocess", False)
        if not force_reprocess:
            previous = await async_ops.check_previous_analysis(
                state["paper_id"], node_id
            )
            if previous:
                logger.info(
                    f"Found previous code embedding from {previous['completed_at']}"
                )
                await async_ops.create_node_log(
                    node, "INFO", f"Using cached result from run {previous['run_id']}"
                )

                result = CodeEmbeddingResult(**previous["result"])
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

                return {"code_embedding_result": result}

        # Get code URL from Node B
        code_availability = state.get("code_availability_result")
        if not code_availability or not code_availability.code_available:
            # This shouldn't happen due to routing, but handle defensively
            logger.warning(
                "Node F called without code availability - this indicates routing issue"
            )
            await async_ops.create_node_log(
                node, "WARNING", "Code not available - skipping embeddings"
            )
            await async_ops.update_node_status(
                node, "completed", completed_at=timezone.now()
            )
            # Return empty result - code_embedding is optional
            return {
                "code_embedding_result": None,
                "total_files": 0,
                "total_chunks": 0
            }

        code_url = code_availability.code_url
        paper = await async_ops.get_paper(state["paper_id"])
        client = state["client"]
        model = state["model"]
        
        # Track tokens
        total_input_tokens = 0
        total_output_tokens = 0

        # Check if Node B provided a local clone path (use it to avoid re-cloning)
        source = code_url  # Default to URL
        clone_path_str = None
        
        if code_availability.clone_path:
            clone_path = PathlibPath(code_availability.clone_path)
            if clone_path.exists():
                logger.info(f"Reusing clone from Node B: {clone_path}")
                await async_ops.create_node_log(
                    node, "INFO", f"Reusing verified clone from Node B: {clone_path}"
                )
                source = str(clone_path)
                clone_path_str = str(clone_path)
            else:
                logger.warning(f"Clone path from Node B no longer exists: {clone_path}")
                await async_ops.create_node_log(
                    node,
                    "WARNING",
                    "Clone from Node B not found, will re-clone from URL",
                )

        logger.info(f"Ingesting repository: {source}")
        await async_ops.create_node_log(
            node, "INFO", f"Getting documentation and repository structure from: {source}"
        )

        # Step 1: Initial ingestion - README + tree structure
        summary, tree, content, clone_path_obj = await ingest_with_steroids(
            source,
            max_file_size=100000,
            include_patterns=["/README*"],
            cleanup=False,  # Keep clone for embedding
            get_tree=True,
        )
        
        # Update clone path if we cloned
        if clone_path_obj and not clone_path_str:
            clone_path_str = str(clone_path_obj)

        logger.info(
            f"Repository ingested. Files in the repository: {len(tree.splitlines())}"
        )
        await async_ops.create_node_log(
            node,
            "INFO",
            f"Repository ingested. Files in tree: {len(tree.splitlines())}",
        )

        # Step 2: LLM call to select important files
        code_info_prompt = f"""Documentation:
{content}

Repository Structure:
{tree}

Based on the documentation and the tree structure provided before, generate a list:
 - include_patterns: containing the patterns of files to include that are useful for reproducibility. 
I will use your output on gitingest to retrieve from the code only the useful files, this is an example on how the list should be provided to gitingest: 
include_patterns=["README.md","test/test.py","requirements.txt","Dockerfile","compose.yml"] You can write the full name of a file, avoid using wildcards. 
The include_patterns should be ordered in the way I should retrieve the files, first the documentation files and than the code files. 
If the README is available and it contains instructions to reproduce the results, be sure all the files in it are included in the include_patterns.
DO NOT include files related to comparisons models, only the ones related the architecture proposed in the paper.
ADD "/" in front of a name to include only a file in the root, otherwise everyfile with that name will be included. For example, if you want to include only the README in the root, write "/README.md".
In the tree structure next to the filename is also provided the tokens of each file. Select the included_patterns in a way to reach at maximum 100000 tokens as the count of every file selected, prioritizing the most important files for reproducibility. DO NOT exceed the token limit. DO NOT provide tokens in output, just the filenames or the patterns.
Generate the output ready to be transformed into a Python list of strings.
"""
        
        logger.info("Calling LLM to select important files...")
        await async_ops.create_node_log(
            node, "INFO", "Calling LLM to select important files for embedding..."
        )
        
        response = client.responses.parse(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": "You are an expert code reviewer. Focus on identifying files essential for reproducibility.",
                },
                {"role": "user", "content": code_info_prompt},
            ],
            text_format=PatternExtraction,
            reasoning={"effort":"minimal"},
        )
        retrieved_patterns = response.output_parsed
        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        logger.info(f"LLM suggested code file patterns: {retrieved_patterns.included_patterns}")
        await async_ops.create_node_log(
            node,
            "INFO",
            f"LLM suggested file patterns: {retrieved_patterns.included_patterns}",
        )

        # Step 3: Re-ingest with selected patterns
        _, _, selected_content, _ = await ingest_with_steroids(
            source,
            max_file_size=100000,
            include_patterns=retrieved_patterns.included_patterns,
            cleanup=False,  # Keep clone for embedding ???
            get_tree=False,
        )

        logger.info(f"Retrieved {len(selected_content)} chars of code")
        await async_ops.create_node_log(
            node,
            "INFO",
            f"Retrieved {len(selected_content)} chars from {len(retrieved_patterns.included_patterns)} patterns",
        )

        # Step 4: Parse content into individual files
        # The content from ingest_with_steroids is formatted as:
        # ================================================================================
        # File: path/to/file.py
        # ================================================================================
        #
        # <content>
        
        files = {}
        current_file = None
        current_content_lines = []
        in_header = False
        
        for line in selected_content.split('\n'):
            if line.strip() == '=' * 80:
                if in_header:
                    # End of header, start content
                    in_header = False
                else:
                    # Start of new file header - save previous file
                    if current_file:
                        files[current_file] = '\n'.join(current_content_lines).strip()
                    current_content_lines = []
                    in_header = True
            elif in_header and line.startswith('File: '):
                # Extract filename
                current_file = line[6:].strip()
            elif not in_header and current_file:
                # Content line
                current_content_lines.append(line)
        
        # Save last file
        if current_file and current_content_lines:
            files[current_file] = '\n'.join(current_content_lines).strip()

        logger.info(f"Parsed {len(files)} files from content")
        await async_ops.create_node_log(
            node,
            "INFO",
            f"Parsed {len(files)} files for embedding",
        )

        # Step 5 & 6: Chunk large files and compute embeddings
        embedded_files = []
        total_chunks = 0
        total_tokens_for_embedding = 0
        
        # TODO this should be moved to allow the handling of multiple embedder in the future and to 
        #avoid the coupling with the OpenAI API, we can create a separate service for embeddings that 
        # can handle different providers and models, and also manage the token counting in a more 
        # centralized way. For now, we keep it here for simplicity and because we only have one 
        # embedding model, but this is something to refactor in the future.
        embedding_model = "text-embedding-3-small"

        for file_path, file_content in files.items():
            # Compute content hash
            content_hash = hashlib.sha256(file_content.encode('utf-8')).hexdigest()
            
            # Chunk if necessary
            chunks = chunk_text(file_content, max_chars=20000)
            total_chunks += len(chunks)
            
            logger.info(f"Processing {file_path}: {len(chunks)} chunk(s)")
            
            for chunk_index, chunk_content in enumerate(chunks):
                # Compute embedding
                try:
                    embedding, tokens_used = await compute_embedding(
                        client, chunk_content, model=embedding_model
                    )
                    embedding_dimension = len(embedding)  # Get dimension from actual embedding
                    total_tokens_for_embedding += tokens_used
                    
                    # Create embedding info
                    embedding_info = CodeFileEmbeddingInfo(
                        file_path=file_path,
                        file_content=chunk_content,
                        chunk_index=chunk_index,
                        total_chunks=len(chunks),
                        content_hash=content_hash,
                        embedding=embedding,
                        tokens_used=tokens_used
                    )
                    embedded_files.append(embedding_info)
                    
                    # Store in database
                    from webApp.models import CodeFileEmbedding
                    
                    await sync_to_async(CodeFileEmbedding.objects.update_or_create)(
                        paper=paper,
                        code_url=code_url,
                        file_path=file_path,
                        chunk_index=chunk_index,
                        embedding_model=embedding_model,
                        defaults={
                            'file_content': chunk_content,
                            'total_chunks': len(chunks),
                            'content_hash': content_hash,
                            'embedding': embedding,
                            'embedding_dimension': embedding_dimension,
                            'tokens_used': tokens_used,
                        }
                    )
                    
                    logger.info(
                        f"Embedded {file_path} chunk {chunk_index + 1}/{len(chunks)}: {tokens_used} tokens"
                    )
                    
                except Exception as e:
                    logger.error(f"Error embedding {file_path} chunk {chunk_index}: {e}")
                    await async_ops.create_node_log(
                        node,
                        "WARNING",
                        f"Failed to embed {file_path} chunk {chunk_index}: {str(e)}",
                    )
                    # Continue with other files

        # Determine embedding dimension (from any embedding, all should be same dimension)
        embedding_dimension = len(embedded_files[0].embedding) if embedded_files else 1536

        # Create result
        result = CodeEmbeddingResult(
            code_url=code_url,
            clone_path=clone_path_str,
            summary=summary,
            tree_structure=tree,
            selected_patterns=retrieved_patterns.included_patterns,
            embedded_files=embedded_files,
            total_files=len(files),
            total_chunks=total_chunks,
            total_tokens=total_tokens_for_embedding,
            embedding_model=embedding_model,
            embedding_dimension=embedding_dimension,
        )

        # Store as artifacts
        await async_ops.create_node_artifact(node, "result", result)
        await async_ops.create_node_artifact(
            node,
            "token_usage",
            {
                "llm_input_tokens": total_input_tokens,
                "llm_output_tokens": total_output_tokens,
                "embedding_tokens": total_tokens_for_embedding,
                "total_input_tokens": total_input_tokens + total_tokens_for_embedding,
                "total_output_tokens": total_output_tokens,
            },
        )
        
        # Update node token fields in database
        # Embedding tokens count as input (we send text to embedding API)
        await async_ops.update_node_tokens(
            node,
            input_tokens=total_input_tokens + total_tokens_for_embedding,
            output_tokens=total_output_tokens,
            was_cached=False
        )

        # Log results
        await async_ops.create_node_log(
            node,
            "INFO",
            f"Embedding complete - {len(embedded_files)} chunks embedded from {len(files)} files, {total_tokens_for_embedding} tokens used",
        )

        # Update node status
        await async_ops.update_node_status(
            node,
            "completed",
            completed_at=timezone.now(),
            output_data={"total_files": len(files), "total_chunks": total_chunks},
        )

        return {"code_embedding_result": result}

    except Exception as e:
        logger.error(f"Error in code embedding: {e}", exc_info=True)
        await async_ops.create_node_log(
            node,
            "ERROR",
            f"Error in code embedding: {str(e)}",
        )
        await async_ops.update_node_status(
            node, "failed", completed_at=timezone.now()
        )
        raise
