# DAG Visualization Feature

## Overview

The workflow engine now automatically generates and stores visual diagrams of the DAG (Directed Acyclic Graph) structure for each workflow definition.

## Features

- **Automatic Generation**: When creating or updating a workflow using the `create_workflow` management command, a PNG diagram is automatically generated using Graphviz
- **Database Storage**: The diagram is stored as an ImageField in the WorkflowDefinition model
- **Admin Preview**: The diagram is displayed in the Django admin interface for easy visualization
- **Color-Coded Nodes**: Different node types are colored differently:
  - `celery` nodes: Light blue
  - `langgraph` nodes: Light green
  - `python` nodes: Light yellow

## Generated Diagram

The diagram includes:
- All workflow nodes with their IDs, types, and descriptions
- Directed edges showing dependencies between nodes
- Clear visual representation of parallel execution paths
- Professional rendering using Graphviz's DOT layout engine

## Viewing the Diagram

### In Django Admin

1. Navigate to: `http://localhost:8900/admin/workflow_engine/workflowdefinition/`
2. Click on any workflow definition
3. Scroll to the "DAG Structure" section
4. View the "DAG Diagram" field showing the full visualization

### Direct File Access

The PNG files are stored in: `/app/media/workflow_diagrams/`

Example: `/app/media/workflow_diagrams/pdf_analysis_pipeline_dag.png`

### Via Code

```python
from workflow_engine.models import WorkflowDefinition

workflow = WorkflowDefinition.objects.get(name='pdf_analysis_pipeline')
if workflow.dag_diagram:
    print(f"Diagram URL: {workflow.dag_diagram.url}")
    print(f"Diagram Path: {workflow.dag_diagram.path}")
```

## Requirements

- **Python Package**: `graphviz==0.21` (installed via uv)
- **System Package**: `graphviz` (Debian/Ubuntu: `apt-get install graphviz`)

Both are now installed in the Django container.

## Regenerating Diagrams

To regenerate the diagram for an existing workflow:

```bash
sudo docker exec -it django-web-dev bash -c "cd /app && uv run python manage.py create_workflow"
```

This will update the existing workflow and regenerate its diagram.

## Implementation Details

### Model Change

Added `dag_diagram` ImageField to WorkflowDefinition:

```python
dag_diagram = models.ImageField(
    upload_to='workflow_diagrams/',
    null=True,
    blank=True,
    help_text="Auto-generated DAG visualization (PNG)"
)
```

### Management Command

The `create_workflow` command now:
1. Creates/updates the workflow definition
2. Generates a Graphviz digraph from the DAG structure
3. Renders it to PNG format
4. Saves it to the database via the ImageField

### Admin Interface

Added `dag_diagram_preview` method to display the image:

```python
def dag_diagram_preview(self, obj):
    if obj.dag_diagram:
        return format_html(
            '<img src="{}" style="max-width: 800px; border: 1px solid #ddd; padding: 10px; background: white;"/>',
            obj.dag_diagram.url
        )
    return "No diagram generated"
```

## Example Output

For the PDF analysis pipeline, the diagram shows:

```
ingest_pdf → extract_text → extract_evidence → validate_links → fetch_repo
                    ↓                                                  ↓
              ai_checks_pdf                                     ai_checks_repo
                    ↓                                                  ↓
                    └──────────────→ aggregate_findings ←──────────────┘
                                            ↓
                                      compute_score
                                            ↓
                                     generate_report
```

This makes it easy to:
- Understand workflow structure at a glance
- Identify parallel execution paths
- Verify dependency relationships
- Communicate workflow design to stakeholders

## Troubleshooting

### "graphviz not installed" Warning

If you see this warning, install the package:

```bash
# Install system package
sudo docker exec -it django-web-dev apt-get update
sudo docker exec -it django-web-dev apt-get install -y graphviz

# Install Python package
sudo docker exec -it django-web-dev bash -c "cd /app && uv add graphviz"
```

### Image Not Displaying in Admin

Check that:
1. MEDIA_URL is configured in settings (`/media/`)
2. MEDIA_ROOT points to the correct directory
3. The file exists: `ls /app/media/workflow_diagrams/`
4. The Django dev server serves media files (automatic in development)

## Future Enhancements

Potential improvements:
- Interactive SVG diagrams instead of static PNG
- Zoom/pan capabilities in admin
- Real-time execution status overlay on diagram
- Export to multiple formats (SVG, PDF, DOT)
- Diagram customization options (colors, layout, size)
