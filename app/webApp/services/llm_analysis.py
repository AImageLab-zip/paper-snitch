"""
LLM Analysis Service for Paper Evaluation

This module provides functions to extract text from PDFs and analyze them
using various LLM models based on specific criteria.
"""

import logging
import time
from typing import Dict, Any, Optional

from openai import OpenAI
import json

logger = logging.getLogger(__name__)
from dotenv import load_dotenv

load_dotenv(".env.local")

from django.contrib.auth.models import User
from webApp.models import (
    Paper,
    Analysis,
    Criterion,
    AnalysisCriterion,
)
from webApp.functions import update_token
from pydantic import BaseModel, Field


class CriterionResponse(BaseModel):
    criterion: str = Field(..., description="The name of the criterion being evaluated")
    extracted: str = Field(
        ..., description="The exact text extracted from the paper/code"
    )
    score_explanation: str = Field(
        ..., description="Detailed explanation for the assigned score"
    )
    score: int = Field(..., description="Integer score between 0 and 10, or -1 for N/A")

    class Config:
        extra = "forbid"


def code_tool():
    """Define the code documentation tool for LLM."""
    tools = [
        {
            "type": "function",
            "name": "get_code_documentation",
            "description": 'Download and get code documentation from a repository URL formatted in a JSON with summary, tree and content fields. {"summary": summary, "tree": tree, "content": content}',
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL of the code repository.",
                    }
                },
                "required": ["url"],
            },
        }
    ]
    tool_instruction = """\n When you find a code repository link from ONLY github (eg. https://github.com/openai) call the function get_code_documentation with the url parameter set to the link found. The text returned from the tool is the documentation of the code. Use the documentation to provide a score in the `score` field and an explaination for the score given in the `score_explanation` field."""

    return tools, tool_instruction


def llm_analysis(
    client: OpenAI,
    system_prompt: str,
    pdf_text: str,
    config: dict,
    code_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Get JSON response from the LLM model analyzing the text gotten from a PDF.
    Args:
        client: The OpenAI client instance.
        system_prompt: The system prompt to set the context.
        pdf_text: The extracted text from the PDF.
        config: Configuration dictionary containing model details.
    Returns:
        Parsed JSON response from the LLM.
    """
    input_list = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": f"PAPER TEXT:\n{pdf_text}\nCODE REPOSITORY:\n{code_text or 'Not provided'}",
        },
    ]

    if "reasoning" in config:
        reasoning = {"effort": config["reasoning"].get("effort", "none")}

    code_text = None

    # GPT MODELS

    if config["model"].startswith("gpt"):
        ##Tool request:  WORK IN PROGRESS - DO NNOT USE IT YET ##
        if config["code_tool"]:
            ...
        #     tools, tool_instruction = code_tool()
        #     input_list[0]["content"] = input_list[0]["content"] + tool_instruction

        #     response = client.responses.create(
        #         model=config["model"],
        #         input=input_list,
        #         temperature=config.get("temperature", 1.0),
        #         reasoning=reasoning,
        #         # text=JSON_SCHEMA,
        #         text_format=PaperAnalysis,
        #         tools=tools,
        #     )

        #     input_list += response.output

        #     # Handle tool call
        #     for item in response.output:
        #         if item.type == "function_call":
        #             if item.name == "get_code":
        #                 if progress_callback:
        #                     progress_callback(
        #                         "LLM requesting code, starting ingestion process..."
        #                     )
        #                 args = json.loads(item.arguments)
        #                 print("=" * 50)
        #                 print(args)
        #                 code_text = get_code(**args)
        #                 paper = Paper.objects.filter(id=config["paper_id"]).first()
        #                 paper.code_text = code_text
        #                 paper.save(update_fields=["code_text"])
        #                 if progress_callback:
        #                     progress_callback(
        #                         "Ingestion completed successfully, continuing analysis..."
        #                     )

        #                 input_list.append(
        #                     {
        #                         "type": "function_call_output",
        #                         "call_id": item.call_id,
        #                         "output": json.dumps({"code": code_text}),
        #                     }
        #                 )

        #     response = client.responses.create(
        #         model=config["model"],
        #         input=input_list,
        #         temperature=config.get("temperature", 1.0),
        #         reasoning=reasoning,
        #         # text=JSON_SCHEMA,
        #         text_format=PaperAnalysis,
        #         tools=tools,
        #     )

        else:
            # regular request - Code already ingested or not available

            response = client.responses.parse(
                model=config["model"],
                input=input_list,
                temperature=config.get("temperature", 0.1),
                reasoning=reasoning,
                # text=JSON_SCHEMA,
                text_format=CriterionResponse,
                max_output_tokens=10000,
            )

        output_tokens = response.usage.output_tokens
        input_tokens = response.usage.input_tokens
        total_tokens = response.usage.total_tokens
        parsed_result = response.output_parsed

    # NON GPT MODELS ## WORK IN PROGRESS - DO NOT USE (C'è da creare un prompt per cui i modelli rispondano in formato JSON)##
    # elif config["model"].startswith("kimi-k2"):
    #     completion = client.chat.completions.create(
    #         model=config["model"],
    #         messages=input_list,
    #         temperature=config.get("temperature", 1.0),
    #     )
    #     response = completion.choices[0].message.content
    #     output_tokens = completion.usage.completion_tokens
    #     input_tokens = completion.usage.prompt_tokens
    #     total_tokens = completion.usage.total_tokens

    else:
        time.sleep(1)
        # create a dummy response as PaperAnalysis with empty fields
        parsed_result = CriterionResponse(
            criterion="Unknown",
            extracted="No information extracted for this criterion",
            score_explanation="No information extracted for this criterion",
            score=0,
        )
        input_tokens = 0
        output_tokens = 0
        total_tokens = 0

    update_token(total_tokens, config["token_var"])

    return {
        "model": config.get("visual_name", config["model_key"]),
        "result": parsed_result,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def pdf_analysis(
    client: OpenAI,
    system_prompt: str,
    pdf: str,
    config: dict,
    code_text: Optional[str] = None,
    output_format: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get JSON response from the LLM model analyzing a PDF file."""
    if config["model"].startswith("gpt"):
        print(f"PDF PATH: {pdf}")
        file = client.files.create(file=open(pdf, "rb"), purpose="user_data")
        input_list = [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_file",
                        "file_id": file.id,
                    },
                    {
                        "type": "input_text",
                        "text": f"CODE REPOSITORY:\n{code_text or 'Not provided'}",
                    },
                ],
            },
        ]

        if "reasoning" in config:
            reasoning = {"effort": config["reasoning"].get("effort", "none")}

        if output_format and output_format.lower() == "structured":
            response = client.responses.parse(
                model=config["model"],
                input=input_list,
                reasoning=reasoning,
                temperature=config.get("temperature", 0.1),
                text_format=CriterionResponse,
                max_output_tokens=10000,
            )
            parsed_result = response.output_parsed
        else:
            response = client.responses.create(
                model=config["model"],
                input=input_list,
                reasoning=reasoning,
                temperature=config.get("temperature", 0.1),
            )
            try:
                parsed_result = json.loads(response.output_text)
            except json.JSONDecodeError as e:
                print(f"JSON decode error: {e}")
                return {
                    "model": config.get("visual_name", config["model_key"]),
                    "result": None,
                    "input_tokens": None,
                    "output_tokens": None,
                }

        output_tokens = response.usage.output_tokens
        input_tokens = response.usage.input_tokens
        total_tokens = response.usage.total_tokens

    else:
        time.sleep(1)
        # create a dummy response as PaperAnalysis with empty fields
        parsed_result = CriterionResponse(
            criterion="Unknown",
            extracted="No information extracted for this criterion",
            score_explanation="No information extracted for this criterion",
            score=0,
        )
        input_tokens = 0
        output_tokens = 0
        total_tokens = 0

    update_token(total_tokens, config["token_var"])

    return {
        "model": config.get("visual_name", config["model_key"]),
        "result": parsed_result,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


def _save_analysis_to_db(
    paper_id: int, model_key: str, config: dict, result: dict, user_id: int = None
):
    """Save analysis results to the database.
    Args:
        paper_id: The ID of the Paper model instance.
        model_key: The key of the model used for analysis.
        config: Model configuration dictionary.
        result: The analysis result from llm_analysis or error dict.
        user_id: The ID of the user who initiated the analysis.
    """
    try:
        paper = Paper.objects.get(id=paper_id)
        user = User.objects.get(id=user_id) if user_id else None

        # Check if this is an error result
        if "error" in result and "result" not in result:
            Analysis.objects.create(
                paper=paper,
                user=user,
                model_name=config.get("visual_name", model_key),
                model_key=model_key,
                error=result["error"],
            )
            return

        # Extract data from successful result
        llm_response = result.get("result", {})

        # # Save code_url to Paper if extracted
        # code_data = llm_response.get("code", {})
        # if isinstance(code_data, dict):
        #     code_url = code_data.get("url")
        #     if (
        #         code_url
        #         and isinstance(code_url, str)
        #         and code_url.startswith("http")
        #         and paper.code_url == ""
        #     ):
        #         paper.code_url = code_url
        #         paper.save(update_fields=["code_url"])

        # # Save datasets to Dataset model
        # datasets_data = llm_response.get("datasets", {})
        # if isinstance(datasets_data, dict):
        #     datasets_list = datasets_data.get("extracted", [])
        #     if isinstance(datasets_list, list):
        #         for dataset_name in datasets_list:
        #             if dataset_name and isinstance(dataset_name, str):
        #                 dataset, _ = Dataset.objects.get_or_create(
        #                     name=dataset_name, defaults={"from_pdf": True}
        #                 )
        #                 dataset.papers.add(paper)

        # Create the Analysis instance
        analysis = Analysis.objects.create(
            paper=paper,
            user=user,
            model_name=config.get("visual_name", model_key),
            model_key=model_key,
            input_tokens=result.get("input_tokens"),
            output_tokens=result.get("output_tokens"),
            duration=result.get("duration"),
            raw_response=llm_response,
        )

        # Save each criterion result
        for criterion_key, criterion_data in llm_response.items():
            try:
                criterion = Criterion.objects.get(key=criterion_key)

                AnalysisCriterion.objects.create(
                    analysis=analysis,
                    criterion=criterion,
                    extracted=criterion_data.get("extracted", ""),
                    score_explanation=criterion_data.get("score_explanation", ""),
                    score=criterion_data.get("score", 0),
                )
            except Criterion.DoesNotExist:
                # Criterion not found in database, skip
                logger.warning(f"Criterion '{criterion_key}' not found in database")
                continue

    except Exception as e:
        logger.exception(f"Error saving analysis to database: {e}")
        return None

    return analysis


# def run_analysis_task(task_id: str):
#     """Run the analysis task in a background thread.
#     Args:
#         task_id: The task ID to run.
#     """

#     def _update_progress(step: str, increment: bool = True):
#         try:
#             task = AnalysisTask.objects.get(id=task_id)
#             task.current_step = step
#             if increment:
#                 task.completed_steps += 1
#             if task.total_steps > 0:
#                 task.progress = int((task.completed_steps / task.total_steps) * 100)
#             task.save(update_fields=["current_step", "completed_steps", "progress"])
#         except AnalysisTask.DoesNotExist:
#             pass

#     def _run():
#         try:
#             try:
#                 task = AnalysisTask.objects.get(id=task_id)
#                 task.status = "running"
#                 task.save(update_fields=["status"])

#                 pdf_text = task.paper.text
#                 paper_id = task.paper.id
#                 user_id = task.user.id if task.user else None
#                 selected_models = task.selected_models
#                 total_steps = task.total_steps
#                 completed_steps = task.completed_steps
#             except AnalysisTask.DoesNotExist:
#                 return

#             # Get model configs from database
#             model_configs = get_model_configs()

#             # Get system prompt
#             system_prompt = Prompt.objects.filter(name="system_prompt").first()
#             system_prompt = system_prompt.template + "\n" + get_criterions()

#             # Analyze with selected LLM models
#             results = {}

#             for model_key in selected_models:
#                 config = model_configs.get(model_key)
#                 if not config:
#                     continue
#                 visual_name = config.get("visual_name", model_key)
#                 _update_progress(f"Analyzing with {visual_name}...", increment=False)

#                 client = OpenAI(
#                     api_key=config["api_key"],
#                     base_url=config["base_url"],
#                 )
#                 # check if the code already exists in the paper
#                 _update_progress(f"Checking for pre-existing code...", increment=False)
#                 code_text = None
#                 paper = Paper.objects.filter(id=paper_id).first()
#                 if paper.code_text == "" or paper.code_text is None:
#                     if paper.code_url == "" or paper.code_url is None:
#                         # GITHUB url regex
#                         url_pattern = re.compile(
#                             r"https?://(?:www\.)?github\.com/[A-Za-z0-9-]{1,39}/[A-Za-z0-9_.-]+(?:\.git)?"
#                         )
#                         match = url_pattern.search(paper.text)
#                         url = match.group(0) if match else None
#                         if url:
#                             url = url.rstrip(".,;:!?)\"]'")
#                             paper.code_url = url

#                     # GITHUB ingestion

#                     if "github" in paper.code_url:
#                         _update_progress(
#                             f"Code not ingested, starting ingestion process...",
#                             increment=False,
#                         )
#                         code_text = get_code(paper.code_url)
#                         paper.code_text = code_text
#                         paper.save(update_fields=["code_text", "code_url"])
#                         config["code_tool"] = False

#                         _update_progress(
#                             f"Ingestion completed successfully, continuing analysis...",
#                             increment=False,
#                         )

#                     else:
#                         # To remove the line below after implement the tool code
#                         config["code_tool"] = False

#                         # TODO Abilitare code tool di GPT
#                         # config["code_tool"] = True
#                         # config["paper_id"] = paper_id

#                 else:
#                     code_text = paper.code_text
#                     config["code_tool"] = False

#                 _update_progress(
#                     f"Sending request to {visual_name} model...", increment=False
#                 )

#                 # Create a progress callback for detailed updates (no increment to prevent overflow)
#                 def model_progress(msg):
#                     _update_progress(
#                         f"[{completed_steps+1}/{total_steps}] {visual_name}: {msg}",
#                         increment=False,
#                     )

#                 result = llm_analysis(
#                     client,
#                     system_prompt,
#                     pdf_text,
#                     config,
#                     code_text=code_text,
#                     progress_callback=model_progress,
#                 )
#                 # pdf = Paper.objects.get(id=paper_id).file.url
#                 # # print("PDF PATH:", pdf)
#                 # result = pdf_analysis(
#                 #     client,
#                 #     system_prompt,
#                 #     "/app" + pdf,
#                 #     config,
#                 #     code_text=code_text,
#                 #     progress_callback=model_progress,
#                 # )

#                 result["result"] = result["result"].dict()

#                 results[model_key] = result

#                 # Save analysis to database
#                 _update_progress(
#                     f"Saving analysis results to database...", increment=False
#                 )
#                 analysis = _save_analysis_to_db(
#                     paper_id, model_key, config, result, user_id
#                 )

#                 if analysis:
#                     results[model_key]["final_score"] = analysis.final_score()

#                 _update_progress(f"Completed {visual_name}")

#             # Mark as completed
#             try:
#                 task = AnalysisTask.objects.get(id=task_id)
#                 task.status = "completed"
#                 task.progress = 100
#                 task.current_step = "Analysis complete"
#                 task.results = results
#                 task.save(
#                     update_fields=["status", "progress", "current_step", "results"]
#                 )
#             except AnalysisTask.DoesNotExist:
#                 pass

#         except Exception as e:
#             logger.exception(f"Error in analysis task {task_id}: {e}")
#             try:
#                 task = AnalysisTask.objects.get(id=task_id)
#                 task.status = "error"
#                 task.error = str(e)
#                 task.current_step = f"Error: {str(e)}"
#                 task.save(update_fields=["status", "error", "current_step"])
#             except AnalysisTask.DoesNotExist:
#                 pass

#     # Start background thread
#     thread = threading.Thread(target=_run, daemon=True)
#     thread.start()


# JSON Schema for structured model outputs
# JSON_SCHEMA = {
#     "format": {
#         "type": "json_schema",
#         "name": "paper_analysis",
#         "strict": True,
#         "schema": {
#             "type": "object",
#             "properties": {
#                 "code": {
#                     "type": "object",
#                     "description": "Code repository information extracted from the paper",
#                     "properties": {
#                         "url": {
#                             "type": "string",
#                             "description": "Code repository URL (e.g., GitHub link). Empty string if not found.",
#                         },
#                         "extracted": {
#                             "type": "string",
#                             "description": "Extracted text related to code availability, documentation, or instructions to access the code",
#                         },
#                         "score_explanation": {
#                             "type": "string",
#                             "description": "Explanation and motivation for the score given regarding code availability and documentation",
#                         },
#                         "score": {
#                             "type": "integer",
#                             "description": "Score indicating how well the paper addresses code availability and documentation",
#                         },
#                     },
#                     "required": ["url", "extracted", "score_explanation", "score"],
#                     "additionalProperties": False,
#                 },
#                 "datasets": {
#                     "type": "object",
#                     "description": "Datasets used in the paper",
#                     "properties": {
#                         "extracted": {
#                             "type": "array",
#                             "items": {"type": "string"},
#                             "description": "List of dataset names extracted from the paper",
#                         }
#                     },
#                     "required": ["extracted"],
#                     "additionalProperties": False,
#                 },
#                 "annotation": {
#                     "type": "object",
#                     "description": "Information about data annotation methodology",
#                     "properties": {
#                         "extracted": {
#                             "type": "string",
#                             "description": "Extracted text related to annotation methodology",
#                         },
#                         "score_explanation": {
#                             "type": "string",
#                             "description": "Explanation and motivation for the score given",
#                         },
#                         "score": {
#                             "type": "integer",
#                             "description": "Score indicating how well the paper addresses annotation",
#                         },
#                     },
#                     "required": ["extracted", "score_explanation", "score"],
#                     "additionalProperties": False,
#                 },
#                 "preprocessing": {
#                     "type": "object",
#                     "description": "Information about data preprocessing steps",
#                     "properties": {
#                         "extracted": {
#                             "type": "string",
#                             "description": "Extracted text related to preprocessing methodology",
#                         },
#                         "score_explanation": {
#                             "type": "string",
#                             "description": "Explanation and motivation for the score given",
#                         },
#                         "score": {
#                             "type": "integer",
#                             "description": "Score indicating how well the paper addresses preprocessing",
#                         },
#                     },
#                     "required": ["extracted", "score_explanation", "score"],
#                     "additionalProperties": False,
#                 },
#                 "evaluation": {
#                     "type": "object",
#                     "description": "Information about experimental evaluation setup",
#                     "properties": {
#                         "extracted": {
#                             "type": "string",
#                             "description": "Extracted text related to evaluation methodology",
#                         },
#                         "score_explanation": {
#                             "type": "string",
#                             "description": "Explanation and motivation for the score given",
#                         },
#                         "score": {
#                             "type": "integer",
#                             "description": "Score indicating how well the paper addresses evaluation",
#                         },
#                     },
#                     "required": ["extracted", "score_explanation", "score"],
#                     "additionalProperties": False,
#                 },
#                 "licensing": {
#                     "type": "object",
#                     "description": "Information about licensing and ethical considerations",
#                     "properties": {
#                         "extracted": {
#                             "type": "string",
#                             "description": "Extracted text related to licensing and ethical transparency",
#                         },
#                         "score_explanation": {
#                             "type": "string",
#                             "description": "Explanation and motivation for the score given",
#                         },
#                         "score": {
#                             "type": "integer",
#                             "description": "Score indicating how well the paper addresses licensing and ethics",
#                         },
#                     },
#                     "required": ["extracted", "score_explanation", "score"],
#                     "additionalProperties": False,
#                 },
#             },
#             "required": [
#                 "code",
#                 "datasets",
#                 "annotation",
#                 "preprocessing",
#                 "evaluation",
#                 "licensing",
#             ],
#             "additionalProperties": False,
#         },
#     }
# }

# json_object = {
#     "code": {
#         "url": "Code repository URL (e.g., GitHub link). Empty string if not found.",
#         "extracted": "Extracted text related to code availability, documentation, or instructions to access the code",
#         "score_explanation": "Explanation and motivation for the score given regarding code availability and documentation",
#         "score": "INTEGER Score indicating how well the paper addresses code availability and documentation",
#     },
#     "datasets": {"extracted": "List of dataset names extracted from the paper"},
#     "annotation": {
#         "extracted": "Extracted text related to annotation methodology",
#         "score_explanation": "Explanation and motivation for the score given",
#         "score": "INTEGER Score indicating how well the paper addresses annotation",
#     },
#     "preprocessing": {
#         "extracted": "Extracted text related to preprocessing methodology",
#         "score_explanation": "Explanation and motivation for the score given",
#         "score": "INTEGER Score indicating how well the paper addresses preprocessing",
#     },
#     "evaluation": {
#         "extracted": "Extracted text related to evaluation methodology",
#         "score_explanation": "Explanation and motivation for the score given",
#         "score": "INTEGER Score indicating how well the paper addresses evaluation",
#     },
#     "licensing": {
#         "extracted": "Extracted text related to licensing and ethical transparency",
#         "score_explanation": "Explanation and motivation for the score given",
#         "score": "INTEGER Score indicating how well the paper addresses licensing and ethics",
#     },
# }
