"""Runtime client used by the DeckMind Decky shell backend."""

from __future__ import annotations

import contextlib
import asyncio
import importlib
import io
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

PLUGIN_DIR = Path(__file__).resolve().parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

from config_store import ConfigStore
from installer import RUNTIME_HOME


API_KEY_ENVS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "openai-chat": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
    "moonshot-global": "MOONSHOT_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
}


AgentFactory = Callable[..., Awaitable[Any]]
PROFILE_FACT_LIMIT = 12
PROFILE_VALUE_LIMIT = 80


def _message_texts(messages: list[dict[str, Any]] | None) -> list[str]:
    if not messages:
        return []
    texts: list[str] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        if item.get("role") != "user":
            continue
        text = str(item.get("text") or "").strip()
        if text:
            texts.append(text)
    return texts[-50:]


def _has_explicit_preference(text: str) -> bool:
    return bool(re.search(r"(以后|默认|总是|每次|不用|不要|别|直接|保持)", text))


def summarize_memory_candidates(
    messages: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    """Extract short, high-confidence user preferences from recent UI history.

    This is intentionally conservative: it recognizes repeated workflow
    preferences and explicit "以后/默认" instructions, not arbitrary summaries.
    """
    texts = _message_texts(messages)
    combined = "\n".join(texts)
    candidates: list[dict[str, str]] = []

    push_hits = sum(
        1 for text in texts
        if re.search(r"(push|推送|远端)", text, re.I)
    )
    if (
        push_hits >= 2
        or any(
            _has_explicit_preference(text)
            and re.search(r"(push|推送|远端)", text, re.I)
            for text in texts
        )
    ):
        candidates.append({
            "key": "workflow_push_preference",
            "value": "完成代码改动后直接 push，并保持 main/dev 同步。",
        })

    if (
        re.search(r"(低风险|明确请求|更新|升级|side[-_ ]?effect)", combined, re.I)
        and re.search(r"(别|不要|不用|不需要|直接).{0,12}(问|确认|打扰)", combined)
    ):
        candidates.append({
            "key": "confirmation_preference",
            "value": "低风险或明确请求的操作不要反复确认。",
        })

    return [
        {"key": item["key"], "value": item["value"][:PROFILE_VALUE_LIMIT]}
        for item in candidates
        if len(item["value"]) <= PROFILE_VALUE_LIMIT
    ]


class DenyPermissionProvider:
    """Temporary provider until the Decky UI can answer permission prompts."""

    async def request(self, request: Any) -> str:
        _ = request
        return "deny"


class TurnPermissionProvider:
    def __init__(self, turn: dict[str, Any]) -> None:
        self.turn = turn
        self._counter = 0
        self._pending: dict[str, asyncio.Future[str]] = {}

    async def request(self, request: Any) -> str:
        self._counter += 1
        request_id = f"perm-{self._counter}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._pending[request_id] = future
        payload = {
            "request_id": request_id,
            "name": request.name,
            "arguments": request.arguments,
            "risk": request.risk,
            "message": request.message,
        }
        self.turn["status"] = "waiting_permission"
        self.turn["permission_request"] = payload
        self.turn["events"].append({"type": "permission_request", **payload})
        decision = await future
        self.turn["permission_request"] = None
        self.turn["status"] = "running"
        self.turn["events"].append({
            "type": "permission_result",
            "request_id": request_id,
            "name": request.name,
            "risk": request.risk,
            "decision": decision,
        })
        return decision

    def answer(self, request_id: str, decision: str) -> bool:
        future = self._pending.get(request_id)
        if future is None or future.done():
            return False
        future.set_result(decision)
        return True


class RuntimeSession:
    """Lazy in-process session for the installed external runtime."""

    def __init__(
        self,
        *,
        runtime_dir: Path = RUNTIME_HOME,
        config_store: ConfigStore,
        agent_factory: AgentFactory | None = None,
    ) -> None:
        self.runtime_dir = runtime_dir
        self.config_store = config_store
        self._agent_factory = agent_factory
        self._agent: Any | None = None
        self._turns: dict[str, dict[str, Any]] = {}
        self._turn_counter = 0

    def _entrypoint(self) -> Path:
        return self.runtime_dir / "main.py"

    def _ensure_runtime_path(self) -> None:
        runtime_path = str(self.runtime_dir)
        vendor_path = str(self.runtime_dir / ".vendor")
        for p in (vendor_path, runtime_path):
            if Path(p).exists() and p not in sys.path:
                sys.path.insert(0, p)

    def _installed(self) -> bool:
        return self.runtime_dir.exists() and self._entrypoint().exists()

    def _apply_env(self, config: dict[str, Any]) -> str | None:
        provider = str(config.get("provider") or "openai").lower()
        key_env = API_KEY_ENVS.get(provider)
        if key_env is None:
            return "unknown_provider"

        api_keys = config.get("api_keys") if isinstance(config.get("api_keys"), dict) else {}
        api_key = str(api_keys.get(provider) or "").strip()
        if not api_key:
            return key_env

        os.environ["LLM_PROVIDER"] = provider
        os.environ[key_env] = api_key
        model = str(config.get("model") or "").strip()
        if model:
            os.environ["LLM_MODEL"] = model
        else:
            os.environ.pop("LLM_MODEL", None)
        return None

    def _llm_selection(self, config: dict[str, Any]) -> tuple[str, str | None]:
        provider = str(config.get("provider") or "openai").lower()
        model = str(config.get("model") or "").strip() or None
        return provider, model

    def _agent_needs_llm_switch(
        self,
        agent: Any,
        provider: str,
        model: str | None,
    ) -> bool:
        current_provider = getattr(agent, "provider", provider)
        current_model = getattr(agent, "model", None)
        if current_provider != provider:
            return True
        return model is not None and current_model != model

    def _sync_agent_llm(
        self,
        agent: Any,
        provider: str,
        model: str | None,
    ) -> None:
        switch_llm = getattr(agent, "switch_llm", None)
        if not callable(switch_llm):
            return
        if self._agent_needs_llm_switch(agent, provider, model):
            switch_llm(provider=provider, model=model)

    async def _create_agent(
        self,
        events: list[dict[str, Any]],
        permission_provider: Any,
    ) -> Any:
        if self._agent_factory is not None:
            return await self._agent_factory(
                permission_provider=permission_provider,
                events=events,
            )

        # 把 runtime 目录 + .vendor (装第三方依赖如 openai) 加到 sys.path
        self._ensure_runtime_path()

        runtime_module = importlib.import_module("runtime")
        agent_cls = getattr(runtime_module, "Agent")

        async def emit(event: dict[str, Any]) -> None:
            events.append(event)

        return await agent_cls.create(
            permission_provider=permission_provider,
            event_sink=emit,
        )

    async def _preflight(self) -> dict[str, Any] | None:
        if not self._installed():
            return {"ok": False, "error": "runtime_not_installed"}

        missing = self._apply_env(self.config_store.get_runtime_config())
        if missing:
            if missing == "unknown_provider":
                return {"ok": False, "error": "unknown_provider"}
            return {"ok": False, "error": "missing_api_key", "missing_api_key": missing}
        return None

    def reset_session(self, messages: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Start a fresh agent session and optionally persist compact preferences."""
        for turn in self._turns.values():
            task = turn.get("task")
            if task is not None and not task.done():
                task.cancel()
        self._turns.clear()
        self._agent = None

        candidates = summarize_memory_candidates(messages)
        remembered: list[dict[str, str]] = []
        if candidates and self._installed():
            try:
                self._ensure_runtime_path()
                profile_module = importlib.import_module("runtime.profile")
                facts = profile_module.load_profile()
                for item in candidates:
                    if len(facts) >= PROFILE_FACT_LIMIT and item["key"] not in facts:
                        continue
                    facts[item["key"]] = item["value"]
                    remembered.append(item)
                profile_module.save_profile(facts)
            except Exception:
                remembered = []

        return {
            "ok": True,
            "reset": True,
            "remembered": remembered,
            "candidate_count": len(candidates),
        }

    async def ask(self, message: str) -> dict[str, Any]:
        text = message.strip()
        if not text:
            return {"ok": False, "error": "empty_message"}
        error = await self._preflight()
        if error is not None:
            return error
        provider, model = self._llm_selection(self.config_store.get_runtime_config())

        events: list[dict[str, Any]] = []
        if self._agent is None:
            self._agent = await self._create_agent(events, DenyPermissionProvider())
        self._sync_agent_llm(self._agent, provider, model)

        with contextlib.redirect_stdout(io.StringIO()):
            reply = await self._agent.handle(text)

        return {
            "ok": True,
            "reply": reply,
            "model": getattr(self._agent, "model", None),
            "events": events,
        }

    async def start_turn(self, message: str) -> dict[str, Any]:
        text = message.strip()
        if not text:
            return {"ok": False, "error": "empty_message"}
        error = await self._preflight()
        if error is not None:
            return error

        provider, model = self._llm_selection(self.config_store.get_runtime_config())

        self._turn_counter += 1
        turn_id = f"turn-{int(time.time() * 1000)}-{self._turn_counter}"
        turn: dict[str, Any] = {
            "turn_id": turn_id,
            "status": "running",
            "message": text,
            "reply": None,
            "error": None,
            "model": None,
            "events": [],
            "permission_request": None,
            "permission_provider": None,
            "task": None,
        }
        permission_provider = TurnPermissionProvider(turn)
        turn["permission_provider"] = permission_provider
        self._turns[turn_id] = turn

        # 限制 _turns 大小，避免长会话内存泄漏（保留最近 32 个 turn）
        if len(self._turns) > 32:
            stale = sorted(self._turns.keys())[: len(self._turns) - 32]
            for key in stale:
                self._turns.pop(key, None)

        turn["task"] = asyncio.create_task(
            self._run_turn(turn, permission_provider, provider, model)
        )
        return {"ok": True, "turn_id": turn_id}

    async def _run_turn(
        self,
        turn: dict[str, Any],
        permission_provider: TurnPermissionProvider,
        provider: str,
        model: str | None,
    ) -> None:
        events = turn["events"]
        try:
            # 复用 agent 保持对话上下文/记忆；首轮才创建
            if self._agent is None:
                self._agent = await self._create_agent(events, permission_provider)
            else:
                # 复用时把当前 turn 的 permission_provider 注入，让 UI 能处理权限请求
                if hasattr(self._agent, "set_permission_provider"):
                    self._agent.set_permission_provider(permission_provider)
                elif hasattr(self._agent, "permission_provider"):
                    self._agent.permission_provider = permission_provider

                async def emit(event: dict[str, Any]) -> None:
                    events.append(event)

                if hasattr(self._agent, "set_event_sink"):
                    self._agent.set_event_sink(emit)

            # 切换 LLM provider/model（若变化）
            self._sync_agent_llm(self._agent, provider, model)

            with contextlib.redirect_stdout(io.StringIO()):
                reply = await self._agent.handle(turn["message"])
            turn["reply"] = reply
            turn["model"] = getattr(self._agent, "model", None)
            turn["status"] = "completed"
        except Exception as e:
            turn["error"] = f"{type(e).__name__}: {e}"
            turn["status"] = "failed"

    async def get_turn(self, turn_id: str) -> dict[str, Any]:
        turn = self._turns.get(turn_id)
        if turn is None:
            return {"ok": False, "error": "unknown_turn"}
        return self._public_turn(turn)

    async def answer_permission(
        self,
        turn_id: str,
        request_id: str,
        decision: str,
    ) -> dict[str, Any]:
        turn = self._turns.get(turn_id)
        if turn is None:
            return {"ok": False, "error": "unknown_turn"}
        if decision not in {"allow", "deny", "allow_all"}:
            return {"ok": False, "error": "invalid_decision"}
        provider = turn.get("permission_provider")
        if provider is None or not provider.answer(request_id, decision):
            return {"ok": False, "error": "unknown_permission_request"}
        return {"ok": True}

    def _public_turn(self, turn: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "turn_id": turn["turn_id"],
            "status": turn["status"],
            "reply": turn["reply"],
            "error": turn["error"],
            "model": turn["model"],
            "events": list(turn["events"]),
            "permission_request": turn["permission_request"],
        }
