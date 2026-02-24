"""
MICCAI Reproducibility Checklist Criteria

Defines the 20 criteria used for reproducibility evaluation.
Code-related criteria (12-17) are excluded as they're handled by Node C.

Structure:
- Models/Algorithms: 7 criteria (1-7)
- Datasets: 4 criteria (8-11)
- Experiments: 9 criteria (12-20)
"""

from typing import Dict, List
from dataclasses import dataclass


@dataclass
class ChecklistCriterion:
    """Definition of a single reproducibility checklist criterion."""
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


# Define the 20 reproducibility criteria (excluding code-related 12-17)
REPRODUCIBILITY_CRITERIA: Dict[str, ChecklistCriterion] = {
    # MODELS/ALGORITHMS (7 criteria)
    "mathematical_description": ChecklistCriterion(
        criterion_number=1,
        criterion_id="mathematical_description",
        criterion_name="Mathematical Description",
        category="models",
        description="Full mathematical description of model/algorithm with formulas, equations, and computational steps"
    ),
    
    "assumptions_stated": ChecklistCriterion(
        criterion_number=2,
        criterion_id="assumptions_stated",
        criterion_name="Model Assumptions",
        category="models",
        description="Model assumptions explicitly stated (e.g., data distribution, independence assumptions, convergence conditions)"
    ),
    
    "software_framework": ChecklistCriterion(
        criterion_number=3,
        criterion_id="software_framework",
        criterion_name="Software Framework",
        category="models",
        description="Software framework and version specified (e.g., PyTorch 1.12, TensorFlow 2.8, scikit-learn)"
    ),
    
    "hyperparameters_reported": ChecklistCriterion(
        criterion_number=4,
        criterion_id="hyperparameters_reported",
        criterion_name="Hyperparameters Reported",
        category="models",
        description="All hyperparameters specified (learning rate, batch size, optimizer settings, architecture details)"
    ),
    
    "hyperparameter_selection": ChecklistCriterion(
        criterion_number=5,
        criterion_id="hyperparameter_selection",
        criterion_name="Hyperparameter Selection Method",
        category="models",
        description="Method for selecting hyperparameters described (grid search, random search, validation set tuning)"
    ),
    
    "baseline_implementation": ChecklistCriterion(
        criterion_number=6,
        criterion_id="baseline_implementation",
        criterion_name="Baseline Implementation",
        category="models",
        description="Details on how baselines were implemented and tuned for fair comparison"
    ),
    
    "sensitivity_analysis": ChecklistCriterion(
        criterion_number=7,
        criterion_id="sensitivity_analysis",
        criterion_name="Sensitivity Analysis",
        category="models",
        description="Parameter sensitivity or ablation study showing impact of key design choices"
    ),
    
    # DATASETS (4 criteria)
    "dataset_statistics": ChecklistCriterion(
        criterion_number=8,
        criterion_id="dataset_statistics",
        criterion_name="Dataset Statistics",
        category="datasets",
        description="Dataset size, class distribution, patient demographics, imaging parameters, and other relevant statistics"
    ),
    
    "dataset_splits": ChecklistCriterion(
        criterion_number=9,
        criterion_id="dataset_splits",
        criterion_name="Dataset Splits",
        category="datasets",
        description="Train/val/test split details or cross-validation strategy with fold definitions"
    ),
    
    "dataset_availability": ChecklistCriterion(
        criterion_number=10,
        criterion_id="dataset_availability",
        criterion_name="Dataset Availability",
        category="datasets",
        description="Public dataset names or availability statement (how to access or request the data)"
    ),
    
    "dataset_ethics": ChecklistCriterion(
        criterion_number=11,
        criterion_id="dataset_ethics",
        criterion_name="Ethics Approval",
        category="datasets",
        description="Ethics approval mentioned or specified that no approval was needed (e.g., public data)"
    ),
    
    # EXPERIMENTS (9 criteria) - Note: renumbered after removing code criteria
    "number_of_runs": ChecklistCriterion(
        criterion_number=12,
        criterion_id="number_of_runs",
        criterion_name="Number of Runs",
        category="experiments",
        description="Number of training/evaluation runs specified to assess variance"
    ),
    
    "results_with_variance": ChecklistCriterion(
        criterion_number=13,
        criterion_id="results_with_variance",
        criterion_name="Results with Variance",
        category="experiments",
        description="Results report mean ± standard deviation or confidence intervals across multiple runs"
    ),
    
    "statistical_significance": ChecklistCriterion(
        criterion_number=14,
        criterion_id="statistical_significance",
        criterion_name="Statistical Significance",
        category="experiments",
        description="Statistical tests reported (t-test, p-values, Wilcoxon test) to validate performance claims"
    ),
    
    "evaluation_metrics": ChecklistCriterion(
        criterion_number=15,
        criterion_id="evaluation_metrics",
        criterion_name="Evaluation Metrics",
        category="experiments",
        description="Clear metric definitions with formulas (Dice, IoU, AUC, sensitivity, specificity)"
    ),
    
    "runtime_reported": ChecklistCriterion(
        criterion_number=16,
        criterion_id="runtime_reported",
        criterion_name="Runtime Reported",
        category="experiments",
        description="Training and/or inference time reported to assess computational cost"
    ),
    
    "memory_footprint": ChecklistCriterion(
        criterion_number=17,
        criterion_id="memory_footprint",
        criterion_name="Memory Footprint",
        category="experiments",
        description="GPU memory or RAM requirements specified for running the method"
    ),
    
    "failure_analysis": ChecklistCriterion(
        criterion_number=18,
        criterion_id="failure_analysis",
        criterion_name="Failure Analysis",
        category="experiments",
        description="Discussion of failure cases, limitations, or scenarios where method underperforms"
    ),
    
    "clinical_significance": ChecklistCriterion(
        criterion_number=19,
        criterion_id="clinical_significance",
        criterion_name="Clinical Significance",
        category="experiments",
        description="Clinical relevance or practical significance of results discussed (not just statistical significance)"
    ),
    
    "computing_infrastructure": ChecklistCriterion(
        criterion_number=20,
        criterion_id="computing_infrastructure",
        criterion_name="Computing Infrastructure",
        category="experiments",
        description="Hardware specifications reported (GPU model, CPU, number of GPUs, memory)"
    ),
}


def get_criterion_by_id(criterion_id: str) -> ChecklistCriterion:
    """Get criterion by ID."""
    if criterion_id not in REPRODUCIBILITY_CRITERIA:
        raise ValueError(f"Unknown criterion ID: {criterion_id}")
    return REPRODUCIBILITY_CRITERIA[criterion_id]


def get_all_criteria() -> List[ChecklistCriterion]:
    """Get all criteria ordered by criterion_number."""
    return sorted(REPRODUCIBILITY_CRITERIA.values(), key=lambda c: c.criterion_number)


def get_criteria_by_category(category: str) -> List[ChecklistCriterion]:
    """Get all criteria for a specific category."""
    return [c for c in get_all_criteria() if c.category == category]


def get_criterion_ids() -> List[str]:
    """Get list of all criterion IDs."""
    return [c.criterion_id for c in get_all_criteria()]
