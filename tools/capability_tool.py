"""Agent-facing tools for runtime capabilities."""

from __future__ import annotations

import inspect
from typing import Any

from runtime.capabilities.registry import get_capability
from runtime.capabilities.registry import list_capabilities as registry_list_capabilities


async def list_capabilities() -> dict[str, Any]:
    return {
        "ok": True,
        "capabilities": registry_list_capabilities(),
    }


async def run_capability(
    name: str,
    args: dict[str, Any] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    capability = get_capability(name)
    if capability is None:
        return {
            "ok": False,
            "error": "unknown_capability",
            "capability": name,
            "suggestions": ["list_capabilities"],
        }

    arguments = dict(args or {})
    if capability.risk != "safe" and not confirm:
        return {
            "ok": True,
            "dry_run": True,
            "capability": capability.name,
            "description": capability.description,
            "risk": capability.risk,
            "confirm_required": capability.confirm_required,
            "args": arguments,
        }

    signature = inspect.signature(capability.handler)
    if "confirm" in signature.parameters:
        arguments["confirm"] = confirm
    return await capability.handler(**arguments)
