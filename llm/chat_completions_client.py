"""Chat Completions client — works with DeepSeek, Kimi, Qwen, GLM,
OpenRouter, and OpenAI itself (via the legacy chat endpoint).

The OpenAI Python SDK speaks Chat Completions to any host you point it
at via `base_url`, so we just reuse it.
"""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from .base import HistoryItem, LLMClient, PlannedCall, ToolSpec


class ChatCompletionsClient(LLMClient):
    """One implementation, many providers — selected by base_url + key."""

    def __init__(self, *, api_key: str, base_url: str | None, model: str) -> None:
        # base_url=None falls back to OpenAI's own endpoint.
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    # ----- format conversions -----

    def _to_messages(
        self, system_prompt: str, history: list[HistoryItem],
    ) -> list[dict[str, Any]]:
        """Translate neutral history into Chat Completions `messages`."""
        msgs: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        for h in history:
            if h.kind == "user":
                msgs.append({"role": "user", "content": h.text or ""})
            elif h.kind == "assistant_text":
                msgs.append({"role": "assistant", "content": h.text or ""})
            elif h.kind == "tool_call":
                # Chat Completions wants tool_calls attached to an assistant
                # message with content=None.
                msgs.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": h.call_id,
                        "type": "function",
                        "function": {
                            "name": h.name,
                            "arguments": json.dumps(h.arguments),
                        },
                    }],
                })
            elif h.kind == "tool_result":
                msgs.append({
                    "role": "tool",
                    "tool_call_id": h.call_id,
                    "content": h.output or "",
                })
        return msgs

    def _to_tools(self, tools: list[ToolSpec]) -> list[dict[str, Any]]:
        """Chat Completions nests the spec under a `function` key."""
        return [{
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        } for t in tools]

    # ----- main call -----

    async def plan(
        self,
        *,
        system_prompt: str,
        history: list[HistoryItem],
        tools: list[ToolSpec],
    ) -> list[PlannedCall]:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=self._to_messages(system_prompt, history),
            tools=self._to_tools(tools),
            tool_choice="auto",
        )

        msg = response.choices[0].message
        if not msg.tool_calls:
            return []

        calls: list[PlannedCall] = []
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(PlannedCall(
                name=tc.function.name,
                arguments=args,
                call_id=tc.id,
            ))
        return calls
