"""Planner: ask the LLM what to do next.

The planner is deliberately thin. It owns the system prompt and forwards
the call to whichever provider client was configured. It does NOT
execute tools and it does NOT know which API style we're using.
"""

from __future__ import annotations

from pathlib import Path

from llm import HistoryItem, LLMClient, PlannedCall
from tools import specs


_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "system_prompt.txt"


class Planner:
    """Wraps an LLMClient and returns PlannedCall objects."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm
        self.system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")

    async def next_step(self, history: list[HistoryItem]) -> list[PlannedCall]:
        """Run one LLM step. Returns the tool calls the model emitted."""
        return await self.llm.plan(
            system_prompt=self.system_prompt,
            history=history,
            tools=specs(),
        )
