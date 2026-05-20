"""System tools: battery + volume.

Linux-first. Battery uses /sys/class/power_supply (the Steam Deck exposes
BAT1 there). Volume uses `wpctl` (PipeWire, default on SteamOS 3) and
falls back to `amixer` if available.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import re
import shutil
from typing import Any


def _session_env() -> dict[str, str]:
    # Lazy import: runtime/__init__.py pulls in the agent, which would
    # circularly import tools at module-load time.
    return importlib.import_module("runtime.session_env").session_env()


# ---------- battery ----------

def _read(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


async def get_battery() -> dict[str, Any]:
    """Read battery capacity + status from sysfs."""
    base = "/sys/class/power_supply"
    if not os.path.isdir(base):
        return {"ok": False, "error": "no /sys/class/power_supply (not Linux?)"}

    for name in sorted(os.listdir(base)):
        cap = _read(f"{base}/{name}/capacity")
        if cap is not None:
            status = _read(f"{base}/{name}/status") or "unknown"
            return {"ok": True, "device": name, "percent": int(cap), "status": status}

    return {"ok": False, "error": "no battery device found"}


# ---------- volume ----------

_WPCTL_SINK = "@DEFAULT_AUDIO_SINK@"


async def _run(*cmd: str) -> tuple[int, str, str]:
    """Run a subprocess and return (rc, stdout, stderr).

    Always injects a user-session env so wpctl/pactl can reach the DBus
    session bus when DeckMind runs under plugin_loader.service.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_session_env(),
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="ignore"), err.decode(errors="ignore")


async def get_volume() -> dict[str, Any]:
    """Get current volume as an integer percent."""
    if shutil.which("wpctl"):
        rc, out, _ = await _run("wpctl", "get-volume", _WPCTL_SINK)
        # Example output: "Volume: 0.45"
        m = re.search(r"([0-9.]+)", out)
        if rc == 0 and m:
            return {"ok": True, "percent": int(float(m.group(1)) * 100), "backend": "wpctl"}

    if shutil.which("amixer"):
        rc, out, _ = await _run("amixer", "get", "Master")
        m = re.search(r"\[(\d+)%\]", out)
        if rc == 0 and m:
            return {"ok": True, "percent": int(m.group(1)), "backend": "amixer"}

    return {"ok": False, "error": "no supported audio backend (wpctl/amixer)"}


async def _verify_volume(expected: int, backend: str) -> dict[str, Any]:
    """Read volume back and confirm it matches what we asked for.

    rc==0 from wpctl/amixer is not enough — under a broken DBus session
    the command silently no-ops. A read-back catches that case.
    """
    after = await get_volume()
    actual = after.get("percent") if after.get("ok") else None
    # Allow 2pp slack for wpctl float rounding.
    if actual is not None and abs(actual - expected) <= 2:
        return {"ok": True, "percent": actual, "backend": backend, "verified": True}
    return {
        "ok": False,
        "backend": backend,
        "requested": expected,
        "actual": actual,
        "error": (
            "volume change reported success but read-back disagreed — "
            "likely the audio backend cannot reach the user session bus "
            "(check XDG_RUNTIME_DIR / DBUS_SESSION_BUS_ADDRESS)"
        ),
    }


async def set_volume(percent: int) -> dict[str, Any]:
    """Set volume; percent is clamped to [0, 100]."""
    percent = max(0, min(100, int(percent)))

    if shutil.which("wpctl"):
        rc, _, err = await _run("wpctl", "set-volume", _WPCTL_SINK, f"{percent / 100:.2f}")
        if rc != 0:
            return {"ok": False, "error": err.strip() or "wpctl failed"}
        return await _verify_volume(percent, "wpctl")

    if shutil.which("amixer"):
        rc, _, err = await _run("amixer", "set", "Master", f"{percent}%")
        if rc != 0:
            return {"ok": False, "error": err.strip() or "amixer failed"}
        return await _verify_volume(percent, "amixer")

    return {"ok": False, "error": "no supported audio backend (wpctl/amixer)"}
