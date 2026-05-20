"""Restricted command execution with validation and dry-run support."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
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
    advanced: bool = False
    risk_level: str = "normal"
    risk_reason: str | None = None


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
_SECRET_ENV_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|PASSWD|AUTH)[A-Za-z0-9_]*=).*$",
    re.IGNORECASE,
)
_URL_CREDENTIAL_RE = re.compile(r"://([^/\s:@]+):([^/\s@]+)@")
_TRUSTED_EXECUTABLE_DIRS: tuple[str, ...] = (
    "/usr/bin",
    "/bin",
    "/usr/local/bin",
    "/opt/homebrew/bin",
)
_TRUSTED_PATH = ":".join(_TRUSTED_EXECUTABLE_DIRS)
_COMMAND_TIMEOUT_SECONDS = 60

# Commands that only read state — no filesystem writes, no daemon control,
# no network changes. The executor treats run_command with one of these
# as "safe" (no confirmation prompt) and the validator returns
# read_only=True / risk_level=normal so the dry-run dance is skipped.
_READ_ONLY_COMMANDS: frozenset[str] = frozenset({
    # File inspection
    "cat", "head", "tail", "tac", "nl", "od", "xxd", "hexdump",
    # Listing / metadata
    "ls", "stat", "wc", "du", "df", "tree",
    # Hashing
    "md5sum", "sha1sum", "sha256sum", "sha512sum", "b2sum", "cksum",
    # Text processing (read-only forms — see _READ_ONLY_FLAG_DENY for sed/find)
    "grep", "egrep", "fgrep", "rg", "awk", "gawk", "cut", "sort", "uniq",
    "tr", "fold", "fmt", "expand", "unexpand", "column", "paste", "join",
    "comm", "diff", "cmp", "sed", "find",
    # Paths
    "realpath", "readlink", "basename", "dirname",
    # Processes
    "ps", "pgrep", "pidof",
    # System info
    "uname", "hostname", "whoami", "id", "groups", "uptime", "free",
    "date", "env", "printenv", "locale", "nproc", "arch", "lsblk",
    "lscpu", "lsmod", "lsusb", "lspci", "getent",
    # Trivial output
    "echo", "printf", "pwd", "true", "false",
    # Logs (read-only; -f tails until timeout)
    "journalctl", "dmesg",
})

# Flags that turn an otherwise read-only command into a write. Matched
# by startswith() so `-i.bak` is caught alongside `-i`.
_READ_ONLY_FLAG_DENY: dict[str, tuple[str, ...]] = {
    "sed": ("-i", "--in-place"),
    "find": ("-delete", "-exec", "-execdir", "-ok", "-okdir",
             "-fprint", "-fprintf", "-fls"),
}
_EXEC_ENV = {
    "PATH": _TRUSTED_PATH,
    "HOME": str(Path.home()),
    "LANG": os.environ.get("LANG", "C.UTF-8"),
    "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
}
_LAUNCH_ENV_KEYS: tuple[str, ...] = (
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS",
    "XDG_CURRENT_DESKTOP",
    "DESKTOP_SESSION",
)
_ADVANCED_DISALLOWED_COMMANDS: set[str] = {
    "bash",
    "sh",
    "zsh",
    "fish",
    "ksh",
    "python",
    "python3",
    "perl",
    "ruby",
    "node",
    "sudo",
    "su",
    "doas",
    "pacman",
    "rm",
    "dd",
    "mount",
    "umount",
    "systemctl",
    "osascript",
}
_HARDLINE_COMMANDS: set[str] = {
    "reboot",
    "shutdown",
    "halt",
    "poweroff",
    "mkfs",
    "mkfs.ext2",
    "mkfs.ext3",
    "mkfs.ext4",
    "mkfs.fat",
    "mkfs.vfat",
    "mkfs.xfs",
    "init",
    "telinit",
}


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


def _detect_hardline_command(argv: list[str]) -> str | None:
    if not argv:
        return None

    command = argv[0].lower()
    if command in _HARDLINE_COMMANDS:
        return f"hardline blocked command: {command}"

    if command.startswith("mkfs."):
        return f"hardline blocked command: {command}"

    if command == "kill" and "-1" in argv[1:]:
        return "hardline blocked command: kill -1"

    if command == "dd":
        for arg in argv[1:]:
            if arg.startswith("of=/dev/"):
                return "hardline blocked command: dd writes to raw device"

    return None


def _redact_sensitive_output(text: str) -> str:
    redacted_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        line = _SECRET_ENV_RE.sub(r"\1[REDACTED]", line)
        line = _URL_CREDENTIAL_RE.sub(r"://[REDACTED]:[REDACTED]@", line)
        redacted_lines.append(line)
    return "".join(redacted_lines)


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


def _validate_approved_directory(raw_path: str) -> tuple[Path | None, str | None]:
    path, reason = _validate_approved_write_path(raw_path)
    if reason:
        return None, reason
    if path is None or not path.exists() or not path.is_dir():
        return None, "target directory must exist"
    return path, None


def _validated(
    argv: list[str],
    command: str,
    read_only: bool = False,
    output_path: str | None = None,
    advanced: bool = False,
    risk_level: str = "normal",
    risk_reason: str | None = None,
) -> ValidationResult:
    return ValidationResult(
        True,
        list(argv),
        command=command,
        read_only=read_only,
        output_path=output_path,
        advanced=advanced,
        risk_level=risk_level,
        risk_reason=risk_reason,
    )


def validate_command(argv: list[str], advanced: bool = False) -> ValidationResult:
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
    elif command == "tar":
        validation = _validate_tar(argv)
    elif command == "launch_file":
        return _validate_launch_file(argv)
    elif command in _READ_ONLY_COMMANDS:
        validation = _validate_read_only(argv)
    else:
        if advanced:
            return _validate_advanced_command(argv)
        return _reject(argv, f"unsupported command: {command}", command=command)

    if not validation.ok and advanced:
        return _validate_advanced_command(argv)
    if not validation.ok:
        return validation

    executable, reason = _resolve_executable(command)
    if reason:
        return _reject(argv, reason, command=command)

    validation.argv[0] = executable or validation.argv[0]
    return validation


def _validate_read_only(argv: list[str]) -> ValidationResult:
    """Validate a member of `_READ_ONLY_COMMANDS`.

    Rejects flags that would turn it into a write (sed -i, find -delete,
    find -exec, ...). Otherwise marks the call as read_only=True so the
    executor and run_command can skip the confirmation gate.
    """
    command = argv[0]
    deny = _READ_ONLY_FLAG_DENY.get(command, ())
    if deny:
        for arg in argv[1:]:
            for bad in deny:
                if arg == bad or arg.startswith(bad + "="):
                    return _reject(argv, f"{command} {bad} is not a read-only form",
                                   command=command)
                # `sed -i.bak` / `find -execdir` already handled above; also
                # block `-i` followed by a separate suffix arg.
                if bad == "-i" and arg.startswith("-i") and arg != "-i":
                    return _reject(argv, f"{command} {arg} is not a read-only form",
                                   command=command)
    return _validated(list(argv), command, read_only=True)


def is_read_only_invocation(arguments: dict[str, Any]) -> bool:
    """Quick check used by the executor to skip prompting on read-only calls.

    Returns True only if validation succeeds AND the command is in the
    read-only allowlist. Anything ambiguous returns False so the normal
    destructive gate still runs.
    """
    argv = arguments.get("argv")
    if not isinstance(argv, list) or not argv:
        return False
    try:
        validation = validate_command(argv, advanced=False)
    except Exception:
        return False
    return validation.ok and validation.read_only


def _validate_advanced_command(argv: list[str]) -> ValidationResult:
    command = argv[0]
    if "/" in command:
        return _reject(argv, "advanced command must be an executable name", command=command)
    if not _SIMPLE_COMMAND_RE.fullmatch(command):
        return _reject(argv, "advanced command name is not allowed", command=command)

    hardline_reason = _detect_hardline_command(argv)
    if hardline_reason:
        return _reject(argv, hardline_reason, command=command)

    if command.lower() in _ADVANCED_DISALLOWED_COMMANDS:
        return _reject(argv, f"{command} is not allowed in advanced mode", command=command)

    executable, reason = _resolve_executable(command)
    if reason:
        return _reject(argv, reason, command=command)

    exec_argv = list(argv)
    exec_argv[0] = executable or exec_argv[0]
    return _validated(
        exec_argv,
        command,
        read_only=False,
        advanced=True,
        risk_level="high",
        risk_reason="advanced command outside the restricted allowlist",
    )


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
        exec_argv = [argv[0], "-q", *argv[1:]]
        exec_argv[4] = str(path)
        return _validated(exec_argv, command, output_path=str(path))

    if len(argv) == 3 and argv[1] == "-I":
        url_reason = _validate_url(argv[2])
        if url_reason:
            return _reject(argv, url_reason, command=command)
        return _validated([argv[0], "-q", *argv[1:]], command, read_only=True)

    if len(argv) == 4 and argv[1:3] == ["-L", "-I"]:
        url_reason = _validate_url(argv[3])
        if url_reason:
            return _reject(argv, url_reason, command=command)
        return _validated([argv[0], "-q", *argv[1:]], command, read_only=True)

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

    exec_argv = [argv[0], "--no-config", *argv[1:]]
    exec_argv[3] = str(path)
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


def _validate_tar(argv: list[str]) -> ValidationResult:
    command = "tar"
    if len(argv) != 5 or argv[1] != "-xzf" or argv[3] != "-C":
        return _reject(argv, "only tar -xzf <archive> -C <directory> is allowed", command=command)

    archive, archive_reason = _validate_readable_path(argv[2])
    if archive_reason:
        return _reject(argv, archive_reason, command=command)
    if archive is None or not (archive.name.endswith(".tar.gz") or archive.name.endswith(".tgz")):
        return _reject(argv, "tar archive must be .tar.gz or .tgz", command=command)

    dest, dest_reason = _validate_approved_directory(argv[4])
    if dest_reason:
        return _reject(argv, dest_reason, command=command)

    archive_reason = _validate_tar_archive_members(archive, dest)
    if archive_reason:
        return _reject(argv, archive_reason, command=command)

    exec_argv = list(argv)
    exec_argv[2] = str(archive)
    exec_argv[4] = str(dest)
    return _validated(exec_argv, command, output_path=str(dest))


def _validate_tar_archive_members(archive: Path, dest: Path) -> str | None:
    try:
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                name = member.name
                if not name or _has_sensitive_fragment(name):
                    return f"unsafe tar member path: {name}"
                member_path = PurePosixPath(name)
                if member_path.is_absolute() or ".." in member_path.parts:
                    return f"unsafe tar member path: {name}"
                if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                    return f"unsafe tar member type: {name}"
                target = (dest / Path(*member_path.parts)).resolve(strict=False)
                if not (_is_under(target, dest) or target == dest):
                    return f"unsafe tar member path: {name}"
    except (tarfile.TarError, OSError) as exc:
        return f"could not inspect tar archive: {exc}"
    return None


def _validate_launch_file(argv: list[str]) -> ValidationResult:
    command = "launch_file"
    if len(argv) != 2:
        return _reject(argv, "launch_file expects one executable path", command=command)

    path, path_reason = _validate_approved_write_path(argv[1])
    if path_reason:
        return _reject(argv, path_reason, command=command)
    if path is None or not path.exists() or not path.is_file():
        return _reject(argv, "launch target must be an existing regular file", command=command)
    if not os.access(path, os.X_OK):
        return _reject(argv, "launch target must be executable", command=command)

    return _validated([str(path)], command)


def _launch_env() -> dict[str, str]:
    env = dict(_EXEC_ENV)
    for key in _LAUNCH_ENV_KEYS:
        value = os.environ.get(key)
        if value:
            env[key] = value
    # Fall back to reconstructed user-session vars (DBus/Wayland/XDG)
    # when the host process didn't inherit them — e.g. running under
    # Decky's plugin_loader.service.
    from runtime.session_env import session_env
    filled = session_env(env)
    for key in _LAUNCH_ENV_KEYS:
        if key not in env and key in filled:
            env[key] = filled[key]
    return env


async def run_command(
    argv: list[str],
    confirm: bool = False,
    advanced: bool = False,
    high_risk_confirm: bool = False,
) -> dict[str, Any]:
    """Validate and optionally execute a command.

    Commands return a dry-run preview unless confirm=True.
    """
    validation = validate_command(argv, advanced=advanced)
    if not validation.ok:
        return {
            "ok": False,
            "refused": True,
            "reason": validation.reason,
            "argv": validation.argv,
        }

    # Read-only commands (cat, ls, grep, wc, sed -n, ...) bypass the
    # dry-run / confirm dance. The executor also classifies them as
    # "safe" so the user never sees a prompt.
    if validation.read_only and validation.risk_level == "normal":
        return await _execute_validated(validation)

    requires_high_risk_confirm = validation.risk_level == "high"
    if confirm and requires_high_risk_confirm and not high_risk_confirm:
        return {
            "ok": False,
            "refused": True,
            "reason": "high-risk command requires high_risk_confirm=true after explicit user approval",
            "argv": validation.argv,
            "command": validation.command,
            "advanced": validation.advanced,
            "risk_level": validation.risk_level,
            "risk_reason": validation.risk_reason,
            "requires_high_risk_confirm": True,
        }

    if not confirm:
        return {
            "ok": True,
            "dry_run": True,
            "argv": validation.argv,
            "command": validation.command,
            "read_only": validation.read_only,
            "output_path": validation.output_path,
            "advanced": validation.advanced,
            "risk_level": validation.risk_level,
            "risk_reason": validation.risk_reason,
            "requires_high_risk_confirm": requires_high_risk_confirm,
            "message": "Command validated. Ask the user to confirm, then call again with confirm=true.",
        }

    if validation.command == "launch_file":
        return await _launch_validated(validation)
    return await _execute_validated(validation)


async def _launch_validated(validation: ValidationResult) -> dict[str, Any]:
    """Launch an approved user executable and return immediately."""
    started = time.monotonic()
    executable = Path(validation.argv[0])
    try:
        proc = await asyncio.create_subprocess_exec(
            *validation.argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(executable.parent),
            env=_launch_env(),
            start_new_session=True,
        )
    except OSError as exc:
        elapsed = time.monotonic() - started
        return {
            "ok": False,
            "argv": validation.argv,
            "command": validation.command,
            "returncode": -1,
            "elapsed_seconds": elapsed,
            "output_size_bytes": None,
            "read_only": validation.read_only,
            "output_path": validation.output_path,
            "advanced": validation.advanced,
            "risk_level": validation.risk_level,
            "risk_reason": validation.risk_reason,
            "error": f"failed to launch file: {exc}",
        }

    return {
        "ok": True,
        "argv": validation.argv,
        "command": validation.command,
        "pid": proc.pid,
        "elapsed_seconds": time.monotonic() - started,
        "read_only": validation.read_only,
        "output_path": validation.output_path,
        "advanced": validation.advanced,
        "risk_level": validation.risk_level,
        "risk_reason": validation.risk_reason,
        "message": "launched approved executable",
    }


async def _execute_validated(validation: ValidationResult) -> dict[str, Any]:
    """Execute a validated command without using a shell."""
    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *validation.argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=dict(_EXEC_ENV),
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
            "advanced": validation.advanced,
            "risk_level": validation.risk_level,
            "risk_reason": validation.risk_reason,
            "error": f"failed to start command: {exc}",
        }

    communicate = proc.communicate()
    try:
        stdout, stderr = await asyncio.wait_for(
            communicate,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
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
                "stdout_tail": _redact_sensitive_output(stdout.decode(errors="replace"))[-4000:],
                "stderr_tail": _redact_sensitive_output(stderr.decode(errors="replace"))[-4000:],
                "elapsed_seconds": elapsed,
                "output_size_bytes": None,
                "read_only": validation.read_only,
                "output_path": validation.output_path,
                "advanced": validation.advanced,
                "risk_level": validation.risk_level,
                "risk_reason": validation.risk_reason,
                "error": (
                    f"command timed out after {_COMMAND_TIMEOUT_SECONDS} "
                    f"seconds; failed to drain output: {exc}"
                ),
            }
        elapsed = time.monotonic() - started
        return {
            "ok": False,
            "argv": validation.argv,
            "command": validation.command,
            "returncode": proc.returncode if proc.returncode is not None else -1,
            "stdout_tail": _redact_sensitive_output(stdout.decode(errors="replace"))[-4000:],
            "stderr_tail": _redact_sensitive_output(stderr.decode(errors="replace"))[-4000:],
            "elapsed_seconds": elapsed,
            "output_size_bytes": None,
            "read_only": validation.read_only,
            "output_path": validation.output_path,
            "advanced": validation.advanced,
            "risk_level": validation.risk_level,
            "risk_reason": validation.risk_reason,
            "error": f"command timed out after {_COMMAND_TIMEOUT_SECONDS} seconds",
        }
    elapsed = time.monotonic() - started

    stdout_text = _redact_sensitive_output(stdout.decode(errors="replace"))
    stderr_text = _redact_sensitive_output(stderr.decode(errors="replace"))
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
        "advanced": validation.advanced,
        "risk_level": validation.risk_level,
        "risk_reason": validation.risk_reason,
    }
