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
