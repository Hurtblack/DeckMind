"""CLI entry point.

Reads lines from stdin, hands each one to the Agent, prints the reply.
Type `exit` / `quit` (or Ctrl-D / Ctrl-C) to leave.
"""

from __future__ import annotations

import asyncio
import os
import sys

from llm import PROVIDERS
from runtime import Agent


BANNER = "SteamDeckAgent — type a request, or `exit` to quit."


def _check_api_key() -> None:
    """Make sure the API key for the selected provider is present."""
    name = os.environ.get("LLM_PROVIDER", "openai").lower()
    cfg = PROVIDERS.get(name)
    if not cfg:
        print(f"ERROR: unknown LLM_PROVIDER={name!r}. "
              f"Valid: {list(PROVIDERS)}", file=sys.stderr)
        sys.exit(1)
    key_env = cfg["api_key_env"]
    if not os.environ.get(key_env):
        print(f"ERROR: provider {name!r} requires env var {key_env}.",
              file=sys.stderr)
        sys.exit(1)


async def repl() -> None:
    """Async REPL: input() in a thread, agent.handle() awaited normally."""
    _check_api_key()
    agent = Agent()
    provider = os.environ.get("LLM_PROVIDER", "openai")
    print(f"{BANNER}  [provider={provider}]")

    loop = asyncio.get_running_loop()
    while True:
        try:
            # Run blocking input() off the event loop so background macro
            # tasks (start_key_loop) keep ticking while we wait for the user.
            line = await loop.run_in_executor(None, lambda: input("you> "))
        except (EOFError, KeyboardInterrupt):
            print()
            break

        line = line.strip()
        if not line:
            continue
        if line.lower() in {"exit", "quit"}:
            break

        try:
            reply = await agent.handle(line)
        except Exception as e:  # pragma: no cover — defensive top-level
            print(f"[agent error] {type(e).__name__}: {e}")
            continue

        print(f"bot> {reply}")


if __name__ == "__main__":
    asyncio.run(repl())
