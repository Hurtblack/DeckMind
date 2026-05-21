"""Steam capabilities backed by existing Steam tools."""

from __future__ import annotations

from typing import Any

from tools import steam_tool

from .types import Capability


async def launch_game(game_name: str) -> dict[str, Any]:
    return await steam_tool.launch_game(game_name)


async def close_game(process_name: str) -> dict[str, Any]:
    return await steam_tool.close_game(process_name)


def capabilities() -> list[Capability]:
    return [
        Capability(
            name="steam.launch_game",
            description="Launch a Steam game by friendly name.",
            args_schema={
                "type": "object",
                "properties": {"game_name": {"type": "string"}},
                "required": ["game_name"],
            },
            risk="side_effect",
            confirm_required=False,
            handler=launch_game,
        ),
        Capability(
            name="steam.close_game",
            description="Close a running game process by process name.",
            args_schema={
                "type": "object",
                "properties": {"process_name": {"type": "string"}},
                "required": ["process_name"],
            },
            risk="side_effect",
            confirm_required=False,
            handler=close_game,
        ),
    ]
