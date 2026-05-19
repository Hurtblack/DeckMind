from __future__ import annotations

import unittest
import sys
from types import SimpleNamespace
from typing import Any

sys.modules.setdefault(
    "openai",
    SimpleNamespace(AsyncOpenAI=lambda **kwargs: SimpleNamespace()),
)

from llm import HistoryItem
from llm.chat_completions_client import ChatCompletionsClient


class AsyncChunks:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks

    def __aiter__(self) -> "AsyncChunks":
        self._index = 0
        return self

    async def __anext__(self) -> Any:
        if self._index >= len(self._chunks):
            raise StopAsyncIteration
        item = self._chunks[self._index]
        self._index += 1
        return item


class FakeCompletions:
    def __init__(self, chunks: list[Any]) -> None:
        self.chunks = chunks

    async def create(self, **kwargs: Any) -> AsyncChunks:
        return AsyncChunks(self.chunks)


class FakeClient:
    def __init__(self, chunks: list[Any]) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(chunks))


class ChatCompletionsClientTests(unittest.IsolatedAsyncioTestCase):
    def test_to_messages_preserves_tool_call_reasoning_content(self) -> None:
        client = ChatCompletionsClient.__new__(ChatCompletionsClient)
        history = [
            HistoryItem(
                kind="tool_call",
                text="Let me inspect Downloads.",
                name="find_files",
                arguments={"path": "~/Downloads"},
                call_id="call-1",
                reasoning_content="Need to inspect Downloads before installing.",
            ),
            HistoryItem(
                kind="tool_result",
                call_id="call-1",
                output='{"ok": true}',
            ),
        ]

        messages = client._to_messages("system", history)

        self.assertEqual(
            messages[1]["content"],
            "Let me inspect Downloads.",
        )
        self.assertEqual(
            messages[1]["reasoning_content"],
            "Need to inspect Downloads before installing.",
        )

    async def test_plan_captures_reasoning_content_for_tool_calls(self) -> None:
        client = ChatCompletionsClient.__new__(ChatCompletionsClient)
        client.model = "deepseek-v4-flash"
        client.client = FakeClient([
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None,
                            reasoning_content="Need to inspect Downloads.",
                            tool_calls=[],
                        )
                    )
                ],
                usage=None,
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None,
                            reasoning_content=None,
                            tool_calls=[
                                SimpleNamespace(
                                    index=0,
                                    id="call-1",
                                    function=SimpleNamespace(
                                        name="find_files",
                                        arguments='{"path": "~/Downloads"}',
                                    ),
                                )
                            ],
                        )
                    )
                ],
                usage=None,
            ),
        ])

        result = await client.plan(
            system_prompt="system",
            history=[],
            tools=[],
        )

        self.assertEqual(len(result.tool_calls), 1)
        self.assertEqual(
            result.tool_calls[0].reasoning_content,
            "Need to inspect Downloads.",
        )


if __name__ == "__main__":
    unittest.main()
