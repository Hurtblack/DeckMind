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
