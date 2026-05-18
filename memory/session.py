"""Tiny conversation memory.

Stores HistoryItem entries (the provider-neutral format). The Agent
extends this snapshot with in-turn tool_call/tool_result items before
sending it to the planner.
"""

from __future__ import annotations

from collections import deque

from llm import HistoryItem


class SessionMemory:
    """Bounded chat history of HistoryItem entries."""

    def __init__(self, max_turns: int = 6) -> None:
        # Each "turn" is roughly a (user, assistant) pair — we cap items
        # at max_turns * 2 to keep prompts cheap.
        self._items: deque[HistoryItem] = deque(maxlen=max_turns * 2)

    def add_user(self, text: str) -> None:
        """Record what the user typed."""
        self._items.append(HistoryItem(kind="user", text=text))

    def add_assistant(self, text: str) -> None:
        """Record the assistant's final natural-language reply."""
        self._items.append(HistoryItem(kind="assistant_text", text=text))

    def snapshot(self) -> list[HistoryItem]:
        """Return a copy — safe to extend without mutating the deque."""
        return list(self._items)
