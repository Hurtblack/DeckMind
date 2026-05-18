"""Executor: actually invoke a tool the planner picked.

Kept as its own module so you can later add policy (allow-lists,
timeouts, confirmation prompts, sandboxing) without touching the agent
loop.
"""

from __future__ import annotations

from typing import Any

from tools import get as get_tool


class Executor:
    """Dispatches a PlannedCall to its registered implementation."""

    async def run(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Look up `name` in the tool registry and await it."""
        fn = get_tool(name)
        if fn is None:
            return {"ok": False, "error": f"unknown tool '{name}'"}
        try:
            return await fn(**arguments)
        except TypeError as e:
            # Wrong/missing args — common LLM mistake. Report cleanly so the
            # planner can correct itself on the next turn.
            return {"ok": False, "error": f"bad arguments for {name}: {e}"}
        except Exception as e:  # pragma: no cover — defensive
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
