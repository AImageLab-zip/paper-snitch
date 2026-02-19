"""
Test script to create a paper and associate it with a workflow definition.

Creates a test paper in the MICCAI 2025 conference and associates it with
the reduced_paper_processing_pipeline workflow (without starting execution).

runnable using ./debug-dev-stack.sh exec 8900 ${STACK-NAME} django-web-dev uv run test_ingest_steroids.py

./debug-dev-stack.sh exec 8900 dev-santoli django-web-dev uv run test_ingest_steroids.py
"""

import asyncio
import os
import sys

# Django setup (must be done before importing Django models)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "web.settings.development")
import django

django.setup()

# Import models
from webApp.models import Paper, Conference
from workflow_engine.models import WorkflowDefinition, WorkflowRun


async def create_paper_with_workflow():
    """
    Create test Paper and associate it with a workflow (without starting execution).
    """
    print("\n" + "=" * 80)
    print("Creating test paper and associating with workflow")
    print("=" * 80)

    # Get existing MICCAI 2025 conference
    try:
        conference = await Conference.objects.aget(name="MICCAI 2025", acronym="MICCAI")
        print(f"✓ Found conference: {conference.name} ({conference.acronym})")
    except Conference.DoesNotExist:
        print("❌ ERROR: Conference 'MICCAI 2025' not found in database")
        raise

    # Create or get test paper
    paper, created = await Paper.objects.aget_or_create(
        title="a telegram bot for calling APIs",
        defaults={
            "abstract": "This paper presents a method for create a telegram bot "
            "serving as a pretext task for medical image analysis.",
            "code_url": "",  # Will be found during test
            "text": "This paper introduces a novel approach. Repository: I found this architecture that is useful for my workat the following repository: https://github.com/MarinCervinschi/DraftStream",
            "conference": conference,
        },
    )

    if created:
        print(f"✓ Created new test paper with ID: {paper.id}")
    else:
        print(f"✓ Using existing test paper with ID: {paper.id}")

    # Get existing workflow definition
    try:
        workflow_def = await WorkflowDefinition.objects.aget(
            name="reduced_paper_processing_pipeline"
        )
        print(
            f"✓ Found workflow definition: {workflow_def.name} (version {workflow_def.version})"
        )
    except WorkflowDefinition.DoesNotExist:
        print(
            "❌ ERROR: Workflow definition 'reduced_paper_processing_pipeline' not found in database"
        )
        raise

    # Create workflow run in pending status (not started)
    workflow_run = await WorkflowRun.objects.acreate(
        workflow_definition=workflow_def,
        status="pending",
        paper=paper,
        input_data={"model": "gpt-4o", "max_retries": 3, "force_reprocess": True},
    )

    print(f"✓ Created workflow run with ID: {workflow_run.id} (status: pending)")

    print("\n" + "=" * 80)
    print("✅ Setup completed successfully!")
    print("=" * 80)
    print(f"\nPaper ID: {paper.id}")
    print(f"Paper Title: {paper.title}")
    print(f"Conference: {conference.name}")
    print(f"Workflow: {workflow_def.name}")
    print(f"Workflow Run ID: {workflow_run.id}")
    print(f"Workflow Status: {workflow_run.status}")
    print("\n📝 The workflow has been associated but NOT started.")
    print("   To start execution, update the workflow run status to 'running'.")


if __name__ == "__main__":
    print("\n🚀 Starting paper creation...\n")
    asyncio.run(create_paper_with_workflow())
    print("\n✨ Done!\n")
