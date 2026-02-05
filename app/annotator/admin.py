from django.contrib import admin
from .models import Document, Annotation, AnnotationCategory


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ["title", "uploaded_at", "converted_at"]
    list_filter = ["uploaded_at", "converted_at"]
    search_fields = ["title"]


@admin.register(Annotation)
class AnnotationAdmin(admin.ModelAdmin):
    list_display = ["document", "category", "selected_text_preview", "created_at"]
    list_filter = ["category", "created_at"]
    search_fields = ["selected_text", "category"]

    def selected_text_preview(self, obj):
        return (
            obj.selected_text[:50] + "..."
            if len(obj.selected_text) > 50
            else obj.selected_text
        )

    selected_text_preview.short_description = "Selected Text"


@admin.register(AnnotationCategory)
class AnnotationCategoryAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "parent",
        "color",
        "order",
        "description",
    ]
    list_filter = ["parent"]
    search_fields = ["name", "description"]
    list_editable = ["order"]
    ordering = ["order", "name"]
    fields = ["name", "parent", "color", "description", "order", "embedding"]

    def embedding_preview(self, obj):
        """Shows the size of the vector and the first 3 values."""
        if not obj.embedding:
            return "No embedding"

        # Calculate length and show first few items
        length = len(obj.embedding)
        preview = str(obj.embedding[:3]) + "..."

        return f"Size: {length} | {preview}"

    # OPTIONAL: This gives the column a nice header name
    embedding_preview.short_description = "Embedding Vector"
