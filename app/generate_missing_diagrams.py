#!/usr/bin/env python
"""
Script to generate DAG diagrams for existing workflows that don't have one.
"""
import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'web.settings.dev')
django.setup()

from workflow_engine.models import WorkflowDefinition
from workflow_engine.utils import generate_dag_diagram


def main():
    """Generate diagrams for workflows without diagrams."""
    workflows = WorkflowDefinition.objects.all()
    
    print(f"Found {workflows.count()} workflow(s)")
    print("-" * 60)
    
    for workflow in workflows:
        print(f"\nWorkflow: {workflow.name} (v{workflow.version})")
        
        if workflow.dag_diagram:
            print(f"  ✓ Diagram exists: {workflow.dag_diagram.name}")
        else:
            print(f"  ✗ No diagram found - generating...")
            success = generate_dag_diagram(workflow)
            
            if success:
                # Save to persist the diagram
                workflow.save(update_fields=['dag_diagram'])
                print(f"  ✓ Diagram generated: {workflow.dag_diagram.name}")
            else:
                print(f"  ✗ Failed to generate diagram (check if graphviz is installed)")
    
    print("\n" + "=" * 60)
    print("Done!")


if __name__ == '__main__':
    main()
