"""SteamOS `/usr` read-only lock — toggle + persistent state tracking.

Why this exists:
  SteamOS keeps /usr read-only by default. Any tool that needs to write
  there (pacman_install) must `steamos-readonly disable` first and
  `enable` after. If the agent crashes between those two calls, /usr
  stays unlocked — which is risky around the next SteamOS update.

  We persist a small state file at ~/.deckmind/steamos_lock.json the
  moment we unlock, and clear it the moment we lock back. On every
  agent startup, runtime/context.py compares this record against the
  live /usr state. If we have a record AND /usr is still unlocked, we
  surface a "dangling unlock" warning so the user can relock.

  Combined with try/finally in pacman_install, this means a dropped
  call almost never leaves /usr unlocked silently.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import shutil
from pathlib import Path
from typing import Any


_STATE_DIR = Path.home() / ".deckmind"
_STATE_FILE = _STATE_DIR / "steamos_lock.json"


# ---------- low-level helpers (also used by pacman_install) ----------

def is_usr_readonly() -> bool | None:
    """Return True if /usr is mounted RO, False if RW, None if not Linux."""
    if not os.path.exists("/proc/mounts"):
        return None
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4 and parts[1] == "/usr":
                    return "ro" in parts[3].split(",")
    except OSError:
        return None
    return False


def load_state() -> dict[str, Any]:
    """Read the unlock-record file. Empty dict if missing/unreadable."""
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def record_unlock(reason: str) -> None:
    """Persist 'we unlocked /usr at time T for reason R'."""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(
        json.dumps({
            "unlocked_by_us_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "reason": reason,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clear_unlock() -> None:
    """Erase the unlock record (we've locked back)."""
    try:
        _STATE_FILE.unlink()
    except FileNotFoundError:
        pass


async def _run(*cmd: str) -> tuple[int, str, str]:
    """Subprocess that does NOT redirect stdin — sudo can prompt on tty."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return (
        proc.returncode or 0,
        out.decode(errors="ignore"),
        err.decode(errors="ignore"),
    )


# ---------- public tools ----------

async def steamos_lock_status() -> dict[str, Any]:
    """Report whether /usr is RO + whether we have a dangling unlock record."""
    if not shutil.which("steamos-readonly"):
        return {"ok": False,
                "error": "steamos-readonly not found — not a SteamOS device?"}

    ro = is_usr_readonly()
    record = load_state()
    dangling = bool(record) and (ro is False)

    return {
        "ok": True,
        "usr_readonly": ro,
        "we_unlocked_at": record.get("unlocked_by_us_at"),
        "we_unlocked_reason": record.get("reason"),
        "dangling_unlock": dangling,
        "hint": (
            ("/usr 当前未锁定，且我们记录上次解锁后没有锁回去（原因："
             f"{record.get('reason')}）。建议立刻调用 steamos_lock 锁回去。")
            if dangling else None
        ),
    }


async def steamos_unlock(reason: str = "manual user request") -> dict[str, Any]:
    """Disable SteamOS's /usr read-only lock and remember we did it."""
    if not shutil.which("steamos-readonly"):
        return {"ok": False, "error": "steamos-readonly not found"}

    rc, _, err = await _run("sudo", "steamos-readonly", "disable")
    if rc != 0:
        return {"ok": False,
                "error": f"steamos-readonly disable failed: {err.strip() or '(empty)'}"}

    record_unlock(reason)
    return {
        "ok": True, "unlocked": True,
        "reason": reason,
        "warning": ("/usr 已解锁。完事后**务必**记得调用 steamos_lock 锁回去，"
                    "否则 SteamOS 大版本更新可能出问题。"),
    }


async def steamos_lock() -> dict[str, Any]:
    """Re-enable SteamOS's /usr read-only lock and clear the unlock record."""
    if not shutil.which("steamos-readonly"):
        return {"ok": False, "error": "steamos-readonly not found"}

    rc, _, err = await _run("sudo", "steamos-readonly", "enable")
    if rc != 0:
        return {"ok": False,
                "error": f"steamos-readonly enable failed: {err.strip() or '(empty)'}"}

    clear_unlock()
    return {"ok": True, "locked": True}
