"""Planner: ask the LLM what to do next.

Thin wrapper. Reads the system prompt from disk once, appends any
runtime-collected device context, and forwards everything to the
configured LLM client. Does NOT execute tools.
"""

from __future__ import annotations

from pathlib import Path

from llm import HistoryItem, LLMClient, PlanResult, TextDeltaCallback
from tools import specs


_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "system_prompt.txt"


class Planner:
    """Wraps an LLMClient and returns PlanResult objects."""

    def __init__(self, llm: LLMClient, *, context_block: str = "") -> None:
        self.llm = llm
        base = _PROMPT_PATH.read_text(encoding="utf-8")
        # If we have device context, append it so every turn sees it.
        self.system_prompt = base + ("\n\n" + context_block if context_block else "")

    async def next_step(
        self,
        history: list[HistoryItem],
        *,
        on_text_delta: TextDeltaCallback | None = None,
    ) -> PlanResult:
        """Run one LLM step. Streams text via the callback if provided."""
        return await self.llm.plan(
            system_prompt=self.system_prompt,
            history=history,
            tools=specs(),
            on_text_delta=on_text_delta,
        )
