# Capability Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal Capability Registry and validate it with bluetoothctl-backed Bluetooth capabilities.

**Architecture:** Introduce `runtime.capabilities` as a small registry layer with typed capability metadata and built-in Bluetooth handlers. Expose the layer through `tools.capability_tool` via `list_capabilities` and `run_capability`, then register those tools in the existing tool registry and Executor risk model.

**Tech Stack:** Python 3.11+, standard library `asyncio` / `dataclasses` / `re` / `shutil` / `unittest`, existing `ToolSpec` and Executor permission flow.

---

## File Structure

- Create: `runtime/capabilities/__init__.py`
  - Imports the built-in registry so callers can access `list_capabilities`, `get_capability`, and `register_capability`.
- Create: `runtime/capabilities/types.py`
  - Defines `CapabilityRisk`, `CapabilityHandler`, and `Capability`.
- Create: `runtime/capabilities/registry.py`
  - Owns the in-process registry, duplicate-name validation, public metadata serialization, and built-in Bluetooth registration.
- Create: `runtime/capabilities/bluetooth.py`
  - Implements bluetoothctl command runner, parsers, MAC validation, and handlers.
- Create: `tools/capability_tool.py`
  - Exposes `list_capabilities()` and `run_capability(name, args=None, confirm=False)` for the Agent.
- Create: `tests/test_capability_registry.py`
  - Covers registry metadata, duplicate rejection, unknown capability behavior, and dry-run behavior.
- Create: `tests/test_bluetooth_capability.py`
  - Covers bluetoothctl parsing, MAC validation, dry-run, connect verification, and disconnect verification without Bluetooth hardware.
- Modify: `tools/__init__.py`
  - Imports `capability_tool` and registers `list_capabilities` / `run_capability`.
- Modify: `runtime/executor.py`
  - Adds `list_capabilities` to `RISK_SAFE` and `run_capability` to `RISK_DESTRUCTIVE`.
- Modify: `prompts/system_prompt.txt`
  - Teaches the model to use capabilities, distinguish skills from capabilities, and avoid shell fallback for unknown capabilities.

## Task 1: Registry Types And Metadata Tests

**Files:**
- Create: `tests/test_capability_registry.py`
- Create later in Task 2: `runtime/capabilities/types.py`
- Create later in Task 2: `runtime/capabilities/registry.py`

- [ ] **Step 1: Write the failing registry tests**

Create `tests/test_capability_registry.py`:

```python
from __future__ import annotations

import unittest
from typing import Any

from runtime.capabilities.registry import (
    CapabilityRegistry,
    get_capability,
    list_capabilities,
)
from runtime.capabilities.types import Capability


async def fake_handler(**kwargs: Any) -> dict[str, Any]:
    return {"ok": True, "args": kwargs}


class CapabilityRegistryTests(unittest.TestCase):
    def test_builtin_bluetooth_capabilities_are_listed(self) -> None:
        names = {item["name"] for item in list_capabilities()}

        self.assertIn("bluetooth.get_devices", names)
        self.assertIn("bluetooth.connect", names)
        self.assertIn("bluetooth.disconnect", names)

    def test_public_metadata_omits_handler(self) -> None:
        capability = get_capability("bluetooth.connect")

        self.assertIsNotNone(capability)
        assert capability is not None
        public = capability.to_public_dict()

        self.assertEqual(public["name"], "bluetooth.connect")
        self.assertEqual(public["risk"], "side_effect")
        self.assertTrue(public["confirm_required"])
        self.assertNotIn("handler", public)

    def test_registry_rejects_duplicate_names(self) -> None:
        registry = CapabilityRegistry()
        capability = Capability(
            name="demo.echo",
            description="Echo demo",
            args_schema={"type": "object", "properties": {}},
            risk="safe",
            confirm_required=False,
            handler=fake_handler,
        )

        registry.register(capability)

        with self.assertRaises(ValueError):
            registry.register(capability)

    def test_registry_get_unknown_returns_none(self) -> None:
        registry = CapabilityRegistry()

        self.assertIsNone(registry.get("missing.capability"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m unittest tests.test_capability_registry -v
```

Expected: FAIL with `ModuleNotFoundError` for `runtime.capabilities`.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_capability_registry.py
git commit -m "添加能力注册表测试"
```

## Task 2: Capability Types And Registry

**Files:**
- Create: `runtime/capabilities/__init__.py`
- Create: `runtime/capabilities/types.py`
- Create: `runtime/capabilities/registry.py`
- Create temporary stub during this task: `runtime/capabilities/bluetooth.py`

- [ ] **Step 1: Create capability types**

Create `runtime/capabilities/types.py`:

```python
"""Shared types for DeckMind capabilities."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal


CapabilityRisk = Literal["safe", "side_effect", "destructive"]
CapabilityHandler = Callable[..., Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    args_schema: dict[str, Any]
    risk: CapabilityRisk
    confirm_required: bool
    handler: CapabilityHandler

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "args_schema": self.args_schema,
            "risk": self.risk,
            "confirm_required": self.confirm_required,
        }
```

- [ ] **Step 2: Create temporary Bluetooth registrations**

Create `runtime/capabilities/bluetooth.py` with temporary handlers that Task 4 will replace:

```python
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
```

- [ ] **Step 3: Create registry**

Create `runtime/capabilities/registry.py`:

```python
"""Capability registry for DeckMind runtime actions."""

from __future__ import annotations

from . import bluetooth
from .types import Capability


class CapabilityRegistry:
    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        if capability.name in self._capabilities:
            raise ValueError(f"duplicate capability: {capability.name}")
        self._capabilities[capability.name] = capability

    def get(self, name: str) -> Capability | None:
        return self._capabilities.get(name)

    def list(self) -> list[dict[str, object]]:
        return [
            capability.to_public_dict()
            for capability in sorted(
                self._capabilities.values(),
                key=lambda item: item.name,
            )
        ]


_REGISTRY = CapabilityRegistry()

for capability in bluetooth.capabilities():
    _REGISTRY.register(capability)


def register_capability(capability: Capability) -> None:
    _REGISTRY.register(capability)


def get_capability(name: str) -> Capability | None:
    return _REGISTRY.get(name)


def list_capabilities() -> list[dict[str, object]]:
    return _REGISTRY.list()
```

- [ ] **Step 4: Create package exports**

Create `runtime/capabilities/__init__.py`:

```python
"""Runtime capability registry."""

from .registry import get_capability, list_capabilities, register_capability
from .types import Capability, CapabilityRisk

__all__ = [
    "Capability",
    "CapabilityRisk",
    "get_capability",
    "list_capabilities",
    "register_capability",
]
```

- [ ] **Step 5: Run registry tests**

Run:

```bash
python -m unittest tests.test_capability_registry -v
```

Expected: PASS.

- [ ] **Step 6: Commit implementation**

```bash
git add runtime/capabilities tests/test_capability_registry.py
git commit -m "实现能力注册表骨架"
```

## Task 3: Bluetooth Parser And Handler Tests

**Files:**
- Create: `tests/test_bluetooth_capability.py`
- Modify later in Task 4: `runtime/capabilities/bluetooth.py`

- [ ] **Step 1: Write Bluetooth tests**

Create `tests/test_bluetooth_capability.py`:

```python
from __future__ import annotations

import unittest

from runtime.capabilities import bluetooth
from runtime.capabilities.bluetooth import CommandResult


DEVICES_OUTPUT = """\
Device AA:BB:CC:DD:EE:FF Xbox Wireless Controller
Device 11:22:33:44:55:66 Pixel Buds Pro
"""

INFO_CONNECTED = """\
Device AA:BB:CC:DD:EE:FF (public)
        Name: Xbox Wireless Controller
        Alias: Xbox Wireless Controller
        Paired: yes
        Trusted: yes
        Connected: yes
"""

INFO_DISCONNECTED = """\
Device AA:BB:CC:DD:EE:FF (public)
        Name: Xbox Wireless Controller
        Alias: Xbox Wireless Controller
        Paired: yes
        Trusted: yes
        Connected: no
"""


class BluetoothParserTests(unittest.TestCase):
    def test_parse_devices_output(self) -> None:
        devices = bluetooth.parse_devices_output(DEVICES_OUTPUT)

        self.assertEqual(devices, [
            {"address": "AA:BB:CC:DD:EE:FF", "name": "Xbox Wireless Controller"},
            {"address": "11:22:33:44:55:66", "name": "Pixel Buds Pro"},
        ])

    def test_parse_info_output(self) -> None:
        info = bluetooth.parse_info_output("AA:BB:CC:DD:EE:FF", INFO_CONNECTED)

        self.assertEqual(info["address"], "AA:BB:CC:DD:EE:FF")
        self.assertEqual(info["name"], "Xbox Wireless Controller")
        self.assertTrue(info["paired"])
        self.assertTrue(info["trusted"])
        self.assertTrue(info["connected"])

    def test_invalid_mac_is_rejected(self) -> None:
        self.assertFalse(bluetooth.is_valid_address("not-a-mac"))
        self.assertTrue(bluetooth.is_valid_address("AA:BB:CC:DD:EE:FF"))


class BluetoothHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_devices_queries_info_for_each_device(self) -> None:
        calls: list[list[str]] = []

        async def runner(args: list[str]) -> CommandResult:
            calls.append(args)
            if args == ["devices"]:
                return CommandResult(0, DEVICES_OUTPUT, "")
            if args == ["info", "AA:BB:CC:DD:EE:FF"]:
                return CommandResult(0, INFO_CONNECTED, "")
            if args == ["info", "11:22:33:44:55:66"]:
                return CommandResult(
                    0,
                    INFO_DISCONNECTED.replace("AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66").replace(
                        "Xbox Wireless Controller",
                        "Pixel Buds Pro",
                    ),
                    "",
                )
            raise AssertionError(f"unexpected call: {args}")

        result = await bluetooth.get_devices(runner=runner)

        self.assertTrue(result["ok"])
        self.assertEqual(calls, [
            ["devices"],
            ["info", "AA:BB:CC:DD:EE:FF"],
            ["info", "11:22:33:44:55:66"],
        ])
        self.assertEqual(len(result["devices"]), 2)
        self.assertTrue(result["devices"][0]["connected"])
        self.assertFalse(result["devices"][1]["connected"])

    async def test_connect_dry_run_does_not_call_runner(self) -> None:
        calls: list[list[str]] = []

        async def runner(args: list[str]) -> CommandResult:
            calls.append(args)
            return CommandResult(0, "", "")

        result = await bluetooth.connect(
            address="AA:BB:CC:DD:EE:FF",
            confirm=False,
            runner=runner,
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(calls, [])

    async def test_connect_executes_and_verifies_connected_state(self) -> None:
        calls: list[list[str]] = []

        async def runner(args: list[str]) -> CommandResult:
            calls.append(args)
            if args == ["connect", "AA:BB:CC:DD:EE:FF"]:
                return CommandResult(0, "Connection successful", "")
            if args == ["info", "AA:BB:CC:DD:EE:FF"]:
                return CommandResult(0, INFO_CONNECTED, "")
            raise AssertionError(f"unexpected call: {args}")

        result = await bluetooth.connect(
            address="AA:BB:CC:DD:EE:FF",
            confirm=True,
            runner=runner,
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result.get("dry_run", False))
        self.assertTrue(result["device"]["connected"])
        self.assertEqual(calls, [
            ["connect", "AA:BB:CC:DD:EE:FF"],
            ["info", "AA:BB:CC:DD:EE:FF"],
        ])

    async def test_disconnect_executes_and_verifies_disconnected_state(self) -> None:
        async def runner(args: list[str]) -> CommandResult:
            if args == ["disconnect", "AA:BB:CC:DD:EE:FF"]:
                return CommandResult(0, "Successful disconnected", "")
            if args == ["info", "AA:BB:CC:DD:EE:FF"]:
                return CommandResult(0, INFO_DISCONNECTED, "")
            raise AssertionError(f"unexpected call: {args}")

        result = await bluetooth.disconnect(
            address="AA:BB:CC:DD:EE:FF",
            confirm=True,
            runner=runner,
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["device"]["connected"])

    async def test_bluetoothctl_failure_is_reported(self) -> None:
        async def runner(args: list[str]) -> CommandResult:
            return CommandResult(1, "", "Device not available")

        result = await bluetooth.connect(
            address="AA:BB:CC:DD:EE:FF",
            confirm=True,
            runner=runner,
        )

        self.assertFalse(result["ok"])
        self.assertIn("Device not available", result["error"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m unittest tests.test_bluetooth_capability -v
```

Expected: FAIL with missing `CommandResult`, `parse_devices_output`, `parse_info_output`, or `is_valid_address`.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_bluetooth_capability.py
git commit -m "添加蓝牙能力测试"
```

## Task 4: Bluetooth Capability Implementation

**Files:**
- Modify: `runtime/capabilities/bluetooth.py`

- [ ] **Step 1: Replace Bluetooth stub with real implementation**

Replace `runtime/capabilities/bluetooth.py` with:

```python
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
```

- [ ] **Step 2: Run Bluetooth tests**

Run:

```bash
python -m unittest tests.test_bluetooth_capability -v
```

Expected: PASS.

- [ ] **Step 3: Run registry tests**

Run:

```bash
python -m unittest tests.test_capability_registry -v
```

Expected: PASS.

- [ ] **Step 4: Commit Bluetooth implementation**

```bash
git add runtime/capabilities/bluetooth.py tests/test_bluetooth_capability.py
git commit -m "实现蓝牙 capability"
```

## Task 5: Capability Tool Tests And Implementation

**Files:**
- Create: `tools/capability_tool.py`
- Modify: `tests/test_capability_registry.py`

- [ ] **Step 1: Add tool-level tests**

Append these tests to `tests/test_capability_registry.py` before the `if __name__ == "__main__"` block:

```python
class CapabilityToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_capabilities_tool_returns_public_metadata(self) -> None:
        from tools.capability_tool import list_capabilities as list_tool

        result = await list_tool()

        self.assertTrue(result["ok"])
        names = {item["name"] for item in result["capabilities"]}
        self.assertIn("bluetooth.get_devices", names)

    async def test_run_capability_unknown_returns_structured_error(self) -> None:
        from tools.capability_tool import run_capability

        result = await run_capability("wifi.switch_network")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unknown_capability")
        self.assertEqual(result["capability"], "wifi.switch_network")
        self.assertIn("list_capabilities", result["suggestions"])

    async def test_run_side_effect_capability_without_confirm_returns_dry_run(self) -> None:
        from tools.capability_tool import run_capability

        result = await run_capability(
            "bluetooth.connect",
            {"address": "AA:BB:CC:DD:EE:FF"},
            confirm=False,
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["capability"], "bluetooth.connect")

    async def test_run_safe_capability_executes_without_confirm(self) -> None:
        from unittest.mock import patch
        from runtime.capabilities.bluetooth import CommandResult
        from tools.capability_tool import run_capability

        async def runner(args: list[str]) -> CommandResult:
            if args == ["devices"]:
                return CommandResult(0, "", "")
            raise AssertionError(f"unexpected call: {args}")

        with patch("runtime.capabilities.bluetooth._run_bluetoothctl", runner):
            result = await run_capability("bluetooth.get_devices")

        self.assertTrue(result["ok"])
        self.assertEqual(result["devices"], [])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m unittest tests.test_capability_registry -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tools.capability_tool'`.

- [ ] **Step 3: Create capability tool**

Create `tools/capability_tool.py`:

```python
"""Agent-facing tools for runtime capabilities."""

from __future__ import annotations

import inspect
from typing import Any

from runtime.capabilities.registry import get_capability
from runtime.capabilities.registry import list_capabilities as registry_list_capabilities


async def list_capabilities() -> dict[str, Any]:
    return {
        "ok": True,
        "capabilities": registry_list_capabilities(),
    }


async def run_capability(
    name: str,
    args: dict[str, Any] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    capability = get_capability(name)
    if capability is None:
        return {
            "ok": False,
            "error": "unknown_capability",
            "capability": name,
            "suggestions": ["list_capabilities"],
        }

    arguments = dict(args or {})
    if capability.risk != "safe" and not confirm:
        return {
            "ok": True,
            "dry_run": True,
            "capability": capability.name,
            "description": capability.description,
            "risk": capability.risk,
            "confirm_required": capability.confirm_required,
            "args": arguments,
        }

    signature = inspect.signature(capability.handler)
    if "confirm" in signature.parameters:
        arguments["confirm"] = confirm
    return await capability.handler(**arguments)
```

- [ ] **Step 4: Run capability tool tests**

Run:

```bash
python -m unittest tests.test_capability_registry -v
```

Expected: PASS.

- [ ] **Step 5: Commit tool implementation**

```bash
git add tools/capability_tool.py tests/test_capability_registry.py
git commit -m "添加 capability 工具入口"
```

## Task 6: Register Tools, Permissions, And Prompt

**Files:**
- Modify: `tools/__init__.py`
- Modify: `runtime/executor.py`
- Modify: `prompts/system_prompt.txt`

- [ ] **Step 1: Import capability tool**

Modify the import tuple in `tools/__init__.py` to include `capability_tool`:

```python
from . import (
    capability_tool, command_tool, decky_plugin_tool, file_tool, file_write_tool,
    macro_tool, notion_tool, package_tool, pacman_tool, profile_tool, steam_tool,
    steamos_lock as steamos_lock_tool, system_tool, update_tool,
)
```

- [ ] **Step 2: Register list_capabilities and run_capability**

Add these entries near the system tools in `TOOLS`:

```python
    "list_capabilities": (
        capability_tool.list_capabilities,
        ToolSpec(
            name="list_capabilities",
            description=(
                "List registered DeckMind capabilities with descriptions, "
                "argument schemas, risk levels, and confirmation requirements."
            ),
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "run_capability": (
        capability_tool.run_capability,
        ToolSpec(
            name="run_capability",
            description=(
                "Run a registered DeckMind capability by name. For non-safe "
                "capabilities, call first with confirm=false for preview, then "
                "again with confirm=true after the user approves. Unknown "
                "capabilities return unknown_capability and must not be replaced "
                "with shell commands."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "args": {
                        "type": "object",
                        "description": "Capability arguments matching its args_schema.",
                    },
                    "confirm": {"type": "boolean", "default": False},
                },
                "required": ["name"],
            },
        ),
    ),
```

- [ ] **Step 3: Update Executor risk sets**

In `runtime/executor.py`, add `list_capabilities` to `RISK_SAFE` and `run_capability` to `RISK_DESTRUCTIVE`:

```python
RISK_SAFE: set[str] = {
    "get_battery",
    "get_volume",
    "list_capabilities",
    ...
}
```

```python
RISK_DESTRUCTIVE: set[str] = {
    "install_game",
    ...
    "run_capability",
}
```

- [ ] **Step 4: Update system prompt**

In `prompts/system_prompt.txt`, add a new category after `System:`:

```text
- Capabilities:
            list_capabilities, run_capability
            (Capabilities are controlled system actions registered with
             metadata: name, description, args_schema, risk, and
             confirm_required. Prefer run_capability for registered
             system actions instead of inventing shell commands. For
             non-safe capabilities, call run_capability with
             confirm=false first, explain the preview, then call again
             with confirm=true after approval. If run_capability returns
             unknown_capability, explain that DeckMind does not yet have
             that ability and suggest designing a new capability. Do not
             fall back to run_command or ad-hoc shell to replace a missing
             capability. Skills are workflow knowledge; capabilities are
             executable actions.)
```

Also update the available tool categories line so Bluetooth requests route to capabilities:

```text
            For Bluetooth device listing, connecting, or disconnecting,
            use run_capability with bluetooth.get_devices,
            bluetooth.connect, or bluetooth.disconnect.
```

- [ ] **Step 5: Add registration tests to runtime interface tests**

Append to `tests/test_runtime_interfaces.py`:

```python
class CapabilityExecutorRiskTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_capabilities_is_safe(self) -> None:
        provider = RecordingPermissionProvider("deny")
        executor = Executor(permission_provider=provider)

        result = await executor.run("list_capabilities", {})

        self.assertTrue(result["ok"])
        self.assertEqual(provider.requests, [])

    async def test_run_capability_confirm_true_requests_permission(self) -> None:
        provider = RecordingPermissionProvider("allow")
        executor = Executor(permission_provider=provider)

        result = await executor.run(
            "run_capability",
            {
                "name": "bluetooth.connect",
                "args": {"address": "AA:BB:CC:DD:EE:FF"},
                "confirm": False,
            },
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(provider.requests, [])
```

This test intentionally uses `confirm=false`; it verifies the destructive tool preview path does not ask permission. Real `confirm=true` Bluetooth execution depends on the local Bluetooth stack and stays covered by handler unit tests.

- [ ] **Step 6: Run focused tests**

Run:

```bash
python -m unittest tests.test_capability_registry tests.test_bluetooth_capability tests.test_runtime_interfaces -v
```

Expected: PASS.

- [ ] **Step 7: Commit integration**

```bash
git add tools/__init__.py runtime/executor.py prompts/system_prompt.txt tests/test_runtime_interfaces.py
git commit -m "接入 capability 工具"
```

## Task 7: Final Verification

**Files:**
- No new files.

- [ ] **Step 1: Run all unit tests**

Run:

```bash
python -m unittest discover -v
```

Expected: PASS.

- [ ] **Step 2: Inspect git status**

Run:

```bash
git status --short
```

Expected: no uncommitted changes.

- [ ] **Step 3: Manual Steam Deck verification**

On a Steam Deck with Bluetooth enabled, run the agent and ask:

```text
列出蓝牙设备
```

Expected: Agent uses `run_capability` / `bluetooth.get_devices` and reports known devices.

Then ask:

```text
连接 AA:BB:CC:DD:EE:FF 这个蓝牙设备
```

Expected: Agent previews `bluetooth.connect`, Decky/terminal permission flow asks for confirmation, and after approval the result reports the device connected or a clear bluetoothctl error.

Then ask:

```text
断开 AA:BB:CC:DD:EE:FF
```

Expected: Agent previews `bluetooth.disconnect`, permission flow asks for confirmation, and after approval the result reports disconnected or a clear bluetoothctl error.

- [ ] **Step 4: Document manual result if tested**

If manual Deck verification was run, add a short note to the final response with:

```text
Manual Deck verification:
- bluetooth.get_devices: pass/fail + note
- bluetooth.connect: pass/fail + note
- bluetooth.disconnect: pass/fail + note
```

If no Deck is available in the current environment, say manual Bluetooth verification was not run.

---

## Self-Review Checklist

- Spec coverage:
  - Capability Registry metadata: Tasks 1-2.
  - `list_capabilities` / `run_capability`: Tasks 5-6.
  - bluetoothctl-backed validation capability: Tasks 3-4.
  - Unknown capability does not fall back to shell: Task 5.
  - Prompt update for skill/capability distinction: Task 6.
- Completeness scan:
  - No vague markers or unspecified implementation steps should remain in this plan.
- Type consistency:
  - Capability names use `bluetooth.get_devices`, `bluetooth.connect`, and `bluetooth.disconnect` throughout.
  - Tool entrypoint is `run_capability(name, args=None, confirm=False)`.
  - Bluetooth command runner returns `CommandResult(returncode, stdout, stderr)`.
