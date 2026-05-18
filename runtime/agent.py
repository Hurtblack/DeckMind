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
        (repeat until `final_answer`
         or MAX_STEPS reached)

The loop stays provider-agnostic — everything that knows about a
specific LLM API lives behind llm.LLMClient.
"""

from __future__ import annotations

import json

from llm import HistoryItem, make_client
from memory import SessionMemory

from .executor import Executor
from .planner import Planner


MAX_STEPS = 8  # Hard cap to prevent runaway tool-calling.


class Agent:
    """Owns the planner, executor, and bounded session memory."""

    def __init__(self) -> None:
        self.planner = Planner(make_client())
        self.executor = Executor()
        self.memory = SessionMemory(max_turns=6)

    async def handle(self, user_text: str) -> str:
        """Run one user turn end-to-end and return the assistant's reply."""
        self.memory.add_user(user_text)

        # `history` is the rolling input we feed back into the model each
        # iteration. It starts as the session snapshot and grows with each
        # tool_call / tool_result pair produced this turn.
        history: list[HistoryItem] = self.memory.snapshot()

        reply_text = "(no reply)"

        for _ in range(MAX_STEPS):
            calls = await self.planner.next_step(history)

            if not calls:
                # Model returned text only (no tool). Treat it as the answer.
                reply_text = "Model returned no tool call; ending turn."
                break

            # We force one call at a time, so just take the first.
            call = calls[0]

            # Echo the tool_call back into history — both APIs require it
            # so the model can correlate with our response on next turn.
            history.append(HistoryItem(
                kind="tool_call",
                name=call.name,
                arguments=call.arguments,
                call_id=call.call_id,
            ))

            print(f"  ▸ tool: {call.name}({call.arguments})")
            result = await self.executor.run(call.name, call.arguments)
            print(f"    ↳ {result}")

            history.append(HistoryItem(
                kind="tool_result",
                call_id=call.call_id,
                name=call.name,
                output=json.dumps(result),
            ))

            # `final_answer` ends the loop with the model's chosen message.
            if call.name == "final_answer":
                reply_text = call.arguments.get("message", "")
                break
        else:
            reply_text = f"(stopped after {MAX_STEPS} tool steps)"

        self.memory.add_assistant(reply_text)
        return reply_text
