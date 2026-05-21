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
