"""
Dataset Documentation Criteria

Defines the 10 criteria for evaluating dataset documentation quality.
Used for dataset and both papers to assess compliance with MICCAI standards.

Structure:
- Data Collection: 3 criteria (1-3)
- Annotation: 4 criteria (4-7)
- Ethics & Availability: 3 criteria (8-10)
"""

from typing import Dict, List
from dataclasses import dataclass


@dataclass
class DatasetDocumentationCriterion:
    """Definition of a single dataset documentation criterion."""
    criterion_number: int
    criterion_id: str
    criterion_name: str
    category: str
    description: str
    
    def get_embedding_context(self) -> str:
        """
        Generate context text for embedding generation.
        Combines name, description, and relevant search queries.
        """
        return f"{self.criterion_name}. {self.description}"


# Define the 10 dataset documentation criteria
DATASET_DOCUMENTATION_CRITERIA: Dict[str, DatasetDocumentationCriterion] = {
    # DATA COLLECTION (3 criteria)
    "data_collection_described": DatasetDocumentationCriterion(
        criterion_number=1,
        criterion_id="data_collection_described",
        criterion_name="Data Collection Process",
        category="data_collection",
        description="Complete description of data collection process, including recruitment strategy, time period, institutions involved, and sampling methodology"
    ),
    
    "acquisition_parameters": DatasetDocumentationCriterion(
        criterion_number=2,
        criterion_id="acquisition_parameters",
        criterion_name="Acquisition Parameters",
        category="data_collection",
        description="Device types, imaging modalities, scanner specifications, imaging protocols, acquisition parameters (resolution, field of view, etc.)"
    ),
    
    "study_cohort": DatasetDocumentationCriterion(
        criterion_number=3,
        criterion_id="study_cohort",
        criterion_name="Study Cohort Description",
        category="data_collection",
        description="Patient/subject selection criteria, demographics (age, gender, clinical characteristics), inclusion/exclusion criteria, cohort stratification"
    ),
    
    # ANNOTATION (4 criteria)
    "annotation_protocol": DatasetDocumentationCriterion(
        criterion_number=4,
        criterion_id="annotation_protocol",
        criterion_name="Annotation Protocol",
        category="annotation",
        description="Clear annotation guidelines, procedures, tools used, annotation types (segmentation, classification, etc.), and specific instructions given to annotators"
    ),
    
    "annotator_details": DatasetDocumentationCriterion(
        criterion_number=5,
        criterion_id="annotator_details",
        criterion_name="Annotator Qualifications",
        category="annotation",
        description="Annotator qualifications (e.g., board-certified radiologists, medical students), number of annotators, training procedures, and annotation instructions"
    ),
    
    "inter_rater_agreement": DatasetDocumentationCriterion(
        criterion_number=6,
        criterion_id="inter_rater_agreement",
        criterion_name="Inter-Rater Agreement",
        category="annotation",
        description="Inter-annotator agreement metrics such as Cohen's kappa, Dice coefficient, intraclass correlation (ICC), or percentage agreement"
    ),
    
    "quality_control": DatasetDocumentationCriterion(
        criterion_number=7,
        criterion_id="quality_control",
        criterion_name="Quality Control",
        category="annotation",
        description="Quality control and validation procedures, review processes, handling of disagreements, and measures to ensure annotation accuracy"
    ),
    
    # ETHICS & AVAILABILITY (3 criteria)
    "ethics_approval": DatasetDocumentationCriterion(
        criterion_number=8,
        criterion_id="ethics_approval",
        criterion_name="Ethics Approval",
        category="ethics_availability",
        description="IRB/ethics committee approval mentioned, informed consent procedures, or statement that approval was not required (e.g., public data)"
    ),
    
    "data_availability": DatasetDocumentationCriterion(
        criterion_number=9,
        criterion_id="data_availability",
        criterion_name="Data Availability Statement",
        category="ethics_availability",
        description="Clear statement on how to access the dataset (public URL, request procedure, contact information), availability timeline, and access conditions"
    ),
    
    "data_license": DatasetDocumentationCriterion(
        criterion_number=10,
        criterion_id="data_license",
        criterion_name="Usage License",
        category="ethics_availability",
        description="Explicit usage license or terms of use (e.g., CC-BY, CC-BY-NC, custom agreements), restrictions, and permitted use cases"
    ),
}


def get_criterion_by_id(criterion_id: str) -> DatasetDocumentationCriterion:
    """Get criterion by ID."""
    if criterion_id not in DATASET_DOCUMENTATION_CRITERIA:
        raise ValueError(f"Unknown criterion ID: {criterion_id}")
    return DATASET_DOCUMENTATION_CRITERIA[criterion_id]


def get_all_criteria() -> List[DatasetDocumentationCriterion]:
    """Get all criteria ordered by criterion_number."""
    return sorted(DATASET_DOCUMENTATION_CRITERIA.values(), key=lambda c: c.criterion_number)


def get_criteria_by_category(category: str) -> List[DatasetDocumentationCriterion]:
    """Get all criteria for a specific category."""
    return [c for c in get_all_criteria() if c.category == category]


def get_criterion_ids() -> List[str]:
    """Get list of all criterion IDs."""
    return [c.criterion_id for c in get_all_criteria()]
