from __future__ import annotations

import importlib.util
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


def load_plugin_module(filename: str):
    module_path = Path(__file__).resolve().parents[1] / "decky-plugin" / filename
    spec = importlib.util.spec_from_file_location(
        f"decky_plugin_{filename.replace('.', '_')}_under_test",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {filename} from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeAgent:
    model = "fake-model"
    provider = "deepseek"

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = events
        self.messages: list[str] = []
        self.switches: list[tuple[str | None, str | None]] = []

    def switch_llm(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> dict[str, str]:
        self.provider = provider or self.provider
        self.model = model or "default-model"
        self.switches.append((provider, model))
        return {"provider": self.provider, "model": self.model}

    async def handle(self, message: str) -> str:
        self.messages.append(message)
        self.events.append({"type": "tool_start", "name": "get_battery"})
        self.events.append({"type": "tool_result", "name": "get_battery", "result": {"ok": True}})
        return f"reply: {message}"


class FakePermissionRequest:
    name = "launch_game"
    arguments = {"game_name": "Portal"}
    risk = "side_effect"
    message = "launch Portal?"


class PermissionAgent:
    model = "fake-model"

    def __init__(self, permission_provider: Any) -> None:
        self.permission_provider = permission_provider

    async def handle(self, message: str) -> str:
        decision = await self.permission_provider.request(FakePermissionRequest())
        return f"{message}: {decision}"


class DeckyPluginConfigStoreTests(unittest.TestCase):
    def test_config_store_saves_provider_model_and_api_key_without_exposing_secret(self) -> None:
        module = load_plugin_module("config_store.py")
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "config.json"
            store = module.ConfigStore(path=path)

            public = store.save({
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key": "sk-test",
            })

            self.assertEqual(public["provider"], "deepseek")
            self.assertEqual(public["model"], "deepseek-v4-flash")
            self.assertTrue(public["has_api_key"])
            self.assertNotIn("sk-test", str(public))
            self.assertIn("sk-test", path.read_text(encoding="utf-8"))


class DeckyPluginRuntimeSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_ask_reports_missing_api_key_before_loading_agent(self) -> None:
        config_module = load_plugin_module("config_store.py")
        client_module = load_plugin_module("runtime_client.py")

        with tempfile.TemporaryDirectory() as root:
            store = config_module.ConfigStore(path=Path(root) / "config.json")
            store.save({"provider": "deepseek", "model": "deepseek-v4-flash"})
            runtime_dir = Path(root) / "runtime"
            runtime_dir.mkdir()
            (runtime_dir / "main.py").write_text("", encoding="utf-8")

            async def make_agent(**kwargs: Any) -> FakeAgent:
                raise AssertionError("agent should not be loaded without an API key")

            session = client_module.RuntimeSession(
                runtime_dir=runtime_dir,
                config_store=store,
                agent_factory=make_agent,
            )

            result = await session.ask("查看电量")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "missing_api_key")
        self.assertEqual(result["missing_api_key"], "DEEPSEEK_API_KEY")

    async def test_ask_sets_env_loads_agent_and_returns_reply_with_events(self) -> None:
        config_module = load_plugin_module("config_store.py")
        client_module = load_plugin_module("runtime_client.py")

        previous_provider = os.environ.get("LLM_PROVIDER")
        previous_key = os.environ.get("DEEPSEEK_API_KEY")
        try:
            with tempfile.TemporaryDirectory() as root:
                store = config_module.ConfigStore(path=Path(root) / "config.json")
                store.save({
                    "provider": "deepseek",
                    "model": "fake-model",
                    "api_key": "sk-test",
                })
                runtime_dir = Path(root) / "runtime"
                runtime_dir.mkdir()
                (runtime_dir / "main.py").write_text("", encoding="utf-8")
                created: list[FakeAgent] = []

                async def make_agent(**kwargs: Any) -> FakeAgent:
                    agent = FakeAgent(kwargs["events"])
                    created.append(agent)
                    return agent

                session = client_module.RuntimeSession(
                    runtime_dir=runtime_dir,
                    config_store=store,
                    agent_factory=make_agent,
                )

                result = await session.ask("查看电量")

            self.assertTrue(result["ok"])
            self.assertEqual(result["reply"], "reply: 查看电量")
            self.assertEqual(result["model"], "fake-model")
            self.assertEqual([event["type"] for event in result["events"]], [
                "tool_start",
                "tool_result",
            ])
            self.assertEqual(created[0].messages, ["查看电量"])
            self.assertEqual(os.environ["LLM_PROVIDER"], "deepseek")
            self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "sk-test")
        finally:
            if previous_provider is None:
                os.environ.pop("LLM_PROVIDER", None)
            else:
                os.environ["LLM_PROVIDER"] = previous_provider
            if previous_key is None:
                os.environ.pop("DEEPSEEK_API_KEY", None)
            else:
                os.environ["DEEPSEEK_API_KEY"] = previous_key

    async def test_cached_agent_switches_llm_when_config_changes(self) -> None:
        config_module = load_plugin_module("config_store.py")
        client_module = load_plugin_module("runtime_client.py")

        previous_provider = os.environ.get("LLM_PROVIDER")
        previous_model = os.environ.get("LLM_MODEL")
        previous_key = os.environ.get("DEEPSEEK_API_KEY")
        try:
            with tempfile.TemporaryDirectory() as root:
                store = config_module.ConfigStore(path=Path(root) / "config.json")
                store.save({
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                    "api_key": "sk-test",
                })
                runtime_dir = Path(root) / "runtime"
                runtime_dir.mkdir()
                (runtime_dir / "main.py").write_text("", encoding="utf-8")
                created: list[FakeAgent] = []

                async def make_agent(**kwargs: Any) -> FakeAgent:
                    agent = FakeAgent(kwargs["events"])
                    agent.model = "deepseek-v4-flash"
                    created.append(agent)
                    return agent

                session = client_module.RuntimeSession(
                    runtime_dir=runtime_dir,
                    config_store=store,
                    agent_factory=make_agent,
                )

                first = await session.ask("第一轮")
                store.save({
                    "provider": "deepseek",
                    "model": "deepseek-v4-pro",
                    "api_key": "sk-test",
                })
                second = await session.ask("第二轮")

            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            self.assertEqual(len(created), 1)
            self.assertEqual(created[0].messages, ["第一轮", "第二轮"])
            self.assertEqual(created[0].switches, [("deepseek", "deepseek-v4-pro")])
            self.assertEqual(second["model"], "deepseek-v4-pro")
        finally:
            if previous_provider is None:
                os.environ.pop("LLM_PROVIDER", None)
            else:
                os.environ["LLM_PROVIDER"] = previous_provider
            if previous_model is None:
                os.environ.pop("LLM_MODEL", None)
            else:
                os.environ["LLM_MODEL"] = previous_model
            if previous_key is None:
                os.environ.pop("DEEPSEEK_API_KEY", None)
            else:
                os.environ["DEEPSEEK_API_KEY"] = previous_key

    async def test_reset_session_drops_cached_agent_so_next_turn_starts_fresh(self) -> None:
        config_module = load_plugin_module("config_store.py")
        client_module = load_plugin_module("runtime_client.py")

        with tempfile.TemporaryDirectory() as root:
            store = config_module.ConfigStore(path=Path(root) / "config.json")
            store.save({
                "provider": "deepseek",
                "model": "fake-model",
                "api_key": "sk-test",
            })
            runtime_dir = Path(root) / "runtime"
            runtime_dir.mkdir()
            (runtime_dir / "main.py").write_text("", encoding="utf-8")
            created: list[FakeAgent] = []

            async def make_agent(**kwargs: Any) -> FakeAgent:
                agent = FakeAgent(kwargs["events"])
                created.append(agent)
                return agent

            session = client_module.RuntimeSession(
                runtime_dir=runtime_dir,
                config_store=store,
                agent_factory=make_agent,
            )

            first = await session.ask("第一轮")
            reset = session.reset_session([])
            second = await session.ask("第二轮")

        self.assertTrue(first["ok"])
        self.assertTrue(reset["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual(len(created), 2)
        self.assertEqual(created[0].messages, ["第一轮"])
        self.assertEqual(created[1].messages, ["第二轮"])

    def test_memory_candidates_are_compact_and_high_confidence(self) -> None:
        client_module = load_plugin_module("runtime_client.py")

        messages = [
            {"role": "user", "text": "以后代码改完直接 push 到远端，dev 和 main 保持同步"},
            {"role": "assistant", "text": "已 push"},
            {"role": "user", "text": "对，以后这种低风险操作别一直问确认"},
            {"role": "user", "text": "这个临时想法只是今天试一下，不要长期保存"},
        ]

        candidates = client_module.summarize_memory_candidates(messages)

        self.assertEqual(candidates, [
            {
                "key": "workflow_push_preference",
                "value": "完成代码改动后直接 push，并保持 main/dev 同步。",
            },
            {
                "key": "confirmation_preference",
                "value": "低风险或明确请求的操作不要反复确认。",
            },
        ])
        self.assertTrue(all(len(item["value"]) <= 80 for item in candidates))

    async def test_turn_waits_for_permission_answer_then_completes(self) -> None:
        config_module = load_plugin_module("config_store.py")
        client_module = load_plugin_module("runtime_client.py")

        with tempfile.TemporaryDirectory() as root:
            store = config_module.ConfigStore(path=Path(root) / "config.json")
            store.save({
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key": "sk-test",
            })
            runtime_dir = Path(root) / "runtime"
            runtime_dir.mkdir()
            (runtime_dir / "main.py").write_text("", encoding="utf-8")

            async def make_agent(**kwargs: Any) -> PermissionAgent:
                return PermissionAgent(kwargs["permission_provider"])

            session = client_module.RuntimeSession(
                runtime_dir=runtime_dir,
                config_store=store,
                agent_factory=make_agent,
            )

            started = await session.start_turn("打开 Portal")
            turn_id = started["turn_id"]

            pending: dict[str, Any] | None = None
            for _ in range(20):
                state = await session.get_turn(turn_id)
                if state["status"] == "waiting_permission":
                    pending = state
                    break
                await asyncio.sleep(0.01)

            self.assertIsNotNone(pending)
            assert pending is not None
            request = pending["permission_request"]
            self.assertEqual(request["name"], "launch_game")
            self.assertEqual(request["risk"], "side_effect")

            answer = await session.answer_permission(
                turn_id,
                request["request_id"],
                "allow",
            )

            self.assertTrue(answer["ok"])

            completed: dict[str, Any] | None = None
            for _ in range(20):
                state = await session.get_turn(turn_id)
                if state["status"] == "completed":
                    completed = state
                    break
                await asyncio.sleep(0.01)

            self.assertIsNotNone(completed)
            assert completed is not None
            self.assertEqual(completed["reply"], "打开 Portal: allow")
            self.assertEqual([event["type"] for event in completed["events"]], [
                "permission_request",
                "permission_result",
            ])

    async def test_each_turn_uses_its_own_permission_provider(self) -> None:
        config_module = load_plugin_module("config_store.py")
        client_module = load_plugin_module("runtime_client.py")

        with tempfile.TemporaryDirectory() as root:
            store = config_module.ConfigStore(path=Path(root) / "config.json")
            store.save({
                "provider": "deepseek",
                "model": "deepseek-v4-flash",
                "api_key": "sk-test",
            })
            runtime_dir = Path(root) / "runtime"
            runtime_dir.mkdir()
            (runtime_dir / "main.py").write_text("", encoding="utf-8")

            async def make_agent(**kwargs: Any) -> PermissionAgent:
                return PermissionAgent(kwargs["permission_provider"])

            session = client_module.RuntimeSession(
                runtime_dir=runtime_dir,
                config_store=store,
                agent_factory=make_agent,
            )

            first = await session.start_turn("第一次")
            first_id = first["turn_id"]
            first_pending: dict[str, Any] | None = None
            for _ in range(20):
                state = await session.get_turn(first_id)
                if state["status"] == "waiting_permission":
                    first_pending = state
                    break
                await asyncio.sleep(0.01)

            self.assertIsNotNone(first_pending)
            assert first_pending is not None
            await session.answer_permission(
                first_id,
                first_pending["permission_request"]["request_id"],
                "allow",
            )

            for _ in range(20):
                state = await session.get_turn(first_id)
                if state["status"] == "completed":
                    break
                await asyncio.sleep(0.01)

            second = await session.start_turn("第二次")
            second_id = second["turn_id"]
            second_pending: dict[str, Any] | None = None
            for _ in range(20):
                state = await session.get_turn(second_id)
                if state["status"] == "waiting_permission":
                    second_pending = state
                    break
                await asyncio.sleep(0.01)

            self.assertIsNotNone(second_pending)
            assert second_pending is not None
            self.assertEqual(second_pending["turn_id"], second_id)
            self.assertEqual(second_pending["permission_request"]["name"], "launch_game")


if __name__ == "__main__":
    unittest.main()
