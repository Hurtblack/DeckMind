"""Self-update — fetch the agent's own source from `origin` and re-sync deps.

Restricted by design:
  - Operates ONLY inside the project directory (parent of this file).
  - Talks to whichever `origin` remote is already configured locally.
    We never accept a URL from the LLM, so the LLM cannot redirect the
    update to a different repository.
  - Refuses to overwrite uncommitted local changes.
  - Uses `--ff-only` so a divergent history will fail loudly instead of
    silently merging.
  - The new code only takes effect after the user restarts the agent;
    Python keeps the old modules cached in this process.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any


# The project root = the directory containing this file's parent
# (tools/) — i.e. the repo root. Resolved once at import time.
_PROJECT_DIR: Path = Path(__file__).resolve().parent.parent


async def _git(*args: str) -> tuple[int, str, str]:
    """Run a git command inside the project directory."""
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=str(_PROJECT_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return (
        proc.returncode or 0,
        out.decode(errors="ignore").strip(),
        err.decode(errors="ignore").strip(),
    )


def _preflight() -> dict[str, Any] | None:
    """Return an error dict if the environment isn't usable for updates."""
    if not shutil.which("git"):
        return {"ok": False, "error": "git is not installed"}
    if not (_PROJECT_DIR / ".git").exists():
        return {"ok": False,
                "error": "project is not a git checkout — cannot self-update"}
    return None


# ---------- read-only ----------

async def check_for_updates() -> dict[str, Any]:
    """Fetch from `origin` and report how far behind we are."""
    err = _preflight()
    if err:
        return err

    rc, _, stderr = await _git("fetch", "--quiet")
    if rc != 0:
        return {"ok": False, "error": f"git fetch failed: {stderr or '(no message)'}"}

    rc, local, _ = await _git("rev-parse", "HEAD")
    if rc != 0:
        return {"ok": False, "error": "could not read HEAD commit"}

    rc, remote, _ = await _git("rev-parse", "@{u}")
    if rc != 0:
        return {"ok": False,
                "error": "current branch has no upstream — set one with "
                         "`git branch --set-upstream-to=origin/main`"}

    if local == remote:
        return {"ok": True, "up_to_date": True, "commit": local[:7]}

    rc, log, _ = await _git("log", "--oneline", "HEAD..@{u}")
    new_commits = log.splitlines()[:20] if log else []

    rc, status, _ = await _git("status", "--porcelain")
    dirty_files = status.splitlines() if status else []

    return {
        "ok": True,
        "up_to_date": False,
        "local": local[:7],
        "remote": remote[:7],
        "behind_by": len(new_commits),
        "new_commits": new_commits,
        "local_modifications": bool(dirty_files),
        "local_modifications_files": dirty_files,
    }


# ---------- destructive ----------

async def apply_update(confirm: bool = False) -> dict[str, Any]:
    """`git pull --ff-only` + `uv sync`. Two-step confirmation."""
    err = _preflight()
    if err:
        return err

    if not confirm:
        preview = await check_for_updates()
        if not preview.get("ok"):
            return preview
        if preview.get("up_to_date"):
            return {"ok": True, "dry_run": True, "up_to_date": True,
                    "message": f"Already up to date at {preview['commit']}."}
        return {
            "ok": True, "dry_run": True,
            "from": preview["local"], "to": preview["remote"],
            "behind_by": preview["behind_by"],
            "new_commits": preview["new_commits"],
            "local_modifications": preview["local_modifications"],
            "message": (
                "Ask the user to confirm, then call again with confirm=true. "
                "After updating, the agent must be restarted to load the new code."
            ),
        }

    # Refuse outright if the working tree is dirty — pulling would
    # either fail or destroy uncommitted work.
    rc, status, _ = await _git("status", "--porcelain")
    dirty = status.splitlines() if status else []
    if dirty:
        return {
            "ok": False, "refused": True,
            "reason": ("uncommitted local changes present — refusing to pull "
                       "to avoid losing work"),
            "files": dirty,
            "hint": "Commit, stash, or discard the changes manually first.",
        }

    rc, pull_out, pull_err = await _git("pull", "--ff-only")
    if rc != 0:
        return {"ok": False,
                "error": f"git pull failed: {pull_err or pull_out or '(no message)'}"}

    # Pick up new HEAD for the response.
    _, new_head, _ = await _git("rev-parse", "HEAD")

    # Best-effort dependency refresh. Failing here is non-fatal — the
    # code is updated, the user can rerun `uv sync` manually.
    sync_status = "skipped (uv not on PATH)"
    if shutil.which("uv"):
        proc = await asyncio.create_subprocess_exec(
            "uv", "sync",
            cwd=str(_PROJECT_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err_bytes = await proc.communicate()
        if proc.returncode == 0:
            sync_status = "ok"
        else:
            tail = err_bytes.decode(errors="ignore")[-400:]
            sync_status = f"failed: {tail}"

    return {
        "ok": True, "updated": True,
        "new_head": new_head[:7],
        "pull_output_tail": pull_out[-300:],
        "uv_sync": sync_status,
        "message": (
            "Updated. Type `exit` and relaunch (`uv run python ./main.py`) "
            "to load the new code — Python has the old modules cached in "
            "this process."
        ),
    }
