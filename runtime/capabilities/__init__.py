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
