"""File-system utilities — search for files, list processes.

These are READ-ONLY operations that wrap `find` and `ps`. They don't
modify anything. Useful for answering "where is X installed?" /
"is X running?" without resorting to press_key hallucinations or
making the user drop to a separate terminal.

Both tools cap their output so a stray `find ~/` doesn't dump 100k
paths back into the LLM context.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from typing import Any


# Path patterns we always skip during search — caches, trash, vendor
# directories that bloat results and confuse the user. The Steam library
# itself (~/.steam) is left in because users sometimes want to find
# Proton prefixes etc.
_DEFAULT_EXCLUDES: tuple[str, ...] = (
    "*/.cache/*",
    "*/.local/share/Trash/*",
    "*/.local/share/baloo/*",
    "*/node_modules/*",
    "*/.git/*",
    "*/proc/*",
    "*/sys/*",
)


async def _run(*cmd: str) -> tuple[int, str, str]:
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


async def find_files(
    pattern: str,
    base_dir: str = "~",
    max_depth: int = 6,
    max_results: int = 30,
    case_insensitive: bool = True,
) -> dict[str, Any]:
    """Search for files matching a glob pattern under base_dir.

    Examples:
      find_files("*clash*verge*")              -> any path with both
      find_files("*.AppImage", "~/Downloads")  -> AppImages in Downloads
      find_files("config.toml", "~/.config", max_depth=3)
    """
    if not shutil.which("find"):
        return {"ok": False, "error": "find not available on this system"}

    base = os.path.expanduser(base_dir or "~")
    if not os.path.isdir(base):
        return {"ok": False, "error": f"directory does not exist: {base_dir}"}

    name_flag = "-iname" if case_insensitive else "-name"
    cmd: list[str] = [
        "find", base,
        "-maxdepth", str(int(max_depth)),
        "-type", "f",
        name_flag, pattern,
    ]
    for excl in _DEFAULT_EXCLUDES:
        cmd += ["-not", "-path", excl]

    rc, out, err = await _run(*cmd)
    # `find` exits non-zero on permission-denied subdirs, but still
    # returns useful matches — treat as best-effort success.
    paths = [p for p in out.splitlines() if p.strip()]
    truncated = len(paths) > max_results

    return {
        "ok": True,
        "pattern": pattern,
        "base": base,
        "count": len(paths),
        "matches": paths[:max_results],
        "truncated": truncated,
        "stderr_tail": err[-200:] if err else "",
    }


async def list_processes(
    filter: str | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    """List running processes. If `filter` is given, keep only rows that
    contain it (case-insensitive substring on command + args).
    """
    if not shutil.which("ps"):
        return {"ok": False, "error": "ps not available on this system"}

    # `--no-headers` is GNU-only — BSD/macOS ps rejects it. Always
    # request the headerful form and strip the first line ourselves so
    # this works on both Steam Deck (Linux/GNU) and developer Macs.
    rc, out, err = await _run("ps", "-eo", "pid,user,comm,args")
    if rc != 0:
        return {"ok": False, "error": err.strip() or "ps failed"}

    needle = (filter or "").lower().strip() or None
    rows: list[dict[str, Any]] = []
    for line in out.splitlines()[1:]:        # drop header row
        if needle and needle not in line.lower():
            continue
        # First 3 cols are fixed-width-ish; everything after is the cmdline.
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        rows.append({
            "pid": pid,
            "user": parts[1],
            "comm": parts[2],
            # Cap each cmdline at 200 chars so a single weird process
            # can't blow up the LLM context.
            "args": parts[3][:200],
        })

    truncated = len(rows) > limit
    return {
        "ok": True,
        "filter": filter,
        "count": len(rows),
        "processes": rows[:limit],
        "truncated": truncated,
    }
