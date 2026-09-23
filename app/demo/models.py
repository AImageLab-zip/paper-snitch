from django.db import models


class DemoScenario(models.Model):
    """A completed workflow run that the poster demo replays when its PDF is uploaded."""

    paper = models.ForeignKey(
        "webApp.Paper", on_delete=models.CASCADE, related_name="demo_scenarios"
    )
    workflow_run = models.ForeignKey(
        "workflow_engine.WorkflowRun",
        on_delete=models.CASCADE,
        related_name="demo_scenarios",
        help_text="Completed run whose node timings, logs and results are replayed",
    )
    label = models.CharField(
        max_length=100, blank=True, help_text="Short tagline shown on the sample card"
    )
    pdf_sha256 = models.CharField(
        max_length=64, db_index=True, help_text="Hash of the paper PDF, used to recognise uploads"
    )
    order = models.IntegerField(default=0)
    target_duration_s = models.PositiveIntegerField(
        default=75, help_text="Replay length of the workflow at 1x speed"
    )
    is_active = models.BooleanField(default=True)
    match_stats = models.JSONField(
        default=dict, blank=True, help_text="Evidence-matching dry run from prepare_demo"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.paper.title[:60]} ({self.workflow_run_id})"
