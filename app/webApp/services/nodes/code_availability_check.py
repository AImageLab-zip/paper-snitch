import re
import json
import logging

from typing import Dict, Any

from django.utils import timezone
from openai import OpenAI
from pydantic import BaseModel, Field

from webApp.models import Paper
from workflow_engine.services.async_orchestrator import async_ops
from .shared_helpers import ingest_with_steroids

from webApp.services.pydantic_schemas import (
    OnlineCodeSearch,
    CodeAvailabilityCheck,
)
from webApp.services.graphs_state import PaperProcessingState

logger = logging.getLogger(__name__)


async def code_availability_check_node(
    state: PaperProcessingState,
) -> Dict[str, Any]:
    """
    Node B: Check code availability (can run in parallel to paper type classification).

    This lightweight node:
    1. Checks if code links exist in paper database or text
    2. If not found, performs LLM-powered online search
    3. Saves found URL to database if discovered online
    4. Returns code availability result

    Results are stored as NodeArtifacts.
    """
    node_id = "code_availability_check"
    logger.info(
        f"Node B: Starting code availability check for paper {state['paper_id']}"
    )

    # Get workflow node
    node = await async_ops.get_workflow_node(state["workflow_run_id"], node_id)

    # Update node status to running
    await async_ops.update_node_status(node, "running", started_at=timezone.now())
    await async_ops.create_node_log(node, "INFO", "Starting code availability check")

    try:
        # Check for previous analysis
        force_reprocess = state.get("force_reprocess", False)
        if not force_reprocess:
            previous = await async_ops.check_previous_analysis(
                state["paper_id"], node_id
            )
            if previous:
                logger.info(f"Found previous check from {previous['completed_at']}")
                await async_ops.create_node_log(
                    node, "INFO", f"Using cached result from run {previous['run_id']}"
                )

                result = CodeAvailabilityCheck(**previous["result"])
                await async_ops.create_node_artifact(node, "result", result)
                await async_ops.update_node_status(
                    node, "completed", completed_at=timezone.now()
                )

                return {"code_availability_result": result}

        # Get paper from database
        paper = await async_ops.get_paper(state["paper_id"])
        client = state["client"]
        model = state["model"]

        code_url = None
        found_online = False
        search_notes = ""

        # Step 1: Check if URL already exists in database
        if paper.code_url:
            code_url = paper.code_url
            search_notes = "Found in paper database"
            logger.info(f"Found code URL in database: {code_url}")
            await async_ops.create_node_log(
                node, "INFO", f"Code URL found in database: {code_url}"
            )

        # Step 2: If not in database, search in paper text
        if not code_url and paper.text:
            url_pattern = r"https?://(?:github\.com|gitlab\.com|bitbucket\.org|gitee\.com|codeberg\.org)/[\w\-]+/[\w\-]+"
            matches = re.findall(url_pattern, paper.text)

            if matches:
                # Multiple matches found - need to verify which is the correct one
                logger.info(
                    f"Found {len(matches)} repository URLs in paper text. Verifying which belongs to this paper..."
                )
                await async_ops.create_node_log(
                    node,
                    "INFO",
                    f"Found {len(matches)} repository URLs - checking each to find the correct one",
                )

                class RepoVerification(BaseModel):
                    is_official_repo: bool = Field(
                        description="True if this is the official code repo for the paper"
                    )
                    confidence: float = Field(
                        description="Confidence score 0.0-1.0",
                        ge=0.0,
                        le=1.0,
                    )
                    reasoning: str = Field(
                        description="Brief explanation of the decision"
                    )

                best_match = RepoVerification(
                    is_official_repo=False, confidence=0.0, reasoning=""
                )
                best_match_url = None

                for candidate_url in matches:
                    try:
                        logger.info(f"Checking repository: {candidate_url}")

                        # Clone and get README
                        summary, tree, content, clone_path = await ingest_with_steroids(
                            candidate_url,
                            max_file_size=100000,
                            include_patterns=["README*", "readme*"],
                            cleanup=True,  # Clean up after checking
                            get_tree=False,
                        )

                        if content and len(content) > 50:
                            # Use LLM to check if this repo is associated with this paper
                            verification_prompt = f"""You are verifying if a GitHub repository belongs to a specific research paper.

Paper Title: {paper.title}
Paper Authors: {getattr(paper, 'authors', 'Unknown')}

Repository URL: {candidate_url}
Repository README excerpt:
{content[:2000]}

Your task: Determine if this repository is the OFFICIAL code release for THIS specific paper, or if it's just cited/referenced as related work.

Indicators that it IS the official repo:
- README mentions the exact paper title
- README mentions the paper authors
- README says "code for our paper" or similar
- README links to this paper on arXiv/proceedings

Indicators that it is NOT the official repo:
- README describes a different paper/project
- Different authors
- Just a general tool/library cited as related work
- No mention of this specific paper

Respond with your assessment."""

                            response = client.responses.parse(
                                model=model,
                                input=[
                                    {"role": "user", "content": verification_prompt}
                                ],
                                text_format=RepoVerification,
                            )

                            verification = response.output_parsed
                            input_tokens = response.usage.input_tokens
                            output_tokens = response.usage.output_tokens

                            logger.info(
                                f"Verification for {candidate_url}: official={verification.is_official_repo}, confidence={verification.confidence}"
                            )
                            await async_ops.create_node_log(
                                node,
                                "INFO",
                                f"Repository {candidate_url}: {'OFFICIAL' if verification.is_official_repo else 'NOT official'} (confidence: {verification.confidence})",
                                {"reasoning": verification.reasoning},
                            )

                            if (
                                verification.is_official_repo
                                and verification.confidence > best_match.confidence
                            ):
                                best_match = verification
                                best_match_url = candidate_url

                    except Exception as e:
                        logger.warning(
                            f"Error verifying repository {candidate_url}: {e}"
                        )
                        await async_ops.create_node_log(
                            node,
                            "WARNING",
                            f"Could not verify {candidate_url}: {str(e)}",
                        )

                # After checking all candidates, select the best match
                if best_match.is_official_repo and best_match_url:
                    code_url = best_match_url
                    search_notes = f"Found in paper text (verified from {len(matches)} candidates, confidence: {best_match.confidence})"
                    logger.info(
                        f"Selected repository: {code_url} (confidence: {best_match.confidence})"
                    )
                    await async_ops.create_node_log(
                        node, "INFO", f"Selected verified repository: {code_url}"
                    )
                else:
                    # No match found
                    search_notes = f"Not found in paper text (unverified - None of {len(matches)} candidates has been selected)"
                    logger.info(
                        f"No verified match found among {len(matches)} candidates"
                    )

        # Step 3: If still not found, perform LLM-powered online search (last resort)
        if not code_url:
            logger.info(
                "Code URL not in database or paper text. Performing online search as last resort..."
            )
            await async_ops.create_node_log(
                node,
                "INFO",
                "Code not found in database or paper - attempting LLM-powered online search",
            )

            try:
                search_result = await search_code_online(paper, client, model, node)

                if search_result.repository_url and search_result.confidence >= 0.7:
                    code_url = search_result.repository_url
                    found_online = True
                    search_notes = f"Found online: {search_result.search_strategy} (confidence: {search_result.confidence})"

                    logger.info(
                        f"LLM found repository: {code_url} ({search_result.search_strategy})"
                    )
                    await async_ops.create_node_log(
                        node,
                        "INFO",
                        f"Online search successful: {code_url}",
                        {
                            "strategy": search_result.search_strategy,
                            "confidence": search_result.confidence,
                        },
                    )

                    # Save to database
                    from asgiref.sync import sync_to_async

                    @sync_to_async
                    def update_paper_code_url(paper_id, url):
                        paper = Paper.objects.get(id=paper_id)
                        paper.code_url = url
                        paper.save()

                    await update_paper_code_url(state["paper_id"], code_url)
                    logger.info(
                        f"Saved code URL to database for paper {state['paper_id']}"
                    )
                    await async_ops.create_node_log(
                        node, "INFO", "Code URL saved to paper database"
                    )
                else:
                    search_notes = search_result.notes
                    logger.info(f"Online search unsuccessful: {search_notes}")
                    await async_ops.create_node_log(
                        node, "WARNING", f"No code found online: {search_notes}"
                    )

            except Exception as e:
                logger.warning(f"Error in online search: {e}")
                await async_ops.create_node_log(
                    node, "WARNING", f"Online search error: {str(e)}"
                )
                search_notes = f"Online search failed: {str(e)}"

        # Step 4: If URL found, verify it's actually accessible and contains code
        verified_clone_path = None
        if code_url:
            logger.info(f"Verifying code URL accessibility: {code_url}")
            await async_ops.create_node_log(
                node, "INFO", f"Verifying repository accessibility"
            )

            try:
                # Quick HTTP HEAD check
                import requests

                response = requests.head(code_url, timeout=10, allow_redirects=True)

                if response.status_code == 404:
                    logger.warning(f"Repository not found (404): {code_url}")
                    await async_ops.create_node_log(
                        node, "WARNING", f"Repository not found (HTTP 404)"
                    )
                    result = CodeAvailabilityCheck(
                        code_available=False,
                        code_url=code_url,
                        found_online=found_online,
                        availability_notes=f"{search_notes}. Verification failed: Repository not found (404)",
                    )
                elif response.status_code >= 400:
                    logger.warning(
                        f"Repository not accessible (HTTP {response.status_code}): {code_url}"
                    )
                    await async_ops.create_node_log(
                        node,
                        "WARNING",
                        f"Repository not accessible (HTTP {response.status_code})",
                    )
                    result = CodeAvailabilityCheck(
                        code_available=False,
                        code_url=code_url,
                        found_online=found_online,
                        availability_notes=f"{search_notes}. Verification failed: HTTP {response.status_code}",
                    )
                else:
                    # URL is reachable, now verify it contains actual code files
                    logger.info(f"URL reachable, verifying code content...")
                    await async_ops.create_node_log(
                        node,
                        "INFO",
                        "URL reachable, performing shallow clone to verify code content",
                    )

                    try:
                        # Shallow clone to verify code content (lightweight check)
                        # Include common research code patterns: Python, JS, Java, C/C++, Go, Rust,
                        # Matlab, R, Julia, shell scripts, and Jupyter notebooks
                        # verify_code_accessibility
                        summary, tree, content, clone_path = await ingest_with_steroids(
                            code_url,
                            max_file_size=50000,
                            include_patterns=[
                                "*.py",
                                "*.js",
                                "*.ts",
                                "*.java",
                                "*.cpp",
                                "*.c",
                                "*.h",
                                "*.go",
                                "*.rs",
                                "*.m",
                                "*.R",
                                "*.jl",
                                "*.sh",
                                "*.bash",
                                "*.ipynb",
                                "*.scala",
                                "*.rb",
                            ],
                            cleanup=False,  # Keep clone for Node C
                            get_tree=False,  # Skip tree for speed
                        )

                        # Check if actual code files exist
                        if not content or len(content) < 100:
                            logger.warning(
                                f"Repository empty or no code files: {code_url}"
                            )
                            await async_ops.create_node_log(
                                node,
                                "WARNING",
                                "Repository empty or contains no code files",
                            )
                            # Cleanup failed clone
                            if clone_path and clone_path.parent.exists():
                                import shutil

                                shutil.rmtree(clone_path.parent)
                            result = CodeAvailabilityCheck(
                                code_available=False,
                                code_url=code_url,
                                found_online=found_online,
                                availability_notes=f"{search_notes}. Verification failed: No code files found",
                            )
                        else:
                            # Success - code verified!
                            verified_clone_path = (
                                str(clone_path) if clone_path else None
                            )
                            logger.info(
                                f"Repository verified: contains {len(content)//4} tokens of code"
                            )
                            await async_ops.create_node_log(
                                node,
                                "INFO",
                                f"Repository verified: contains code ({len(content)//4} tokens).",
                            )
                            result = CodeAvailabilityCheck(
                                code_available=True,
                                code_url=code_url,
                                found_online=found_online,
                                availability_notes=f"{search_notes}. Verified: Repository accessible and contains code.",
                                clone_path=verified_clone_path,
                            )

                    except Exception as e:
                        logger.warning(f"Error verifying repository content: {e}")
                        await async_ops.create_node_log(
                            node, "WARNING", f"Error during shallow clone: {str(e)}"
                        )
                        result = CodeAvailabilityCheck(
                            code_available=False,
                            code_url=code_url,
                            found_online=found_online,
                            availability_notes=f"{search_notes}. Verification failed: {str(e)}",
                        )

            except requests.Timeout:
                logger.warning(f"Repository request timed out: {code_url}")
                await async_ops.create_node_log(
                    node, "WARNING", "Repository request timed out"
                )
                result = CodeAvailabilityCheck(
                    code_available=False,
                    code_url=code_url,
                    found_online=found_online,
                    availability_notes=f"{search_notes}. Verification failed: Request timed out",
                )
            except Exception as e:
                logger.warning(f"Error verifying repository: {e}")
                await async_ops.create_node_log(
                    node, "WARNING", f"Error during verification: {str(e)}"
                )
                result = CodeAvailabilityCheck(
                    code_available=False,
                    code_url=code_url,
                    found_online=found_online,
                    availability_notes=f"{search_notes}. Verification error: {str(e)}",
                )
        else:
            # No URL found at all
            result = CodeAvailabilityCheck(
                code_available=False,
                code_url=None,
                found_online=False,
                availability_notes=search_notes
                or "No code repository found in paper, text, or online",
            )

        # Store result as artifact
        await async_ops.create_node_artifact(node, "result", result)

        # Log success
        await async_ops.create_node_log(
            node,
            "INFO",
            f"Code availability check complete: {'Found' if code_url else 'Not found'}",
            {"code_url": code_url, "found_online": found_online},
        )

        # Update node status
        await async_ops.update_node_status(
            node,
            "completed",
            completed_at=timezone.now(),
            output_data={
                "code_available": result.code_available,
                "code_url": code_url,
                "found_online": found_online,
            },
        )

        return {"code_availability_result": result}

    except Exception as e:
        logger.error(f"Error in code availability check: {e}", exc_info=True)

        # Log error
        await async_ops.create_node_log(
            node, "ERROR", str(e), {"traceback": str(e.__traceback__)}
        )

        # Update node status to failed
        await async_ops.update_node_status(
            node, "failed", completed_at=timezone.now(), error_message=str(e)
        )

        return {"errors": state.get("errors", []) + [f"Node B error: {str(e)}"]}


async def search_code_online(
    paper: Paper, client: OpenAI, model: str, node: Any = None
) -> OnlineCodeSearch:
    """
    Use LLM to search for code repository online with structured output.

    This function performs an intelligent search using the paper's metadata
    to find the most likely code repository.

    Args:
        paper: Paper object with title, abstract, authors
        client: OpenAI client
        model: Model name

    Returns:
        OnlineCodeSearch result with repository URL (if found) and metadata
    """
    # Construct detailed search prompt
    authors_str = ""
    if hasattr(paper, "authors") and paper.authors:
        authors_str = f"Authors: {paper.authors}\n"

    search_prompt = f"""You are a research code repository finder. Your task is to find the official code repository for this paper.

Paper Information:
Title: {paper.title}
{authors_str}Abstract: {paper.abstract or 'Not available'}

Search Strategy:
1. Search GitHub/GitLab/Bitbucket for repositories matching the paper title
2. Look for repositories from the paper's authors
3. Check for official implementations mentioned in the paper
4. Verify the repository actually corresponds to this specific paper

Platforms to search: GitHub, GitLab, Bitbucket, Gitee, Codeberg

Important:
- Only return a repository URL if you are reasonably confident it's the correct one
- The repository should match the paper title and methodology
- If uncertain or no repository found, set repository_url to null and confidence to 0.0
- Explain your search strategy and reasoning

Provide:
1. Repository URL (or null if not found/uncertain)
2. Confidence score (0.0 to 1.0) - only use >= 0.7 if very confident
3. Search strategy used
4. Notes about the search process"""

    try:
        response = client.responses.parse(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": "You are an expert at finding academic code repositories. Be conservative - only return URLs when you're confident they match the paper.",
                },
                {"role": "user", "content": search_prompt},
            ],
            tools=[{"type": "web_search_preview"}],
            text_format=OnlineCodeSearch,
            temperature=0.2,
        )

        result = response.output_parsed

        logger.info(
            f"Online search result: {result.repository_url or 'Not found'} (confidence: {result.confidence})"
        )
        await async_ops.create_node_log(
            node,
            "INFO",
            f"Online search result: {result.repository_url or 'Not found'} (confidence: {result.confidence}, input tokens: {response.usage.input_tokens}, output tokens: {response.usage.output_tokens})",
        )

        logger.info(f"Search strategy: {result.search_strategy}")

        return result

    except Exception as e:
        logger.error(f"Error in online code search: {e}")
        await async_ops.create_node_log(
            node,
            "INFO",
            f"Error in online code search: {e}",
        )
        return OnlineCodeSearch(
            repository_url=None,
            confidence=0.0,
            search_strategy="Error occurred",
            notes=f"Search failed: {str(e)}",
        )
