"""OpenAI Responses API client — streams text deltas to a callback.

Used when LLM_PROVIDER=openai (the default).
"""

from __future__ import annotations

import json
import os
from typing import Any

from openai import AsyncOpenAI

from .base import (
    HistoryItem,
    LLMClient,
    PlanResult,
    PlannedCall,
    TextDeltaCallback,
    ToolSpec,
)


class OpenAIResponsesClient(LLMClient):
    """Async wrapper over `client.responses.stream`."""

    def __init__(self, model: str | None = None) -> None:
        # AsyncOpenAI reads OPENAI_API_KEY (+ optional OPENAI_BASE_URL) from env.
        self.client = AsyncOpenAI()
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    # ----- format conversions -----

    def _to_input(self, history: list[HistoryItem]) -> list[dict[str, Any]]:
        """Translate neutral history into Responses API `input` items."""
        out: list[dict[str, Any]] = []
        for h in history:
            if h.kind == "user":
                out.append({"role": "user", "content": h.text or ""})
            elif h.kind == "assistant_text":
                out.append({"role": "assistant", "content": h.text or ""})
            elif h.kind == "tool_call":
                out.append({
                    "type": "function_call",
                    "call_id": h.call_id,
                    "name": h.name,
                    "arguments": json.dumps(h.arguments),
                })
            elif h.kind == "tool_result":
                out.append({
                    "type": "function_call_output",
                    "call_id": h.call_id,
                    "output": h.output or "",
                })
        return out

    def _to_tools(self, tools: list[ToolSpec]) -> list[dict[str, Any]]:
        """Responses API expects flat {type,name,description,parameters}."""
        return [{
            "type": "function",
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
        } for t in tools]

    # ----- main call -----

    async def plan(
        self,
        *,
        system_prompt: str,
        history: list[HistoryItem],
        tools: list[ToolSpec],
        on_text_delta: TextDeltaCallback | None = None,
    ) -> PlanResult:
        text_parts: list[str] = []

        # Streaming context: we get events for text deltas in real time,
        # while function_call items only show up complete in `output`
        # at the end.
        async with self.client.responses.stream(
            model=self.model,
            instructions=system_prompt,
            input=self._to_input(history),
            tools=self._to_tools(tools),
            tool_choice="auto",
            parallel_tool_calls=False,
        ) as stream:
            async for event in stream:
                if event.type == "response.output_text.delta":
                    text_parts.append(event.delta)
                    if on_text_delta is not None:
                        on_text_delta(event.delta)
            response = await stream.get_final_response()

        calls: list[PlannedCall] = []
        for item in response.output:
            if getattr(item, "type", None) != "function_call":
                continue
            calls.append(PlannedCall(
                name=item.name,
                arguments=json.loads(item.arguments or "{}"),
                call_id=item.call_id,
            ))

        usage = getattr(response, "usage", None)
        return PlanResult(
            text="".join(text_parts),
            tool_calls=calls,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
        )
