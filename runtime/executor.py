"""Executor: dispatches tool calls + asks the user when a call is risky.

Policy: never silently refuse. Whenever a call looks dangerous, the
Executor asks the user — the user always has final say.

Three risk classes:

  - safe         : read-only ops. Pass through silently.
  - side_effect  : ask [y/n/a] before each call.
                   `a` = allow this tool for the rest of the session.
  - destructive  : recommended path is dry-run (confirm=false) then
                   confirm=true. The Executor asks the user before
                   running confirm=true. If the LLM skips the dry-run
                   and calls confirm=true directly, the user gets a
                   stronger warning prompt — but can still approve.

Unknown tools are treated as destructive.

A separate per-tool input check (e.g. close_game's denylist) lives
inside each tool — also as a warning prompt, never a hard refusal.
"""

from __future__ import annotations

from typing import Any

from tools import get as get_tool

from .prompt import ask, is_yes


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

# For destructive tools, the argument that identifies the target. Used
# to match a confirm=true call against an earlier dry-run preview.
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
    """Dispatches tool calls and asks the user before risky ones."""

    def __init__(self) -> None:
        # Side-effect tools the user white-listed for this session.
        self._allow_all: set[str] = set()
        # (tool_name, key) pairs already dry-run in this session — used
        # to decide whether a confirm=true call had a recent preview.
        self._dry_run_seen: set[tuple[str, str]] = set()

    async def run(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Gate + dispatch one tool call."""
        fn = get_tool(name)
        if fn is None:
            return {"ok": False, "error": f"unknown tool '{name}'"}

        risk = _risk_of(name)

        # ----- permission gate -----

        if risk == "safe":
            pass  # read-only — no prompt

        elif risk == "side_effect":
            if name not in self._allow_all:
                ans = await ask(
                    f"    ⚠ side-effect: {name}({arguments})  "
                    f"[y=允许 / n=拒绝 / a=本会话此工具全允许] > "
                )
                if ans == "a":
                    self._allow_all.add(name)
                elif not (is_yes(ans) or ans == ""):
                    return {"ok": False, "denied": True,
                            "reason": f"user rejected side-effect call to {name}"}

        elif risk == "destructive":
            key_arg = DESTRUCTIVE_KEY.get(name, "")
            target = str(arguments.get(key_arg, "")).strip().lower()
            confirm = bool(arguments.get("confirm", False))

            if not confirm:
                # Dry-run path: harmless. Remember it so a later
                # confirm=true call is recognized as "previewed first".
                self._dry_run_seen.add((name, target))
            else:
                # Real execution. Decide which warning to use based on
                # whether the LLM did a dry-run first.
                if (name, target) in self._dry_run_seen:
                    prompt = (f"    🚨 DESTRUCTIVE: {name}({arguments})  "
                              f"[y=确认执行 / n=取消] > ")
                else:
                    prompt = (f"    🚨 DESTRUCTIVE (NO DRY-RUN!): "
                              f"{name}({arguments})  "
                              f"LLM skipped the preview step — please double-check. "
                              f"[y=确认执行 / n=取消] > ")
                ans = await ask(prompt)
                if not is_yes(ans):
                    return {"ok": False, "denied": True,
                            "reason": f"user rejected destructive call to {name}"}

        # ----- execute -----
        try:
            return await fn(**arguments)
        except TypeError as e:
            # Wrong/missing args — common LLM mistake. Report cleanly so
            # the planner can correct itself on the next turn.
            return {"ok": False, "error": f"bad arguments for {name}: {e}"}
        except Exception as e:  # pragma: no cover — defensive
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
