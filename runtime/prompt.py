"""Async user prompt — shared by the Executor and any tool that needs
to ask the user before doing something risky.

We use a thread executor so the asyncio loop stays free (background
macro tasks keep ticking while we wait at the prompt).
"""

from __future__ import annotations

import asyncio


# Words that count as a "yes" answer. Both English and common Chinese.
_YES_WORDS: frozenset[str] = frozenset({
    "y", "yes", "是", "确认", "好", "好的", "ok", "行", "可以",
})


async def ask(message: str) -> str:
    """Read one line from the user without blocking the event loop."""
    loop = asyncio.get_running_loop()
    text = await loop.run_in_executor(None, lambda: input(message))
    return text.strip().lower()


def is_yes(answer: str) -> bool:
    """True if `answer` (already lowercased) means yes."""
    return answer in _YES_WORDS
