"""Notion logbook tools — write game-session records into a Notion database.

Configuration via environment variables (set them in ~/.bashrc on the Deck):
  NOTION_API_KEY      — required. Internal integration token (ntn_xxx).
  NOTION_DATABASE_ID  — required. 32-char ID of the database to log into.

You do NOT need to touch this file when you set those up. The code is
already shipped; setting the env vars and restarting the agent is all
that's needed.

Schema convention (by FIELD TYPE, not name — works with any layout):
  - Title          → game name
  - First Number   → minutes played
  - First Date     → session date (defaults to today)
  - First Rich Text → optional notes
"""

from __future__ import annotations

import datetime
import os
from typing import Any

import httpx  # bundled via the openai SDK; no extra install needed


NOTION_VERSION = "2022-06-28"
API_BASE = "https://api.notion.com/v1"


# ---------- env + http helpers ----------

def _key() -> str | None:
    v = os.environ.get("NOTION_API_KEY")
    return v if v else None


def _db() -> str | None:
    v = os.environ.get("NOTION_DATABASE_ID")
    return v if v else None


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_key()}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


async def _request(
    method: str, path: str, **kwargs: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Make a Notion API call. Returns (data, err) — exactly one is None."""
    if not _key():
        return None, {"ok": False, "error": "NOTION_API_KEY not set"}
    async with httpx.AsyncClient(timeout=20.0) as cli:
        try:
            r = await cli.request(method, f"{API_BASE}{path}",
                                  headers=_headers(), **kwargs)
        except httpx.HTTPError as e:
            return None, {"ok": False, "error": f"network error: {e}"}
    if r.status_code >= 400:
        # Truncate the body — Notion errors can be verbose.
        return None, {"ok": False,
                      "error": f"Notion {r.status_code}: {r.text[:300]}"}
    return r.json(), None


# ---------- schema cache (per process) ----------

# Maps database_id -> {"title": "name", "number": "name", "date": "name",
#                      "rich_text": "name", "_props": {name: type},
#                      "title_text": "DB display title"}
_schema_cache: dict[str, dict[str, Any]] = {}


async def _schema(db_id: str) -> dict[str, Any] | None:
    """Fetch + cache the database property schema for this process."""
    if db_id in _schema_cache:
        return _schema_cache[db_id]
    data, err = await _request("GET", f"/databases/{db_id}")
    if err:
        return None
    props_meta = data.get("properties", {})
    types = {name: p["type"] for name, p in props_meta.items()}
    schema = {
        "_props": types,
        "title": next((n for n, t in types.items() if t == "title"), None),
        "number": next((n for n, t in types.items() if t == "number"), None),
        "date": next((n for n, t in types.items() if t == "date"), None),
        "rich_text": next((n for n, t in types.items() if t == "rich_text"), None),
        "title_text": "".join(t.get("plain_text", "")
                              for t in data.get("title", [])),
    }
    _schema_cache[db_id] = schema
    return schema


def _flatten_page(page: dict[str, Any]) -> dict[str, Any]:
    """Pull readable values out of a Notion page object — for display."""
    out: dict[str, Any] = {}
    for name, prop in page.get("properties", {}).items():
        t = prop.get("type")
        if t == "title":
            out[name] = "".join(s.get("plain_text", "") for s in prop.get("title", []))
        elif t == "rich_text":
            out[name] = "".join(s.get("plain_text", "") for s in prop.get("rich_text", []))
        elif t == "number":
            out[name] = prop.get("number")
        elif t == "date":
            d = prop.get("date")
            out[name] = d.get("start") if d else None
        elif t == "select":
            s = prop.get("select")
            out[name] = s.get("name") if s else None
    return out


# ---------- public tools ----------

_SETUP_HINT = (
    "在 Deck 的终端里运行（一次性，写入 ~/.bashrc）：\n"
    "  echo 'export NOTION_API_KEY=ntn_你的token' >> ~/.bashrc\n"
    "  echo 'export NOTION_DATABASE_ID=你的数据库id' >> ~/.bashrc\n"
    "  source ~/.bashrc\n"
    "数据库 ID 是 URL 里那串 32 位 hex。\n"
    "别忘了把数据库分享给 DeckMind integration（数据库页右上角 ⋯ → Connections → DeckMind）。"
)


async def notion_status() -> dict[str, Any]:
    """Show Notion connection status, database info, and detected field mapping."""
    if not _key():
        return {"ok": False, "connected": False, "missing": "NOTION_API_KEY",
                "hint": _SETUP_HINT}
    if not _db():
        return {"ok": False, "connected": False, "missing": "NOTION_DATABASE_ID",
                "hint": _SETUP_HINT}

    s = await _schema(_db())
    if not s:
        return {"ok": False, "connected": True,
                "error": "could not read the database",
                "hint": "请确认 DATABASE_ID 正确，并且已把这个数据库分享给 "
                        "DeckMind integration（数据库右上角 ⋯ → Connections → DeckMind）。"}

    return {
        "ok": True, "connected": True,
        "database_title": s["title_text"],
        "database_id_short": _db()[:8] + "...",
        "properties": s["_props"],
        "field_mapping": {
            "game (title)": s["title"],
            "minutes (number)": s["number"],
            "date": s["date"],
            "notes (rich_text)": s["rich_text"],
        },
    }


async def notion_log_session(
    game: str,
    minutes: int,
    notes: str | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    """Add one row to the database recording a play session."""
    if not _key() or not _db():
        return {"ok": False, "error": "Notion not configured",
                "hint": _SETUP_HINT}
    s = await _schema(_db())
    if not s or not s["title"]:
        return {"ok": False, "error": "database has no Title field — every "
                                       "Notion database needs exactly one Title property"}

    props: dict[str, Any] = {
        s["title"]: {"title": [{"text": {"content": game}}]},
    }
    if s["number"]:
        props[s["number"]] = {"number": int(minutes)}
    when = date or datetime.date.today().isoformat()
    if s["date"]:
        props[s["date"]] = {"date": {"start": when}}
    if notes and s["rich_text"]:
        props[s["rich_text"]] = {"rich_text": [{"text": {"content": notes}}]}

    data, err = await _request("POST", "/pages", json={
        "parent": {"database_id": _db()},
        "properties": props,
    })
    if err:
        return err
    return {
        "ok": True, "logged": True,
        "game": game, "minutes": int(minutes),
        "date": when, "notes": notes,
        "url": data.get("url"),
    }


async def notion_recent(limit: int = 10) -> dict[str, Any]:
    """Return the most recently created sessions."""
    if not _key() or not _db():
        return {"ok": False, "error": "Notion not configured", "hint": _SETUP_HINT}
    page_size = max(1, min(int(limit), 100))
    data, err = await _request("POST", f"/databases/{_db()}/query", json={
        "page_size": page_size,
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
    })
    if err:
        return err
    rows = [_flatten_page(p) for p in data.get("results", [])]
    return {"ok": True, "count": len(rows), "sessions": rows}


async def notion_total(days: int = 7) -> dict[str, Any]:
    """Sum playtime over the last `days` days, with per-game breakdown."""
    if not _key() or not _db():
        return {"ok": False, "error": "Notion not configured", "hint": _SETUP_HINT}
    s = await _schema(_db())
    if not s or not s["date"] or not s["number"]:
        return {"ok": False,
                "error": "database needs both a Date and a Number field for totals"}

    days = max(1, int(days))
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    data, err = await _request("POST", f"/databases/{_db()}/query", json={
        "page_size": 100,
        "filter": {"property": s["date"], "date": {"on_or_after": cutoff}},
    })
    if err:
        return err

    title_field = s["title"]
    num_field = s["number"]
    total = 0
    by_game: dict[str, int] = {}
    for page in data.get("results", []):
        props = page.get("properties", {})
        game = ""
        if title_field:
            game = "".join(t.get("plain_text", "")
                           for t in props.get(title_field, {}).get("title", []))
        minutes = props.get(num_field, {}).get("number") or 0
        total += int(minutes)
        if game:
            by_game[game] = by_game.get(game, 0) + int(minutes)

    top = sorted(by_game.items(), key=lambda kv: -kv[1])[:5]
    return {
        "ok": True, "days": days,
        "total_minutes": total,
        "total_hours": round(total / 60, 1),
        "top_games": [{"game": g, "minutes": m} for g, m in top],
    }
