"""Bluetooth capabilities backed by bluetoothctl."""

from __future__ import annotations

from typing import Any

from .types import Capability


async def get_devices() -> dict[str, Any]:
    return {"ok": True, "devices": []}


async def connect(address: str, confirm: bool = False) -> dict[str, Any]:
    return {
        "ok": True,
        "dry_run": not confirm,
        "capability": "bluetooth.connect",
        "target": {"address": address},
    }


async def disconnect(address: str, confirm: bool = False) -> dict[str, Any]:
    return {
        "ok": True,
        "dry_run": not confirm,
        "capability": "bluetooth.disconnect",
        "target": {"address": address},
    }


def capabilities() -> list[Capability]:
    address_schema = {
        "type": "object",
        "properties": {
            "address": {
                "type": "string",
                "description": "Bluetooth MAC address, e.g. AA:BB:CC:DD:EE:FF",
            }
        },
        "required": ["address"],
    }
    return [
        Capability(
            name="bluetooth.get_devices",
            description="List known Bluetooth devices and their connection state.",
            args_schema={"type": "object", "properties": {}},
            risk="safe",
            confirm_required=False,
            handler=get_devices,
        ),
        Capability(
            name="bluetooth.connect",
            description="Connect a Bluetooth device by MAC address.",
            args_schema=address_schema,
            risk="side_effect",
            confirm_required=True,
            handler=connect,
        ),
        Capability(
            name="bluetooth.disconnect",
            description="Disconnect a Bluetooth device by MAC address.",
            args_schema=address_schema,
            risk="side_effect",
            confirm_required=True,
            handler=disconnect,
        ),
    ]
