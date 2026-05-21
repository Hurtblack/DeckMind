"""Audio capabilities backed by existing system tools."""

from __future__ import annotations

from typing import Any

from tools import system_tool

from .types import Capability


async def get_volume() -> dict[str, Any]:
    return await system_tool.get_volume()


async def set_volume(percent: int) -> dict[str, Any]:
    return await system_tool.set_volume(percent)


def capabilities() -> list[Capability]:
    return [
        Capability(
            name="audio.get_volume",
            description="Read current audio output volume as a percent.",
            args_schema={"type": "object", "properties": {}},
            risk="safe",
            confirm_required=False,
            handler=get_volume,
        ),
        Capability(
            name="audio.set_volume",
            description="Set audio output volume percentage.",
            args_schema={
                "type": "object",
                "properties": {
                    "percent": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 100,
                    },
                },
                "required": ["percent"],
            },
            risk="side_effect",
            confirm_required=False,
            handler=set_volume,
        ),
    ]
