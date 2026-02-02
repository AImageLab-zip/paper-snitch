# webApp/tasks.py
from celery import shared_task
from .models import AnalysisTask, Paper, Prompt, Criterion
from .services.llm_analysis import (
    get_model_configs,
    llm_analysis,
    pdf_analysis,
    _save_analysis_to_db,
)

from webApp.functions import analyze_code
from openai import OpenAI
import re
import logging

import concurrent.futures
import time

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def run_analysis_celery_task(self, task_id):
    """
    Background worker process for running LLM analysis on papers.
    Uses Celery with Redis as the message broker.
    """
    try:
        task = AnalysisTask.objects.get(id=task_id)
        task.status = "running"
        task.save()

        # Extract task parameters from the AnalysisTask model
        selected_models = task.selected_models
        paper_id = task.paper_id
        user_id = task.user_id
        total_steps = task.total_steps
        completed_steps = task.completed_steps

        # Get paper and its PDF file path or the text (based on the function we want to use)
        paper = Paper.objects.get(id=paper_id)
        pdf_text = paper.text
        pdf_path = paper.file.path if paper.file else None

        if not pdf_path:
            raise ValueError(f"Paper {paper_id} does not have a PDF file attached")

        # Helper to update DB progress so your JS polling still works
        def _update_progress(step, increment=True):
            nonlocal completed_steps
            t = AnalysisTask.objects.get(id=task_id)
            t.current_step = step
            if increment:
                completed_steps += 1
                t.completed_steps = completed_steps
            if t.total_steps > 0:
                t.progress = int((t.completed_steps / t.total_steps) * 100)
            t.save()

        # Get model configs from database
        model_configs = get_model_configs()

        # all_criterions = Criterion.objects.all().order_by("id")
        # TEST TODO REMOVE IT
        all_criterions = Criterion.objects.filter(key__in=["evaluation"]).order_by("id")

        total_models = len(selected_models)
        total_criterions = all_criterions.count()

        # if paper.code_url == "" or paper.code_url is None:
        #     code_result = analyze_code(paper.code_url)

        results = {}

        for model_idx, model_key in enumerate(selected_models):
            config = model_configs.get(model_key)

            iteration_start = time.perf_counter()

            if not config:
                logger.warning(f"Model config not found for key: {model_key}")
                continue
            visual_name = config.get("visual_name", model_key)
            _update_progress(f"Analyzing with {visual_name}...", increment=False)

            # check if the code already exists in the paper
            _update_progress(f"Checking for pre-existing code...", increment=False)
            code_text = None

            if paper.code_text == "" or paper.code_text is None:
                if paper.code_url == "" or paper.code_url is None:
                    # GITHUB url regex
                    github_pattern = re.compile(
                        r"https?://(?:www\.)?github\.com/[A-Za-z0-9-]{1,39}/[A-Za-z0-9_.-]+(?:\.git)?"
                    )
                    if paper.text:
                        match = github_pattern.search(paper.text)
                        url = match.group(0) if match else None
                        if url:
                            url = url.rstrip(".,;:!?)\"]'")
                            paper.code_url = url
                    # Others urls
                    # TODO add url field in paper model to save them
                    url_pattern = re.compile(r"https?://[^\s]+")

                    if paper.text:
                        raw_urls = url_pattern.findall(paper.text)
                        paper.urls = [url.rstrip(".,;:!?)\"]'") for url in raw_urls]
                    else:
                        paper.urls = []

                # GITHUB ingestion
                if paper.code_url and "github" in paper.code_url:
                    _update_progress(
                        f"Code not ingested, starting ingestion process...",
                        increment=False,
                    )
                    analysis_result = analyze_code(paper.code_url)
                    code_text = analysis_result["content"]
                    code_errors = analysis_result["code_errors"]
                    print(f"Code ingestion errors: {code_errors}")
                    paper.code_text = code_text
                    paper.save(update_fields=["code_text", "code_url"])
                    config["code_tool"] = False

                    _update_progress(
                        f"Ingestion completed successfully, continuing analysis...",
                        increment=False,
                    )

                else:
                    # To remove the line below after implement the tool code
                    config["code_tool"] = False

                    # TODO Abilitare code tool di GPT
                    # config["code_tool"] = True
                    # config["paper_id"] = paper_id

            else:
                code_text = paper.code_text
                config["code_tool"] = False

            _update_progress(
                f"Sending request to {visual_name} model...", increment=False
            )
            model_aggregated_result = {}
            sum_input_tokens = 0
            sum_output_tokens = 0

            def process_single_criterion(crit, crit_idx):
                """
                Helper function to run inside a thread.
                Captures outer scope variables (client, pdf_path or pdf_text, code_text, etc.)
                """
                # Format prompt
                # Get system prompt
                system_prompt = (
                    Prompt.objects.filter(name="system_prompt")
                    .values_list("template", flat=True)
                    .first()
                )
                formatted_prompt = system_prompt.format(
                    criterion_name=crit.name, criterion_description=crit.description
                )

                if crit == "code":

                    input_list = [
                        {
                            "role": "system",
                            "content": formatted_prompt,
                        },
                        {
                            "role": "user",
                            "content": f"CODE REPOSITORY:\n{code_text or 'Not provided'}",
                        },
                    ]
                else:
                    input_list = [
                        {
                            "role": "system",
                            "content": formatted_prompt,
                        },
                        {
                            "role": "user",
                            "content": f"PAPER TEXT:\n{pdf_text}",
                        },
                    ]

                # response = llm_analysis(
                #     client, prompt, config, code_text=code_text
                # )

                # Call LLM
                client = OpenAI(
                    api_key=config["api_key"],
                    base_url=config["base_url"],
                )
                # TODO switch between llm_analysis and pdf_analysis based on if we want to use text or pdf
                # response = llm_analysis(
                #     client, formatted_prompt, pdf_text, config, code_text=code_text
                # )
                response = pdf_analysis(
                    client, formatted_prompt, pdf_path, config, code_text=code_text
                )

                # Process result
                res_obj = response["result"]
                if hasattr(res_obj, "model_dump"):
                    clean_result = res_obj.model_dump()
                elif hasattr(res_obj, "dict"):
                    clean_result = res_obj.dict()
                else:
                    clean_result = res_obj

                return {
                    "key": crit.key,
                    "name": crit.name,
                    "clean_result": clean_result,
                    "input_tokens": response["input_tokens"],
                    "output_tokens": response["output_tokens"],
                }

            # Use ThreadPoolExecutor to run criterion calls in parallel
            # Adjust max_workers based on your API Rate Limits (e.g., 5 or 10)
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                # Submit all tasks
                future_to_crit = {
                    executor.submit(process_single_criterion, crit, idx): crit
                    for idx, crit in enumerate(all_criterions)
                }

                completed_count = 0

                # Process results as they complete
                for future in concurrent.futures.as_completed(future_to_crit):
                    try:
                        data = future.result()

                        # Aggregate Data
                        model_aggregated_result[data["key"]] = data["clean_result"]
                        sum_input_tokens += data["input_tokens"]
                        sum_output_tokens += data["output_tokens"]

                        # Update Progress (Safe to do here in Main Thread)
                        completed_count += 1
                        _update_progress(
                            f"[{model_idx + 1}/{total_models}] {visual_name}: Completed {data['name']} ({completed_count}/{total_criterions})",
                            increment=False,
                        )

                    except Exception as exc:
                        # Handle exceptions nicely so one failure doesn't crash the whole model
                        crit_failed = future_to_crit[future]
                        logger.error(
                            f"Criterion {crit_failed.name} generated an exception: {exc}"
                        )

            # 5. Prepare final structure for database compatibility
            # _save_analysis_to_db expects the criteria as top-level keys in result['result']

            duration = round(time.perf_counter() - iteration_start, 2)
            final_model_payload = {
                "model": config.get("visual_name", config["model_key"]),
                "result": model_aggregated_result,
                "input_tokens": sum_input_tokens,
                "output_tokens": sum_output_tokens,
                "duration": duration,
            }

            results[model_key] = final_model_payload

            # 6. Save the full analysis (all criteria) to the DB for this model
            _update_progress(f"Saving {visual_name} results...", increment=False)
            analysis = _save_analysis_to_db(
                paper_id, model_key, config, final_model_payload, user_id
            )

            if analysis:
                results[model_key]["final_score"] = analysis.final_score()

            _update_progress(f"Completed {visual_name}", increment=True)

        # Save results to task
        task = AnalysisTask.objects.get(id=task_id)
        task.results = results
        task.status = "completed"
        task.progress = 100
        task.save()

    except Exception as e:
        logger.exception(f"Error in analysis task {task_id}: {str(e)}")
        AnalysisTask.objects.filter(id=task_id).update(status="error", error=str(e))
