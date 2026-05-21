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


if __name__ == "__main__":
    unittest.main()
