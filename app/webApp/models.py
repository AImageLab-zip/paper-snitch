from django.db import models
import uuid
from .models_schema import DatabaseSchema


class Operations(models.Model):
    """Different operations of analizer"""

    name = models.CharField(max_length=100, unique=True, verbose_name="Operation type")

    class Meta:
        verbose_name = "Operations"
        verbose_name_plural = "Operations"

    def __str__(self):
        return self.name


class Conference(models.Model):

    name = models.CharField(max_length=300, verbose_name="Conference name")
    year = models.IntegerField(verbose_name="Year", blank=True, null=True)
    url = models.URLField(verbose_name="Website", blank=True, max_length=500)
    last_update = models.DateTimeField(auto_now=True, verbose_name="Last update")

    class Meta:
        ordering = ["name"]
        verbose_name = "Conference"
        verbose_name_plural = "Conferences"

    def __str__(self):
        return f"{self.name}{self.year}"


# class Author(models.Model):

#     email = models.CharField(max_length=500, verbose_name="Authot mail", blank=True, null=True)
#     name = models.CharField(max_length=500, verbose_name="Author name")
#     is_sus = models.BooleanField(default=False)

#     class Meta:
#         verbose_name = "Author"
#         verbose_name_plural = "Authors"

#     def __str__(self):
#         return self.name

# TODO aggiungere un modello relativo agli score, sia per aver salvato il valore che il testo che ha portato a tale valore


class Paper(models.Model):

    title = models.CharField(max_length=500, verbose_name="Title")
    doi = models.CharField(
        max_length=255, unique=True, verbose_name="DOI", blank=True, null=True
    )
    abstract = models.TextField(verbose_name="Abstract", blank=True, null=True)
    supp_materials = models.FileField(
        upload_to="supp_materials",
        verbose_name="Supplementary materials",
        blank=True,
        null=True,
    )
    paper_url = models.URLField(verbose_name="Paper URL", blank=True, max_length=500)
    pdf_url = models.URLField(verbose_name="PDF URL", blank=True, max_length=500)
    code_url = models.URLField(verbose_name="Code URL", blank=True, max_length=500)
    authors = models.CharField(
        max_length=255, unique=True, verbose_name="Authors", blank=True, null=True
    )
    conference = models.ForeignKey(
        Conference,
        on_delete=models.PROTECT,
        related_name="papers",
        verbose_name="Conference",
        blank=True,
        null=True,
    )
    file = models.FileField(
        upload_to="pdfs/",
        blank=True,
        null=True,
    )

    text = models.TextField(verbose_name="Full paper text", blank=True, null=True)
    code_text = models.TextField(
        verbose_name="Code text retrieved from the repository", blank=True, null=True
    )
    reviews = models.TextField(verbose_name="All reviews text", blank=True, null=True)
    author_feedback = models.TextField(
        verbose_name="Author feedback", blank=True, null=True
    )
    meta_review = models.TextField(
        verbose_name="All Meta-reviews text", blank=True, null=True
    )
    last_update = models.DateTimeField(
        auto_now=True, verbose_name="Last update", blank=True, null=True
    )

    class Meta:
        verbose_name = "Paper"
        verbose_name_plural = "Papers"

    def __str__(self):
        return self.title


class Dataset(models.Model):

    name = models.CharField(max_length=300, verbose_name="Dataset name")
    description = models.CharField(
        max_length=500, verbose_name="Dataset description", blank=True, null=True
    )
    url = models.URLField(verbose_name="Dataset URL", blank=True, max_length=500)
    dimension = models.IntegerField(
        verbose_name="Dataset dimension (in MB)", blank=True, null=True
    )
    from_pdf = models.BooleanField(
        default=False, verbose_name="Dataset got from the PDF"
    )
    papers = models.ManyToManyField(
        Paper, related_name="datasets", verbose_name="Paper datasets"
    )
    last_update = models.DateTimeField(
        auto_now=True, verbose_name="Last update", blank=True, null=True
    )

    class Meta:
        verbose_name = "Dataset"
        verbose_name_plural = "Datasets"

    def __str__(self):
        return self.name


class PDFPaper(models.Model):

    paper = models.ForeignKey(
        Paper, on_delete=models.CASCADE, related_name="pdf_papers"
    )
    abstract = models.TextField(verbose_name="Abstract")
    supp_materials = models.TextField(
        verbose_name="Supplementary materials", blank=True, null=True
    )
    code_url = models.URLField(verbose_name="code URL", blank=True, max_length=500)
    text = models.TextField(verbose_name="Full paper text", blank=True, null=True)
    last_update = models.DateTimeField(
        auto_now=True, verbose_name="Last update", blank=True, null=True
    )

    class Meta:
        verbose_name = "PDF Paper"
        verbose_name_plural = "PDF Papers"

    def __str__(self):
        return self.title


class Criterion(models.Model):
    """Defines evaluation criteria for paper analysis."""

    name = models.CharField(max_length=100, unique=True, verbose_name="Criterion Name")
    key = models.CharField(max_length=50, unique=True, verbose_name="Criterion Key")
    description = models.TextField(verbose_name="Description", blank=True, null=True)
    weight = models.FloatField(
        verbose_name="Weight", default=1.0, blank=True, null=True
    )

    class Meta:
        verbose_name = "Criterion"
        verbose_name_plural = "Criteria"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Analysis(models.Model):
    """Stores LLM analysis results for a paper."""

    paper = models.ForeignKey(
        Paper,
        on_delete=models.CASCADE,
        related_name="analyses",
        verbose_name="Paper",
    )
    user = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        related_name="analyses",
        verbose_name="User",
        blank=True,
        null=True,
    )
    model_name = models.CharField(max_length=100, verbose_name="LLM Model Name")
    model_key = models.CharField(max_length=50, verbose_name="Model Key")

    # Metadata
    input_tokens = models.IntegerField(
        verbose_name="Input Tokens", blank=True, null=True
    )
    output_tokens = models.IntegerField(
        verbose_name="Output Tokens", blank=True, null=True
    )
    duration = models.FloatField(
        verbose_name="Duration (seconds)", blank=True, null=True
    )
    raw_response = models.JSONField(
        verbose_name="Raw LLM Response", blank=True, null=True
    )
    error = models.TextField(verbose_name="Error Message", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")

    class Meta:
        verbose_name = "Analysis"
        verbose_name_plural = "Analyses"
        ordering = ["-created_at"]

    def final_score(self):
        """
        Calculates the weighted average score of the analysis based on criteria weights.
        Criteria with negative scores are ignored.
        """
        weighted_score = 0
        total_weight = 0

        criteria_results = self.criteria_results.select_related("criterion").all()

        for result in criteria_results:
            score = result.score
            weight = result.criterion.weight

            if score is not None and score >= 0 and weight > 0:
                weighted_score += score * weight
                total_weight += weight

        return round(weighted_score / total_weight, 2)

    def __str__(self):
        return f"{self.paper.title} - {self.model_name}"


class AnalysisCriterion(models.Model):
    """Stores the result of a specific criterion for an analysis."""

    analysis = models.ForeignKey(
        Analysis,
        on_delete=models.CASCADE,
        related_name="criteria_results",
        verbose_name="Analysis",
    )
    criterion = models.ForeignKey(
        Criterion,
        on_delete=models.PROTECT,
        related_name="analysis_results",
        verbose_name="Criterion",
    )
    extracted = models.TextField(
        verbose_name="Extracted Information", blank=True, null=True
    )
    score_explanation = models.TextField(
        verbose_name="Score Explanation", blank=True, null=True
    )
    score = models.IntegerField(verbose_name="Score", blank=True, null=True)

    class Meta:
        verbose_name = "Analysis Criterion Result"
        verbose_name_plural = "Analysis Criterion Results"
        unique_together = ["analysis", "criterion"]

    def __str__(self):
        return f"{self.analysis} - {self.criterion.name}"


class BugReport(models.Model):
    """Stores bug reports and feature suggestions submitted by users."""

    REPORT_TYPE_CHOICES = [
        ("bug", "Bug Report"),
        ("suggestion", "Suggestion"),
    ]

    PRIORITY_CHOICES = [
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
        ("critical", "Critical"),
    ]

    STATUS_CHOICES = [
        ("new", "New"),
        ("in_progress", "In Progress"),
        ("resolved", "Resolved"),
        ("closed", "Closed"),
        ("wont_fix", "Won't Fix"),
    ]

    user = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        related_name="bug_reports",
        verbose_name="Reporter",
        blank=True,
        null=True,
    )
    report_type = models.CharField(
        max_length=20,
        choices=REPORT_TYPE_CHOICES,
        default="bug",
        verbose_name="Report Type",
    )
    title = models.CharField(max_length=200, verbose_name="Title")
    description = models.TextField(verbose_name="Description")
    steps_to_reproduce = models.TextField(
        verbose_name="Steps to Reproduce", blank=True, null=True
    )
    expected_behavior = models.TextField(
        verbose_name="Expected Behavior", blank=True, null=True
    )
    actual_behavior = models.TextField(
        verbose_name="Actual Behavior", blank=True, null=True
    )
    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default="medium",
        verbose_name="Priority",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="new",
        verbose_name="Status",
    )
    browser_info = models.CharField(
        max_length=300, verbose_name="Browser Info", blank=True, null=True
    )
    screenshot = models.ImageField(
        upload_to="bug_screenshots/",
        verbose_name="Screenshot",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    class Meta:
        verbose_name = "Feedback"
        verbose_name_plural = "Feedback"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.get_report_type_display()}] {self.title}"


class TokenUsage(models.Model):
    """Tracks daily token usage for each LLM model."""

    date = models.DateField(verbose_name="Date")
    model_var = models.CharField(max_length=100, verbose_name="Model Variable Name")
    tokens_used = models.BigIntegerField(default=0, verbose_name="Tokens Used")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    class Meta:
        verbose_name = "Token Usage"
        verbose_name_plural = "Token Usage"
        unique_together = ["date", "model_var"]
        ordering = ["-date", "model_var"]

    def __str__(self):
        return f"{self.date} - {self.model_var}: {self.tokens_used}"


class LLMModelConfig(models.Model):
    """Stores LLM model configurations for paper analysis."""

    REASONING_EFFORT_CHOICES = [
        ("none", "None"),
        ("minimal", "Minimal"),
        ("low", "Low"),
        ("medium", "Medium"),
        ("high", "High"),
    ]

    API_KEY_CHOICES = [
        ("OPENAI_API_KEY", "OpenAI API Key"),
        ("GEMINI_API_KEY", "Gemini API Key"),
        ("BYTEPLUS_API_KEY", "BytePlus API Key"),
        ("ANTHROPIC_API_KEY", "Anthropic API Key"),
        ("MOONSHOT_API_KEY", "Moonshot API Key"),
    ]

    # Basic identification
    model_key = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Model Key",
        help_text="Unique identifier for this model configuration (e.g., 'gpt51', 'gemini25_flash')",
    )
    visual_name = models.CharField(
        max_length=100,
        verbose_name="Display Name",
        help_text="Human-readable name shown in the UI",
    )
    model = models.CharField(
        max_length=100,
        verbose_name="Model Name",
        help_text="Actual model name used in API calls (e.g., 'gpt-5.1', 'gemini-2.5-flash')",
    )

    # API configuration
    api_key_env_var = models.CharField(
        max_length=50,
        choices=API_KEY_CHOICES,
        verbose_name="API Key Environment Variable",
        help_text="Environment variable name containing the API key",
    )
    base_url = models.URLField(
        max_length=300, verbose_name="Base URL", help_text="API base URL for this model"
    )

    # Token tracking
    token_var = models.CharField(
        max_length=100,
        verbose_name="Token Variable",
        help_text="Variable name for tracking token usage (e.g., 'TOTAL_TOKEN_OPENAI')",
    )

    # Model-specific settings
    temperature = models.FloatField(
        default=1.0,
        verbose_name="Temperature",
        help_text="Sampling temperature for the model",
    )

    reasoning_effort = models.CharField(
        max_length=20,
        choices=REASONING_EFFORT_CHOICES,
        blank=True,
        null=True,
        verbose_name="Reasoning Effort",
        help_text="Reasoning effort level (for OpenAI models)",
    )

    # Status
    is_active = models.BooleanField(
        default=True,
        verbose_name="Active",
        help_text="Whether this model is available for use",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    class Meta:
        verbose_name = "LLM Model Configuration"
        verbose_name_plural = "LLM Model Configurations"
        ordering = ["visual_name"]

    def __str__(self):
        return f"{self.visual_name} ({self.model_key})"

    def get_api_key(self):
        """Get the actual API key from environment variable."""
        import os

        return os.getenv(self.api_key_env_var)

    def to_config_dict(self):
        """Convert model instance to configuration dictionary for LLM analysis."""
        import os

        config = {
            "model": self.model,
            "token_var": self.token_var,
            "model_key": self.model_key,
            "api_key": os.getenv(self.api_key_env_var),
            "base_url": self.base_url,
            "visual_name": self.visual_name,
            "temperature": self.temperature,
        }

        # Add reasoning effort if set
        if self.reasoning_effort:
            config["reasoning"] = {"effort": self.reasoning_effort}

        return config

    @classmethod
    def get_all_configs(cls):
        """Get all active model configurations as a dictionary."""
        configs = {}
        for model_config in cls.objects.filter(is_active=True):
            configs[model_config.model_key] = model_config.to_config_dict()
        return configs

    @classmethod
    def get_available_models(cls):
        """Get dictionary of available models for selection."""
        return {
            config.model_key: config.visual_name
            for config in cls.objects.filter(is_active=True)
        }


class Prompt(models.Model):
    """Stores prompt templates for LLM interactions."""

    name = models.CharField(
        max_length=100,
        verbose_name="Prompt Name",
        help_text="Name for the prompt template",
        blank=True,
        null=True,
    )
    template = models.TextField(
        verbose_name="Prompt Template",
        help_text="The actual prompt template text with placeholders",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    class Meta:
        verbose_name = "Prompt"
        verbose_name_plural = "Prompts"
        ordering = ["name"]

    def __str__(self):
        return self.name


class AnalysisTask(models.Model):
    """Stores the status of a running analysis task."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(max_length=20, default="pending")
    progress = models.IntegerField(default=0)
    current_step = models.CharField(max_length=255, default="Initializing...")
    total_steps = models.IntegerField(default=0)
    completed_steps = models.IntegerField(default=0)
    results = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, null=True)
    is_read = models.BooleanField(default=False)

    paper = models.ForeignKey(
        Paper, on_delete=models.CASCADE, related_name="analysis_tasks"
    )
    user = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True
    )
    selected_models = models.JSONField(default=list)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Task {self.id} - {self.status}"
