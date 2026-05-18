"""Provider-neutral types for the LLM layer.

We keep ONE history format in the Agent. Each provider client knows how
to translate this neutral format into the wire format its API expects.
That way adding a new provider = adding one file, no Agent changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlannedCall:
    """One tool the model wants the runtime to execute."""
    name: str
    arguments: dict[str, Any]
    call_id: str   # opaque id used to correlate the tool result later


@dataclass
class HistoryItem:
    """One entry in the conversation history.

    `kind` decides which other fields are populated:
      - 'user'           -> text
      - 'assistant_text' -> text
      - 'tool_call'      -> name + arguments + call_id
      - 'tool_result'    -> call_id + output (JSON string) + name
    """
    kind: str
    text: str | None = None
    name: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str | None = None
    output: str | None = None


@dataclass
class ToolSpec:
    """Neutral tool schema. Each client wraps it into its own shape."""
    name: str
    description: str
    parameters: dict[str, Any]


class LLMClient(ABC):
    """All provider clients implement this."""

    @abstractmethod
    async def plan(
        self,
        *,
        system_prompt: str,
        history: list[HistoryItem],
        tools: list[ToolSpec],
    ) -> list[PlannedCall]:
        """Ask the model what tool to call next."""
        ...
