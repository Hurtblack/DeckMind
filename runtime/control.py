"""Runtime control commands that should not be sent to the model."""

from __future__ import annotations


_DEEPSEEK_MODEL_ALIASES = {
    "pro": "deepseek-v4-pro",
    "v4-pro": "deepseek-v4-pro",
    "deepseek-pro": "deepseek-v4-pro",
    "deepseek-v4-pro": "deepseek-v4-pro",
    "flash": "deepseek-v4-flash",
    "v4-flash": "deepseek-v4-flash",
    "deepseek-flash": "deepseek-v4-flash",
    "deepseek-v4-flash": "deepseek-v4-flash",
}


def _resolve_model_alias(provider: str, model: str) -> str:
    normalized = model.strip().lower()
    if provider == "deepseek":
        return _DEEPSEEK_MODEL_ALIASES.get(normalized, model)
    return model


def _parse_natural_language_model_switch(
    line: str,
    *,
    current_provider: str,
) -> dict[str, str | None] | None:
    compact = "".join(line.strip().lower().split())
    if not compact:
        return None

    provider = "deepseek" if "deepseek" in compact else current_provider
    if provider != "deepseek":
        return None

    has_switch_intent = any(word in compact for word in (
        "换",
        "切换",
        "切到",
        "切回",
        "改成",
        "换成",
        "switch",
    ))
    if not has_switch_intent:
        return None

    if "pro" in compact:
        return {"provider": provider, "model": "deepseek-v4-pro"}
    if "flash" in compact:
        return {"provider": provider, "model": "deepseek-v4-flash"}
    return None


def parse_control_command(
    line: str,
    *,
    current_provider: str,
) -> dict[str, str | None] | None:
    """Parse REPL/chat control commands for switching LLM settings."""
    parts = line.split()
    if not parts:
        return None

    command = parts[0].lower()
    if command == "/model":
        if len(parts) != 2:
            raise ValueError("Usage: /model <model>")
        provider = current_provider
        return {
            "provider": provider,
            "model": _resolve_model_alias(provider, parts[1]),
        }

    if command in {"/api", "/provider"}:
        if len(parts) not in {2, 3}:
            raise ValueError("Usage: /api <provider> [model]")
        provider = parts[1].lower()
        return {
            "provider": provider,
            "model": (
                _resolve_model_alias(provider, parts[2])
                if len(parts) == 3
                else None
            ),
        }

    return _parse_natural_language_model_switch(
        line,
        current_provider=current_provider,
    )
