"""
Helper functions for enhanced paper code repository processing and analysis workflow nodes in paper_processing_workflow.py
"""

import json
import logging
from typing import Optional, Dict, Any, List, Tuple

import numpy as np
from openai import OpenAI
from asgiref.sync import sync_to_async
from gitingest.clone import clone_repo
from gitingest.query_parser import parse_remote_repo, parse_local_dir_path
from gitingest.utils.auth import resolve_token
from gitingest.utils.pattern_utils import process_patterns
from gitingest.utils.ingestion_utils import _should_exclude, _should_include
from urllib.parse import urlparse
from gitingest.utils.query_parser_utils import KNOWN_GIT_HOSTS
import tempfile
import shutil
import subprocess
from pathlib import Path as PathlibPath

from webApp.models import Paper
from workflow_engine.models import (
    WorkflowNode,
)
from workflow_engine.services.async_orchestrator import async_ops
from webApp.services.pydantic_schemas import (
    PatternExtraction,
    ResearchMethodologyAnalysis,
    RepositoryStructureAnalysis,
    CodeAvailabilityAnalysis,
    ArtifactsAnalysis,
    DatasetSplitsAnalysis,
    ReproducibilityDocumentation,
)

logger = logging.getLogger(__name__)


def prepare_paper_content(paper, max_chars: int = 12000) -> str:
    """
    Prepare paper content for analysis (fallback when sections not available).
    
    Args:
        paper: Paper object
        max_chars: Maximum characters to extract from paper text
        
    Returns:
        Formatted string with title, abstract, and truncated text
    """
    content_parts = [f"Title: {paper.title}"]

    if paper.abstract:
        content_parts.append(f"\nAbstract: {paper.abstract}")

    if paper.text:
        text = paper.text[:max_chars]
        content_parts.append(f"\nFull Text:\n{text}")
    else:
        content_parts.append("\n(No full text available)")

    return "\n".join(content_parts)


# ============================================================================
# Embedding Similarity Utilities
# ============================================================================

async def retrieve_sections_by_embedding(
    paper,
    query_embedding: List[float],
    top_k: Optional[int] = None,
    min_similarity: Optional[float] = None,
    max_chars_per_section: Optional[int] = None,
    token_budget: Optional[int] = None
) -> List[Tuple[Any, float, str]]:
    """
    Low-level function to retrieve paper sections by embedding similarity.
    
    Args:
        paper: Paper object or paper_id
        query_embedding: Pre-computed embedding vector to compare against
        top_k: Return top K sections (if using simple cutoff)
        min_similarity: Minimum similarity threshold to include
        max_chars_per_section: Character limit per section
        token_budget: Token budget for selection (alternative to top_k)
        
    Returns:
        List of (section_object, similarity, section_text) tuples
        Sorted by similarity (highest first)
    """
    from webApp.models import PaperSectionEmbedding
    
    # Handle paper_id vs paper object
    paper_id = paper.id if hasattr(paper, 'id') else paper
    
    # Get all section embeddings for this paper
    all_sections = await sync_to_async(
        lambda: list(
            PaperSectionEmbedding.objects.filter(paper_id=paper_id).exclude(
                section_text__isnull=True
            ).exclude(section_text="")
        )
    )()
    
    if not all_sections:
        logger.info(f"No section embeddings found for paper {paper_id}")
        return []
    
    # Compute similarities using model method
    similarities = []
    for section in all_sections:
        similarity = section.compute_cosine_similarity(query_embedding)
        
        # Apply minimum similarity filter if specified
        if min_similarity is not None and similarity < min_similarity:
            continue
        
        similarities.append((section, similarity, section.section_text))
    
    # Sort by similarity (highest first)
    similarities.sort(reverse=True, key=lambda x: x[1])
    
    # Apply selection strategy
    selected = []
    
    if token_budget is not None:
        # Token budget strategy: fill until budget exhausted
        tokens_used = 0
        for section, similarity, text in similarities:
            section_tokens = len(text) // 4  # Rough estimate
            if tokens_used + section_tokens <= token_budget:
                selected.append((section, similarity, text[:max_chars_per_section] if max_chars_per_section else text))
                tokens_used += section_tokens
            else:
                break
    else:
        # Top-k strategy: just take top K
        k = top_k if top_k is not None else len(similarities)
        selected = [
            (section, similarity, text[:max_chars_per_section] if max_chars_per_section else text)
            for section, similarity, text in similarities[:k]
        ]
    
    avg_sim = np.mean([s[1] for s in selected]) if selected else 0.0
    logger.info(
        f"Found {len(all_sections)} sections for paper {paper_id}, "
        f"selected {len(selected)} (avg similarity: {avg_sim:.3f})"
    )
    
    return selected


async def get_relevant_sections_by_similarity(
    paper,
    query: str,
    top_k: int = 4,
    max_chars_per_section: int = 4000,
    client = None
) -> List[Tuple[float, str, str]]:
    """
    Retrieve paper sections most semantically relevant to a text query.
    
    High-level convenience function that computes query embedding and retrieves sections.
    
    Args:
        paper: Paper object
        query: Query text to find relevant sections
        top_k: Number of top sections to return
        max_chars_per_section: Maximum characters per section (for token management)
        client: OpenAI client (optional, will create if not provided)
        
    Returns:
        List of tuples (similarity_score, section_type, section_text)
        Sorted by similarity (highest first)
    """
    try:
        # Get or create OpenAI client
        if client is None:
            from openai import OpenAI
            import os
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        # Compute query embedding
        query_response = client.embeddings.create(
            model="text-embedding-3-small",
            input=query
        )
        query_embedding = query_response.data[0].embedding
        
        # Use low-level function
        results = await retrieve_sections_by_embedding(
            paper=paper,
            query_embedding=query_embedding,
            top_k=top_k,
            max_chars_per_section=max_chars_per_section
        )
        
        # Convert to simplified format (similarity, section_type, section_text)
        return [
            (similarity, section.section_type, text)
            for section, similarity, text in results
        ]
        
    except Exception as e:
        logger.warning(f"Could not retrieve sections by similarity: {e}")
        return []


# ============================================================================
# Reproducibility Scoring
# ============================================================================

def compute_reproducibility_score(
    methodology: Optional[ResearchMethodologyAnalysis],
    structure: Optional[RepositoryStructureAnalysis],
    components: Optional[CodeAvailabilityAnalysis],
    artifacts: Optional[ArtifactsAnalysis],
    dataset_splits: Optional[DatasetSplitsAnalysis],
    documentation: Optional[ReproducibilityDocumentation],
) -> tuple[float, Dict[str, float], List[str]]:
    """
    Compute reproducibility score programmatically from extracted facts.

    Adapts scoring weights based on research methodology type:
    - deep_learning/machine_learning: Full weights on training, checkpoints, splits
    - algorithm: Focus on code completeness and examples
    - simulation: Focus on parameters and seeds
    - data_analysis: Focus on data and scripts
    - theoretical: Focus on proofs/derivations (if applicable)

    Returns:
        (score, breakdown, recommendations)
        - score: 0-100 overall reproducibility score
        - breakdown: Dict with component scores (0-100 scale)
        - recommendations: List of improvement suggestions
    """
    breakdown = {
        "code_completeness": 0.0,  # 2.5-3.0 points (adaptive)
        "dependencies": 0.0,  # 1.0 points
        "artifacts": 0.0,  # 0-2.5 points (adaptive)
        "dataset_splits": 0.0,  # 0-2.0 points (adaptive)
        "documentation": 0.0,  # 2.0 points
    }
    
    # Track max points for each component (for normalization to 0-100 scale)
    component_max = {
        "code_completeness": 0.0,
        "dependencies": 1.0,
        "artifacts": 0.0,
        "dataset_splits": 0.0,
        "documentation": 2.0,
    }
    
    recommendations = []

    # Determine methodology-specific weights
    if methodology:
        requires_training = methodology.requires_training
        requires_datasets = methodology.requires_datasets
        requires_splits = methodology.requires_splits
        method_type = methodology.methodology_type
    else:
        # Default to ML assumptions if no methodology detected
        requires_training = True
        requires_datasets = True
        requires_splits = True
        method_type = "unknown"

    # 1. Code Completeness (2.5-3.0 points, adaptive)
    max_code_points = 3.0 if requires_training else 2.5
    component_max["code_completeness"] = max_code_points

    if components:
        score = 0.0

        if requires_training:
            # ML/DL: Needs both training and evaluation
            if components.has_training_code and components.has_evaluation_code:
                score = 2.5
            elif components.has_evaluation_code or components.has_training_code:
                score = 1.5
                if not components.has_training_code:
                    recommendations.append(
                        "Add training code to enable full reproducibility"
                    )
                if not components.has_evaluation_code:
                    recommendations.append("Add evaluation/inference code")
            else:
                score = 0.5
                recommendations.append("Provide both training and evaluation code")
        else:
            # Non-ML: Evaluation/implementation code is sufficient
            if components.has_evaluation_code:
                score = 2.0  # Full credit for having implementation
            elif components.has_training_code:  # Could be simulation code
                score = 2.0
            else:
                score = 0.5
                recommendations.append(
                    f"Provide implementation code for the {method_type} method"
                )

        # Bonus for documented commands (always valuable)
        if components.has_documented_commands:
            score += 0.5
        else:
            recommendations.append("Document precise commands to run the code")

        breakdown["code_completeness"] = min(score, max_code_points)
    else:
        recommendations.append("Provide complete code implementation")

    # 2. Dependencies (1.0 point - always important)
    if structure:
        if structure.has_requirements:
            if structure.requirements_match_imports is True:
                breakdown["dependencies"] = 1.0
            elif structure.requirements_match_imports is False:
                breakdown["dependencies"] = 0.5
                recommendations.append(
                    "Fix dependencies file - some imports are missing"
                )
            else:
                breakdown["dependencies"] = 0.7
        else:
            recommendations.append(
                "Add requirements/dependencies file with all necessary packages and versions"
            )

    # 3. Artifacts (0-2.5 points, adaptive)
    if requires_datasets or requires_training:
        component_max["artifacts"] = 2.5
        if artifacts:
            # Checkpoints: 0-1.0 point (only for models)
            if requires_training:
                if artifacts.has_checkpoints:
                    breakdown["artifacts"] += 1.0
                else:
                    recommendations.append(
                        "Release model checkpoints to enable result verification without retraining"
                    )

            # Dataset links: 0-1.5 points (weighted by coverage)
            if requires_datasets:
                if artifacts.has_dataset_links:
                    if artifacts.dataset_coverage == "full":
                        breakdown["artifacts"] += 1.5
                    elif artifacts.dataset_coverage == "partial":
                        breakdown["artifacts"] += 0.8
                        recommendations.append(
                            "Provide download links for ALL datasets used"
                        )
                    else:
                        breakdown["artifacts"] += 0.3
                else:
                    recommendations.append("Provide dataset download links")
            else:
                # Non-dataset research: Give partial credit if repo is complete
                breakdown["artifacts"] += 1.0  # Baseline for having working code
        else:
            if requires_training:
                recommendations.append("Release model checkpoints and dataset links")
            elif requires_datasets:
                recommendations.append("Provide dataset download links")
    else:
        # Non-data research: Award full artifacts points if code is complete
        component_max["artifacts"] = 2.0
        if components and (
            components.has_evaluation_code or components.has_training_code
        ):
            breakdown["artifacts"] = 2.0  # Full credit for complete implementation

    # 4. Dataset Splits (0-2.0 points, adaptive) - CRITICAL for ML, less for others
    if requires_splits:
        component_max["dataset_splits"] = 2.0
        if dataset_splits:
            score = 0.0
            if dataset_splits.splits_specified:
                score += 0.7
            else:
                recommendations.append(
                    "Specify which dataset splits (train/val/test) were used"
                )

            if dataset_splits.splits_provided:
                score += 0.7
            else:
                recommendations.append("Provide split files or explicit split logic")

            if dataset_splits.random_seeds_documented:
                score += 0.6
            else:
                recommendations.append(
                    "Document random seeds for reproducible data partitioning"
                )

            breakdown["dataset_splits"] = score
        else:
            recommendations.append(
                "Document dataset splits and random seeds for experiment replicability"
            )
    else:
        # Non-ML: Award points if seeds/parameters are documented
        component_max["dataset_splits"] = 1.5
        if dataset_splits and dataset_splits.random_seeds_documented:
            breakdown["dataset_splits"] = 1.5  # Reward for documenting randomness
            recommendations.append("Continue documenting all sources of randomness")
        else:
            breakdown["dataset_splits"] = (
                0.5  # Partial credit for deterministic methods
            )
            if method_type in ["simulation", "algorithm"]:
                recommendations.append(
                    "Document random seeds and parameters for reproducible results"
                )

    # 5. Documentation (2.0 points - always critical)
    if documentation:
        if documentation.has_readme:
            breakdown["documentation"] += 0.5
        else:
            recommendations.append("Create comprehensive README file")

        if documentation.has_results_table:
            breakdown["documentation"] += 0.75
        else:
            recommendations.append("Include results table in README for comparison")

        if documentation.has_reproduction_commands:
            breakdown["documentation"] += 0.75
        else:
            recommendations.append("Document step-by-step reproduction commands")
    else:
        recommendations.append(
            "Add comprehensive documentation with results and reproduction steps"
        )

    # Calculate maximum achievable score for this paper type (for normalization)
    max_possible_score = 0.0
    max_possible_score += max_code_points  # 2.5 or 3.0
    max_possible_score += 1.0  # dependencies (always)

    if requires_datasets or requires_training:
        max_possible_score += 2.5  # artifacts
    else:
        max_possible_score += 2.0  # baseline for complete code

    if requires_splits:
        max_possible_score += 2.0  # dataset_splits
    else:
        max_possible_score += 1.5  # best case for non-split papers (documented seeds)

    max_possible_score += 2.0  # documentation (always)

    # Compute raw total score
    raw_score = sum(breakdown.values())

    # Normalize to 100-point scale
    total_score = (
        (raw_score / max_possible_score) * 100.0 if max_possible_score > 0 else 0.0
    )

    # Round to 1 decimal place
    total_score = round(total_score, 1)
    
    # Scale each component breakdown to 0-100 based on its OWN max value
    breakdown_normalized = {}
    for component, raw_value in breakdown.items():
        max_for_component = component_max.get(component, 1.0)
        if max_for_component > 0:
            normalized = round((raw_value / max_for_component) * 100.0, 1)
        else:
            normalized = 0.0
        breakdown_normalized[component] = normalized

    return total_score, breakdown_normalized, recommendations


async def ingest_with_steroids(
    source: str,
    *,
    max_file_size: int = 100000,
    include_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
    token: str | None = None,
    cleanup: bool = True,
    get_tree: bool = True,
) -> tuple[str, str, str, Optional[PathlibPath]]:
    """
    Enhanced repository ingestion function that:
    1. Clones the full repository locally (for URLs) or processes existing local path
    2. Generates a complete tree structure using the 'tree' command
    3. Organizes file content based on include_pattern order

    Parameters
    ----------
    source : str
        Repository URL or local path to existing repository
    max_file_size : int
        Maximum file size to include (default: 100000 bytes)
    include_patterns : Optional[List[str]]
        List of patterns to include (e.g., ["*.md", "*.py"])
        Files will be ordered in content based on this list order
    exclude_patterns : Optional[List[str]]
        List of patterns to exclude
    token : str | None
        Authentication token for private repositories
    cleanup : bool
        Whether to delete the cloned repository after processing (default: True)
        Only applies to cloned repositories, not local paths
    get_tree : bool
        Whether to generate the full tree structure (default: True)

    Returns
    -------
    tuple[str, str, str, Optional[PathlibPath]]
        (summary, tree, content, clone_path) where:
        - summary: Repository metadata and statistics
        - tree: Full directory tree structure
        - content: Concatenated file contents ordered by include_patterns
        - clone_path: Path to cloned repository (None if cleanup=True)
    """
    logger.info(f"Starting enhanced ingestion for: {source}")

    # Resolve authentication token
    token = resolve_token(token)

    # Create temporary directory for cloning
    temp_dir = None
    clone_path = None
    query = None

    try:
        if urlparse(source).scheme in ("https", "http") or any(
            h in source for h in KNOWN_GIT_HOSTS
        ):
            # We either have a full URL or a domain-less slug
            logger.info("Parsing remote repository", extra={"source": source})
            # Parse the repository URL
            query = await parse_remote_repo(source, token=token)

            temp_dir = tempfile.mkdtemp(prefix="gitingest_steroids_")
            clone_path = PathlibPath(temp_dir) / query.slug

            # Update query with our clone path
            query.local_path = clone_path

            # Clone the full repository (not sparse)
            clone_config = query.extract_clone_config()
            logger.info(f"Cloning repository to: {clone_path}")
            await clone_repo(clone_config, token=token)
        else:
            # Local path scenario
            logger.info("Processing local directory", extra={"source": source})
            query = parse_local_dir_path(source)
            clone_path = query.local_path

        # Generate full tree structure using tree command
        tree_output = ""
        if get_tree:
            logger.info("Generating full repository tree structure")
            try:
                tree_result = subprocess.run(
                    ["tree", "--gitignore", "-a", "-L", "10", str(clone_path)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                tree_output = tree_result.stdout
                if tree_result.returncode != 0:
                    logger.warning(f"Tree command warning: {tree_result.stderr}")
                    # Fallback to basic tree without --gitignore
                    tree_result = subprocess.run(
                        ["tree", "-a", "-L", "10", str(clone_path)],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    tree_output = tree_result.stdout
            except subprocess.TimeoutExpired:
                logger.warning("Tree command timed out, using fallback")
                tree_output = f"Repository tree (timeout): {query.slug}\n"
            except FileNotFoundError:
                logger.warning("'tree' command not found, generating basic structure")
                tree_output = _generate_basic_tree(clone_path)

        # Collect files based on include_patterns order
        logger.info("Collecting file contents based on patterns")
        content_parts = []
        total_files = 0
        total_size = 0

        # Process patterns using gitingest's pattern processor
        ignore_patterns, include_patterns_processed = process_patterns(
            exclude_patterns=exclude_patterns,
            include_patterns=include_patterns,
        )

        # Collect all files, then organize them by pattern order
        if include_patterns:
            # Dictionary to group files by which pattern they match
            files_by_pattern = {pattern: [] for pattern in include_patterns}
            unmatched_files = []

            # Walk through all files in the repository
            for file_path in clone_path.rglob("*"):
                if not file_path.is_file():
                    continue

                # Skip if excluded by ignore patterns
                if ignore_patterns and _should_exclude(
                    file_path, clone_path, ignore_patterns
                ):
                    continue

                # Skip if not included by include patterns
                if include_patterns_processed and not _should_include(
                    file_path, clone_path, include_patterns_processed
                ):
                    continue

                # Check file size
                file_size = file_path.stat().st_size
                if file_size > max_file_size:
                    logger.debug(
                        f"Skipping large file: {file_path.name} ({file_size} bytes)"
                    )
                    continue

                # Determine which pattern this file matches (use first matching pattern)
                matched = False
                for pattern in include_patterns:
                    # Simple pattern matching for ordering
                    if pattern.startswith("*") and file_path.name.endswith(pattern[1:]):
                        files_by_pattern[pattern].append(file_path)
                        matched = True
                        break
                    elif pattern.endswith("*") and file_path.name.startswith(
                        pattern[:-1]
                    ):
                        files_by_pattern[pattern].append(file_path)
                        matched = True
                        break
                    elif pattern in file_path.name or pattern.strip("/") in str(
                        file_path
                    ):
                        files_by_pattern[pattern].append(file_path)
                        matched = True
                        break

                if not matched:
                    unmatched_files.append(file_path)

            # Process files in pattern order
            for pattern in include_patterns:
                for file_path in sorted(files_by_pattern[pattern]):
                    try:
                        relative_path = file_path.relative_to(clone_path)
                        content_parts.append(f"\n{'='*80}\n")
                        content_parts.append(f"File: {relative_path}\n")
                        content_parts.append(f"{'='*80}\n\n")

                        with open(
                            file_path, "r", encoding="utf-8", errors="ignore"
                        ) as f:
                            file_content = f.read()
                            content_parts.append(file_content)
                            content_parts.append("\n\n")

                        total_files += 1
                        total_size += file_path.stat().st_size

                    except Exception as e:
                        logger.warning(f"Error reading file {file_path}: {e}")
                        continue

            # Add unmatched files at the end (if any were included)
            for file_path in sorted(unmatched_files):
                try:
                    relative_path = file_path.relative_to(clone_path)
                    content_parts.append(f"\n{'='*80}\n")
                    content_parts.append(f"File: {relative_path}\n")
                    content_parts.append(f"{'='*80}\n\n")

                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        file_content = f.read()
                        content_parts.append(file_content)
                        content_parts.append("\n\n")

                    total_files += 1
                    total_size += file_path.stat().st_size

                except Exception as e:
                    logger.warning(f"Error reading file {file_path}: {e}")
                    continue
        else:
            # No patterns specified, collect all text files
            for file_path in clone_path.rglob("*"):
                if not file_path.is_file():
                    continue

                # Skip if excluded
                if ignore_patterns and _should_exclude(
                    file_path, clone_path, ignore_patterns
                ):
                    continue

                file_size = file_path.stat().st_size
                if file_size > max_file_size:
                    continue

                try:
                    relative_path = file_path.relative_to(clone_path)
                    content_parts.append(f"\n{'='*80}\n")
                    content_parts.append(f"File: {relative_path}\n")
                    content_parts.append(f"{'='*80}\n\n")

                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        file_content = f.read()
                        content_parts.append(file_content)
                        content_parts.append("\n\n")

                    total_files += 1
                    total_size += file_size

                except Exception as e:
                    continue

        content = "".join(content_parts)

        # Generate summary
        summary = f"""Repository: {query.repo_name}
Owner: {query.user_name}
URL: {query.url}
Branch: {query.branch or 'default'}
Commit: {query.commit or 'latest'}
Total Files Processed: {total_files}
Total Size: {total_size} bytes
"""

        logger.info(f"Ingestion complete: {total_files} files, {total_size} bytes")

        # Return clone path if cleanup is False, otherwise None
        return_clone_path = clone_path if not cleanup else None

        return (summary, tree_output, content, return_clone_path)

    except Exception as e:
        logger.error(f"Error during enhanced ingestion: {e}", exc_info=True)
        raise
    finally:
        # Cleanup temporary directory only if cleanup=True
        if cleanup and temp_dir and PathlibPath(temp_dir).exists():
            try:
                shutil.rmtree(temp_dir)
                logger.debug(f"Cleaned up temporary directory: {temp_dir}")
            except Exception as e:
                logger.warning(f"Error cleaning up temp directory: {e}")


def _generate_basic_tree(
    path: PathlibPath, prefix: str = "", max_depth: int = 5, current_depth: int = 0
) -> str:
    """
    Fallback method
    Generate a basic tree structure when 'tree' command is not available.

    Parameters
    ----------
    path : PathlibPath
        Directory path to generate tree from
    prefix : str
        Prefix for tree formatting
    max_depth : int
        Maximum depth to traverse
    current_depth : int
        Current traversal depth

    Returns
    -------
    str
        Tree structure as string
    """
    if current_depth >= max_depth:
        return ""

    tree_lines = []

    # Directories to exclude from tree
    excluded_dirs = {"static", "staticfiles", "media", "node_modules", "__pycache__"}

    try:
        items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))

        # Filter out items starting with '.' (hidden files/directories) and excluded directories
        items = [
            item
            for item in items
            if not item.name.startswith(".") and item.name not in excluded_dirs
        ]

        for i, item in enumerate(items):
            current_prefix = "    "  # spaces instead of │ and ├─ for save tokens
            child_prefix = "    "

            # For files, add estimated token count
            if item.is_file():
                try:
                    # Get file size in bytes
                    file_size = item.stat().st_size
                    # Estimate tokens (1 token ≈ 4 characters/bytes)
                    estimated_tokens = file_size // 4
                    tree_lines.append(
                        f"{prefix}{current_prefix}{item.name} - {estimated_tokens}\n"
                    )
                except Exception:
                    # If we can't read file size, just show the name
                    tree_lines.append(f"{prefix}{current_prefix}{item.name}\n")
            else:
                tree_lines.append(f"{prefix}{current_prefix}{item.name}\n")

            if item.is_dir() and not item.is_symlink():
                subtree = _generate_basic_tree(
                    item, prefix + child_prefix, max_depth, current_depth + 1
                )
                tree_lines.append(subtree)
    except PermissionError:
        pass

    return "".join(tree_lines)


async def analyze_repository_comprehensive(
    code_url: str,
    paper: Paper,
    client: OpenAI,
    model: str,
    node: "WorkflowNode" = None,  # Optional node for detailed logging
) -> Dict[str, Any]:
    """
    Perform comprehensive analysis of code repository.

    This is the main agentic analysis function that evaluates all reproducibility criteria.

    Parameters
    ----------
    code_url : str
        Repository URL or local path to repository
    paper : Paper
        Paper object
    client : OpenAI
        OpenAI client
    model : str
        Model name
    node : WorkflowNode
        Optional node for detailed logging
    """
    logger.info(f"Starting comprehensive repository analysis for {paper.title}")

    if node:
        await async_ops.create_node_log(
            node, "INFO", "Starting comprehensive repository analysis"
        )

    try:
        # Download repository content using gitingest
        logger.info("Getting documentation and repository structure...")
        if node:
            await async_ops.create_node_log(
                node, "INFO", "Getting documentation and repository structure..."
            )
        # Download repository content using enhanced ingestion with full tree structure
        # Note: include_patterns order matters - files will be ordered in content as:
        # 1. Documentation files (*.md, *.txt) - for understanding the project
        # 2. Code files (*.py, *.js, etc.) - for analyzing implementation
        # 3. Config files (*.yml, *.json, etc.) - for dependencies and setup
        summary, tree, content, _ = await ingest_with_steroids(
            code_url,
            max_file_size=100000,
            include_patterns=[
                "/README*",
            ],
            cleanup=True,  # Always cleanup after comprehensive analysis
            get_tree=True,  # Get full tree structure for analysis
        )

        logger.info(
            f"Repository ingested. Files in the repository: {len(tree.splitlines())}"
        )
        if node:
            await async_ops.create_node_log(
                node,
                "INFO",
                f"Repository ingested. Files in the repository:\n{len(tree.splitlines())}",
            )

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
        )
        retrieved_patterns = response.output_parsed
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens

        logger.info(f"LLM suggested code file patterns: {retrieved_patterns}")
        if node:
            await async_ops.create_node_log(
                node,
                "INFO",
                f"LLM suggested code file patterns: {retrieved_patterns}",
            )

        # Get the content from the repository using the retrieved patterns generated by the LLM.
        _, _, content, _ = await ingest_with_steroids(
            code_url,
            max_file_size=100000,
            include_patterns=retrieved_patterns.included_patterns,
            cleanup=True,  # Always cleanup after comprehensive analysis
            get_tree=False,
        )

        file_count = len(tree.splitlines())  # directories included
        logger.info(
            f"Repository ingested: {file_count} files, {len(content)// 4} tokens"
        )
        if node:
            await async_ops.create_node_log(
                node,
                "INFO",
                f"Repository ingested: {file_count} files, {len(content)// 4} tokens",
            )

        # Prepare paper text (truncate if too long to avoid token limits)
        # TODO manage this point
        max_code_chars = 400000
        if len(content) > max_code_chars:
            content = (
                content[:max_code_chars]
                + "\n\n[... code content truncated for brevity ...]"
            )
            logger.info(
                f"Code content truncated to {max_code_chars} chars for analysis"
            )
            if node:
                await async_ops.create_node_log(
                    node,
                    "INFO",
                    f"Code content truncated to {max_code_chars} chars for analysis",
                )

        # Use LLM to analyze repository structure and contents
        analysis_prompt = f"""You are an expert code reviewer analyzing a research code repository for reproducibility.

Repository: {code_url}

Repository Structure:
{tree}

Code Files and documentation:
{content[:400000]}

Paper Information:
Title: {paper.title}
Abstract: {paper.abstract or 'Not available'}

Paper Text (excerpt):
{paper.text if paper.text else 'Not available'}

Analyze this repository comprehensively and provide structured JSON output covering:

0. Research Methodology Classification:
   - What type of research is this? (deep_learning, machine_learning, algorithm, simulation, data_analysis, theoretical, other)
   - Does the methodology require model training?
   - Does it require datasets?
   - Does it require dataset splits for evaluation?
   - Notes about the methodology and what reproducibility components are essential

1. Repository Structure:
   - Is it standalone or built on another repository?
   - Does it have requirements/dependencies file?
   - Do requirements match the imports in code?
   - Programming languages used (Python, JavaScript, C++, Java, Matlab, etc.)

2. Code Components:
   - Is training code available?
   - Is evaluation/inference code available?
   - Are commands to run the code documented?

3. Artifacts:
   - Are model checkpoints released?
   - Are dataset download links provided?
   - Is coverage full or partial?

4. Dataset Splits Information:
   - Does the repository specify which dataset splits (train/val/test) were used?
   - Are the exact splits documented or provided?
   - Can experiments be replicated with the same data partitioning?
   - Are random seeds documented for reproducible splits?

5. Documentation:
   - Does README exist?
   - Does it include results table?
   - Does it include precise reproduction commands?

6. Overall Assessment:
   - Summary assessment of reproducibility
   - Key strengths and weaknesses

Be thorough and evidence-based in your analysis. Pay special attention to whether experiments can be truly replicated with the same dataset splits.

NOTE: Do NOT compute a numeric score - focus on extracting factual information only in a JSON format ready to be saved."""

        logger.info("Analyzing repository with LLM...")
        if node:
            await async_ops.create_node_log(
                node, "INFO", "Analyzing repository with LLM..."
            )

        # Call LLM with structured output
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": "You are an expert code reproducibility analyst. Provide detailed, evidence-based analysis.",
                },
                {"role": "user", "content": analysis_prompt},
            ],
            reasoning_effort="minimal",
        #temperature=0.2,
            #max_output_tokens=4000,
        )

        # Parse LLM response
        analysis_text = response.output_text
        input_tokens += response.usage.input_tokens
        output_tokens += response.usage.output_tokens

        logger.info(f"LLM analysis completed ({output_tokens} tokens)")
        if node:
            # Save detailed analysis text
            await async_ops.create_node_log(
                node,
                "INFO",
                f"LLM analysis completed ({output_tokens} tokens)",
            )
            # Log a preview of the analysis
            preview = (
                analysis_text[:500] + "..."
                if len(analysis_text) > 500
                else analysis_text
            )
            await async_ops.create_node_log(
                node, "DEBUG", f"Analysis preview:\n{preview}"
            )

        # Use LLM again to structure the analysis into our schema
        structuring_prompt = f"""Convert this repository analysis into structured JSON with the following exact schema:

{{
  "methodology": {{
    "methodology_type": string (one of: deep_learning, machine_learning, algorithm, simulation, data_analysis, theoretical, other),
    "requires_training": boolean (does this method need model training?),
    "requires_datasets": boolean (does this method need datasets?),
    "requires_splits": boolean (does evaluation need train/val/test splits?),
    "methodology_notes": string (notes about research type and essential reproducibility components)
  }},
  "structure": {{
    "is_standalone": boolean (true/false),
    "base_repository": string or null,
    "has_requirements": boolean,
    "requirements_match_imports": boolean or null,
    "requirements_issues": [list of strings]
  }},
  "components": {{
    "has_training_code": boolean,
    "training_code_paths": [list of file paths],
    "has_evaluation_code": boolean,
    "evaluation_code_paths": [list of file paths],
    "has_documented_commands": boolean,
    "command_documentation_location": string or null
  }},
  "artifacts": {{
    "has_checkpoints": boolean,
    "checkpoint_locations": [list of URLs/paths],
    "has_dataset_links": boolean,
    "dataset_coverage": "full" or "partial" or "none",
    "dataset_links": [list of {{"name": "dataset name", "url": "URL"}}]
  }},
  "dataset_splits": {{
    "splits_specified": boolean (whether train/val/test splits are mentioned),
    "splits_provided": boolean (whether split files or exact splits are in repo),
    "random_seeds_documented": boolean (whether seeds are documented),
    "splits_notes": string (notes about splits and replicability)
  }},
  "documentation": {{
    "has_readme": boolean,
    "has_results_table": boolean,
    "has_reproduction_commands": boolean,
    "documentation_notes": string (notes about documentation quality)
  }},
  "overall_assessment": string (summary of reproducibility status)
}}

IMPORTANT: 
- All fields are REQUIRED, use appropriate null/empty values if not applicable
- For boolean fields, use true or false (not "yes"/"no")
- For list fields, use [] if empty (not null)
- Focus on FACTUAL extraction only - no scoring or recommendations
- Include specific file paths, URLs, and evidence-based values

Analysis to convert:
{analysis_text}

Output the complete JSON object with ALL fields filled in based on the analysis above."""

        logger.info("Structuring analysis into schema...")
        if node:
            await async_ops.create_node_log(
                node, "INFO", "Structuring analysis into schema..."
            )

        structured_response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a JSON conversion specialist. Convert the analysis to the exact JSON schema provided. Include ALL required fields.",
                },
                {"role": "user", "content": structuring_prompt},
            ],
            response_format={"type": "json_object"},
            reasoning_effort="minimal",
        #temperature=0.0,
            #max_tokens=2000,
        )

        structured_data = json.loads(structured_response.choices[0].message.content)

        input_tokens += structured_response.usage.prompt_tokens
        output_tokens += structured_response.usage.completion_tokens

        logger.info(
            f"Structured data extracted: {len(structured_data)} top-level fields ({list(structured_data.keys())})"
        )
        if node:
            await async_ops.create_node_log(
                node,
                "INFO",
                f"Structured data extracted: {len(structured_data)} top-level fields ({list(structured_data.keys())})",
            )

        # Helper function to safely create Pydantic models
        def safe_model_create(model_class, data):
            """Create Pydantic model only if data is not empty."""
            if not data or not isinstance(data, dict):
                logger.warning(f"{model_class.__name__}: No data or invalid type")
                return None

            # Check if ALL values are None (but allow False, 0, empty strings, empty lists)
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

        # Build comprehensive result
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

        # Compute reproducibility score programmatically
        logger.info("Computing reproducibility score...")
        if node:
            await async_ops.create_node_log(
                node, "INFO", "Computing reproducibility score..."
            )

        score, breakdown, recommendations = compute_reproducibility_score(
            methodology_obj,
            structure_obj,
            components_obj,
            artifacts_obj,
            dataset_splits_obj,
            documentation_obj,
        )

        logger.info(f"Computed reproducibility score: {score}/100")
        logger.info(f"Score breakdown: {breakdown}")

        if node:
            breakdown_text = "\n".join(f"  • {k}: {v}/100" for k, v in breakdown.items())
            await async_ops.create_node_log(
                node,
                "INFO",
                f"Reproducibility score: {score}/100\n\nBreakdown:\n{breakdown_text}",
            )

            # Log key findings
            if recommendations:
                rec_preview = "\n".join(f"  • {r}" for r in recommendations[:3])
                await async_ops.create_node_log(
                    node,
                    "INFO",
                    f'Top recommendations:\n{rec_preview}{"\n  ..." if len(recommendations) > 3 else ""}',
                )

        result = {
            "methodology": methodology_obj,
            "structure": structure_obj,
            "components": components_obj,
            "artifacts": artifacts_obj,
            "dataset_splits": dataset_splits_obj,
            "documentation": documentation_obj,
            "reproducibility_score": score,
            "score_breakdown": breakdown,
            "overall_assessment": structured_data.get(
                "overall_assessment", "Analysis completed"
            ),
            "recommendations": recommendations,  # Programmatically generated
            "input_tokens": input_tokens,  # concatenated previously since the number of llm calls increased
            "output_tokens": output_tokens,  # concatenated previously since the number of llm calls increased
            "llm_analysis_text": analysis_text,  # Store full LLM analysis
            "structured_data": structured_data,  # Store structured JSON
        }

        logger.info("Comprehensive repository analysis complete")
        return result

    except Exception as e:
        logger.error(f"Error in comprehensive repository analysis: {e}", exc_info=True)
        if node:
            await async_ops.create_node_log(
                node,
                "ERROR",
                f"Error in comprehensive repository analysis: {e}",
            )

        # Return minimal analysis on error
        return {
            "structure": None,
            "components": None,
            "artifacts": None,
            "dataset_splits": None,
            "documentation": None,
            "reproducibility_score": 0.0,
            "score_breakdown": {},
            "overall_assessment": f"Analysis failed: {str(e)}",
            "recommendations": ["Manual review required due to analysis error"],
            "input_tokens": 0,
            "output_tokens": 0,
        }
