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


# ---------- output device routing ----------
#
# Uses `pactl` (PipeWire's PulseAudio shim, default on SteamOS 3). pactl
# exposes stable sink Names plus human Descriptions, which parse far more
# cleanly than `wpctl status`. Switching is a per-user session operation, so
# the shared session_env() is essential — under plugin_loader.service the
# command otherwise can't reach the user's PipeWire socket and silently
# no-ops, hence the read-back verification below.


def parse_sinks(list_output: str) -> list[dict[str, str]]:
    """Parse `pactl list sinks` into [{name, description, state}]."""
    sinks: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in list_output.splitlines():
        line = raw.strip()
        if line.startswith("Sink #"):
            if current is not None:
                sinks.append(current)
            current = {"name": "", "description": "", "state": ""}
        elif current is not None:
            if line.startswith("Name:"):
                current["name"] = line.split(":", 1)[1].strip()
            elif line.startswith("Description:"):
                current["description"] = line.split(":", 1)[1].strip()
            elif line.startswith("State:"):
                current["state"] = line.split(":", 1)[1].strip()
    if current is not None:
        sinks.append(current)
    return sinks


def match_sink(target: str, sinks: list[dict[str, str]]) -> str | None:
    """Resolve a user-supplied string to exactly one sink Name.

    Exact Name match wins; otherwise a case-insensitive substring of either
    Name or Description, but only if it's unambiguous. Returns None when no
    match or more than one matches.
    """
    target_l = target.strip().lower()
    for sink in sinks:
        if sink["name"].lower() == target_l:
            return sink["name"]
    matches = [
        sink["name"]
        for sink in sinks
        if target_l in sink["name"].lower() or target_l in sink["description"].lower()
    ]
    return matches[0] if len(matches) == 1 else None


async def list_outputs() -> dict[str, Any]:
    """List audio output devices (sinks) and mark the current default."""
    if not shutil.which("pactl"):
        return {"ok": False, "error": "pactl not found (pipewire-pulse not installed?)"}

    rc, out, err = await _run("pactl", "list", "sinks")
    if rc != 0:
        return {"ok": False, "error": err.strip() or "pactl list sinks failed"}

    sinks = parse_sinks(out)
    drc, dout, _ = await _run("pactl", "get-default-sink")
    default = dout.strip() if drc == 0 else ""

    devices = [
        {
            "name": sink["name"],
            "description": sink["description"] or sink["name"],
            "state": sink["state"],
            "default": sink["name"] == default,
        }
        for sink in sinks
    ]
    return {"ok": True, "devices": devices, "default": default}


async def set_output_device(device: str) -> dict[str, Any]:
    """Switch the default output sink and move playing streams onto it."""
    if not shutil.which("pactl"):
        return {"ok": False, "error": "pactl not found (pipewire-pulse not installed?)"}

    rc, out, err = await _run("pactl", "list", "sinks")
    if rc != 0:
        return {"ok": False, "error": err.strip() or "pactl list sinks failed"}

    sinks = parse_sinks(out)
    name = match_sink(device, sinks)
    if name is None:
        return {
            "ok": False,
            "error": "no unique sink matched",
            "requested": device,
            "available": [
                {"name": sink["name"], "description": sink["description"]}
                for sink in sinks
            ],
        }

    rc, _, err = await _run("pactl", "set-default-sink", name)
    if rc != 0:
        return {"ok": False, "error": err.strip() or "pactl set-default-sink failed"}

    # Setting the default only routes *new* streams; move the ones already
    # playing so audio actually follows to the new device (what the KDE tray
    # does after a Bluetooth connect).
    moved = 0
    irc, iout, _ = await _run("pactl", "list", "short", "sink-inputs")
    if irc == 0:
        for line in iout.splitlines():
            input_id = line.split("\t", 1)[0].strip()
            if input_id:
                mrc, _, _ = await _run("pactl", "move-sink-input", input_id, name)
                if mrc == 0:
                    moved += 1

    # rc==0 isn't trust-worthy under a broken session bus; confirm by read-back.
    drc, dout, _ = await _run("pactl", "get-default-sink")
    if drc != 0 or dout.strip() != name:
        return {
            "ok": False,
            "requested": name,
            "actual": dout.strip() if drc == 0 else None,
            "error": (
                "set-default-sink reported success but read-back disagreed — "
                "likely the audio backend cannot reach the user session bus "
                "(check XDG_RUNTIME_DIR / DBUS_SESSION_BUS_ADDRESS)"
            ),
        }
    return {"ok": True, "default": name, "moved_streams": moved, "verified": True}
