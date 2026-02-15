#!/usr/bin/env python
"""
Script to view detailed code reproducibility analysis for a paper.
Usage: python view_analysis.py <paper_id>
"""
import sys
import os
import django

# Setup Django
sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'web.settings.dev')
django.setup()

from workflow_engine.models import WorkflowRun, NodeArtifact
import json

def view_analysis(paper_id):
    # Get the latest run for the paper
    run = WorkflowRun.objects.filter(paper_id=paper_id).order_by('-created_at').first()
    
    if not run:
        print(f"No workflow runs found for paper {paper_id}")
        return
    
    print(f"\n{'='*80}")
    print(f"Latest Analysis for Paper {paper_id}: {run.paper.title}")
    print(f"Run ID: {run.id}")
    print(f"Status: {run.status.upper()}")
    print(f"Created: {run.created_at}")
    print(f"{'='*80}\n")
    
    # Get code reproducibility analysis artifact
    try:
        node = run.nodes.get(node_id='code_reproducibility_analysis')
        artifact = NodeArtifact.objects.get(node=node, name='result')
        
        print("CODE REPRODUCIBILITY ANALYSIS")
        print("="*80)
        
        data = artifact.inline_data
        
        # Code availability
        print("\n1. CODE AVAILABILITY")
        print("-" * 40)
        code_avail = data.get('code_availability', {})
        print(f"Available: {code_avail.get('code_available')}")
        print(f"URL: {code_avail.get('code_url')}")
        print(f"Found Online: {code_avail.get('found_online')}")
        print(f"Notes: {code_avail.get('availability_notes')}")
        
        # Repository structure
        if data.get('repository_structure'):
            print("\n2. REPOSITORY STRUCTURE")
            print("-" * 40)
            struct = data['repository_structure']
            print(f"Standalone: {struct.get('is_standalone')}")
            print(f"Base Repository: {struct.get('base_repository')}")
            print(f"Has Requirements: {struct.get('has_requirements')}")
            print(f"Requirements Match: {struct.get('requirements_match_imports')}")
            if struct.get('requirements_issues'):
                print(f"Issues: {', '.join(struct['requirements_issues'])}")
        
        # Code components
        if data.get('code_components'):
            print("\n3. CODE COMPONENTS")
            print("-" * 40)
            comp = data['code_components']
            print(f"Training Code: {comp.get('has_training_code')}")
            if comp.get('training_code_paths'):
                print(f"  Paths: {', '.join(comp['training_code_paths'])}")
            print(f"Evaluation Code: {comp.get('has_evaluation_code')}")
            if comp.get('evaluation_code_paths'):
                print(f"  Paths: {', '.join(comp['evaluation_code_paths'])}")
            print(f"Documented Commands: {comp.get('has_documented_commands')}")
            print(f"  Location: {comp.get('command_documentation_location')}")
        
        # Artifacts
        if data.get('artifacts'):
            print("\n4. ARTIFACTS")
            print("-" * 40)
            art = data['artifacts']
            print(f"Checkpoints: {art.get('has_checkpoints')}")
            if art.get('checkpoint_locations'):
                print(f"  Locations: {', '.join(art['checkpoint_locations'])}")
            print(f"Dataset Links: {art.get('has_dataset_links')}")
            print(f"Dataset Coverage: {art.get('dataset_coverage')}")
            if art.get('dataset_links'):
                for ds in art['dataset_links']:
                    print(f"  - {ds.get('name', 'Unknown')}: {ds.get('url', 'N/A')}")
        
        # Documentation
        if data.get('documentation'):
            print("\n5. DOCUMENTATION & REPRODUCIBILITY")
            print("-" * 40)
            doc = data['documentation']
            print(f"README: {doc.get('has_readme')}")
            print(f"Results Table: {doc.get('has_results_table')}")
            print(f"Reproduction Commands: {doc.get('has_reproduction_commands')}")
            print(f"\n⭐ REPRODUCIBILITY SCORE: {doc.get('reproducibility_score')}/10")
            print(f"\nNotes:")
            print(f"{doc.get('reproducibility_notes')}")
        
        # Overall assessment
        print("\n6. OVERALL ASSESSMENT")
        print("-" * 40)
        print(data.get('overall_assessment', 'N/A'))
        
        # Recommendations
        if data.get('recommendations'):
            print("\n7. RECOMMENDATIONS")
            print("-" * 40)
            for i, rec in enumerate(data['recommendations'], 1):
                print(f"{i}. {rec}")
        
        # Token usage
        token_artifact = NodeArtifact.objects.filter(node=node, name='token_usage').first()
        if token_artifact:
            tokens = token_artifact.inline_data
            print("\n" + "="*80)
            print(f"Token Usage: {tokens.get('input_tokens')} input + {tokens.get('output_tokens')} output = {tokens.get('total_tokens')} total")
        
    except Exception as e:
        print(f"Error retrieving analysis: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python view_analysis.py <paper_id>")
        sys.exit(1)
    
    paper_id = int(sys.argv[1])
    view_analysis(paper_id)
