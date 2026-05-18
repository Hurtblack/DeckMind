"""Device context — gathered once at agent startup and injected into
the system prompt so the LLM has a baseline picture of the machine.

Cheap reads only (sysfs / subprocess / file globbing). Refresh by
restarting the agent. Tools are still the source of truth for live
values; the snapshot just lets the LLM answer common questions ("我装了哪些游戏？", "还剩多少电？") without round-tripping.
"""

from __future__ import annotations

import asyncio
import glob
import os
import re
import shutil
from typing import Any


# ---------- subprocess helper ----------

async def _run(*cmd: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="ignore")


# ---------- Steam library scanner ----------

# Default Steam install locations on Linux. We also follow paths listed
# in libraryfolders.vdf so SD-card / external-drive libraries are seen.
_STEAM_DIRS: tuple[str, ...] = (
    "~/.steam/steam/steamapps",
    "~/.local/share/Steam/steamapps",
)


def scan_steam_library() -> list[dict[str, str]]:
    """Return [{appid, name}, ...] for every locally installed Steam game.

    Reads `appmanifest_*.acf` from every known library folder. Dedup by
    appid. Result is sorted by name.
    """
    games: dict[str, str] = {}
    extra_dirs: list[str] = []

    # Discover extra library folders (SD card / external drive).
    for base in _STEAM_DIRS:
        lf = os.path.expanduser(os.path.join(base, "libraryfolders.vdf"))
        if os.path.exists(lf):
            try:
                text = open(lf, encoding="utf-8", errors="ignore").read()
                for m in re.finditer(r'"path"\s+"([^"]+)"', text):
                    extra_dirs.append(os.path.join(m.group(1), "steamapps"))
            except OSError:
                continue

    for base in list(_STEAM_DIRS) + extra_dirs:
        pattern = os.path.expanduser(os.path.join(base, "appmanifest_*.acf"))
        for fn in glob.glob(pattern):
            try:
                text = open(fn, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            m_app = re.search(r'"appid"\s+"(\d+)"', text)
            m_name = re.search(r'"name"\s+"([^"]+)"', text)
            if m_app and m_name:
                games[m_app.group(1)] = m_name.group(1)

    return [{"appid": a, "name": n}
            for a, n in sorted(games.items(), key=lambda kv: kv[1].lower())]


# ---------- full context snapshot ----------

async def gather_context() -> dict[str, Any]:
    """Snapshot battery / volume / disk / steam library / flatpak apps."""
    ctx: dict[str, Any] = {}

    try:
        ctx["hostname"] = os.uname().nodename
    except OSError:
        pass

    # Battery (first device that exposes 'capacity').
    sysfs = "/sys/class/power_supply"
    if os.path.isdir(sysfs):
        for name in sorted(os.listdir(sysfs)):
            cap_path = f"{sysfs}/{name}/capacity"
            try:
                with open(cap_path) as f:
                    ctx["battery_percent"] = int(f.read().strip())
                try:
                    with open(f"{sysfs}/{name}/status") as f:
                        ctx["battery_status"] = f.read().strip()
                except OSError:
                    pass
                break
            except (OSError, ValueError):
                continue

    # Disk usage of /home (where games live on the Deck).
    if shutil.which("df"):
        rc, out = await _run("df", "-h", "/home")
        lines = out.strip().splitlines()
        if rc == 0 and len(lines) >= 2:
            parts = lines[-1].split()
            if len(parts) >= 5:
                ctx["disk_home"] = {
                    "size": parts[1], "used": parts[2],
                    "free": parts[3], "percent": parts[4],
                }

    # Volume (PipeWire preferred, then ALSA).
    if shutil.which("wpctl"):
        rc, out = await _run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@")
        m = re.search(r"([0-9.]+)", out)
        if rc == 0 and m:
            ctx["volume_percent"] = int(float(m.group(1)) * 100)

    # Steam library.
    ctx["steam_games"] = scan_steam_library()

    # User profile (cross-session memory).
    from .profile import load_profile
    ctx["user_profile"] = load_profile()

    # SteamOS dangling-unlock check: if a previous pacman_install left
    # /usr unlocked (e.g. agent crashed), surface it loudly so the LLM
    # can tell the user to relock. Best-effort; non-Linux gives None.
    try:
        from tools.steamos_lock import is_usr_readonly, load_state
        ro = is_usr_readonly()
        record = load_state()
        if record and ro is False:
            ctx["steamos_dangling_unlock"] = {
                "unlocked_at": record.get("unlocked_by_us_at"),
                "reason": record.get("reason"),
            }
    except Exception:
        # Never let a context-collection failure block agent startup.
        pass

    # Flatpak apps (Steam Deck users install most extra software this way).
    if shutil.which("flatpak"):
        rc, out = await _run(
            "flatpak", "list", "--app", "--columns=application,name",
        )
        if rc == 0:
            apps: list[dict[str, str]] = []
            for line in out.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    apps.append({"app_id": parts[0], "name": parts[1]})
            ctx["flatpak_apps"] = apps

    return ctx


def format_context_for_prompt(ctx: dict[str, Any]) -> str:
    """Render the context dict as a section to append to the system prompt."""
    sections: list[str] = []

    # Profile section first — most important for personalization.
    from .profile import format_profile_for_prompt
    profile_block = format_profile_for_prompt(ctx.get("user_profile") or {})
    if profile_block:
        sections.append(profile_block)

    lines: list[str] = ["=== DEVICE CONTEXT (auto-collected at startup) ==="]

    if "hostname" in ctx:
        lines.append(f"Hostname: {ctx['hostname']}")
    if "battery_percent" in ctx:
        st = ctx.get("battery_status", "?")
        lines.append(f"Battery: {ctx['battery_percent']}% ({st})")
    if "volume_percent" in ctx:
        lines.append(f"Volume: {ctx['volume_percent']}%")
    if "disk_home" in ctx:
        d = ctx["disk_home"]
        lines.append(
            f"Disk /home: {d['used']} used / {d['size']} total "
            f"({d['percent']} full, {d['free']} free)"
        )

    danger = ctx.get("steamos_dangling_unlock")
    if danger:
        lines.append("")
        lines.append("⚠️ STEAMOS DANGLING UNLOCK DETECTED")
        lines.append(f"  We unlocked /usr at {danger.get('unlocked_at')} "
                     f"for reason: {danger.get('reason')}")
        lines.append("  /usr is STILL unlocked. Tell the user this and offer "
                     "to call steamos_lock to re-lock right now.")

    games = ctx.get("steam_games") or []
    if games:
        lines.append("")
        lines.append(f"Steam library ({len(games)} installed):")
        for g in games:
            lines.append(f"  - {g['name']}  [appid {g['appid']}]")
    else:
        lines.append("\nSteam library: none detected.")

    apps = ctx.get("flatpak_apps") or []
    if apps:
        lines.append("")
        lines.append(f"Flatpak apps ({len(apps)} installed):")
        # Cap to keep prompt cheap. Tools can still query the full list.
        for a in apps[:40]:
            lines.append(f"  - {a['name']}  [{a['app_id']}]")
        if len(apps) > 40:
            lines.append(f"  ... and {len(apps) - 40} more (use list_flatpak_apps to see all)")

    lines.append("")
    lines.append("Use this context to answer questions about the device "
                 "WITHOUT calling tools when you can. Call tools only "
                 "when you need to ACT or fetch a fresher value.")
    lines.append("=== END CONTEXT ===")
    sections.append("\n".join(lines))

    return "\n\n".join(sections)
