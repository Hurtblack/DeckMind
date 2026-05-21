"""Bluetooth capabilities backed by bluetoothctl."""

from __future__ import annotations

import asyncio
import importlib
import re
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .types import Capability


BluetoothRunner = Callable[[list[str]], Awaitable["CommandResult"]]
_ADDRESS_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def _session_env() -> dict[str, str]:
    return importlib.import_module("runtime.session_env").session_env()


def is_valid_address(address: str) -> bool:
    return bool(_ADDRESS_RE.match(address.strip()))


def _normalize_address(address: str) -> str:
    return address.strip().upper()


def parse_devices_output(output: str) -> list[dict[str, str]]:
    devices: list[dict[str, str]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.startswith("Device "):
            continue
        parts = line.split(maxsplit=2)
        if len(parts) < 2 or not is_valid_address(parts[1]):
            continue
        devices.append({
            "address": _normalize_address(parts[1]),
            "name": parts[2] if len(parts) > 2 else parts[1],
        })
    return devices


def parse_info_output(address: str, output: str) -> dict[str, Any]:
    device: dict[str, Any] = {
        "address": _normalize_address(address),
        "name": _normalize_address(address),
        "paired": False,
        "trusted": False,
        "connected": False,
    }
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if ":" not in line:
            continue
        key, value = [part.strip() for part in line.split(":", 1)]
        lowered = value.lower()
        if key in {"Name", "Alias"} and value:
            device["name"] = value
        elif key == "Paired":
            device["paired"] = lowered == "yes"
        elif key == "Trusted":
            device["trusted"] = lowered == "yes"
        elif key == "Connected":
            device["connected"] = lowered == "yes"
    return device


async def _run_bluetoothctl(args: list[str]) -> CommandResult:
    if shutil.which("bluetoothctl") is None:
        return CommandResult(127, "", "bluetoothctl not found")
    proc = await asyncio.create_subprocess_exec(
        "bluetoothctl",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_session_env(),
    )
    out, err = await proc.communicate()
    return CommandResult(
        proc.returncode or 0,
        out.decode(errors="ignore"),
        err.decode(errors="ignore"),
    )


async def _info(address: str, runner: BluetoothRunner) -> dict[str, Any]:
    result = await runner(["info", address])
    if result.returncode != 0:
        return {
            "address": address,
            "name": address,
            "paired": False,
            "trusted": False,
            "connected": False,
            "error": (result.stderr or result.stdout).strip(),
        }
    return parse_info_output(address, result.stdout)


async def get_devices(runner: BluetoothRunner | None = None) -> dict[str, Any]:
    runner = runner or _run_bluetoothctl
    result = await runner(["devices"])
    if result.returncode != 0:
        return {
            "ok": False,
            "error": (result.stderr or result.stdout).strip() or "bluetoothctl devices failed",
        }

    base_devices = parse_devices_output(result.stdout)
    devices = [
        await _info(device["address"], runner)
        for device in base_devices
    ]
    for index, base in enumerate(base_devices):
        if devices[index].get("name") == devices[index].get("address"):
            devices[index]["name"] = base["name"]
    return {"ok": True, "devices": devices}


def _invalid_address_result(address: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": "invalid_bluetooth_address",
        "address": address,
    }


def _dry_run(name: str, address: str) -> dict[str, Any]:
    return {
        "ok": True,
        "dry_run": True,
        "capability": name,
        "target": {"address": _normalize_address(address)},
    }


async def connect(
    address: str,
    confirm: bool = False,
    runner: BluetoothRunner | None = None,
) -> dict[str, Any]:
    if not is_valid_address(address):
        return _invalid_address_result(address)
    address = _normalize_address(address)
    if not confirm:
        return _dry_run("bluetooth.connect", address)

    runner = runner or _run_bluetoothctl
    result = await runner(["connect", address])
    if result.returncode != 0:
        return {
            "ok": False,
            "error": (result.stderr or result.stdout).strip() or "bluetoothctl connect failed",
            "address": address,
        }

    device = await _info(address, runner)
    if not device.get("connected"):
        return {
            "ok": False,
            "error": "connect command succeeded but device is not connected",
            "device": device,
        }
    return {"ok": True, "device": device}


async def disconnect(
    address: str,
    confirm: bool = False,
    runner: BluetoothRunner | None = None,
) -> dict[str, Any]:
    if not is_valid_address(address):
        return _invalid_address_result(address)
    address = _normalize_address(address)
    if not confirm:
        return _dry_run("bluetooth.disconnect", address)

    runner = runner or _run_bluetoothctl
    result = await runner(["disconnect", address])
    if result.returncode != 0:
        return {
            "ok": False,
            "error": (result.stderr or result.stdout).strip() or "bluetoothctl disconnect failed",
            "address": address,
        }

    device = await _info(address, runner)
    if device.get("connected"):
        return {
            "ok": False,
            "error": "disconnect command succeeded but device is still connected",
            "device": device,
        }
    return {"ok": True, "device": device}


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
