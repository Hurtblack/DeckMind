"""Steam-related tools.

These are intentionally simple. On a real Steam Deck you would use the
`steam steam://rungameid/<id>` URI scheme or `flatpak run` to launch
games. Here we use shell commands with safe fallbacks so the agent can
run on a developer machine as well.
"""

from __future__ import annotations

import asyncio
import importlib
import shutil
from typing import Any


def _session_env() -> dict[str, str]:
    # Lazy import to avoid runtime/__init__.py circular load.
    return importlib.import_module("runtime.session_env").session_env()

# A small mock registry so the demo works even without a real Steam install.
# Map a human-friendly name -> Steam AppID.
_GAME_REGISTRY: dict[str, str] = {
    "cs2": "730",
    "counter-strike 2": "730",
    "dota2": "570",
    "dota 2": "570",
    "hades": "1145360",
}


def _has_steam() -> bool:
    """Return True if a `steam` binary is available on PATH."""
    return shutil.which("steam") is not None


def _resolve_app_id(game_name: str) -> tuple[str | None, str | None]:
    """Map a game name to (app_id, resolved_name).

    Tries (in order): built-in aliases, exact match against installed
    Steam library, substring match against installed library.
    """
    key = game_name.strip().lower()
    if not key:
        return None, None

    if key in _GAME_REGISTRY:
        return _GAME_REGISTRY[key], key

    # Local import to avoid a hard dependency cycle and to keep the
    # scanner cost only when actually needed.
    from runtime.context import scan_steam_library
    library = scan_steam_library()

    # Exact name match (case-insensitive).
    for g in library:
        if g["name"].lower() == key:
            return g["appid"], g["name"]
    # Substring match — "elden" -> "Elden Ring".
    for g in library:
        if key in g["name"].lower():
            return g["appid"], g["name"]

    return None, None


async def launch_game(game_name: str) -> dict[str, Any]:
    """Launch a game by friendly name.

    Resolves the name via built-in aliases first, then the locally
    installed Steam library. Uses Steam's URI scheme when available,
    otherwise returns a mock result.
    """
    app_id, resolved = _resolve_app_id(game_name)
    if app_id is None:
        return {"ok": False,
                "error": f"Unknown game '{game_name}'. Not in the built-in "
                         f"alias list and not found in your installed Steam "
                         f"library. Try a more specific name or install it first."}
    key = resolved or game_name.strip().lower()

    if not _has_steam():
        # Mock branch — useful on macOS / CI / dev machines.
        return {"ok": True, "mock": True, "game": key, "app_id": app_id,
                "note": "steam binary not found; pretending to launch"}

    # Fire-and-forget: don't block on the game process.
    proc = await asyncio.create_subprocess_exec(
        "steam", f"steam://rungameid/{app_id}",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        env=_session_env(),
    )
    rc = await proc.wait()
    # `steam` URI handler exits 0 quickly after handing off to the
    # running Steam client. If Steam isn't running and we couldn't reach
    # the session bus, it exits 0 too — but no Steam process exists.
    # A short delay + pgrep catches the silent-failure case.
    await asyncio.sleep(0.4)
    steam_alive = await _steam_running()
    if not steam_alive:
        return {
            "ok": False,
            "game": key,
            "app_id": app_id,
            "returncode": rc,
            "error": (
                "issued steam:// URI but no Steam process is running — "
                "Steam Client may not be launched, or this backend cannot "
                "reach the user DBus session (check XDG_RUNTIME_DIR / "
                "DBUS_SESSION_BUS_ADDRESS)."
            ),
        }
    return {"ok": True, "game": key, "app_id": app_id, "pid": proc.pid,
            "steam_running": True}


async def _steam_running() -> bool:
    """True if a steam client process is alive in this session."""
    if not shutil.which("pgrep"):
        return True  # can't tell — assume success and don't false-alarm
    proc = await asyncio.create_subprocess_exec(
        "pgrep", "-x", "steam",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        env=_session_env(),
    )
    rc = await proc.wait()
    return rc == 0


# Processes whose death would break the running system in ways the user
# almost certainly does NOT want (kernel/init/desktop session/audio).
# We hard-refuse these with a clear explanation. Everything else
# (including 'steam', 'bash', etc.) goes through the normal Executor
# prompt — the user can decide.
_CLOSE_GAME_CRITICAL: dict[str, str] = {
    "systemd":    "PID 1 / system init — killing this crashes the machine",
    "init":       "PID 1 / system init — killing this crashes the machine",
    "kernel":     "kernel thread — cannot be killed safely",
    "gamescope":  "Steam Deck's Game Mode compositor — kills the whole UI",
    "kwin":       "KDE window manager — kills your desktop session",
    "plasma":     "KDE shell — kills your desktop session",
    "kded":       "KDE daemon — desktop will become unusable",
    "xorg":       "X display server — kills your desktop session",
    "wayland":    "Wayland display server — kills your desktop session",
    "pipewire":   "system audio server — system-wide sound stops",
    "pulseaudio": "system audio server — system-wide sound stops",
    "dbus":       "system IPC bus — most apps will stop responding",
}


async def close_game(process_name: str) -> dict[str, Any]:
    """Kill a running game by process name using `pkill -f`.

    Hard-refuses (with reason) only when the name would match a process
    that, if killed, would break the running system. Everything else is
    allowed — the Executor's side-effect prompt is the user's chance to
    veto a questionable name.
    """
    if not shutil.which("pkill"):
        return {"ok": False, "error": "pkill not available on this system"}

    name = (process_name or "").strip()
    if not name:
        return {"ok": False, "error": "empty process_name"}

    lower = name.lower()
    for bad, why in _CLOSE_GAME_CRITICAL.items():
        if bad in lower:
            return {
                "ok": False, "refused": True, "process": name,
                "matched": bad, "reason": why,
                "message": (
                    f"Refusing to pkill -f {name!r}: it matches {bad!r}, "
                    f"which is a critical system process ({why})."
                ),
            }

    proc = await asyncio.create_subprocess_exec(
        "pkill", "-f", name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_session_env(),
    )
    await proc.communicate()
    # pkill exits 0 if it killed something, 1 if nothing matched.
    return {"ok": proc.returncode in (0, 1), "killed": proc.returncode == 0,
            "process": name}


async def install_game(game_name: str, confirm: bool = False) -> dict[str, Any]:
    """Open Steam's install dialog for a known game.

    Two-step confirmation: confirm=False returns a preview; confirm=True
    actually launches the Steam URI, which opens the install dialog in
    Steam itself (the user still clicks "Install" there to start the
    download).
    """
    key = game_name.strip().lower()
    app_id = _GAME_REGISTRY.get(key)
    if app_id is None:
        return {"ok": False,
                "error": f"Unknown game '{game_name}'. Known: {list(_GAME_REGISTRY)}"}

    if not confirm:
        return {
            "ok": True, "dry_run": True, "game": key, "app_id": app_id,
            "message": (
                f"Will open Steam's install dialog for '{key}' (AppID {app_id}). "
                "Ask the user to confirm, then call again with confirm=true."
            ),
        }

    if not _has_steam():
        return {"ok": True, "mock": True, "game": key, "app_id": app_id,
                "note": "steam binary not found; pretending to open install dialog"}

    proc = await asyncio.create_subprocess_exec(
        "steam", f"steam://install/{app_id}",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        env=_session_env(),
    )
    await proc.wait()
    await asyncio.sleep(0.4)
    if not await _steam_running():
        return {"ok": False, "game": key, "app_id": app_id,
                "error": "steam:// URI sent but no Steam process is running "
                         "(see launch_game for likely DBus session cause)."}
    return {"ok": True, "game": key, "app_id": app_id, "pid": proc.pid,
            "note": "Steam install dialog opened — user must click Install there."}


async def uninstall_game(game_name: str, confirm: bool = False) -> dict[str, Any]:
    """Open Steam's uninstall dialog for a known game (two-step confirm)."""
    key = game_name.strip().lower()
    app_id = _GAME_REGISTRY.get(key)
    if app_id is None:
        return {"ok": False,
                "error": f"Unknown game '{game_name}'. Known: {list(_GAME_REGISTRY)}"}

    if not confirm:
        return {
            "ok": True, "dry_run": True, "game": key, "app_id": app_id,
            "message": (
                f"Will open Steam's uninstall dialog for '{key}' (AppID {app_id}). "
                "Ask the user to confirm, then call again with confirm=true."
            ),
        }

    if not _has_steam():
        return {"ok": True, "mock": True, "game": key, "app_id": app_id,
                "note": "steam binary not found; pretending to open uninstall dialog"}

    proc = await asyncio.create_subprocess_exec(
        "steam", f"steam://uninstall/{app_id}",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        env=_session_env(),
    )
    await proc.wait()
    await asyncio.sleep(0.4)
    if not await _steam_running():
        return {"ok": False, "game": key, "app_id": app_id,
                "error": "steam:// URI sent but no Steam process is running "
                         "(see launch_game for likely DBus session cause)."}
    return {"ok": True, "game": key, "app_id": app_id, "pid": proc.pid,
            "note": "Steam uninstall dialog opened — user must confirm in Steam."}


async def list_running_games() -> dict[str, Any]:
    """List processes that look like known games.

    Naive implementation: greps `ps` for the keys we know about.
    """
    if not shutil.which("ps"):
        return {"ok": False, "error": "ps not available"}

    proc = await asyncio.create_subprocess_exec(
        "ps", "-eo", "pid,comm",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    text = out.decode("utf-8", errors="ignore").lower()
    hits = [name for name in _GAME_REGISTRY if name in text]
    return {"ok": True, "running": sorted(set(hits))}
