"""
Utility functions for workflow engine.
"""
from typing import Dict, Any, List, Optional
from django.db.models import Q
from django.utils import timezone

from workflow_engine.models import WorkflowRun, WorkflowNode, WorkflowDefinition


def get_or_create_workflow_for_paper(
    paper,
    workflow_name: str = 'pdf_analysis_pipeline',
    force_new: bool = False,
    user=None
) -> WorkflowRun:
    """
    Get existing workflow run or create new one for a paper.
    
    Args:
        paper: Paper instance
        workflow_name: Name of workflow to use
        force_new: If True, always create new run even if one exists
        user: User instance
        
    Returns:
        WorkflowRun instance
    """
    from workflow_engine.services.orchestrator import WorkflowOrchestrator
    
    if not force_new:
        # Check for existing running workflow
        existing = WorkflowRun.objects.filter(
            paper=paper,
            workflow_definition__name=workflow_name,
            status__in=['pending', 'running']
        ).first()
        
        if existing:
            return existing
    
    # Create new run
    orchestrator = WorkflowOrchestrator()
    workflow_run = orchestrator.create_workflow_run(
        workflow_name=workflow_name,
        paper=paper,
        user=user
    )
    
    # Start it
    workflow_run.status = 'running'
    workflow_run.started_at = timezone.now()
    workflow_run.save(update_fields=['status', 'started_at'])
    
    return workflow_run


def get_workflow_results(workflow_run: WorkflowRun) -> Dict[str, Any]:
    """
    Extract results from a completed workflow run.
    
    Args:
        workflow_run: WorkflowRun instance
        
    Returns:
        Dictionary with all node outputs and final results
    """
    if workflow_run.status != 'completed':
        return {
            'status': workflow_run.status,
            'error': workflow_run.error_message,
            'completed': False
        }
    
    results = {
        'status': 'completed',
        'completed': True,
        'workflow_id': str(workflow_run.id),
        'paper_id': workflow_run.paper.id,
        'duration': workflow_run.duration,
        'node_outputs': {}
    }
    
    # Collect all node outputs
    for node in workflow_run.nodes.all():
        results['node_outputs'][node.node_id] = {
            'status': node.status,
            'output': node.output_data,
            'duration': node.duration
        }
    
    # Extract specific important outputs
    score_node = workflow_run.nodes.filter(node_id='compute_score').first()
    if score_node and score_node.status == 'completed':
        results['final_score'] = score_node.output_data.get('final_score')
        results['score_breakdown'] = score_node.output_data.get('component_scores')
    
    report_node = workflow_run.nodes.filter(node_id='generate_report').first()
    if report_node and report_node.status == 'completed':
        results['report'] = report_node.output_data
    
    return results


def retry_failed_nodes(workflow_run: WorkflowRun) -> int:
    """
    Retry all failed nodes in a workflow run.
    
    Args:
        workflow_run: WorkflowRun instance
        
    Returns:
        Number of nodes reset for retry
    """
    failed_nodes = workflow_run.nodes.filter(status='failed')
    
    count = 0
    for node in failed_nodes:
        if node.can_retry():
            node.status = 'ready'
            node.claimed_by = None
            node.claimed_at = None
            node.claim_expires_at = None
            node.error_message = None
            node.error_traceback = None
            node.save(update_fields=[
                'status', 'claimed_by', 'claimed_at', 
                'claim_expires_at', 'error_message', 'error_traceback'
            ])
            count += 1
    
    if count > 0 and workflow_run.status == 'failed':
        workflow_run.status = 'running'
        workflow_run.error_message = None
        workflow_run.save(update_fields=['status', 'error_message'])
    
    return count


def get_active_workflows(
    paper=None,
    limit: int = 10
) -> List[WorkflowRun]:
    """
    Get currently active (running) workflows.
    
    Args:
        paper: Optional Paper instance to filter by
        limit: Maximum number to return
        
    Returns:
        List of WorkflowRun instances
    """
    query = WorkflowRun.objects.filter(
        status__in=['pending', 'running']
    ).select_related('workflow_definition', 'paper')
    
    if paper:
        query = query.filter(paper=paper)
    
    return list(query.order_by('-created_at')[:limit])


def get_workflow_statistics() -> Dict[str, Any]:
    """
    Get overall workflow system statistics.
    
    Returns:
        Dictionary with system-wide stats
    """
    from django.db.models import Count, Avg, Q
    from datetime import timedelta
    
    now = timezone.now()
    last_24h = now - timedelta(hours=24)
    
    stats = {
        'total_runs': WorkflowRun.objects.count(),
        'active_runs': WorkflowRun.objects.filter(
            status__in=['pending', 'running']
        ).count(),
        'completed_runs': WorkflowRun.objects.filter(
            status='completed'
        ).count(),
        'failed_runs': WorkflowRun.objects.filter(
            status='failed'
        ).count(),
        
        # Last 24 hours
        'last_24h_runs': WorkflowRun.objects.filter(
            created_at__gte=last_24h
        ).count(),
        'last_24h_completed': WorkflowRun.objects.filter(
            created_at__gte=last_24h,
            status='completed'
        ).count(),
        
        # Node statistics
        'total_nodes': WorkflowNode.objects.count(),
        'running_nodes': WorkflowNode.objects.filter(
            status='running'
        ).count(),
        'ready_nodes': WorkflowNode.objects.filter(
            status='ready'
        ).count(),
        'failed_nodes': WorkflowNode.objects.filter(
            status='failed'
        ).count(),
        
        # Workflow definitions
        'active_definitions': WorkflowDefinition.objects.filter(
            is_active=True
        ).count(),
    }
    
    # Average duration for completed workflows
    avg_duration = WorkflowRun.objects.filter(
        status='completed',
        completed_at__isnull=False,
        started_at__isnull=False
    ).values_list('started_at', 'completed_at')
    
    if avg_duration:
        durations = [
            (completed - started).total_seconds() 
            for started, completed in avg_duration
        ]
        stats['avg_duration_seconds'] = sum(durations) / len(durations)
    else:
        stats['avg_duration_seconds'] = None
    
    return stats


def visualize_workflow(workflow_definition: WorkflowDefinition) -> str:
    """
    Create a text-based visualization of a workflow DAG.
    
    Args:
        workflow_definition: WorkflowDefinition instance
        
    Returns:
        String representation of the DAG
    """
    nodes = {n['id']: n for n in workflow_definition.dag_structure.get('nodes', [])}
    edges = workflow_definition.dag_structure.get('edges', [])
    
    # Build adjacency lists
    children = {node_id: [] for node_id in nodes.keys()}
    parents = {node_id: [] for node_id in nodes.keys()}
    
    for edge in edges:
        children[edge['from']].append(edge['to'])
        parents[edge['to']].append(edge['from'])
    
    # Find root nodes (no parents)
    roots = [node_id for node_id, p in parents.items() if not p]
    
    # Build visualization
    lines = [f"Workflow: {workflow_definition.name}"]
    lines.append("=" * 60)
    
    def print_node(node_id: str, indent: int = 0, prefix: str = ""):
        node = nodes[node_id]
        lines.append(
            f"{' ' * indent}{prefix}{node_id} ({node.get('type', 'celery')})"
        )
        
        # Print children
        child_nodes = children[node_id]
        for i, child_id in enumerate(child_nodes):
            is_last = i == len(child_nodes) - 1
            child_prefix = "└─ " if is_last else "├─ "
            print_node(child_id, indent + 2, child_prefix)
    
    # Print from roots
    for root in roots:
        print_node(root)
    
    return "\n".join(lines)


def generate_dag_diagram(workflow_definition: WorkflowDefinition) -> bool:
    """
    Generate and save a Graphviz DAG diagram for a workflow definition.
    
    Args:
        workflow_definition: WorkflowDefinition instance
        
    Returns:
        True if diagram was generated successfully, False otherwise
    """
    try:
        import graphviz
        import tempfile
        import os
        from django.core.files import File
    except ImportError:
        return False
    
    try:
        dag_structure = workflow_definition.dag_structure
        
        # Create graphviz digraph
        dot = graphviz.Digraph(
            comment=workflow_definition.name,
            format='png',
            engine='dot'
        )
        
        # Set graph attributes for better visualization
        dot.attr(rankdir='TB', size='10,15')
        dot.attr('node', shape='box', style='rounded,filled', 
                fillcolor='lightblue', fontname='Arial', fontsize='10')
        dot.attr('edge', fontsize='8', color='gray40')
        
        # Add nodes with colors based on type
        node_colors = {
            'celery': 'lightblue',
            'langgraph': 'lightgreen',
            'python': 'lightyellow'
        }
        
        for node in dag_structure.get('nodes', []):
            node_id = node['id']
            node_type = node.get('type', 'celery')
            description = node.get('description', '')
            color = node_colors.get(node_type, 'lightgray')
            
            # Create label with node ID and description
            label = f"{node_id}\n({node_type})\n{description}"
            dot.node(node_id, label=label, fillcolor=color)
        
        # Add edges
        for edge in dag_structure.get('edges', []):
            dot.edge(edge['from'], edge['to'])
        
        # Render to temporary file
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, 'dag')
            dot.render(output_path, cleanup=True)
            
            # Save to model
            png_path = f'{output_path}.png'
            with open(png_path, 'rb') as f:
                workflow_definition.dag_diagram.save(
                    f'{workflow_definition.name}_dag.png',
                    File(f),
                    save=False  # Don't trigger another save
                )
        
        return True
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f'Failed to generate DAG diagram for {workflow_definition.name}: {e}')
        return False


def cleanup_old_workflows(days: int = 30, keep_failed: bool = True) -> int:
    """
    Cleanup old completed workflow runs.
    
    Args:
        days: Delete workflows older than this many days
        keep_failed: If True, keep failed workflows for debugging
        
    Returns:
        Number of workflows deleted
    """
    from datetime import timedelta
    
    cutoff = timezone.now() - timedelta(days=days)
    
    query = WorkflowRun.objects.filter(
        created_at__lt=cutoff,
        status='completed'
    )
    
    if keep_failed:
        # Don't delete failed workflows
        query = query.exclude(status='failed')
    
    count = query.count()
    query.delete()
    
    return count
