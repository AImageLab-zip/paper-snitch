"""
Workflow Engine - A database-backed DAG workflow system for Django.

This app provides a durable, distributed workflow orchestration system using
Django models, MySQL, and Celery for processing complex multi-step pipelines.
"""

default_app_config = 'workflow_engine.apps.WorkflowEngineConfig'
