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

from webApp.models import Paper
from workflow_engine.models import (
    WorkflowDefinition,
    WorkflowRun,
    WorkflowNode,
    NodeArtifact,
    NodeLog
)
from workflow_engine.services.async_orchestrator import async_ops

logger = logging.getLogger(__name__)


# ============================================================================
# Pydantic Models for Structured Outputs
# ============================================================================

class PaperTypeClassification(BaseModel):
    """Structured output for paper type classification."""
    model_config = ConfigDict(extra='forbid')
    
    paper_type: str = Field(
        description="Type of contribution: 'dataset', 'method', 'both', 'theoretical', or 'unknown'"
    )
    confidence: float = Field(
        description="Confidence score between 0 and 1",
        ge=0.0,
        le=1.0
    )
    reasoning: str = Field(
        description="Detailed reasoning for the classification decision"
    )
    key_evidence: List[str] = Field(
        description="Key quotes or evidence from the paper supporting the classification"
    )


class CodeAvailabilityCheck(BaseModel):
    """Structured output for code availability verification."""
    model_config = ConfigDict(extra='forbid')
    
    code_available: bool = Field(description="Whether actual code is available")
    code_url: Optional[str] = Field(description="URL to the code repository if found")
    found_online: bool = Field(
        description="Whether code was found online (not in original paper)"
    )
    availability_notes: str = Field(
        description="Notes about code availability (empty, unreachable, docs only, etc.)"
    )


class ResearchMethodologyAnalysis(BaseModel):
    """Analysis of research methodology type for context-aware scoring."""
    model_config = ConfigDict(extra='forbid')
    
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
    methodology_notes: str = Field(
        description="Notes about the research methodology"
    )


class RepositoryStructureAnalysis(BaseModel):
    """Analysis of repository structure and dependencies."""
    model_config = ConfigDict(extra='forbid')
    
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
    model_config = ConfigDict(extra='forbid')
    
    has_training_code: bool = Field(description="Training code available")
    training_code_paths: List[str] = Field(
        description="Paths to training code files"
    )
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
    model_config = ConfigDict(extra='forbid')
    
    has_checkpoints: bool = Field(description="Model checkpoints are released")
    checkpoint_locations: List[str] = Field(
        description="URLs or paths to checkpoints"
    )
    has_dataset_links: bool = Field(description="Dataset download links available")
    dataset_coverage: str = Field(
        description="'full', 'partial', or 'none' - coverage of dataset links"
    )
    dataset_links: List[Dict[str, str]] = Field(
        description="List of dataset names and their download URLs"
    )


class DatasetSplitsAnalysis(BaseModel):
    """Analysis of dataset splits and experiment replicability."""
    model_config = ConfigDict(extra='forbid')
    
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
    model_config = ConfigDict(extra='forbid')
    
    has_readme: bool = Field(description="README file exists")
    has_results_table: bool = Field(
        description="README includes results table"
    )
    has_reproduction_commands: bool = Field(
        description="README includes precise commands to reproduce results"
    )
    documentation_notes: str = Field(
        description="Notes about documentation quality"
    )


class CodeReproducibilityAnalysis(BaseModel):
    """Complete code reproducibility analysis artifact."""
    model_config = ConfigDict(extra='forbid')
    
    analysis_timestamp: str = Field(description="ISO timestamp of analysis")
    code_availability: CodeAvailabilityCheck
    research_methodology: Optional[ResearchMethodologyAnalysis] = None
    repository_structure: Optional[RepositoryStructureAnalysis] = None
    code_components: Optional[CodeAvailabilityAnalysis] = None
    artifacts: Optional[ArtifactsAnalysis] = None
    dataset_splits: Optional[DatasetSplitsAnalysis] = None
    documentation: Optional[ReproducibilityDocumentation] = None
    reproducibility_score: float = Field(
        description="Computed reproducibility score (0-10)",
        ge=0.0,
        le=10.0
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
    documentation: Optional[ReproducibilityDocumentation]
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
        "code_completeness": 0.0,       # 2.5-3.0 points (adaptive)
        "dependencies": 0.0,            # 1.0 points
        "artifacts": 0.0,               # 0-2.5 points (adaptive)
        "dataset_splits": 0.0,          # 0-2.0 points (adaptive)
        "documentation": 0.0            # 2.0 points
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
                    recommendations.append("Add training code to enable full reproducibility")
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
                recommendations.append(f"Provide implementation code for the {method_type} method")
        
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
                recommendations.append("Fix dependencies file - some imports are missing")
            else:
                breakdown["dependencies"] = 0.7
        else:
            recommendations.append("Add requirements/dependencies file with all necessary packages and versions")
    
    # 3. Artifacts (0-2.5 points, adaptive)
    if requires_datasets or requires_training:
        if artifacts:
            # Checkpoints: 0-1.0 point (only for models)
            if requires_training:
                if artifacts.has_checkpoints:
                    breakdown["artifacts"] += 1.0
                else:
                    recommendations.append("Release model checkpoints to enable result verification without retraining")
            
            # Dataset links: 0-1.5 points (weighted by coverage)
            if requires_datasets:
                if artifacts.has_dataset_links:
                    if artifacts.dataset_coverage == "full":
                        breakdown["artifacts"] += 1.5
                    elif artifacts.dataset_coverage == "partial":
                        breakdown["artifacts"] += 0.8
                        recommendations.append("Provide download links for ALL datasets used")
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
        if components and (components.has_evaluation_code or components.has_training_code):
            breakdown["artifacts"] = 2.0  # Full credit for complete implementation
    
    # 4. Dataset Splits (0-2.0 points, adaptive) - CRITICAL for ML, less for others
    if requires_splits:
        if dataset_splits:
            score = 0.0
            if dataset_splits.splits_specified:
                score += 0.7
            else:
                recommendations.append("Specify which dataset splits (train/val/test) were used")
            
            if dataset_splits.splits_provided:
                score += 0.7
            else:
                recommendations.append("Provide split files or explicit split logic")
            
            if dataset_splits.random_seeds_documented:
                score += 0.6
            else:
                recommendations.append("Document random seeds for reproducible data partitioning")
            
            breakdown["dataset_splits"] = score
        else:
            recommendations.append("Document dataset splits and random seeds for experiment replicability")
    else:
        # Non-ML: Award points if seeds/parameters are documented
        if dataset_splits and dataset_splits.random_seeds_documented:
            breakdown["dataset_splits"] = 1.5  # Reward for documenting randomness
            recommendations.append("Continue documenting all sources of randomness")
        else:
            breakdown["dataset_splits"] = 0.5  # Partial credit for deterministic methods
            if method_type in ["simulation", "algorithm"]:
                recommendations.append("Document random seeds and parameters for reproducible results")
    
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
        recommendations.append("Add comprehensive documentation with results and reproduction steps")
    
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
    total_score = (raw_score / max_possible_score) * 10.0 if max_possible_score > 0 else 0.0
    
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
    logger.info(f"Node A: Starting paper type classification for paper {state['paper_id']}")
    
    # Get workflow node
    node = await async_ops.get_workflow_node(state['workflow_run_id'], node_id)
    
    # Update node status to running
    await async_ops.update_node_status(node, 'running', started_at=timezone.now())
    await async_ops.create_node_log(node, 'INFO', 'Starting paper type classification')
    
    try:
        # Check for force_reprocess flag
        force_reprocess = state.get('force_reprocess', False)
        
        # Check if already classified
        if not force_reprocess:
            previous = await async_ops.check_previous_analysis(state['paper_id'], node_id)
            if previous:
                logger.info(f"Found previous analysis from {previous['completed_at']}")
                await async_ops.create_node_log(node, 'INFO', f"Using cached result from run {previous['run_id']}")
                
                result = PaperTypeClassification(**previous['result'])
                await async_ops.create_node_artifact(node, 'result', result)
                await async_ops.update_node_status(node, 'completed', completed_at=timezone.now())
                
                return {"paper_type_result": result}
        
        # Get paper from database
        paper = await async_ops.get_paper(state['paper_id'])
        
        # Use title + abstract for efficiency (or full text if abstract unavailable)
        if paper.abstract:
            paper_content = f"Title: {paper.title}\n\nAbstract: {paper.abstract}"
        elif paper.text:
            # Use first 3000 characters of full text if no abstract
            paper_content = f"Title: {paper.title}\n\nText excerpt:\n{paper.text[:3000]}"
        else:
            paper_content = f"Title: {paper.title}\n\n(No abstract or full text available)"
        
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
        await async_ops.create_node_log(node, 'INFO', f'Analyzing paper with {state["model"]}', {
            'paper_id': state['paper_id'],
            'has_abstract': bool(paper.abstract),
            'content_length': len(paper_content)
        })
        
        # Call OpenAI API
        response = state['client'].chat.completions.create(
            model=state['model'],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_schema", "json_schema": {
                "name": "paper_type_classification",
                "strict": True,
                "schema": PaperTypeClassification.model_json_schema()
            }},
            temperature=0.3
        )
        
        # Parse response
        result_dict = json.loads(response.choices[0].message.content)
        result = PaperTypeClassification(**result_dict)
        
        # Track tokens
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens
        
        logger.info(f"Classification result: {result.paper_type} (confidence: {result.confidence})")
        logger.info(f"Reasoning: {result.reasoning}")
        
        # Store result as artifact
        await async_ops.create_node_artifact(node, 'result', result)
        await async_ops.create_node_artifact(node, 'token_usage', {
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'total_tokens': input_tokens + output_tokens
        })
        
        # Log success
        await async_ops.create_node_log(node, 'INFO', f'Classification successful: {result.paper_type}', {
            'confidence': result.confidence,
            'tokens_used': input_tokens + output_tokens
        })
        
        # Update node status
        await async_ops.update_node_status(
            node,
            'completed',
            completed_at=timezone.now(),
            output_data={'paper_type': result.paper_type, 'confidence': result.confidence}
        )
        
        return {"paper_type_result": result}
        
    except Exception as e:
        logger.error(f"Error in paper type classification: {e}", exc_info=True)
        
        # Log error
        await async_ops.create_node_log(node, 'ERROR', str(e), {'traceback': str(e.__traceback__)})
        
        # Update node status to failed
        await async_ops.update_node_status(
            node,
            'failed',
            completed_at=timezone.now(),
            error_message=str(e)
        )
        
        return {
            "errors": state.get('errors', []) + [f"Node A error: {str(e)}"]
        }


# ============================================================================
# Node B: Code Reproducibility Analysis (Agentic)
# ============================================================================

async def code_reproducibility_analysis_node(state: PaperProcessingState) -> Dict[str, Any]:
    """
    Node B: Agentic code reproducibility analysis.
    
    This node performs comprehensive analysis of code availability and reproducibility.
    It works in multiple steps:
    1. Check if code links exist in paper
    2. If not, search online for code
    3. Download and analyze repository
    4. Evaluate reproducibility components
    
    Results are stored as NodeArtifacts.
    """
    node_id = "code_reproducibility_analysis"
    logger.info(f"Node B: Starting code reproducibility analysis for paper {state['paper_id']}")
    
    # Get workflow node
    node = await async_ops.get_workflow_node(state['workflow_run_id'], node_id)
    
    # Update node status to running
    await async_ops.update_node_status(node, 'running', started_at=timezone.now())
    await async_ops.create_node_log(node, 'INFO', 'Starting code reproducibility analysis')
    
    try:
        # Check for previous analysis
        force_reprocess = state.get('force_reprocess', False)
        if not force_reprocess:
            previous = await async_ops.check_previous_analysis(state['paper_id'], node_id)
            if previous:
                logger.info(f"Found previous code analysis from {previous['completed_at']}")
                await async_ops.create_node_log(node, 'INFO', f"Using cached result from run {previous['run_id']}")
                
                result = CodeReproducibilityAnalysis(**previous['result'])
                await async_ops.create_node_artifact(node, 'result', result)
                await async_ops.update_node_status(node, 'completed', completed_at=timezone.now())
                
                return {"code_reproducibility_result": result}
        
        paper = await async_ops.get_paper(state['paper_id'])
        client = state['client']
        model = state['model']
        
        # Check paper type from Node A - theoretical papers don't need code analysis
        paper_type_result = state.get('paper_type_result')
        if paper_type_result and paper_type_result.paper_type == 'theoretical':
            logger.info("Paper classified as theoretical - code analysis not applicable")
            
            # Theoretical papers don't require executable code
            analysis = CodeReproducibilityAnalysis(
                analysis_timestamp=datetime.utcnow().isoformat(),
                code_availability=CodeAvailabilityCheck(
                    code_available=False,
                    code_url=None,
                    found_online=False,
                    availability_notes="Theoretical paper - code analysis not applicable. This paper presents theoretical contributions where executable code is not expected."
                ),
                research_methodology=ResearchMethodologyAnalysis(
                    methodology_type="theoretical",
                    requires_training=False,
                    requires_datasets=False,
                    requires_splits=False,
                    methodology_notes=paper_type_result.reasoning
                ),
                reproducibility_score=10.0,  # Perfect score - no code needed for theoretical work
                score_breakdown={},
                overall_assessment=f"Code reproducibility analysis not applicable. This is a theoretical paper where executable code is not expected. {paper_type_result.reasoning}",
                recommendations=[]
            )
            
            await async_ops.create_node_artifact(node, 'result', analysis)
            await async_ops.create_node_log(node, 'INFO', 'Theoretical paper - code analysis skipped')
            await async_ops.update_node_status(node, 'completed', completed_at=timezone.now())
            
            return {"code_reproducibility_result": analysis}
        
        if paper_type_result and paper_type_result.paper_type == 'dataset':
            logger.info("Paper classified as dataset-only - code analysis not applicable")
            
            # Dataset papers are evaluated differently
            analysis = CodeReproducibilityAnalysis(
                analysis_timestamp=datetime.utcnow().isoformat(),
                code_availability=CodeAvailabilityCheck(
                    code_available=False,
                    code_url=None,
                    found_online=False,
                    availability_notes="Dataset paper - code analysis not applicable. Dataset papers should be evaluated on dataset availability, documentation, and ethical considerations."
                ),
                research_methodology=ResearchMethodologyAnalysis(
                    methodology_type="data_analysis",
                    requires_training=False,
                    requires_datasets=True,
                    requires_splits=False,
                    methodology_notes="Dataset paper - focus on data availability, documentation quality, and reproducibility of data collection/preprocessing rather than code."
                ),
                reproducibility_score=0.0,
                score_breakdown={},
                overall_assessment="Dataset paper - code reproducibility analysis not applicable. These papers should be evaluated on dataset accessibility, documentation quality, format specifications, collection methodology, and ethical considerations.",
                recommendations=[
                    "Ensure dataset is publicly accessible or access instructions are clear",
                    "Provide comprehensive dataset documentation (format, statistics, collection methodology)",
                    "Document any preprocessing or filtering steps with reproducible scripts",
                    "Include ethical considerations and usage guidelines",
                    "Provide dataset versioning and persistent identifiers (e.g., DOI)"
                ]
            )
            
            await async_ops.create_node_artifact(node, 'result', analysis)
            await async_ops.create_node_log(node, 'INFO', 'Dataset paper - code analysis skipped')
            await async_ops.update_node_status(node, 'completed', completed_at=timezone.now())
            
            return {"code_reproducibility_result": analysis}
        
        # Step 1: Check for code links
        await async_ops.create_node_log(node, 'INFO', 'Checking for code links')
        code_url = await check_code_availability(paper, client, model)
        
        if not code_url:
            # No code found - finalize analysis
            analysis = CodeReproducibilityAnalysis(
                analysis_timestamp=datetime.utcnow().isoformat(),
                code_availability=CodeAvailabilityCheck(
                    code_available=False,
                    code_url=None,
                    found_online=False,
                    availability_notes="No code repository found in paper or online"
                ),
                reproducibility_score=0.0,
                score_breakdown={},
                overall_assessment="Code not available - reproducibility cannot be assessed",
                recommendations=[
                    "Authors should release code to enable reproducibility",
                    "Consider reaching out to authors for code access"
                ]
            )
            
            await async_ops.create_node_artifact(node, 'result', analysis)
            await async_ops.create_node_log(node, 'WARNING', 'No code repository found')
            await async_ops.update_node_status(node, 'completed', completed_at=timezone.now())
            
            return {"code_reproducibility_result": analysis}
        
        # Step 2: Verify code is actually available (not empty/unreachable)
        await async_ops.create_node_log(node, 'INFO', f'Verifying code accessibility: {code_url}')
        code_check_result = await verify_code_accessibility(code_url, client, model)
        
        if not code_check_result['accessible']:
            analysis = CodeReproducibilityAnalysis(
                analysis_timestamp=datetime.utcnow().isoformat(),
                code_availability=CodeAvailabilityCheck(
                    code_available=False,
                    code_url=code_url,
                    found_online=code_check_result.get('found_online', False),
                    availability_notes=code_check_result['notes']
                ),
                reproducibility_score=0.0,
                score_breakdown={},
                overall_assessment=f"Code repository exists but is not accessible: {code_check_result['notes']}",
                recommendations=["Verify repository permissions and accessibility"]
            )
            
            await async_ops.create_node_artifact(node, 'result', analysis)
            await async_ops.create_node_log(node, 'WARNING', code_check_result['notes'])
            await async_ops.update_node_status(node, 'completed', completed_at=timezone.now())
            
            return {"code_reproducibility_result": analysis}
        
        # Step 3: Download and analyze repository
        logger.info(f"Downloading repository: {code_url}")
        await async_ops.create_node_log(node, 'INFO', f'Downloading and analyzing repository: {code_url}')
        
        repo_analysis = await analyze_repository_comprehensive(
            code_url, 
            paper,
            client, 
            model,
            node  # Pass node for detailed logging
        )
        
        # Step 4: Compile complete analysis
        analysis = CodeReproducibilityAnalysis(
            analysis_timestamp=datetime.utcnow().isoformat(),
            code_availability=CodeAvailabilityCheck(
                code_available=True,
                code_url=code_url,
                found_online=code_check_result.get('found_online', False),
                availability_notes="Code repository accessible and contains actual code"
            ),
            research_methodology=repo_analysis.get('methodology'),
            repository_structure=repo_analysis.get('structure'),
            code_components=repo_analysis.get('components'),
            artifacts=repo_analysis.get('artifacts'),
            dataset_splits=repo_analysis.get('dataset_splits'),
            documentation=repo_analysis.get('documentation'),
            reproducibility_score=repo_analysis.get('reproducibility_score', 0.0),
            score_breakdown=repo_analysis.get('score_breakdown', {}),
            overall_assessment=repo_analysis.get('overall_assessment', ''),
            recommendations=repo_analysis.get('recommendations', [])
        )
        
        # Store as artifacts
        await async_ops.create_node_artifact(node, 'result', analysis)
        await async_ops.create_node_artifact(node, 'token_usage', {
            'input_tokens': repo_analysis.get('input_tokens', 0),
            'output_tokens': repo_analysis.get('output_tokens', 0)
        })
        
        # Store detailed LLM analysis if available
        if repo_analysis.get('llm_analysis_text'):
            await async_ops.create_node_artifact(node, 'llm_analysis', {
                'analysis_text': repo_analysis['llm_analysis_text'],
                'structured_data': repo_analysis.get('structured_data', {})
            })
        
        # Log detailed results
        await async_ops.create_node_log(
            node, 
            'INFO', 
            f'Analysis complete - Score: {analysis.reproducibility_score}/10',
            {'score_breakdown': analysis.score_breakdown}
        )
        
        # Log detailed component availability
        components_summary = []
        if analysis.code_components:
            components_summary.append(f"Training code: {analysis.code_components.has_training_code}")
            components_summary.append(f"Evaluation code: {analysis.code_components.has_evaluation_code}")
            components_summary.append(f"Documented commands: {analysis.code_components.has_documented_commands}")
        if analysis.artifacts:
            components_summary.append(f"Checkpoints available: {analysis.artifacts.has_checkpoints}")
            components_summary.append(f"Dataset links: {analysis.artifacts.has_dataset_links}")
        if analysis.documentation:
            components_summary.append(f"README: {analysis.documentation.has_readme}")
            components_summary.append(f"Results table: {analysis.documentation.has_results_table}")
            
        if components_summary:
            await async_ops.create_node_log(node, 'INFO', 'Component availability:\n' + '\n'.join(f'  • {item}' for item in components_summary))
        
        # Update node status
        await async_ops.update_node_status(
            node,
            'completed',
            completed_at=timezone.now(),
            output_data={'code_available': True, 'code_url': code_url}
        )
        
        return {"code_reproducibility_result": analysis}
        
    except Exception as e:
        logger.error(f"Error in code reproducibility analysis: {e}", exc_info=True)
        return {
            "errors": state['errors'] + [f"Node B error: {str(e)}"]
        }


async def check_code_availability(paper: Paper, client: OpenAI, model: str) -> Optional[str]:
    """
    Check if paper has code links in database or search online.
    
    Supports multiple git hosting platforms:
    - GitHub
    - GitLab
    - Bitbucket
    - And other common git hosting services
    
    Returns:
        Code URL if found, None otherwise
    """
    # First check database
    if paper.code_url:
        logger.info(f"Found code URL in database: {paper.code_url}")
        return paper.code_url
    
    # Search in paper text for git repository links (GitHub, GitLab, Bitbucket, etc.)
    if paper.text:
        # Pattern matches: github.com, gitlab.com, bitbucket.org, and other git hosting services
        url_pattern = r'https?://(?:github\.com|gitlab\.com|bitbucket\.org|gitee\.com|codeberg\.org)/[\w\-]+/[\w\-]+'
        matches = re.findall(url_pattern, paper.text)
        if matches:
            logger.info(f"Found code URL in paper text: {matches[0]}")
            return matches[0]
    
    # Use LLM to search online (simulated - in production use search API)
    logger.info("No code URL found in database or paper. Attempting online search...")
    
    # In production, you would use actual search API here
    # For now, we'll use LLM to suggest likely repository URL
    try:
        search_prompt = f"""Given this paper title and abstract, suggest the most likely code repository URL if it exists.
Look for repositories on GitHub, GitLab, Bitbucket, or any other git hosting platform.
If you cannot confidently identify a repository, return null.

Paper Title: {paper.title}
Abstract: {paper.abstract or 'Not available'}

Respond with ONLY the repository URL or 'null' (no quotes, no explanation)."""

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a research code finder. Respond only with repository URLs or 'null'."},
                {"role": "user", "content": search_prompt}
            ],
            temperature=0.0,
            max_tokens=100
        )
        
        result = response.choices[0].message.content.strip()
        
        # Accept any git hosting platform URL
        git_platforms = ['github.com', 'gitlab.com', 'bitbucket.org', 'gitee.com', 'codeberg.org']
        if result and result.lower() != 'null' and any(platform in result for platform in git_platforms):
            logger.info(f"LLM suggested repository: {result}")
            return result
            
    except Exception as e:
        logger.warning(f"Error in online search: {e}")
    
    return None


async def verify_code_accessibility(code_url: str, client: OpenAI, model: str) -> Dict[str, Any]:
    """
    Verify that code repository is accessible and contains actual code.
    
    Returns:
        Dict with 'accessible' bool, 'notes' str, and token counts
    """
    try:
        # Try to fetch repository info
        logger.info(f"Verifying accessibility of {code_url}")
        
        # Check if URL is reachable
        response = requests.head(code_url, timeout=10, allow_redirects=True)
        
        if response.status_code == 404:
            return {
                'accessible': False,
                'notes': 'Repository not found (404)',
                'found_online': False
            }
        elif response.status_code >= 400:
            return {
                'accessible': False,
                'notes': f'Repository not accessible (HTTP {response.status_code})',
                'found_online': False
            }
        
        # Try to ingest a small sample to verify it contains code
        try:
            summary, tree, content = await ingest_async(
                code_url,
                max_file_size=50000,  # Limit file size
                include_patterns=["*.py", "*.js", "*.ts", "*.java", "*.cpp", "*.c", "*.m", "README*"]
            )
            
            # Check if we got actual code (not just documentation)
            if not content or len(content) < 100:
                return {
                    'accessible': False,
                    'notes': 'Repository is empty or contains only documentation',
                    'found_online': True
                }
            
            # Check if it's mostly code vs just README
            # Supports: Python, JavaScript, TypeScript, Java, C++, C, Go, Rust, Matlab
            code_extensions = ['.py', '.js', '.ts', '.java', '.cpp', '.c', '.go', '.rs', '.m']
            has_code_files = any(ext in content for ext in code_extensions)
            
            if not has_code_files:
                return {
                    'accessible': False,
                    'notes': 'Repository contains no recognizable code files',
                    'found_online': True
                }
            
            logger.info("Repository is accessible and contains code")
            return {
                'accessible': True,
                'notes': 'Repository verified accessible with code',
                'found_online': False
            }
            
        except Exception as e:
            logger.warning(f"Error ingesting repository: {e}")
            return {
                'accessible': False,
                'notes': f'Error accessing repository content: {str(e)}',
                'found_online': False
            }
            
    except requests.Timeout:
        return {
            'accessible': False,
            'notes': 'Repository request timed out',
            'found_online': False
        }
    except Exception as e:
        return {
            'accessible': False,
            'notes': f'Error checking repository: {str(e)}',
            'found_online': False
        }


async def analyze_repository_comprehensive(
    code_url: str,
    paper: Paper,
    client: OpenAI,
    model: str,
    node: 'WorkflowNode' = None  # Optional node for detailed logging
) -> Dict[str, Any]:
    """
    Perform comprehensive analysis of code repository.
    
    This is the main agentic analysis function that evaluates all reproducibility criteria.
    """
    logger.info(f"Starting comprehensive repository analysis for {code_url}")
    if node:
        await async_ops.create_node_log(node, 'INFO', 'Starting comprehensive repository analysis')
    
    try:
        # Download repository content using gitingest
        if node:
            await async_ops.create_node_log(node, 'INFO', 'Downloading repository files...')
            
        summary, tree, content = await ingest_async(
            code_url,
            max_file_size=100000,
            include_patterns=["*.py", "*.js", "*.ts", "*.java", "*.cpp", "*.c", "*.m", "*.sh", 
                             "*.md", "*.txt", "*.yml", "*.yaml", "*.json", "requirements*", 
                             "setup.py", "package.json", "Dockerfile", "README*"]
        )
        
        content_size_kb = len(content) / 1024
        logger.info(f"Repository ingested. Content size: {len(content)} chars ({content_size_kb:.1f} KB)")
        if node:
            # Count files in tree
            file_count = tree.count('├──') + tree.count('└──')
            await async_ops.create_node_log(
                node, 
                'INFO', 
                f'Repository downloaded: {file_count} files, {content_size_kb:.1f} KB'
            )
        
        # Prepare paper text (truncate if too long to avoid token limits)
        paper_text = paper.text or ''
        max_paper_chars = 10000
        if len(paper_text) > max_paper_chars:
            paper_text = paper_text[:max_paper_chars] + "\n\n[... text truncated for brevity ...]"
            if node:
                await async_ops.create_node_log(
                    node, 
                    'INFO', 
                    f'Paper text truncated to {max_paper_chars} chars for analysis'
                )
        
        # Use LLM to analyze repository structure and contents
        analysis_prompt = f"""You are an expert code reviewer analyzing a research code repository for reproducibility.

Repository: {code_url}

Repository Structure:
{tree}

Code Summary:
{summary}

Paper Information:
Title: {paper.title}
Abstract: {paper.abstract or 'Not available'}

Paper Text (excerpt):
{paper_text if paper_text else 'Not available'}

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
            await async_ops.create_node_log(node, 'INFO', 'Analyzing repository with LLM...')

        # Call LLM with structured output
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are an expert code reproducibility analyst. Provide detailed, evidence-based analysis."},
                {"role": "user", "content": analysis_prompt}
            ],
            temperature=0.3,
            max_tokens=4000
        )
        
        # Parse LLM response
        analysis_text = response.choices[0].message.content
        
        logger.info(f"LLM analysis received ({len(analysis_text)} chars)")
        if node:
            # Save detailed analysis text
            await async_ops.create_node_log(
                node, 
                'INFO', 
                f'LLM analysis complete ({len(analysis_text)} chars, {response.usage.completion_tokens} tokens)'
            )
            # Log a preview of the analysis
            preview = analysis_text[:500] + '...' if len(analysis_text) > 500 else analysis_text
            await async_ops.create_node_log(node, 'DEBUG', f'Analysis preview:\n{preview}')
        
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
            await async_ops.create_node_log(node, 'INFO', 'Structuring analysis into schema...')
            
        structured_response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a JSON conversion specialist. Convert the analysis to the exact JSON schema provided. Include ALL required fields."},
                {"role": "user", "content": structuring_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=2000
        )
        
        structured_data = json.loads(structured_response.choices[0].message.content)
        
        # Log the structured data for debugging
        logger.info(f"Structured extraction completed. Keys: {list(structured_data.keys())}")
        if node:
            await async_ops.create_node_log(
                node, 
                'INFO', 
                f'Structured data extracted: {len(structured_data)} top-level fields'
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
        methodology_obj = safe_model_create(ResearchMethodologyAnalysis, structured_data.get('methodology'))
        structure_obj = safe_model_create(RepositoryStructureAnalysis, structured_data.get('structure'))
        components_obj = safe_model_create(CodeAvailabilityAnalysis, structured_data.get('components'))
        artifacts_obj = safe_model_create(ArtifactsAnalysis, structured_data.get('artifacts'))
        dataset_splits_obj = safe_model_create(DatasetSplitsAnalysis, structured_data.get('dataset_splits'))
        documentation_obj = safe_model_create(ReproducibilityDocumentation, structured_data.get('documentation'))
        
        # Compute reproducibility score programmatically
        if node:
            await async_ops.create_node_log(node, 'INFO', 'Computing reproducibility score...')
            
        score, breakdown, recommendations = compute_reproducibility_score(
            methodology_obj,
            structure_obj,
            components_obj,
            artifacts_obj,
            dataset_splits_obj,
            documentation_obj
        )
        
        logger.info(f"Computed reproducibility score: {score}/10")
        logger.info(f"Score breakdown: {breakdown}")
        if node:
            breakdown_text = '\n'.join(f'  • {k}: {v}/10' for k, v in breakdown.items())
            await async_ops.create_node_log(
                node, 
                'INFO', 
                f'Reproducibility score: {score}/10\n\nBreakdown:\n{breakdown_text}'
            )
            
            # Log key findings
            if recommendations:
                rec_preview = '\n'.join(f'  • {r}' for r in recommendations[:3])
                await async_ops.create_node_log(
                    node, 
                    'INFO', 
                    f'Top recommendations:\n{rec_preview}{"\n  ..." if len(recommendations) > 3 else ""}'
                )
        
        result = {
            'methodology': methodology_obj,
            'structure': structure_obj,
            'components': components_obj,
            'artifacts': artifacts_obj,
            'dataset_splits': dataset_splits_obj,
            'documentation': documentation_obj,
            'reproducibility_score': score,
            'score_breakdown': breakdown,
            'overall_assessment': structured_data.get('overall_assessment', 'Analysis completed'),
            'recommendations': recommendations,  # Programmatically generated
            'input_tokens': response.usage.prompt_tokens + structured_response.usage.prompt_tokens,
            'output_tokens': response.usage.completion_tokens + structured_response.usage.completion_tokens,
            'llm_analysis_text': analysis_text,  # Store full LLM analysis
            'structured_data': structured_data  # Store structured JSON
        }
        
        logger.info("Comprehensive repository analysis complete")
        return result
        
    except Exception as e:
        logger.error(f"Error in comprehensive repository analysis: {e}", exc_info=True)
        
        # Return minimal analysis on error
        return {
            'structure': None,
            'components': None,
            'artifacts': None,
            'dataset_splits': None,
            'documentation': None,
            'reproducibility_score': 0.0,
            'score_breakdown': {},
            'overall_assessment': f'Analysis failed: {str(e)}',
            'recommendations': ['Manual review required due to analysis error'],
            'input_tokens': 0,
            'output_tokens': 0
        }


# ============================================================================
# Workflow Definition and Execution  
# ============================================================================

def build_paper_processing_workflow() -> StateGraph:
    """Build the LangGraph workflow for paper processing."""
    
    workflow = StateGraph(PaperProcessingState)
    
    # Add nodes
    workflow.add_node("paper_type_classification", paper_type_classification_node)
    workflow.add_node("code_reproducibility_analysis", code_reproducibility_analysis_node)
    
    # Define edges
    workflow.set_entry_point("paper_type_classification")
    workflow.add_edge("paper_type_classification", "code_reproducibility_analysis")
    workflow.add_edge("code_reproducibility_analysis", END)
    
    return workflow.compile()


async def execute_single_node_only(
    node_uuid: str,
    force_reprocess: bool = True,
    openai_api_key: Optional[str] = None,
    model: str = "gpt-4o"
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
        
        logger.info(f"Node {node_uuid} current status: {node.status}, node_id: {node.node_id}")
        
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
            "code_reproducibility_result": None,
            "errors": []
        }
        
        logger.info(f"Loading dependencies for node {node.node_id}")
        
        # Load previous node results if they exist
        if node.node_id == "code_reproducibility_analysis":
            # Need paper_type_result from previous node
            prev_node = await async_ops.get_workflow_node(str(workflow_run.id), "paper_type_classification")
            if prev_node and prev_node.status == 'completed':
                # Get the result artifact
                artifacts = await async_ops.get_node_artifacts(prev_node)
                for artifact in artifacts:
                    if artifact.name == 'result':
                        state["paper_type_result"] = PaperTypeClassification(**artifact.data)
                        logger.info(f"Loaded paper_type_result from previous node: {state['paper_type_result'].paper_type}")
                        break
        
        logger.info(f"Executing node function for {node.node_id}")
        
        # Execute the appropriate node function
        if node.node_id == "paper_type_classification":
            result = await paper_type_classification_node(state)
        elif node.node_id == "code_reproducibility_analysis":
            result = await code_reproducibility_analysis_node(state)
        else:
            raise ValueError(f"Unknown node type: {node.node_id}")
        
        logger.info(f"Node function executed, result keys: {result.keys()}")
        
        # Check for errors
        errors = result.get("errors", [])
        success = len(errors) == 0
        
        logger.info(f"Single node execution completed. Success: {success}, Errors: {errors}")
        
        # Check if all nodes in the workflow are completed to update workflow run status
        try:
            # Get all nodes in this workflow run
            all_nodes = await async_ops.get_workflow_nodes(str(workflow_run.id))
            
            # Check statuses
            all_completed_or_failed = all(n.status in ['completed', 'failed'] for n in all_nodes)
            any_failed = any(n.status == 'failed' for n in all_nodes)
            
            if all_completed_or_failed:
                # All nodes finished, update workflow run status
                workflow_status = 'failed' if any_failed else 'completed'
                await async_ops.update_workflow_run_status(
                    workflow_run.id,
                    workflow_status,
                    completed_at=timezone.now()
                )
                logger.info(f"Workflow run {workflow_run.id} updated to status: {workflow_status}")
        except Exception as e:
            logger.warning(f"Failed to update workflow run status after node execution: {e}")
        
        return {
            "success": success,
            "node_id": node.node_id,
            "node_uuid": str(node.id),
            "workflow_run_id": str(workflow_run.id),
            "errors": errors
        }
        
    except Exception as e:
        logger.error(f"Failed to execute single node: {e}", exc_info=True)
        # Try to update node status to failed
        try:
            node = await async_ops.get_node_by_uuid(node_uuid)
            if node:
                await async_ops.update_node_status(
                    node,
                    'failed',
                    completed_at=timezone.now(),
                    error_message=str(e)
                )
                await async_ops.create_node_log(node, 'ERROR', f'Node execution failed: {str(e)}')
                
                # Also check if workflow should be marked as failed
                try:
                    all_nodes = await async_ops.get_workflow_nodes(str(node.workflow_run.id))
                    all_completed_or_failed = all(n.status in ['completed', 'failed'] for n in all_nodes)
                    if all_completed_or_failed:
                        await async_ops.update_workflow_run_status(
                            node.workflow_run.id,
                            'failed',
                            completed_at=timezone.now(),
                            error_message=str(e)
                        )
                        logger.info(f"Workflow run {node.workflow_run.id} updated to 'failed'")
                except Exception as inner_inner_e:
                    logger.error(f"Failed to update workflow status: {inner_inner_e}")
        except Exception as inner_e:
            logger.error(f"Failed to update node status after error: {inner_e}", exc_info=True)
        
        return {
            "success": False,
            "error": str(e)
        }


async def execute_workflow_from_node(
    node_uuid: str,
    openai_api_key: Optional[str] = None,
    model: str = "gpt-4o"
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
            'force_reprocess': True,
            'model': model,
            'max_retries': 3,
            'start_from_node': original_node.node_id
        }
        new_workflow_run = await async_ops.create_workflow_run_with_paper_id(
            workflow_name=workflow_def.name,
            paper_id=paper_id,
            input_data=config
        )
        
        # Update workflow run status to running
        await async_ops.update_workflow_run_status(
            new_workflow_run.id,
            'running',
            started_at=timezone.now()
        )
        
        # Get all nodes from the original workflow run
        original_nodes = await async_ops.get_workflow_nodes(str(original_workflow_run.id))
        
        # Determine which nodes come before the target node based on DAG
        dag_structure = workflow_def.dag_structure
        nodes_order = [n['id'] for n in dag_structure.get('nodes', [])]
        target_node_index = nodes_order.index(original_node.node_id) if original_node.node_id in nodes_order else -1
        
        # Copy results from nodes that come before the target node
        for orig_node in original_nodes:
            if nodes_order.index(orig_node.node_id) < target_node_index:
                # Get new node in the new workflow run
                new_node = await async_ops.get_workflow_node(str(new_workflow_run.id), orig_node.node_id)
                
                # Copy status and results
                await async_ops.update_node_status(
                    new_node,
                    orig_node.status,
                    started_at=orig_node.started_at,
                    completed_at=orig_node.completed_at,
                    output_data=orig_node.output_data
                )
                
                # Copy artifacts
                orig_artifacts = await async_ops.get_node_artifacts(orig_node)
                for artifact in orig_artifacts:
                    await async_ops.create_node_artifact(new_node, artifact.name, artifact.data)
                
                # Copy logs
                orig_logs = orig_node.logs.all().order_by('timestamp')
                for log in orig_logs:
                    await async_ops.create_node_log(
                        new_node,
                        log.level,
                        f"[COPIED] {log.message}",
                        log.context
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
            "code_reproducibility_result": None,
            "errors": []
        }
        
        # Load paper_type_result if we're starting from code_reproducibility_analysis
        if original_node.node_id == "code_reproducibility_analysis":
            paper_type_node = await async_ops.get_workflow_node(str(new_workflow_run.id), "paper_type_classification")
            if paper_type_node and paper_type_node.status == 'completed':
                artifacts = await async_ops.get_node_artifacts(paper_type_node)
                for artifact in artifacts:
                    if artifact.name == 'result':
                        state["paper_type_result"] = PaperTypeClassification(**artifact.data)
                        break
        
        # Execute nodes from target node onwards
        if original_node.node_id == "paper_type_classification":
            # Execute both nodes
            result1 = await paper_type_classification_node(state)
            if "paper_type_result" in result1:
                state["paper_type_result"] = result1["paper_type_result"]
            if "errors" in result1:
                state["errors"].extend(result1["errors"])
            
            result2 = await code_reproducibility_analysis_node(state)
            if "code_reproducibility_result" in result2:
                state["code_reproducibility_result"] = result2["code_reproducibility_result"]
            if "errors" in result2:
                state["errors"].extend(result2["errors"])
                
        elif original_node.node_id == "code_reproducibility_analysis":
            # Execute only code_reproducibility_analysis
            result = await code_reproducibility_analysis_node(state)
            if "code_reproducibility_result" in result:
                state["code_reproducibility_result"] = result["code_reproducibility_result"]
            if "errors" in result:
                state["errors"].extend(result["errors"])
        
        # Check for errors
        errors = state.get("errors", [])
        success = len(errors) == 0
        
        # Update workflow run status
        await async_ops.update_workflow_run_status(
            new_workflow_run.id,
            'completed' if success else 'failed',
            completed_at=timezone.now(),
            output_data={
                'success': success,
                'paper_type': state.get("paper_type_result").model_dump() if state.get("paper_type_result") else None,
                'code_reproducibility': state.get("code_reproducibility_result").model_dump() if state.get("code_reproducibility_result") else None
            },
            error_message='; '.join(errors) if errors else None
        )
        
        return {
            "success": success,
            "workflow_run_id": str(new_workflow_run.id),
            "run_number": new_workflow_run.run_number,
            "paper_id": paper_id,
            "started_from_node": original_node.node_id,
            "errors": errors
        }
        
    except Exception as e:
        logger.error(f"Failed to execute workflow from node: {e}", exc_info=True)
        
        # Try to update workflow run status
        try:
            if 'new_workflow_run' in locals():
                await async_ops.update_workflow_run_status(
                    new_workflow_run.id,
                    'failed',
                    completed_at=timezone.now(),
                    error_message=str(e)
                )
        except:
            pass
        
        return {
            "success": False,
            "error": str(e)
        }


async def process_paper_workflow(
    paper_id: int,
    force_reprocess: bool = False,
    openai_api_key: Optional[str] = None,
    model: str = "gpt-4o",
    user_id: Optional[int] = None
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
            version=1,
            description="Two-node workflow for paper type classification and code reproducibility analysis",
            dag_structure={
                "nodes": [
                    {
                        "id": "paper_type_classification",
                        "type": "python",
                        "handler": "webApp.services.paper_processing_workflow.paper_type_classification_handler",
                        "config": {}
                    },
                    {
                        "id": "code_reproducibility_analysis",
                        "type": "python",
                        "handler": "webApp.services.paper_processing_workflow.code_reproducibility_analysis_handler",
                        "config": {}
                    }
                ],
                "edges": [
                    {
                        "from": "paper_type_classification",
                        "to": "code_reproducibility_analysis"
                    }
                ]
            }
        )
        
        # Create workflow run using orchestrator
        config = {
            'force_reprocess': force_reprocess,
            'model': model,
            'max_retries': 3
        }
        workflow_run = await async_ops.create_workflow_run_with_paper_id(
            workflow_name="reduced_paper_processing_pipeline",
            paper_id=paper_id,
            input_data=config
        )
        
        # Update workflow run status to running
        await async_ops.update_workflow_run_status(
            workflow_run.id,
            'running',
            started_at=timezone.now()
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
            "code_reproducibility_result": None,
            "errors": []
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
            'completed' if success else 'failed',
            completed_at=timezone.now(),
            output_data={
                'success': success,
                'paper_type': final_state.get("paper_type_result").model_dump() if final_state.get("paper_type_result") else None,
                'code_reproducibility': final_state.get("code_reproducibility_result").model_dump() if final_state.get("code_reproducibility_result") else None
            },
            error_message='; '.join(errors) if errors else None
        )
        
        # Get token usage from artifacts
        input_tokens, output_tokens = await async_ops.get_token_stats(str(workflow_run.id))
        
        # Compile results
        results = {
            "success": success,
            "workflow_run_id": str(workflow_run.id),
            "run_number": workflow_run.run_number,
            "paper_id": paper_id,
            "paper_title": (await async_ops.get_paper(paper_id)).title,
            "paper_type": final_state.get("paper_type_result"),
            "code_reproducibility": final_state.get("code_reproducibility_result"),
            "total_input_tokens": input_tokens,
            "total_output_tokens": output_tokens,
            "errors": errors
        }
        
        logger.info(f"Workflow run {workflow_run.id} completed. Status: {'success' if success else 'failed'}")
        logger.info(f"Tokens used: {input_tokens} input, {output_tokens} output")
        
        return results
        
    except Exception as e:
        logger.error(f"Workflow execution failed: {e}", exc_info=True)
        
        # Try to update workflow run status
        try:
            if 'workflow_run' in locals():
                await async_ops.update_workflow_run_status(
                    workflow_run.id,
                    'failed',
                    completed_at=timezone.now(),
                    error_message=str(e)
                )
        except:
            pass
        
        return {
            "success": False,
            "paper_id": paper_id,
            "error": str(e),
            "total_input_tokens": 0,
            "total_output_tokens": 0
        }


# ============================================================================
# Convenience Functions
# ============================================================================

async def process_multiple_papers(
    paper_ids: List[int],
    force_reprocess: bool = False,
    max_concurrent: int = 3
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
