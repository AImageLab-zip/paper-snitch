empty_categories = {
    "Model/Algorithm Description": {
        "category": "Models and Algorithms",
        "description": "A description of the mathematical setting, algorithm, and/or model.",
        "embedding": [],
        "key_words": [],
    },
    "Assumptions": {
        "category": "Models and Algorithms",
        "description": "An explanation of any assumptions.",
        "embedding": [],
        "key_words": [],
    },
    "Software Framework": {
        "category": "Models and Algorithms",
        "description": "A declaration of what software framework and version you used.",
        "embedding": [],
        "key_words": [],
    },
    "Statistics": {
        "category": "Datasets",
        "description": "The relevant statistics, such as the number of examples.",
        "embedding": [],
        "key_words": [],
    },
    "Study Cohort": {
        "category": "Datasets",
        "description": "Description of the study cohort.",
        "embedding": [],
        "key_words": [],
    },
    "Existing Datasets Info": {
        "category": "Datasets",
        "description": "For existing datasets, citations as well as descriptions if they are not publicly available.",
        "embedding": [],
        "key_words": [],
    },
    "Data Collection Process": {
        "category": "Datasets",
        "description": "For new data collected, a complete description of the data collection process, such as descriptions of the experimental setup, device(s) used, image acquisition parameters, subjects/objects involved, instructions to annotators, and methods for quality control.",
        "embedding": [],
        "key_words": [],
    },
    "Download Link": {
        "category": "Datasets",
        "description": "A link to a downloadable version of the dataset (if public).",
        "embedding": [],
        "key_words": [],
    },
    "Ethics Approval": {
        "category": "Datasets",
        "description": "Whether ethics approval was necessary for the data.",
        "embedding": [],
        "key_words": [],
    },
    "Dependencies": {
        "category": "Code Related",
        "description": "Specification of dependencies.",
        "embedding": [],
        "key_words": [],
    },
    "Training Code": {
        "category": "Code Related",
        "description": "Training code.",
        "embedding": [],
        "key_words": [],
    },
    "Evaluation Code": {
        "category": "Code Related",
        "description": "Evaluation code.",
        "embedding": [],
        "key_words": [],
    },
    "Pre-trained Models": {
        "category": "Code Related",
        "description": "(Pre-)trained model(s).",
        "embedding": [],
        "key_words": [],
    },
    "Dataset for Code": {
        "category": "Code Related",
        "description": "Dataset or link to the dataset needed to run the code.",
        "embedding": [],
        "key_words": [],
    },
    "README & Results": {
        "category": "Code Related",
        "description": "README file including a table of results accompanied by precise commands to run to produce those results.",
        "embedding": [],
        "key_words": [],
    },
    "Hyperparameters": {
        "category": "Experimental Results",
        "description": "The range of hyperparameters considered, the method to select the best hyperparameter configuration, and the specification of all hyperparameters used to generate results.",
        "embedding": [],
        "key_words": [],
    },
    "Sensitivity Analysis": {
        "category": "Experimental Results",
        "description": "Information on sensitivity regarding parameter changes.",
        "embedding": [],
        "key_words": [],
    },
    "Training/Eval Runs": {
        "category": "Experimental Results",
        "description": "The exact number of training and evaluation runs.",
        "embedding": [],
        "key_words": [],
    },
    "Baseline Methods": {
        "category": "Experimental Results",
        "description": "Details on how baseline methods were implemented and tuned.",
        "embedding": [],
        "key_words": [],
    },
    "Data Splits": {
        "category": "Experimental Results",
        "description": "The details of training / validation / testing splits.",
        "embedding": [],
        "key_words": [],
    },
    "Evaluation Metrics": {
        "category": "Experimental Results",
        "description": "A clear definition of the specific evaluation metrics and/or statistics used to report results.",
        "embedding": [],
        "key_words": [],
    },
    "Central Tendency & Variation": {
        "category": "Experimental Results",
        "description": "A description of results with central tendency (e.g., mean) & variation (e.g., error bars).",
        "embedding": [],
        "key_words": [],
    },
    "Statistical Significance": {
        "category": "Experimental Results",
        "description": "An analysis of the statistical significance of reported differences in performance between methods.",
        "embedding": [],
        "key_words": [],
    },
    "Runtime / Energy Cost": {
        "category": "Experimental Results",
        "description": "The average runtime for each result, or estimated energy cost.",
        "embedding": [],
        "key_words": [],
    },
    "Memory Footprint": {
        "category": "Experimental Results",
        "description": "A description of the memory footprint.",
        "embedding": [],
        "key_words": [],
    },
    "Failure Analysis": {
        "category": "Experimental Results",
        "description": "An analysis of situations in which the method failed.",
        "embedding": [],
        "key_words": [],
    },
    "Computing Infrastructure": {
        "category": "Experimental Results",
        "description": "A description of the computing infrastructure used (hardware and software).",
        "embedding": [],
        "key_words": [],
    },
    "Clinical Significance": {
        "category": "Experimental Results",
        "description": "Discussion of clinical significance.",
        "embedding": [],
        "key_words": [],
    },
}


import os
import json
import numpy as np
from typing import List, Tuple, Dict
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables
load_dotenv("/home/dsantoli/papersnitch/.env.local")
api_key = os.getenv("OPENAI_API_KEY")

EMBEDDING_MODEL = "text-embedding-3-small"

# Initialize client globally or pass it around
client = OpenAI(
    api_key=api_key,
    base_url="https://api.openai.com/v1",
)


def get_embedding(
    text: str,
    dimensions: int = 256,
    model: str = EMBEDDING_MODEL,
) -> List[float]:
    """Wraps the OpenAI API to get embeddings."""
    text = text.replace("\n", " ")
    response = client.embeddings.create(
        input=[text], model=model, dimensions=dimensions
    )
    return response.data[0].embedding


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Calculates cosine similarity between two vectors."""
    a = np.array(a)
    b = np.array(b)
    if np.linalg.norm(a) == 0 or np.linalg.norm(b) == 0:
        return 0.0
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


def rank_categories_for_text(
    input_text: str,
    categories_dict: Dict,
    dimensions: int = 256,
    top_n: int = 10,
) -> List[Tuple[str, float]]:
    """
    Computes embedding for input_text, compares with cached category embeddings,
    and returns the top N most similar categories.
    """
    print(f"\n--- Processing Input: '{input_text}' ---")

    # 1. Get embedding for the input string
    try:
        input_embedding = get_embedding(input_text, dimensions)
    except Exception as e:
        print(f"Error getting embedding for input: {e}")
        return []

    scored_categories = []

    # 2. Calculate similarity for each category
    print("\nCalculated Similarities (Debug):")
    for cat_name, cat_data in categories_dict.items():
        # Check if embedding exists
        if "embedding" not in cat_data or not cat_data["embedding"]:
            print(f"Skipping {cat_name}: No embedding found.")
            continue

        cat_embedding = cat_data["embedding"]

        # Calculate Cosine Similarity
        score = cosine_similarity(input_embedding, cat_embedding)
        scored_categories.append((cat_name, score))

        # specific debug print to see the raw score
        print(f"  {score:.4f} | {cat_name}")

    # 3. Sort by score descending
    scored_categories.sort(key=lambda x: x[1], reverse=True)

    # 4. Return top N
    return scored_categories[:top_n]


def test_embedding_and_ranking(dimensions=256, annotation=""):
    """
    1. Generates embeddings for the categories (if not already done or loaded).
    2. Runs a test ranking on a sample string.
    """

    # Check if we need to generate embeddings for the categories first
    # (In a real app, you'd load 'categories_embeddings.json', but here we generate them if empty)
    print("Checking category embeddings...")

    try:
        with open(
            f"categories_embeddings_{dimensions}.json", "r", encoding="utf-8"
        ) as f:
            categories = json.load(f)
    except FileNotFoundError:
        categories = {
            "Model/Algorithm Description": {
                "category": "Models and Algorithms",
                "description": "A precise formalization of the mathematical framework and the algorithmic steps. Example: 'We define our loss function as the weighted sum of cross-entropy and a regularization term.'",
                "embedding": [],
                "key_words": [
                    "architecture",
                    "pseudocode",
                    "objective function",
                    "optimization",
                    "formulation",
                    "layer",
                ],
            },
            "Assumptions": {
                "category": "Models and Algorithms",
                "description": "A theoretical justification of the constraints or conditions under which the model is expected to perform. Example: 'We assume the data is independent and identically distributed (i.i.d.).'",
                "embedding": [],
                "key_words": [
                    "constraints",
                    "limitations",
                    "i.i.d.",
                    "linearity",
                    "prior distribution",
                    "simplification",
                ],
            },
            "Software Framework": {
                "category": "Models and Algorithms",
                "description": "The specific computational libraries and versioning required to replicate the environment. Example: 'The model was implemented using PyTorch v2.1 with CUDA 12.0 support.'",
                "embedding": [],
                "key_words": [
                    "PyTorch",
                    "TensorFlow",
                    "scikit-learn",
                    "Keras",
                    "version",
                    "library",
                    "environment",
                ],
            },
            "Statistics": {
                "category": "Datasets",
                "description": "Quantitative summary of the data used for training and testing. Example: 'The final dataset consists of 50,000 high-resolution images across 10 classes.'",
                "embedding": [],
                "key_words": [
                    "sample size",
                    "distribution",
                    "mean",
                    "median",
                    "cardinality",
                    "imbalance ratio",
                ],
            },
            "Study Cohort": {
                "category": "Datasets",
                "description": "Demographic or clinical characteristics of the subjects involved in the study. Example: 'The cohort included 200 participants aged 18-65 with no prior history of neurological disorders.'",
                "embedding": [],
                "key_words": [
                    "participants",
                    "demographics",
                    "inclusion criteria",
                    "exclusion criteria",
                    "population",
                    "subjects",
                ],
            },
            "Existing Datasets Info": {
                "category": "Datasets",
                "description": "Attribution and access details for established benchmarks. Example: 'We evaluated our method on the publicly available ImageNet-1K and COCO 2017 datasets.'",
                "embedding": [],
                "key_words": [
                    "benchmark",
                    "publicly available",
                    "citation",
                    "corpus",
                ],
            },
            "Data Collection Process": {
                "category": "Datasets",
                "description": "The methodology for gathering, labeling, and verifying new data. Example: 'Three expert radiologists independently annotated the scans, with conflicts resolved by a senior consultant.'",
                "embedding": [],
                "key_words": [
                    "labeling",
                    "annotation",
                    "crowdsourcing",
                    "sensors",
                    "acquisition",
                    "ground truth",
                    "quality control",
                ],
            },
            "Download Link": {
                "category": "Datasets",
                "description": "The persistent identifier or URL where the data can be accessed. Example: 'The processed dataset is hosted on Zenodo and can be accessed via the following DOI.'",
                "embedding": [],
                "key_words": [
                    "repository",
                    "URL",
                    "Zenodo",
                    "HuggingFace",
                    "access",
                    "DOI",
                    "hosting",
                ],
            },
            "Ethics Approval": {
                "category": "Datasets",
                "description": "Documentation regarding institutional review board (IRB) oversight and consent. Example: 'This study was approved by the Institutional Ethics Committee (Ref: 2024-051).'",
                "embedding": [],
                "key_words": [
                    "IRB",
                    "consent",
                    "privacy",
                    "anonymization",
                    "compliance",
                    "ethical guidelines",
                ],
            },
            "Dependencies": {
                "category": "Code Related",
                "description": "A list of external packages and system-level requirements. Example: 'All required Python packages are listed in the requirements.txt file provided in the repository.'",
                "embedding": [],
                "key_words": [
                    "packages",
                    "requirements.txt",
                    "conda",
                    "docker",
                    "environment.yml",
                    "installation",
                ],
            },
            "Training Code": {
                "category": "Code Related",
                "description": "The scripts and logic used to fit the model parameters. Example: 'The main training loop and data augmentation logic are located in train.py.'",
                "embedding": [],
                "key_words": [
                    "source code",
                    "scripts",
                    "training loop",
                    "fitting",
                    "optimization script",
                ],
            },
            "Evaluation Code": {
                "category": "Code Related",
                "description": "The scripts used to generate performance metrics from a trained model. Example: 'Run eval.py to generate the confusion matrix and F1-score for the test set.'",
                "embedding": [],
                "key_words": [
                    "inference",
                    "test script",
                    "validation",
                    "scoring",
                    "prediction",
                ],
            },
            "Pre-trained Models": {
                "category": "Code Related",
                "description": "Access to the serialized weights of the final model. Example: 'We provide pre-trained weights for the ResNet-50 backbone used in our experiments.'",
                "embedding": [],
                "key_words": [
                    "weights",
                    "checkpoints",
                    "model zoo",
                    "serialization",
                    "pth",
                    "onnx",
                    "h5",
                ],
            },
            "Dataset for Code": {
                "category": "Code Related",
                "description": "Specific instructions or subsets of data needed to execute the provided code. Example: 'A toy dataset is included to verify the pipeline functionality.'",
                "embedding": [],
                "key_words": [
                    "sample data",
                    "input format",
                    "data loader",
                    "preprocessing script",
                ],
            },
            "README & Results": {
                "category": "Code Related",
                "description": "Comprehensive documentation for reproducing the paper's table of results. Example: 'The README contains a step-by-step guide to reproducing the results in Table 1.'",
                "embedding": [],
                "key_words": [
                    "documentation",
                    "usage",
                    "reproducibility",
                    "CLI",
                    "commands",
                    "setup",
                ],
            },
            "Hyperparameters": {
                "category": "Experimental Results",
                "description": "The configuration space and tuning strategy for model constants. Example: 'We performed a grid search over learning rates [1e-3, 1e-4] and batch sizes [32, 64].'",
                "embedding": [],
                "key_words": [
                    "learning rate",
                    "batch size",
                    "epochs",
                    "grid search",
                    "random search",
                    "tuning",
                ],
            },
            "Sensitivity Analysis": {
                "category": "Experimental Results",
                "description": "An investigation into how much the output changes with respect to parameter variations. Example: 'Figure 4 illustrates model robustness when varying the noise threshold.'",
                "embedding": [],
                "key_words": [
                    "ablation",
                    "robustness",
                    "variance",
                    "stability",
                    "parameter sweep",
                ],
            },
            "Training/Eval Runs": {
                "category": "Experimental Results",
                "description": "The number of independent iterations performed to ensure reliability. Example: 'Results are averaged over 5 independent runs with different random seeds.'",
                "embedding": [],
                "key_words": [
                    "iterations",
                    "seeds",
                    "replicates",
                    "averaging",
                    "trials",
                ],
            },
            "Baseline Methods": {
                "category": "Experimental Results",
                "description": "Comparison against state-of-the-art or standard techniques. Example: 'Our model significantly outperforms the baseline Random Forest implementation.'",
                "embedding": [],
                "key_words": [
                    "SOTA",
                    "benchmarking",
                    "comparison",
                    "competitors",
                    "state-of-the-art",
                ],
            },
            "Data Splits": {
                "category": "Experimental Results",
                "description": "The partitioning of data to avoid leakage and ensure generalization. Example: 'Data was split into 80% training, 10% validation, and 10% held-out test sets.'",
                "embedding": [],
                "key_words": [
                    "cross-validation",
                    "k-fold",
                    "hold-out",
                    "stratification",
                    "test set",
                ],
            },
            "Evaluation Metrics": {
                "category": "Experimental Results",
                "description": "The mathematical definitions used to quantify performance. Example: 'We report the Area Under the Receiver Operating Characteristic (AUROC) curve.'",
                "embedding": [],
                "key_words": [
                    "accuracy",
                    "precision",
                    "recall",
                    "F1-score",
                    "RMSE",
                    "mAP",
                    "dice coefficient",
                ],
            },
            "Central Tendency & Variation": {
                "category": "Experimental Results",
                "description": "Statistical reporting of average performance and its spread. Example: 'The model achieved an accuracy of 92.5% ± 0.4% across all folds.'",
                "embedding": [],
                "key_words": [
                    "mean",
                    "standard deviation",
                    "confidence interval",
                    "error bars",
                    "percentile",
                ],
            },
            "Statistical Significance": {
                "category": "Experimental Results",
                "description": "Hypothesis testing to confirm that improvements are not due to chance. Example: 'The p-value was calculated using a two-tailed t-test, yielding p < 0.05.'",
                "embedding": [],
                "key_words": [
                    "p-value",
                    "t-test",
                    "Wilcoxon",
                    "ANOVA",
                    "statistically significant",
                ],
            },
            "Runtime / Energy Cost": {
                "category": "Experimental Results",
                "description": "The computational efficiency or environmental impact of the method. Example: 'Inference takes approximately 15ms per image on a single GPU.'",
                "embedding": [],
                "key_words": [
                    "latency",
                    "throughput",
                    "carbon footprint",
                    "wattage",
                    "execution time",
                ],
            },
            "Memory Footprint": {
                "category": "Experimental Results",
                "description": "The peak RAM or VRAM consumption during execution. Example: 'The model requires a maximum of 8GB of VRAM during the training phase.'",
                "embedding": [],
                "key_words": [
                    "VRAM",
                    "RAM",
                    "parameters",
                    "size",
                    "peak memory",
                    "compressed",
                ],
            },
            "Failure Analysis": {
                "category": "Experimental Results",
                "description": "A qualitative or quantitative look at edge cases and errors. Example: 'The model struggles with low-contrast images, as seen in the error analysis section.'",
                "embedding": [],
                "key_words": [
                    "error analysis",
                    "misclassification",
                    "outliers",
                    "edge cases",
                    "false positives",
                ],
            },
            "Computing Infrastructure": {
                "category": "Experimental Results",
                "description": "The hardware environment used for experiments. Example: 'All experiments were conducted on an NVIDIA A100 GPU with 40GB of memory.'",
                "embedding": [],
                "key_words": ["GPU", "CPU", "cluster", "node", "TPU", "workstation"],
            },
            "Clinical Significance": {
                "category": "Experimental Results",
                "description": "The real-world impact and practical utility in a medical or specialized context. Example: 'The reduction in false negatives could decrease the rate of unnecessary biopsies.'",
                "embedding": [],
                "key_words": [
                    "utility",
                    "patient outcome",
                    "deployment",
                    "workflow",
                    "relevance",
                ],
            },
        }

        # Simple check: if the first category has no embedding, we generate all.
        first_cat = list(categories.keys())[0]
        if not categories[first_cat]["embedding"]:
            print("Embeddings missing. Generating embeddings for all categories...")
            for category_name, category_info in categories.items():
                # Construct the rich text representation for the category
                text_context = (
                    category_name
                    + " "
                    + category_info["description"]
                    + " "
                    + " ".join(category_info["key_words"])
                )

                response = client.embeddings.create(
                    input=text_context,
                    model=EMBEDDING_MODEL,
                    dimensions=dimensions,
                )
                if dimensions == 0:
                    dimensions = len(response.data[0].embedding)
                category_info["embedding"] = response.data[0].embedding

            # Save them so we don't have to pay for them again next time
            with open(
                f"categories_embeddings_{dimensions}.json", "w", encoding="utf-8"
            ) as f:
                json.dump(categories, f, indent=4)
                print(f"Saved categories_embeddings_{dimensions}.json")
        else:
            print("Embeddings found in memory.")

    # --- TEST THE RANKING ---

    top_results = rank_categories_for_text(annotation, categories, dimensions, top_n=10)

    print(
        f"\n\n=== Top 10 Recommendations for: '{annotation}' with dimensions= {dimensions} ==="
    )
    for rank, (name, score) in enumerate(top_results, 1):
        print(f"{rank}. {name} (Similarity: {score:.4f})")


if __name__ == "__main__":
    dimensions = 1024  # max 1536
    annotation = "It contains 500 MRI scans collected from 3 hospitals."
    test_embedding_and_ranking(dimensions=dimensions, annotation=annotation)

"""

=== Top 10 Recommendations for: 'It contains 500 MRI scans collected from 3 hospitals.' with dimensions= 256 ===
1. Data Collection Process (Similarity: 0.3637)
2. Statistics (Similarity: 0.3345)
3. Training/Eval Runs (Similarity: 0.3341)
4. Study Cohort (Similarity: 0.3270)
5. Existing Datasets Info (Similarity: 0.3175)
6. Computing Infrastructure (Similarity: 0.2870)
7. Data Splits (Similarity: 0.2730)
8. Central Tendency & Variation (Similarity: 0.2660)
9. Ethics Approval (Similarity: 0.2634)
10. Evaluation Metrics (Similarity: 0.2614)

=== Top 10 Recommendations for: 'It contains 500 MRI scans collected from 3 hospitals.' with dimensions= 1024 ===
1. Data Collection Process (Similarity: 0.3632)
2. Existing Datasets Info (Similarity: 0.3122)
3. Statistics (Similarity: 0.3118)
4. Study Cohort (Similarity: 0.2641)
5. Computing Infrastructure (Similarity: 0.2459)
6. Central Tendency & Variation (Similarity: 0.2249)
7. Pre-trained Models (Similarity: 0.2241)
8. README & Results (Similarity: 0.2164)
9. Ethics Approval (Similarity: 0.2137)
10. Training/Eval Runs (Similarity: 0.2056)

=== Top 10 Recommendations for: 'It contains 500 MRI scans collected from 3 hospitals.' with dimensions= 1536 ===
1. Data Collection Process (Similarity: 0.3570)
2. Statistics (Similarity: 0.3092)
3. Existing Datasets Info (Similarity: 0.2884)
4. Study Cohort (Similarity: 0.2578)
5. Computing Infrastructure (Similarity: 0.2252)
6. Ethics Approval (Similarity: 0.2218)
7. README & Results (Similarity: 0.2111)
8. Central Tendency & Variation (Similarity: 0.2084)
9. Pre-trained Models (Similarity: 0.2006)
10. Training/Eval Runs (Similarity: 0.1983)

"""
