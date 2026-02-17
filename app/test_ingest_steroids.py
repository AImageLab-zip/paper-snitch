"""
Test script for code_availability_check_node and analyze_repository_comprehensive functions.

Tests the enhanced repository ingestion and code availability checking.

runnable using ./debug-dev-stack.sh exec 8900 ${STACK-NAME} django-web-dev uv run test_ingest_steroids.py

./debug-dev-stack.sh exec 8900 dev-santoli django-web-dev uv run test_ingest_steroids.py
"""

import asyncio
import os
import sys
import json
from pathlib import Path
from typing import Dict, Any

# Django setup (must be done before importing Django models)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "web.settings.dev")
import django

django.setup()

from django.utils import timezone
from openai import OpenAI

# Import the functions we're testing
from webApp.services.paper_processing_workflow import (
    code_availability_check_node,
    analyze_repository_comprehensive,
    PaperProcessingState,
)

# Import models
from webApp.models import Paper
from workflow_engine.models import (
    WorkflowDefinition,
    WorkflowRun,
    WorkflowNode,
)


async def setup_test_data(test_url: str) -> Dict[str, Any]:
    """
    Create test Paper and Workflow objects in the database.

    Returns a dict with paper_id, workflow_run, and node IDs.
    """
    print("\n" + "=" * 80)
    print("SETUP: Creating test data in database")
    print("=" * 80)

    # Create or get test paper
    paper, created = await Paper.objects.aget_or_create(
        title="Test Paper: Brain Age Prediction as Pretext Task",
        defaults={
            "abstract": "This paper presents a method for brain age prediction using deep learning, "
            "serving as a pretext task for medical image analysis.",
            "code_url": "https://github.com/TasneemN/BrainAgePrediction_asPretextTask",  # Will be found during test
            "text": f"This paper introduces a novel approach. Repository: {test_url}",
        },
    )

    if created:
        print(f"✓ Created new test paper with ID: {paper.id}")
    else:
        print(f"✓ Using existing test paper with ID: {paper.id}")

    # Create workflow definition for paper processing
    workflow_def, _ = await WorkflowDefinition.objects.aget_or_create(
        name="test_paper_processing",
        version="1",
        defaults={
            "description": "Three-node workflow: paper type classification, code availability check, and conditional code repository analysis",
            "dag_structure": {
                "edges": [
                    {
                        "to": "code_availability_check",
                        "from": "paper_type_classification",
                        "type": "sequential",
                    },
                    {
                        "to": "code_repository_analysis",
                        "from": "code_availability_check",
                        "type": "conditional",
                        "condition": "code_available AND paper_type NOT IN (theoretical, dataset)",
                    },
                ],
                "nodes": [
                    {
                        "id": "paper_type_classification",
                        "type": "python",
                        "config": {},
                        "handler": "webApp.services.paper_processing_workflow.paper_type_classification_node",
                        "description": "Classify paper type (dataset/method/both/theoretical/unknown)",
                    },
                    {
                        "id": "code_availability_check",
                        "type": "python",
                        "config": {},
                        "handler": "webApp.services.paper_processing_workflow.code_availability_check_node",
                        "description": "Check if code repository exists (database/text/online search)",
                    },
                    {
                        "id": "code_repository_analysis",
                        "type": "python",
                        "config": {},
                        "handler": "webApp.services.paper_processing_workflow.code_repository_analysis_node",
                        "description": "Analyze repository and compute reproducibility score (conditional)",
                    },
                ],
            },
        },
    )

    print(f"✓ Created/found workflow definition: {workflow_def.name}")

    # Create workflow run
    workflow_run = await WorkflowRun.objects.acreate(
        workflow_definition=workflow_def,
        status="running",
        paper=paper,
        input_data={"model": "gpt-4o", "max_retries": 3, "force_reprocess": True},
    )

    print(f"✓ Created workflow run with ID: {workflow_run.id}")

    # Create workflow nodes
    node_availability = await WorkflowNode.objects.acreate(
        workflow_run=workflow_run,
        node_id="code_availability_check",
        status="pending",
    )

    node_analysis = await WorkflowNode.objects.acreate(
        workflow_run=workflow_run,
        node_id="code_repository_analysis",
        status="pending",
    )

    print(f"✓ Created workflow nodes")

    return {
        "paper": paper,
        "workflow_run": workflow_run,
        "node_availability": node_availability,
        "node_analysis": node_analysis,
    }


async def test_functions():
    """Test code_availability_check_node and analyze_repository_comprehensive."""

    # Configuration
    test_url = "https://github.com/TasneemN/BrainAgePrediction_asPretextTask"

    # Get OpenAI API key from environment
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY environment variable not set")
        print("Please set it with: export OPENAI_API_KEY='your-key-here'")
        return

    # Initialize OpenAI client
    client = OpenAI(api_key=api_key)
    model = "gpt-4o-mini"  # Using mini for testing to save costs

    print("=" * 80)
    print("Testing Repository Ingestion Functions")
    print("=" * 80)
    print(f"\nRepository URL: {test_url}")
    print(f"Model: {model}\n")

    # Setup test data
    test_data = await setup_test_data(test_url)
    paper = test_data["paper"]
    workflow_run = test_data["workflow_run"]

    # Step 1: Test code_availability_check_node
    print("\n" + "=" * 80)
    print("STEP 1: Testing code_availability_check_node")
    print("=" * 80)

    # Create PaperProcessingState
    state: PaperProcessingState = {
        "workflow_run_id": str(workflow_run.id),
        "paper_id": paper.id,
        "current_node_id": "code_availability_check",
        "client": client,
        "model": model,
        "force_reprocess": True,  # Force reprocessing for testing
        "paper_type_result": None,
        "code_availability_result": None,
        "code_reproducibility_result": None,
        "errors": [],
    }

    try:
        print(f"\nCalling code_availability_check_node with:")
        print(f"  - Paper ID: {paper.id}")
        print(f"  - Workflow Run ID: {workflow_run.id}")
        print(f"  - Force Reprocess: True")

        result = await code_availability_check_node(state)

        print("\n✅ code_availability_check_node completed successfully!")

        availability_result = result.get("code_availability_result")
        if availability_result:
            print(f"\nCode Availability Results:")
            print(f"  - Code Available: {availability_result.code_available}")
            print(f"  - Code URL: {availability_result.code_url}")
            print(f"  - Found Online: {availability_result.found_online}")
            print(f"  - Notes: {availability_result.availability_notes}")
        else:
            print("⚠️  No availability result returned")
            return

    except Exception as e:
        print(f"\n❌ code_availability_check_node failed with error:")
        print(f"   {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        return

    # Check if code is available before proceeding
    if not availability_result.code_available:
        print("\n⚠️  Code not available, skipping comprehensive analysis.")
        return

    # Step 2: Test analyze_repository_comprehensive
    print("\n" + "=" * 80)
    print("STEP 2: Testing analyze_repository_comprehensive")
    print("=" * 80)

    try:
        code_url = availability_result.code_url

        print(f"\nCalling analyze_repository_comprehensive with:")
        print(f"  - Code URL: {code_url}")
        print(f"  - Paper ID: {paper.id}")
        print(f"  - Model: {model}")

        # Refresh paper from database to get updated code_url
        paper = await Paper.objects.aget(id=paper.id)

        analysis_result = await analyze_repository_comprehensive(
            code_url=code_url,
            paper=paper,
            client=client,
            model=model,
            clone_path=None,  # Let it clone fresh
            node=test_data["node_analysis"],  # Pass the analysis node for logging
        )

        print("\n✅ analyze_repository_comprehensive completed successfully!")
        print("\nAnalysis Results:")
        print("-" * 80)

        # Extract and display results
        if "included_patterns" in analysis_result:
            print(f"Included Patterns: {analysis_result['included_patterns']}")
        if "excluded_patterns" in analysis_result:
            print(f"Excluded Patterns: {analysis_result['excluded_patterns']}")

        # Show analysis text preview
        if "analysis_text" in analysis_result:
            analysis_text = analysis_result["analysis_text"]
            preview_length = min(500, len(analysis_text))
            print(f"\nAnalysis Text Preview ({len(analysis_text)} chars total):")
            print(analysis_text[:preview_length])
            if len(analysis_text) > preview_length:
                print("...")

        # Show token usage
        if "input_tokens" in analysis_result:
            print(f"\nInput Tokens: {analysis_result['input_tokens']}")
        if "output_tokens" in analysis_result:
            print(f"Output Tokens: {analysis_result['output_tokens']}")

        # Show reproducibility score if available
        if "reproducibility_score" in analysis_result:
            score = analysis_result["reproducibility_score"]
            print(f"\n🎯 Reproducibility Score: {score}/10")

    except Exception as e:
        print(f"\n❌ analyze_repository_comprehensive failed with error:")
        print(f"   {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        return

    print("\n" + "=" * 80)
    print("✅ All tests completed successfully!")
    print("=" * 80)

    # Cleanup message
    print("\n📝 Note: Test data remains in database for inspection.")
    print(f"   Paper ID: {paper.id}")
    print(f"   Workflow Run ID: {workflow_run.id}")


if __name__ == "__main__":
    print("\n🚀 Starting test...\n")
    asyncio.run(test_functions())
    print("\n✨ Test finished!\n")
