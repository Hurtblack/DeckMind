"""Tool registry.

Each entry maps a tool name (string the LLM will emit) to:
  - the coroutine that implements it
  - a neutral ToolSpec describing its arguments

The LLM client translates ToolSpec into whatever shape its API expects
(OpenAI Responses, Chat Completions, etc.). Tool code is provider-agnostic.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from llm import ToolSpec

from . import (
    macro_tool, notion_tool, package_tool, profile_tool,
    steam_tool, system_tool, update_tool,
)


# Every tool is an async callable returning a dict.
ToolFn = Callable[..., Awaitable[dict[str, Any]]]


# name -> (callable, neutral spec)
# Note: the LLM ends a turn by simply producing natural-language text
# (which is streamed to the user). There is no `final_answer` tool.
TOOLS: dict[str, tuple[ToolFn, ToolSpec]] = {
    "launch_game": (
        steam_tool.launch_game,
        ToolSpec(
            name="launch_game",
            description="Launch a Steam game by friendly name (e.g. 'cs2').",
            parameters={
                "type": "object",
                "properties": {"game_name": {"type": "string"}},
                "required": ["game_name"],
            },
        ),
    ),
    "close_game": (
        steam_tool.close_game,
        ToolSpec(
            name="close_game",
            description="Kill a running game process by name (uses pkill -f).",
            parameters={
                "type": "object",
                "properties": {"process_name": {"type": "string"}},
                "required": ["process_name"],
            },
        ),
    ),
    "list_running_games": (
        steam_tool.list_running_games,
        ToolSpec(
            name="list_running_games",
            description="List currently running known games.",
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "install_game": (
        steam_tool.install_game,
        ToolSpec(
            name="install_game",
            description=(
                "Open Steam's install dialog for a known game. DESTRUCTIVE — "
                "call first with confirm=false for a dry-run preview, then "
                "again with confirm=true after the user explicitly approves."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "game_name": {"type": "string"},
                    "confirm": {"type": "boolean", "default": False},
                },
                "required": ["game_name"],
            },
        ),
    ),
    "uninstall_game": (
        steam_tool.uninstall_game,
        ToolSpec(
            name="uninstall_game",
            description=(
                "Open Steam's uninstall dialog for a known game. DESTRUCTIVE — "
                "call first with confirm=false for a dry-run preview, then "
                "again with confirm=true after the user explicitly approves."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "game_name": {"type": "string"},
                    "confirm": {"type": "boolean", "default": False},
                },
                "required": ["game_name"],
            },
        ),
    ),
    "list_flatpak_apps": (
        package_tool.list_flatpak_apps,
        ToolSpec(
            name="list_flatpak_apps",
            description="List every installed Flatpak app with its on-disk size.",
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "search_flatpak": (
        package_tool.search_flatpak,
        ToolSpec(
            name="search_flatpak",
            description="Search Flathub for apps matching a keyword (e.g. 'dolphin', 'nes emulator').",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
    ),
    "install_flatpak": (
        package_tool.install_flatpak,
        ToolSpec(
            name="install_flatpak",
            description=(
                "Install a Flatpak app from Flathub by its app_id "
                "(e.g. 'org.DolphinEmu.dolphin-emu'). DESTRUCTIVE — call "
                "first with confirm=false for dry-run, then with confirm=true "
                "after the user explicitly approves."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "app_id": {"type": "string"},
                    "confirm": {"type": "boolean", "default": False},
                },
                "required": ["app_id"],
            },
        ),
    ),
    "uninstall_flatpak": (
        package_tool.uninstall_flatpak,
        ToolSpec(
            name="uninstall_flatpak",
            description=(
                "Uninstall a Flatpak app by its app_id. DESTRUCTIVE — call "
                "first with confirm=false for dry-run (returns current size), "
                "then with confirm=true after the user explicitly approves."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "app_id": {"type": "string"},
                    "confirm": {"type": "boolean", "default": False},
                },
                "required": ["app_id"],
            },
        ),
    ),
    "disk_usage": (
        package_tool.disk_usage,
        ToolSpec(
            name="disk_usage",
            description="Show human-readable disk usage for / and /home.",
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "remember": (
        profile_tool.remember,
        ToolSpec(
            name="remember",
            description=(
                "Save a fact about the user that should persist across "
                "sessions (name, preferences, schedule, gaming style, etc.). "
                "Use a short snake_case key. Overwrites any prior value at "
                "the same key. Examples: "
                "remember('name','赖天宇'); "
                "remember('favorite_genre','soulslike'); "
                "remember('play_window','weekends 1-2h')."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["key", "value"],
            },
        ),
    ),
    "forget": (
        profile_tool.forget,
        ToolSpec(
            name="forget",
            description="Remove a previously saved fact by key.",
            parameters={
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
            },
        ),
    ),
    "list_profile": (
        profile_tool.list_profile,
        ToolSpec(
            name="list_profile",
            description=(
                "Return every fact currently stored about the user. "
                "Usually you don't need to call this — the profile is "
                "already injected into your system prompt at startup. "
                "Use it only when the user asks 'what do you know about me?' "
                "and you want to confirm against the latest on-disk state."
            ),
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "notion_status": (
        notion_tool.notion_status,
        ToolSpec(
            name="notion_status",
            description=(
                "Show Notion connection status. If only NOTION_API_KEY is "
                "set, this also auto-discovers the database: silently picks "
                "the only accessible one, or returns the list with "
                "`needs_user_choice: true` if there are multiple. Call this "
                "first whenever the user wants to 'connect Notion' / '绑定 "
                "notion' / '看看 notion 状态'."
            ),
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "notion_databases": (
        notion_tool.notion_databases,
        ToolSpec(
            name="notion_databases",
            description=(
                "List every Notion database the integration can access. "
                "Read-only. Useful when the user has multiple databases "
                "shared with DeckMind and wants to switch which one is "
                "active."
            ),
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "notion_set_default_database": (
        notion_tool.notion_set_default_database,
        ToolSpec(
            name="notion_set_default_database",
            description=(
                "Persist a Notion database ID as the active default "
                "(saved to ~/.deckmind/notion.json). Use this after "
                "notion_status returns `needs_user_choice: true`, or when "
                "the user asks to switch to a different shared database."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "database_id": {"type": "string",
                                    "description": "The 32-char hex ID of the database"},
                },
                "required": ["database_id"],
            },
        ),
    ),
    "notion_log_session": (
        notion_tool.notion_log_session,
        ToolSpec(
            name="notion_log_session",
            description=(
                "Append one play-session row to the Notion database. "
                "Use when the user reports having played something "
                "(e.g. '记一笔我刚玩了 1 小时 CS2'). `minutes` is integer "
                "minutes. `date` defaults to today (YYYY-MM-DD). `notes` "
                "is optional free-text."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "game": {"type": "string"},
                    "minutes": {"type": "integer", "minimum": 1},
                    "notes": {"type": "string"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": ["game", "minutes"],
            },
        ),
    ),
    "notion_recent": (
        notion_tool.notion_recent,
        ToolSpec(
            name="notion_recent",
            description="Return the N most-recently-logged play sessions.",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
                },
            },
        ),
    ),
    "notion_total": (
        notion_tool.notion_total,
        ToolSpec(
            name="notion_total",
            description=(
                "Sum playtime over the last `days` days, with a top-5 "
                "per-game breakdown. Use for '本周玩了多少' / "
                "'这个月谁玩得最多' / weekly summary."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "minimum": 1, "maximum": 365,
                             "description": "Look back this many days (7=week, 30=month)"},
                },
            },
        ),
    ),
    "check_for_updates": (
        update_tool.check_for_updates,
        ToolSpec(
            name="check_for_updates",
            description=(
                "Fetch from the project's git origin and report whether "
                "a newer commit is available. Read-only, safe."
            ),
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "apply_update": (
        update_tool.apply_update,
        ToolSpec(
            name="apply_update",
            description=(
                "Pull the latest code from origin (fast-forward only) and "
                "run `uv sync`. DESTRUCTIVE — call first with confirm=false "
                "for a dry-run preview, then with confirm=true after the "
                "user explicitly approves. Refuses if there are uncommitted "
                "local changes. The new code only takes effect after the "
                "user restarts the agent."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "confirm": {"type": "boolean", "default": False},
                },
            },
        ),
    ),
    "get_battery": (
        system_tool.get_battery,
        ToolSpec(
            name="get_battery",
            description="Read battery percentage and charging status.",
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "get_volume": (
        system_tool.get_volume,
        ToolSpec(
            name="get_volume",
            description="Read current audio output volume as a percent (0-100).",
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "set_volume": (
        system_tool.set_volume,
        ToolSpec(
            name="set_volume",
            description="Set audio output volume. `percent` is 0-100.",
            parameters={
                "type": "object",
                "properties": {"percent": {"type": "integer", "minimum": 0, "maximum": 100}},
                "required": ["percent"],
            },
        ),
    ),
    "press_key": (
        macro_tool.press_key,
        ToolSpec(
            name="press_key",
            description="Press and release a single key once (e.g. 'space', 'a', 'enter').",
            parameters={
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
            },
        ),
    ),
    "start_key_loop": (
        macro_tool.start_key_loop,
        ToolSpec(
            name="start_key_loop",
            description="Start a background loop that presses `key` every `interval_seconds`.",
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "interval_seconds": {"type": "number", "minimum": 0.05},
                },
                "required": ["key", "interval_seconds"],
            },
        ),
    ),
    "stop_all_macros": (
        macro_tool.stop_all_macros,
        ToolSpec(
            name="stop_all_macros",
            description="Cancel every running key-loop macro.",
            parameters={"type": "object", "properties": {}},
        ),
    ),
}


def specs() -> list[ToolSpec]:
    """Return all tool specs for the planner to advertise to the LLM."""
    return [spec for _, spec in TOOLS.values()]


def get(name: str) -> ToolFn | None:
    """Look up the implementation for a tool name. None if unknown."""
    entry = TOOLS.get(name)
    return entry[0] if entry else None
