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

from .interfaces import (
    PermissionProvider,
    PermissionRequest,
    RuntimeEventSink,
    TerminalPermissionProvider,
    null_event_sink,
)


# ---------- risk classification ----------

RISK_SAFE: set[str] = {
    "get_battery",
    "get_volume",
    "list_capabilities",
    "list_running_games",
    "list_flatpak_apps",
    "search_flatpak",
    "disk_usage",
    "check_for_updates",
    # Filesystem queries — read-only wrappers around `find` and `ps`.
    "find_files",
    "list_processes",
    "read_text_file",
    # Pacman search — read-only query.
    "pacman_search",
    # SteamOS lock-state query (read-only).
    "steamos_lock_status",
    # Re-locking /usr is reverting to the SAFE default — no prompt.
    "steamos_lock",
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
    # Manual SteamOS unlock — explicit user action; let them confirm.
    "steamos_unlock",
}

RISK_DESTRUCTIVE: set[str] = {
    "install_game",
    "uninstall_game",
    "install_flatpak",
    "uninstall_flatpak",
    "apply_update",
    # Writes a file inside the user's home — same dry-run/confirm gate
    # as the install/uninstall tools.
    "write_text_file",
    # Pacman writes (require sudo + dirty /usr).
    "pacman_install",
    "set_pacman_mirror_china",
    # Restricted command runner — still executes local user-level commands.
    "run_command",
    # Replaces the Decky plugin directory under ~/homebrew/plugins.
    "install_decky_plugin",
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


def _capability_risk(arguments: dict[str, Any]) -> str:
    """Return risk for run_capability using target capability metadata."""
    name = arguments.get("name")
    if not isinstance(name, str):
        return "safe"

    from runtime.capabilities.registry import get_capability

    capability = get_capability(name)
    if capability is None:
        return "safe"
    return capability.risk


# ---------- the executor ----------

class Executor:
    """Dispatches tool calls and asks the user before risky ones."""

    def __init__(
        self,
        *,
        permission_provider: PermissionProvider | None = None,
        event_sink: RuntimeEventSink | None = None,
    ) -> None:
        # Side-effect tools the user white-listed for this session.
        self._allow_all: set[str] = set()
        self._permission_provider = permission_provider or TerminalPermissionProvider()
        self._event_sink = event_sink or null_event_sink

    async def _emit(self, event: dict[str, Any]) -> None:
        await self._event_sink(event)

    async def _request_permission(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        risk: str,
        message: str,
    ) -> str:
        request = PermissionRequest(
            name=name,
            arguments=arguments,
            risk=risk,
            message=message,
        )
        await self._emit({
            "type": "permission_request",
            "name": name,
            "arguments": arguments,
            "risk": risk,
            "message": message,
        })
        decision = await self._permission_provider.request(request)
        await self._emit({
            "type": "permission_result",
            "name": name,
            "risk": risk,
            "decision": decision,
        })
        return decision

    async def run(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Gate + dispatch one tool call."""
        fn = get_tool(name)
        if fn is None:
            return {"ok": False, "error": f"unknown tool '{name}'"}

        risk = _risk_of(name)
        if name == "run_capability":
            risk = _capability_risk(arguments)

        # run_command is destructive by default, but a call that only
        # reads state (cat / ls / grep / wc / sed -n / ...) is harmless;
        # treat it as safe so the user isn't asked to confirm every
        # `cat plugin.json`.
        if name == "run_command":
            from tools.command_tool import is_read_only_invocation
            if is_read_only_invocation(arguments):
                risk = "safe"

        # ----- permission gate -----

        if risk == "safe":
            pass  # read-only — no prompt

        elif risk == "side_effect":
            if name == "run_capability" and not bool(arguments.get("confirm", False)):
                pass
            elif name not in self._allow_all:
                decision = await self._request_permission(
                    name=name,
                    arguments=arguments,
                    risk=risk,
                    message=(
                        f"    ⚠ side-effect: {name}({arguments})  "
                        f"[y=允许 / n=拒绝 / a=本会话此工具全允许] > "
                    ),
                )
                if decision == "allow_all":
                    self._allow_all.add(name)
                elif decision != "allow":
                    result = {"ok": False, "denied": True,
                              "reason": f"user rejected side-effect call to {name}"}
                    await self._emit({"type": "tool_result", "name": name, "result": result})
                    return result

        elif risk == "destructive":
            confirm = bool(arguments.get("confirm", False))
            if confirm:
                # `a` from a previous turn pre-approves this tool, so we
                # don't pester the user mid-batch (e.g. uninstalling
                # several flatpaks in a row).
                if name not in self._allow_all:
                    decision = await self._request_permission(
                        name=name,
                        arguments=arguments,
                        risk=risk,
                        message=(
                            f"    🚨 DESTRUCTIVE: {name}({arguments})  "
                            f"[y=确认执行 / n=取消 / a=本会话此工具全允许] > "
                        ),
                    )
                    if decision == "allow_all":
                        self._allow_all.add(name)
                    elif decision != "allow":
                        result = {"ok": False, "denied": True,
                                  "reason": f"user rejected destructive call to {name}"}
                        await self._emit({"type": "tool_result", "name": name, "result": result})
                        return result
            # confirm=False is a dry-run — harmless, pass through silently.

        # ----- execute -----
        await self._emit({
            "type": "tool_start",
            "name": name,
            "arguments": arguments,
            "risk": risk,
        })
        try:
            result = await fn(**arguments)
        except TypeError as e:
            # Wrong/missing args — common LLM mistake. Report cleanly so
            # the planner can correct itself on the next turn.
            result = {"ok": False, "error": f"bad arguments for {name}: {e}"}
        except Exception as e:  # pragma: no cover — defensive
            result = {"ok": False, "error": f"{type(e).__name__}: {e}"}

        await self._emit({"type": "tool_result", "name": name, "result": result})
        return result
