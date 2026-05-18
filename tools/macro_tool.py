"""Macro tools: single key press + repeating key loops.

Uses `pynput` if available. On headless systems or systems without an
input backend, the calls degrade gracefully to a mock that just logs.

Background loops are tracked in a module-level registry so we can stop
them all from a different turn of the conversation.
"""

from __future__ import annotations

import asyncio
from typing import Any

try:
    from pynput.keyboard import Controller, Key  # type: ignore
    _KB: Controller | None = Controller()
except Exception:  # pragma: no cover — no display, no permissions, etc.
    _KB = None
    Key = None  # type: ignore


# Active background tasks created by start_key_loop, keyed by id.
_LOOPS: dict[int, asyncio.Task] = {}
_NEXT_ID = 0


def _resolve_key(key: str):
    """Map a string like 'space' or 'a' to a pynput key object or char."""
    if _KB is None:
        return key
    name = key.strip().lower()
    # Try named special keys (space, enter, esc, f1...)
    special = getattr(Key, name, None)
    if special is not None:
        return special
    return key  # raw character


async def press_key(key: str) -> dict[str, Any]:
    """Press and release a single key."""
    target = _resolve_key(key)
    if _KB is None:
        return {"ok": True, "mock": True, "key": key,
                "note": "pynput unavailable; pretending to press"}
    _KB.press(target)
    _KB.release(target)
    return {"ok": True, "key": key}


async def _loop_body(key: str, interval: float) -> None:
    """Worker coroutine that presses `key` every `interval` seconds."""
    target = _resolve_key(key)
    while True:
        if _KB is not None:
            _KB.press(target)
            _KB.release(target)
        await asyncio.sleep(interval)


async def start_key_loop(key: str, interval_seconds: float) -> dict[str, Any]:
    """Start a background task pressing `key` on a fixed interval."""
    global _NEXT_ID
    _NEXT_ID += 1
    loop_id = _NEXT_ID
    task = asyncio.create_task(_loop_body(key, float(interval_seconds)))
    _LOOPS[loop_id] = task
    return {"ok": True, "loop_id": loop_id, "key": key,
            "interval_seconds": interval_seconds,
            "mock": _KB is None}


async def stop_all_macros() -> dict[str, Any]:
    """Cancel every running background key loop."""
    stopped = list(_LOOPS.keys())
    for task in _LOOPS.values():
        task.cancel()
    # Await cancellations so the runtime doesn't leak tasks.
    for task in list(_LOOPS.values()):
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    _LOOPS.clear()
    return {"ok": True, "stopped": stopped}
