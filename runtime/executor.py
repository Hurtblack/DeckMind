"""Executor: dispatches tool calls + enforces runtime permissions.

The permission gate runs in Python BEFORE the tool is awaited, so the
LLM cannot bypass it by ignoring the system prompt. Three risk classes:

  - safe         : read-only ops (get/list/search). Pass through silently.
  - side_effect  : prompt user with [y/n/a] before every call.
                   `a` = allow this tool for the rest of the session.
  - destructive  : two-gate check.
                   1. confirm=false acts as a dry-run; we record (name, key).
                   2. confirm=true is refused unless we saw a matching
                      dry-run AND the user explicitly types `y`.

Unknown tools are treated as destructive.

A separate per-tool input validation (e.g. close_game's denylist) lives
inside each tool — this Executor only does the generic gating.
"""

from __future__ import annotations

import asyncio
from typing import Any

from tools import get as get_tool


# ---------- risk classification ----------

RISK_SAFE: set[str] = {
    "get_battery",
    "get_volume",
    "list_running_games",
    "list_flatpak_apps",
    "search_flatpak",
    "disk_usage",
    "final_answer",
}

RISK_SIDE_EFFECT: set[str] = {
    "set_volume",
    "press_key",
    "start_key_loop",
    "stop_all_macros",
    "launch_game",
    "close_game",
}

RISK_DESTRUCTIVE: set[str] = {
    "install_game",
    "uninstall_game",
    "install_flatpak",
    "uninstall_flatpak",
}

# For destructive tools, which argument uniquely identifies the target.
# Used to match a confirm=true call against an earlier dry-run.
DESTRUCTIVE_KEY: dict[str, str] = {
    "install_game": "game_name",
    "uninstall_game": "game_name",
    "install_flatpak": "app_id",
    "uninstall_flatpak": "app_id",
}


def _risk_of(name: str) -> str:
    """Return the risk class for a tool. Unknown tools count as destructive."""
    if name in RISK_SAFE:
        return "safe"
    if name in RISK_SIDE_EFFECT:
        return "side_effect"
    if name in RISK_DESTRUCTIVE:
        return "destructive"
    return "destructive"


# ---------- the executor ----------

class Executor:
    """Dispatches tool calls and enforces the permission gate."""

    def __init__(self) -> None:
        # Side-effect tools the user white-listed for this session.
        self._allow_all: set[str] = set()
        # (tool_name, key) pairs already dry-run in this session.
        self._dry_run_seen: set[tuple[str, str]] = set()

    async def _ask(self, prompt: str) -> str:
        """Read one line from the user without blocking the event loop."""
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, lambda: input(prompt))
        return text.strip().lower()

    async def run(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Gate + dispatch one tool call."""
        fn = get_tool(name)
        if fn is None:
            return {"ok": False, "error": f"unknown tool '{name}'"}

        # ----- permission gate -----
        risk = _risk_of(name)

        if risk == "safe":
            pass  # no prompt; always allowed

        elif risk == "side_effect":
            if name not in self._allow_all:
                ans = await self._ask(
                    f"    ⚠ side-effect: {name}({arguments})  "
                    f"[y=允许 / n=拒绝 / a=本会话此工具全允许] > "
                )
                if ans == "a":
                    self._allow_all.add(name)
                elif ans not in {"y", "yes", ""}:
                    return {"ok": False, "denied": True,
                            "reason": f"user rejected side-effect call to {name}"}

        elif risk == "destructive":
            key_arg = DESTRUCTIVE_KEY.get(name, "")
            target = str(arguments.get(key_arg, "")).strip().lower()
            confirm = bool(arguments.get("confirm", False))

            if not confirm:
                # Dry-run path: harmless, just remember it so a follow-up
                # confirm=true call is allowed to proceed to its own prompt.
                self._dry_run_seen.add((name, target))
            else:
                # Real-execution path: refuse if we never saw a dry-run for
                # this exact (tool, target). This blocks the LLM from
                # jumping straight to confirm=true.
                if (name, target) not in self._dry_run_seen:
                    return {"ok": False, "denied": True,
                            "reason": (
                                f"refused: {name}(confirm=true) without a "
                                f"prior dry-run for {key_arg}={target!r}. "
                                "Call with confirm=false first."
                            )}
                ans = await self._ask(
                    f"    🚨 DESTRUCTIVE: {name}({arguments})  "
                    f"[y=确认执行 / n=取消] > "
                )
                if ans not in {"y", "yes"}:
                    return {"ok": False, "denied": True,
                            "reason": f"user rejected destructive call to {name}"}

        # ----- execute -----
        try:
            return await fn(**arguments)
        except TypeError as e:
            # Wrong/missing args — common LLM mistake. Report cleanly so the
            # planner can correct itself on the next turn.
            return {"ok": False, "error": f"bad arguments for {name}: {e}"}
        except Exception as e:  # pragma: no cover — defensive
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
