"""Provider-neutral types for the LLM layer.

We keep ONE history format in the Agent. Each provider client knows how
to translate this neutral format into the wire format its API expects.
That way adding a new provider = adding one file, no Agent changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class PlannedCall:
    """One tool the model wants the runtime to execute."""
    name: str
    arguments: dict[str, Any]
    call_id: str   # opaque id used to correlate the tool result later


@dataclass
class PlanResult:
    """Output of one LLM step.

    `text` is the natural-language reply (possibly streamed). When
    `tool_calls` is empty, `text` is the agent's final reply for this
    user turn — the loop ends. When `tool_calls` is non-empty, `text`
    is any narration the model emitted before deciding to call a tool
    (often empty); the loop continues after executing the tools.

    `input_tokens` / `output_tokens` come from the provider's usage
    report. They are best-effort: 0 when the provider doesn't ship
    them with a streamed response.
    """
    text: str = ""
    tool_calls: list[PlannedCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


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


# Type alias: a callback invoked with each streamed text fragment.
# Synchronous to keep clients simple — typical impl: `lambda s: print(s, end="", flush=True)`.
TextDeltaCallback = Callable[[str], None]


class LLMClient(ABC):
    """All provider clients implement this."""

    # Concrete subclasses set this to the model name they're using
    # (e.g. "gpt-4o-mini", "deepseek-chat"). Exposed so the CLI can
    # show the model in the banner and per-turn footer.
    model: str = ""

    @abstractmethod
    async def plan(
        self,
        *,
        system_prompt: str,
        history: list[HistoryItem],
        tools: list[ToolSpec],
        on_text_delta: TextDeltaCallback | None = None,
    ) -> PlanResult:
        """Ask the model for its next step.

        If `on_text_delta` is provided, the client streams natural-language
        output and calls the callback with each fragment as it arrives.
        Tool calls are NOT streamed token-by-token — they are collected
        and returned in the final PlanResult.
        """
        ...
