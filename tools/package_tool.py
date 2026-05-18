"""Flatpak package management + disk usage.

Most Steam Deck apps (emulators, browsers, Discover-store installs) are
Flatpaks, so this module focuses on `flatpak`. Steam games themselves
are handled in steam_tool.py.

All destructive operations (install / uninstall) follow a two-step
confirmation pattern:
  - confirm=False (default) → return a dry-run preview, do nothing
  - confirm=True            → actually perform the operation

The Agent loop is expected to:
  1. call with confirm=False
  2. show the dry-run preview to the user via final_answer
  3. on the next user turn, if they approve, call again with confirm=True
"""

from __future__ import annotations

import asyncio
import shutil
from typing import Any


def _has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


async def _run(*cmd: str) -> tuple[int, str, str]:
    """Run a subprocess and capture (rc, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="ignore"), err.decode(errors="ignore")


# ---------- read-only queries ----------

async def list_flatpak_apps() -> dict[str, Any]:
    """List every installed Flatpak application with its on-disk size."""
    if not _has("flatpak"):
        return {"ok": False, "error": "flatpak not installed"}

    rc, out, err = await _run(
        "flatpak", "list", "--app",
        "--columns=application,name,size",
    )
    if rc != 0:
        return {"ok": False, "error": err.strip() or "flatpak list failed"}

    apps: list[dict[str, str]] = []
    for line in out.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            apps.append({
                "app_id": parts[0],
                "name": parts[1],
                "size": parts[2] if len(parts) > 2 else "",
            })
    return {"ok": True, "count": len(apps), "apps": apps}


async def search_flatpak(query: str) -> dict[str, Any]:
    """Search Flathub for apps matching `query`. Caps results at 20."""
    if not _has("flatpak"):
        return {"ok": False, "error": "flatpak not installed"}

    rc, out, err = await _run(
        "flatpak", "search",
        "--columns=application,name,description",
        query,
    )
    if rc != 0:
        # `flatpak search` exits 1 when there are no results — distinguish.
        if "No matches" in (out + err):
            return {"ok": True, "count": 0, "results": []}
        return {"ok": False, "error": err.strip() or "search failed"}

    results: list[dict[str, str]] = []
    for line in out.strip().splitlines()[:20]:
        parts = line.split("\t")
        if len(parts) >= 2:
            results.append({
                "app_id": parts[0],
                "name": parts[1],
                "description": parts[2] if len(parts) > 2 else "",
            })
    return {"ok": True, "count": len(results), "results": results}


async def disk_usage() -> dict[str, Any]:
    """Return human-readable disk usage for the root + home filesystems."""
    if not _has("df"):
        return {"ok": False, "error": "df not available"}

    rc, out, err = await _run("df", "-h", "/", "/home")
    if rc != 0:
        return {"ok": False, "error": err.strip() or "df failed"}
    return {"ok": True, "output": out.strip()}


# ---------- destructive: install / uninstall ----------

# Flatpak app IDs we refuse to uninstall, with the reason. These are
# shared runtimes that other Flatpak apps depend on — removing one
# breaks every app that builds on it. Matched as a prefix on app_id
# so e.g. "org.freedesktop.Platform.GL.default" is also caught.
_FLATPAK_CRITICAL_PREFIXES: dict[str, str] = {
    "org.freedesktop.Platform":
        "shared runtime that almost every Flatpak app depends on",
    "org.freedesktop.Sdk":
        "shared SDK that almost every Flatpak app depends on",
    "org.freedesktop.BasePlatform":
        "shared base platform that other Flatpak runtimes depend on",
    "org.kde.Platform":
        "KDE runtime — required by most KDE/Qt Flatpak apps on the Deck",
    "org.kde.Sdk":
        "KDE SDK — required by KDE/Qt Flatpak apps",
    "org.gnome.Platform":
        "GNOME runtime — required by GTK Flatpak apps",
    "org.gnome.Sdk":
        "GNOME SDK — required by GTK Flatpak apps",
}


def _flatpak_critical_reason(app_id: str) -> str | None:
    """Return the refusal reason if `app_id` is a protected runtime."""
    for prefix, reason in _FLATPAK_CRITICAL_PREFIXES.items():
        if app_id == prefix or app_id.startswith(prefix + "."):
            return reason
    return None

async def _flatpak_size_of(app_id: str) -> str:
    """Look up the installed size of one app (empty string if not found)."""
    rc, out, _ = await _run(
        "flatpak", "list", "--app", "--columns=application,size",
    )
    if rc != 0:
        return ""
    for line in out.splitlines():
        parts = line.split("\t")
        if parts and parts[0] == app_id:
            return parts[1] if len(parts) > 1 else ""
    return ""


async def install_flatpak(app_id: str, confirm: bool = False) -> dict[str, Any]:
    """Install a Flatpak app from Flathub.

    First call (confirm=False) is a dry run — only returns what *would*
    happen. Second call with confirm=True performs the install.
    """
    if not _has("flatpak"):
        return {"ok": False, "error": "flatpak not installed"}

    if not confirm:
        return {
            "ok": True, "dry_run": True, "app_id": app_id,
            "message": (
                f"Will install '{app_id}' from flathub. "
                "Ask the user to confirm, then call again with confirm=true."
            ),
        }

    rc, out, err = await _run(
        "flatpak", "install", "-y", "--noninteractive", "flathub", app_id,
    )
    return {
        "ok": rc == 0,
        "installed": app_id if rc == 0 else None,
        "stdout_tail": out[-300:],
        "stderr_tail": err[-300:],
    }


async def uninstall_flatpak(app_id: str, confirm: bool = False) -> dict[str, Any]:
    """Uninstall a Flatpak app. Two-step confirmation, same pattern as install.

    Hard-refuses (with reason) if `app_id` is a shared runtime — those
    are dependencies of every other Flatpak app and removing them
    breaks the whole Flatpak install.
    """
    # Hard refusal runs FIRST so it still fires on systems without
    # flatpak — keeps the safety contract consistent.
    critical = _flatpak_critical_reason(app_id)
    if critical is not None:
        return {
            "ok": False, "refused": True, "app_id": app_id,
            "reason": critical,
            "message": (
                f"Refusing to uninstall {app_id!r}: {critical}. "
                "Removing it would break other Flatpak apps that depend on it."
            ),
        }

    if not _has("flatpak"):
        return {"ok": False, "error": "flatpak not installed"}

    if not confirm:
        size = await _flatpak_size_of(app_id)
        return {
            "ok": True, "dry_run": True, "app_id": app_id, "size": size,
            "message": (
                f"Will uninstall '{app_id}' (currently using {size or 'unknown size'}). "
                "Ask the user to confirm, then call again with confirm=true."
            ),
        }

    rc, out, err = await _run(
        "flatpak", "uninstall", "-y", "--noninteractive", app_id,
    )
    return {
        "ok": rc == 0,
        "uninstalled": app_id if rc == 0 else None,
        "stdout_tail": out[-300:],
        "stderr_tail": err[-300:],
    }
