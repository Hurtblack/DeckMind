"""Tiny ANSI color helpers used by the REPL.

We honor the de-facto `NO_COLOR` env-var convention: when set (to any
value), we emit no escape codes. Pipe-to-file or non-tty stdout also
disables colors so dumps don't get littered with `\x1b[...]`.
"""

from __future__ import annotations

import os
import sys


def _colors_enabled() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


_ENABLED = _colors_enabled()


def _wrap(code: str, text: str) -> str:
    if not _ENABLED:
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


# Public helpers — semantic names, not raw color names, so we can
# change the palette in one place.

def user_prompt(text: str) -> str:
    """Prefix for the `you›` input prompt — bold cyan."""
    return _wrap("1;36", text)


def agent_prefix(text: str) -> str:
    """Prefix for streamed `deckmind›` replies — bold green."""
    return _wrap("1;32", text)


def tool_line(text: str) -> str:
    """Quiet-mode tool indicator — dim yellow."""
    return _wrap("2;33", text)


def error_line(text: str) -> str:
    """Tool error / refusal callout — dim red."""
    return _wrap("2;31", text)


def footer(text: str) -> str:
    """Dim grey footer (model + token usage)."""
    return _wrap("2", text)
