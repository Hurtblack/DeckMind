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
    async def test_side_effect_executes_without_permission_prompt(self) -> None:
        events: list[dict[str, Any]] = []
        provider = RecordingPermissionProvider("deny")
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
        self.assertEqual(provider.requests, [])
        self.assertEqual([event["type"] for event in events], [
            "tool_start",
            "tool_result",
        ])
        self.assertEqual(events[0]["name"], "launch_game")
        self.assertEqual(events[0]["risk"], "side_effect")

    async def test_destructive_permission_denial_does_not_execute_tool(self) -> None:
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
            result = await executor.run("write_text_file", {
                "path": "~/Documents/demo.txt",
                "content": "demo",
                "confirm": True,
            })

        self.assertFalse(result["ok"])
        self.assertTrue(result["denied"])
        self.assertEqual(calls, [])
        self.assertEqual([event["type"] for event in events], [
            "permission_request",
            "permission_result",
            "tool_result",
        ])
        self.assertEqual(events[1]["decision"], "deny")

    async def test_side_effect_runs_each_time_without_allow_all(self) -> None:
        provider = RecordingPermissionProvider("deny")
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
        self.assertEqual(provider.requests, [])

    async def test_apply_update_is_side_effect_without_permission_prompt(self) -> None:
        provider = RecordingPermissionProvider("deny")
        calls: list[dict[str, Any]] = []

        async def fake_tool(**kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            return {"ok": True, "updated": True}

        executor = Executor(permission_provider=provider)

        with patch("runtime.executor.get_tool", return_value=fake_tool):
            result = await executor.run("apply_update", {"confirm": True})

        self.assertEqual(result, {"ok": True, "updated": True})
        self.assertEqual(calls, [{"confirm": True}])
        self.assertEqual(provider.requests, [])


class CapabilityExecutorRiskTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_capabilities_is_safe(self) -> None:
        provider = RecordingPermissionProvider("deny")
        executor = Executor(permission_provider=provider)

        result = await executor.run("list_capabilities", {})

        self.assertTrue(result["ok"])
        self.assertEqual(provider.requests, [])

    async def test_run_side_effect_capability_default_executes_without_permission(self) -> None:
        provider = RecordingPermissionProvider("allow")
        executor = Executor(permission_provider=provider)

        async def fake_set_volume(percent: int) -> dict[str, object]:
            return {"ok": True, "percent": percent, "backend": "fake", "verified": True}

        with patch("tools.system_tool.set_volume", fake_set_volume):
            result = await executor.run(
                "run_capability",
                {
                    "name": "audio.set_volume",
                    "args": {"percent": 55},
                },
            )

        self.assertEqual(result, {"ok": True, "percent": 55, "backend": "fake", "verified": True})
        self.assertEqual(provider.requests, [])

    async def test_run_destructive_capability_preview_skips_permission(self) -> None:
        from runtime.capabilities.registry import register_capability
        from runtime.capabilities.types import Capability

        async def fake_handler() -> dict[str, object]:
            return {"ok": True}

        register_capability(Capability(
            name="test.destructive_preview",
            description="Test destructive preview",
            args_schema={"type": "object", "properties": {}},
            risk="destructive",
            confirm_required=True,
            handler=fake_handler,
        ))
        provider = RecordingPermissionProvider("deny")
        executor = Executor(permission_provider=provider)

        result = await executor.run("run_capability", {"name": "test.destructive_preview"})

        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["capability"], "test.destructive_preview")
        self.assertEqual(provider.requests, [])

    async def test_run_safe_capability_executes_without_permission(self) -> None:
        provider = RecordingPermissionProvider("deny")
        executor = Executor(permission_provider=provider)

        async def fake_get_volume() -> dict[str, object]:
            return {"ok": True, "percent": 25, "backend": "fake"}

        with patch("tools.system_tool.get_volume", fake_get_volume):
            result = await executor.run("run_capability", {"name": "audio.get_volume"})

        self.assertEqual(result, {"ok": True, "percent": 25, "backend": "fake"})
        self.assertEqual(provider.requests, [])

    async def test_run_destructive_capability_confirm_true_requests_permission(self) -> None:
        from runtime.capabilities.registry import register_capability
        from runtime.capabilities.types import Capability

        async def fake_handler() -> dict[str, object]:
            return {"ok": True, "changed": True}

        register_capability(Capability(
            name="test.destructive_execute",
            description="Test destructive execute",
            args_schema={"type": "object", "properties": {}},
            risk="destructive",
            confirm_required=True,
            handler=fake_handler,
        ))
        provider = RecordingPermissionProvider("allow")
        executor = Executor(permission_provider=provider)

        result = await executor.run(
            "run_capability",
            {"name": "test.destructive_execute", "confirm": True},
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(provider.requests[0].name, "run_capability")
        self.assertEqual(provider.requests[0].risk, "destructive")

    async def test_run_destructive_capability_confirm_true_denial_skips_execution(self) -> None:
        from runtime.capabilities.registry import register_capability
        from runtime.capabilities.types import Capability

        calls = 0

        async def fake_handler() -> dict[str, object]:
            nonlocal calls
            calls += 1
            return {"ok": True}

        register_capability(Capability(
            name="test.destructive_denied",
            description="Test destructive denied",
            args_schema={"type": "object", "properties": {}},
            risk="destructive",
            confirm_required=True,
            handler=fake_handler,
        ))
        provider = RecordingPermissionProvider("deny")
        executor = Executor(permission_provider=provider)

        result = await executor.run(
            "run_capability",
            {"name": "test.destructive_denied", "confirm": True},
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["denied"])
        self.assertEqual(calls, 0)
        self.assertEqual(len(provider.requests), 1)

    async def test_run_unknown_capability_does_not_request_permission(self) -> None:
        provider = RecordingPermissionProvider("deny")
        executor = Executor(permission_provider=provider)

        result = await executor.run(
            "run_capability",
            {"name": "wifi.switch_network", "confirm": True},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unknown_capability")
        self.assertEqual(provider.requests, [])


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
