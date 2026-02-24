# ============================================================================
# Pydantic Models for Structured Outputs
# ============================================================================

from typing import Optional, Dict, List
from pydantic import BaseModel, Field, ConfigDict


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
        description="Computed reproducibility score (0-100)", ge=0.0, le=100.0
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

class CodeFileEmbeddingInfo(BaseModel):
    """Information about a single embedded code file or chunk."""
    
    model_config = ConfigDict(extra="forbid")
    
    file_path: str = Field(description="Relative path of the file in repository")
    file_content: str = Field(description="Text content of file or chunk")
    chunk_index: int = Field(default=0, description="Chunk index (0 for non-chunked)")
    total_chunks: int = Field(default=1, description="Total chunks for this file")
    content_hash: str = Field(description="SHA256 hash of original file content")
    embedding: List[float] = Field(description="Embedding vector")
    tokens_used: int = Field(description="Tokens used for this embedding")


class CodeEmbeddingResult(BaseModel):
    """Result of code repository embedding (Node F)."""
    
    model_config = ConfigDict(extra="forbid")
    
    code_url: str = Field(description="Repository URL")
    clone_path: Optional[str] = Field(
        default=None,
        description="Path to cloned repository (for reuse in Node C)"
    )
    summary: str = Field(description="Repository summary from ingestion")
    tree_structure: str = Field(description="Full repository tree structure")
    selected_patterns: List[str] = Field(
        description="File patterns selected by LLM for embedding"
    )
    embedded_files: List[CodeFileEmbeddingInfo] = Field(
        description="List of embedded files with their embeddings"
    )
    total_files: int = Field(description="Total number of files embedded")
    total_chunks: int = Field(description="Total number of chunks created")
    total_tokens: int = Field(description="Total tokens used for embeddings")
    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model used"
    )
    embedding_dimension: int = Field(
        default=1536,
        description="Dimension of embedding vectors"
    )


class DatasetDocumentationItem(BaseModel):
    """Individual dataset documentation item."""
    
    model_config = ConfigDict(extra="forbid")
    
    criterion: str = Field(description="Documentation criterion being evaluated")
    present: bool = Field(description="Whether criterion is satisfied")
    confidence: float = Field(description="Confidence score 0-1", ge=0.0, le=1.0)
    evidence_text: Optional[str] = Field(
        default=None,
        description="Text excerpt providing evidence (max 500 chars)"
    )
    page_reference: Optional[str] = Field(
        default=None,
        description="Page/section reference where evidence was found"
    )
    notes: Optional[str] = Field(
        default=None,
        description="Additional notes or clarifications"
    )


class DatasetDocumentationCheck(BaseModel):
    """Structured output for dataset documentation check (for dataset/both papers)."""
    
    model_config = ConfigDict(extra="forbid")
    
    # Core dataset information
    dataset_name: Optional[str] = Field(
        default=None,
        description="Name of the dataset if mentioned"
    )
    dataset_size: Optional[str] = Field(
        default=None,
        description="Number of samples/images/patients mentioned"
    )
    
    # Data collection criteria
    data_collection_described: DatasetDocumentationItem = Field(
        description="Whether data collection process is described"
    )
    acquisition_parameters: DatasetDocumentationItem = Field(
        description="Whether image acquisition parameters are specified"
    )
    study_cohort: DatasetDocumentationItem = Field(
        description="Whether study cohort/population is described"
    )
    
    # Annotation criteria
    annotation_protocol: DatasetDocumentationItem = Field(
        description="Whether annotation protocol is documented"
    )
    annotator_details: DatasetDocumentationItem = Field(
        description="Whether annotator qualifications/instructions are described"
    )
    inter_rater_agreement: DatasetDocumentationItem = Field(
        description="Whether inter-annotator agreement metrics reported"
    )
    quality_control: DatasetDocumentationItem = Field(
        description="Whether quality control measures are described"
    )
    
    # Ethics and availability
    ethics_approval: DatasetDocumentationItem = Field(
        description="Whether ethics approval/IRB is mentioned"
    )
    data_availability: DatasetDocumentationItem = Field(
        description="Whether data availability statement is present"
    )
    data_license: DatasetDocumentationItem = Field(
        description="Whether usage license is specified"
    )
    download_link: Optional[str] = Field(
        default=None,
        description="Download link or access procedure URL if mentioned"
    )
    
    # Overall assessment
    overall_score: float = Field(
        description="Overall documentation score 0-100",
        ge=0.0,
        le=100.0
    )
    summary: str = Field(
        description="Brief summary of dataset documentation quality"
    )


class ReproducibilityChecklistItem(BaseModel):
    """Individual reproducibility checklist item."""
    
    model_config = ConfigDict(extra="forbid")
    
    criterion: str = Field(description="MICCAI reproducibility criterion")
    category: str = Field(
        description="Category: models, datasets, code, experiments, or infrastructure"
    )
    present: bool = Field(description="Whether criterion is satisfied")
    confidence: float = Field(description="Confidence score 0-1", ge=0.0, le=1.0)
    evidence_text: Optional[str] = Field(
        default=None,
        description="Text excerpt providing evidence (max 500 chars)"
    )
    page_reference: Optional[str] = Field(
        default=None,
        description="Page/section reference where evidence was found"
    )
    importance: str = Field(
        description="'critical', 'important', or 'optional' based on paper type"
    )


class CategoryScores(BaseModel):
    """Category-wise reproducibility scores."""
    
    model_config = ConfigDict(extra="forbid")
    
    models: float = Field(description="Models/algorithms score (0-100)", ge=0.0, le=100.0)
    datasets: float = Field(description="Dataset documentation score (0-100)", ge=0.0, le=100.0)
    code: float = Field(description="Code availability score (0-100)", ge=0.0, le=100.0)
    experiments: float = Field(description="Experimental rigor score (0-100)", ge=0.0, le=100.0)
    infrastructure: float = Field(description="Infrastructure transparency score (0-100)", ge=0.0, le=100.0)


class ReproducibilityChecklist(BaseModel):
    """Structured output for MICCAI reproducibility checklist extraction."""
    
    model_config = ConfigDict(extra="forbid")
    
    # Models/Algorithms criteria (7 items)
    mathematical_description: ReproducibilityChecklistItem
    assumptions_stated: ReproducibilityChecklistItem
    software_framework: ReproducibilityChecklistItem
    hyperparameters_reported: ReproducibilityChecklistItem
    hyperparameter_selection: ReproducibilityChecklistItem
    baseline_implementation: ReproducibilityChecklistItem
    sensitivity_analysis: ReproducibilityChecklistItem
    
    # Dataset criteria (4 items)
    dataset_statistics: ReproducibilityChecklistItem
    dataset_splits: ReproducibilityChecklistItem
    dataset_availability: ReproducibilityChecklistItem
    dataset_ethics: ReproducibilityChecklistItem
    
    # Code criteria (6 items)
    code_available: ReproducibilityChecklistItem
    dependencies_specified: ReproducibilityChecklistItem
    training_code: ReproducibilityChecklistItem
    evaluation_code: ReproducibilityChecklistItem
    pretrained_models: ReproducibilityChecklistItem
    readme_with_instructions: ReproducibilityChecklistItem
    
    # Experimental results criteria (9 items)
    number_of_runs: ReproducibilityChecklistItem
    results_with_variance: ReproducibilityChecklistItem
    statistical_significance: ReproducibilityChecklistItem
    evaluation_metrics: ReproducibilityChecklistItem
    runtime_reported: ReproducibilityChecklistItem
    memory_footprint: ReproducibilityChecklistItem
    failure_analysis: ReproducibilityChecklistItem
    clinical_significance: ReproducibilityChecklistItem
    computing_infrastructure: ReproducibilityChecklistItem
    
    # Overall assessment
    category_scores: CategoryScores = Field(
        description="Scores by category: models, datasets, code, experiments, infrastructure (0-100)"
    )
    overall_score: float = Field(
        description="Overall reproducibility score 0-100",
        ge=0.0,
        le=100.0
    )
    paper_type_context: str = Field(
        description="Paper type from classification node ('dataset', 'method', 'both', etc.)"
    )
    weighted_score: float = Field(
        description="Score weighted by paper type (0-100)",
        ge=0.0,
        le=100.0
    )
    summary: str = Field(
        description="Executive summary of reproducibility assessment"
    )
    strengths: List[str] = Field(
        description="Key reproducibility strengths (2-5 items)"
    )
    weaknesses: List[str] = Field(
        description="Key reproducibility weaknesses (2-5 items)"
    )


class SingleCriterionAnalysis(BaseModel):
    """
    Individual criterion analysis result (used in multi-step process).
    LLM analyzes each criterion independently with targeted paper sections.
    """
    
    model_config = ConfigDict(extra="forbid")
    
    criterion_id: str = Field(description="Unique criterion identifier")
    criterion_number: int = Field(description="Criterion number (1-20)")
    criterion_name: str = Field(description="Human-readable criterion name")
    category: str = Field(description="Category: models, datasets, or experiments")
    
    present: bool = Field(description="Whether criterion is satisfied in the paper")
    confidence: float = Field(description="Confidence score 0-1", ge=0.0, le=1.0)
    
    evidence_text: Optional[str] = Field(
        default=None,
        description="Direct quote/excerpt supporting assessment (max 500 chars)"
    )
    page_reference: Optional[str] = Field(
        default=None,
        description="Where evidence was found (e.g., 'Methods section', 'Table 2', 'Page 4')"
    )
    
    notes: Optional[str] = Field(
        default=None,
        description="Additional context or reasons for assessment"
    )
    
    importance: str = Field(
        description="Importance for THIS paper type: 'critical', 'important', or 'optional'"
    )


class SingleDatasetCriterionAnalysis(BaseModel):
    """
    Individual dataset documentation criterion analysis result (used in multi-step process).
    LLM analyzes each criterion independently with targeted paper sections.
    """
    
    model_config = ConfigDict(extra="forbid")
    
    criterion_id: str = Field(description="Unique criterion identifier")
    criterion_number: int = Field(description="Criterion number (1-10)")
    criterion_name: str = Field(description="Human-readable criterion name")
    category: str = Field(description="Category: data_collection, annotation, or ethics_availability")
    
    present: bool = Field(description="Whether criterion is satisfied in the paper")
    confidence: float = Field(description="Confidence score 0-1", ge=0.0, le=1.0)
    
    evidence_text: Optional[str] = Field(
        default=None,
        description="Direct quote/excerpt supporting assessment (max 500 chars)"
    )
    page_reference: Optional[str] = Field(
        default=None,
        description="Where evidence was found (e.g., 'Methods section', 'Table 1', 'Page 3')"
    )
    
    notes: Optional[str] = Field(
        default=None,
        description="Additional context or reasons for assessment"
    )
    
    importance: str = Field(
        description="Importance for dataset papers: 'critical', 'important', or 'optional'"
    )


class AggregatedReproducibilityAnalysis(BaseModel):
    """
    Final aggregated reproducibility analysis combining all criteria.
    Generated programmatically after analyzing all 20 criteria individually.
    All scores and text are computed deterministically (no LLM aggregation).
    """
    
    model_config = ConfigDict(extra="forbid")
    
    # Category scores (0-100 each) - computed programmatically
    models_score: float = Field(
        description="Average score for models/algorithms criteria (1-7)",
        ge=0.0,
        le=100.0
    )
    datasets_score: float = Field(
        description="Average score for dataset criteria (8-11)",
        ge=0.0,
        le=100.0
    )
    experiments_score: float = Field(
        description="Average score for experiments criteria (12-20)",
        ge=0.0,
        le=100.0
    )
    
    # Overall scores - computed programmatically
    overall_score: float = Field(
        description="Overall reproducibility score (average of category scores, 0-100)",
        ge=0.0,
        le=100.0
    )
    weighted_score: float = Field(
        description="Score weighted by paper type importance (0-100)",
        ge=0.0,
        le=100.0
    )
    
    paper_type_context: str = Field(
        description="Paper type from classification: 'dataset', 'method', 'both', 'theoretical', 'unknown'"
    )
    
    # Qualitative assessment - generated programmatically from structured criterion analyses
    summary: str = Field(
        description="Executive summary generated programmatically (2-4 sentences)"
    )
    strengths: List[str] = Field(
        description="Key reproducibility strengths extracted from criteria (3-7 items)"
    )
    weaknesses: List[str] = Field(
        description="Key reproducibility gaps extracted from criteria (3-7 items)"
    )
    recommendations: List[str] = Field(
        description="Specific recommendations generated programmatically (3-7 items)"
    )


class AggregatedDatasetDocumentationAnalysis(BaseModel):
    """
    Final aggregated dataset documentation analysis combining all criteria.
    Generated programmatically after analyzing all 10 criteria individually.
    All scores and text are computed deterministically (no LLM aggregation).
    """
    
    model_config = ConfigDict(extra="forbid")
    
    # Core dataset information (optional, extracted if found)
    dataset_name: Optional[str] = Field(
        default=None,
        description="Name of the dataset if mentioned in paper"
    )
    dataset_size: Optional[str] = Field(
        default=None,
        description="Dataset size (samples/images/patients) if mentioned"
    )
    download_link: Optional[str] = Field(
        default=None,
        description="Download link or access URL if mentioned"
    )
    
    # Category scores (0-100 each) - computed programmatically
    data_collection_score: float = Field(
        description="Average score for data collection criteria (1-3)",
        ge=0.0,
        le=100.0
    )
    annotation_score: float = Field(
        description="Average score for annotation criteria (4-7)",
        ge=0.0,
        le=100.0
    )
    ethics_availability_score: float = Field(
        description="Average score for ethics & availability criteria (8-10)",
        ge=0.0,
        le=100.0
    )
    
    # Overall score - computed programmatically
    overall_score: float = Field(
        description="Overall documentation score (weighted average of category scores, 0-100)",
        ge=0.0,
        le=100.0
    )
    
    # Qualitative assessment - generated programmatically from structured criterion analyses
    summary: str = Field(
        description="Executive summary generated programmatically (2-4 sentences)"
    )
    strengths: List[str] = Field(
        description="Key documentation strengths extracted from criteria (3-7 items)"
    )
    weaknesses: List[str] = Field(
        description="Key documentation gaps extracted from criteria (3-7 items)"
    )
    recommendations: List[str] = Field(
        description="Specific recommendations generated programmatically (3-7 items)"
    )


class FinalQualitativeAssessment(BaseModel):
    """
    Qualitative text assessment generated by LLM for final aggregation.
    This is the LLM response format containing only qualitative text,
    which is then combined with programmatic scores in FinalReproducibilityAssessment.
    """
    
    model_config = ConfigDict(extra="forbid")
    
    executive_summary: str = Field(
        description="2-3 paragraph exec summary synthesizing key findings and implications"
    )
    strengths: List[str] = Field(
        description="3-7 concrete reproducibility strengths across all dimensions"
    )
    weaknesses: List[str] = Field(
        description="3-7 specific gaps or areas needing improvement"
    )


class FinalReproducibilityAssessment(BaseModel):
    """
    Final comprehensive reproducibility assessment combining:
    - Paper checklist (reproducibility_checklist node) 
    - Code repository analysis (code_repository_analysis node)
    - Dataset documentation (dataset_documentation_check node)
    
    Scores are computed programmatically, qualitative text is LLM-generated.
    """
    
    model_config = ConfigDict(extra="forbid")
    
    # Scores (computed programmatically from component nodes)
    paper_checklist_score: float = Field(
        description="Score from reproducibility_checklist node (0-100)",
        ge=0.0,
        le=100.0
    )
    code_analysis_score: Optional[float] = Field(
        default=None,
        description="Score from code_repository_analysis node if code available (0-100)",
        ge=0.0,
        le=100.0
    )
    dataset_documentation_score: Optional[float] = Field(
        default=None,
        description="Score from dataset_documentation_check node if dataset paper (0-100)",
        ge=0.0,
        le=100.0
    )
    overall_score: float = Field(
        description="Weighted average of all available component scores (0-100)",
        ge=0.0,
        le=100.0
    )
    weighted_score: float = Field(
        description="Same as overall_score (for backward compatibility)",
        ge=0.0,
        le=100.0
    )
    
    # Qualitative text (LLM-generated from FinalQualitativeAssessment)
    executive_summary: str = Field(
        description="Comprehensive summary synthesizing all findings"
    )
    strengths: List[str] = Field(
        description="Key reproducibility strengths across all evaluated dimensions"
    )
    weaknesses: List[str] = Field(
        description="Key reproducibility gaps and areas needing improvement"
    )
    
    # Recommendations (computed programmatically)
    recommendations: List[str] = Field(
        description="Specific actionable recommendations based on identified gaps"
    )
    
    # Metadata
    has_code_analysis: bool = Field(
        description="Whether code repository analysis was performed"
    )
    has_dataset_analysis: bool = Field(
        description="Whether dataset documentation analysis was performed"
    )
    paper_type: str = Field(
        description="Paper type: 'dataset', 'method', 'both', 'theoretical', 'unknown'"
    )
    
    # Detailed evaluation criteria (for comparison with human evaluation)
    evaluation_details: Optional[Dict] = Field(
        default=None,
        description="Merged detailed evaluation criteria from all components (reproducibility checklist, code analysis, dataset docs) with true/false presence/absence details"
    )
