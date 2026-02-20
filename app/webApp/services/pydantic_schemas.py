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