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

from . import macro_tool, package_tool, steam_tool, system_tool, update_tool


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
