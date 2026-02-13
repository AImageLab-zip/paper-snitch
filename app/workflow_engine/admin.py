"""
Django admin interface for workflow engine.
"""
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe

from .models import (
    WorkflowDefinition,
    WorkflowRun,
    WorkflowNode,
    NodeArtifact,
    NodeLog,
    LangGraphCheckpoint
)


@admin.register(WorkflowDefinition)
class WorkflowDefinitionAdmin(admin.ModelAdmin):
    list_display = ['name', 'version', 'is_active', 'node_count', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['id', 'created_at', 'updated_at', 'dag_visualization', 'dag_diagram_preview']
    
    fieldsets = [
        ('Basic Information', {
            'fields': ['id', 'name', 'version', 'description', 'is_active']
        }),
        ('DAG Structure', {
            'fields': ['dag_structure', 'dag_visualization', 'dag_diagram', 'dag_diagram_preview']
        }),
        ('Metadata', {
            'fields': ['created_by', 'created_at', 'updated_at']
        })
    ]
    
    def node_count(self, obj):
        return len(obj.dag_structure.get('nodes', []))
    node_count.short_description = 'Nodes'
    
    def dag_visualization(self, obj):
        """Display a simple text visualization of the DAG."""
        nodes = obj.dag_structure.get('nodes', [])
        edges = obj.dag_structure.get('edges', [])
        
        html = '<div style="font-family: monospace; white-space: pre;">'
        html += f'<strong>Nodes ({len(nodes)}):</strong>\n'
        for node in nodes:
            html += f'  • {node["id"]} ({node.get("type", "celery")})\n'
        
        html += f'\n<strong>Dependencies ({len(edges)}):</strong>\n'
        for edge in edges:
            html += f'  {edge["from"]} → {edge["to"]}\n'
        
        html += '</div>'
        return mark_safe(html)
    dag_visualization.short_description = 'DAG Visualization'
    
    def dag_diagram_preview(self, obj):
        """Display the DAG diagram image."""
        if obj.dag_diagram:
            return format_html(
                '<img src="{}" style="max-width: 800px; border: 1px solid #ddd; padding: 10px; background: white;"/>',
                obj.dag_diagram.url
            )
        return "No diagram generated"
    dag_diagram_preview.short_description = 'DAG Diagram'


@admin.register(WorkflowRun)
class WorkflowRunAdmin(admin.ModelAdmin):
    list_display = [
        'id_short',
        'workflow_name',
        'paper_link',
        'status_badge',
        'progress_bar',
        'created_at',
        'duration_display'
    ]
    list_filter = ['status', 'workflow_definition', 'created_at']
    search_fields = ['id', 'paper__title']
    readonly_fields = [
        'id',
        'created_at',
        'started_at',
        'completed_at',
        'duration_display',
        'progress_display'
    ]
    
    fieldsets = [
        ('Workflow Information', {
            'fields': ['id', 'workflow_definition', 'paper', 'run_number', 'status']
        }),
        ('Input/Output', {
            'fields': ['input_data', 'output_data']
        }),
        ('Error Information', {
            'fields': ['error_message'],
            'classes': ['collapse']
        }),
        ('Timestamps', {
            'fields': ['created_at', 'started_at', 'completed_at', 'duration_display']
        }),
        ('Progress', {
            'fields': ['progress_display']
        }),
        ('User', {
            'fields': ['created_by']
        })
    ]
    
    def id_short(self, obj):
        return str(obj.id)[:8]
    id_short.short_description = 'ID'
    
    def workflow_name(self, obj):
        return obj.workflow_definition.name
    workflow_name.short_description = 'Workflow'
    
    def paper_link(self, obj):
        url = reverse('admin:webApp_paper_change', args=[obj.paper.id])
        return format_html('<a href="{}">{}</a>', url, obj.paper.title[:50])
    paper_link.short_description = 'Paper'
    
    def status_badge(self, obj):
        colors = {
            'pending': 'gray',
            'running': 'blue',
            'completed': 'green',
            'failed': 'red',
            'cancelled': 'orange'
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color,
            obj.status.upper()
        )
    status_badge.short_description = 'Status'
    
    def progress_bar(self, obj):
        progress = obj.get_progress()
        percentage = progress['percentage']
        
        return format_html(
            '<div style="width: 100px; background-color: #f0f0f0; border-radius: 3px;">'
            '<div style="width: {}%; background-color: #4CAF50; padding: 2px 5px; color: white; text-align: center; border-radius: 3px;">{}</div>'
            '</div>',
            percentage,
            f'{percentage}%'
        )
    progress_bar.short_description = 'Progress'
    
    def duration_display(self, obj):
        if obj.duration:
            return f'{obj.duration:.2f}s'
        return '-'
    duration_display.short_description = 'Duration'
    
    def progress_display(self, obj):
        progress = obj.get_progress()
        html = '<table style="width: 100%;">'
        html += f'<tr><td>Total:</td><td><strong>{progress["total"]}</strong></td></tr>'
        html += f'<tr><td>Completed:</td><td style="color: green;">{progress["completed"]}</td></tr>'
        html += f'<tr><td>Running:</td><td style="color: blue;">{progress["running"]}</td></tr>'
        html += f'<tr><td>Pending:</td><td>{progress["pending"]}</td></tr>'
        html += f'<tr><td>Failed:</td><td style="color: red;">{progress["failed"]}</td></tr>'
        html += '</table>'
        return mark_safe(html)
    progress_display.short_description = 'Detailed Progress'


@admin.register(WorkflowNode)
class WorkflowNodeAdmin(admin.ModelAdmin):
    list_display = [
        'node_id',
        'workflow_run_short',
        'status_badge',
        'attempt_count',
        'duration_display',
        'created_at'
    ]
    list_filter = ['status', 'node_type', 'created_at']
    search_fields = ['node_id', 'workflow_run__id']
    readonly_fields = [
        'id',
        'created_at',
        'started_at',
        'completed_at',
        'duration_display'
    ]
    
    fieldsets = [
        ('Node Information', {
            'fields': ['id', 'workflow_run', 'node_id', 'node_type', 'handler', 'status']
        }),
        ('Execution', {
            'fields': [
                'attempt_count',
                'max_retries',
                'celery_task_id',
                'claimed_by',
                'claimed_at',
                'claim_expires_at'
            ]
        }),
        ('Input/Output', {
            'fields': ['input_data', 'output_data']
        }),
        ('Error Information', {
            'fields': ['error_message', 'error_traceback'],
            'classes': ['collapse']
        }),
        ('Timestamps', {
            'fields': ['created_at', 'started_at', 'completed_at', 'duration_display']
        })
    ]
    
    def workflow_run_short(self, obj):
        return str(obj.workflow_run.id)[:8]
    workflow_run_short.short_description = 'Run'
    
    def status_badge(self, obj):
        colors = {
            'pending': 'gray',
            'ready': 'lightblue',
            'claimed': 'yellow',
            'running': 'blue',
            'completed': 'green',
            'failed': 'red',
            'skipped': 'orange'
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color,
            obj.status.upper()
        )
    status_badge.short_description = 'Status'
    
    def duration_display(self, obj):
        if obj.duration:
            return f'{obj.duration:.2f}s'
        return '-'
    duration_display.short_description = 'Duration'


@admin.register(NodeArtifact)
class NodeArtifactAdmin(admin.ModelAdmin):
    list_display = ['name', 'artifact_type', 'node_link', 'size_display', 'created_at']
    list_filter = ['artifact_type', 'created_at']
    search_fields = ['name', 'node__node_id']
    readonly_fields = ['id', 'created_at']
    
    def node_link(self, obj):
        url = reverse('admin:workflow_engine_workflownode_change', args=[obj.node.id])
        return format_html('<a href="{}">{}</a>', url, obj.node.node_id)
    node_link.short_description = 'Node'
    
    def size_display(self, obj):
        if obj.size_bytes:
            if obj.size_bytes < 1024:
                return f'{obj.size_bytes} B'
            elif obj.size_bytes < 1024 * 1024:
                return f'{obj.size_bytes / 1024:.2f} KB'
            else:
                return f'{obj.size_bytes / (1024 * 1024):.2f} MB'
        return '-'
    size_display.short_description = 'Size'


@admin.register(NodeLog)
class NodeLogAdmin(admin.ModelAdmin):
    list_display = ['timestamp', 'level_badge', 'node_link', 'message_short']
    list_filter = ['level', 'timestamp']
    search_fields = ['message', 'node__node_id']
    readonly_fields = ['id', 'timestamp']
    
    def node_link(self, obj):
        url = reverse('admin:workflow_engine_workflownode_change', args=[obj.node.id])
        return format_html('<a href="{}">{}</a>', url, obj.node.node_id)
    node_link.short_description = 'Node'
    
    def level_badge(self, obj):
        colors = {
            'DEBUG': 'lightgray',
            'INFO': 'blue',
            'WARNING': 'orange',
            'ERROR': 'red'
        }
        color = colors.get(obj.level, 'gray')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 6px; border-radius: 2px; font-size: 11px;">{}</span>',
            color,
            obj.level
        )
    level_badge.short_description = 'Level'
    
    def message_short(self, obj):
        return obj.message[:100]
    message_short.short_description = 'Message'


@admin.register(LangGraphCheckpoint)
class LangGraphCheckpointAdmin(admin.ModelAdmin):
    list_display = ['checkpoint_id', 'thread_id', 'node_link', 'created_at']
    list_filter = ['created_at']
    search_fields = ['checkpoint_id', 'thread_id', 'node__node_id']
    readonly_fields = ['id', 'created_at']
    
    def node_link(self, obj):
        url = reverse('admin:workflow_engine_workflownode_change', args=[obj.node.id])
        return format_html('<a href="{}">{}</a>', url, obj.node.node_id)
    node_link.short_description = 'Node'
