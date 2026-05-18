"""OpenAI Responses API client.

Used when LLM_PROVIDER=openai (the default).
"""

from __future__ import annotations

import json
import os
from typing import Any

from openai import AsyncOpenAI

from .base import HistoryItem, LLMClient, PlannedCall, ToolSpec


class OpenAIResponsesClient(LLMClient):
    """Thin async wrapper over `client.responses.create`."""

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
    ) -> list[PlannedCall]:
        response = await self.client.responses.create(
            model=self.model,
            instructions=system_prompt,
            input=self._to_input(history),
            tools=self._to_tools(tools),
            tool_choice="auto",
            parallel_tool_calls=False,
        )

        calls: list[PlannedCall] = []
        for item in response.output:
            if getattr(item, "type", None) != "function_call":
                continue
            calls.append(PlannedCall(
                name=item.name,
                arguments=json.loads(item.arguments or "{}"),
                call_id=item.call_id,
            ))
        return calls
