import json
import os
import sys
from pathlib import Path
import re

from litellm import FileObject
import requests
from openai import OpenAI

# os.environ.setdefault(
#     "DJANGO_SETTINGS_MODULE",
#     os.getenv("DJANGO_SETTINGS_MODULE", "web.settings.development"),
# )
# from web.settings import BASE_DIR

# from webApp.models import Paper, Dataset, Conference
from dotenv import load_dotenv, set_key
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(BASE_DIR))
load_dotenv("/home/dsantoli/papersnitch/.env.local")
PDF_DIR = BASE_DIR / "media" / "pdfs"


# ======= KIMI ========
# api_key = os.getenv("MOONSHOT_API_KEY")
# base_url = "https://api.moonshot.ai/v1"
# model = "kimi-k2-thinking",
# model="kimi-k2-thinking-turbo",
# temperature = 1.0

# ======= OPEN AI ========
api_key = os.getenv("OPENAI_API_KEY")
base_url = "https://api.openai.com/v1"
model = ("gpt-5.1",)
temperature = 0.6

# Set as True means the API are called providing the pdf file in input
is_pdf = False


class CriterionResponse(BaseModel):
    criterion: str = Field(..., description="The name of the criterion being evaluated")
    extracted: str = Field(
        ..., description="The exact text extracted from the paper/code"
    )
    score_justification: str = Field(
        ..., description="Detailed justification for the assigned score"
    )
    score: int = Field(..., description="Integer score between 0 and 10, or -1 for N/A")

    class Config:
        extra = "forbid"


# ================================= KIMI K2 ========================================
# structured answer
"""{
    "id": "cmpl-04ea926191a14749b7f2c7a48a68abc6",
    "object": "chat.completion",
    "created": 1698999496,
    "model": "kimi-k2-turbo-preview",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "Hello, Li Lei! 1+1 equals 2. If you have any other questions, feel free to ask!"
            },
            "finish_reason": "stop"
        }
    ],
    "usage": {
        "prompt_tokens": 19,
        "completion_tokens": 21,
        "total_tokens": 40,
        "cached_tokens": 10  # The number of tokens hit by the cache, only models that support automatic caching will return this field
    }
}"""


# ========== STANDARD USE ============
def kimi_standard(
    client: OpenAI,
    pdf_text: str,
    system_prompt: str,
    model: str,
    temperature: float = 0.0,
):

    messages = [
        {
            "role": "system",
            "content": pdf_text,
        },
        {"role": "user", "content": system_prompt},
    ]

    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        response_format={
            "type": "json_object"
        },  # <-- Use the response_format parameter to specify the output format as json_object
    )

    return completion


# ============ UPLOAD FILES ============


def kimi_files(
    client: OpenAI, file: str, system_prompt: str, model: str, temperature: float = 0.0
):

    file_object = client.files.create(file=file, purpose="file-extract")

    # Retrieve the result
    file_content = client.files.content(file_id=file_object.id).text

    # Include it in the request
    messages = [
        {
            "role": "system",
            "content": file_content,
        },
        {
            "role": "user",
            "content": system_prompt,
        },
    ]

    # Then call chat-completion to get Kimi's response

    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        response_format={"type": "json_object"},
    )

    return completion


def _update_token_kimi(tokens_used: int) -> int:
    current_total = int(os.getenv("TOTAL_TOKEN_KIMI", 0))
    new_total = current_total + tokens_used
    set_key(str(BASE_DIR / ".env.local"), "TOTAL_TOKEN_KIMI", str(new_total))
    return new_total


def calculate_expected_score(probs, n=3):
    import math

    subset = probs[:n]

    # 2. probabilities computation
    linear_probs = []
    total_p = 0

    for item in subset:
        try:
            s_i = float(item["token"].strip())
            p_i = math.exp(item["logprob"])
            linear_probs.append((s_i, p_i))
            total_p += p_i
        except ValueError:
            # skip non-numeric tokens
            continue

    # 3. normalization
    score = 0
    if total_p > 0:
        for s_i, p_i in linear_probs:
            normalized_p = p_i / total_p
            score += normalized_p * s_i

    return score


def estimate_tokens(client: OpenAI, messages: list, model: str) -> dict:
    """
    Estimate tokens for given messages using Kimi's token estimation API.
    Uses the requests library since OpenAI client doesn't have this endpoint.
    """
    import requests

    url = "https://api.moonshot.ai/v1/tokenizers/estimate-token-count"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {client.api_key}",
    }
    payload = {"model": model, "messages": messages}

    response = requests.post(url, headers=headers, json=payload)
    return response.json()


def get_logprobs(logprobs_content, top_logprobs=10):
    # We look for the sequence: 'score' -> '":' -> [THE NUMBER]
    for i, entry in enumerate(logprobs_content):
        if entry.token == "score":
            if i + 1 < len(logprobs_content) and logprobs_content[i + 1].token == '":':
                if i + 2 < len(logprobs_content):
                    target = logprobs_content[i + 2]

                    # Optional: Verify it's actually a number
                    if target.token.strip().isdigit():
                        # Create a list of dictionaries for the top 10 logprobs
                        # We use [:10] to ensure we only get 10 if more are returned
                        alternatives = [
                            {"token": top.token, "logprob": top.logprob}
                            for top in target.top_logprobs[:top_logprobs]
                        ]
                        return alternatives
    return []


def retrieve_file(client: OpenAI, filename: str) -> str:
    existing_files = client.files.list()

    for f in existing_files.data:
        if f.filename == os.path.basename(filename):
            file_id = f.id
            print(f"File found: Using existing ID {file_id}")
            break

    # 2. Upload only if not found
    if not file_id:
        print("File not found: Uploading...")
        new_file = client.files.create(file=open(filename, "rb"), purpose="user-data")
        file_id = new_file.id

    # 3. Retrieve content using the file_id (whether new or existing)
    file_content = client.files.content(file_id=file_id).text
    return file_content


def from_doc_to_code(doc_text: str, url: str) -> list[str]:
    """Extract all code files from a document text.
    This function its designed to be used in the initial stage of the code analysis pipeline,
    to get the subset of the entire repository useful to evaluate the reproducibility of the paper
    Args:
        doc_text: The documentation text extracted from the code repository.
        url: URL of the code repository.
    Returns:
        List of all code files path found in the document text.
    """
    # Step 1: Parse GitHub URL to extract owner and repo name
    github_pattern = re.compile(
        r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)"
    )
    match = github_pattern.match(url.rstrip("/"))
    if not match:
        return []

    owner, repo = match.groups()
    # Remove .git suffix if present
    repo = repo.removesuffix(".git")

    # Step 2: Fetch repository tree using GitHub API
    api_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/main?recursive=1"
    headers = {"Accept": "application/vnd.github.v3+json"}

    # Try main branch first, then master
    response = requests.get(api_url, headers=headers, timeout=30)
    if response.status_code != 200:
        api_url = (
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/master?recursive=1"
        )
        response = requests.get(api_url, headers=headers, timeout=30)
        if response.status_code != 200:
            print(f"Error fetching repository tree:{response.status_code}")
            return []

    tree_data = response.json()
    if "tree" not in tree_data:
        return []

    # Build a set of all file paths in the repository
    repo_files = {item["path"] for item in tree_data["tree"] if item["type"] == "blob"}

    # Also build a mapping of filename -> list of full paths for quick lookup
    filename_to_paths: dict[str, list[str]] = {}
    for filepath in repo_files:
        filename = Path(filepath).name
        if filename not in filename_to_paths:
            filename_to_paths[filename] = []
        filename_to_paths[filename].append(filepath)

    # Step 3: Extract filenames mentioned in doc_text
    # Pattern to match common code file references
    # Matches: file.py, path/to/file.py, `file.py`, "file.py", 'file.py'
    file_patterns = [
        # Match paths with extensions (e.g., src/main.py, utils/helper.js)
        r"(?:[\w./\\-]+/)?[\w.-]+\.(?:py|js|ts|sh|yaml|yml|json|toml|cfg|ini)",
        # Match backtick-quoted filenames
        r"`([\w./\\-]+\.(?:py|js|ts|sh|yaml|yml|json|toml|cfg|ini))`",
        # Match quoted filenames
        r'["\']([\w./\\-]+\.(?:py|js|ts|sh|yaml|yml|json|toml|cfg|ini))["\']',
    ]

    found_files = set()
    for pattern in file_patterns:
        matches = re.findall(pattern, doc_text, re.IGNORECASE)
        for match in matches:
            # Clean up the match
            cleaned = match.strip("`\"'").strip()
            if cleaned:
                found_files.add(cleaned)

    # Step 4: Resolve found filenames to absolute paths in the repository
    resolved_paths = []
    for found_file in found_files:
        # Check if it's already a full path in the repo
        if found_file in repo_files:
            resolved_paths.append(found_file)
            continue

        # Try to match just the filename
        filename = Path(found_file).name
        if filename in filename_to_paths:
            # If found_file contains a partial path, try to match it
            if "/" in found_file or "\\" in found_file:
                # Normalize the path
                normalized = found_file.replace("\\", "/")
                for full_path in filename_to_paths[filename]:
                    if full_path.endswith(normalized):
                        resolved_paths.append(full_path)
                        break
                else:
                    # If no exact suffix match, add all matching filenames
                    resolved_paths.extend(filename_to_paths[filename])
            else:
                # Just a filename, add all matching paths
                resolved_paths.extend(filename_to_paths[filename])

    # Remove duplicates while preserving order
    seen = set()
    unique_paths = []
    for path in resolved_paths:
        if path not in seen:
            seen.add(path)
            unique_paths.append(path)
    print(unique_paths)
    return unique_paths


def main():
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
    )

    with open("webApp/fixtures/prompt.json", "r") as f:
        prompts = json.load(f)
        justification_prompt = prompts[2].get("fields").get("template")
        score_prompt = prompts[3].get("fields").get("template")

    with open("webApp/fixtures/criteria.json", "r") as f:
        criterions = json.load(f)
        datasets = criterions[1].get("fields").get("description")
        evaluation = criterions[4].get("fields").get("description")

    criteria = datasets
    justification_prompt = justification_prompt.format(
        criterion_name="dataset", criterion_description=criteria
    )
    top_logprobs = 5
    file = "IM-Fuse_A_Mamba-based_Fusion_Block_for_Brain_Tumor_Segmentation_with_Incomplete_Modalities.pdf"
    pdf_text = retrieve_file(client, file)
    code_text = None

    # ======== EXPLANATION CALL ========
    # input_list = [
    #     {
    #         "role": "system",
    #         "content": justification_prompt,
    #     },
    #     {
    #         "role": "user",
    #         "content": f"PAPER TEXT:\n{pdf_text}\nCODE REPOSITORY:\n{code_text or 'Not provided'}",
    #     },
    # ]
    # print(input_list)

    # justification_completion = client.chat.completions.create(
    #     model="kimi-k2-0905-preview",
    #     # model="kimi-k2-turbo-preview",
    #     messages=input_list,
    #     temperature=0.6,
    # )

    # score_justification = justification_completion.choices[0].message.content
    # output_tokens_justification = justification_completion.usage.completion_tokens
    # input_tokens_justification = justification_completion.usage.prompt_tokens
    # total_tokens_justification = justification_completion.usage.total_tokens
    # print(
    #     f"\n=== FIRST: Score Explanation (output: {output_tokens_justification} - input: {input_tokens_justification} - total: {total_tokens_justification})"
    # )
    # print(score_justification)

    # ======== SCORE CALL ========
    # score_justification = """The paper provides a reasonably thorough description of the dataset and splits, but with some limitations from a strict reproducibility standpoint. Positive aspects: - Origin and context: The dataset is clearly described as 104 COPD patients from three imaging centers, a subset of the COSYCONET multi-center trial [8]. This gives a clear study context and likely pathway to data access (via COSYCONET), even if not explicitly stated as publicly available. - Population details: Basic cohort statistics are given (age 56.9±18.6, mean GOLD 2.10±1.19), which helps characterize the sample. - Imaging modalities and acquisition protocols: - MRI: 1.5T Magnetom Aera scanners, standardized chest protocol, inspiratory breath-hold, TWIST DCE-MRI (slice thickness 5.0 mm, coronal-plane resolution range), VIBE and post-VIBE (slice thickness 4.0 mm, resolution range). This is quite specific. - CT: Non-contrast low-dose CT from three Siemens Somatom scanners, inspiratory and expiratory breath-hold, soft kernel reconstruction, slice thickness 1.0 mm and in-plane resolution range. - Derived maps and processing: Description of how R(t), IRmax, PBF maps are computed (with citation to established methods [12]) and how PRM classifications and lobe segmentations are generated using in-house software (with references [3,15,10,9]). - Registration and preprocessing: Detailed description of co-registration strategy (affine + deformable registration TWIST/post-VIBE to VIBE; resampling CT to VIBE spacing; ANTs SyN rigid/affine/deformable registration; application of spatial transforms to segmentations and PRM maps; lung mask application; normalization to [-1,1]; cropping/padding to 60×256×256). This is very helpful for reproduction. - Data splitting: Exact split is given: 60 train, 14 validation, 30 test, with random splitting and explicit mention that the same split is used for both models to keep the test set unseen. This satisfies the requirement of defining data splits clearly, including independence of test data. Missing or weaker aspects: - Data availability: It is not stated whether the specific imaging dataset (or derived PRM maps) is publicly available, nor are URLs, accession numbers, or procedures for access given. Only the parent study (COSYCONET) is cited. For reproducibility outside the authors' group, this is a notable gap. - Fine-grained dataset composition: There is no breakdown of the number of samples per center, per GOLD stage, or class distribution (e.g., distribution of PRMnormal, PRMfSAD, PRMemphysema voxels). For voxel-level prediction tasks, class imbalance details would be useful but are not provided. - Split methodology details: While they state the split is random, there is no mention of stratification (e.g., by center or disease severity), random seed, or whether whole-patient-level splitting was used (this is implied but not explicitly stated). Still, since units are “patients”, it’s reasonable to assume each patient belongs to only one set, but explicit confirmation is absent. - Leakage considerations: They state they use the same split for both models and that the test set stays unseen, which partially addresses leakage. However, they do not explicitly discuss strategies to prevent potential leakage between train/val/test (e.g., if multiple scans per patient existed, which here seems not to be the case since it’s per patient, but it’s not fully clarified). Overall, the dataset is well characterized in terms of origin, imaging protocols, preprocessing, and split sizes. The main reproducibility limitations are lack of explicit data availability/access instructions and missing detailed label/class distributions and stratification specifics. Nonetheless, a researcher with access to a similar COSYCONET subset and following the described acquisition and preprocessing could reasonably reproduce the data side of the experiments. """
    # kimi score justification
    score_justification = """The paper provides a clear statement that the experiments were carried out on the BraTS 2023 dataset, explicitly citing the reference [2] (Baid et al., LNCS 14669, 2023) and giving the total number of samples (1,251 volumes). It also contrasts this with the older BraTS 2018 set (285 volumes) to justify the new benchmark. The exact splitting strategy is spelled out: 70 % training, 10 % validation, 20 % test. The authors further state that the same preprocessing and augmentation pipeline used in mmFormer [38] was adopted, and they explicitly mention that the data-split files are publicly released at the provided GitHub URL. These elements satisfy the core requirements of origin, size, and split definition What is missing are finer-grained dataset statistics and leakage safeguards. No table or paragraph summarises class balance (e.g., how many voxels or slices belong to edema, enhancing tumour, necrosis), patient-wise or subject-wise splitting is not asserted, and there is no explicit confirmation that all slices of a single patient are confined to one split. While the citation of BraTS 2023 implies that the imaging format is standard 3-D MRI with four modalities (FLAIR, T1, T1c, T2), the manuscript never states the voxel spacing, in-plane resolution, or whether any cases were excluded after quality control. Finally, no version number or checksum for the BraTS 2023 release is given, so a future researcher cannot be certain they are downloading the identical set In summary, the paper gives enough information to roughly reproduce the train/val/test split and to locate the dataset, but the absence of detailed class distributions, patient-wise split confirmation, and precise versioning leaves room for subtle mismatch or leakage that could hinder exact reproduction."""
    input_list = [
        {
            "role": "system",
            "content": score_justification + "\nCRITERIA DEFINITION: " + criteria,
        },
        {
            "role": "user",
            "content": score_prompt.format(criterion_name="dataset"),
        },
    ]

    # print(input_list)

    score_completion = client.chat.completions.create(
        model="kimi-k2-0905-preview",
        # model="kimi-k2-turbo-preview",
        messages=input_list,
        temperature=0.6,  # 0.6 for non-thinking - 1.0 for thinking
        logprobs=True,
        top_logprobs=top_logprobs,
        max_tokens=1,
    )

    choice = score_completion.choices[0]
    score_text = choice.message.content.strip()
    output_tokens_score = score_completion.usage.completion_tokens
    input_tokens_score = score_completion.usage.prompt_tokens
    print(f"\n=== SECOND CALL: Score ===(output tokens: {output_tokens_score})")
    print(f"{score_completion}")

    # ======== PARSE RESULT ========

    logprobs_content = choice.logprobs.content if choice.logprobs else None
    probs = []
    if logprobs_content and len(logprobs_content) > 0:
        # The first token should be the score number
        first_token = logprobs_content[0]
        if first_token.token.strip().isdigit():
            probs = [
                {"token": top.token, "logprob": top.logprob}
                for top in first_token.top_logprobs[:top_logprobs]
            ]

    if probs:
        print("\nTop Logprobs for the score:")
        import math

        for entry in probs:
            prob = math.exp(entry["logprob"]) * 100
            print(
                f"Token: {entry['token']:<5} | Logprob: {entry['logprob']:<10.4f} | Prob: {prob:>6.2f}%"
            )

        # take the first three token and get the final score as the sum of them times their probability
        score = sum(probs[:3]["token"] * probs[:3]["token"])
    else:
        print("Score token not found in logprobs.")

    try:
        score = int(score_text)
    except ValueError:
        score = -1  # Invalid score

    parsed_result = {
        "score_justification": score_justification,
        "score": score,
        "logprobs": probs,
    }

    result = {
        # "model": config.get("visual_name", config["model_key"]),
        "result": parsed_result,
        "input_tokens": input_tokens_score,  # + input_tokens_justification,
        "output_tokens": output_tokens_score,  # + output_tokens_justification,
    }
    print("\n=== FINAL RESULT ===")
    print(result)

    # print(json.dumps(result, indent=2))

    # total_tokens = justification_completion.usage.total_tokens + score_completion.usage.total_tokens
    # print(f"\nTotal tokens used (both calls): {total_tokens}")

    # if is_pdf:
    #     completion = kimi_files(
    #         client, PDF_DIR / "miccai_2025_0308_paper.pdf", system_prompt, model
    #     )
    # else:
    #     with open(PDF_DIR / "miccai_2025_0308_paper.txt", "r") as f:
    #         pdf_text = f.read()
    #         completion = kimi_standard(client, pdf_text, system_prompt, model)


def fill_evidence_locator():
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
    )
    file = "IM-Fuse_A_Mamba-based_Fusion_Block_for_Brain_Tumor_Segmentation_with_Incomplete_Modalities.pdf"

    checklist = {
        "models_and_algorithms": {
            "mathematical_setting": {
                "objective_function": bool,
                "loss_formulation": bool,
                "optimization_constraints": bool,
                "variable_definitions": bool,
                "model_assumptions": bool,
            },
            "algorithm_description": {
                "pseudocode": bool,
                "architecture_diagrams": bool,
                "update_rules": bool,
                "convergence_criteria": bool,
            },
        },
        "datasets": {
            "dataset_statistics": {
                "sample_counts": bool,
                "class_balance_distribution": "Balanced | Slight Imbalance | Severe Imbalance | Not Reported",
                "missing_data_rates": bool,
                "feature_dimensionality": bool,
                "data_leakage": "Checked & Mitigated | Potential Risk | Not Discussed",
            },
            "study_cohort_description": {
                "sample_taxonomy": bool,
                "inclusion_criteria": bool,
                "exclusion_criteria": bool,
                "population_size": bool,
            },
            "dataset_metadata": {
                "citations_and_doi": bool,
                "source_url": "Public | Request-only | Private | Broken Link",
                "license_type": "MIT | Apache 2.0 | CC-BY | Proprietary",
                "versioning": bool,
            },
            "data_collection_process": {
                "data_source": bool,
                "sampling_methodology": bool,
                "temporal_period": bool,
                "survey_design": bool,
                "cleaning_preprocessing": bool,
                "expert_review_process": bool,
            },
            "acquisition_setup": {
                "device_specifications": "Multiple Vendors | Multiple Devices | Single Device | Unknown",
                "environmental_conditions": bool,
                "calibration_procedures": bool,
                "acquisition_parameters": bool,
            },
            "annotation_instructions": {
                "labeling_guidelines": bool,
                "annotator_expertise": "Expert | Trained | Crowd | Algorithm",
                "consensus_protocols": bool,
                "inter_rater_reliability_score": "Strong | Weak | Not Reported",
            },
            "quality_control": {
                "outlier_detection_methods": bool,
                "manual_audits": bool,
                "validation_checks": bool,
                "automated_filtering": bool,
                "bias_analysis": bool,
            },
            "availability_and_ethics": {
                "repository_links": bool,
                "access_permissions": bool,
                "ethics_approval_id": "Provided | Generic statement | Missing | Not Applicable",
                "anonymization_protocol": bool,
            },
        },
        "code_artifacts": {
            "environment_setup": {
                "libraries_used": "Full | Partial | Missing",
                "version_numbers": "Full | Partial | Missing",
                "container_definitions": "Full | Partial | Missing | Not Applicable",
                "os_requirements": "Full | Partial | Missing | Not Applicable",
                "cuda_or_backend_info": bool,
                "random_state_seeding": "Full | Partial | Missing | Not Applicable",
            },
            "implementation_scripts": {
                "script_setup": bool,
                "training_logic": bool,
                "inference_logic": bool,
                "preprocessing_details": "Full | Partial | Missing | Not Applicable",
            },
            "reproducibility_artifacts": {
                "checkpoints": bool,
                "configuration_files": "Full | Partial | Missing | Not Applicable",
                "logging_outputs": "Full | Partial | Missing | Not Applicable",
                "documentation": "Full | Partial | Missing",
            },
            "code_availability": {
                "repository_link_status": [
                    "Active/Public",
                    "Broken",
                    "Request Access",
                    "None",
                ],
                "training_script": bool,
                "evaluation_script": bool,
                "checkpoints": bool,
                "preprocessing_details": "Full | Partial | Missing | Not Applicable",
                "logging_outputs": "Full | Partial | Missing | Not Applicable",
                "readme_quality": "Full | Partial | None",
                "license_type": "MIT | Apache 2.0 | CC-BY | Proprietary",
            },
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
                "baseline_tuning": bool,
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
                "sensitivity_analysis": bool,
            },
            "qualitative_analysis": {
                "failure_analysis": bool,
                "perturbation_testing": bool,
                "out_of_distribution_testing": bool,
                "subgroup_fairness_analysis": bool,
                "clinical_significance_discussion": bool,
                "results_discussion": bool,
            },
            "compute_and_resources": {
                "hardware_specification": bool,
                "environment_description": bool,
                "training_time": bool,
                "energy_cost_or_average_runtime": bool,
                "memory_usage": bool,
            },
        },
    }
    pdf_text = retrieve_file(client, file)
    system_prompt = """You are an expert reviewer of scientific paper specializing in Artificial Intelligence reproducibility. Your task  is to produce as output the following json with values compiled based on the content of the provided scientific paper synthetize in evidence locators list.
For each field in the JSON you have the type of value excepted. There are three main types:
- bool: the field should be marked as True if the information is present in the paper, False otherwise
- "Value A | Value B | Value C": the field should be marked with ONE of the provided categorical options, choose the option that fits best the content of the paper
- list[str]: the field should be marked with a LIST OF WORDS found in the paper that belong to the category indicated in the field
"""
    input_list = [
        {
            "role": "system",
            "content": system_prompt + json.dumps(checklist, indent=2),
        },
        {
            "role": "user",
            "content": pdf_text,
        },
    ]

    completion = client.chat.completions.create(
        model=model,
        messages=input_list,
        temperature=temperature,  # 0.6 for non-thinking - 1.0 for thinking
    )

    # choice = completion.choices[0].message.content
    output_tokens = completion.usage.completion_tokens
    input_tokens = completion.usage.prompt_tokens
    print(
        f"\n=== CALL ===(output tokens: {output_tokens}, input tokens: {input_tokens})"
    )
    print(f"{completion}")


def check_balance():
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
    )

    url = "https://api.openai.com/v1/users/me/balance"
    headers = {
        "Authorization": f"Bearer {client.api_key}",
    }

    response = requests.get(url, headers=headers)
    return response


import pymupdf


def underline_text(input_pdf, output_pdf, text_to_search: list, color: tuple) -> int:
    """
    Highlight all sentences of specific texts in a PDF document."""
    # 1. Open the document
    doc = pymupdf.open(input_pdf)
    instances = []
    for text in text_to_search:
        for page in doc:
            # 2. Find the coordinates (quads) of the text to search
            instances = page.search_for(text)

            # 3. Apply underline for each occurrence found
            for inst in instances:
                annot = page.add_highlight_annot(inst)
                annot.set_colors(stroke=color)
                annot.update()

    # 4. Save the result
    doc.save(output_pdf)
    doc.close()
    return len(instances)


if __name__ == "__main__":
    # main()
    # fill_evidence_locator()
    # print(check_balance())

    # from gitingest import ingest

    # url = "/home/dsantoli/papersnitch/IM-Fuse"
    # _, _, content = ingest(
    #     url,
    #     include_patterns=["*.md"],
    # )
    # code_filenames = from_doc_to_code(
    #     content, "https://github.com/AImageLab-zip/IM-Fuse"
    # )
    # summary, _, content = ingest(
    #     url,
    #     include_patterns=code_filenames,
    # )
    # print(summary)
    HIGHLIGHTING_COLOR = {
        "pink": (1.0, 0.0, 1.0),
        "green": (0.67, 1.0, 0.18),
        "yellow": (1.0, 1.0, 0.0),
        "cyan": (0.0, 1.0, 1.0),
        "orange": (1.0, 0.65, 0.0),
    }
    print(
        underline_text(
            "/home/dsantoli/papersnitch/app/media/pdf/µ_2_Tokenizer_Differentiable_Multi-Scale_Multi-Modal_Tokenizer_for_Radiology_Report__zFZkv6h.pdf",
            "/home/dsantoli/papersnitch/app/media/pdf/µ_2_Tokenizer_Differentiable_Multi-Scale_Multi-Modal_Tokenizer_for_Radiology_Report__zFZkv6h_underlined.pdf",
            ["""asd"""],
            HIGHLIGHTING_COLOR["orange"],
        )
    )


# ChatCompletion(
#     id="chatcmpl-6970e9201eda4bf7387410e3",
#     choices=[
#         Choice(
#             finish_reason="stop",
#             index=0,
#             logprobs=None,
#             message=ChatCompletionMessage(
#                 content='{"criterion":"Datasets and Splits","extracted":"We reproduce and extensively analyze the most relevant models using BraTS2023, which includes 1,251 volumes... We split the dataset5 into 70% for training, 10% for validation, and 20% for testing, and the model selected for evaluation on the test set was the one that achieved the highest metric on the validation set. 5Data splits are available at https://github.com/AImageLab-zip/IM-Fuse.","score_justification":"The paper explicitly names the dataset (BraTS2023), states the total number of volumes (1,251), and gives the exact percentages for the train/val/test split (70/10/20). It also provides a URL where the splits themselves can be downloaded. However, no further details are supplied: no citation or version number for BraTS2023, no summary statistics about class balance or image resolution, no statement about the splitting methodology (random, patient-wise, etc.), and no explicit mention of measures to avoid data leakage. Because the core information (dataset, size, and split proportions) is present but several standard details are missing, the description is insufficient for full reproduction without consulting the external link.","score":5}',
#                 refusal=None,
#                 role="assistant",
#                 annotations=None,
#                 audio=None,
#                 function_call=None,
#                 tool_calls=None,
#             ),
#         )
#     ],
#     created=1769007393,
#     model="kimi-k2-0905-preview",
#     object="chat.completion",
#     service_tier=None,
#     system_fingerprint=None,
#     usage=CompletionUsage(
#         completion_tokens=261,
#         prompt_tokens=10580,
#         total_tokens=10841,
#         completion_tokens_details=None,
#         prompt_tokens_details=None,
#         cached_tokens=512,
#     ),
# )
# ChoiceLogprobs(content=[ChatCompletionTokenLogprob(token='score', bytes=[115, 99, 111, 114, 101], logprob=-2.3841855067985307e-07, top_logprobs=[TopLogprob(token='score', bytes=[115, 99, 111, 114, 101], logprob=-2.3841855067985307e-07)]), ChatCompletionTokenLogprob(token='":', bytes=[34, 58], logprob=-3.576278118089249e-07, top_logprobs=[TopLogprob(token='":', bytes=[34, 58], logprob=-3.576278118089249e-07)]), ChatCompletionTokenLogprob(token='5', bytes=[53], logprob=-0.015113015659153461, top_logprobs=[TopLogprob(token='5', bytes=[53], logprob=-0.015113015659153461)])], refusal=None)
#
# RANDOM NUMBER REQUEST:
# Top 10 Logprobs for the score position:
# Token: 0     | Logprob: -1.2484    | Prob:  28.70%
# Token: 7     | Logprob: -1.4215    | Prob:  24.13%
# Token: 8     | Logprob: -1.8712    | Prob:  15.39%
# Token: 6     | Logprob: -2.4279    | Prob:   8.82%
# Token: 5     | Logprob: -2.5027    | Prob:   8.19%
# Token: 3     | Logprob: -2.5818    | Prob:   7.56%
# Token: 9     | Logprob: -3.5919    | Prob:   2.75%
# Token: 4     | Logprob: -3.6886    | Prob:   2.50%
# Token: 2     | Logprob: -4.7310    | Prob:   0.88%
# Token: 10    | Logprob: -4.9577    | Prob:   0.70%
# Token: 1     | Logprob: -6.4111    | Prob:   0.16%

# The paper provides a clear statement that the experiments were carried out on the BraTS 2023 dataset, explicitly citing the reference [2] (Baid et al., LNCS 14669, 2023) and giving the total number of samples (1,251 volumes). It also contrasts this with the older BraTS 2018 set (285 volumes) to justify the new benchmark. The exact splitting strategy is spelled out: 70 % training, 10 % validation, 20 % test. The authors further state that the same preprocessing and augmentation pipeline used in mmFormer [38] was adopted, and they explicitly mention that the data-split files are publicly released at the provided GitHub URL. These elements satisfy the core requirements of origin, size, and split definition What is missing are finer-grained dataset statistics and leakage safeguards. No table or paragraph summarises class balance (e.g., how many voxels or slices belong to edema, enhancing tumour, necrosis), patient-wise or subject-wise splitting is not asserted, and there is no explicit confirmation that all slices of a single patient are confined to one split. While the citation of BraTS 2023 implies that the imaging format is standard 3-D MRI with four modalities (FLAIR, T1, T1c, T2), the manuscript never states the voxel spacing, in-plane resolution, or whether any cases were excluded after quality control. Finally, no version number or checksum for the BraTS 2023 release is given, so a future researcher cannot be certain they are downloading the identical set In summary, the paper gives enough information to roughly reproduce the train/val/test split and to locate the dataset, but the absence of detailed class distributions, patient-wise split confirmation, and precise versioning leaves room for subtle mismatch or leakage that could hinder exact reproduction.
