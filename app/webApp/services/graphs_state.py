# ============================================================================
# Workflow State
# ============================================================================

from typing import Optional, List, TypedDict
from webApp.services.pydantic_schemas import (
    PaperTypeClassification,
    DatasetDocumentationCheck,
    ReproducibilityChecklist,
    CodeAvailabilityCheck,
    CodeReproducibilityAnalysis,
    CodeEmbeddingResult,
)
from openai import OpenAI


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
    section_embeddings_result: Optional[dict]  # Dict with sections_processed, section_types, etc.
    dataset_documentation_result: Optional[DatasetDocumentationCheck]  # Dataset docs evaluation
    reproducibility_checklist_result: Optional[ReproducibilityChecklist]  # MICCAI checklist
    code_availability_result: Optional[CodeAvailabilityCheck]
    code_embedding_result: Optional[CodeEmbeddingResult]  # Node F: Code file embeddings
    code_reproducibility_result: Optional[CodeReproducibilityAnalysis]  # Node C: Code analysis
