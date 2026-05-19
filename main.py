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
from runtime import ui


BANNER = (
    "SteamDeckAgent — type a request, `/model <model>`, "
    "`/api <provider> [model]`, or `exit` to quit."
)


def parse_control_command(
    line: str,
    *,
    current_provider: str,
) -> dict[str, str | None] | None:
    """Parse REPL-only control commands for switching LLM settings."""
    parts = line.split()
    if not parts:
        return None

    command = parts[0].lower()
    if command == "/model":
        if len(parts) != 2:
            raise ValueError("Usage: /model <model>")
        return {"provider": current_provider, "model": parts[1]}

    if command in {"/api", "/provider"}:
        if len(parts) not in {2, 3}:
            raise ValueError("Usage: /api <provider> [model]")
        return {
            "provider": parts[1].lower(),
            "model": parts[2] if len(parts) == 3 else None,
        }

    return None


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
    print(f"{BANNER}  [{provider} · {agent.model} · {mode}]")

    loop = asyncio.get_running_loop()
    user_label = ui.user_prompt("you ›") + " "
    while True:
        try:
            # Run blocking input() off the event loop so background
            # macro tasks (start_key_loop) keep ticking while we wait.
            line = await loop.run_in_executor(None, lambda: input(user_label))
        except (EOFError, KeyboardInterrupt):
            print()
            break

        line = line.strip()
        if not line:
            continue
        if line.lower() in {"exit", "quit"}:
            break

        try:
            command = parse_control_command(line, current_provider=agent.provider)
            if command is not None:
                result = agent.switch_llm(
                    provider=command["provider"],
                    model=command["model"],
                )
                print(
                    ui.agent_prefix("deckmind ›") + " "
                    f"已切换到 {result['provider']} · {result['model']}"
                )
                continue
            await agent.handle(line)
        except ValueError as e:
            print(ui.error_line(f"[control error] {e}"))
        except RuntimeError as e:
            print(ui.error_line(f"[provider error] {e}"))
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
