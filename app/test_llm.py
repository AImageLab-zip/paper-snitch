import json
import os
import sys
import time

from openai import OpenAI

# os.environ.setdefault(
#     "DJANGO_SETTINGS_MODULE",
#     os.getenv("DJANGO_SETTINGS_MODULE", "web.settings.development"),
# )
# from web.settings import BASE_DIR

# from webApp.models import Paper, Dataset, Conference
from dotenv import load_dotenv, set_key, get_key

load_dotenv("/home/dsantoli/papersnitch/.env.local")
# PDF_DIR = BASE_DIR / "media" / "pdfs"


api_key = os.getenv("BYTEPLUS_API_KEY")
base_url = "https://ark.ap-southeast.bytepluses.com/api/v3"


# ========== DEEPSEEK ==============
MODEL_CONFIGS = {
    "seed_flash": {
        "model": "seed-1-6-flash-250715",
        "var": "TOTAL_TOKEN_BYTEPLUS_SEED_FLASH",
        "thinking": False,
        "model_key": "seed_flash",
        "api_key": os.getenv("BYTEPLUS_API_KEY"),
        "base_url": "https://ark.ap-southeast.bytepluses.com/api/v3",
    },
    "r1": {
        "model": "deepseek-r1-250528",
        "var": "TOTAL_TOKEN_BYTEPLUS_SEED_FLASH",
        "thinking": False,
        "model_key": "r1",
        "api_key": os.getenv("BYTEPLUS_API_KEY"),
        "base_url": "https://ark.ap-southeast.bytepluses.com/api/v3",
    },
    # "deepseek31_T": {
    #     "model": "deepseek-v3-1-250821",
    #     "var": "TOTAL_TOKEN_BYTEPLUS_DEEPSEEK",
    #     "thinking": True,
    # },
    # "seed_NT": {
    #     "model": "seed-1-6-250915",
    #     "var": "TOTAL_TOKEN_BYTEPLUS_SEED",
    #     "thinking": False,
    # },
    # "seed_T": {
    #     "model": "seed-1-6-250915",
    #     "var": "TOTAL_TOKEN_BYTEPLUS_SEED",
    #     "thinking": True,
    # },
    # "gpt5.1": {
    #     "model": "gpt-5.1",
    #     "var": "TOTAL_TOKEN_OPENAI",
    #     "model_key": "gpt5.1",
    #     "api_key": os.getenv("OPENAI_API_KEY"),
    #     "base_url": "https://api.openai.com/v1",
    # },
    # "gpt5_mini": {
    #     "model": "gpt-5-mini",
    #     "var": "TOTAL_TOKEN_OPENAI_MINI",
    #     "model_key": "gpt5_mini",
    #     "api_key": os.getenv("OPENAI_API_KEY"),
    #     "base_url": "https://api.openai.com/v1",
    #     "temperature": 1,
    # },
    # "gemini2.5_flash": {
    #     "model": "gemini-2.5-flash",
    #     "var": "TOTAL_TOKEN_GEMINI",
    #     "model_key": "gemini2.5_flash",
    #     "api_key": os.getenv("GEMINI_API_KEY"),
    #     "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
    # },
    # "kimi_k2": {
    #     "model": "kimi-k2-250905",
    #     "var": "TOTAL_TOKEN_BYTEPLUS_KIMI_K2",
    #     "thinking": False,
    #     "model_key": "kimi_k2",
    #     "api_key": os.getenv("BYTEPLUS_API_KEY"),
    #     "base_url": "https://ark.ap-southeast.bytepluses.com/api/v3",
    # },
    # "deepseek3.1_NT": {
    #     "model": "deepseek-v3-1-250821",
    #     "var": "TOTAL_TOKEN_BYTEPLUS_DEEPSEEK",
    #     "thinking": False,
    #     "model_key": "deepseek31_NT",
    #     "api_key": os.getenv("BYTEPLUS_API_KEY"),
    #     "base_url": "https://ark.ap-southeast.bytepluses.com/api/v3",
    # },
}

# structure responses answer
"""
{
  "id": "resp_67ccd2bed1ec8190b14f964abc0542670bb6a6b452d3795b",
  "object": "response",
  "created_at": 1741476542,
  "status": "completed",
  "error": null,
  "incomplete_details": null,
  "instructions": null,
  "max_output_tokens": null,
  "model": "gpt-4.1-2025-04-14",
  "output": [
    {
      "type": "message",
      "id": "msg_67ccd2bf17f0819081ff3bb2cf6508e60bb6a6b452d3795b",
      "status": "completed",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "In a peaceful grove beneath a silver moon, a unicorn named Lumina discovered a hidden pool that reflected the stars. As she dipped her horn into the water, the pool began to shimmer, revealing a pathway to a magical realm of endless night skies. Filled with wonder, Lumina whispered a wish for all who dream to find their own hidden magic, and as she glanced back, her hoofprints sparkled like stardust.",
          "annotations": []
        }
      ]
    }
  ],
  "parallel_tool_calls": true,
  "previous_response_id": null,
  "reasoning": {
    "effort": null,
    "summary": null
  },
  "store": true,
  "temperature": 1.0,
  "text": {
    "format": {
      "type": "text"
    }
  },
  "tool_choice": "auto",
  "tools": [],
  "top_p": 1.0,
  "truncation": "disabled",
  "usage": {
    "input_tokens": 36,
    "input_tokens_details": {
      "cached_tokens": 0
    },
    "output_tokens": 87,
    "output_tokens_details": {
      "reasoning_tokens": 0
    },
    "total_tokens": 123
  },
  "user": null,
  "metadata": {}
}
"""

# structured chat.completions answer
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


def _update_token(tokens_used: int, var: str) -> int:
    """
     Update the cumulative token usage for a given LLM model.
    Args:
        tokens_used (int): The number of tokens used in the current API call.
        var (str): The environment variable name that tracks the cumulative token usage.
    Returns:
        int: The updated cumulative token usage.
    """

    current_total = get_key(".token_usage", var)
    if current_total is None:
        current_total = 0
    else:
        current_total = int(current_total)
    new_total = current_total + tokens_used
    set_key(".token_usage", var, str(new_total))
    os.environ[var] = str(new_total)
    return new_total


def json_response(
    client: OpenAI,
    system_prompt: str,
    user_prompt: str,
    config: dict,
    paper_id: str,
):
    """Function to get JSON response from the model based on the provided prompts and configuration.
    Args:
        client (OpenAI): The OpenAI client instance.
        system_prompt (str): The system prompt to set the context.
        user_prompt (str): The user prompt containing the question or instruction.
        config (dict): Configuration dictionary containing model details.
        paper_id (str): Identifier for the paper being processed.
    """
    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {"role": "user", "content": user_prompt},
    ]
    if "thinking" in config:
        if config["thinking"] == True:
            extra_body = {
                "thinking": {
                    "type": "enabled",  # Use the Deep Thinking capability.
                }
            }
        elif config["thinking"] == False:
            extra_body = {
                "thinking": {
                    "type": "disabled",  # Do not use the Deep Thinking capability.
                }
            }
    else:
        extra_body = {}

    iteration_start = time.perf_counter()

    if config["model"].startswith("kimi-k2"):
        completion = client.chat.completions.create(
            model=config["model"],
            messages=messages,
            temperature=0.0 if "temperature" not in config else config["temperature"],
            extra_body=extra_body,
        )
    else:
        completion = client.chat.completions.create(
            model=config["model"],
            messages=messages,
            temperature=0.0 if "temperature" not in config else config["temperature"],
            response_format={"type": "json_object"},
            extra_body=extra_body,
        )

    duration = time.perf_counter() - iteration_start

    try:
        response = json.loads(completion.choices[0].message.content)
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON for model {config['model_key']}: {e}")
        print(completion.choices[0].message.content)

    output_tokens = completion.usage.completion_tokens
    input_tokens = completion.usage.prompt_tokens
    total_tokens = completion.usage.total_tokens
    cumulative_tokens = _update_token(total_tokens, config["var"])

    # with open(PDF_DIR / f"evalscore_{paper_id}_{config['model_key']}.json", "w") as f:
    #     json.dump(response, f, indent=2)

    print(
        f"Model: {config['model_key']} - Input tokens: {input_tokens}, "
        f"Output tokens: {output_tokens}, Cumulative tokens: {cumulative_tokens}, "
        f"Time: {duration:.2f}s"
    )


JSON_FORMAT = """{
    "code": {
        "url": "Code url ONLY",
        "extracted": " If code is private provide instructions to access it, otherwise put the extracted text regards the documentation of the code"
        "score_explanation": "Motivations of the score given",
        "score": INTEGER_VALUE
    },
    "datasets": {
        "extracted": ["List of the datasets name extracted"]
    },
    "annotation": {
        "extracted": "Extracted text related to the annotation",
        "score_explanation": "Motivations of the score given",
        "score": INTEGER_VALUE
    },
    "preprocessing": {
        "extracted": "Extracted text related to the preprocessing",
        "score_explanation": "Motivations of the score given",
        "score": INTEGER_VALUE
    },
    "evaluation": {
        "extracted": "Extracted text related to the evaluation",
        "score_explanation": "Motivations of the score given",
        "score": INTEGER_VALUE
    },
    "licensing_and_ethical_transparency": {
        "extracted": "Extracted text related to the licensing_and_ethical_transparency",
        "score_explanation": "Motivations of the score given",
        "score": INTEGER_VALUE
    }
}"""


def main_old():
    # Prompt for the LLM
    criterions = """{
  "code": {
    "definition": "Only provide the link at the repository. If it's private also provide information on how to access it. If no code is provided put null.",
    "keywords": [
      "code",
      "repository",
      "github",
      "gitlab",
      "available"
    ]
  },

  "data": {
  "definition": "Only provide the names of the datasets used in the paper. If no dataset is used put null.",
    "keywords": [
        "data",
        "dataset"
        ]
  },
  "annotation": {
    "definition": "Information describing how data annotations or labels were created, validated, and quality-controlled. This includes: how labels were produced, who performed the annotation, what tools or platforms were used, what annotation guidelines were followed, the expertise or training of annotators, reported inter-annotator agreement metrics (e.g., Cohen's kappa, Fleiss' kappa, Krippendorff's alpha, percent agreement), how disagreements were resolved (consensus, arbitration, majority vote), and any procedures used to check or enforce annotation reliability.",
    "keywords": [
      "annotation",
      "labeling",
      "human raters",
      "dataset creation",
      "labeling guidelines",
      "agreement",
      "crowdworkers",
      "expert annotators",
      "quality control"
    ]
  },

  "preprocessing": {
    "definition": "Detailed description of all transformations applied to raw data before training or evaluation. This includes explicit preprocessing steps such as resampling, cropping, normalization, and augmentation; numerical parameters such as input dimensions, value ranges, and augmentation probabilities; description of the augmentation pipeline; motivations for each preprocessing step; and any software libraries, frameworks, or pipelines used.",
    "keywords": [
      "data preprocessing",
      "data preparation",
      "normalization",
      "augmentation",
      "resampling",
      "cropping",
      "feature scaling",
      "input processing"
    ]
  },

  "evaluation": {
    "definition": "Completeness and transparency of the experimental evaluation setup. This includes train/validation/test data splits, stratification, subject-wise splits, cross-validation strategies (e.g., k-fold, leave-one-out), performance metrics used, uncertainty or variability reporting (standard deviations, confidence intervals, repeated runs, random seeds), details of the experimental setup such as hyperparameters, epochs, hardware, search methods, and any robustness, ablation, or sensitivity analyses.",
    "keywords": [
      "experimental evaluation",
      "results",
      "validation protocol",
      "test split",
      "cross-validation",
      "performance reporting",
      "uncertainty",
      "experimental setup"
    ]
  },

  "licensing_and_ethical_transparency": {
    "definition": "Legal, ethical, and compliance information for datasets, code, and experiments involving human subjects. This includes dataset and code licensing terms (e.g., CC-BY, CC-BY-NC, MIT, GPL), any usage restrictions, ethical approvals or IRB statements, informed consent procedures, anonymization or pseudonymization methods, and discussions of privacy protection, risks, societal impact, bias, or limitations.",
    "keywords": [
      "ethical considerations",
      "IRB approval",
      "informed consent",
      "anonymization",
      "privacy",
      "licensing",
      "data release terms",
      "usage restrictions",
      "responsible use"
    ]
  }
}"""

    system_prompt = f"""You are an intelligent scientific paper information extractor, responsible for analyzing scientific papers provided and extract text from them based on specific criterions. Your reply can be only text in JSON format as specified below.
    Based on the criterion provided, one or more, you have to find and put in the answer the text related to the CRITERION (`extracted` field).
    CRITERION - {criterions}
    
    Beside that you have to provide a motivation of the score given in the `score_explanation` field.
    And at the end you should give a score (based ONLY on the text extracted) from 0 to 5 (integer value) based on how well the paper addresses the criterion related.
    0 means that the information are not provided at all, or the text can't be associated to the criterion. 5 means that criterion is very well covered and detailed based on the definition of the criterion. All the score from 1 to 4 are in between for texts that partially address the criterion or some important detaileds are missing.
    You have to put the score in the `score` key instead of INTEGER_VALUE.
    Please output your reply in the following JSON format:
    
    {JSON_FORMAT}
    
    Note: Your answer MUST contain ONLY the JSON with the text extracted from the paper in the `extracted` field and the `score` field, no other words or markdown symbols. Please place the information extracted from the paper in the `extracted` field and the score value in the `score` field. Not all the criterions have the `score` field, only the ones that need it.
    If you didn't find any information related to a specific criterion, set the `extracted` field to an empty string. and the `score` field to 0"""

    # Select the paper to process
    paper_list = [
        "miccai_2025_0752_paper.txt",
    ]
    for paper_file in paper_list:
        with open(BASE_DIR / "media" / "pdf" / paper_file, "r") as f:
            pdf_text = f.read()
        paper_id = paper_file[-14:-10]
        # Iterate over all model configurations and get JSON responses

        for _, config in MODEL_CONFIGS.items():
            client = OpenAI(
                api_key=config["api_key"],
                base_url=config["base_url"],
            )
            json_response(client, system_prompt, pdf_text, config, paper_id)


from pydantic import BaseModel, Field


class CriterionResponse(BaseModel):
    score: int = Field(..., description="Integer score between 0 and 10, or -1 for N/A")

    class Config:
        extra = "forbid"


def main():
    config = {
        "model": "gpt-4.1",
        "api_key_env_var": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "temperature": 0.1,
        "reasoning_effort": "none",
    }
    api_key = os.getenv("OPENAI_API_KEY")
    client = OpenAI(
        api_key=api_key,
        base_url=config["base_url"],
    )
    response = client.responses.create(
        model=config["model"],
        input="Answer with a number between 1 and 9, nothing else",
        reasoning=None,
        temperature=config.get("temperature", 0.1),
        top_logprobs=10,
    )

    output_tokens = response.usage.output_tokens
    input_tokens = response.usage.input_tokens
    total_tokens = response.usage.total_tokens

    logprobs = response.top_logprobs
    print(response)


# TEST PER VEDERE QUANTO OVERHEAD C'è NEI VARI MODELLI IN INPUT

# client = OpenAI(
#     api_key=api_key,
#     base_url=base_url,
# )
# for model_key, config in MODEL_CONFIGS.items():
#     iteration_start = time.perf_counter()
#     messages = [
#         {
#             "role": "system",
#             "content": "Your an intelligent assistant. Answer to questions",
#         },
#         {"role": "user", "content": "What is 1+1?"},
#     ]

#     if config["thinking"]:
#         extra_body = {
#             "thinking": {
#                 "type": "enabled",  # Use the Deep Thinking capability.
#             }
#         }
#     else:
#         extra_body = {
#             "thinking": {
#                 "type": "disabled",  # Do not use the Deep Thinking capability.
#             }
#         }

#     completion = client.chat.completions.create(
#         model=config["model"],
#         messages=messages,
#         temperature=0.0,
#         extra_body=extra_body,
#     )

#     response = completion.choices[0].message.content

#     duration = time.perf_counter() - iteration_start

#     output_tokens = completion.usage.completion_tokens
#     input_tokens = completion.usage.prompt_tokens
#     total_tokens = completion.usage.total_tokens
#     cumulative_tokens = _update_token(total_tokens, config["var"])

#     print(
#         f"Model: {config['model']} ({model_key}) Input tokens: {input_tokens}, "
#         f"Output tokens: {output_tokens}, Cumulative tokens: {cumulative_tokens}, "
#         f"Duration: {duration:.2f}s"
#     )
# exit(0)


def test_embedding():
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)

    response = client.embeddings.create(
        input="Your text string goes here", model="text-embedding-3-small"
    )

    print(response.data[0].embedding)


if __name__ == "__main__":
    test_embedding()
