from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from runtime.agent import Agent
from runtime.executor import Executor
from runtime.interfaces import PermissionRequest


class RecordingPermissionProvider:
    def __init__(self, decision: str) -> None:
        self.decision = decision
        self.requests: list[PermissionRequest] = []

    async def request(self, request: PermissionRequest) -> str:
        self.requests.append(request)
        return self.decision


class RuntimeInterfaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_side_effect_permission_uses_injected_provider_and_emits_events(self) -> None:
        events: list[dict[str, Any]] = []
        provider = RecordingPermissionProvider("allow")
        calls: list[dict[str, Any]] = []

        async def fake_tool(**kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            return {"ok": True, "launched": kwargs["game_name"]}

        async def emit(event: dict[str, Any]) -> None:
            events.append(event)

        executor = Executor(permission_provider=provider, event_sink=emit)

        with patch("runtime.executor.get_tool", return_value=fake_tool):
            result = await executor.run("launch_game", {"game_name": "Portal"})

        self.assertEqual(result, {"ok": True, "launched": "Portal"})
        self.assertEqual(calls, [{"game_name": "Portal"}])
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(provider.requests[0].name, "launch_game")
        self.assertEqual(provider.requests[0].risk, "side_effect")
        self.assertEqual([event["type"] for event in events], [
            "permission_request",
            "permission_result",
            "tool_start",
            "tool_result",
        ])
        self.assertEqual(events[1]["decision"], "allow")
        self.assertEqual(events[2]["name"], "launch_game")

    async def test_permission_denial_does_not_execute_tool(self) -> None:
        events: list[dict[str, Any]] = []
        provider = RecordingPermissionProvider("deny")
        calls: list[dict[str, Any]] = []

        async def fake_tool(**kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            return {"ok": True}

        async def emit(event: dict[str, Any]) -> None:
            events.append(event)

        executor = Executor(permission_provider=provider, event_sink=emit)

        with patch("runtime.executor.get_tool", return_value=fake_tool):
            result = await executor.run("launch_game", {"game_name": "Portal"})

        self.assertFalse(result["ok"])
        self.assertTrue(result["denied"])
        self.assertEqual(calls, [])
        self.assertEqual([event["type"] for event in events], [
            "permission_request",
            "permission_result",
            "tool_result",
        ])
        self.assertEqual(events[1]["decision"], "deny")

    async def test_allow_all_decision_reuses_permission_for_same_tool(self) -> None:
        provider = RecordingPermissionProvider("allow_all")
        calls = 0

        async def fake_tool(**kwargs: Any) -> dict[str, Any]:
            nonlocal calls
            calls += 1
            return {"ok": True, "volume": kwargs["percent"]}

        executor = Executor(permission_provider=provider)

        with patch("runtime.executor.get_tool", return_value=fake_tool):
            first = await executor.run("set_volume", {"percent": 30})
            second = await executor.run("set_volume", {"percent": 40})

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual(calls, 2)
        self.assertEqual(len(provider.requests), 1)


class AgentInterfaceWiringTests(unittest.TestCase):
    def test_agent_passes_runtime_interfaces_to_executor(self) -> None:
        provider = object()

        async def emit(event: dict[str, Any]) -> None:
            _ = event

        class FakeClient:
            model = "fake-model"

        with (
            patch("runtime.agent.make_client", return_value=FakeClient()),
            patch("runtime.agent.Executor") as executor_class,
        ):
            Agent(permission_provider=provider, event_sink=emit)

        executor_class.assert_called_once_with(
            permission_provider=provider,
            event_sink=emit,
        )


if __name__ == "__main__":
    unittest.main()
