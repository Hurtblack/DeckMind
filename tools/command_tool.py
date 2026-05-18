"""Restricted command execution with validation and dry-run support."""

from __future__ import annotations

import asyncio
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse


@dataclass
class ValidationResult:
    ok: bool
    argv: list[str]
    command: str | None = None
    reason: str | None = None
    read_only: bool = False
    output_path: str | None = None


_APPROVED_WRITE_DIRS: tuple[str, ...] = (
    "~/Downloads",
    "~/.deckmind",
    "~/.local/share/applications",
    "~/.config/systemd/user",
    "~/.config/autostart",
    "~/Documents",
    "~/Desktop",
)

_APPROVED_READ_DIRS: tuple[str, ...] = _APPROVED_WRITE_DIRS + (
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

_CREDENTIAL_QUERY_KEYS: set[str] = {
    "token",
    "access_token",
    "key",
    "api_key",
    "secret",
}

_SHELL_META_TOKENS: tuple[str, ...] = (
    "||",
    "&&",
    ">>",
    "$(",
    "|",
    "&",
    ";",
    ">",
    "<",
    "`",
    "$",
)

_SIMPLE_COMMAND_RE = re.compile(r"^[A-Za-z0-9._+-]+$")
_SYSTEMD_UNIT_RE = re.compile(r"^[A-Za-z0-9_.@-]+\.service$")
_TRUSTED_EXECUTABLE_DIRS: tuple[str, ...] = (
    "/usr/bin",
    "/bin",
    "/usr/local/bin",
    "/opt/homebrew/bin",
)
_TRUSTED_PATH = ":".join(_TRUSTED_EXECUTABLE_DIRS)


def _reject(argv: list[str], reason: str, command: str | None = None) -> ValidationResult:
    return ValidationResult(False, list(argv), command=command, reason=reason)


def _approved_dirs() -> tuple[Path, ...]:
    return tuple(Path(p).expanduser().resolve(strict=False) for p in _APPROVED_WRITE_DIRS)


def _approved_read_dirs() -> tuple[Path, ...]:
    return tuple(Path(p).expanduser().resolve(strict=False) for p in _APPROVED_READ_DIRS)


def _normalize_path(raw_path: str) -> Path:
    return Path(raw_path).expanduser().resolve(strict=False)


def _is_under(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def _has_sensitive_fragment(value: str) -> bool:
    lowered = value.lower()
    return any(fragment in lowered for fragment in _SENSITIVE_FRAGMENTS)


def _contains_shell_metacharacter(argv: list[str]) -> bool:
    return any(any(token in arg for token in _SHELL_META_TOKENS) for arg in argv)


def _resolve_executable(command: str) -> tuple[str | None, str | None]:
    executable = shutil.which(command, path=_TRUSTED_PATH)
    if executable is None:
        return None, f"allowlisted command not found in trusted path: {command}"

    resolved = Path(executable).resolve(strict=False)
    trusted_dirs = tuple(Path(path).resolve(strict=False) for path in _TRUSTED_EXECUTABLE_DIRS)
    if not any(resolved.parent == trusted_dir for trusted_dir in trusted_dirs):
        return None, f"resolved outside trusted executable directories: {command}"

    return str(resolved), None


def _validate_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "URL must use http or https"
    if parsed.username or parsed.password:
        return "credential-like URL parameter is not allowed"

    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in _CREDENTIAL_QUERY_KEYS:
            return "credential-like URL parameter is not allowed"

    if _has_sensitive_fragment(parsed.path):
        return "sensitive path fragment is not allowed"

    return None


def _validate_approved_write_path(raw_path: str) -> tuple[Path | None, str | None]:
    if _has_sensitive_fragment(raw_path):
        return None, "sensitive path fragment is not allowed"

    path = _normalize_path(raw_path)
    if not any(_is_under(path, approved) or path == approved for approved in _approved_dirs()):
        return None, "path is outside allowed write directories"
    if path.is_symlink():
        return None, "refusing to operate on symlink path"

    return path, None


def _validate_readable_path(raw_path: str) -> tuple[Path | None, str | None]:
    if _has_sensitive_fragment(raw_path):
        return None, "sensitive path fragment is not allowed"

    path = _normalize_path(raw_path)
    if not any(_is_under(path, approved) or path == approved for approved in _approved_read_dirs()):
        return None, "path is outside allowed read directories"
    if not path.exists():
        return None, "readable path does not exist"
    if not path.is_file():
        return None, "readable path must be a regular file"

    return path, None


def _validated(
    argv: list[str],
    command: str,
    read_only: bool = False,
    output_path: str | None = None,
) -> ValidationResult:
    return ValidationResult(
        True,
        list(argv),
        command=command,
        read_only=read_only,
        output_path=output_path,
    )


def validate_command(argv: list[str]) -> ValidationResult:
    """Validate a command against a narrow allowlist."""
    if not argv:
        return _reject(argv, "empty command")
    if not all(isinstance(arg, str) and arg for arg in argv):
        return _reject(argv, "argv must contain non-empty strings")
    if _contains_shell_metacharacter(argv):
        return _reject(argv, "shell metacharacter or compound command is not allowed")

    command = argv[0]
    if "/" in command:
        return _reject(argv, "command must be an allowlisted executable name", command=command)

    if command == "curl":
        validation = _validate_curl(argv)
    elif command == "wget":
        validation = _validate_wget(argv)
    elif command == "chmod":
        validation = _validate_chmod(argv)
    elif command == "mkdir":
        validation = _validate_mkdir(argv)
    elif command == "file":
        validation = _validate_file(argv)
    elif command == "which":
        validation = _validate_which(argv)
    elif command == "systemctl":
        validation = _validate_systemctl(argv)
    else:
        return _reject(argv, f"unsupported command: {command}", command=command)

    if not validation.ok:
        return validation

    executable, reason = _resolve_executable(command)
    if reason:
        return _reject(argv, reason, command=command)

    validation.argv[0] = executable or validation.argv[0]
    return validation


def _validate_curl(argv: list[str]) -> ValidationResult:
    command = "curl"
    if len(argv) == 5 and argv[1:3] in (["-L", "-o"], ["-fL", "-o"]):
        output, url = argv[3], argv[4]
        url_reason = _validate_url(url)
        if url_reason:
            return _reject(argv, url_reason, command=command)
        path, path_reason = _validate_approved_write_path(output)
        if path_reason:
            return _reject(argv, path_reason, command=command)
        exec_argv = list(argv)
        exec_argv[3] = str(path)
        return _validated(exec_argv, command, output_path=str(path))

    if len(argv) == 3 and argv[1] == "-I":
        url_reason = _validate_url(argv[2])
        if url_reason:
            return _reject(argv, url_reason, command=command)
        return _validated(argv, command, read_only=True)

    if len(argv) == 4 and argv[1:3] == ["-L", "-I"]:
        url_reason = _validate_url(argv[3])
        if url_reason:
            return _reject(argv, url_reason, command=command)
        return _validated(argv, command, read_only=True)

    return _reject(argv, "unsupported curl form", command=command)


def _validate_wget(argv: list[str]) -> ValidationResult:
    command = "wget"
    if len(argv) != 4 or argv[1] != "-O":
        return _reject(argv, "unsupported wget form", command=command)

    output, url = argv[2], argv[3]
    url_reason = _validate_url(url)
    if url_reason:
        return _reject(argv, url_reason, command=command)
    path, path_reason = _validate_approved_write_path(output)
    if path_reason:
        return _reject(argv, path_reason, command=command)

    exec_argv = list(argv)
    exec_argv[2] = str(path)
    return _validated(exec_argv, command, output_path=str(path))


def _validate_chmod(argv: list[str]) -> ValidationResult:
    command = "chmod"
    if len(argv) != 3 or argv[1] != "+x":
        return _reject(argv, "only chmod +x is allowed", command=command)

    path, path_reason = _validate_approved_write_path(argv[2])
    if path_reason:
        return _reject(argv, path_reason, command=command)
    if path is None or not path.exists() or not path.is_file():
        return _reject(argv, "chmod target must be an existing regular file", command=command)

    exec_argv = list(argv)
    exec_argv[2] = str(path)
    return _validated(exec_argv, command, output_path=str(path))


def _validate_mkdir(argv: list[str]) -> ValidationResult:
    command = "mkdir"
    if len(argv) != 3 or argv[1] != "-p":
        return _reject(argv, "only mkdir -p is allowed", command=command)

    path, path_reason = _validate_approved_write_path(argv[2])
    if path_reason:
        return _reject(argv, path_reason, command=command)

    exec_argv = list(argv)
    exec_argv[2] = str(path)
    return _validated(exec_argv, command, output_path=str(path))


def _validate_file(argv: list[str]) -> ValidationResult:
    command = "file"
    if len(argv) != 2:
        return _reject(argv, "file expects one path", command=command)

    path, path_reason = _validate_readable_path(argv[1])
    if path_reason:
        return _reject(argv, path_reason, command=command)

    exec_argv = list(argv)
    exec_argv[1] = str(path)
    return _validated(exec_argv, command, read_only=True)


def _validate_which(argv: list[str]) -> ValidationResult:
    command = "which"
    if len(argv) != 2 or not _SIMPLE_COMMAND_RE.fullmatch(argv[1]):
        return _reject(argv, "which expects a simple command name", command=command)

    if _has_sensitive_fragment(argv[1]):
        return _reject(argv, "sensitive path fragment is not allowed", command=command)

    return _validated(argv, command, read_only=True)


def _validate_systemctl(argv: list[str]) -> ValidationResult:
    command = "systemctl"
    if len(argv) < 3 or argv[1] != "--user":
        return _reject(argv, "only systemctl --user is allowed", command=command)

    action = argv[2]
    if action == "daemon-reload":
        if len(argv) != 3:
            return _reject(argv, "systemctl --user daemon-reload takes no unit", command=command)
        return _validated(argv, command)

    if action not in {"enable", "disable", "start", "stop", "status"}:
        return _reject(argv, "unsupported systemctl --user action", command=command)
    if len(argv) != 4 or not _SYSTEMD_UNIT_RE.fullmatch(argv[3]):
        return _reject(argv, "systemctl unit must be a simple .service name", command=command)
    if _has_sensitive_fragment(argv[3]):
        return _reject(argv, "sensitive path fragment is not allowed", command=command)

    return _validated(argv, command, read_only=(action == "status"))


async def run_command(argv: list[str], confirm: bool = False) -> dict[str, Any]:
    """Validate and optionally execute a command.

    Commands return a dry-run preview unless confirm=True.
    """
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
            "message": "Command validated. Ask the user to confirm, then call again with confirm=true.",
        }

    return await _execute_validated(validation)


async def _execute_validated(validation: ValidationResult) -> dict[str, Any]:
    """Execute a validated command without using a shell."""
    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *validation.argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        elapsed = time.monotonic() - started
        return {
            "ok": False,
            "argv": validation.argv,
            "command": validation.command,
            "returncode": -1,
            "stdout_tail": "",
            "stderr_tail": "",
            "elapsed_seconds": elapsed,
            "output_size_bytes": None,
            "read_only": validation.read_only,
            "output_path": validation.output_path,
            "error": f"failed to start command: {exc}",
        }

    communicate = proc.communicate()
    try:
        stdout, stderr = await asyncio.wait_for(communicate, timeout=60)
    except asyncio.TimeoutError:
        if hasattr(communicate, "close"):
            communicate.close()
        stdout = b""
        stderr = b""
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = await proc.communicate()
        except Exception as exc:
            elapsed = time.monotonic() - started
            return {
                "ok": False,
                "argv": validation.argv,
                "command": validation.command,
                "returncode": proc.returncode if proc.returncode is not None else -1,
                "stdout_tail": stdout.decode(errors="replace")[-4000:],
                "stderr_tail": stderr.decode(errors="replace")[-4000:],
                "elapsed_seconds": elapsed,
                "output_size_bytes": None,
                "read_only": validation.read_only,
                "output_path": validation.output_path,
                "error": f"command timed out after 60 seconds; failed to drain output: {exc}",
            }
        elapsed = time.monotonic() - started
        return {
            "ok": False,
            "argv": validation.argv,
            "command": validation.command,
            "returncode": proc.returncode if proc.returncode is not None else -1,
            "stdout_tail": stdout.decode(errors="replace")[-4000:],
            "stderr_tail": stderr.decode(errors="replace")[-4000:],
            "elapsed_seconds": elapsed,
            "output_size_bytes": None,
            "read_only": validation.read_only,
            "output_path": validation.output_path,
            "error": "command timed out after 60 seconds",
        }
    elapsed = time.monotonic() - started

    stdout_text = stdout.decode(errors="replace")
    stderr_text = stderr.decode(errors="replace")
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
        "stdout_tail": stdout_text[-4000:],
        "stderr_tail": stderr_text[-4000:],
        "elapsed_seconds": elapsed,
        "output_size_bytes": output_size,
        "read_only": validation.read_only,
        "output_path": validation.output_path,
    }
