"""Installer/client helpers for the thin DeckMind Decky plugin.

调试期：runtime 通过 git clone / git pull 直接从 GitHub 仓库拉取。
发布期：可改回 tar.gz release 下载（保留代码以便切换）。
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

GIT_TIMEOUT = 120  # 秒，单次 git 操作超时
PIP_TIMEOUT = 300  # 秒，pip install 超时（首次装 openai 等较慢）
VENDOR_DIR_NAME = ".vendor"  # runtime 内放第三方依赖的子目录


DEFAULT_RUNTIME_REPO = "https://github.com/Hurtblack/DeckMind.git"
DEFAULT_BRANCH = "main"


def _xdg_dir(env_var: str, default_subpath: str) -> Path:
    """遵循 XDG Base Directory 规范解析路径，支持环境变量覆盖。"""
    base = os.environ.get(env_var)
    if base:
        return Path(base).expanduser()
    return Path.home() / default_subpath


# 数据放 $XDG_DATA_HOME/deckmind/runtime  (默认 ~/.local/share/deckmind/runtime)
# 缓存放 $XDG_CACHE_HOME/deckmind         (默认 ~/.cache/deckmind)
# 调试时可用 DECKMIND_RUNTIME_DIR / DECKMIND_CACHE_DIR 覆盖整条路径
RUNTIME_HOME = Path(
    os.environ.get("DECKMIND_RUNTIME_DIR")
    or _xdg_dir("XDG_DATA_HOME", ".local/share") / "deckmind" / "runtime"
)
CACHE_HOME = Path(
    os.environ.get("DECKMIND_CACHE_DIR")
    or _xdg_dir("XDG_CACHE_HOME", ".cache") / "deckmind"
)
MANIFEST_NAME = "deckmind-runtime.json"


class RuntimeInstaller:
    """通过 git 安装/更新 DeckMind runtime。"""

    def __init__(
        self,
        *,
        runtime_dir: Path = RUNTIME_HOME,
        cache_dir: Path = CACHE_HOME,
        repo_url: str | None = None,
        branch: str | None = None,
    ) -> None:
        self.runtime_dir = runtime_dir
        self.cache_dir = cache_dir
        self.repo_url = repo_url or os.environ.get(
            "DECKMIND_RUNTIME_REPO", DEFAULT_RUNTIME_REPO
        )
        self.branch = branch or os.environ.get("DECKMIND_RUNTIME_BRANCH", DEFAULT_BRANCH)

    @property
    def manifest_path(self) -> Path:
        return self.runtime_dir / MANIFEST_NAME

    def _manifest(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return {}
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _git_commit(self) -> str | None:
        """读 runtime_dir 当前 commit hash，失败返回 None。"""
        try:
            out = subprocess.check_output(
                ["git", "-C", str(self.runtime_dir), "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            return out.decode().strip()
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            return None

    def status(self) -> dict[str, Any]:
        manifest = self._manifest()
        entrypoint = self.runtime_dir / "main.py"
        installed = self.runtime_dir.exists() and entrypoint.exists()
        return {
            "ok": True,
            "installed": installed,
            "runtime_dir": str(self.runtime_dir),
            "version": manifest.get("version"),
            "commit": self._git_commit(),
            "entrypoint": str(entrypoint),
            "repo_url": self.repo_url,
            "branch": self.branch,
        }

    def _clean_env(self) -> dict[str, str]:
        """剔除 Decky Loader (PyInstaller 打包) 注入的运行时环境变量。

        Decky Loader 是 PyInstaller 单文件二进制，启动时把自带的旧 libssl/libcrypto
        解压到 /tmp/_MEI*/，并通过 LD_LIBRARY_PATH 让自己加载它们。但 subprocess
        会继承这些变量，导致 git/curl 等系统二进制加载到错误版本的库（典型表现：
        `libssl.so.3: version 'OPENSSL_3.x.0' not found`）。

        这里把 PyInstaller 相关的环境变量全部移除，让子进程使用系统默认库。
        """
        env = os.environ.copy()
        for key in (
            "LD_LIBRARY_PATH",
            "LD_PRELOAD",
            "PYTHONHOME",
            "PYTHONPATH",
            "_MEIPASS",
            "_MEIPASS2",
        ):
            env.pop(key, None)
        return env

    def _run_git(self, args: list[str], cwd: Path | None = None) -> str:
        """跑 git 命令，捕获 stdout+stderr，超时/失败抛 RuntimeError。"""
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT,
                check=False,
                env=self._clean_env(),
            )
        except FileNotFoundError as e:
            raise RuntimeError("系统未安装 git，请先 sudo pacman -S git") from e
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"git 操作超时（{GIT_TIMEOUT}s），可能网络不通"
            ) from e
        if result.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} 失败:\n{result.stderr.strip() or result.stdout.strip()}"
            )
        return result.stdout

    def _find_system_python(self) -> str | None:
        """找一个系统 Python 来跑 pip（避免用 Decky bundled 的、可能没 pip 的解释器）。"""
        for candidate in ("/usr/bin/python3", "/usr/bin/python", "python3", "python"):
            try:
                result = subprocess.run(
                    [candidate, "-c", "import pip; print(pip.__version__)"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    env=self._clean_env(),
                )
                if result.returncode == 0:
                    return candidate
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        return None

    def _install_python_deps(self) -> dict[str, Any]:
        """把 requirements.txt 装到 runtime/.vendor 里，runtime 启动时会 sys.path 这里。

        失败不抛——返回 {ok: false, error: ...} 以便用户能看到 runtime 已安装
        但缺依赖的状态，并手动重试。
        """
        req_file = self.runtime_dir / "requirements.txt"
        if not req_file.exists():
            return {"ok": True, "skipped": "no_requirements"}

        vendor = self.runtime_dir / VENDOR_DIR_NAME
        python = self._find_system_python()
        if python is None:
            return {
                "ok": False,
                "error": "未找到系统 Python（带 pip）。请在 Konsole 执行："
                f" python3 -m pip install --target {vendor} -r {req_file}",
            }

        try:
            result = subprocess.run(
                [
                    python, "-m", "pip", "install",
                    "--target", str(vendor),
                    "--upgrade",
                    "-r", str(req_file),
                ],
                capture_output=True,
                text=True,
                timeout=PIP_TIMEOUT,
                env=self._clean_env(),
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"pip install 超时（{PIP_TIMEOUT}s）"}

        if result.returncode != 0:
            return {
                "ok": False,
                "error": f"pip install 失败:\n{result.stderr.strip() or result.stdout.strip()}",
            }
        return {"ok": True, "vendor": str(vendor), "python": python}

    def install(self) -> dict[str, Any]:
        """首次安装 (git clone) 或更新 (git pull)。"""
        parent = self.runtime_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        git_dir = self.runtime_dir / ".git"

        if self.runtime_dir.exists() and git_dir.exists():
            # 已是 git 仓库 → pull 更新
            action = "pulled"
            self._run_git(["fetch", "origin", self.branch], cwd=self.runtime_dir)
            self._run_git(["reset", "--hard", f"origin/{self.branch}"], cwd=self.runtime_dir)
        else:
            # 目录已存在但不是 git 仓库 → 备份再 clone
            if self.runtime_dir.exists():
                backup = self.runtime_dir.with_suffix(".bak")
                if backup.exists():
                    shutil.rmtree(backup)
                self.runtime_dir.rename(backup)
            action = "cloned"
            self._run_git(
                [
                    "clone",
                    "--depth", "1",
                    "--branch", self.branch,
                    self.repo_url,
                    str(self.runtime_dir),
                ]
            )

        # git clone / pull 完成后，安装 Python 依赖到 runtime/.vendor
        deps_result = self._install_python_deps()

        commit = self._git_commit() or "unknown"
        manifest = {
            "version": commit,
            "source": self.repo_url,
            "branch": self.branch,
            "action": action,
            "deps": deps_result,
        }
        self.manifest_path.write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        return {
            "ok": True,
            "installed": True,
            "action": action,
            "runtime_dir": str(self.runtime_dir),
            "commit": commit,
            "branch": self.branch,
        }

    async def install_async(self) -> dict[str, Any]:
        """从 async 上下文安全调用，不阻塞 Decky 事件循环。"""
        try:
            return await asyncio.to_thread(self.install)
        except Exception as e:
            return {
                "ok": False,
                "installed": (self.runtime_dir / "main.py").exists(),
                "error": str(e),
                "repo_url": self.repo_url,
                "branch": self.branch,
            }


INSTALLER = RuntimeInstaller()
