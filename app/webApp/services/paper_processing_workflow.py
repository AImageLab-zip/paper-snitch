"""
Paper Processing Workflow - Integrated with Workflow Engine

This module implements a two-node workflow for analyzing papers:
- Node A: Paper Type Classification (dataset vs method vs both)
- Node B: Code Reproducibility Analysis (agentic analysis of code availability and quality)

Properly integrated with the workflow_engine models for:
- History tracking
- Versioning
- Artifact storage
- Progress monitoring
"""

import os
import re
import json
import logging
import asyncio
import requests
from typing import TypedDict, Optional, Dict, Any, List
from pathlib import Path
from datetime import datetime, timedelta

from django.utils import timezone

from langgraph.graph import StateGraph, END
from openai import OpenAI
from pydantic import BaseModel, Field, ConfigDict
from gitingest import ingest_async
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
    WorkflowDefinition,
    WorkflowRun,
    WorkflowNode,
    NodeArtifact,
    NodeLog,
)
from workflow_engine.services.async_orchestrator import async_ops

logger = logging.getLogger(__name__)


# ============================================================================
# Pydantic Models for Structured Outputs
# ============================================================================


class PaperTypeClassification(BaseModel):
    """Structured output for paper type classification."""

    model_config = ConfigDict(extra="forbid")

    paper_type: str = Field(
        description="Type of contribution: 'dataset', 'method', 'both', 'theoretical', or 'unknown'"
    )
    confidence: float = Field(
        description="Confidence score between 0 and 1", ge=0.0, le=1.0
    )
    reasoning: str = Field(
        description="Detailed reasoning for the classification decision"
    )
    key_evidence: List[str] = Field(
        description="Key quotes or evidence from the paper supporting the classification"
    )


class OnlineCodeSearch(BaseModel):
    """Structured output for online code repository search."""

    model_config = ConfigDict(extra="forbid")

    repository_url: Optional[str] = Field(
        description="URL to the code repository if found, null if not found"
    )
    confidence: float = Field(
        description="Confidence score between 0 and 1", ge=0.0, le=1.0
    )
    search_strategy: str = Field(
        description="How the repository was found (e.g., 'GitHub search', 'author's profile', 'paper title match')"
    )
    notes: str = Field(
        description="Additional notes about the search process or why repository wasn't found"
    )


class CodeAvailabilityCheck(BaseModel):
    """Structured output for code availability verification."""

    model_config = ConfigDict(extra="forbid")

    code_available: bool = Field(description="Whether actual code is available")
    code_url: Optional[str] = Field(description="URL to the code repository if found")
    found_online: bool = Field(
        description="Whether code was found online (not in original paper)"
    )
    availability_notes: str = Field(
        description="Notes about code availability (empty, unreachable, docs only, etc.)"
    )
    clone_path: Optional[str] = Field(
        default=None,
        description="Path to cloned repository if verified (for reuse in Node C)",
    )


class ResearchMethodologyAnalysis(BaseModel):
    """Analysis of research methodology type for context-aware scoring."""

    model_config = ConfigDict(extra="forbid")

    methodology_type: str = Field(
        description="Type: 'deep_learning', 'machine_learning', 'algorithm', 'simulation', 'data_analysis', 'theoretical', 'other'"
    )
    requires_training: bool = Field(
        description="Whether this research requires model training"
    )
    requires_datasets: bool = Field(
        description="Whether this research requires datasets"
    )
    requires_splits: bool = Field(
        description="Whether this research requires dataset splits"
    )
    methodology_notes: str = Field(description="Notes about the research methodology")


class RepositoryStructureAnalysis(BaseModel):
    """Analysis of repository structure and dependencies."""

    model_config = ConfigDict(extra="forbid")

    is_standalone: bool = Field(
        description="Whether repository is standalone or built on another repo"
    )
    base_repository: Optional[str] = Field(
        description="Base repository if not standalone"
    )
    has_requirements: bool = Field(description="Requirements file exists")
    requirements_match_imports: Optional[bool] = Field(
        description="Whether requirements match code imports (None if cannot check)"
    )
    requirements_issues: List[str] = Field(
        description="List of issues with requirements"
    )


class CodeAvailabilityAnalysis(BaseModel):
    """Analysis of what code components are available."""

    model_config = ConfigDict(extra="forbid")

    has_training_code: bool = Field(description="Training code available")
    training_code_paths: List[str] = Field(description="Paths to training code files")
    has_evaluation_code: bool = Field(description="Evaluation/inference code available")
    evaluation_code_paths: List[str] = Field(
        description="Paths to evaluation code files"
    )
    has_documented_commands: bool = Field(
        description="Commands to run code are documented"
    )
    command_documentation_location: Optional[str] = Field(
        description="Where commands are documented (README, scripts, etc.)"
    )


class ArtifactsAnalysis(BaseModel):
    """Analysis of checkpoints and dataset availability."""

    model_config = ConfigDict(extra="forbid")

    has_checkpoints: bool = Field(description="Model checkpoints are released")
    checkpoint_locations: List[str] = Field(description="URLs or paths to checkpoints")
    has_dataset_links: bool = Field(description="Dataset download links available")
    dataset_coverage: str = Field(
        description="'full', 'partial', or 'none' - coverage of dataset links"
    )
    dataset_links: List[Dict[str, str]] = Field(
        description="List of dataset names and their download URLs"
    )


class DatasetSplitsAnalysis(BaseModel):
    """Analysis of dataset splits and experiment replicability."""

    model_config = ConfigDict(extra="forbid")

    splits_specified: bool = Field(
        description="Dataset splits (train/val/test) are specified"
    )
    splits_provided: bool = Field(
        description="Split files or exact splits are provided in repo"
    )
    random_seeds_documented: bool = Field(
        description="Random seeds are documented for reproducible splits"
    )
    splits_notes: str = Field(
        description="Notes about dataset splits and replicability"
    )


class ReproducibilityDocumentation(BaseModel):
    """Analysis of reproducibility documentation."""

    model_config = ConfigDict(extra="forbid")

    has_readme: bool = Field(description="README file exists")
    has_results_table: bool = Field(description="README includes results table")
    has_reproduction_commands: bool = Field(
        description="README includes precise commands to reproduce results"
    )
    documentation_notes: str = Field(description="Notes about documentation quality")


class CodeReproducibilityAnalysis(BaseModel):
    """Complete code reproducibility analysis artifact."""

    model_config = ConfigDict(extra="forbid")

    analysis_timestamp: str = Field(description="ISO timestamp of analysis")
    code_availability: CodeAvailabilityCheck
    research_methodology: Optional[ResearchMethodologyAnalysis] = None
    repository_structure: Optional[RepositoryStructureAnalysis] = None
    code_components: Optional[CodeAvailabilityAnalysis] = None
    artifacts: Optional[ArtifactsAnalysis] = None
    dataset_splits: Optional[DatasetSplitsAnalysis] = None
    documentation: Optional[ReproducibilityDocumentation] = None
    reproducibility_score: float = Field(
        description="Computed reproducibility score (0-10)", ge=0.0, le=10.0
    )
    score_breakdown: Dict[str, float] = Field(
        description="Breakdown of score by component"
    )
    overall_assessment: str = Field(
        description="High-level summary of reproducibility status"
    )
    recommendations: List[str] = Field(
        description="Recommendations for improving reproducibility"
    )
    input_tokens: int = Field(description="Tokens used in LLM input")
    output_tokens: int = Field(description="Tokens used in LLM output")


class PatternExtraction(BaseModel):
    """Schema to extract inclusion and exclusion patterns."""

    included_patterns: List[str] = Field(
        default_factory=list,
        description="List of string patterns to include. Return an empty list if no inclusion patterns are found.",
    )


# ============================================================================
# Workflow State
# ============================================================================


class PaperProcessingState(TypedDict):
    """State passed between workflow nodes."""

    # Workflow engine models
    workflow_run_id: str
    paper_id: int

    # Current node being executed
    current_node_id: Optional[str]

    # OpenAI client
    client: OpenAI
    model: str

    # Configuration
    force_reprocess: bool

    # Node outputs (stored as artifacts)
    paper_type_result: Optional[PaperTypeClassification]
    code_availability_result: Optional[CodeAvailabilityCheck]
    code_reproducibility_result: Optional[CodeReproducibilityAnalysis]

    # Errors
    errors: List[str]


# ============================================================================
# Reproducibility Scoring Function
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
        - score: 0-10 overall reproducibility score
        - breakdown: Dict with component scores
        - recommendations: List of improvement suggestions
    """
    breakdown = {
        "code_completeness": 0.0,  # 2.5-3.0 points (adaptive)
        "dependencies": 0.0,  # 1.0 points
        "artifacts": 0.0,  # 0-2.5 points (adaptive)
        "dataset_splits": 0.0,  # 0-2.0 points (adaptive)
        "documentation": 0.0,  # 2.0 points
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
        if components and (
            components.has_evaluation_code or components.has_training_code
        ):
            breakdown["artifacts"] = 2.0  # Full credit for complete implementation

    # 4. Dataset Splits (0-2.0 points, adaptive) - CRITICAL for ML, less for others
    if requires_splits:
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

    # Normalize to 10-point scale
    total_score = (
        (raw_score / max_possible_score) * 10.0 if max_possible_score > 0 else 0.0
    )

    # Round to 1 decimal place
    total_score = round(total_score, 1)
    breakdown = {k: round(v, 2) for k, v in breakdown.items()}

    return total_score, breakdown, recommendations


# ============================================================================
# Node A: Paper Type Classification
# ============================================================================


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


# ============================================================================
# Node B: Code Availability Check
# ============================================================================


async def code_availability_check_node(
    state: PaperProcessingState,
) -> Dict[str, Any]:
    """
    Node B: Check code availability (can run in parallel to paper type classification).

    This lightweight node:
    1. Checks if code links exist in paper database or text
    2. If not found, performs LLM-powered online search
    3. Saves found URL to database if discovered online
    4. Returns code availability result

    Results are stored as NodeArtifacts.
    """
    node_id = "code_availability_check"
    logger.info(
        f"Node B: Starting code availability check for paper {state['paper_id']}"
    )

    # Get workflow node
    node = await async_ops.get_workflow_node(state["workflow_run_id"], node_id)

    # Update node status to running
    await async_ops.update_node_status(node, "running", started_at=timezone.now())
    await async_ops.create_node_log(node, "INFO", "Starting code availability check")

    try:
        # Check for previous analysis
        force_reprocess = state.get("force_reprocess", False)
        if not force_reprocess:
            previous = await async_ops.check_previous_analysis(
                state["paper_id"], node_id
            )
            if previous:
                logger.info(f"Found previous check from {previous['completed_at']}")
                await async_ops.create_node_log(
                    node, "INFO", f"Using cached result from run {previous['run_id']}"
                )

                result = CodeAvailabilityCheck(**previous["result"])
                await async_ops.create_node_artifact(node, "result", result)
                await async_ops.update_node_status(
                    node, "completed", completed_at=timezone.now()
                )

                return {"code_availability_result": result}

        # Get paper from database
        paper = await async_ops.get_paper(state["paper_id"])
        client = state["client"]
        model = state["model"]

        code_url = None
        found_online = False
        search_notes = ""

        # Step 1: Check if URL already exists in database
        if paper.code_url:
            code_url = paper.code_url
            search_notes = "Found in paper database"
            logger.info(f"Found code URL in database: {code_url}")
            await async_ops.create_node_log(
                node, "INFO", f"Code URL found in database: {code_url}"
            )

        # Step 2: If not in database, search in paper text
        if not code_url and paper.text:
            url_pattern = r"https?://(?:github\.com|gitlab\.com|bitbucket\.org|gitee\.com|codeberg\.org)/[\w\-]+/[\w\-]+"
            matches = re.findall(url_pattern, paper.text)

            if matches:
                # Multiple matches found - need to verify which is the correct one
                logger.info(
                    f"Found {len(matches)} repository URLs in paper text. Verifying which belongs to this paper..."
                )
                await async_ops.create_node_log(
                    node,
                    "INFO",
                    f"Found {len(matches)} repository URLs - checking each to find the correct one",
                )

                best_match = None
                best_confidence = 0.0

                for candidate_url in matches:
                    try:
                        logger.info(f"Checking repository: {candidate_url}")

                        # Clone and get README
                        summary, tree, content, clone_path = await ingest_with_steroids(
                            candidate_url,
                            max_file_size=100000,
                            include_patterns=["README*", "readme*"],
                            cleanup=True,  # Clean up after checking
                            get_tree=False,
                        )

                        if content and len(content) > 50:
                            # Use LLM to check if this repo is associated with this paper
                            verification_prompt = f"""You are verifying if a GitHub repository belongs to a specific research paper.

Paper Title: {paper.title}
Paper Authors: {getattr(paper, 'authors', 'Unknown')}

Repository URL: {candidate_url}
Repository README excerpt:
{content[:2000]}

Your task: Determine if this repository is the OFFICIAL code release for THIS specific paper, or if it's just cited/referenced as related work.

Indicators that it IS the official repo:
- README mentions the exact paper title
- README mentions the paper authors
- README says "code for our paper" or similar
- README links to this paper on arXiv/proceedings

Indicators that it is NOT the official repo:
- README describes a different paper/project
- Different authors
- Just a general tool/library cited as related work
- No mention of this specific paper

Respond with your assessment."""

                            class RepoVerification(BaseModel):
                                is_official_repo: bool = Field(
                                    description="True if this is the official code repo for the paper"
                                )
                                confidence: float = Field(
                                    description="Confidence score 0.0-1.0",
                                    ge=0.0,
                                    le=1.0,
                                )
                                reasoning: str = Field(
                                    description="Brief explanation of the decision"
                                )

                            response = client.responses.parse(
                                model=model,
                                input=[
                                    {"role": "user", "content": verification_prompt}
                                ],
                                text_format=RepoVerification,
                            )

                            verification = response.output_parsed
                            input_tokens = response.usage.input_tokens
                            output_tokens = response.usage.output_tokens

                            logger.info(
                                f"Verification for {candidate_url}: official={verification.is_official_repo}, confidence={verification.confidence}"
                            )
                            await async_ops.create_node_log(
                                node,
                                "INFO",
                                f"Repository {candidate_url}: {'OFFICIAL' if verification.is_official_repo else 'NOT official'} (confidence: {verification.confidence})",
                                {"reasoning": verification.reasoning},
                            )

                            if (
                                verification.is_official_repo
                                and verification.confidence > best_confidence
                            ):
                                best_match = candidate_url
                                best_confidence = verification.confidence

                    except Exception as e:
                        logger.warning(
                            f"Error verifying repository {candidate_url}: {e}"
                        )
                        await async_ops.create_node_log(
                            node,
                            "WARNING",
                            f"Could not verify {candidate_url}: {str(e)}",
                        )

                    if best_match:
                        code_url = best_match
                        search_notes = f"Found in paper text (verified from {len(matches)} candidates, confidence: {best_confidence})"
                        logger.info(
                            f"Selected repository: {code_url} (confidence: {best_confidence})"
                        )
                        await async_ops.create_node_log(
                            node, "INFO", f"Selected verified repository: {code_url}"
                        )
                    else:
                        # No match found
                        search_notes = f"Not found in paper text (unverified - None of {len(matches)} candidates has been selected)"
                        logger.info(
                            f"No verified match found, using first URL: {code_url}"
                        )
                        await async_ops.create_node_log(
                            node,
                            "WARNING",
                            f"Could not verify any repository - using first match: {code_url}",
                        )

        # Step 3: If still not found, perform LLM-powered online search (last resort)
        if not code_url:
            logger.info(
                "Code URL not in database or paper text. Performing online search as last resort..."
            )
            await async_ops.create_node_log(
                node,
                "INFO",
                "Code not found in database or paper - attempting LLM-powered online search",
            )

            try:
                search_result = await search_code_online(paper, client, model)

                if search_result.repository_url and search_result.confidence >= 0.7:
                    code_url = search_result.repository_url
                    found_online = True
                    search_notes = f"Found online: {search_result.search_strategy} (confidence: {search_result.confidence})"

                    logger.info(
                        f"LLM found repository: {code_url} ({search_result.search_strategy})"
                    )
                    await async_ops.create_node_log(
                        node,
                        "INFO",
                        f"Online search successful: {code_url}",
                        {
                            "strategy": search_result.search_strategy,
                            "confidence": search_result.confidence,
                        },
                    )

                    # Save to database
                    from asgiref.sync import sync_to_async

                    @sync_to_async
                    def update_paper_code_url(paper_id, url):
                        paper = Paper.objects.get(id=paper_id)
                        paper.code_url = url
                        paper.save()

                    await update_paper_code_url(state["paper_id"], code_url)
                    logger.info(
                        f"Saved code URL to database for paper {state['paper_id']}"
                    )
                    await async_ops.create_node_log(
                        node, "INFO", "Code URL saved to paper database"
                    )
                else:
                    search_notes = search_result.notes
                    logger.info(f"Online search unsuccessful: {search_notes}")
                    await async_ops.create_node_log(
                        node, "WARNING", f"No code found online: {search_notes}"
                    )

            except Exception as e:
                logger.warning(f"Error in online search: {e}")
                await async_ops.create_node_log(
                    node, "WARNING", f"Online search error: {str(e)}"
                )
                search_notes = f"Online search failed: {str(e)}"

        # Step 4: If URL found, verify it's actually accessible and contains code
        verified_clone_path = None
        if code_url:
            logger.info(f"Verifying code URL accessibility: {code_url}")
            await async_ops.create_node_log(
                node, "INFO", f"Verifying repository accessibility: {code_url}"
            )

            try:
                # Quick HTTP HEAD check
                import requests

                response = requests.head(code_url, timeout=10, allow_redirects=True)

                if response.status_code == 404:
                    logger.warning(f"Repository not found (404): {code_url}")
                    await async_ops.create_node_log(
                        node, "WARNING", f"Repository not found (HTTP 404)"
                    )
                    result = CodeAvailabilityCheck(
                        code_available=False,
                        code_url=code_url,
                        found_online=found_online,
                        availability_notes=f"{search_notes}. Verification failed: Repository not found (404)",
                    )
                elif response.status_code >= 400:
                    logger.warning(
                        f"Repository not accessible (HTTP {response.status_code}): {code_url}"
                    )
                    await async_ops.create_node_log(
                        node,
                        "WARNING",
                        f"Repository not accessible (HTTP {response.status_code})",
                    )
                    result = CodeAvailabilityCheck(
                        code_available=False,
                        code_url=code_url,
                        found_online=found_online,
                        availability_notes=f"{search_notes}. Verification failed: HTTP {response.status_code}",
                    )
                else:
                    # URL is reachable, now verify it contains actual code files
                    logger.info(f"URL reachable, verifying code content...")
                    await async_ops.create_node_log(
                        node,
                        "INFO",
                        "URL reachable, performing shallow clone to verify code content",
                    )

                    try:
                        # Shallow clone to verify code content (lightweight check)
                        # Include common research code patterns: Python, JS, Java, C/C++, Go, Rust,
                        # Matlab, R, Julia, shell scripts, and Jupyter notebooks
                        # verify_code_accessibility
                        summary, tree, content, clone_path = await ingest_with_steroids(
                            code_url,
                            max_file_size=50000,
                            include_patterns=[
                                "*.py",
                                "*.js",
                                "*.ts",
                                "*.java",
                                "*.cpp",
                                "*.c",
                                "*.h",
                                "*.go",
                                "*.rs",
                                "*.m",
                                "*.R",
                                "*.jl",
                                "*.sh",
                                "*.bash",
                                "*.ipynb",
                                "*.scala",
                                "*.rb",
                            ],
                            cleanup=False,  # Keep clone for Node C
                            get_tree=False,  # Skip tree for speed
                        )

                        # Check if actual code files exist
                        if not content or len(content) < 100:
                            logger.warning(
                                f"Repository empty or no code files: {code_url}"
                            )
                            await async_ops.create_node_log(
                                node,
                                "WARNING",
                                "Repository empty or contains no code files",
                            )
                            # Cleanup failed clone
                            if clone_path and clone_path.parent.exists():
                                import shutil

                                shutil.rmtree(clone_path.parent)
                            result = CodeAvailabilityCheck(
                                code_available=False,
                                code_url=code_url,
                                found_online=found_online,
                                availability_notes=f"{search_notes}. Verification failed: No code files found",
                            )
                        else:
                            # Success - code verified!
                            verified_clone_path = (
                                str(clone_path) if clone_path else None
                            )
                            logger.info(
                                f"Repository verified: contains {len(content)} chars of code"
                            )
                            await async_ops.create_node_log(
                                node,
                                "INFO",
                                f"Repository verified: contains code ({len(content)} chars). Clone saved for Node C.",
                            )
                            result = CodeAvailabilityCheck(
                                code_available=True,
                                code_url=code_url,
                                found_online=found_online,
                                availability_notes=f"{search_notes}. Verified: Repository accessible and contains code.",
                                clone_path=verified_clone_path,
                            )

                    except Exception as e:
                        logger.warning(f"Error verifying repository content: {e}")
                        await async_ops.create_node_log(
                            node, "WARNING", f"Error during shallow clone: {str(e)}"
                        )
                        result = CodeAvailabilityCheck(
                            code_available=False,
                            code_url=code_url,
                            found_online=found_online,
                            availability_notes=f"{search_notes}. Verification failed: {str(e)}",
                        )

            except requests.Timeout:
                logger.warning(f"Repository request timed out: {code_url}")
                await async_ops.create_node_log(
                    node, "WARNING", "Repository request timed out"
                )
                result = CodeAvailabilityCheck(
                    code_available=False,
                    code_url=code_url,
                    found_online=found_online,
                    availability_notes=f"{search_notes}. Verification failed: Request timed out",
                )
            except Exception as e:
                logger.warning(f"Error verifying repository: {e}")
                await async_ops.create_node_log(
                    node, "WARNING", f"Error during verification: {str(e)}"
                )
                result = CodeAvailabilityCheck(
                    code_available=False,
                    code_url=code_url,
                    found_online=found_online,
                    availability_notes=f"{search_notes}. Verification error: {str(e)}",
                )
        else:
            # No URL found at all
            result = CodeAvailabilityCheck(
                code_available=False,
                code_url=None,
                found_online=False,
                availability_notes=search_notes
                or "No code repository found in paper, text, or online",
            )

        # Store result as artifact
        await async_ops.create_node_artifact(node, "result", result)

        # Log success
        await async_ops.create_node_log(
            node,
            "INFO",
            f"Code availability check complete: {'Found' if code_url else 'Not found'}",
            {"code_url": code_url, "found_online": found_online},
        )

        # Update node status
        await async_ops.update_node_status(
            node,
            "completed",
            completed_at=timezone.now(),
            output_data={
                "code_available": result.code_available,
                "code_url": code_url,
                "found_online": found_online,
            },
        )

        return {"code_availability_result": result}

    except Exception as e:
        logger.error(f"Error in code availability check: {e}", exc_info=True)

        # Log error
        await async_ops.create_node_log(
            node, "ERROR", str(e), {"traceback": str(e.__traceback__)}
        )

        # Update node status to failed
        await async_ops.update_node_status(
            node, "failed", completed_at=timezone.now(), error_message=str(e)
        )

        return {"errors": state.get("errors", []) + [f"Node B error: {str(e)}"]}


# ============================================================================
# Node C: Code Repository Analysis
# ============================================================================


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

        logger.info(f"Analyzing repository: {code_url}")

        # Get clone path from Node B if available (avoid re-cloning)
        clone_path = None
        if code_availability.clone_path:
            clone_path = PathlibPath(code_availability.clone_path)
            if clone_path.exists():
                logger.info(f"Reusing clone from Node B: {clone_path}")
                await async_ops.create_node_log(
                    node, "INFO", f"Reusing verified clone from Node B: {clone_path}"
                )
            else:
                logger.warning(f"Clone path from Node B no longer exists: {clone_path}")
                await async_ops.create_node_log(
                    node, "WARNING", "Clone from Node B not found, will re-clone"
                )
                clone_path = None

        # Step 1: Comprehensive repository analysis (reuses clone if available)
        await async_ops.create_node_log(
            node, "INFO", f"Starting comprehensive repository analysis: {code_url}"
        )

        repo_analysis = await analyze_repository_comprehensive(
            code_url, paper, client, model, clone_path=clone_path, node=node
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


# ============================================================================
# Helper Functions
# ============================================================================


async def search_code_online(
    paper: Paper, client: OpenAI, model: str
) -> OnlineCodeSearch:
    """
    Use LLM to search for code repository online with structured output.

    This function performs an intelligent search using the paper's metadata
    to find the most likely code repository.

    Args:
        paper: Paper object with title, abstract, authors
        client: OpenAI client
        model: Model name

    Returns:
        OnlineCodeSearch result with repository URL (if found) and metadata
    """
    # Construct detailed search prompt
    authors_str = ""
    if hasattr(paper, "authors") and paper.authors:
        authors_str = f"Authors: {paper.authors}\n"

    search_prompt = f"""You are a research code repository finder. Your task is to find the official code repository for this paper.

Paper Information:
Title: {paper.title}
{authors_str}Abstract: {paper.abstract or 'Not available'}

Search Strategy:
1. Search GitHub/GitLab/Bitbucket for repositories matching the paper title
2. Look for repositories from the paper's authors
3. Check for official implementations mentioned in the paper
4. Verify the repository actually corresponds to this specific paper

Platforms to search: GitHub, GitLab, Bitbucket, Gitee, Codeberg

Important:
- Only return a repository URL if you are reasonably confident it's the correct one
- The repository should match the paper title and methodology
- If uncertain or no repository found, set repository_url to null and confidence to 0.0
- Explain your search strategy and reasoning

Provide:
1. Repository URL (or null if not found/uncertain)
2. Confidence score (0.0 to 1.0) - only use >= 0.7 if very confident
3. Search strategy used
4. Notes about the search process"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert at finding academic code repositories. Be conservative - only return URLs when you're confident they match the paper.",
                },
                {"role": "user", "content": search_prompt},
            ],
            tools=[{"type": "web_search"}],
            tool_choice="auto",
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "online_code_search",
                    "strict": True,
                    "schema": OnlineCodeSearch.model_json_schema(),
                },
            },
            temperature=0.2,
        )

        result_dict = json.loads(response.choices[0].message.content)
        result = OnlineCodeSearch(**result_dict)

        logger.info(
            f"Online search result: {result.repository_url or 'Not found'} (confidence: {result.confidence})"
        )
        logger.info(f"Search strategy: {result.search_strategy}")

        return result

    except Exception as e:
        logger.error(f"Error in online code search: {e}")
        return OnlineCodeSearch(
            repository_url=None,
            confidence=0.0,
            search_strategy="Error occurred",
            notes=f"Search failed: {str(e)}",
        )


async def ingest_with_steroids(
    source: str,
    *,
    max_file_size: int = 100000,
    include_patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
    token: str | None = None,
    cleanup: bool = True,
    existing_clone_path: Optional[PathlibPath] = None,
    get_tree: bool = True,
) -> tuple[str, str, str, Optional[PathlibPath]]:
    """
    Enhanced repository ingestion function that:
    1. Clones the full repository locally (or reuses existing clone)
    2. Generates a complete tree structure using the 'tree' command
    3. Organizes file content based on include_pattern order

    Parameters
    ----------
    source : str
        Repository URL or local path
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
    existing_clone_path : Optional[PathlibPath]
        Path to existing cloned repository to reuse (skips cloning step)
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
    clone_path = existing_clone_path
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
    clone_path: Optional[PathlibPath] = None,
    node: "WorkflowNode" = None,  # Optional node for detailed logging
) -> Dict[str, Any]:
    """
    Perform comprehensive analysis of code repository.

    This is the main agentic analysis function that evaluates all reproducibility criteria.

    Parameters
    ----------
    code_url : str
        Repository URL
    paper : Paper
        Paper object
    client : OpenAI
        OpenAI client
    model : str
        Model name
    clone_path : Optional[PathlibPath]
        Existing clone path from verify_code_accessibility (avoids re-cloning)
    """
    logger.info(f"Starting comprehensive repository analysis for {code_url}")

    if node:
        await async_ops.create_node_log(
            node, "INFO", "Starting comprehensive repository analysis"
        )

    try:
        # Download repository content using gitingest
        if node:
            await async_ops.create_node_log(
                node, "INFO", "Downloading repository files..."
            )
        # Download repository content using enhanced ingestion with full tree structure
        # Note: include_patterns order matters - files will be ordered in content as:
        # 1. Documentation files (*.md, *.txt) - for understanding the project
        # 2. Code files (*.py, *.js, etc.) - for analyzing implementation
        # 3. Config files (*.yml, *.json, etc.) - for dependencies and setup
        # If clone_path is provided, reuse it; otherwise clone fresh
        summary, tree, content, _ = await ingest_with_steroids(
            code_url,
            max_file_size=100000,
            include_patterns=[
                "/README*",
            ],
            cleanup=True,  # Always cleanup after comprehensive analysis
            existing_clone_path=clone_path,  # Reuse existing clone if available
        )

        logger.info(f"Repository ingested. Content size: {len(content)} chars")

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

        # Get the content from the repository using the retrieved patterns generated by the LLM.
        _, _, content, _ = await ingest_with_steroids(
            code_url,
            max_file_size=100000,
            include_patterns=retrieved_patterns.included_patterns,
            cleanup=True,  # Always cleanup after comprehensive analysis
            existing_clone_path=clone_path,  # Reuse existing clone if available
            get_tree=True,
        )

        content_size_kb = len(content) / 1024
        logger.info(
            f"Repository ingested. Content size: {len(content)} chars ({content_size_kb:.1f} KB)"
        )
        if node:
            # Count files in tree
            file_count = len(tree.splitlines())  # directories included
            await async_ops.create_node_log(
                node,
                "INFO",
                f"Repository downloaded: {file_count} files, {content_size_kb:.1f} KB",
            )

        # Prepare paper text (truncate if too long to avoid token limits)
        paper_text = paper.text or ""
        max_paper_chars = 50000
        if len(paper_text) > max_paper_chars:
            paper_text = (
                paper_text[:max_paper_chars]
                + "\n\n[... text truncated for brevity ...]"
            )
            if node:
                await async_ops.create_node_log(
                    node,
                    "INFO",
                    f"Paper text truncated to {max_paper_chars} chars for analysis",
                )

        max_code_chars = 400000
        if len(content) > max_code_chars:
            content = (
                content[:max_code_chars]
                + "\n\n[... code content truncated for brevity ...]"
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

NOTE: Do NOT compute a numeric score - focus on extracting factual information only."""

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
            temperature=0.2,
            max_output_tokens=4000,
        )

        # Parse LLM response
        analysis_text = response.output_text
        input_tokens += response.usage.input_tokens
        output_tokens += response.usage.output_tokens

        logger.info(f"LLM analysis received ({len(analysis_text)} chars)")
        if node:
            # Save detailed analysis text
            await async_ops.create_node_log(
                node,
                "INFO",
                f"LLM analysis complete ({len(analysis_text)} chars, {output_tokens} tokens)",
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
            temperature=0.0,
            max_tokens=2000,
        )

        structured_data = json.loads(structured_response.choices[0].message.content)

        # Log the structured data for debugging
        logger.info(
            f"Structured extraction completed. Keys: {list(structured_data.keys())}"
        )
        input_tokens += structured_response.usage.prompt_tokens
        output_tokens += structured_response.usage.completion_tokens

        if node:
            await async_ops.create_node_log(
                node,
                "INFO",
                f"Structured data extracted: {len(structured_data)} top-level fields",
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

        logger.info(f"Computed reproducibility score: {score}/10")
        logger.info(f"Score breakdown: {breakdown}")

        if node:
            breakdown_text = "\n".join(f"  • {k}: {v}/10" for k, v in breakdown.items())
            await async_ops.create_node_log(
                node,
                "INFO",
                f"Reproducibility score: {score}/10\n\nBreakdown:\n{breakdown_text}",
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


# ============================================================================
# Workflow Definition and Execution
# ============================================================================


def build_paper_processing_workflow() -> StateGraph:
    """
    Build the LangGraph workflow for paper processing with conditional routing.

    Workflow structure (sequential with conditional routing):
    - Node A (paper_type_classification): Classify paper type
    - Node B (code_availability_check): Check code availability and verify accessibility
    - Node C (code_repository_analysis): Comprehensive code analysis (conditional)

    Flow:
    1. paper_type_classification runs first
    2. code_availability_check runs second
    3. After code_availability_check, route to:
       * END if paper is 'theoretical' or 'dataset'
       * END if no code found (code_available=False)
       * code_repository_analysis if code found AND paper is 'method', 'both', or 'unknown'
    """

    workflow = StateGraph(PaperProcessingState)

    # Add nodes
    workflow.add_node("paper_type_classification", paper_type_classification_node)
    workflow.add_node("code_availability_check", code_availability_check_node)
    workflow.add_node("code_repository_analysis", code_repository_analysis_node)

    # Define routing function
    def route_after_checks(state: PaperProcessingState) -> str:
        """
        Route after both paper type classification and code availability check.

        Returns:
            - "code_repository_analysis" if should analyze code
            - END if should skip analysis
        """
        paper_type_result = state.get("paper_type_result")
        code_availability = state.get("code_availability_result")

        # Skip if theoretical or dataset paper
        if paper_type_result and paper_type_result.paper_type in [
            "theoretical",
            "dataset",
        ]:
            logger.info(
                f"Skipping code analysis for {paper_type_result.paper_type} paper"
            )
            return END

        # Skip if no code available
        if not code_availability or not code_availability.code_available:
            logger.info("Skipping code analysis - no code available")
            return END

        # Proceed to repository analysis for method/both/unknown papers with code
        logger.info("Proceeding to code repository analysis")
        return "code_repository_analysis"

    # Set entry point and sequential flow
    workflow.set_entry_point("paper_type_classification")
    workflow.add_edge("paper_type_classification", "code_availability_check")

    # Conditional routing after both checks complete
    workflow.add_conditional_edges(
        "code_availability_check",
        route_after_checks,
        {
            "code_repository_analysis": "code_repository_analysis",
            END: END,
        },
    )

    # Code repository analysis always ends
    workflow.add_edge("code_repository_analysis", END)

    return workflow.compile()


async def execute_single_node_only(
    node_uuid: str,
    force_reprocess: bool = True,
    openai_api_key: Optional[str] = None,
    model: str = "gpt-4o",
) -> Dict[str, Any]:
    """
    Execute a single node in isolation by re-running it within its existing workflow run.

    Args:
        node_uuid: UUID of the node to re-execute
        force_reprocess: If True, reprocess even if already completed (default True)
        openai_api_key: OpenAI API key (uses env var if not provided)
        model: OpenAI model to use

    Returns:
        Dictionary with execution results
    """
    logger.info(f"Re-executing single node {node_uuid}")

    try:
        # Get the node
        node = await async_ops.get_node_by_uuid(node_uuid)
        if not node:
            raise ValueError(f"Node {node_uuid} not found")

        workflow_run = node.workflow_run
        paper_id = workflow_run.paper.id

        logger.info(
            f"Node {node_uuid} current status: {node.status}, node_id: {node.node_id}"
        )

        # Note: Node status should already be set to 'pending' by the view
        # The node function will update it to 'running' when it starts

        # Initialize OpenAI client
        api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        client = OpenAI(api_key=api_key)

        # Build state for this node execution
        state: PaperProcessingState = {
            "workflow_run_id": str(workflow_run.id),
            "paper_id": paper_id,
            "current_node_id": node.node_id,
            "client": client,
            "model": model,
            "force_reprocess": force_reprocess,
            "paper_type_result": None,
            "code_availability_result": None,
            "code_reproducibility_result": None,
            "errors": [],
        }

        logger.info(f"Loading dependencies for node {node.node_id}")

        # Load previous node results if they exist
        if node.node_id == "code_availability_check":
            # Need paper_type_result from previous node
            prev_node = await async_ops.get_workflow_node(
                str(workflow_run.id), "paper_type_classification"
            )
            if prev_node and prev_node.status == "completed":
                # Get the result artifact
                artifacts = await async_ops.get_node_artifacts(prev_node)
                for artifact in artifacts:
                    if artifact.name == "result":
                        state["paper_type_result"] = PaperTypeClassification(
                            **artifact.inline_data
                        )
                        logger.info(
                            f"Loaded paper_type_result from previous node: {state['paper_type_result'].paper_type}"
                        )
                        break

        elif node.node_id == "code_repository_analysis":
            # Need both paper_type_result and code_availability_result from previous nodes
            paper_type_node = await async_ops.get_workflow_node(
                str(workflow_run.id), "paper_type_classification"
            )
            if paper_type_node and paper_type_node.status == "completed":
                artifacts = await async_ops.get_node_artifacts(paper_type_node)
                for artifact in artifacts:
                    if artifact.name == "result":
                        state["paper_type_result"] = PaperTypeClassification(
                            **artifact.inline_data
                        )
                        logger.info(
                            f"Loaded paper_type_result: {state['paper_type_result'].paper_type}"
                        )
                        break

            code_avail_node = await async_ops.get_workflow_node(
                str(workflow_run.id), "code_availability_check"
            )
            if code_avail_node and code_avail_node.status == "completed":
                artifacts = await async_ops.get_node_artifacts(code_avail_node)
                for artifact in artifacts:
                    if artifact.name == "result":
                        state["code_availability_result"] = CodeAvailabilityCheck(
                            **artifact.inline_data
                        )
                        logger.info(
                            f"Loaded code_availability_result: code_available={state['code_availability_result'].code_available}"
                        )
                        break

        logger.info(f"Executing node function for {node.node_id}")

        # Execute the appropriate node function
        if node.node_id == "paper_type_classification":
            result = await paper_type_classification_node(state)
        elif node.node_id == "code_availability_check":
            result = await code_availability_check_node(state)
        elif node.node_id == "code_repository_analysis":
            result = await code_repository_analysis_node(state)
        else:
            raise ValueError(f"Unknown node type: {node.node_id}")

        logger.info(f"Node function executed, result keys: {result.keys()}")

        # Check for errors
        errors = result.get("errors", [])
        success = len(errors) == 0

        logger.info(
            f"Single node execution completed. Success: {success}, Errors: {errors}"
        )

        # Check if all nodes in the workflow are completed to update workflow run status
        try:
            # Get all nodes in this workflow run
            all_nodes = await async_ops.get_workflow_nodes(str(workflow_run.id))

            # Check statuses
            all_completed_or_failed = all(
                n.status in ["completed", "failed"] for n in all_nodes
            )
            any_failed = any(n.status == "failed" for n in all_nodes)

            if all_completed_or_failed:
                # All nodes finished, update workflow run status
                workflow_status = "failed" if any_failed else "completed"
                await async_ops.update_workflow_run_status(
                    workflow_run.id, workflow_status, completed_at=timezone.now()
                )
                logger.info(
                    f"Workflow run {workflow_run.id} updated to status: {workflow_status}"
                )
        except Exception as e:
            logger.warning(
                f"Failed to update workflow run status after node execution: {e}"
            )

        return {
            "success": success,
            "node_id": node.node_id,
            "node_uuid": str(node.id),
            "workflow_run_id": str(workflow_run.id),
            "errors": errors,
        }

    except Exception as e:
        logger.error(f"Failed to execute single node: {e}", exc_info=True)
        # Try to update node status to failed
        try:
            node = await async_ops.get_node_by_uuid(node_uuid)
            if node:
                await async_ops.update_node_status(
                    node, "failed", completed_at=timezone.now(), error_message=str(e)
                )
                await async_ops.create_node_log(
                    node, "ERROR", f"Node execution failed: {str(e)}"
                )

                # Also check if workflow should be marked as failed
                try:
                    all_nodes = await async_ops.get_workflow_nodes(
                        str(node.workflow_run.id)
                    )
                    all_completed_or_failed = all(
                        n.status in ["completed", "failed"] for n in all_nodes
                    )
                    if all_completed_or_failed:
                        await async_ops.update_workflow_run_status(
                            node.workflow_run.id,
                            "failed",
                            completed_at=timezone.now(),
                            error_message=str(e),
                        )
                        logger.info(
                            f"Workflow run {node.workflow_run.id} updated to 'failed'"
                        )
                except Exception as inner_inner_e:
                    logger.error(f"Failed to update workflow status: {inner_inner_e}")
        except Exception as inner_e:
            logger.error(
                f"Failed to update node status after error: {inner_e}", exc_info=True
            )

        return {"success": False, "error": str(e)}


async def execute_workflow_from_node(
    node_uuid: str, openai_api_key: Optional[str] = None, model: str = "gpt-4o"
) -> Dict[str, Any]:
    """
    Create a new workflow run that copies results from previous nodes and executes from the specified node onwards.

    Args:
        node_uuid: UUID of the node to start from
        openai_api_key: OpenAI API key (uses env var if not provided)
        model: OpenAI model to use

    Returns:
        Dictionary with workflow results
    """
    logger.info(f"Executing workflow from node {node_uuid}")

    try:
        # Get the original node
        original_node = await async_ops.get_node_by_uuid(node_uuid)
        if not original_node:
            raise ValueError(f"Node {node_uuid} not found")

        original_workflow_run = original_node.workflow_run
        paper_id = original_workflow_run.paper.id

        # Get workflow definition
        workflow_def = original_workflow_run.workflow_definition

        # Create new workflow run
        config = {
            "force_reprocess": True,
            "model": model,
            "max_retries": 3,
            "start_from_node": original_node.node_id,
        }
        new_workflow_run = await async_ops.create_workflow_run_with_paper_id(
            workflow_name=workflow_def.name, paper_id=paper_id, input_data=config
        )

        # Update workflow run status to running
        await async_ops.update_workflow_run_status(
            new_workflow_run.id, "running", started_at=timezone.now()
        )

        # Get all nodes from the original workflow run
        original_nodes = await async_ops.get_workflow_nodes(
            str(original_workflow_run.id)
        )

        # Determine which nodes come before the target node based on DAG
        dag_structure = workflow_def.dag_structure
        nodes_order = [n["id"] for n in dag_structure.get("nodes", [])]
        target_node_index = (
            nodes_order.index(original_node.node_id)
            if original_node.node_id in nodes_order
            else -1
        )

        # Copy results from nodes that come before the target node
        for orig_node in original_nodes:
            if nodes_order.index(orig_node.node_id) < target_node_index:
                # Get new node in the new workflow run
                new_node = await async_ops.get_workflow_node(
                    str(new_workflow_run.id), orig_node.node_id
                )

                # Copy status and results
                await async_ops.update_node_status(
                    new_node,
                    orig_node.status,
                    started_at=orig_node.started_at,
                    completed_at=orig_node.completed_at,
                    output_data=orig_node.output_data,
                )

                # Copy artifacts
                orig_artifacts = await async_ops.get_node_artifacts(orig_node)
                for artifact in orig_artifacts:
                    await async_ops.create_node_artifact(
                        new_node, artifact.name, artifact.inline_data
                    )

                # Copy logs
                orig_logs = orig_node.logs.all().order_by("timestamp")
                for log in orig_logs:
                    await async_ops.create_node_log(
                        new_node, log.level, f"[COPIED] {log.message}", log.context
                    )

        # Now execute the workflow from the target node
        # Initialize OpenAI client
        api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        client = OpenAI(api_key=api_key)

        # Build state with results from copied nodes
        state: PaperProcessingState = {
            "workflow_run_id": str(new_workflow_run.id),
            "paper_id": paper_id,
            "current_node_id": None,
            "client": client,
            "model": model,
            "force_reprocess": True,
            "paper_type_result": None,
            "code_availability_result": None,
            "code_reproducibility_result": None,
            "errors": [],
        }

        # Load previous results based on which node we're starting from
        if original_node.node_id in [
            "code_availability_check",
            "code_repository_analysis",
        ]:
            # Load paper_type_result
            paper_type_node = await async_ops.get_workflow_node(
                str(new_workflow_run.id), "paper_type_classification"
            )
            if paper_type_node and paper_type_node.status == "completed":
                artifacts = await async_ops.get_node_artifacts(paper_type_node)
                for artifact in artifacts:
                    if artifact.name == "result":
                        state["paper_type_result"] = PaperTypeClassification(
                            **artifact.inline_data
                        )
                        break

        if original_node.node_id == "code_repository_analysis":
            # Also load code_availability_result
            code_avail_node = await async_ops.get_workflow_node(
                str(new_workflow_run.id), "code_availability_check"
            )
            if code_avail_node and code_avail_node.status == "completed":
                artifacts = await async_ops.get_node_artifacts(code_avail_node)
                for artifact in artifacts:
                    if artifact.name == "result":
                        state["code_availability_result"] = CodeAvailabilityCheck(
                            **artifact.inline_data
                        )
                        break

        # Execute nodes from target node onwards
        if original_node.node_id == "paper_type_classification":
            # Execute all three nodes
            result1 = await paper_type_classification_node(state)
            if "paper_type_result" in result1:
                state["paper_type_result"] = result1["paper_type_result"]
            if "errors" in result1:
                state["errors"].extend(result1["errors"])

            result2 = await code_availability_check_node(state)
            if "code_availability_result" in result2:
                state["code_availability_result"] = result2["code_availability_result"]
            if "errors" in result2:
                state["errors"].extend(result2["errors"])

            result3 = await code_repository_analysis_node(state)
            if "code_reproducibility_result" in result3:
                state["code_reproducibility_result"] = result3[
                    "code_reproducibility_result"
                ]
            if "errors" in result3:
                state["errors"].extend(result3["errors"])

        elif original_node.node_id == "code_availability_check":
            # Execute code_availability_check and code_repository_analysis
            result1 = await code_availability_check_node(state)
            if "code_availability_result" in result1:
                state["code_availability_result"] = result1["code_availability_result"]
            if "errors" in result1:
                state["errors"].extend(result1["errors"])

            result2 = await code_repository_analysis_node(state)
            if "code_reproducibility_result" in result2:
                state["code_reproducibility_result"] = result2[
                    "code_reproducibility_result"
                ]
            if "errors" in result2:
                state["errors"].extend(result2["errors"])

        elif original_node.node_id == "code_repository_analysis":
            # Execute only code_repository_analysis
            result = await code_repository_analysis_node(state)
            if "code_reproducibility_result" in result:
                state["code_reproducibility_result"] = result[
                    "code_reproducibility_result"
                ]
            if "errors" in result:
                state["errors"].extend(result["errors"])

        # Check for errors
        errors = state.get("errors", [])
        success = len(errors) == 0

        # Update workflow run status
        await async_ops.update_workflow_run_status(
            new_workflow_run.id,
            "completed" if success else "failed",
            completed_at=timezone.now(),
            output_data={
                "success": success,
                "paper_type": (
                    state.get("paper_type_result").model_dump()
                    if state.get("paper_type_result")
                    else None
                ),
                "code_availability": (
                    state.get("code_availability_result").model_dump()
                    if state.get("code_availability_result")
                    else None
                ),
                "code_reproducibility": (
                    state.get("code_reproducibility_result").model_dump()
                    if state.get("code_reproducibility_result")
                    else None
                ),
            },
            error_message="; ".join(errors) if errors else None,
        )

        return {
            "success": success,
            "workflow_run_id": str(new_workflow_run.id),
            "run_number": new_workflow_run.run_number,
            "paper_id": paper_id,
            "started_from_node": original_node.node_id,
            "errors": errors,
        }

    except Exception as e:
        logger.error(f"Failed to execute workflow from node: {e}", exc_info=True)

        # Try to update workflow run status
        try:
            if "new_workflow_run" in locals():
                await async_ops.update_workflow_run_status(
                    new_workflow_run.id,
                    "failed",
                    completed_at=timezone.now(),
                    error_message=str(e),
                )
        except:
            pass

        return {"success": False, "error": str(e)}


async def process_paper_workflow(
    paper_id: int,
    force_reprocess: bool = False,
    openai_api_key: Optional[str] = None,
    model: str = "gpt-4o",
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Execute the complete paper processing workflow using workflow_engine.

    Args:
        paper_id: Database ID of paper to process
        force_reprocess: If True, reprocess even if already analyzed
        openai_api_key: OpenAI API key (uses env var if not provided)
        model: OpenAI model to use
        user_id: Optional user ID for tracking

    Returns:
        Dictionary with workflow results and statistics
    """
    logger.info(f"Starting paper processing workflow for paper ID {paper_id}")

    try:
        # Get or create workflow definition
        workflow_def = await async_ops.get_or_create_workflow_definition(
            name="reduced_paper_processing_pipeline",
            version=2,  # Version 2 with sequential 3-node architecture
            description="Three-node workflow: paper type classification, code availability check, and conditional code repository analysis",
            dag_structure={
                "nodes": [
                    {
                        "id": "paper_type_classification",
                        "type": "python",
                        "handler": "webApp.services.paper_processing_workflow.paper_type_classification_node",
                        "description": "Classify paper type (dataset/method/both/theoretical/unknown)",
                        "config": {},
                    },
                    {
                        "id": "code_availability_check",
                        "type": "python",
                        "handler": "webApp.services.paper_processing_workflow.code_availability_check_node",
                        "description": "Check if code repository exists (database/text/online search)",
                        "config": {},
                    },
                    {
                        "id": "code_repository_analysis",
                        "type": "python",
                        "handler": "webApp.services.paper_processing_workflow.code_repository_analysis_node",
                        "description": "Analyze repository and compute reproducibility score (conditional)",
                        "config": {},
                    },
                ],
                "edges": [
                    {
                        "from": "paper_type_classification",
                        "to": "code_availability_check",
                        "type": "sequential",
                    },
                    {
                        "from": "code_availability_check",
                        "to": "code_repository_analysis",
                        "type": "conditional",
                        "condition": "code_available AND paper_type NOT IN (theoretical, dataset)",
                    },
                ],
            },
        )

        # Create workflow run using orchestrator
        config = {"force_reprocess": force_reprocess, "model": model, "max_retries": 3}
        workflow_run = await async_ops.create_workflow_run_with_paper_id(
            workflow_name="reduced_paper_processing_pipeline",
            paper_id=paper_id,
            input_data=config,
        )

        # Update workflow run status to running
        await async_ops.update_workflow_run_status(
            workflow_run.id, "running", started_at=timezone.now()
        )

        # Initialize OpenAI client
        api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        client = OpenAI(api_key=api_key)

        # Initialize state
        initial_state: PaperProcessingState = {
            "workflow_run_id": str(workflow_run.id),
            "paper_id": paper_id,
            "current_node_id": None,
            "client": client,
            "model": model,
            "force_reprocess": force_reprocess,
            "paper_type_result": None,
            "code_availability_result": None,
            "code_reproducibility_result": None,
            "errors": [],
        }

        # Build and run workflow
        workflow = build_paper_processing_workflow()

        final_state = await workflow.ainvoke(initial_state)

        # Check for errors
        errors = final_state.get("errors", [])
        success = len(errors) == 0

        # Update workflow run status
        await async_ops.update_workflow_run_status(
            workflow_run.id,
            "completed" if success else "failed",
            completed_at=timezone.now(),
            output_data={
                "success": success,
                "paper_type": (
                    final_state.get("paper_type_result").model_dump()
                    if final_state.get("paper_type_result")
                    else None
                ),
                "code_availability": (
                    final_state.get("code_availability_result").model_dump()
                    if final_state.get("code_availability_result")
                    else None
                ),
                "code_reproducibility": (
                    final_state.get("code_reproducibility_result").model_dump()
                    if final_state.get("code_reproducibility_result")
                    else None
                ),
            },
            error_message="; ".join(errors) if errors else None,
        )

        # Get token usage from artifacts
        input_tokens, output_tokens = await async_ops.get_token_stats(
            str(workflow_run.id)
        )

        # Compile results
        results = {
            "success": success,
            "workflow_run_id": str(workflow_run.id),
            "run_number": workflow_run.run_number,
            "paper_id": paper_id,
            "paper_title": (await async_ops.get_paper(paper_id)).title,
            "paper_type": final_state.get("paper_type_result"),
            "code_availability": final_state.get("code_availability_result"),
            "code_reproducibility": final_state.get("code_reproducibility_result"),
            "total_input_tokens": input_tokens,
            "total_output_tokens": output_tokens,
            "errors": errors,
        }

        logger.info(
            f"Workflow run {workflow_run.id} completed. Status: {'success' if success else 'failed'}"
        )
        logger.info(f"Tokens used: {input_tokens} input, {output_tokens} output")

        return results

    except Exception as e:
        logger.error(f"Workflow execution failed: {e}", exc_info=True)

        # Try to update workflow run status
        try:
            if "workflow_run" in locals():
                await async_ops.update_workflow_run_status(
                    workflow_run.id,
                    "failed",
                    completed_at=timezone.now(),
                    error_message=str(e),
                )
        except:
            pass

        return {
            "success": False,
            "paper_id": paper_id,
            "error": str(e),
            "total_input_tokens": 0,
            "total_output_tokens": 0,
        }


# ============================================================================
# Convenience Functions
# ============================================================================


async def process_multiple_papers(
    paper_ids: List[int], force_reprocess: bool = False, max_concurrent: int = 3
) -> List[Dict[str, Any]]:
    """
    Process multiple papers concurrently.

    Args:
        paper_ids: List of paper IDs to process
        force_reprocess: If True, reprocess even if already analyzed
        max_concurrent: Maximum number of concurrent processing tasks

    Returns:
        List of results for each paper
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def process_with_limit(paper_id):
        async with semaphore:
            return await process_paper_workflow(paper_id, force_reprocess)

    tasks = [process_with_limit(pid) for pid in paper_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    return results
