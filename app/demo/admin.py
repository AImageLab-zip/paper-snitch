from django.contrib import admin

from .models import DemoScenario


@admin.register(DemoScenario)
class DemoScenarioAdmin(admin.ModelAdmin):
    list_display = ("paper", "label", "order", "target_duration_s", "is_active", "updated_at")
    list_editable = ("order", "is_active")
    raw_id_fields = ("paper", "workflow_run")
