from django.contrib import admin
from django.utils.html import format_html
from django.db import models
import json
from .models import (
    AnalysisTask,
    Operations,
    Conference,
    Paper,
    Dataset,
    Analysis,
    Criterion,
    AnalysisCriterion,
    BugReport,
    TokenUsage,
    LLMModelConfig,
    Prompt,
    PaperSectionEmbedding,
)
from .models_schema import DatabaseSchema


def format_json_with_highlighting(data):
    """Format JSON data for display."""
    if not data:
        return '<em>No data available</em>'
    
    formatted_json = json.dumps(data, indent=2, ensure_ascii=False)
    
    return format_html(
        '<div style="max-width: 1000px;">'
        '<pre style="'
        'background: #f8f8f8;'
        'border: 1px solid #ddd;'
        'border-radius: 4px;'
        'padding: 15px;'
        'overflow-x: auto;'
        'font-family: \"Consolas\", \"Monaco\", \"Courier New\", monospace;'
        'font-size: 13px;'
        'line-height: 1.6;'
        'max-height: 600px;'
        'overflow-y: auto;'
        '">{}</pre>'
        '</div>',
        formatted_json
    )


@admin.register(Operations)
class OperationsAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]


@admin.register(Conference)
class ConferenceAdmin(admin.ModelAdmin):
    list_display = ["name", "year", "paper_count", "last_update"]
    list_filter = ["year"]
    search_fields = ["name"]
    readonly_fields = ["last_update", "scraping_schema_display"]
    
    def paper_count(self, obj):
        return obj.papers.count()
    paper_count.short_description = "Papers"
    paper_count.admin_order_field = "papers__count"
    
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.annotate(
            models.Count("papers")
        )
        return queryset
    
    def scraping_schema_display(self, obj):
        return format_json_with_highlighting(obj.scraping_schema)
    scraping_schema_display.short_description = "Scraping Schema (JSON)"


class DatasetInline(admin.TabularInline):
    model = Dataset.papers.through
    extra = 0
    verbose_name = "Dataset"
    verbose_name_plural = "Datasets"
    fields = ["dataset"]
    readonly_fields = ["dataset"]
    
    def dataset(self, obj):
        if obj.dataset:
            return format_html(
                '<a href="{}">{}</a><br><small>{}</small>',
                obj.dataset.url if obj.dataset.url else "#",
                obj.dataset.name,
                obj.dataset.url if obj.dataset.url else "No URL"
            )
        return "-"
    dataset.short_description = "Dataset"


@admin.register(Paper)
class PaperAdmin(admin.ModelAdmin):
    list_display = ["title", "doi", "last_update"]
    search_fields = ["title", "doi", "authors", "abstract"]
    readonly_fields = ["last_update", "text_preview", "reviews_preview", "author_feedback_preview", "meta_review_preview", "sections_display", "metadata_display"]
    exclude = ["text", "reviews", "author_feedback", "meta_review", "sections", "metadata"]
    inlines = [DatasetInline]
    
    def text_preview(self, obj):
        if obj.text:
            preview = obj.text[:500]
            return format_html(
                '<div style="max-width: 800px;">'
                '<p>{}</p>'
                '<a href="#" onclick="'
                "event.preventDefault();"
                "var fullText = document.getElementById('full-text-{}');"
                "if (fullText.style.display === 'none') {{"
                "fullText.style.display = 'block';"
                "this.textContent = 'Hide full text';"
                "}} else {{"
                "fullText.style.display = 'none';"
                "this.textContent = 'Show full text';"
                "}}"
                '">Show full text</a>'
                '<div id="full-text-{}" style="display:none; margin-top:10px; padding:10px; background:#f5f5f5; border:1px solid #ddd; max-height:600px; overflow-y:auto; white-space:pre-wrap;">{}</div>'
                '</div>',
                preview + "..." if len(obj.text) > 500 else preview,
                obj.id,
                obj.id,
                obj.text
            )
        return "No text available"
    text_preview.short_description = "Full paper text"
    
    def reviews_preview(self, obj):
        if obj.reviews:
            preview = obj.reviews[:500]
            return format_html(
                '<div style="max-width: 800px;">'
                '<p>{}</p>'
                '<a href="#" onclick="'
                "event.preventDefault();"
                "var fullText = document.getElementById('reviews-{}');"
                "if (fullText.style.display === 'none') {{"
                "fullText.style.display = 'block';"
                "this.textContent = 'Hide full reviews';"
                "}} else {{"
                "fullText.style.display = 'none';"
                "this.textContent = 'Show full reviews';"
                "}}"
                '">Show full reviews</a>'
                '<div id="reviews-{}" style="display:none; margin-top:10px; padding:10px; background:#f5f5f5; border:1px solid #ddd; max-height:600px; overflow-y:auto; white-space:pre-wrap;">{}</div>'
                '</div>',
                preview + "..." if len(obj.reviews) > 500 else preview,
                obj.id,
                obj.id,
                obj.reviews
            )
        return "No reviews available"
    reviews_preview.short_description = "All review text"
    
    def author_feedback_preview(self, obj):
        if obj.author_feedback:
            preview = obj.author_feedback[:500]
            return format_html(
                '<div style="max-width: 800px;">'
                '<p>{}</p>'
                '<a href="#" onclick="'
                "event.preventDefault();"
                "var fullText = document.getElementById('feedback-{}');"
                "if (fullText.style.display === 'none') {{"
                "fullText.style.display = 'block';"
                "this.textContent = 'Hide full feedback';"
                "}} else {{"
                "fullText.style.display = 'none';"
                "this.textContent = 'Show full feedback';"
                "}}"
                '">Show full feedback</a>'
                '<div id="feedback-{}" style="display:none; margin-top:10px; padding:10px; background:#f5f5f5; border:1px solid #ddd; max-height:600px; overflow-y:auto; white-space:pre-wrap;">{}</div>'
                '</div>',
                preview + "..." if len(obj.author_feedback) > 500 else preview,
                obj.id,
                obj.id,
                obj.author_feedback
            )
        return "No author feedback available"
    author_feedback_preview.short_description = "Author feedback"
    
    def meta_review_preview(self, obj):
        if obj.meta_review:
            preview = obj.meta_review[:500]
            return format_html(
                '<div style="max-width: 800px;">'
                '<p>{}</p>'
                '<a href="#" onclick="'
                "event.preventDefault();"
                "var fullText = document.getElementById('meta-review-{}');"
                "if (fullText.style.display === 'none') {{"
                "fullText.style.display = 'block';"
                "this.textContent = 'Hide full meta-review';"
                "}} else {{"
                "fullText.style.display = 'none';"
                "this.textContent = 'Show full meta-review';"
                "}}"
                '">Show full meta-review</a>'
                '<div id="meta-review-{}" style="display:none; margin-top:10px; padding:10px; background:#f5f5f5; border:1px solid #ddd; max-height:600px; overflow-y:auto; white-space:pre-wrap;">{}</div>'
                '</div>',
                preview + "..." if len(obj.meta_review) > 500 else preview,
                obj.id,
                obj.id,
                obj.meta_review
            )
        return "No meta-review available"
    meta_review_preview.short_description = "All meta review text"
    
    def sections_display(self, obj):
        return format_json_with_highlighting(obj.sections)
    sections_display.short_description = "Paper Sections (JSON)"
    
    def metadata_display(self, obj):
        return format_json_with_highlighting(obj.metadata)
    metadata_display.short_description = "Metadata (unknown/unexpected fields)"


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ["name", "url", "last_update"]
    list_filter = ["dimension"]
    search_fields = ["name"]
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


@admin.register(PaperSectionEmbedding)
class PaperSectionEmbeddingAdmin(admin.ModelAdmin):
    list_display = ('paper', 'section_type', 'embedding_model', 'embedding_dimension', 'created_at')
    list_filter = ('section_type', 'embedding_model', 'created_at')
    search_fields = ('paper__title', 'section_type', 'section_text')
    readonly_fields = ('created_at', 'updated_at', 'embedding_dimension', 'embedding_preview')
    
    fieldsets = (
        ('Paper Information', {
            'fields': ('paper',)
        }),
        ('Section Details', {
            'fields': ('section_type', 'section_text')
        }),
        ('Embedding Information', {
            'fields': ('embedding_model', 'embedding_dimension', 'embedding_preview')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def embedding_preview(self, obj):
        """Show first few and last few dimensions of embedding."""
        if not obj.embedding:
            return "No embedding"
        
        embedding = obj.embedding
        if len(embedding) > 10:
            preview = embedding[:5] + ['...'] + embedding[-5:]
        else:
            preview = embedding
        
        return format_html(
            '<div style="font-family: monospace; font-size: 11px;">'
            'Dimension: {} | Preview: {}'
            '</div>',
            len(embedding),
            str(preview)
        )
    embedding_preview.short_description = "Embedding Preview"

