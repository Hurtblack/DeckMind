"""Build a user-session environment for subprocess calls.

When DeckMind runs under Decky's `plugin_loader.service` (systemd, started
as root before the user logs in), DBus / Wayland / X env vars are not
inherited. Tools like `wpctl`, `steam`, `pactl` then exit 0 but silently
no-op because they cannot reach the session bus. The caller mistakes
`returncode == 0` for success.

`session_env()` reconstructs the missing vars by resolving the desktop
user (`deck` by default) and pointing at their `/run/user/<uid>` paths,
so subprocesses talk to the right DBus session.
"""

from __future__ import annotations

import os
import pwd
from pathlib import Path

_DEFAULT_TARGET_USER = "deck"

# Env vars that GUI / session tools rely on.
_SESSION_ENV_KEYS: tuple[str, ...] = (
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS",
    "XDG_CURRENT_DESKTOP",
    "DESKTOP_SESSION",
    "PULSE_SERVER",
)


def _resolve_uid() -> int | None:
    name = os.environ.get("DECKMIND_TARGET_USER", _DEFAULT_TARGET_USER)
    try:
        return pwd.getpwnam(name).pw_uid
    except KeyError:
        pass

    own = os.getuid()
    if own != 0:
        return own

    # Last resort: a single non-root /run/user/<uid> directory.
    try:
        candidates = [
            int(p.name) for p in Path("/run/user").iterdir()
            if p.is_dir() and p.name.isdigit() and int(p.name) != 0
        ]
    except OSError:
        return None
    return candidates[0] if len(candidates) == 1 else None


def session_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Return an env dict with session vars filled in.

    Only fills keys that are missing — never overwrites caller-provided
    values, so explicit configuration always wins.
    """
    env = dict(base) if base is not None else dict(os.environ)

    # Carry through anything the host process already has.
    for key in _SESSION_ENV_KEYS:
        host = os.environ.get(key)
        if host and key not in env:
            env[key] = host

    uid = _resolve_uid()
    if uid is not None:
        runtime_dir = f"/run/user/{uid}"
        env.setdefault("XDG_RUNTIME_DIR", runtime_dir)
        bus_path = f"{runtime_dir}/bus"
        if os.path.exists(bus_path):
            env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={bus_path}")
        pulse_path = f"{runtime_dir}/pulse/native"
        if os.path.exists(pulse_path):
            env.setdefault("PULSE_SERVER", f"unix:{pulse_path}")

    # GUI defaults — SteamOS Game Mode uses wayland-0; Plasma desktop uses :0.
    env.setdefault("DISPLAY", ":0")
    env.setdefault("WAYLAND_DISPLAY", "wayland-0")
    return env
