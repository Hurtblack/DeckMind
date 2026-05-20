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
import threading
import time
from pathlib import Path
from typing import Any

GIT_TIMEOUT = 120  # 秒，单次 git 操作超时
GIT_RETRIES = 4  # git 网络错误重试次数（Deck 访问 GitHub 不稳定）
PIP_TIMEOUT = 300  # 秒，pip install 超时（首次装 openai 等较慢）
VENDOR_DIR_NAME = ".vendor"  # runtime 内放第三方依赖的子目录


DEFAULT_RUNTIME_REPO = "https://github.com/Hurtblack/DeckMind.git"
DEFAULT_BRANCH = "main"


def _deck_user_home() -> Path:
    """deck 用户的 home 目录（即使当前进程以 root 运行）。

    Decky Loader 注入 DECKY_USER_HOME 环境变量，其值始终为 /home/deck；
    没有时回退到 Path.home()（本地开发/测试场景）。
    """
    env = os.environ.get("DECKY_USER_HOME")
    if env:
        return Path(env)
    return Path.home()


def _deck_user() -> str:
    """deck 用户名。"""
    return os.environ.get("DECKY_USER") or "deck"


def _xdg_dir(env_var: str, default_subpath: str) -> Path:
    """遵循 XDG Base Directory 规范解析路径，支持环境变量覆盖。"""
    base = os.environ.get(env_var)
    if base:
        return Path(base).expanduser()
    return _deck_user_home() / default_subpath


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
        # Progress events — install() runs on a worker thread, UI polls
        # from the asyncio loop, so all access goes through the lock.
        self._events_lock = threading.Lock()
        self._events: list[dict[str, Any]] = []
        self._install_running = False

    def _emit(self, stage: str, status: str, message: str = "",
              extra: dict[str, Any] | None = None) -> None:
        """Append a progress event the UI can poll.

        status conventions: "start" | "ok" | "fail" | "skip" | "info".
        """
        event: dict[str, Any] = {
            "ts": time.time(), "stage": stage, "status": status,
            "message": message,
        }
        if extra:
            event["extra"] = extra
        with self._events_lock:
            self._events.append(event)

    def _reset_progress(self) -> None:
        with self._events_lock:
            self._events = []
            self._install_running = True

    def _finish_progress(self) -> None:
        with self._events_lock:
            self._install_running = False

    def get_progress(self, since: int = 0) -> dict[str, Any]:
        """Return events with index >= `since`, plus the new cursor."""
        with self._events_lock:
            return {
                "events": list(self._events[since:]),
                "total": len(self._events),
                "running": self._install_running,
            }

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

    def _fix_permissions(self) -> None:
        """将 runtime + cache 目录归属修正为 deck 用户。

        当 Decky Loader (systemd, root) 拉起的 plugin 进程以 root 身份运行时，
        git clone / pip install 写出的文件 owner 是 root，导致 deck 用户后续
        rsync 部署或手动操作时 Permission denied。这里递归 chown 回 deck:deck。

        仅当当前进程是 root 且目标用户不是 root 时才做，普通用户运行则是 no-op。
        """
        if os.getuid() != 0:
            return
        try:
            import pwd
            target = _deck_user()
            pw = pwd.getpwnam(target)
            uid, gid = pw.pw_uid, pw.pw_gid
            if uid == 0:
                return  # 目标用户就是 root，不需要改
        except (KeyError, ImportError):
            return

        for _dir in (self.runtime_dir, self.cache_dir):
            if not _dir.exists():
                continue
            try:
                os.chown(str(_dir), uid, gid)
            except OSError:
                pass
            for root, dirs, files in os.walk(str(_dir)):
                for name in dirs + files:
                    try:
                        os.chown(os.path.join(root, name), uid, gid)
                    except OSError:
                        pass

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
        """跑 git 命令；网络类错误自动重试，超时/最终失败抛 RuntimeError。

        Deck 访问 GitHub 经常间歇性失败（SSL_ERROR_SYSCALL / Connection reset /
        timeout，尤其国内网络）。这里对网络错误重试 GIT_RETRIES 次，每次退避递增。
        """
        # 网络不稳时给 git 加点韧性
        git_env = self._clean_env()
        git_env.setdefault("GIT_HTTP_LOW_SPEED_LIMIT", "1000")
        git_env.setdefault("GIT_HTTP_LOW_SPEED_TIME", str(GIT_TIMEOUT))

        last_err = ""
        for attempt in range(1, GIT_RETRIES + 1):
            try:
                result = subprocess.run(
                    ["git", "-c", "http.postBuffer=524288000", *args],
                    cwd=str(cwd) if cwd else None,
                    capture_output=True,
                    text=True,
                    timeout=GIT_TIMEOUT,
                    check=False,
                    env=git_env,
                )
            except FileNotFoundError as e:
                raise RuntimeError("系统未安装 git，请先 sudo pacman -S git") from e
            except subprocess.TimeoutExpired:
                last_err = f"git 操作超时（{GIT_TIMEOUT}s）"
                if attempt < GIT_RETRIES:
                    self._emit("git", "retry",
                               f"超时，重试 {attempt}/{GIT_RETRIES - 1}")
                    time.sleep(attempt * 2)
                    continue
                raise RuntimeError(f"{last_err}，已重试 {GIT_RETRIES} 次仍失败，网络不通")

            if result.returncode == 0:
                return result.stdout

            err = result.stderr.strip() or result.stdout.strip()
            last_err = err
            # 判断是否网络类错误（值得重试）
            transient = any(
                kw in err
                for kw in (
                    "SSL_ERROR_SYSCALL", "Connection reset", "Could not resolve",
                    "Connection timed out", "unable to access", "Recv failure",
                    "TLS", "GnuTLS", "early EOF", "RPC failed", "fetch-pack",
                )
            )
            if transient and attempt < GIT_RETRIES:
                self._emit("git", "retry",
                           f"网络错误，重试 {attempt}/{GIT_RETRIES - 1}")
                time.sleep(attempt * 2)
                continue
            raise RuntimeError(
                f"git {' '.join(args)} 失败"
                + (f"（已重试 {GIT_RETRIES} 次）" if transient else "")
                + f":\n{err}"
            )

        raise RuntimeError(f"git {' '.join(args)} 失败:\n{last_err}")

    def _decky_python_version(self) -> tuple[int, int]:
        """Decky 内置 Python 的 (major, minor)。

        installer.py 在 Decky 插件后端里被加载，所以 sys.version_info 就是
        Decky 自带的 PyInstaller Python 版本（典型为 3.11）。
        """
        v = sys.version_info
        return v.major, v.minor

    def _probe_python(self, candidate: str) -> tuple[int, int] | None:
        """返回 candidate 的 (major, minor)；不存在/不可执行返回 None。"""
        try:
            result = subprocess.run(
                [candidate, "-c",
                 "import sys; print(f'{sys.version_info[0]} {sys.version_info[1]}')"],
                capture_output=True,
                text=True,
                timeout=10,
                env=self._clean_env(),
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        try:
            major_str, minor_str = result.stdout.strip().split()
            return int(major_str), int(minor_str)
        except (ValueError, IndexError):
            return None

    def _find_matching_python(self, target: tuple[int, int]) -> str | None:
        """找一个版本号与 Decky 一致的系统 Python。"""
        major, minor = target
        for candidate in (
            f"/usr/bin/python{major}.{minor}",
            f"/usr/local/bin/python{major}.{minor}",
            f"python{major}.{minor}",
        ):
            if self._probe_python(candidate) == target:
                return candidate
        return None

    def _find_system_python(self) -> str | None:
        """找任意一个可用的系统 Python（用于 pip 跨版本下载）。"""
        for candidate in ("/usr/bin/python3", "/usr/bin/python", "python3", "python"):
            if self._probe_python(candidate) is not None:
                return candidate
        return None

    def _pip_install_to_vendor(
        self,
        pip_python: str,
        vendor: Path,
        req_file: Path,
        *,
        target_version: tuple[int, int] | None = None,
    ) -> tuple[bool, str]:
        """用指定 Python 跑 pip install --target。

        当 `target_version` 给定且与 `pip_python` 自身版本不一致时，附加
        `--python-version` / `--abi` / `--only-binary` 让 pip 下载与目标
        Python 兼容的 wheel —— 这是修复"系统装的是 3.13，但 Decky 是
        3.11，pydantic_core 的 .so 不兼容"的关键。
        """
        cmd = [
            pip_python, "-m", "pip", "install",
            "--target", str(vendor),
            "--upgrade",
            "-r", str(req_file),
        ]
        if target_version is not None:
            pip_self = self._probe_python(pip_python)
            if pip_self != target_version:
                major, minor = target_version
                # 跨版本下载的黄金组合（实测可用）：
                #   --python-version + --platform + --only-binary
                # - --platform 必须给：否则 pip 跨版本时选不到 pydantic_core 的
                #   manylinux wheel（C 扩展），导致 install 失败
                # - --abi 不能给：会拒绝 openai 的纯 Python 依赖
                #   (certifi/idna/sniffio/anyio/h11 是 py3-none-any，abi=none)
                cmd[3:3] = [
                    "--python-version", f"{major}.{minor}",
                    "--platform", "manylinux2014_x86_64",
                    "--only-binary", ":all:",
                ]
        try:
            result = subprocess.run(
                cmd,
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
        """把 requirements.txt 装到 runtime/.vendor，全自动选对 wheel。

        关键约束：装出来的 .so 文件必须匹配 Decky 自带 Python 的 ABI。
        Decky 通常打包 cpython-3.11，但 SteamOS 系统 Python 可能是 3.13，
        直接用系统 pip 装 pydantic_core 会生成 .cpython-313-*.so，
        Decky 3.11 加载时报 `ModuleNotFoundError: No module named
        'pydantic_core._pydantic_core'`。

        策略（每步失败自动回退到下一步，返回结构化日志方便排错）：

          A. 系统装了与 Decky 同版本的 Python（如 /usr/bin/python3.11）
             → 用它的 pip --target，ABI 天然匹配
          B. 没同版本，但任何系统 Python 都行 → 用 pip 的跨版本能力
             (--python-version / --abi / --only-binary :all:) 下载匹配 wheel
          C. 系统 pip 被 PEP 668 锁 → 在 venv 里跑同样的 pip 命令
          D. 所有路径都失败 → 返回 ok=false + 完整 pip 输出，前端直接显示
        """
        req_file = self.runtime_dir / "requirements.txt"
        if not req_file.exists():
            return {"ok": True, "skipped": "no_requirements"}

        vendor = self.runtime_dir / VENDOR_DIR_NAME
        decky_ver = self._decky_python_version()
        decky_ver_str = f"{decky_ver[0]}.{decky_ver[1]}"

        attempts: list[dict[str, Any]] = []
        self._emit("deps", "start",
                   f"安装依赖到 .vendor (目标 Python {decky_ver_str})")

        def attempt(via: str, ok: bool, msg: str, extra: dict[str, Any] | None = None) -> None:
            entry: dict[str, Any] = {"via": via, "ok": ok}
            if msg:
                entry["log_tail"] = msg[-2000:]  # cap log size in manifest
            if extra:
                entry.update(extra)
            attempts.append(entry)
            self._emit(
                f"deps.{via}",
                "ok" if ok else "fail",
                "" if ok else msg.splitlines()[-1][:200] if msg else "",
            )

        # ---------- Strategy A: matching system Python ----------
        matched = self._find_matching_python(decky_ver)
        if matched:
            self._emit("deps.A", "try",
                       f"找到系统 Python {decky_ver_str}: {matched}")
            ok, msg = self._pip_install_to_vendor(matched, vendor, req_file)
            attempt(f"system_python{decky_ver_str}", ok, msg, {"python": matched})
            if ok:
                return {"ok": True, "vendor": str(vendor),
                        "via": f"system_python{decky_ver_str}",
                        "decky_python": decky_ver_str,
                        "attempts": attempts}
        else:
            self._emit("deps.A", "skip",
                       f"系统未安装 python{decky_ver_str}，走跨版本路径")

        # ---------- Strategy B/C: cross-version pip via any Python ----------
        any_python = self._find_system_python()
        if any_python is None:
            return {
                "ok": False,
                "decky_python": decky_ver_str,
                "attempts": attempts,
                "error": (
                    f"未找到任何系统 Python；Decky 需要 Python {decky_ver_str} 的依赖。\n"
                    f"建议: sudo pacman -S python"
                ),
            }

        any_ver = self._probe_python(any_python)
        any_ver_str = f"{any_ver[0]}.{any_ver[1]}" if any_ver else "?"

        # B: 直接调系统 pip + 跨版本下载
        self._emit("deps.B", "try",
                   f"用 {any_python} (Python {any_ver_str}) 下载 Python "
                   f"{decky_ver_str} 的预编译 wheel")
        ok, msg = self._pip_install_to_vendor(
            any_python, vendor, req_file, target_version=decky_ver,
        )
        attempt(f"cross_version_pip(host={any_ver_str},target={decky_ver_str})",
                ok, msg, {"python": any_python})
        if ok:
            return {"ok": True, "vendor": str(vendor),
                    "via": f"cross_version_pip_for_{decky_ver_str}",
                    "host_python": any_ver_str,
                    "decky_python": decky_ver_str,
                    "attempts": attempts}

        # C: 系统 pip 被 PEP 668 锁 → 走 venv
        pep668 = (
            "externally-managed-environment" in msg
            or "No module named pip" in msg
        )
        if pep668:
            self._emit("deps.C", "try",
                       "系统 pip 被 PEP 668 锁定，在 venv 内跨版本下载")
            venv_python, venv_log = self._ensure_venv_python(any_python)
            if venv_python is None:
                return {
                    "ok": False,
                    "decky_python": decky_ver_str,
                    "attempts": attempts,
                    "error": f"系统 pip 被 PEP 668 锁；venv 兜底也失败：{venv_log}",
                }
            ok, msg = self._pip_install_to_vendor(
                venv_python, vendor, req_file, target_version=decky_ver,
            )
            attempt(f"venv_cross_version(target={decky_ver_str})", ok, msg,
                    {"venv_python": venv_python, "venv_log": venv_log})
            if ok:
                return {"ok": True, "vendor": str(vendor),
                        "via": f"venv_cross_version_for_{decky_ver_str}",
                        "decky_python": decky_ver_str,
                        "venv_log": venv_log,
                        "attempts": attempts}

        # ---------- D: 全失败，返回完整诊断 ----------
        return {
            "ok": False,
            "decky_python": decky_ver_str,
            "vendor": str(vendor),
            "attempts": attempts,
            "error": (
                f"无法为 Decky Python {decky_ver_str} 安装依赖（所有降级路径均失败）。\n"
                f"手动修复:\n"
                f"  python{decky_ver_str} -m pip install --target {vendor} -r {req_file}\n"
                f"或:\n"
                f"  python3 -m pip install --target {vendor} \\\n"
                f"    --python-version {decky_ver_str} --platform manylinux2014_x86_64 \\\n"
                f"    --only-binary :all: --abi cp{decky_ver[0]}{decky_ver[1]} \\\n"
                f"    -r {req_file}\n"
                f"最后一次 pip 输出:\n{msg}"
            ),
        }

    def install(self) -> dict[str, Any]:
        """首次安装 (git clone) 或更新 (git pull)。"""
        parent = self.runtime_dir.parent
        parent.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        git_dir = self.runtime_dir / ".git"

        if self.runtime_dir.exists() and git_dir.exists():
            action = "pulled"
            self._emit("git", "start", f"git pull origin/{self.branch}")
            self._run_git(["fetch", "origin", self.branch], cwd=self.runtime_dir)
            self._run_git(["reset", "--hard", f"origin/{self.branch}"], cwd=self.runtime_dir)
            self._emit("git", "ok", "更新代码完成")
        else:
            if self.runtime_dir.exists():
                backup = self.runtime_dir.with_suffix(".bak")
                if backup.exists():
                    shutil.rmtree(backup)
                self.runtime_dir.rename(backup)
                self._emit("git", "info", f"非 git 目录已备份到 {backup.name}")
            action = "cloned"
            self._emit("git", "start", f"git clone {self.repo_url} ({self.branch})")
            self._run_git(
                [
                    "clone",
                    "--depth", "1",
                    "--branch", self.branch,
                    self.repo_url,
                    str(self.runtime_dir),
                ]
            )
            self._emit("git", "ok", "克隆代码完成")

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
        self._emit("manifest", "ok", f"已写入 {self.manifest_path.name}")

        self._fix_permissions()

        # 顺带把 plugin 本体（含 dist/index.js）同步到最新——
        # runtime 是整个仓库的 clone，含 decky-plugin/ 子目录。
        plugin_result = self._sync_plugin()

        return {
            "ok": True,
            "installed": True,
            "action": action,
            "runtime_dir": str(self.runtime_dir),
            "commit": commit,
            "branch": self.branch,
            "deps": deps_result,
            "plugin": plugin_result,
        }

    def _sync_plugin(self) -> dict[str, Any]:
        """把 runtime 仓库里的 decky-plugin/ 同步到当前 plugin 目录。

        runtime_dir 是整个 DeckMind 仓库的 git clone，其中包含 decky-plugin/
        子目录（即 plugin 本体，含构建好的 dist/index.js）。git pull 之后这里
        就是最新的 plugin 代码，复制过来即可让 plugin 自更新。

        注意：复制会覆盖正在运行的 installer.py/main.py，但 Linux 允许覆盖
        已加载的文件（旧 inode 保留），新代码在下次 Decky 重载 plugin 时生效。
        所以同步后需要用户在 Decky 重载 plugin（或重启 Steam）。
        """
        src = self.runtime_dir / "decky-plugin"
        dst = Path(__file__).resolve().parent  # 当前 plugin 目录

        if not src.exists():
            return {"ok": False, "skipped": "runtime 内无 decky-plugin 目录"}
        if src.resolve() == dst.resolve():
            return {"ok": True, "skipped": "plugin 目录与源相同，无需同步"}

        # 只同步运行所需文件，跳过开发用目录
        skip_dirs = {"node_modules", "src", "scripts", "__pycache__", ".git"}
        skip_files = {"tsconfig.json", "rollup.config.js", "pnpm-lock.yaml",
                      "package-lock.json", ".gitignore"}

        copied: list[str] = []
        try:
            for root, dirs, files in os.walk(src):
                dirs[:] = [d for d in dirs if d not in skip_dirs]
                rel = Path(root).relative_to(src)
                target_dir = dst / rel
                target_dir.mkdir(parents=True, exist_ok=True)
                for name in files:
                    if name in skip_files:
                        continue
                    shutil.copy2(Path(root) / name, target_dir / name)
                    copied.append(str((rel / name)))
        except OSError as e:
            return {"ok": False, "error": f"同步 plugin 失败: {e}",
                    "copied": copied}

        self._emit("plugin", "ok",
                   f"已同步 plugin 本体（{len(copied)} 个文件），"
                   f"请在 Decky 重载插件或重启 Steam 生效")
        return {
            "ok": True,
            "plugin_dir": str(dst),
            "files": len(copied),
            "note": "plugin 已更新，需在 Decky 重载插件 / 重启 Steam 生效",
        }

    async def install_async(self) -> dict[str, Any]:
        """从 async 上下文安全调用，不阻塞 Decky 事件循环。

        包了 progress buffer 的 reset/finish，并把最终结果也作为事件
        emit 出来，前端轮询时拿到的最后一条就是终态。
        """
        self._reset_progress()
        self._emit("install", "start", "开始安装 Runtime")
        try:
            result = await asyncio.to_thread(self.install)
        except Exception as e:
            err_msg = str(e)
            self._emit("install", "fail", err_msg)
            self._finish_progress()
            return {
                "ok": False,
                "installed": (self.runtime_dir / "main.py").exists(),
                "error": err_msg,
                "repo_url": self.repo_url,
                "branch": self.branch,
            }
        # deps 阶段失败时 install() 仍返回 ok=True（外壳成功，依赖没成）
        deps = result.get("deps") or {}
        if not deps.get("ok", True):
            self._emit("install", "fail",
                       f"依赖安装失败：{deps.get('error', '')[:200]}")
        else:
            self._emit("install", "ok",
                       f"安装完成 (commit {result.get('commit', '?')})")
        self._finish_progress()
        return result


INSTALLER = RuntimeInstaller()
