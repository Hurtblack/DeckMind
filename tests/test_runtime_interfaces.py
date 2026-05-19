from __future__ import annotations

import contextlib
import io
import unittest
from typing import Any
from unittest.mock import patch

from runtime.agent import Agent
from runtime.control import parse_control_command
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


class AgentInterfaceWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_passes_runtime_interfaces_to_executor(self) -> None:
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

    async def test_agent_can_switch_llm_without_resetting_runtime_state(self) -> None:
        class FakeClient:
            def __init__(self, model: str) -> None:
                self.model = model

        created: list[tuple[str | None, str | None]] = []

        def fake_make_client(*, provider: str | None = None, model: str | None = None) -> FakeClient:
            created.append((provider, model))
            return FakeClient(model or "initial-model")

        with patch("runtime.agent.make_client", side_effect=fake_make_client):
            agent = Agent()

        original_memory = agent.memory
        original_executor = agent.executor
        agent.total_input_tokens = 12
        agent.total_output_tokens = 34

        with patch("runtime.agent.make_client", side_effect=fake_make_client):
            result = agent.switch_llm(provider="deepseek", model="deepseek-v4-pro")

        self.assertEqual(result, {"provider": "deepseek", "model": "deepseek-v4-pro"})
        self.assertEqual(agent.provider, "deepseek")
        self.assertEqual(agent.model, "deepseek-v4-pro")
        self.assertEqual(agent.planner.llm.model, "deepseek-v4-pro")
        self.assertIs(agent.memory, original_memory)
        self.assertIs(agent.executor, original_executor)
        self.assertEqual(agent.total_input_tokens, 12)
        self.assertEqual(agent.total_output_tokens, 34)
        self.assertEqual(created, [(None, None), ("deepseek", "deepseek-v4-pro")])

    async def test_agent_intercepts_natural_language_deepseek_pro_switch(self) -> None:
        class FakeClient:
            def __init__(self, model: str) -> None:
                self.model = model

        created: list[tuple[str | None, str | None]] = []

        def fake_make_client(*, provider: str | None = None, model: str | None = None) -> FakeClient:
            created.append((provider, model))
            return FakeClient(model or "deepseek-v4-flash")

        with patch("runtime.agent.make_client", side_effect=fake_make_client):
            agent = Agent(provider="deepseek", model="deepseek-v4-flash")
            with contextlib.redirect_stdout(io.StringIO()):
                reply = await agent.handle("换pro模型")

        self.assertEqual(reply, "已切换到 deepseek · deepseek-v4-pro")
        self.assertEqual(agent.model, "deepseek-v4-pro")
        self.assertEqual(agent.memory.snapshot(), [])
        self.assertEqual(created, [
            ("deepseek", "deepseek-v4-flash"),
            ("deepseek", "deepseek-v4-pro"),
        ])


class ControlCommandTests(unittest.TestCase):
    def test_model_command_switches_model_on_current_provider(self) -> None:
        self.assertEqual(
            parse_control_command("/model pro", current_provider="deepseek"),
            {"provider": "deepseek", "model": "deepseek-v4-pro"},
        )

    def test_api_command_switches_provider_and_model(self) -> None:
        self.assertEqual(
            parse_control_command("/api deepseek deepseek-v4-pro", current_provider="openai"),
            {"provider": "deepseek", "model": "deepseek-v4-pro"},
        )

    def test_api_command_can_switch_provider_only(self) -> None:
        self.assertEqual(
            parse_control_command("/api deepseek", current_provider="openai"),
            {"provider": "deepseek", "model": None},
        )

    def test_non_control_command_returns_none(self) -> None:
        self.assertIsNone(parse_control_command("帮我安装 clash", current_provider="deepseek"))

    def test_natural_language_pro_command_switches_deepseek_model(self) -> None:
        self.assertEqual(
            parse_control_command("换pro模型", current_provider="deepseek"),
            {"provider": "deepseek", "model": "deepseek-v4-pro"},
        )

    def test_natural_language_flash_command_switches_deepseek_model(self) -> None:
        self.assertEqual(
            parse_control_command("切回 flash 模型", current_provider="deepseek"),
            {"provider": "deepseek", "model": "deepseek-v4-flash"},
        )


if __name__ == "__main__":
    unittest.main()
