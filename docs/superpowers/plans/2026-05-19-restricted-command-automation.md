# Restricted Command Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 DeckMind 增加受限 `run_command` 工具，让用户授权后即可自动执行安全白名单命令，减少手动输入终端命令。

**Architecture:** 新增 `tools/command_tool.py`，把命令校验、dry-run 预览和 subprocess 执行放在一个聚焦模块内。校验逻辑与执行逻辑分离，单元测试主要覆盖校验器；工具注册、Executor 风险分级和系统提示词只做接入层更新。

**Tech Stack:** Python 3.11+、标准库 `asyncio` / `pathlib` / `urllib.parse` / `unittest`，现有 `ToolSpec` 工具注册体系。

---

## 文件结构

- Create: `tools/command_tool.py`
  - 负责 `run_command(argv, confirm=False)`。
  - 内部包含 allowlist 校验、路径校验、URL 校验、dry-run payload 和实际执行。
  - 不使用 `shell=True`，只使用 `asyncio.create_subprocess_exec(*argv)`。
- Create: `tests/__init__.py`
  - 让 `tests` 可被 `python -m unittest` 发现。
- Create: `tests/test_command_tool.py`
  - 覆盖白名单命令、拒绝规则和 dry-run 行为。
  - 不依赖网络，不下载真实文件。
- Modify: `tools/__init__.py`
  - 导入 `command_tool`。
  - 注册 `run_command` 的 `ToolSpec`。
- Modify: `runtime/executor.py`
  - 将 `run_command` 加入 `RISK_DESTRUCTIVE`。
- Modify: `prompts/system_prompt.txt`
  - 告诉模型优先使用专用工具。
  - 没有专用工具时，用 `run_command` 做小型用户级自动化。
  - 禁止把 `run_command` 用于任意 shell、sudo、pacman、凭据或系统级变更。

## Task 1: 新增命令校验器测试

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_command_tool.py`

- [ ] **Step 1: 写失败测试**

Create `tests/__init__.py` as an empty file.

Create `tests/test_command_tool.py`:

```python
from __future__ import annotations

import unittest

from tools.command_tool import validate_command


class CommandToolValidationTests(unittest.TestCase):
    def test_allows_curl_download_to_downloads(self) -> None:
        result = validate_command([
            "curl",
            "-L",
            "-o",
            "~/Downloads/Clash.Verge.AppImage",
            "https://example.com/Clash.Verge.AppImage",
        ])

        self.assertTrue(result.ok)
        self.assertEqual(result.command, "curl")
        self.assertFalse(result.read_only)

    def test_allows_curl_header_check(self) -> None:
        result = validate_command([
            "curl",
            "-L",
            "-I",
            "https://example.com/Clash.Verge.AppImage",
        ])

        self.assertTrue(result.ok)
        self.assertTrue(result.read_only)

    def test_rejects_shell_compound_command(self) -> None:
        result = validate_command([
            "curl",
            "-L",
            "-o",
            "~/Downloads/app",
            "https://example.com/app",
            "&&",
            "chmod",
            "+x",
            "~/Downloads/app",
        ])

        self.assertFalse(result.ok)
        self.assertIn("shell metacharacter", result.reason or "")

    def test_rejects_writes_outside_allowed_dirs(self) -> None:
        result = validate_command([
            "curl",
            "-L",
            "-o",
            "/tmp/app.AppImage",
            "https://example.com/app.AppImage",
        ])

        self.assertFalse(result.ok)
        self.assertIn("outside allowed write directories", result.reason or "")

    def test_rejects_sensitive_path_fragment(self) -> None:
        result = validate_command([
            "mkdir",
            "-p",
            "~/.deckmind/secret-token-store",
        ])

        self.assertFalse(result.ok)
        self.assertIn("sensitive path fragment", result.reason or "")

    def test_rejects_recursive_chmod(self) -> None:
        result = validate_command([
            "chmod",
            "-R",
            "+x",
            "~/Downloads/app.AppImage",
        ])

        self.assertFalse(result.ok)
        self.assertIn("only chmod +x", result.reason or "")

    def test_rejects_numeric_chmod(self) -> None:
        result = validate_command([
            "chmod",
            "777",
            "~/Downloads/app.AppImage",
        ])

        self.assertFalse(result.ok)
        self.assertIn("only chmod +x", result.reason or "")

    def test_rejects_system_systemctl(self) -> None:
        result = validate_command([
            "systemctl",
            "restart",
            "sshd.service",
        ])

        self.assertFalse(result.ok)
        self.assertIn("systemctl --user", result.reason or "")

    def test_allows_user_systemctl_status(self) -> None:
        result = validate_command([
            "systemctl",
            "--user",
            "status",
            "deckmind-agent.service",
        ])

        self.assertTrue(result.ok)
        self.assertTrue(result.read_only)

    def test_rejects_credential_like_url(self) -> None:
        result = validate_command([
            "curl",
            "-L",
            "-o",
            "~/Downloads/app.AppImage",
            "https://example.com/app.AppImage?token=abc",
        ])

        self.assertFalse(result.ok)
        self.assertIn("credential-like URL parameter", result.reason or "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
python -m unittest tests.test_command_tool -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'tools.command_tool'`.

- [ ] **Step 3: Commit**

```bash
git add tests/__init__.py tests/test_command_tool.py
git commit -m "添加受限命令校验测试"
```

## Task 2: 实现命令校验器和 dry-run

**Files:**
- Create: `tools/command_tool.py`

- [ ] **Step 1: 写最小实现**

Create `tools/command_tool.py`:

```python
"""Restricted command execution tool.

This module intentionally does not expose a shell. It accepts argv only,
validates a small command allowlist, and uses subprocess exec directly.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse


_WRITE_BASES: tuple[str, ...] = (
    "~/Downloads",
    "~/.deckmind",
    "~/.local/share/applications",
    "~/.config/systemd/user",
    "~/.config/autostart",
    "~/Documents",
    "~/Desktop",
)

_READ_BASES: tuple[str, ...] = _WRITE_BASES + (
    "~/.config",
    "~/.local/share",
)

_SENSITIVE_FRAGMENTS: tuple[str, ...] = (
    "/.ssh",
    "/.gnupg",
    "/.aws",
    "/.docker",
    "/.kube",
    "password",
    "credential",
    "secret",
    "token",
    "id_rsa",
    "id_ed25519",
)

_SHELL_METACHARS: set[str] = {
    "|",
    "||",
    "&",
    "&&",
    ";",
    ">",
    ">>",
    "<",
    "$(",
    "`",
}

_URL_CREDENTIAL_KEYS: set[str] = {
    "token",
    "access_token",
    "key",
    "api_key",
    "secret",
}

_SIMPLE_NAME_RE = re.compile(r"^[A-Za-z0-9._+-]+$")
_UNIT_RE = re.compile(r"^[A-Za-z0-9_.@+-]+\\.service$")


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    argv: list[str]
    command: str | None = None
    reason: str | None = None
    read_only: bool = False
    output_path: str | None = None


def _expand(path: str) -> Path:
    return Path(os.path.expanduser(path)).absolute()


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _has_sensitive_fragment(path: Path | str) -> bool:
    lower = str(path).lower()
    return any(fragment in lower for fragment in _SENSITIVE_FRAGMENTS)


def _validate_path(path: str, *, for_write: bool, must_exist_for_mutation: bool = False) -> tuple[Path | None, str | None]:
    resolved = _expand(path)
    if _has_sensitive_fragment(resolved):
        return None, "path contains sensitive path fragment"

    bases = _WRITE_BASES if for_write else _READ_BASES
    allowed = [_expand(base) for base in bases]
    if not any(resolved == base or _is_within(resolved, base) for base in allowed):
        kind = "write" if for_write else "read"
        return None, f"path is outside allowed {kind} directories"

    if resolved.is_symlink():
        return None, "refusing to operate on symlink path"
    if must_exist_for_mutation and not resolved.is_file():
        return None, "target must be an existing regular file"

    return resolved, None


def _validate_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "URL must use http or https"
    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in _URL_CREDENTIAL_KEYS:
            return "refusing credential-like URL parameter"
    return None


def _contains_shell_metachar(argv: list[str]) -> bool:
    return any(arg in _SHELL_METACHARS or "$(" in arg or "`" in arg for arg in argv)


def validate_command(argv: list[str]) -> ValidationResult:
    args = [str(arg) for arg in (argv or [])]
    if not args:
        return ValidationResult(False, args, reason="empty argv")
    if _contains_shell_metachar(args):
        return ValidationResult(False, args, command=args[0], reason="shell metacharacter is not allowed")

    command = args[0]
    if "/" in command:
        return ValidationResult(False, args, command=command, reason="command must be an allowlisted executable name")

    if command == "curl":
        return _validate_curl(args)
    if command == "wget":
        return _validate_wget(args)
    if command == "chmod":
        return _validate_chmod(args)
    if command == "mkdir":
        return _validate_mkdir(args)
    if command == "file":
        return _validate_file(args)
    if command == "which":
        return _validate_which(args)
    if command == "systemctl":
        return _validate_systemctl(args)

    return ValidationResult(False, args, command=command, reason=f"command is not allowlisted: {command}")


def _validate_curl(args: list[str]) -> ValidationResult:
    if len(args) == 4 and args[1:3] == ["-L", "-I"]:
        err = _validate_url(args[3])
        return ValidationResult(err is None, args, "curl", err, read_only=True)
    if len(args) == 3 and args[1] == "-I":
        err = _validate_url(args[2])
        return ValidationResult(err is None, args, "curl", err, read_only=True)
    if len(args) == 5 and args[1] in {"-L", "-fL"} and args[2] == "-o":
        path, err = _validate_path(args[3], for_write=True)
        if err:
            return ValidationResult(False, args, "curl", err)
        url_err = _validate_url(args[4])
        if url_err:
            return ValidationResult(False, args, "curl", url_err)
        return ValidationResult(True, args, "curl", output_path=str(path))
    return ValidationResult(False, args, "curl", "unsupported curl form")


def _validate_wget(args: list[str]) -> ValidationResult:
    if len(args) == 4 and args[1] == "-O":
        path, err = _validate_path(args[2], for_write=True)
        if err:
            return ValidationResult(False, args, "wget", err)
        url_err = _validate_url(args[3])
        if url_err:
            return ValidationResult(False, args, "wget", url_err)
        return ValidationResult(True, args, "wget", output_path=str(path))
    return ValidationResult(False, args, "wget", "unsupported wget form")


def _validate_chmod(args: list[str]) -> ValidationResult:
    if len(args) != 3 or args[1] != "+x":
        return ValidationResult(False, args, "chmod", "only chmod +x is allowed")
    path, err = _validate_path(args[2], for_write=True, must_exist_for_mutation=True)
    if err:
        return ValidationResult(False, args, "chmod", err)
    return ValidationResult(True, args, "chmod", output_path=str(path))


def _validate_mkdir(args: list[str]) -> ValidationResult:
    if len(args) != 3 or args[1] != "-p":
        return ValidationResult(False, args, "mkdir", "only mkdir -p is allowed")
    path, err = _validate_path(args[2], for_write=True)
    if err:
        return ValidationResult(False, args, "mkdir", err)
    return ValidationResult(True, args, "mkdir", output_path=str(path))


def _validate_file(args: list[str]) -> ValidationResult:
    if len(args) != 2:
        return ValidationResult(False, args, "file", "only file <path> is allowed")
    path, err = _validate_path(args[1], for_write=False)
    if err:
        return ValidationResult(False, args, "file", err)
    return ValidationResult(True, args, "file", read_only=True)


def _validate_which(args: list[str]) -> ValidationResult:
    if len(args) != 2 or not _SIMPLE_NAME_RE.match(args[1]):
        return ValidationResult(False, args, "which", "which target must be a simple command name")
    return ValidationResult(True, args, "which", read_only=True)


def _validate_systemctl(args: list[str]) -> ValidationResult:
    if len(args) < 3 or args[1] != "--user":
        return ValidationResult(False, args, "systemctl", "only systemctl --user is allowed")
    action = args[2]
    if action == "daemon-reload" and len(args) == 3:
        return ValidationResult(True, args, "systemctl")
    if action in {"enable", "disable", "start", "stop", "status"} and len(args) == 4:
        if not _UNIT_RE.match(args[3]):
            return ValidationResult(False, args, "systemctl", "unit must be a simple .service name")
        return ValidationResult(True, args, "systemctl", read_only=(action == "status"))
    return ValidationResult(False, args, "systemctl", "unsupported systemctl --user form")


async def run_command(argv: list[str], confirm: bool = False) -> dict[str, Any]:
    validation = validate_command(argv)
    if not validation.ok:
        return {
            "ok": False,
            "refused": True,
            "reason": validation.reason,
            "argv": validation.argv,
        }

    if not confirm:
        return {
            "ok": True,
            "dry_run": True,
            "argv": validation.argv,
            "command": validation.command,
            "read_only": validation.read_only,
            "output_path": validation.output_path,
            "message": "Show this preview to the user and ask them to confirm, then call again with confirm=true.",
        }

    return await _execute_validated(validation)


async def _execute_validated(validation: ValidationResult) -> dict[str, Any]:
    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *validation.argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    elapsed = time.monotonic() - started
    output_size = None
    if validation.output_path:
        path = Path(validation.output_path)
        if path.exists() and path.is_file() and not path.is_symlink():
            output_size = path.stat().st_size

    return {
        "ok": (proc.returncode or 0) == 0,
        "argv": validation.argv,
        "command": validation.command,
        "returncode": proc.returncode or 0,
        "stdout_tail": out.decode(errors="ignore")[-800:],
        "stderr_tail": err.decode(errors="ignore")[-800:],
        "elapsed_seconds": round(elapsed, 2),
        "output_path": validation.output_path,
        "output_size_bytes": output_size,
    }
```

- [ ] **Step 2: 运行测试确认通过**

Run:

```bash
python -m unittest tests.test_command_tool -v
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tools/command_tool.py tests/test_command_tool.py
git commit -m "实现受限命令校验器"
```

## Task 3: 补充执行路径测试

**Files:**
- Modify: `tests/test_command_tool.py`

- [ ] **Step 1: 写执行路径测试**

Append to `CommandToolValidationTests` in `tests/test_command_tool.py`:

```python
    def test_run_command_dry_run_does_not_execute(self) -> None:
        import asyncio

        result = asyncio.run(validate_dry_run_for_test())

        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["command"], "which")


async def validate_dry_run_for_test() -> dict:
    from tools.command_tool import run_command

    return await run_command(["which", "sh"], confirm=False)
```

Add a second test for real execution:

```python
    def test_run_command_executes_harmless_which(self) -> None:
        import asyncio

        result = asyncio.run(execute_which_for_test())

        self.assertTrue(result["ok"])
        self.assertEqual(result["command"], "which")
        self.assertEqual(result["returncode"], 0)
        self.assertIn("sh", result["stdout_tail"])


async def execute_which_for_test() -> dict:
    from tools.command_tool import run_command

    return await run_command(["which", "sh"], confirm=True)
```

The helper functions must live above the `if __name__ == "__main__":` block.

- [ ] **Step 2: 运行测试确认失败或通过**

Run:

```bash
python -m unittest tests.test_command_tool -v
```

Expected: PASS if Task 2 already implemented `_execute_validated`; otherwise fail on missing execution behavior.

- [ ] **Step 3: 修正实现中的执行细节**

If the execution test fails because `which sh` has environment-specific output, keep the assertion broad:

```python
self.assertTrue(result["stdout_tail"].strip())
```

If the test fails because `proc.returncode` is `None`, keep this returncode expression in `tools/command_tool.py`:

```python
"returncode": proc.returncode or 0,
```

- [ ] **Step 4: 重新运行测试**

Run:

```bash
python -m unittest tests.test_command_tool -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/command_tool.py tests/test_command_tool.py
git commit -m "验证受限命令执行路径"
```

## Task 4: 接入工具注册表和 Executor

**Files:**
- Modify: `tools/__init__.py`
- Modify: `runtime/executor.py`

- [ ] **Step 1: 写注册表验证测试**

Append this test class to `tests/test_command_tool.py`:

```python
class CommandToolRegistryTests(unittest.TestCase):
    def test_run_command_is_registered(self) -> None:
        from tools import get, specs

        self.assertIsNotNone(get("run_command"))
        names = {spec.name for spec in specs()}
        self.assertIn("run_command", names)
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
python -m unittest tests.test_command_tool -v
```

Expected: FAIL because `run_command` is not registered.

- [ ] **Step 3: 修改 `tools/__init__.py` 导入**

Change the import block in `tools/__init__.py` from:

```python
from . import (
    file_tool, file_write_tool, macro_tool, notion_tool, package_tool,
    pacman_tool, profile_tool, steam_tool, steamos_lock as steamos_lock_tool,
    system_tool, update_tool,
)
```

to:

```python
from . import (
    command_tool, file_tool, file_write_tool, macro_tool, notion_tool,
    package_tool, pacman_tool, profile_tool, steam_tool,
    steamos_lock as steamos_lock_tool, system_tool, update_tool,
)
```

- [ ] **Step 4: 在 `TOOLS` 中注册 `run_command`**

Add this entry near the filesystem tools in `tools/__init__.py`:

```python
    "run_command": (
        command_tool.run_command,
        ToolSpec(
            name="run_command",
            description=(
                "Run a restricted allowlisted user-level command. "
                "DESTRUCTIVE — call first with confirm=false for a dry-run "
                "preview, then with confirm=true after the user explicitly "
                "approves. Does not use a shell. Allowed command families "
                "include curl/wget downloads to approved user directories, "
                "chmod +x on approved files, mkdir -p in approved directories, "
                "file/which read-only checks, and systemctl --user for simple "
                "user service actions. Never use for sudo, pacman, arbitrary "
                "shell, credentials, system-level systemctl, pipes, redirects, "
                "or compound commands."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Command argv, e.g. ['which', 'sh']",
                    },
                    "confirm": {"type": "boolean", "default": False},
                },
                "required": ["argv"],
            },
        ),
    ),
```

- [ ] **Step 5: 将 `run_command` 加入 destructive 风险**

In `runtime/executor.py`, add `"run_command"` to `RISK_DESTRUCTIVE`:

```python
RISK_DESTRUCTIVE: set[str] = {
    "install_game",
    "uninstall_game",
    "install_flatpak",
    "uninstall_flatpak",
    "apply_update",
    "write_text_file",
    "pacman_install",
    "set_pacman_mirror_china",
    "run_command",
}
```

- [ ] **Step 6: 运行测试**

Run:

```bash
python -m unittest tests.test_command_tool -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add tools/__init__.py runtime/executor.py tests/test_command_tool.py
git commit -m "注册受限命令执行工具"
```

## Task 5: 更新系统提示词

**Files:**
- Modify: `prompts/system_prompt.txt`

- [ ] **Step 1: 更新 Filesys 工具说明**

In `prompts/system_prompt.txt`, replace the `Filesys:` category line:

```text
- Filesys:  find_files, list_processes, read_text_file, write_text_file
```

with:

```text
- Filesys:  find_files, list_processes, read_text_file, write_text_file,
            run_command
```

- [ ] **Step 2: 添加 `run_command` 使用规则**

After the `write_text_file` explanation in `prompts/system_prompt.txt`, add:

```text
             Use run_command only when no dedicated tool covers a small
             user-level command workflow. It is restricted: no shell, no
             sudo, no pacman, no system-level systemctl, no pipes, no
             redirects, no compound commands, no credential handling.
             Prefer dedicated tools first: install_flatpak for Flatpak,
             pacman_install for pacman, write_text_file for text writes.
             If run_command can safely execute a needed command after
             permission, do not ask the user to manually type that command.
             Typical allowed flows: curl/wget download to ~/Downloads,
             chmod +x an approved downloaded file, mkdir -p approved user
             dirs, file/which checks, systemctl --user service actions.
             Like other destructive tools, call run_command with
             confirm=false first, summarize the preview, then call with
             confirm=true only after the user approves.
```

- [ ] **Step 3: 添加下载场景指引**

Add this paragraph near the autostart guidance or after it:

```text
When the user asks to download an AppImage or similar user-space binary:
  1. Prefer official/specific URLs provided by the user or discovered from
     existing context. If the URL is unknown, ask for it instead of guessing.
  2. Use run_command(['curl','-L','-o','~/Downloads/<name>',url],
     confirm=false) to preview.
  3. After approval, execute with confirm=true.
  4. Check the result size from tool output. If it is suspiciously tiny,
     tell the user the download likely failed.
  5. Use run_command(['chmod','+x','~/Downloads/<name>'], confirm=false)
     and then confirm=true after approval or session allow-all.
```

- [ ] **Step 4: 运行测试**

Run:

```bash
python -m unittest tests.test_command_tool -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add prompts/system_prompt.txt
git commit -m "更新受限命令工具提示词"
```

## Task 6: 端到端手工验证

**Files:**
- No new files expected.

- [ ] **Step 1: 验证 dry-run 工具调用**

Run a direct Python snippet:

```bash
python - <<'PY'
import asyncio
from tools.command_tool import run_command

async def main():
    result = await run_command(["which", "sh"], confirm=False)
    print(result)

asyncio.run(main())
PY
```

Expected: output contains:

```text
'ok': True
'dry_run': True
'command': 'which'
```

- [ ] **Step 2: 验证实际执行工具调用**

Run:

```bash
python - <<'PY'
import asyncio
from tools.command_tool import run_command

async def main():
    result = await run_command(["which", "sh"], confirm=True)
    print(result)

asyncio.run(main())
PY
```

Expected: output contains:

```text
'ok': True
'returncode': 0
'stdout_tail':
```

- [ ] **Step 3: 验证拒绝危险命令**

Run:

```bash
python - <<'PY'
import asyncio
from tools.command_tool import run_command

async def main():
    result = await run_command(["sh", "-c", "echo unsafe"], confirm=True)
    print(result)

asyncio.run(main())
PY
```

Expected: output contains:

```text
'ok': False
'refused': True
```

- [ ] **Step 4: 运行完整测试**

Run:

```bash
python -m unittest discover -v
```

Expected: all tests PASS.

- [ ] **Step 5: 查看工作区状态**

Run:

```bash
git status --short
```

Expected: no uncommitted changes.

## Self-Review

- Spec coverage:
  - `run_command` 工具：Task 2。
  - 命令白名单：Task 1、Task 2。
  - 路径策略和敏感路径拒绝：Task 1、Task 2。
  - Executor destructive 风险分级：Task 4。
  - Prompt 更新：Task 5。
  - Clash Verge 下载流程：Task 5。
  - 测试要求：Task 1、Task 3、Task 4、Task 6。
- Placeholder scan:
  - 本计划不包含占位实现或未定义函数。
- Type consistency:
  - 工具函数名统一为 `run_command(argv: list[str], confirm: bool = False)`。
  - 校验函数名统一为 `validate_command(argv: list[str])`。
  - 校验返回类型统一为 `ValidationResult`。
