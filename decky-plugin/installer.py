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
        """找一个可用的系统 Python（能 import sys 即可，不要求 pip）。"""
        for candidate in ("/usr/bin/python3", "/usr/bin/python", "python3", "python"):
            try:
                result = subprocess.run(
                    [candidate, "-c", "import sys; print(sys.version_info[:2])"],
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

    def _pip_install_to_vendor(
        self,
        pip_python: str,
        vendor: Path,
        req_file: Path,
    ) -> tuple[bool, str]:
        """用指定 Python 跑 pip install --target，返回 (ok, stderr/output)。"""
        try:
            result = subprocess.run(
                [
                    pip_python, "-m", "pip", "install",
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
            return False, f"pip install 超时（{PIP_TIMEOUT}s）"
        if result.returncode != 0:
            return False, (result.stderr.strip() or result.stdout.strip())
        return True, result.stdout

    def _ensure_venv_python(self, system_python: str) -> tuple[str | None, str]:
        """创建/复用 venv，返回 (venv 内的 python 路径, 日志)。

        SteamOS 锁了系统 pip (PEP 668)，但允许 venv —— venv 内部的 pip 不受限。
        venv 位置：~/.cache/deckmind/venv，所有 DeckMind plugin 共用一个。
        """
        venv_dir = self.cache_dir / "venv"
        venv_python = venv_dir / "bin" / "python"

        if venv_python.exists():
            return str(venv_python), "复用已有 venv"

        try:
            result = subprocess.run(
                [system_python, "-m", "venv", str(venv_dir)],
                capture_output=True,
                text=True,
                timeout=60,
                env=self._clean_env(),
            )
        except subprocess.TimeoutExpired:
            return None, "创建 venv 超时"
        if result.returncode != 0:
            return None, f"创建 venv 失败:\n{result.stderr.strip()}"

        if not venv_python.exists():
            return None, f"venv 创建后未找到 python 可执行文件：{venv_python}"

        return str(venv_python), "新建 venv"

    def _copy_site_packages_to_vendor(
        self,
        venv_python_path: str,
        vendor: Path,
    ) -> tuple[bool, str]:
        """把 venv 的 site-packages 内容平铺复制到 vendor 目录。

        Decky plugin 用的是 Decky 内置 Python，无法直接用 venv，
        所以必须把 venv 装好的包搬到 vendor，让 runtime 通过 sys.path 找到。
        """
        venv_python = Path(venv_python_path)
        # venv 结构: <venv>/lib/python3.x/site-packages
        lib_dir = venv_python.parent.parent / "lib"
        if not lib_dir.exists():
            return False, f"venv 缺 lib 目录：{lib_dir}"

        site_packages = None
        for py_dir in lib_dir.glob("python*"):
            candidate = py_dir / "site-packages"
            if candidate.exists():
                site_packages = candidate
                break

        if site_packages is None:
            return False, f"venv 内未找到 site-packages：{lib_dir}"

        vendor.mkdir(parents=True, exist_ok=True)
        # 复制 venv site-packages 的所有内容到 vendor
        for item in site_packages.iterdir():
            target = vendor / item.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)
        return True, f"已复制 site-packages → {vendor}"

    def _install_python_deps(self) -> dict[str, Any]:
        """把 requirements.txt 装到 runtime/.vendor 里。

        降级策略：
        1. 直接用系统 Python 的 pip（旧 SteamOS / 其它发行版可用）
        2. 用系统 Python 建 venv，再用 venv 的 pip（SteamOS 3.7+ PEP 668 锁了系统 pip）
        3. 都失败：返回错误，提示用户手动执行

        失败不抛异常，返回 {ok: false, error: ...} 让 UI 显示。
        """
        req_file = self.runtime_dir / "requirements.txt"
        if not req_file.exists():
            return {"ok": True, "skipped": "no_requirements"}

        vendor = self.runtime_dir / VENDOR_DIR_NAME
        system_python = self._find_system_python()
        if system_python is None:
            return {
                "ok": False,
                "error": "未找到系统 Python（/usr/bin/python3 不可用）",
            }

        # 第 1 路：试系统 pip 直接装
        ok, msg = self._pip_install_to_vendor(system_python, vendor, req_file)
        if ok:
            return {"ok": True, "vendor": str(vendor), "via": "system_pip"}

        # 系统 pip 被 PEP 668 拦截 / 不存在 → 走 venv 兜底
        pep668 = "externally-managed-environment" in msg or "No module named pip" in msg
        if not pep668:
            # 既不是 PEP 668 也不是缺 pip，可能是网络/源问题，直接抛
            return {"ok": False, "error": f"系统 pip 安装失败:\n{msg}"}

        # 第 2 路：建 venv 装到 venv，然后复制到 vendor
        venv_python, venv_log = self._ensure_venv_python(system_python)
        if venv_python is None:
            return {
                "ok": False,
                "error": f"系统 pip 不可用（PEP 668）；venv 兜底也失败：{venv_log}",
            }

        ok, msg = self._pip_install_to_vendor(venv_python, vendor, req_file)
        if ok:
            return {"ok": True, "vendor": str(vendor), "via": "venv", "venv_log": venv_log}

        # 第 2.5 路：pip 装到 venv 自身，再 copy site-packages
        # （某些环境 --target 会被 PEP 668 拦截，但装到 venv 默认位置可以）
        try:
            r = subprocess.run(
                [venv_python, "-m", "pip", "install", "--upgrade", "-r", str(req_file)],
                capture_output=True,
                text=True,
                timeout=PIP_TIMEOUT,
                env=self._clean_env(),
            )
            if r.returncode != 0:
                return {
                    "ok": False,
                    "error": f"venv pip 安装也失败:\n{r.stderr.strip() or r.stdout.strip()}",
                }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"venv pip 安装超时（{PIP_TIMEOUT}s）"}

        copied, copy_msg = self._copy_site_packages_to_vendor(venv_python, vendor)
        if not copied:
            return {"ok": False, "error": f"venv 装好后复制失败：{copy_msg}"}
        return {"ok": True, "vendor": str(vendor), "via": "venv+copy", "venv_log": venv_log}
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
