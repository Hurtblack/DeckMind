"""CLI entry point.

Reads lines from stdin, hands each one to the Agent, streams the reply.
Type `exit` / `quit` (or Ctrl-D / Ctrl-C) to leave.

Flags:
  -v, --verbose   show every tool call + raw result (developer mode)
"""

from __future__ import annotations

import argparse
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


async def repl(verbose: bool) -> None:
    """Async REPL: input() in a thread, agent.handle() awaited normally."""
    _check_api_key()

    # Building the agent gathers device context (battery, disk, Steam
    # library, Flatpak apps). Tell the user what we're doing because it
    # can take a couple of seconds on a cold cache.
    print("Gathering device context…", flush=True)
    agent = await Agent.create(verbose=verbose)
    provider = os.environ.get("LLM_PROVIDER", "openai")
    mode = "verbose" if verbose else "quiet"
    print(f"{BANNER}  [provider={provider} · {mode}]")

    loop = asyncio.get_running_loop()
    while True:
        try:
            # Run blocking input() off the event loop so background
            # macro tasks (start_key_loop) keep ticking while we wait.
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
            await agent.handle(line)
        except Exception as e:  # pragma: no cover — defensive top-level
            print(f"[agent error] {type(e).__name__}: {e}")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SteamDeckAgent — local LLM agent for Linux/Steam Deck")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="show every tool call + raw result (developer mode)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(repl(verbose=args.verbose))
