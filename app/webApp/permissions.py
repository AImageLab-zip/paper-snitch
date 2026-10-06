"""Who may run pipelines (and on whose key) and who may see which runs and papers."""
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db.models import Q

from webApp.services.credentials import has_usable_key, uses_system_key


class StaffRequiredMixin(UserPassesTestMixin):
    """Staff only; anonymous users are sent to login, others get 403."""

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff


def is_staff(user) -> bool:
    return bool(user and user.is_authenticated and user.is_staff)


def can_run_pipelines(user) -> bool:
    """Staff (server key) or a registered user with their own key."""
    return has_usable_key(user)


def visible_runs(queryset, user):
    """Public runs of visible papers, plus the user's own; staff see everything.
    A public run never exposes a private uploaded paper."""
    if is_staff(user):
        return queryset
    if user and user.is_authenticated:
        paper_ok = Q(paper__is_public=True) | Q(paper__owner=user)
        return queryset.filter((Q(is_public=True) & paper_ok) | Q(created_by=user))
    return queryset.filter(is_public=True, paper__is_public=True)


def visible_papers(queryset, user):
    """Public papers, plus the user's own uploads; staff see everything."""
    if is_staff(user):
        return queryset
    if user and user.is_authenticated:
        return queryset.filter(Q(is_public=True) | Q(owner=user))
    return queryset.filter(is_public=True)


def can_view_run(run, user) -> bool:
    if is_staff(user) or (user is not None and user.is_authenticated and run.created_by_id == user.id):
        return True
    return run.is_public and can_view_paper(run.paper, user)


def can_view_paper(paper, user) -> bool:
    return paper.is_public or is_staff(user) or (
        user is not None and user.is_authenticated and paper.owner_id == user.id
    )


def can_manage_run(run, user) -> bool:
    """Rerun steps or change visibility: the run's owner or staff."""
    return is_staff(user) or (user is not None and user.is_authenticated and run.created_by_id == user.id)


def default_visibility(user) -> bool:
    """New runs are public for staff, private for everyone else."""
    return uses_system_key(user)


DEFAULT_PIPELINE_MODEL = "gpt-4o"


def allowed_model_configs(user):
    """Models a user can run the pipeline with. The pipeline uses an OpenAI client,
    so only OpenAI-backed configurations work (for staff and users alike)."""
    from webApp.models import LLMModelConfig

    if not (user and user.is_authenticated):
        return []
    return list(
        LLMModelConfig.objects.filter(is_active=True, api_key_env_var="OPENAI_API_KEY")
        .exclude(model_key="test")
        .order_by("visual_name")
    )


def default_model_for(user, allowed=None):
    allowed = allowed if allowed is not None else allowed_model_configs(user)
    names = [cfg.model for cfg in allowed]
    if DEFAULT_PIPELINE_MODEL in names:
        return DEFAULT_PIPELINE_MODEL
    return names[0] if names else None
