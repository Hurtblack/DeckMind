"""Audio capabilities backed by existing system tools."""

from __future__ import annotations

from typing import Any

from tools import system_tool

from .types import Capability


async def get_volume() -> dict[str, Any]:
    return await system_tool.get_volume()


async def set_volume(percent: int) -> dict[str, Any]:
    return await system_tool.set_volume(percent)


async def get_output_devices() -> dict[str, Any]:
    return await system_tool.list_outputs()


async def set_output_device(device: str) -> dict[str, Any]:
    return await system_tool.set_output_device(device)


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
        Capability(
            name="audio.get_output_devices",
            description=(
                "List audio output devices (sinks) and which one is the "
                "current default."
            ),
            args_schema={"type": "object", "properties": {}},
            risk="safe",
            confirm_required=False,
            handler=get_output_devices,
        ),
        Capability(
            name="audio.set_output_device",
            description=(
                "Switch the default audio output device and move currently "
                "playing audio onto it. Accepts a sink name from "
                "audio.get_output_devices, or a unique substring of its name "
                "or description (e.g. a Bluetooth headset name)."
            ),
            args_schema={
                "type": "object",
                "properties": {
                    "device": {
                        "type": "string",
                        "description": (
                            "Sink name, or a unique substring of its name or "
                            "description."
                        ),
                    },
                },
                "required": ["device"],
            },
            risk="side_effect",
            confirm_required=False,
            handler=set_output_device,
        ),
    ]
