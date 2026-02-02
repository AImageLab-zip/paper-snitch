"""
LangGraph workflow for two-step LLM analysis.
Step 1: locator_prompt - extracts evidence locators from paper
Step 2: checklist_prompt - generates checklist based on locators
"""

import sys
from typing import TypedDict
from pathlib import Path
from langgraph.graph import StateGraph, END
from openai import OpenAI

from pydantic import BaseModel, Field


class EvidenceLocators(BaseModel):
    """
    Schema for extracting reproducibility evidence from a scientific paper.
    Each field must contain a list of sentences extracted directly from the text.
    """

    models_and_algorithms: list[str] = Field(
        description="Sentences related to models and algorithms"
    )
    datasets: list[str] = Field(description="Sentences related to dataset aspects")
    code_artifacts: list[str] = Field(description="Sentences related to code aspects")
    experimental_results: list[str] = Field(
        description="Sentences related to experimental results aspects"
    )


def get_or_upload_file(client: OpenAI, file_path: str) -> str:
    """Check if file exists in OpenAI files, else upload it. Return file ID."""

    file_name = Path(file_path).name

    existing_files = client.files.list()

    for f in existing_files:
        if f.filename == file_name:
            print(f"File found. Using existing ID: {f.id}")
            return f.id

    print(f"File not found. Uploading...")
    new_file = client.files.create(file=open(file_path, "rb"), purpose="user_data")
    return new_file.id


class AnalysisState(TypedDict):
    """State passed between nodes."""

    pdf_path: str
    code_text: str
    client: OpenAI
    config: dict
    input_tokens: int
    output_tokens: int
    total_tokens: int
    locators_result: str
    checklist_result: str


def locator_node(state: AnalysisState) -> dict:
    """First node: extract evidence locators from paper."""
    locator_prompt = 'You are an expert AI Reproducibility Auditor and Data Extraction Specialist.\nYour objective is to analyze a scientific paper and its accompanying code documentation to identify and extract textual evidence related to specific reproducibility criteria.\nTask Instructions:\n    Input Analysis: You will receive the full text of a scientific paper/documentation and a specific JSON schema representing reproducibility categories\n    Semantic Mapping: For each category defined in the input JSON template, locate the specific sections or sentences in the source text that discuss that topic.\n    Extraction Strategy:\n        Extract verbatim text segments directly from the source. Do not summarize, paraphrase, or alter the text.\n        The granularity of extraction can vary: capture single sentences, multiple consecutive sentences, or entire paragraphs, depending on what is necessary to preserve the full context of the evidence.\n        If a specific category is not mentioned in the text, leave the list empty [].\n    Output Format: Return strictly a valid JSON object matching the provided template structure, where each key contains a list of strings (list[str]) representing the extracted evidence.\n{\n     "models_and_algorithms": list[str],\n     "datasets": list[str],\n     "code_artifacts": list[str],\n     "experimental_results": list[str],\n}\n NOTE: A sentece CAN be present in multiple fields if it is relevant to multiple aspects. Or it can be not present at all if it is not relevant to any aspect.'
    file_id = get_or_upload_file(state["client"], state["pdf_path"])
    input_list = [
        {
            "role": "system",
            "content": locator_prompt,
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "input_file",
                    "file_id": file_id,
                },
                {
                    "type": "input_text",
                    "text": f"CODE REPOSITORY:\n{state['code_text'] or 'Not provided'}",
                },
            ],
        },
    ]
    response = state["client"].responses.parse(
        model=state["config"]["model"],
        input=input_list,
        reasoning={"effort": "medium"},
        text_format=EvidenceLocators,
    )
    print(
        f'EVIDENCE LOCATORS:\n"locators_result": {response.output_parsed}\n "input_tokens": {response.usage.input_tokens}\n "output_tokens": {response.usage.output_tokens}\n "total_tokens": {response.usage.total_tokens}'
    )
    return {
        "locators_result": response.output_parsed,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "total_tokens": response.usage.total_tokens,
    }


def checklist_node(state: AnalysisState) -> dict:
    """Second node: generate checklist based on locators."""
    checklist_prompt = """You are an expert reviewer of scientific paper specializing in Artificial Intelligence reproducibility. Your task is to produce as output the following json with values compiled based on the content of the provided scientific paper and its code documentation. \nFor each field in the JSON is written the type of value excepted. There are three main types:\n- bool: the field should be marked as true if the information is present in the paper, false otherwise \n- \'Value A | Value B | Value C\': the field should be marked with ONE of the provided categorical options, choose the option that fits best the content of the paper\n- list[str]: the field should be marked with a LIST OF WORDS found in the paper that belong to the category indicated in the field\nThe output MUST be a valid JSON.\nchecklist = {
"models_and_algorithms": {
    "mathematical_setting": {
        "objective_function": bool,
        "loss_formulation": bool,
        "optimization_constraints": bool,
        "variable_definitions": bool,
        "model_assumptions": bool
    },
    "algorithm_description": {
        "pseudocode": bool,
        "architecture_diagrams": bool,
        "update_rules": bool,
        "convergence_criteria": bool
    }
},
"datasets": {
    "dataset_statistics": {
        "sample_counts": bool,
        "class_balance_distribution": "Balanced | Slight Imbalance | Severe Imbalance | Not Reported",
        "missing_data_rates": bool,
        "feature_dimensionality": bool,
        "data_leakage": "Checked & Mitigated | Potential Risk | Not Discussed"
    },
    "study_cohort_description": {
        "sample_taxonomy": bool,
        "inclusion_criteria": bool,
        "exclusion_criteria": bool,
        "population_size": bool
    },
    "dataset_metadata": {
        "citations_and_doi": bool,
        "source_url": "Public | Request-only | Private | Broken Link",
        "license_type": "MIT | Apache 2.0 | CC-BY | Proprietary",
        "versioning": bool
    },
    "data_collection_process": {
        "data_source": bool,
        "sampling_methodology": bool,
        "temporal_period": bool,
        "survey_design": bool,
        "cleaning_preprocessing": bool,
        "expert_review_process": bool
    },
    "acquisition_setup": {
        "device_specifications": "Multiple Vendors | Multiple Devices | Single Device | Unknown",
        "environmental_conditions": bool,
        "calibration_procedures": bool,
        "acquisition_parameters": bool
    },
    "annotation_instructions": {
        "labeling_guidelines": bool,
        "annotator_expertise": "Expert | Trained | Crowd | Algorithm",
        "consensus_protocols": bool,
        "inter_rater_reliability_score": "Strong | Weak | Not Reported"
    },
    "quality_control": {
        "outlier_detection_methods": bool,
        "manual_audits": bool,
        "validation_checks": bool,
        "automated_filtering": bool,
        "bias_analysis": bool
    },
    "availability_and_ethics": {
        "repository_links": bool,
        "access_permissions": bool,
        "ethics_approval_id": "Provided | Generic statement | Missing | Not Applicable",
        "anonymization_protocol": bool
    }
},
"code_artifacts": {
    "environment_setup": {
        "libraries_used": "Full | Partial | Missing",
        "version_numbers": "Full | Partial | Missing",
        "container_definitions": "Full | Partial | Missing | Not Applicable",
        "os_requirements": "Full | Partial | Missing | Not Applicable",
        "cuda_or_backend_info": bool,
        "random_state_seeding": "Full | Partial | Missing | Not Applicable"
    },
    "implementation_scripts": {
        "script_setup": bool,
        "training_logic": bool,
        "inference_logic": bool,
        "preprocessing_details": "Full | Partial | Missing | Not Applicable"
    },
    "reproducibility_artifacts": {
        "checkpoints": bool,
        "configuration_files": "Full | Partial | Missing | Not Applicable",
        "logging_outputs": "Full | Partial | Missing | Not Applicable",
        "documentation": "Full | Partial | Missing"
    },
    "code_availability": {
        "repository_link_status": [
            "Active/Public",
            "Broken",
            "Request Access",
            "None"
        ],
        "training_script": bool,
        "evaluation_script": bool,
        "checkpoints": bool,
        "preprocessing_details": "Full | Partial | Missing | Not Applicable",
        "logging_outputs": "Full | Partial | Missing | Not Applicable",
        "readme_quality": "Full | Partial | None",
        "license_type": "MIT | Apache 2.0 | CC-BY | Proprietary"
    }
},
"experimental_results": {
    "experimental_setup": {
        "architectural_hyperparams": list[str],
        "optimization_parameters": list[str],
        "best_hyperparameters_selection_method": bool,
        "hyperparameters_ranges": "Full | Partial | Missing",
        "batch_sizes": bool,
        "search_strategy": bool,
        "baseline_implementation": bool,
        "baseline_tuning": bool
    },
    "quantitative_analysis": {
        "training_and_evaluation_runs_count": bool,
        "ablation_studies": "Full | Partial | Missing",
        "evaluation_metrics": list[str],
        "data_splits_definition": bool,
        "sota_comparisons": bool,
        "statistical_measures": list[str],
        "central_tendency_measures": bool,
        "dispersion_measures": bool,
        "significance_tests": bool,
        "confidence_intervals": bool,
        "sensitivity_analysis": bool
    },
    "qualitative_analysis": {
        "failure_analysis": bool,
        "perturbation_testing": bool,
        "out_of_distribution_testing": bool,
        "subgroup_fairness_analysis": bool,
        "clinical_significance_discussion": bool,
        "results_discussion": bool
    },
    "compute_and_resources": {
        "hardware_specification": bool,
        "environment_description": bool,
        "training_time": bool,
        "energy_cost_or_average_runtime": bool,
        "memory_usage": bool
    }
}
NOTE: Only answer with the JSON object, do not use any markdown around."""
    file_id = get_or_upload_file(state["client"], state["pdf_path"])

    response = state["client"].responses.create(
        model=state["config"]["model"],
        input=[
            {"role": "system", "content": checklist_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_file",
                        "file_id": file_id,
                    },
                    {
                        "type": "input_text",
                        "text": f"CODE REPOSITORY:\n{state['code_text'] or 'Not provided'}",
                    },
                ],
                # state["locators_result"],
            },
        ],
        reasoning={"effort": "medium"},
    )
    output_tokens = state["output_tokens"] + response.usage.output_tokens
    input_tokens = state["input_tokens"] + response.usage.input_tokens
    total_tokens = state["total_tokens"] + response.usage.total_tokens

    return {
        "checklist_result": response.output_text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def end_node(state: AnalysisState) -> dict:
    """End node: print final result."""
    print("=== CHECKLIST RESULT ===")
    print(state["checklist_result"])
    print("=== TOKEN USAGE ===")
    print(
        f"Input Tokens: {state['input_tokens']}, Output Tokens: {state['output_tokens']}, Total Tokens: {state['total_tokens']}"
    )
    return {}


def build_analysis_graph() -> StateGraph:
    """Build and compile the analysis graph."""
    graph = StateGraph(AnalysisState)

    graph.add_node("locator", locator_node)
    graph.add_node("checklist", checklist_node)
    graph.add_node("end", end_node)

    graph.set_entry_point("locator")
    graph.add_edge("locator", "checklist")
    graph.add_edge("checklist", "end")
    graph.add_edge("end", END)

    return graph.compile()


def run_analysis_graph(
    client: OpenAI, pdf_path: str, config: dict, code_text: str = None
) -> str:
    """Run the analysis graph and return the checklist result."""
    graph = build_analysis_graph()

    initial_state = {
        "pdf_path": pdf_path,
        "code_text": code_text or "",
        "client": client,
        "config": config,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "locators_result": "",
        "checklist_result": "",
    }

    final_state = graph.invoke(initial_state)
    return final_state["checklist_result"]


from collections import defaultdict


def pulisci_file_duplicati(client):
    # 1. Recupera tutti i file (gestendo la lista completa)
    all_files = client.files.list().data

    # 2. Raggruppa i file per nome
    files_by_name = defaultdict(list)
    for f in all_files:
        files_by_name[f.filename].append(f)

    # 3. Itera sui gruppi per identificare ed eliminare i duplicati
    for filename, file_list in files_by_name.items():
        if len(file_list) > 1:
            # Ordina per data di creazione (dal più recente al più vecchio)
            # created_at più alto = più recente
            file_list.sort(key=lambda x: x.created_at, reverse=True)

            # Il primo della lista è il più recente, lo teniamo
            file_da_tenere = file_list[0]
            # Tutti gli altri sono duplicati obsoleti
            file_da_eliminare = file_list[1:]

            print(f"--- File: {filename} ---")
            print(f"Mantenuto: {file_da_tenere.id} (del {file_da_tenere.created_at})")

            for f in file_da_eliminare:
                try:
                    client.files.delete(f.id)
                    print(f"Eliminato duplicato: {f.id}")
                except Exception as e:
                    print(f"Errore eliminazione {f.id}: {e}")
    print("\nPulizia completata.")


if __name__ == "__main__":

    from dotenv import load_dotenv, set_key
    import os

    BASE_DIR = Path(__file__).resolve().parent.parent.parent
    sys.path.append(str(BASE_DIR))
    load_dotenv("/home/dsantoli/papersnitch/.env.local")
    PDF_DIR = BASE_DIR / "media" / "pdfs"

    # ======= OPEN AI ========
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = "https://api.openai.com/v1"
    model = ("gpt-5.1",)
    temperature = 0.6

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
    )

    config = {"model": "gpt-5.1", "temperature": 0.1}
    pdf_path = (
        PDF_DIR
        / "µ_2_Tokenizer_Differentiable_Multi-Scale_Multi-Modal_Tokenizer_for_Radiology_Report__zFZkv6h.pdf"
    )
    code = """

================================================
FILE: LICENSE
================================================    
MIT License

Copyright (c) 2025 Siyou Li

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
    
================================================
FILE: README.md
================================================
<p>
  <h1>
    <img src="./assets/logo.svg" height=150px align="right"/>
   <var>&micro<sup>2</sup></var>Tokenizer: Differentiable Multi-Scale Multi-Modal Tokenizer for Radiology Report Generation
  </h1>
</p>

[![PWC](https://img.shields.io/badge/%F0%9F%93%8E%20arXiv-Paper-red)](https://u2tokenizer.github.io/static/pdfs/%CE%BC2_Tokenizer.pdf)
[![PWC](https://img.shields.io/badge/%F0%9F%8C%8E%20Website-Official%20Page-blue)](https://u2tokenizer.github.io/)
[![PWC](https://img.shields.io/badge/HuggingFace-Demo-Green)]()
---
> 🎉🎉🎉 Our Paper accepted by the 28th conference of The Medical Image Computing and Computer Assisted Intervention Society (MICCAI). See you in Daejeon, Korea from September 23-27, 2025.

<p align="center">
  <img src="./assets/cover.svg">
</p>


This repository contains the official paper for μ² Tokenizer, a novel approach for automated radiology report generation (RRG) introduced in the paper "μ² Tokenizer: Differentiable Multi-Scale Multi-Modal Tokenizer for Radiology Report Generation".

Our proposed model, μ²LLM, leverages a multi-scale, multi-modal architecture to generate accurate and clinically salient radiology reports from CT scans.

## 👋 Introduction

<img src="./assets/ullm.svg">

we introduce μ²LLM, a multi-scale multimodal large language model. At its core is the novel μ² Tokenizer, an intermediate layer that intelligently fuses visual features from CT scans with textual information. The model is further refined using Direct Preference Optimization (DPO), guided by the specialized medical report evaluation metric, GREEN, to ensure the generated reports align with expert standards.

<img src="./assets/dpo.svg">

Our experimental results on four large-scale CT datasets show that μ²LLM outperforms existing methods, highlighting its potential for generating high-quality radiology reports even with limited training data.

## 🚀 Quickstart
Here, we can easily use our model based on Hugging Face.

```python
coming soon...
```

## 🤖 Model
| Model    | Download Link                                                                                                                                 |
|----------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| μ²Qwen3-8B | [HuggingFace](https://huggingface.co/SiyouLi/u2Qwen3-8B)|
| μ²Qwen3-1.7B  | [HuggingFace](https://huggingface.co/SiyouLi/u2Qwen3-1.7B)|

## ⚙️ Installation
```bash
git clone https://github.com/Siyou-Li/u2Tokenizer.git
cd u2Tokenizer
pip install -r requirements.txt
```
Ensure that the NVIDIA CUDA version 11.8 or above to be compatible with PyTorch 2.2.2.

## 💿 Data
Coming soon...

## 🚄 Training
Coming soon...


## 🧰 System Hardware requirements

For training, stage 1 and 2 use a 4 * 80GB A100 GPU. For inference, a single 40GB A40 GPU is used. For loading model checkpoint, approximately 39GB of CPU memory is required.

## 🫡 Acknowledgements


## ✨ Cite our work

If you find this repo useful, please consider citing: 

```bibtex
@misc{li2025mu2tokenizerdifferentiablemultiscalemultimodal,
      title={${\mu}^2$Tokenizer: Differentiable Multi-Scale Multi-Modal Tokenizer for Radiology Report Generation}, 
      author={Siyou Li and Pengyao Qin and Huanan Wu and Dong Nie and Arun J. Thirunavukarasu and Juntao Yu and Le Zhang},
      year={2025},
      eprint={2507.00316},
      archivePrefix={arXiv},
      primaryClass={cs.LG},
      url={https://arxiv.org/abs/2507.00316}, 
}
```

"""

    checklist = run_analysis_graph(client, pdf_path, config, code)
