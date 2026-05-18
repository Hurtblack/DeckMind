"""System tools: battery + volume.

Linux-first. Battery uses /sys/class/power_supply (the Steam Deck exposes
BAT1 there). Volume uses `wpctl` (PipeWire, default on SteamOS 3) and
falls back to `amixer` if available.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from typing import Any


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
    """Run a subprocess and return (rc, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
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


async def set_volume(percent: int) -> dict[str, Any]:
    """Set volume; percent is clamped to [0, 100]."""
    percent = max(0, min(100, int(percent)))

    if shutil.which("wpctl"):
        rc, _, err = await _run("wpctl", "set-volume", _WPCTL_SINK, f"{percent / 100:.2f}")
        if rc == 0:
            return {"ok": True, "percent": percent, "backend": "wpctl"}
        return {"ok": False, "error": err.strip() or "wpctl failed"}

    if shutil.which("amixer"):
        rc, _, err = await _run("amixer", "set", "Master", f"{percent}%")
        if rc == 0:
            return {"ok": True, "percent": percent, "backend": "amixer"}
        return {"ok": False, "error": err.strip() or "amixer failed"}

    return {"ok": False, "error": "no supported audio backend (wpctl/amixer)"}
