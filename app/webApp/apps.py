from django.apps import AppConfig


class WebappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'webApp'
    
    def ready(self):
        """Import signals when app is ready."""
        import webApp.signals
