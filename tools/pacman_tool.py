"""Pacman tools — search + install Arch packages, plus a Chinese-mirror switcher.

⚠️ On SteamOS, pacman is a footgun:

  1. /usr is mounted read-only by default. Installs need
     `sudo steamos-readonly disable` first. This tool does NOT do that
     automatically — we refuse on read-only /usr and tell the user to
     toggle it themselves. They're more aware of the risk that way.
  2. Anything installed via pacman is WIPED on the next major SteamOS
     update. Flatpak (persistent) or distrobox (containerised Arch) is
     usually the better path. We surface this warning in every install.
  3. The keyring shipped with SteamOS often goes stale. If install
     fails with key-related errors, the user has to run
     `sudo pacman-key --init && sudo pacman-key --populate archlinux`
     once.

Sudo password prompts:
  We spawn `sudo …` without redirecting stdin. By design sudo writes
  its prompt to /dev/tty (the controlling terminal), so the password
  prompt appears in the same Konsole window the agent is running in.
  The user types the password there. We still capture stdout/stderr
  for the result.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from typing import Any


# Order matters: pacman tries the top entry first. Tsinghua (TUNA)
# is the default per the user's preference. USTC, SJTU, Aliyun, 163
# are CN backups. Global fallback at the bottom.
_CN_MIRRORS: tuple[str, ...] = (
    "https://mirrors.tuna.tsinghua.edu.cn/archlinux/$repo/os/$arch",
    "https://mirrors.ustc.edu.cn/archlinux/$repo/os/$arch",
    "https://mirror.sjtu.edu.cn/archlinux/$repo/os/$arch",
    "https://mirrors.aliyun.com/archlinux/$repo/os/$arch",
    "https://mirrors.163.com/archlinux/$repo/os/$arch",
    "https://geo.mirror.pkgbuild.com/$repo/os/$arch",  # global fallback
)

_MIRRORLIST_PATH = "/etc/pacman.d/mirrorlist"
_BACKUP_PATH = "/etc/pacman.d/mirrorlist.deckmind.bak"


def _has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


async def _run(*cmd: str) -> tuple[int, str, str]:
    """Spawn a subprocess. stdin is NOT redirected — sudo can prompt on tty."""
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


def _is_usr_readonly() -> bool | None:
    """Check whether /usr is mounted read-only (SteamOS's default).

    Returns True/False on Linux, None when we can't tell (e.g. macOS).
    """
    if not os.path.exists("/proc/mounts"):
        return None
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4 and parts[1] == "/usr":
                    return "ro" in parts[3].split(",")
    except OSError:
        return None
    return False


# ---------- search (safe) ----------

async def pacman_search(query: str) -> dict[str, Any]:
    """Search the configured pacman repositories. Read-only, no sudo."""
    if not _has("pacman"):
        return {"ok": False, "error": "pacman not available — not an Arch-based system"}

    rc, out, err = await _run("pacman", "-Ss", query)
    if rc != 0:
        # `pacman -Ss` exits 1 if no matches — distinguish from real errors.
        if not out.strip() and "no targets" not in err.lower():
            return {"ok": False, "error": err.strip() or "search failed"}
        return {"ok": True, "count": 0, "results": []}

    # `pacman -Ss` output is two-line blocks:
    #   "core/bash 5.2.026-2 [installed]"
    #   "    The GNU Bourne Again shell"
    results: list[dict[str, str]] = []
    lines = out.splitlines()
    i = 0
    while i < len(lines):
        head = lines[i]
        if "/" in head and not head.startswith(" "):
            parts = head.split(None, 2)
            if len(parts) >= 2:
                desc = ""
                if i + 1 < len(lines) and lines[i + 1].startswith(" "):
                    desc = lines[i + 1].strip()
                    i += 1
                results.append({
                    "name": parts[0],
                    "version": parts[1],
                    "tags": parts[2] if len(parts) > 2 else "",
                    "description": desc[:140],
                })
        i += 1

    truncated = len(results) > 30
    return {
        "ok": True, "query": query,
        "count": len(results),
        "results": results[:30],
        "truncated": truncated,
    }


# ---------- install (destructive) ----------

_INSTALL_WARNING = (
    "⚠️ 这是 SteamOS。pacman 装的包将在**下次系统更新时被全部抹掉**。"
    "持久的 CLI 工具建议用 distrobox（容器化 Arch），"
    "持久的 GUI 应用建议用 Flatpak。"
)


async def pacman_install(packages: list[str], confirm: bool = False) -> dict[str, Any]:
    """Install one or more pacman packages. DESTRUCTIVE — two-step confirm."""
    if not _has("pacman"):
        return {"ok": False, "error": "pacman not available"}
    if not packages:
        return {"ok": False, "error": "no packages specified"}

    pkgs = [p.strip() for p in packages if p.strip()]
    if not pkgs:
        return {"ok": False, "error": "all package names were empty"}

    # Sanity check on package names — avoid shell-metachar surprises even
    # though we use exec (not shell). Pacman names are [a-zA-Z0-9._+-].
    bad = [p for p in pkgs if not all(c.isalnum() or c in "._+-@" for c in p)]
    if bad:
        return {"ok": False, "refused": True,
                "reason": f"package names contain unexpected characters: {bad}"}

    ro = _is_usr_readonly()
    if ro is True:
        return {
            "ok": False, "refused": True,
            "reason": ("/usr is read-only (SteamOS default). Run "
                       "`sudo steamos-readonly disable` in a terminal first, "
                       "then ask me again. After installing, re-lock with "
                       "`sudo steamos-readonly enable`."),
            "warning": _INSTALL_WARNING,
        }

    if not confirm:
        return {
            "ok": True, "dry_run": True,
            "packages": pkgs,
            "command_preview": f"sudo pacman -Sy --noconfirm --needed {' '.join(pkgs)}",
            "warning": _INSTALL_WARNING,
            "sudo_note": ("sudo 会在你的终端弹密码提示 —— 直接输入回车即可。"),
            "message": "Ask user to confirm, then call again with confirm=true.",
        }

    # `--needed` skips already-installed; `--noconfirm` answers any pacman
    # prompt with the default. We still rely on sudo's tty prompt for the
    # user's password.
    rc, out, err = await _run(
        "sudo", "pacman", "-Sy", "--noconfirm", "--needed", *pkgs,
    )

    payload: dict[str, Any] = {
        "ok": rc == 0,
        "returncode": rc,
        "stdout_tail": out[-600:],
        "stderr_tail": err[-600:],
    }
    if rc == 0:
        payload["installed"] = pkgs
    else:
        payload["failed"] = pkgs
        # Common-error hints so the LLM can give actionable advice.
        combined = (out + err).lower()
        if "key" in combined and ("could not" in combined or "unknown trust" in combined):
            payload["hint"] = (
                "Keyring issue — try: sudo pacman-key --init && "
                "sudo pacman-key --populate archlinux  (then retry the install)"
            )
        elif "read-only" in combined:
            payload["hint"] = (
                "/usr became read-only mid-install. Run "
                "`sudo steamos-readonly disable` and retry."
            )
    return payload


# ---------- mirror switcher (destructive) ----------

async def set_pacman_mirror_china(confirm: bool = False) -> dict[str, Any]:
    """Replace /etc/pacman.d/mirrorlist with Chinese mirrors. Backs up first.

    DESTRUCTIVE — needs sudo. Original is backed up to
    /etc/pacman.d/mirrorlist.deckmind.bak the first time we run.
    """
    if not _has("pacman"):
        return {"ok": False, "error": "pacman not available"}

    header = (
        "##\n"
        "## Arch Linux mirrorlist — configured by DeckMind.\n"
        "## Chinese mirrors first, global fallback at the bottom.\n"
        "## Original is backed up to /etc/pacman.d/mirrorlist.deckmind.bak\n"
        "## (only the first time we install; re-runs preserve the backup).\n"
        "##\n\n"
    )
    body = "\n".join(f"Server = {m}" for m in _CN_MIRRORS) + "\n"
    content = header + body

    if not confirm:
        return {
            "ok": True, "dry_run": True,
            "target": _MIRRORLIST_PATH,
            "backup_path": _BACKUP_PATH,
            "backup_already_exists": os.path.exists(_BACKUP_PATH),
            "mirrors": list(_CN_MIRRORS),
            "preview": content,
            "sudo_note": "sudo 会在你的终端弹密码提示。",
            "post_step": "建议执行 `sudo pacman -Syy` 刷新数据库。",
            "message": "Ask user to confirm, then call again with confirm=true.",
        }

    # Write to a temp file (no sudo), then `sudo install` it into place.
    # Doing it this way avoids needing `sudo tee` with redirection.
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".mirrorlist", delete=False, encoding="utf-8",
        ) as f:
            f.write(content)
            tmp_path = f.name

        if not os.path.exists(_BACKUP_PATH):
            rc, _, err = await _run("sudo", "cp", _MIRRORLIST_PATH, _BACKUP_PATH)
            if rc != 0:
                return {"ok": False,
                        "error": f"backup failed: {err.strip() or '(empty)'}"}

        rc, _, err = await _run(
            "sudo", "install", "-m", "644", "-o", "root", "-g", "root",
            tmp_path, _MIRRORLIST_PATH,
        )
        if rc != 0:
            return {"ok": False,
                    "error": f"install failed: {err.strip() or '(empty)'}"}

        return {
            "ok": True, "written": True,
            "mirrorlist": _MIRRORLIST_PATH,
            "backup_at": _BACKUP_PATH,
            "mirrors_used": list(_CN_MIRRORS),
            "next_step": ("现在镜像已切到国内。建议执行 "
                          "`sudo pacman -Syy` 刷新数据库（一次性，几秒钟）。"),
        }
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
