"""Persistent user profile — small JSON file of facts the user has shared.

Lives at ~/.deckmind/profile.json. Loaded into the system prompt at
startup so every turn sees what the user has previously told us.
Updated via the `remember` / `forget` tools.

Schema: a flat key→value map (both strings). Keys describe the kind of
fact ("name", "favorite_genre", "play_schedule"), values are short
free-form text. Keep entries small; this is a personalization layer,
not a knowledge base.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


PROFILE_DIR: Path = Path.home() / ".deckmind"
PROFILE_FILE: Path = PROFILE_DIR / "profile.json"


def load_profile() -> dict[str, str]:
    """Return the saved facts. Empty dict if no file or unreadable."""
    if not PROFILE_FILE.exists():
        return {}
    try:
        raw = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    facts = raw.get("facts") if isinstance(raw, dict) else None
    if not isinstance(facts, dict):
        return {}
    # Coerce everything to str so downstream code doesn't trip on
    # numbers or nested objects that may have crept in via direct edits.
    return {str(k): str(v) for k, v in facts.items()}


def save_profile(facts: dict[str, str]) -> None:
    """Write facts to disk. Creates the directory if missing."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "facts": facts,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    # Pretty-print with UTF-8 so the user can hand-edit if they want.
    PROFILE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def format_profile_for_prompt(facts: dict[str, str]) -> str:
    """Render the profile as a system-prompt section. Empty if no facts."""
    if not facts:
        return ""
    lines = ["=== USER PROFILE (things the user has told you in past sessions) ==="]
    for k, v in facts.items():
        lines.append(f"  - {k}: {v}")
    lines.append("")
    lines.append("Use this to personalize replies. If the user shares a new "
                 "fact about themselves, call `remember`. If they ask you "
                 "to forget something, call `forget`.")
    lines.append("=== END USER PROFILE ===")
    return "\n".join(lines)
