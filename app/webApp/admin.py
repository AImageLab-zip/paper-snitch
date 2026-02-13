from django.contrib import admin
from django.utils.html import format_html
from .models import (
    AnalysisTask,
    Operations,
    Conference,
    Paper,
    Dataset,
    PDFPaper,
    Analysis,
    Criterion,
    AnalysisCriterion,
    BugReport,
    TokenUsage,
    LLMModelConfig,
    Prompt,
)
from .models_schema import DatabaseSchema


@admin.register(Operations)
class OperationsAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]


@admin.register(Conference)
class ConferenceAdmin(admin.ModelAdmin):
    list_display = ["name", "year", "last_update"]
    list_filter = ["year"]
    search_fields = ["name"]
    readonly_fields = ["last_update"]


@admin.register(Paper)
class PaperAdmin(admin.ModelAdmin):
    list_display = ["title", "doi", "last_update"]
    search_fields = ["title", "doi", "authors", "abstract"]
    readonly_fields = ["last_update"]


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ["name", "url", "last_update"]
    list_filter = ["dimension"]
    search_fields = ["name"]
    readonly_fields = ["last_update"]


@admin.register(PDFPaper)
class PDFPaperAdmin(admin.ModelAdmin):
    list_display = ["paper", "last_update"]
    readonly_fields = ["last_update"]


@admin.register(Criterion)
class CriterionAdmin(admin.ModelAdmin):
    list_display = ["name", "key"]
    search_fields = ["name", "key"]


class AnalysisCriterionInline(admin.TabularInline):
    model = AnalysisCriterion
    extra = 0
    fields = ["criterion", "extracted", "score_explanation", "score"]
    readonly_fields = []


@admin.register(Analysis)
class AnalysisAdmin(admin.ModelAdmin):
    list_display = [
        "paper",
        "user",
        "model_name",
        "created_at",
    ]
    list_filter = ["model_name", "user", "created_at"]
    search_fields = ["paper__title", "model_name", "user__username"]
    readonly_fields = ["created_at"]
    inlines = [AnalysisCriterionInline]
    fieldsets = (
        (None, {"fields": ("paper", "user", "model_name", "model_key")}),
        (
            "Metadata",
            {
                "fields": (
                    "input_tokens",
                    "output_tokens",
                    "duration",
                    "raw_response",
                    "error",
                    "created_at",
                )
            },
        ),
    )


@admin.register(AnalysisCriterion)
class AnalysisCriterionAdmin(admin.ModelAdmin):
    list_display = ["analysis", "criterion", "score"]
    list_filter = ["criterion", "score"]
    search_fields = ["analysis__paper__title", "criterion__name"]


@admin.register(BugReport)
class BugReportAdmin(admin.ModelAdmin):
    list_display = ["title", "report_type", "user", "priority", "status", "created_at"]
    list_filter = ["report_type", "priority", "status", "created_at"]
    search_fields = ["title", "description", "user__username"]
    readonly_fields = ["created_at", "updated_at", "browser_info"]
    list_editable = ["status", "priority"]
    fieldsets = (
        (None, {"fields": ("title", "report_type", "user", "priority", "status")}),
        (
            "Details",
            {
                "fields": (
                    "description",
                    "steps_to_reproduce",
                    "expected_behavior",
                    "actual_behavior",
                )
            },
        ),
        (
            "Technical Info",
            {
                "fields": ("browser_info", "screenshot"),
                "classes": ("collapse",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )


@admin.register(TokenUsage)
class TokenUsageAdmin(admin.ModelAdmin):
    list_display = ["date", "model_var", "tokens_used", "updated_at"]
    list_filter = ["date", "model_var"]
    search_fields = ["model_var"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["-date", "model_var"]


@admin.register(LLMModelConfig)
class LLMModelConfigAdmin(admin.ModelAdmin):
    list_display = [
        "visual_name",
        "model_key",
        "model",
        "api_key_env_var",
        "is_active",
        "updated_at",
    ]
    list_filter = ["is_active", "api_key_env_var", "reasoning_effort"]
    search_fields = ["visual_name", "model_key", "model"]
    readonly_fields = ["created_at", "updated_at"]
    list_editable = ["is_active"]
    fieldsets = (
        (
            "Identification",
            {
                "fields": ("model_key", "visual_name", "model"),
            },
        ),
        (
            "API Configuration",
            {
                "fields": ("api_key_env_var", "base_url", "token_var"),
            },
        ),
        (
            "Model Settings",
            {
                "fields": ("temperature", "reasoning_effort"),
            },
        ),
        (
            "Status",
            {
                "fields": ("is_active", "created_at", "updated_at"),
            },
        ),
    )


@admin.register(Prompt)
class PromptAdmin(admin.ModelAdmin):
    list_display = ["name", "template", "created_at", "updated_at"]
    search_fields = ["name", "template"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(AnalysisTask)
class AnalysisTaskAdmin(admin.ModelAdmin):
    list_display = ["id", "paper", "user", "status", "created_at", "updated_at"]
    list_filter = ["status", "created_at", "updated_at"]
    search_fields = ["paper__title", "user__username"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(DatabaseSchema)
class DatabaseSchemaAdmin(admin.ModelAdmin):
    list_display = ["created_at", "migration_name", "schema_preview"]
    readonly_fields = ["created_at", "schema_diagram_preview", "schema_dot"]
    list_filter = ["created_at"]
    search_fields = ["migration_name", "notes"]
    
    fieldsets = (
        (
            "Schema Information",
            {
                "fields": ("created_at", "migration_name", "notes"),
            },
        ),
        (
            "Diagram",
            {
                "fields": ("schema_diagram_preview", "schema_diagram"),
            },
        ),
        (
            "GraphViz Source",
            {
                "fields": ("schema_dot",),
                "classes": ("collapse",),
            },
        ),
    )
    
    def schema_preview(self, obj):
        """Small thumbnail preview in list view."""
        if obj.schema_diagram:
            return format_html(
                '<img src="{}" style="max-height: 40px; max-width: 60px;" />',
                obj.schema_diagram.url
            )
        return "No diagram"
    schema_preview.short_description = "Preview"
    
    def schema_diagram_preview(self, obj):
        """Full size preview in detail view."""
        if obj.schema_diagram:
            return format_html(
                '<img src="{}" style="max-width: 100%; height: auto;" />',
                obj.schema_diagram.url
            )
        return "No diagram available"
    schema_diagram_preview.short_description = "Database Schema Diagram"
