from __future__ import annotations

import sys
from pathlib import Path

# Decky 加载 plugin 时不会把 plugin 目录加入 sys.path，
# 所以同目录的 config_store/installer/runtime_client 必须手动加入路径。
_PLUGIN_DIR = Path(__file__).resolve().parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

try:
    import decky
except ImportError:  # pragma: no cover - Decky exists inside decky-loader.
    decky = None

from config_store import CONFIG_STORE
from installer import INSTALLER
from runtime_client import RuntimeSession


class Plugin:
    """Thin Decky backend for installing and talking to DeckMind runtime."""

    def __init__(self) -> None:
        self.runtime = RuntimeSession(
            runtime_dir=INSTALLER.runtime_dir,
            config_store=CONFIG_STORE,
        )

    async def _main(self) -> None:
        if decky is not None:
            decky.logger.info("DeckMind shell backend started")

    async def _unload(self) -> None:
        if decky is not None:
            decky.logger.info("DeckMind shell backend unloaded")

    async def status(self) -> dict:
        status = INSTALLER.status()
        status["config"] = CONFIG_STORE.get()
        return status

    async def get_config(self) -> dict:
        return CONFIG_STORE.get()

    async def save_config(self, config: dict) -> dict:
        return CONFIG_STORE.save(config)

    async def install_runtime(self) -> dict:
        return await INSTALLER.install_async()

    async def ask(self, message: str) -> dict:
        result = await self.runtime.ask(message)
        if not result.get("ok"):
            result["status"] = await self.status()
        return result

    async def start_turn(self, message: str) -> dict:
        result = await self.runtime.start_turn(message)
        if not result.get("ok"):
            result["status"] = await self.status()
        return result

    async def get_turn(self, turn_id: str) -> dict:
        return await self.runtime.get_turn(turn_id)

    async def answer_permission(
        self,
        turn_id: str,
        request_id: str,
        decision: str,
    ) -> dict:
        return await self.runtime.answer_permission(turn_id, request_id, decision)
