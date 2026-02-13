from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
import json


class Document(models.Model):
    """Model for uploaded PDF documents"""

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("success", "Success"),
        ("failed", "Failed"),
    ]

    paper = models.OneToOneField(
        "webApp.Paper",
        on_delete=models.CASCADE,
        related_name="document",
        null=True,
        blank=True,
        help_text="Associated Paper from webApp",
    )
    title = models.CharField(max_length=255)
    pdf_file = models.FileField(upload_to="pdfs/")
    html_file = models.FileField(upload_to="htmls/", null=True, blank=True)
    uploaded_at = models.DateTimeField(default=timezone.now)
    converted_at = models.DateTimeField(null=True, blank=True)
    conversion_status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="pending"
    )
    conversion_error = models.TextField(
        blank=True, null=True, help_text="Error message if conversion failed"
    )

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return self.title


class AnnotationCategory(models.Model):
    """Model for annotation categories with hierarchical support"""

    name = models.CharField(max_length=100, unique=True)
    color = models.CharField(
        max_length=7, default="#FF0000", help_text="Hex color code"
    )
    description = models.TextField(blank=True)
    embedding = models.JSONField(default=dict, help_text="Embedding vector as JSON")
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="subcategories",
    )
    order = models.IntegerField(default=0, help_text="Order for display")

    class Meta:
        verbose_name_plural = "Annotation Categories"
        ordering = ["order", "name"]

    def __str__(self):
        if self.parent:
            return f"{self.parent.name} → {self.name}"
        return self.name

    def get_full_path(self):
        """Returns the full path of the category including parent"""
        if self.parent:
            return f"{self.parent.name} → {self.name}"
        return self.name

    def get_prompt_text(self):
        """
        Returns a formatted string combining Hierarchy, Name, and Description.
        Format: "Category: Parent > Name | Description: ..."
        """
        # Calculate full path
        if self.parent:
            full_path = f"{self.parent.name} > {self.name}"
        else:
            full_path = self.name

        # Handle empty descriptions
        desc_text = (
            self.description.strip() if self.description else "No definition provided."
        )

        return f"Category: {full_path}\nDescription: {desc_text}"


class Annotation(models.Model):
    """Model for storing annotations on HTML documents"""

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="annotations"
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="annotations",
        help_text="User who created this annotation"
    )
    category = models.ForeignKey(
        "AnnotationCategory", on_delete=models.PROTECT, related_name="annotations"
    )
    selected_text = models.TextField()
    html_selector = models.TextField(
        help_text="CSS selector or XPath for the annotated element"
    )
    position_data = models.JSONField(
        default=dict, help_text="Stores position and selection data"
    )
    embedding = models.BinaryField(
        null=True, blank=True, help_text="Embedding vector as binary data"
    )
    similarity_score = models.FloatField(
        null=True, blank=True, help_text="Cosine similarity score with category"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.category} - {self.selected_text[:50]}"
