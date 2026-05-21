from __future__ import annotations

import os
import sys
from pathlib import Path

# Decky 加载 plugin 时不会把 plugin 目录加入 sys.path，
# 所以同目录的 config_store/installer/runtime_client 必须手动加入路径。
_PLUGIN_DIR = Path(__file__).resolve().parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

# 启动/关闭游戏走后端 subprocess（steam steam://rungameid + 进程校验）。
#
# 曾经在这里设 DECKMIND_FRONTEND_LAUNCH=1，让 steam_tool 返回 frontend_action
# 交给插件前端用 SteamClient 执行，以避开 steam:// 确认弹窗。但前端执行只在
# Quick Access 面板挂载且 poll 循环存活时才发生——游戏模式下面板一收起，
# React 组件 unmount、轮询停止，事件没人接，游戏纹丝不动（桌面常开面板时正常，
# 游戏模式时失败，正是这个原因）。后端路径是同步的、不依赖前端 UI 生命周期，
# 且自带 reaper SteamLaunch AppId= 进程校验，可靠得多。
#
# 如需切回前端方案，设环境变量 DECKMIND_FRONTEND_LAUNCH=1 即可（机制仍保留）。

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
