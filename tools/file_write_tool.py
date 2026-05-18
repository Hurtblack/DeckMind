"""Read/write small text files inside whitelisted user directories.

The write side is the dangerous half — restricted to a fixed list of
"things a Steam Deck user reasonably edits" so the LLM cannot
accidentally clobber sensitive files. Walls:

  1. Only paths inside _WRITE_BASES (resolved to absolute paths so
     "../" can't escape).
  2. Refuses any path whose absolute form contains a known-sensitive
     fragment (~/.ssh, *secret*, *credential*, etc.) — defense in
     depth in case a future base is added that overlaps.
  3. Refuses symlinks — those could be a permitted-looking path that
     redirects elsewhere on disk.
  4. Hard cap on content size (100 KB) so an LLM hallucination can't
     fill the disk.
  5. Two-step confirmation: confirm=False shows a dry-run preview;
     confirm=True actually writes.

The read side uses a wider whitelist (most of $HOME plus read-only
system info like /etc/os-release and /proc/cpuinfo) since reading is
strictly safer.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


# Where the agent is allowed to WRITE. These are common config and
# user-content locations on a Steam Deck. Anything else → refuse.
_WRITE_BASES: tuple[str, ...] = (
    "~/.config/autostart",       # KDE/GNOME autostart .desktop entries
    "~/.config/systemd/user",    # user-level systemd services
    "~/.local/share/applications",  # custom .desktop entries
    "~/.deckmind",               # our own config dir
    "~/Documents",
    "~/Desktop",
    "~/Downloads",
)

# Where the agent is allowed to READ. Strict superset of the write list.
_READ_BASES: tuple[str, ...] = _WRITE_BASES + (
    "~/.config",                 # most app configs
    "~/.local/share",            # most app data
    "~/.bashrc",                 # individual files we allow as bases
    "~/.bash_profile",
    "~/.zshrc",
    "~/.profile",
    "/etc/os-release",
    "/etc/hostname",
    "/proc/cpuinfo",
    "/proc/meminfo",
    "/proc/version",
)

# Fragments we refuse to touch even when the parent dir is whitelisted.
# Case-insensitive substring match on the resolved absolute path.
_PATH_DENYLIST: tuple[str, ...] = (
    "/.ssh", "/.gnupg", "/.aws", "/.docker", "/.kube",
    "/.password", "/.credentials", "id_rsa", "id_ed25519",
    "/secrets", "/private",
)

_MAX_WRITE_BYTES = 100 * 1024     # 100 KB
_MAX_READ_BYTES_CAP = 64 * 1024   # 64 KB read at most


def _expand(p: str) -> Path:
    """Expand ~ and resolve to an absolute Path. Symlinks are NOT resolved
    (we want to detect them, not silently follow them)."""
    return Path(os.path.expanduser(p)).absolute()


def _is_within(child: Path, parent: Path) -> bool:
    """True if `child` equals or is nested under `parent`."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate(path: str, *, for_write: bool) -> tuple[Path | None, str | None]:
    """Return (resolved_path, None) on success, or (None, reason) on refusal."""
    if not path or not path.strip():
        return None, "empty path"

    resolved = _expand(path)

    # Sensitive-fragment denylist (case-insensitive substring).
    lower = str(resolved).lower()
    for bad in _PATH_DENYLIST:
        if bad in lower:
            return None, (
                f"path contains denylisted fragment '{bad}' — refusing to "
                f"touch credential / secret files even inside otherwise-"
                f"allowed directories"
            )

    bases = _WRITE_BASES if for_write else _READ_BASES
    allowed = [_expand(b) for b in bases]
    if not any(resolved == b or _is_within(resolved, b) for b in allowed):
        return None, (
            f"path is outside allowed directories for "
            f"{'writing' if for_write else 'reading'}. Allowed:\n  "
            + "\n  ".join(bases)
        )

    return resolved, None


# ---------- public tools ----------

async def write_text_file(
    path: str,
    content: str,
    confirm: bool = False,
) -> dict[str, Any]:
    """Write text content to a file inside a whitelisted directory.

    confirm=False (default) returns a dry-run preview without touching
    disk. confirm=True writes (parent dirs created if missing). Refuses
    paths outside the whitelist, paths containing sensitive fragments,
    symlinks, and content over 100 KB.
    """
    resolved, err = _validate(path, for_write=True)
    if err:
        return {"ok": False, "refused": True, "reason": err}

    body = content or ""
    body_bytes = body.encode("utf-8")
    if len(body_bytes) > _MAX_WRITE_BYTES:
        return {
            "ok": False, "refused": True,
            "reason": f"content is {len(body_bytes)} bytes; max allowed is "
                      f"{_MAX_WRITE_BYTES} ({_MAX_WRITE_BYTES // 1024} KB)",
        }

    # Symlinks could escape the whitelist — refuse to overwrite them.
    if resolved.is_symlink():
        return {"ok": False, "refused": True,
                "reason": f"refusing to overwrite a symbolic link: {resolved}"}

    existed = resolved.exists() and not resolved.is_symlink()
    existing_size = (
        resolved.stat().st_size if existed and resolved.is_file() else None
    )

    if not confirm:
        # Truncate the preview so the LLM context stays small even if
        # the body is large.
        preview = body if len(body) <= 600 else (body[:600] + "\n…[truncated]")
        return {
            "ok": True, "dry_run": True,
            "path": str(resolved),
            "will_overwrite": existed,
            "existing_size_bytes": existing_size,
            "new_size_bytes": len(body_bytes),
            "preview": preview,
            "message": ("Show this preview to the user and ask them to "
                        "confirm, then call again with confirm=true."),
        }

    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(body, encoding="utf-8")

    return {
        "ok": True, "written": True,
        "path": str(resolved),
        "bytes": len(body_bytes),
        "overwrote": existed,
    }


async def read_text_file(
    path: str,
    max_bytes: int = 16 * 1024,
) -> dict[str, Any]:
    """Read up to `max_bytes` of a text file inside a whitelisted location."""
    resolved, err = _validate(path, for_write=False)
    if err:
        return {"ok": False, "refused": True, "reason": err}

    if not resolved.exists():
        return {"ok": False, "error": f"file does not exist: {resolved}"}
    if resolved.is_symlink():
        return {"ok": False, "refused": True,
                "reason": f"refusing to follow a symbolic link: {resolved}"}
    if not resolved.is_file():
        return {"ok": False, "error": f"not a regular file: {resolved}"}

    cap = max(1, min(int(max_bytes), _MAX_READ_BYTES_CAP))
    size = resolved.stat().st_size

    try:
        with open(resolved, "r", encoding="utf-8") as f:
            text = f.read(cap)
    except UnicodeDecodeError:
        return {"ok": False, "error": "file is not valid UTF-8 (binary?)"}
    except OSError as e:
        return {"ok": False, "error": str(e)}

    return {
        "ok": True,
        "path": str(resolved),
        "size_bytes": size,
        "bytes_read": len(text.encode("utf-8")),
        "truncated": size > cap,
        "content": text,
    }
