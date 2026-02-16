"""
Test script for verify_code_accessibility and analyze_repository_comprehensive functions.

Tests the enhanced repository ingestion with the gitingest repository:
https://github.com/coderamp-labs/gitingest

runnable using ./debug-dev-stack.sh exec 8900 ${STACK-NAME} django-web-dev uv run test_ingest_steroids.py

./debug-dev-stack.sh exec 8900 dev-santoli django-web-dev uv run test_ingest_steroids.py
"""

import asyncio
import os
import sys
import json
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent / "app"))

# Django setup
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webApp.settings")
import django

django.setup()

from openai import OpenAI


# Import the functions we're testing
from webApp.services.paper_processing_workflow import (
    verify_code_accessibility,
    analyze_repository_comprehensive,
)


async def test_functions():
    """Test verify_code_accessibility and analyze_repository_comprehensive."""

    # Configuration
    test_url = "https://github.com/Siyou-Li/u2Tokenizer"

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

    # Step 1: Test verify_code_accessibility
    print("\n" + "=" * 80)
    print("STEP 1: Testing verify_code_accessibility")
    print("=" * 80)

    try:
        verify_result = await verify_code_accessibility(test_url, client, model)

        print("\n✅ verify_code_accessibility completed successfully!")
        print(f"\nAccessible: {verify_result.get('accessible')}")
        print(f"Notes: {verify_result.get('notes')}")
        print(f"Found Online: {verify_result.get('found_online')}")

        clone_path = verify_result.get("clone_path")
        if clone_path:
            print(f"Clone Path: {clone_path}")
            print(f"Clone exists: {clone_path.exists() if clone_path else 'N/A'}")
        else:
            print("Clone Path: None (repository cleaned up)")

    except Exception as e:
        print(f"\n❌ verify_code_accessibility failed with error:")
        print(f"   {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        return

    # Check if accessible before proceeding
    if not verify_result.get("accessible"):
        print("\n⚠️  Repository not accessible, stopping test.")
        return

    # Step 2: Test analyze_repository_comprehensive
    print("\n" + "=" * 80)
    print("STEP 2: Testing analyze_repository_comprehensive")
    print("=" * 80)

    # Create a mock Paper object for testing
    class Paper:
        def __init__(self):
            self.title = "Gitingest: A tool for ingesting git repositories"
            self.abstract = "Gitingest is a command-line tool that analyzes git repositories and generates comprehensive documentation."
            self.text = None
            self.code_url = test_url

    mock_paper = Paper()

    try:
        # Pass the clone_path from verify_code_accessibility
        clone_path = verify_result.get("clone_path")

        print(f"\nUsing clone_path: {clone_path}")
        print(f"Clone path exists: {clone_path.exists() if clone_path else 'N/A'}")

        analysis_result = await analyze_repository_comprehensive(
            test_url, mock_paper, client, model, clone_path=clone_path
        )

        print("\n✅ analyze_repository_comprehensive completed successfully!")
        print("\nAnalysis Results:")
        print("-" * 80)

        included = analysis_result.get("included_patterns", [])
        excluded = analysis_result.get("excluded_patterns", [])
        analysis = analysis_result.get("analysis_text", "")
        analysis_length = len(analysis)
        input_tokens = analysis_result.get("input_tokens")
        output_tokens = analysis_result.get("output_tokens")
        code_length = analysis_result.get("code_retrieved", {})

        print(f"Content Preview:\n{analysis}")
        print(f"Analysis Length: {analysis_length}")
        print(f"Included Patterns: {included}")
        print(f"Excluded Patterns: {excluded}")
        print(f"Input Tokens: {input_tokens}")
        print(f"Output Tokens: {output_tokens}")
        print(f"Code Retrieved (length): {code_length}")

    except Exception as e:
        print(f"\n❌ analyze_repository_comprehensive failed with error:")
        print(f"   {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        return

    print("\n" + "=" * 80)
    print("✅ All tests completed successfully!")
    print("=" * 80)


if __name__ == "__main__":
    print("\n🚀 Starting test...\n")
    asyncio.run(test_functions())
    print("\n✨ Test finished!\n")
