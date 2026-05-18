"""The Agent runtime loop.

    user input
        │
        ▼
    ┌─────────┐  tool_call      ┌──────────┐
    │ Planner │ ───────────────▶│ Executor │
    └─────────┘                 └──────────┘
        ▲                            │
        │   tool_result              │
        └────────────────────────────┘
        (repeat until the model produces text instead of a tool call,
         or until MAX_STEPS is reached)

The loop is provider-agnostic. The model "ends" a turn by emitting
natural-language text (which we stream straight to stdout) instead of
calling another tool — there's no special `final_answer` sentinel.
"""

from __future__ import annotations

import json
import sys

from llm import HistoryItem, make_client
from memory import SessionMemory

from .context import format_context_for_prompt, gather_context
from .executor import Executor
from .planner import Planner


MAX_STEPS = 8  # Hard cap to prevent runaway tool-calling.


class Agent:
    """Owns the planner, executor, and bounded session memory."""

    def __init__(self, *, verbose: bool = False, context_block: str = "") -> None:
        self.verbose = verbose
        self.planner = Planner(make_client(), context_block=context_block)
        self.executor = Executor()
        self.memory = SessionMemory(max_turns=6)

    @classmethod
    async def create(cls, *, verbose: bool = False) -> "Agent":
        """Factory that gathers device context before building the agent."""
        ctx = await gather_context()
        block = format_context_for_prompt(ctx)
        return cls(verbose=verbose, context_block=block)

    # ----- per-turn display helpers -----

    def _print_tool_start(self, name: str, args: dict) -> None:
        if self.verbose:
            print(f"  ▸ tool: {name}({args})")
        else:
            # Quiet mode: a single one-line hint so the user knows
            # something is happening without seeing the raw call.
            print(f"  · {name}…")

    def _print_tool_result(self, result: dict) -> None:
        if self.verbose:
            print(f"    ↳ {result}")
        else:
            # Surface errors / refusals only — successes stay quiet.
            if not result.get("ok", True):
                msg = result.get("message") or result.get("reason") or result.get("error")
                if msg:
                    print(f"    ! {msg}")

    # ----- main loop -----

    async def handle(self, user_text: str) -> str:
        """Run one user turn end-to-end. Returns the assistant's full reply."""
        self.memory.add_user(user_text)

        # `history` is the rolling input we feed back into the model
        # each iteration. Starts as session memory + grows with each
        # tool_call/tool_result we record this turn.
        history: list[HistoryItem] = self.memory.snapshot()

        # Bot output prefix. We only print it once, before the first
        # text fragment arrives, so streamed tokens flow inline.
        prefix_printed = False

        def stream_to_stdout(fragment: str) -> None:
            nonlocal prefix_printed
            if not prefix_printed:
                sys.stdout.write("bot> ")
                prefix_printed = True
            sys.stdout.write(fragment)
            sys.stdout.flush()

        reply_parts: list[str] = []

        for _ in range(MAX_STEPS):
            result = await self.planner.next_step(
                history, on_text_delta=stream_to_stdout,
            )

            # Accumulate any narration text from this step.
            if result.text:
                reply_parts.append(result.text)

            if not result.tool_calls:
                # Model is done — its text IS the reply.
                if prefix_printed:
                    print()  # close the streamed line
                break

            # End any in-progress text line so tool logs don't smash into it.
            if prefix_printed:
                print()
                prefix_printed = False

            # We force one tool call at a time, so just take the first.
            call = result.tool_calls[0]

            history.append(HistoryItem(
                kind="tool_call",
                name=call.name,
                arguments=call.arguments,
                call_id=call.call_id,
            ))

            self._print_tool_start(call.name, call.arguments)
            tool_result = await self.executor.run(call.name, call.arguments)
            self._print_tool_result(tool_result)

            history.append(HistoryItem(
                kind="tool_result",
                call_id=call.call_id,
                name=call.name,
                output=json.dumps(tool_result),
            ))
        else:
            note = f"(stopped after {MAX_STEPS} tool steps)"
            print(note)
            reply_parts.append(note)

        full_reply = "".join(reply_parts).strip()
        if full_reply:
            self.memory.add_assistant(full_reply)
        return full_reply
