"""
Reproducibility Analysis Aspects

Defines the aspects used for retrieving relevant sections/code during repository analysis.
Each aspect corresponds to a specific dimension of reproducibility evaluation.
"""

from typing import Dict, List
from dataclasses import dataclass


@dataclass
class ReproducibilityAspect:
    """Definition of a reproducibility analysis aspect."""
    aspect_id: str
    aspect_name: str
    aspect_description: str
    analysis_prompt_template: str


# Define the 7 reproducibility aspects
REPRODUCIBILITY_ASPECTS: Dict[str, ReproducibilityAspect] = {
    "methodology": ReproducibilityAspect(
        aspect_id="methodology",
        aspect_name="Research Methodology Classification",
        aspect_description="""
        Analysis of research methodology type and requirements:
        - Type of research (deep_learning, machine_learning, algorithm, simulation, data_analysis, theoretical, other)
        - Whether methodology requires model training
        - Whether it requires datasets and dataset splits
        - Notes about essential reproducibility components
        """,
        analysis_prompt_template="""Based on the following paper sections and code documentation, analyze the research methodology:

Paper Sections:
{sections_text}

Code Documentation:
{code_text}

Provide a JSON analysis covering:
- methodology_type: string (one of: deep_learning, machine_learning, algorithm, simulation, data_analysis, theoretical, other)
- requires_training: boolean (does this method need model training?)
- requires_datasets: boolean (does this method need datasets?)
- requires_splits: boolean (does evaluation need train/val/test splits?)
- methodology_notes: string (notes about research type and essential reproducibility components)
"""
    ),
    
    "structure": ReproducibilityAspect(
        aspect_id="structure",
        aspect_name="Repository Structure",
        aspect_description="""
        Analysis of repository organization and dependencies:
        - Whether standalone or built on another repository
        - Presence of requirements/dependencies file
        - Match between requirements and imports
        - Programming languages used
        """,
        analysis_prompt_template="""Based on the following paper sections and code files, analyze the repository structure:

Paper Sections:
{sections_text}

Code Files and Structure:
{code_text}

Provide a JSON analysis covering:
- is_standalone: boolean (true if standalone, false if built on another repo)
- base_repository: string or null (base repo name if not standalone)
- has_requirements: boolean
- requirements_match_imports: boolean or null
- requirements_issues: [list of strings describing any issues]
"""
    ),
    
    "components": ReproducibilityAspect(
        aspect_id="components",
        aspect_name="Code Components",
        aspect_description="""
        Analysis of available code components:
        - Availability of training code
        - Availability of evaluation/inference code
        - Documentation of commands to run code
        """,
        analysis_prompt_template="""Based on the following paper sections and code files, analyze code components:

Paper Sections:
{sections_text}

Code Files:
{code_text}

Provide a JSON analysis covering:
- has_training_code: boolean
- training_code_paths: [list of file paths]
- has_evaluation_code: boolean
- evaluation_code_paths: [list of file paths]
- has_documented_commands: boolean
- command_documentation_location: string or null
"""
    ),
    
    "artifacts": ReproducibilityAspect(
        aspect_id="artifacts",
        aspect_name="Artifacts Availability",
        aspect_description="""
        Analysis of released artifacts:
        - Model checkpoints availability
        - Dataset download links
        - Coverage (full/partial/none)
        """,
        analysis_prompt_template="""Based on the following paper sections and code documentation, analyze artifacts:

Paper Sections:
{sections_text}

Code Documentation:
{code_text}

Provide a JSON analysis covering:
- has_checkpoints: boolean
- checkpoint_locations: [list of URLs/paths]
- has_dataset_links: boolean
- dataset_coverage: string ("full", "partial", or "none")
- dataset_links: [list of {{"name": "dataset name", "url": "URL"}}]
"""
    ),
    
    "dataset_splits": ReproducibilityAspect(
        aspect_id="dataset_splits",
        aspect_name="Dataset Splits Information",
        aspect_description="""
        Analysis of dataset split documentation:
        - Whether dataset splits (train/val/test) are specified
        - Whether exact splits are documented or provided
        - Replicability with same data partitioning
        - Documentation of random seeds
        """,
        analysis_prompt_template="""Based on the following paper sections and code files, analyze dataset splits:

Paper Sections:
{sections_text}

Code Files:
{code_text}

Provide a JSON analysis covering:
- splits_specified: boolean (whether train/val/test splits are mentioned)
- splits_provided: boolean (whether split files or exact splits are in repo)
- random_seeds_documented: boolean (whether seeds are documented)
- splits_notes: string (notes about splits and replicability)
"""
    ),
    
    "documentation": ReproducibilityAspect(
        aspect_id="documentation",
        aspect_name="Documentation Quality",
        aspect_description="""
        Analysis of documentation completeness:
        - README existence
        - Results table presence
        - Precise reproduction commands
        """,
        analysis_prompt_template="""Based on the following paper sections and code documentation, analyze documentation:

Paper Sections:
{sections_text}

Code Documentation:
{code_text}

Provide a JSON analysis covering:
- has_readme: boolean
- has_results_table: boolean
- has_reproduction_commands: boolean
- documentation_notes: string (notes about documentation quality)
"""
    ),
    
    "overall": ReproducibilityAspect(
        aspect_id="overall",
        aspect_name="Overall Assessment",
        aspect_description="""
        Summary assessment of reproducibility:
        - Overall reproducibility status
        - Key strengths and weaknesses
        """,
        analysis_prompt_template="""Based on the following analyses of different aspects, provide an overall assessment:

{aspect_analyses}

Provide a JSON with:
- overall_assessment: string (summary of reproducibility status including key strengths and weaknesses)
"""
    ),
}


def get_aspect_ids() -> List[str]:
    """Get list of aspect IDs in order."""
    return ["methodology", "structure", "components", "artifacts", "dataset_splits", "documentation", "overall"]


def get_aspect(aspect_id: str) -> ReproducibilityAspect:
    """Get aspect definition by ID."""
    if aspect_id not in REPRODUCIBILITY_ASPECTS:
        raise ValueError(f"Unknown aspect ID: {aspect_id}")
    return REPRODUCIBILITY_ASPECTS[aspect_id]
