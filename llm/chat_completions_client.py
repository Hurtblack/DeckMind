"""Chat Completions client — streams text + assembles tool calls.

Works with DeepSeek, Kimi, Qwen, GLM, OpenRouter, and OpenAI itself
(via the legacy chat endpoint). The OpenAI SDK speaks Chat Completions
to any host you point it at via `base_url`, so we just reuse it.
"""

from __future__ import annotations

import json
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
        on_text_delta: TextDeltaCallback | None = None,
    ) -> PlanResult:
        # Tool-call deltas come in pieces and need to be reassembled by
        # `index`. Each entry: {"id": str, "name": str, "args": str}.
        tc_buffer: dict[int, dict[str, str]] = {}
        text_parts: list[str] = []
        in_tok = 0
        out_tok = 0

        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=self._to_messages(system_prompt, history),
            tools=self._to_tools(tools),
            tool_choice="auto",
            stream=True,
            # Ask for a final usage chunk so we can show token counts.
            # OpenAI / DeepSeek / Kimi / Qwen all honor this.
            stream_options={"include_usage": True},
        )

        async for chunk in stream:
            # The last chunk often has no choices but does have `usage`.
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                in_tok = getattr(usage, "prompt_tokens", 0) or in_tok
                out_tok = getattr(usage, "completion_tokens", 0) or out_tok

            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue

            # Text fragments → forward to callback + accumulate.
            if delta.content:
                text_parts.append(delta.content)
                if on_text_delta is not None:
                    on_text_delta(delta.content)

            # Tool-call fragments → glue them together by `index`.
            for tc in (delta.tool_calls or []):
                idx = tc.index
                slot = tc_buffer.setdefault(idx, {"id": "", "name": "", "args": ""})
                if tc.id:
                    slot["id"] = tc.id
                fn = tc.function
                if fn and fn.name:
                    slot["name"] = fn.name
                if fn and fn.arguments:
                    slot["args"] += fn.arguments

        calls: list[PlannedCall] = []
        for idx in sorted(tc_buffer):
            slot = tc_buffer[idx]
            try:
                args = json.loads(slot["args"] or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(PlannedCall(
                name=slot["name"],
                arguments=args,
                call_id=slot["id"],
            ))

        return PlanResult(
            text="".join(text_parts), tool_calls=calls,
            input_tokens=in_tok, output_tokens=out_tok,
        )
