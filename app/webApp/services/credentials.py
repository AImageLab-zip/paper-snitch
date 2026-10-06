"""OpenAI key handling: encrypted per-user keys and the single rule that picks a key."""
import os
import re

from asgiref.sync import sync_to_async
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.core.exceptions import ImproperlyConfigured

_KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{6,}")


class MissingAPIKey(Exception):
    """A non-staff user tried to run a pipeline without a stored OpenAI key."""


def _fernet() -> MultiFernet:
    # Comma-separated so the key can be rotated: new key first, old keys after
    raw = os.environ.get("FIELD_ENCRYPTION_KEY", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY is not set")
    return MultiFernet([Fernet(k) for k in keys])


def encrypt(raw: str) -> str:
    return _fernet().encrypt(raw.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise ImproperlyConfigured("Stored API key cannot be decrypted with FIELD_ENCRYPTION_KEY") from e


def mask(raw: str) -> str:
    return f"{raw[:3]}…{raw[-4:]}" if len(raw) > 8 else "…"


def redact(text):
    """Remove anything that looks like an OpenAI key (auth errors echo part of it)."""
    if not text:
        return text
    return _KEY_PATTERN.sub("sk-…[redacted]", str(text))


def validate_openai_key(raw: str) -> tuple[bool, str]:
    """Cheap call that fails fast on a wrong or revoked key."""
    from openai import AuthenticationError, OpenAI, OpenAIError

    try:
        OpenAI(api_key=raw, max_retries=0, timeout=15).models.list()
        return True, ""
    except AuthenticationError:
        return False, "OpenAI rejected this key."
    except OpenAIError as e:
        return False, f"Could not verify the key with OpenAI: {redact(e)}"


def uses_system_key(user) -> bool:
    """Staff (and runs with no user, e.g. management commands) use the server key."""
    return user is None or bool(getattr(user, "is_staff", False))


def resolve_openai_key(user) -> str:
    """The only place a key is chosen for a pipeline run."""
    if uses_system_key(user):
        return os.environ["OPENAI_API_KEY"]
    from webApp.models import UserAPIKey

    stored = UserAPIKey.objects.filter(user=user).first()
    if not stored:
        raise MissingAPIKey(f"User {user.pk} has no OpenAI API key")
    return decrypt(stored.encrypted_key)


def has_usable_key(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if uses_system_key(user):
        return True
    from webApp.models import UserAPIKey

    return UserAPIKey.objects.filter(user=user).exists()


@sync_to_async
def aresolve_run_key(workflow_run_id) -> str:
    """Key for a workflow run: the key of whoever started it."""
    from workflow_engine.models import WorkflowRun

    run = WorkflowRun.objects.select_related("created_by").get(id=workflow_run_id)
    return resolve_openai_key(run.created_by)


@sync_to_async
def aget_user(user_id):
    if user_id is None:
        return None
    from django.contrib.auth import get_user_model

    return get_user_model().objects.get(id=user_id)
