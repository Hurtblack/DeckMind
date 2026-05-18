"""Executor: dispatches tool calls + asks the user when a call is risky.

Policy: ask the user, don't silently block. The only hard refusals
happen inside individual tools, and only when an operation would
actually break the running system (uninstalling a shared Flatpak
runtime, killing PID 1, etc.). Those refusals always come with a
clear `reason` so the LLM can explain why to the user.

Three risk classes here in the Executor:

  - safe         : read-only ops. Pass through silently.
  - side_effect  : ask [y/n/a] before each call.
                   `a` = allow this tool for the rest of the session.
  - destructive  : confirm=false is a free preview (dry-run);
                   confirm=true triggers a [y/n] prompt before running.

Unknown tools are treated as destructive.
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
    "check_for_updates",
    # Filesystem queries — read-only wrappers around `find` and `ps`.
    "find_files",
    "list_processes",
    # Profile read/write: only touches a small user-owned JSON file.
    # Prompting before every "记住我叫 X" would ruin the conversation.
    "remember",
    "forget",
    "list_profile",
    # Notion reads — pure queries, no remote writes. (notion_status and
    # notion_set_default_database touch ~/.deckmind/notion.json only.)
    "notion_status",
    "notion_databases",
    "notion_pages",
    "notion_set_default_database",
    "notion_recent",
    "notion_total",
}

RISK_SIDE_EFFECT: set[str] = {
    "set_volume",
    "press_key",
    "start_key_loop",
    "stop_all_macros",
    "launch_game",
    "close_game",
    # Writes a new row to the user's Notion DB. Worth a [y/n/a] prompt
    # so the user can press `a` once and stop being asked for the rest
    # of the session (typical for batch logging).
    "notion_log_session",
    # Creates a brand-new page (subpage) in Notion — strongest write of
    # the set. Same [y/n/a] gate keeps batch reports tolerable.
    "notion_create_page",
}

RISK_DESTRUCTIVE: set[str] = {
    "install_game",
    "uninstall_game",
    "install_flatpak",
    "uninstall_flatpak",
    "apply_update",
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
            confirm = bool(arguments.get("confirm", False))
            if confirm:
                # `a` from a previous turn pre-approves this tool, so we
                # don't pester the user mid-batch (e.g. uninstalling
                # several flatpaks in a row).
                if name not in self._allow_all:
                    ans = await ask(
                        f"    🚨 DESTRUCTIVE: {name}({arguments})  "
                        f"[y=确认执行 / n=取消 / a=本会话此工具全允许] > "
                    )
                    if ans == "a":
                        self._allow_all.add(name)
                    elif not is_yes(ans):
                        return {"ok": False, "denied": True,
                                "reason": f"user rejected destructive call to {name}"}
            # confirm=False is a dry-run — harmless, pass through silently.

        # ----- execute -----
        try:
            return await fn(**arguments)
        except TypeError as e:
            # Wrong/missing args — common LLM mistake. Report cleanly so
            # the planner can correct itself on the next turn.
            return {"ok": False, "error": f"bad arguments for {name}: {e}"}
        except Exception as e:  # pragma: no cover — defensive
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
