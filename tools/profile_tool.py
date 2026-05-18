"""Profile tools — let the agent remember things across sessions.

`remember(key, value)` is intentionally classified as safe in the
Executor: it only touches a small JSON file owned by the user, and
asking for confirmation every time would interrupt natural
conversation ("我叫赖天宇" → confirm? → ugh). If the LLM saves
something wrong, the user can ask it to forget or edit the file
directly.
"""

from __future__ import annotations

from typing import Any


async def remember(key: str, value: str) -> dict[str, Any]:
    """Save a fact about the user. Overwrites any previous value."""
    # Lazy import to avoid a tools <-> runtime circular import at startup.
    from runtime.profile import load_profile, save_profile

    key = (key or "").strip()
    value = (value or "").strip()
    if not key:
        return {"ok": False, "error": "key is required"}
    if not value:
        return {"ok": False, "error": "value is required"}

    facts = load_profile()
    previous = facts.get(key)
    facts[key] = value
    save_profile(facts)
    return {
        "ok": True,
        "key": key, "value": value,
        "previous": previous,            # so the LLM can confirm "updated X from A to B"
        "total_facts": len(facts),
    }


async def forget(key: str) -> dict[str, Any]:
    """Remove a stored fact by key."""
    from runtime.profile import load_profile, save_profile

    key = (key or "").strip()
    facts = load_profile()
    if key not in facts:
        return {"ok": False, "error": f"no fact named '{key}' to forget",
                "known_keys": list(facts.keys())}
    removed = facts.pop(key)
    save_profile(facts)
    return {"ok": True, "forgot": key, "value_was": removed,
            "remaining": len(facts)}


async def list_profile() -> dict[str, Any]:
    """Return every fact currently stored about the user."""
    from runtime.profile import load_profile

    facts = load_profile()
    return {"ok": True, "count": len(facts), "facts": facts}
