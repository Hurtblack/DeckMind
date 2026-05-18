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

from . import macro_tool, steam_tool, system_tool


# Every tool is an async callable returning a dict.
ToolFn = Callable[..., Awaitable[dict[str, Any]]]


async def _final_answer(message: str) -> dict[str, Any]:
    """Sentinel tool — the LLM calls this to end the loop."""
    return {"ok": True, "final": True, "message": message}


# name -> (callable, neutral spec)
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
    "final_answer": (
        _final_answer,
        ToolSpec(
            name="final_answer",
            description="Finish the current turn. `message` is shown to the user.",
            parameters={
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
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
