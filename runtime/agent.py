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
import time

from llm import HistoryItem, make_client
from memory import SessionMemory

from .context import format_context_for_prompt, gather_context
from .executor import Executor
from .interfaces import PermissionProvider, RuntimeEventSink
from .planner import Planner
from . import ui


MAX_STEPS = 8  # Hard cap to prevent runaway tool-calling.


class Agent:
    """Owns the planner, executor, and bounded session memory."""

    def __init__(
        self,
        *,
        verbose: bool = False,
        context_block: str = "",
        permission_provider: PermissionProvider | None = None,
        event_sink: RuntimeEventSink | None = None,
    ) -> None:
        self.verbose = verbose
        client = make_client()
        self.model = client.model
        self.planner = Planner(client, context_block=context_block)
        self.executor = Executor(
            permission_provider=permission_provider,
            event_sink=event_sink,
        )
        self.memory = SessionMemory(max_turns=6)
        # Lifetime token counters across all turns this session.
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    @classmethod
    async def create(
        cls,
        *,
        verbose: bool = False,
        permission_provider: PermissionProvider | None = None,
        event_sink: RuntimeEventSink | None = None,
    ) -> "Agent":
        """Factory that gathers device context before building the agent."""
        ctx = await gather_context()
        block = format_context_for_prompt(ctx)
        return cls(
            verbose=verbose,
            context_block=block,
            permission_provider=permission_provider,
            event_sink=event_sink,
        )

    # ----- per-turn display helpers -----

    def _print_tool_start(self, name: str, args: dict) -> None:
        if self.verbose:
            print(ui.tool_line(f"  ▸ tool: {name}({args})"))
        else:
            # Quiet mode: a single one-line hint so the user knows
            # something is happening without seeing the raw call.
            print(ui.tool_line(f"  · {name}…"))

    def _print_tool_result(self, result: dict) -> None:
        if self.verbose:
            print(ui.tool_line(f"    ↳ {result}"))
        else:
            # Surface errors / refusals only — successes stay quiet.
            if not result.get("ok", True):
                msg = result.get("message") or result.get("reason") or result.get("error")
                if msg:
                    print(ui.error_line(f"    ! {msg}"))

    # ----- main loop -----

    async def handle(self, user_text: str) -> str:
        """Run one user turn end-to-end. Returns the assistant's full reply."""
        # monotonic so we measure pure elapsed time even if the system
        # clock jumps (NTP sync, daylight savings, etc.).
        turn_start = time.monotonic()
        self.memory.add_user(user_text)

        # `history` is the rolling input we feed back into the model
        # each iteration. Starts as session memory + grows with each
        # tool_call/tool_result we record this turn.
        history: list[HistoryItem] = self.memory.snapshot()

        # Output prefix. Printed once before the first streamed
        # fragment so tokens flow inline after it.
        prefix_printed = False

        def stream_to_stdout(fragment: str) -> None:
            nonlocal prefix_printed
            if not prefix_printed:
                sys.stdout.write(ui.agent_prefix("deckmind ›") + " ")
                prefix_printed = True
            sys.stdout.write(fragment)
            sys.stdout.flush()

        reply_parts: list[str] = []
        turn_input = 0
        turn_output = 0

        for _ in range(MAX_STEPS):
            result = await self.planner.next_step(
                history, on_text_delta=stream_to_stdout,
            )
            turn_input += result.input_tokens
            turn_output += result.output_tokens

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

        # Update lifetime totals and print a footer with this turn's
        # token spend + the running session total. Uses thousands
        # separators and Chinese labels so the meaning is obvious.
        self.total_input_tokens += turn_input
        self.total_output_tokens += turn_output
        elapsed = time.monotonic() - turn_start
        if turn_input or turn_output:
            print(ui.footer(
                f"  ↳ 耗时 {elapsed:.1f}s"
                f"  ·  本轮 提示 {turn_input:,} + 回复 {turn_output:,} tokens"
                f"  ·  累计 提示 {self.total_input_tokens:,} + 回复 {self.total_output_tokens:,}"
                f"  ·  模型 {self.model}"
            ))

        # Blank line between turns so the next `you ›` prompt visually
        # separates from this reply.
        print()

        full_reply = "".join(reply_parts).strip()
        if full_reply:
            self.memory.add_assistant(full_reply)
        return full_reply
