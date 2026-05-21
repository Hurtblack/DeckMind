from __future__ import annotations

import os
import sys
from pathlib import Path

# Decky 加载 plugin 时不会把 plugin 目录加入 sys.path，
# 所以同目录的 config_store/installer/runtime_client 必须手动加入路径。
_PLUGIN_DIR = Path(__file__).resolve().parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

# 启动/关闭游戏走前端 SteamClient（SteamClient.URL.ExecuteSteamURL /
# SteamClient.Apps.LaunchApp / SteamClient.Apps.RunGame），由 steam_tool
# 返回 frontend_action 交给插件前端执行。
#
# 后端 subprocess（steam steam://rungameid）在 Desktop Mode（KDE Session）
# 下能通 DBus，但在 Game Mode（gamescope session）下 plugin_loader.service
# 的 DBus 环境与 Steam UI 进程隔离，URI 会被静默丢弃。前端 SteamClient 跑在
# Steam UI 进程内部，两种模式均可靠。
#
# 如需切回后端 subprocess 方案（例如非 Decky 环境调试），unset 此变量即可。

os.environ["DECKMIND_FRONTEND_LAUNCH"] = "1"

try:
    import decky
except ImportError:  # pragma: no cover - Decky exists inside decky-loader.
    decky = None

from config_store import CONFIG_STORE
from installer import INSTALLER
from runtime_client import RuntimeSession


def _fix_plugin_dir_permissions() -> None:
    """将 plugin 目录下由 root 写出的文件改回 deck 用户。

    Decky Loader 以 root 拉起的 plugin 后端在 import 时生成的 __pycache__/
    及日志等文件归属 root，会阻断 deck 用户后续 rsync 部署。
    仅当当前进程是 root 且目标用户不是 root 时才做。
    """
    if os.getuid() != 0:
        return
    try:
        import pwd
        pw = pwd.getpwnam(os.environ.get("DECKY_USER") or "deck")
        uid, gid = pw.pw_uid, pw.pw_gid
        if uid == 0:
            return
    except (KeyError, ImportError):
        return

    for root, dirs, files in os.walk(str(_PLUGIN_DIR)):
        for name in dirs + files:
            try:
                os.chown(os.path.join(root, name), uid, gid)
            except OSError:
                pass


class Plugin:
    """Thin Decky backend for installing and talking to DeckMind runtime."""

    def __init__(self) -> None:
        self.runtime = RuntimeSession(
            runtime_dir=INSTALLER.runtime_dir,
            config_store=CONFIG_STORE,
        )

    async def _main(self) -> None:
        _fix_plugin_dir_permissions()
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

    async def reset_session(self, messages: list[dict] | None = None) -> dict:
        return self.runtime.reset_session(messages or [])

    async def get_install_progress(self, since: int = 0) -> dict:
        """前端在 install_runtime 运行期间轮询，拿到自 `since` 以后的事件。

        返回 {events, total, running}：把 total 作为下次轮询的 since。
        """
        return INSTALLER.get_progress(since)

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
