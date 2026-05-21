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

    def test_builtin_audio_capabilities_are_listed(self) -> None:
        names = {item["name"] for item in list_capabilities()}

        self.assertIn("audio.get_volume", names)
        self.assertIn("audio.set_volume", names)

    def test_builtin_steam_capabilities_are_listed(self) -> None:
        names = {item["name"] for item in list_capabilities()}

        self.assertIn("steam.launch_game", names)
        self.assertIn("steam.close_game", names)

    def test_existing_tool_capability_metadata(self) -> None:
        audio_set = get_capability("audio.set_volume")
        steam_launch = get_capability("steam.launch_game")

        self.assertIsNotNone(audio_set)
        self.assertIsNotNone(steam_launch)
        assert audio_set is not None
        assert steam_launch is not None

        self.assertEqual(audio_set.risk, "side_effect")
        self.assertTrue(audio_set.confirm_required)
        self.assertEqual(audio_set.args_schema["required"], ["percent"])
        self.assertEqual(steam_launch.risk, "side_effect")
        self.assertTrue(steam_launch.confirm_required)
        self.assertEqual(steam_launch.args_schema["required"], ["game_name"])

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

    async def test_audio_get_volume_safe_capability_executes(self) -> None:
        from unittest.mock import patch

        from tools.capability_tool import run_capability

        async def fake_get_volume() -> dict[str, object]:
            return {"ok": True, "percent": 42, "backend": "fake"}

        with patch("tools.system_tool.get_volume", fake_get_volume):
            result = await run_capability("audio.get_volume")

        self.assertEqual(result, {"ok": True, "percent": 42, "backend": "fake"})

    async def test_audio_set_volume_without_confirm_returns_dry_run(self) -> None:
        from tools.capability_tool import run_capability

        result = await run_capability(
            "audio.set_volume",
            {"percent": 35},
            confirm=False,
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["capability"], "audio.set_volume")
        self.assertEqual(result["args"], {"percent": 35})

    async def test_steam_launch_game_without_confirm_returns_dry_run(self) -> None:
        from tools.capability_tool import run_capability

        result = await run_capability(
            "steam.launch_game",
            {"game_name": "hades"},
            confirm=False,
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["capability"], "steam.launch_game")
        self.assertEqual(result["args"], {"game_name": "hades"})

    async def test_steam_close_game_without_confirm_returns_dry_run(self) -> None:
        from tools.capability_tool import run_capability

        result = await run_capability(
            "steam.close_game",
            {"process_name": "Hades"},
            confirm=False,
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["capability"], "steam.close_game")
        self.assertEqual(result["args"], {"process_name": "Hades"})


if __name__ == "__main__":
    unittest.main()
