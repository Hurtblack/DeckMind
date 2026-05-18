"""Steam-related tools.

These are intentionally simple. On a real Steam Deck you would use the
`steam steam://rungameid/<id>` URI scheme or `flatpak run` to launch
games. Here we use shell commands with safe fallbacks so the agent can
run on a developer machine as well.
"""

from __future__ import annotations

import asyncio
import shutil
from typing import Any

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


async def launch_game(game_name: str) -> dict[str, Any]:
    """Launch a game by friendly name.

    Uses Steam's URI scheme when available, otherwise returns a mock result.
    """
    key = game_name.strip().lower()
    app_id = _GAME_REGISTRY.get(key)

    if app_id is None:
        return {"ok": False, "error": f"Unknown game '{game_name}'. Known: {list(_GAME_REGISTRY)}"}

    if not _has_steam():
        # Mock branch — useful on macOS / CI / dev machines.
        return {"ok": True, "mock": True, "game": key, "app_id": app_id,
                "note": "steam binary not found; pretending to launch"}

    # Fire-and-forget: don't block on the game process.
    proc = await asyncio.create_subprocess_exec(
        "steam", f"steam://rungameid/{app_id}",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    return {"ok": True, "game": key, "app_id": app_id, "pid": proc.pid}


# Substrings we refuse to pkill — killing any of these would brick the
# session or the desktop. Matched case-insensitively against process_name.
_CLOSE_GAME_DENYLIST: tuple[str, ...] = (
    "steam", "systemd", "pulseaudio", "pipewire", "wpctl",
    "kwin", "plasma", "kded", "konsole", "xorg", "wayland", "gamescope",
    "sshd", "bash", "zsh", "python", "init", "kernel",
    "dbus", "polkit", "udev", "networkmanager",
)


async def close_game(process_name: str) -> dict[str, Any]:
    """Kill a running game by process name using `pkill -f`.

    Dangerous inputs (too short, or containing a denylisted substring)
    trigger an extra warning prompt — the user can still approve. We
    never refuse outright.
    """
    if not shutil.which("pkill"):
        return {"ok": False, "error": "pkill not available on this system"}

    # Local import to avoid a top-level dependency on the runtime package.
    from runtime.prompt import ask, is_yes

    name = (process_name or "").strip()

    if len(name) < 3:
        ans = await ask(
            f"    ⚠ very short process_name {name!r} — pkill -f will match "
            f"a LOT of processes. Continue? [y/n] > "
        )
        if not is_yes(ans):
            return {"ok": False, "denied": True,
                    "reason": "user declined short process_name"}

    lower = name.lower()
    for bad in _CLOSE_GAME_DENYLIST:
        if bad in lower:
            ans = await ask(
                f"    🚨 process_name contains {bad!r} — this may kill a "
                f"system process and break your session. Continue? [y/n] > "
            )
            if not is_yes(ans):
                return {"ok": False, "denied": True,
                        "reason": f"user declined denylisted match on {bad!r}"}
            break  # one warning is enough — don't pile prompts

    proc = await asyncio.create_subprocess_exec(
        "pkill", "-f", name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
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
    )
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
    )
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
