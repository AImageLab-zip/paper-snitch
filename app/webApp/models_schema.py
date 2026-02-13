"""
Database schema tracking models.
Stores generated database schema diagrams.
"""
from django.db import models
from django.utils import timezone


class DatabaseSchema(models.Model):
    """Stores database schema diagrams generated after migrations."""
    
    created_at = models.DateTimeField(default=timezone.now)
    migration_name = models.CharField(max_length=500, blank=True)
    schema_diagram = models.ImageField(upload_to='schema_diagrams/', null=True, blank=True)
    schema_dot = models.TextField(blank=True, help_text="GraphViz DOT source")
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Database Schema"
        verbose_name_plural = "Database Schemas"
    
    def __str__(self):
        return f"Schema {self.created_at.strftime('%Y-%m-%d %H:%M')}"
