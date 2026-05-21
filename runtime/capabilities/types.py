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
