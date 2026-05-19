"""Runtime-facing interfaces for non-terminal clients.

The CLI can keep using stdin/stdout. Decky and future daemon clients need
structured permission requests and tool lifecycle events instead.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .prompt import ask, is_yes


PermissionDecision = Literal["allow", "deny", "allow_all"]
RuntimeEventSink = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class PermissionRequest:
    name: str
    arguments: dict[str, Any]
    risk: str
    message: str


class PermissionProvider(Protocol):
    async def request(self, request: PermissionRequest) -> PermissionDecision:
        """Return the user's decision for a side-effecting operation."""


class TerminalPermissionProvider:
    """Default permission provider used by the terminal CLI."""

    async def request(self, request: PermissionRequest) -> PermissionDecision:
        answer = await ask(request.message)
        if answer == "a":
            return "allow_all"
        if is_yes(answer) or (not answer and request.risk == "side_effect"):
            return "allow"
        return "deny"


async def null_event_sink(event: dict[str, Any]) -> None:
    """Default event sink for callers that do not need structured events."""
    _ = event
