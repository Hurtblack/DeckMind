from __future__ import annotations

import unittest

import runtime.capabilities  # noqa: F401  load runtime first to avoid a tools<->runtime import cycle
from tools import system_tool


SINKS_OUTPUT = """\
Sink #41
        State: RUNNING
        Name: alsa_output.pci-0000_04_00.5-platform-acp5x_mach.0.HiFi__hw_acp5x_1__sink
        Description: Built-in Speakers
Sink #88
        State: SUSPENDED
        Name: bluez_output.AA_BB_CC_DD_EE_FF.1
        Description: Pixel Buds Pro
"""


class AudioSinkParserTests(unittest.TestCase):
    def test_parse_sinks(self) -> None:
        sinks = system_tool.parse_sinks(SINKS_OUTPUT)

        self.assertEqual(len(sinks), 2)
        self.assertEqual(sinks[0]["description"], "Built-in Speakers")
        self.assertEqual(sinks[0]["state"], "RUNNING")
        self.assertEqual(sinks[1]["name"], "bluez_output.AA_BB_CC_DD_EE_FF.1")
        self.assertEqual(sinks[1]["description"], "Pixel Buds Pro")

    def test_match_sink_exact_name(self) -> None:
        sinks = system_tool.parse_sinks(SINKS_OUTPUT)
        self.assertEqual(
            system_tool.match_sink("bluez_output.AA_BB_CC_DD_EE_FF.1", sinks),
            "bluez_output.AA_BB_CC_DD_EE_FF.1",
        )

    def test_match_sink_by_description_substring(self) -> None:
        sinks = system_tool.parse_sinks(SINKS_OUTPUT)
        self.assertEqual(
            system_tool.match_sink("pixel buds", sinks),
            "bluez_output.AA_BB_CC_DD_EE_FF.1",
        )

    def test_match_sink_ambiguous_returns_none(self) -> None:
        sinks = system_tool.parse_sinks(SINKS_OUTPUT)
        # Matches both descriptions (each contains the letter sequence).
        self.assertIsNone(system_tool.match_sink("s", sinks))

    def test_match_sink_no_match_returns_none(self) -> None:
        sinks = system_tool.parse_sinks(SINKS_OUTPUT)
        self.assertIsNone(system_tool.match_sink("nonexistent device", sinks))


if __name__ == "__main__":
    unittest.main()
