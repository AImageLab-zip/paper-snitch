REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def reasoning_kwargs(model: str, effort: str = "minimal", api: str = "chat") -> dict:
    """Reasoning-effort arguments for reasoning models; empty for models such as gpt-4o, which reject them."""
    if not model.startswith(REASONING_MODEL_PREFIXES):
        return {}
    if api == "responses":
        return {"reasoning": {"effort": effort}}
    return {"reasoning_effort": effort}
