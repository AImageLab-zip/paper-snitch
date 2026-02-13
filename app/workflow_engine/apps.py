from django.apps import AppConfig


class WorkflowEngineConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'workflow_engine'
    verbose_name = 'Workflow Engine'
    
    def ready(self):
        """Import signal handlers when app is ready."""
        import workflow_engine.signals  # noqa
