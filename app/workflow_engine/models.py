"""
Workflow Engine Models

Database-backed DAG workflow system with MySQL row-level locking for
distributed task execution via Celery.
"""
import uuid
import json
from datetime import datetime
from typing import Dict, List, Optional, Any

from django.db import models, transaction
from django.utils import timezone
from django.core.exceptions import ValidationError


class WorkflowDefinition(models.Model):
    """
    Defines a reusable workflow template (DAG structure).
    
    A workflow is a directed acyclic graph of nodes (tasks) with dependencies.
    Multiple workflow runs can be instantiated from a single definition.
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Unique workflow name (e.g., 'pdf_analysis_pipeline')"
    )
    version = models.IntegerField(
        default=1,
        help_text="Version number for workflow evolution"
    )
    description = models.TextField(blank=True, null=True)
    
    # Workflow structure stored as JSON
    dag_structure = models.JSONField(
        help_text="DAG structure: {'nodes': [...], 'edges': [...]}"
    )
    
    # DAG visualization diagram
    dag_diagram = models.ImageField(
        upload_to='workflow_diagrams/',
        null=True,
        blank=True,
        help_text="Auto-generated DAG visualization (PNG)"
    )
    
    # Metadata
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether this workflow can be used for new runs"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='workflow_definitions'
    )
    
    class Meta:
        verbose_name = "Workflow Definition"
        verbose_name_plural = "Workflow Definitions"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['name', 'version']),
            models.Index(fields=['is_active', 'name']),
        ]
    
    def __str__(self):
        return f"{self.name} (v{self.version})"
    
    def clean(self):
        """Validate DAG structure."""
        super().clean()
        if not self.dag_structure:
            raise ValidationError("DAG structure cannot be empty")
        
        # Validate required keys
        if 'nodes' not in self.dag_structure:
            raise ValidationError("DAG structure must contain 'nodes'")
        
        # Validate no cycles (basic check)
        if not self._is_acyclic():
            raise ValidationError("Workflow contains cycles - must be a DAG")
    
    def _is_acyclic(self) -> bool:
        """Check if the workflow graph is acyclic."""
        nodes = {node['id']: node for node in self.dag_structure.get('nodes', [])}
        edges = self.dag_structure.get('edges', [])
        
        # Build adjacency list
        graph = {node_id: [] for node_id in nodes.keys()}
        for edge in edges:
            if edge['from'] in graph:
                graph[edge['from']].append(edge['to'])
        
        # DFS to detect cycles
        visited = set()
        rec_stack = set()
        
        def has_cycle(node_id):
            visited.add(node_id)
            rec_stack.add(node_id)
            
            for neighbor in graph.get(node_id, []):
                if neighbor not in visited:
                    if has_cycle(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            
            rec_stack.remove(node_id)
            return False
        
        for node_id in graph:
            if node_id not in visited:
                if has_cycle(node_id):
                    return False
        
        return True
    
    def get_node_by_id(self, node_id: str) -> Optional[Dict]:
        """Get a node definition by its ID."""
        for node in self.dag_structure.get('nodes', []):
            if node['id'] == node_id:
                return node
        return None
    
    def get_dependencies(self, node_id: str) -> List[str]:
        """Get list of node IDs that must complete before this node can start."""
        dependencies = []
        for edge in self.dag_structure.get('edges', []):
            if edge['to'] == node_id:
                dependencies.append(edge['from'])
        return dependencies
    
    def get_dependents(self, node_id: str) -> List[str]:
        """Get list of node IDs that depend on this node."""
        dependents = []
        for edge in self.dag_structure.get('edges', []):
            if edge['from'] == node_id:
                dependents.append(edge['to'])
        return dependents


class WorkflowRun(models.Model):
    """
    An instance of a workflow execution for a specific domain entity.
    
    Multiple runs can exist for the same instance (e.g., re-running analysis on same paper).
    """
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow_definition = models.ForeignKey(
        WorkflowDefinition,
        on_delete=models.PROTECT,
        related_name='runs'
    )
    
    # Link to domain entity (Paper in your case)
    paper = models.ForeignKey(
        'webApp.Paper',
        on_delete=models.CASCADE,
        related_name='workflow_runs',
        help_text="The paper being analyzed by this workflow"
    )
    
    # Run metadata
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )
    run_number = models.IntegerField(
        default=1,
        help_text="Sequential run number for this paper (1, 2, 3...)"
    )
    
    # Context data passed to the workflow
    input_data = models.JSONField(
        default=dict,
        help_text="Input parameters for this workflow run"
    )
    
    # Results and error tracking
    output_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Final output/results from the workflow"
    )
    error_message = models.TextField(blank=True, null=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # User tracking
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='workflow_runs'
    )
    
    class Meta:
        verbose_name = "Workflow Run"
        verbose_name_plural = "Workflow Runs"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['paper', 'status']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['workflow_definition', 'status']),
            models.Index(fields=['paper', 'run_number']),
        ]
        # No unique constraint - allow re-running workflows
        # run_number is auto-incremented in save() method
    
    def __str__(self):
        return f"{self.workflow_definition.name} - Run #{self.run_number} for {self.paper.title[:50]}"
    
    def save(self, *args, **kwargs):
        """Auto-increment run_number for the same paper."""
        if not self.run_number:
            last_run = WorkflowRun.objects.filter(paper=self.paper).order_by('-run_number').first()
            self.run_number = (last_run.run_number + 1) if last_run else 1
        super().save(*args, **kwargs)
    
    @property
    def duration(self) -> Optional[float]:
        """Calculate run duration in seconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
    
    def get_progress(self) -> Dict[str, Any]:
        """Calculate workflow progress statistics."""
        nodes = self.nodes.all()
        total = nodes.count()
        
        if total == 0:
            return {'total': 0, 'completed': 0, 'failed': 0, 'running': 0, 'pending': 0, 'percentage': 0}
        
        completed = nodes.filter(status='completed').count()
        failed = nodes.filter(status='failed').count()
        running = nodes.filter(status='running').count()
        pending = nodes.filter(status__in=['pending', 'ready']).count()
        
        return {
            'total': total,
            'completed': completed,
            'failed': failed,
            'running': running,
            'pending': pending,
            'percentage': int((completed / total) * 100)
        }


class WorkflowNode(models.Model):
    """
    A node (task) within a workflow run.
    
    Tracks execution state, attempts, artifacts, and supports idempotent retries
    with MySQL row-level locking for distributed claiming.
    """
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),      # Waiting for dependencies
        ('ready', 'Ready'),          # Dependencies met, ready to be claimed
        ('claimed', 'Claimed'),      # Claimed by a worker
        ('running', 'Running'),      # Currently executing
        ('completed', 'Completed'),  # Successfully finished
        ('failed', 'Failed'),        # Failed after all retries
        ('skipped', 'Skipped'),      # Skipped due to upstream failure
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow_run = models.ForeignKey(
        WorkflowRun,
        on_delete=models.CASCADE,
        related_name='nodes'
    )
    
    # Node identity from workflow definition
    node_id = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Node ID from workflow definition (e.g., 'extract_text')"
    )
    node_type = models.CharField(
        max_length=100,
        help_text="Type of task (e.g., 'celery', 'langgraph', 'python')"
    )
    handler = models.CharField(
        max_length=255,
        help_text="Handler reference (e.g., 'workflow_engine.tasks.extract_text_task')"
    )
    
    # Execution state
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )
    
    # Retry and attempt tracking
    max_retries = models.IntegerField(default=3)
    attempt_count = models.IntegerField(default=0)
    
    # Worker claiming (for distributed execution)
    claimed_by = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Worker/host that claimed this task"
    )
    claimed_at = models.DateTimeField(null=True, blank=True)
    claim_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Claim expiration for stale worker detection"
    )
    
    # Celery task tracking
    celery_task_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True
    )
    
    # Input/output data
    input_data = models.JSONField(
        default=dict,
        help_text="Input parameters for this node"
    )
    output_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Output/results from this node"
    )
    
    # Error tracking
    error_message = models.TextField(blank=True, null=True)
    error_traceback = models.TextField(blank=True, null=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = "Workflow Node"
        verbose_name_plural = "Workflow Nodes"
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['workflow_run', 'status']),
            models.Index(fields=['status', 'claim_expires_at']),
            models.Index(fields=['node_id', 'workflow_run']),
            models.Index(fields=['celery_task_id']),
        ]
        unique_together = [['workflow_run', 'node_id']]
    
    def __str__(self):
        return f"{self.node_id} ({self.status}) - Run {self.workflow_run.id}"
    
    @property
    def duration(self) -> Optional[float]:
        """Calculate execution duration in seconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
    
    def can_retry(self) -> bool:
        """Check if node can be retried."""
        return self.attempt_count < self.max_retries
    
    def get_dependencies(self) -> List['WorkflowNode']:
        """Get upstream dependency nodes."""
        definition = self.workflow_run.workflow_definition
        dep_ids = definition.get_dependencies(self.node_id)
        
        return WorkflowNode.objects.filter(
            workflow_run=self.workflow_run,
            node_id__in=dep_ids
        )
    
    def dependencies_met(self) -> bool:
        """Check if all upstream dependencies have completed successfully."""
        dependencies = self.get_dependencies()
        return all(dep.status == 'completed' for dep in dependencies)
    
    def get_dependents(self) -> List['WorkflowNode']:
        """Get downstream dependent nodes."""
        definition = self.workflow_run.workflow_definition
        dependent_ids = definition.get_dependents(self.node_id)
        
        return WorkflowNode.objects.filter(
            workflow_run=self.workflow_run,
            node_id__in=dependent_ids
        )


class NodeArtifact(models.Model):
    """
    Stores references to artifacts produced by workflow nodes.
    
    Can reference files in media storage, S3, or store small data inline.
    """
    
    ARTIFACT_TYPE_CHOICES = [
        ('file', 'File Reference'),
        ('url', 'URL'),
        ('inline', 'Inline Data'),
        ('database', 'Database Record'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    node = models.ForeignKey(
        WorkflowNode,
        on_delete=models.CASCADE,
        related_name='artifacts'
    )
    
    artifact_type = models.CharField(max_length=20, choices=ARTIFACT_TYPE_CHOICES)
    name = models.CharField(
        max_length=255,
        help_text="Artifact name/key (e.g., 'extracted_text', 'pdf_file')"
    )
    
    # Storage references
    file_path = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Path to file in media storage"
    )
    url = models.URLField(max_length=1000, blank=True, null=True)
    inline_data = models.JSONField(
        blank=True,
        null=True,
        help_text="Small data stored inline"
    )
    
    # Database reference (e.g., to Document, Analysis, etc.)
    content_type = models.ForeignKey(
        'contenttypes.ContentType',
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    object_id = models.CharField(max_length=255, null=True, blank=True)
    
    # Metadata
    mime_type = models.CharField(max_length=100, blank=True, null=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional metadata about the artifact"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Node Artifact"
        verbose_name_plural = "Node Artifacts"
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['node', 'name']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.artifact_type}) - Node {self.node.node_id}"


class NodeLog(models.Model):
    """
    Logs for workflow node execution (structured logging).
    """
    
    LOG_LEVEL_CHOICES = [
        ('DEBUG', 'Debug'),
        ('INFO', 'Info'),
        ('WARNING', 'Warning'),
        ('ERROR', 'Error'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    node = models.ForeignKey(
        WorkflowNode,
        on_delete=models.CASCADE,
        related_name='logs'
    )
    
    level = models.CharField(max_length=10, choices=LOG_LEVEL_CHOICES, default='INFO')
    message = models.TextField()
    context = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional context data for the log entry"
    )
    
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        verbose_name = "Node Log"
        verbose_name_plural = "Node Logs"
        ordering = ['timestamp']
        indexes = [
            models.Index(fields=['node', 'timestamp']),
            models.Index(fields=['level', 'timestamp']),
        ]
    
    def __str__(self):
        return f"[{self.level}] {self.node.node_id}: {self.message[:50]}"


class LangGraphCheckpoint(models.Model):
    """
    Stores LangGraph checkpoints for AI agent nodes.
    
    This allows LangGraph to use MySQL as its checkpointer for persistence.
    """
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    node = models.ForeignKey(
        WorkflowNode,
        on_delete=models.CASCADE,
        related_name='langgraph_checkpoints'
    )
    
    # LangGraph checkpoint data
    thread_id = models.CharField(max_length=255, db_index=True)
    checkpoint_id = models.CharField(max_length=255, db_index=True)
    checkpoint_data = models.JSONField(
        help_text="Serialized LangGraph state"
    )
    
    # Metadata
    parent_checkpoint_id = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        verbose_name = "LangGraph Checkpoint"
        verbose_name_plural = "LangGraph Checkpoints"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['thread_id', 'checkpoint_id']),
            models.Index(fields=['node', 'thread_id']),
        ]
    
    def __str__(self):
        return f"Checkpoint {self.checkpoint_id} - Thread {self.thread_id}"
