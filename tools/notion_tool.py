"""Notion logbook tools — write game-session records into a Notion database.

Configuration:
  NOTION_API_KEY       — required env var. Internal integration token (ntn_xxx).
  NOTION_DATABASE_ID   — optional env var. Forces use of a specific database.
                         When unset, the agent auto-discovers via the Notion
                         search API and persists its choice to
                         ~/.deckmind/notion.json — so you only need the token.

Auto-discovery logic (in notion_status):
  - 0 accessible databases  → tell user to share one with DeckMind.
  - 1 accessible database   → silently auto-pick + persist + use it.
  - 2+ accessible databases → list them, ask user to pick one via
                              notion_set_default_database.

Schema convention (by FIELD TYPE, not name — works with any layout):
  - Title          → game name
  - First Number   → minutes played
  - First Date     → session date (defaults to today)
  - First Rich Text → optional notes
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
from typing import Any


# Persisted default database — lives next to the user profile.
_CONFIG_DIR = pathlib.Path.home() / ".deckmind"
_CONFIG_FILE = _CONFIG_DIR / "notion.json"


NOTION_VERSION = "2022-06-28"
API_BASE = "https://api.notion.com/v1"


# ---------- env + http helpers ----------

def _key() -> str | None:
    v = os.environ.get("NOTION_API_KEY")
    return v if v else None


def _load_config() -> dict[str, Any]:
    """Read the persisted Notion config. Empty dict on any failure."""
    try:
        return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_config(data: dict[str, Any]) -> None:
    """Persist the Notion config (creates ~/.deckmind/ if missing)."""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _db() -> str | None:
    """Resolve the active database ID. Precedence: env var > persisted default."""
    v = os.environ.get("NOTION_DATABASE_ID")
    if v:
        return v
    return _load_config().get("default_database_id") or None


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
    try:
        import httpx
    except ImportError:
        return None, {"ok": False, "error": "httpx not installed"}

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
    "在 Deck 上用 nano 把 token 写入 ~/.bashrc（不要发到任何聊天里）：\n"
    "  nano ~/.bashrc\n"
    "  # 在文件底加这一行：\n"
    "  export NOTION_API_KEY=ntn_你的token\n"
    "  # Ctrl+O 保存, Ctrl+X 退出\n"
    "  source ~/.bashrc\n"
    "然后在 Notion 里把要用的数据库分享给 DeckMind integration（数据库右上角 ⋯ → Connections → DeckMind）。\n"
    "之后重启 deckmind，数据库会被自动发现 —— database_id 不用手动设了。"
)


async def _list_databases() -> tuple[list[dict[str, str]] | None, dict[str, Any] | None]:
    """Query Notion's search API for every database this token can see."""
    data, err = await _request("POST", "/search", json={
        "filter": {"value": "database", "property": "object"},
        "page_size": 100,
    })
    if err:
        return None, err
    dbs = []
    for d in data.get("results", []):
        title = "".join(t.get("plain_text", "") for t in d.get("title", []))
        dbs.append({"id": d["id"], "title": title or "(untitled)"})
    return dbs, None


async def notion_status() -> dict[str, Any]:
    """Show Notion connection + database. Auto-discovers a database when only
    NOTION_API_KEY is set: 0 found → asks user to share one; 1 found → silently
    adopts; 2+ found → lists them for the user to pick."""
    if not _key():
        return {"ok": False, "connected": False, "missing": "NOTION_API_KEY",
                "hint": _SETUP_HINT}

    db = _db()

    # Auto-discovery path: no database configured anywhere yet.
    if not db:
        dbs, err = await _list_databases()
        if err:
            return {"ok": False, "connected": True, **err,
                    "hint": "Token 可能无效，或网络不通。"}
        if not dbs:
            return {
                "ok": False, "connected": True, "databases_found": 0,
                "hint": ("Token 工作正常，但还没有任何数据库分享给 DeckMind "
                         "integration。在 Notion 里打开你想用的数据库 → 右上角 "
                         "⋯ → Connections → 搜索 DeckMind 加进去，然后再问我一次。"),
            }
        if len(dbs) == 1:
            # Silent auto-pick — persist + use immediately.
            chosen = dbs[0]
            _save_config({
                "default_database_id": chosen["id"],
                "default_database_title": chosen["title"],
                "set_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "source": "auto_discovered",
            })
            db = chosen["id"]
        else:
            return {
                "ok": True, "connected": True,
                "needs_user_choice": True,
                "databases": dbs,
                "message": (f"找到 {len(dbs)} 个可访问的数据库。请用 "
                            "notion_set_default_database(database_id=...) 指定一个，"
                            "或者在 ~/.bashrc 里强制 export NOTION_DATABASE_ID=..."),
            }

    s = await _schema(db)
    if not s:
        return {"ok": False, "connected": True,
                "error": "could not read the database schema",
                "hint": "请确认数据库已分享给 DeckMind integration（数据库右上角 ⋯ → Connections → DeckMind）。"}

    cfg = _load_config()
    source = ("env var (NOTION_DATABASE_ID)" if os.environ.get("NOTION_DATABASE_ID")
              else cfg.get("source", "persisted in ~/.deckmind/notion.json"))

    return {
        "ok": True, "connected": True,
        "database_title": s["title_text"],
        "database_id_short": db[:8] + "...",
        "database_id_source": source,
        "properties": s["_props"],
        "field_mapping": {
            "game (title)": s["title"],
            "minutes (number)": s["number"],
            "date": s["date"],
            "notes (rich_text)": s["rich_text"],
        },
    }


async def notion_databases() -> dict[str, Any]:
    """List every database this integration can access (read-only)."""
    if not _key():
        return {"ok": False, "error": "NOTION_API_KEY not set", "hint": _SETUP_HINT}
    dbs, err = await _list_databases()
    if err:
        return err
    return {
        "ok": True, "count": len(dbs or []),
        "databases": dbs or [],
        "current_default": _db(),
        "hint": (None if dbs else
                 "没找到任何能访问的数据库。在 Notion 里把数据库分享给 "
                 "DeckMind integration（⋯ → Connections → DeckMind）。"),
    }


# ---------- page-creation support ----------

# Cap children per /pages call — Notion's hard limit is 100.
_MAX_BLOCKS_PER_PAGE = 100


def _text_block(block_type: str, content: str) -> dict[str, Any]:
    """Build a single text block (paragraph / heading / bullet / ...)."""
    return {
        "object": "block",
        "type": block_type,
        block_type: {
            "rich_text": [{"type": "text", "text": {"content": content}}],
        },
    }


def _md_to_blocks(md: str) -> list[dict[str, Any]]:
    """Convert lightweight markdown into Notion block objects.

    Supported syntax (one line per block, except fenced code):
      # foo / ## foo / ### foo    -> heading_1 / 2 / 3
      - foo  or  * foo            -> bulleted_list_item
      1. foo                      -> numbered_list_item
      ---                         -> divider
      ```lang ... ```             -> code block
      anything else                -> paragraph

    Blank lines are skipped. Inline markdown (bold/italic/links) is NOT
    parsed — Notion's rich_text spans would need a real parser.
    """
    blocks: list[dict[str, Any]] = []
    in_code = False
    code_lang = "plain text"
    code_lines: list[str] = []

    for raw in md.splitlines():
        line = raw.rstrip()

        if in_code:
            if line.startswith("```"):
                blocks.append({
                    "object": "block", "type": "code",
                    "code": {
                        "rich_text": [{"type": "text",
                                       "text": {"content": "\n".join(code_lines)}}],
                        "language": code_lang,
                    },
                })
                in_code = False
                code_lang = "plain text"
                code_lines = []
            else:
                code_lines.append(raw)
            continue

        if line.startswith("```"):
            in_code = True
            code_lang = (line[3:].strip().lower() or "plain text")
            continue

        if not line.strip():
            continue
        if line.strip() == "---":
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        elif line.startswith("### "):
            blocks.append(_text_block("heading_3", line[4:]))
        elif line.startswith("## "):
            blocks.append(_text_block("heading_2", line[3:]))
        elif line.startswith("# "):
            blocks.append(_text_block("heading_1", line[2:]))
        elif line.startswith("- ") or line.startswith("* "):
            blocks.append(_text_block("bulleted_list_item", line[2:]))
        elif len(line) > 2 and line[0].isdigit() and line[1:3] in (". ", ") "):
            blocks.append(_text_block("numbered_list_item", line[3:]))
        else:
            blocks.append(_text_block("paragraph", line))

    # Flush any unterminated code fence so its content isn't silently lost.
    if in_code and code_lines:
        blocks.append({
            "object": "block", "type": "code",
            "code": {
                "rich_text": [{"type": "text", "text": {"content": "\n".join(code_lines)}}],
                "language": code_lang,
            },
        })
    return blocks


async def notion_pages() -> dict[str, Any]:
    """List Notion PAGES (not database rows) the integration can access."""
    if not _key():
        return {"ok": False, "error": "NOTION_API_KEY not set", "hint": _SETUP_HINT}
    data, err = await _request("POST", "/search", json={
        "filter": {"value": "page", "property": "object"},
        "page_size": 100,
    })
    if err:
        return err

    pages: list[dict[str, str]] = []
    for p in data.get("results", []):
        # Skip database rows — those have parent.type == "database_id".
        parent = p.get("parent", {})
        if parent.get("type") == "database_id":
            continue
        title = ""
        for prop in p.get("properties", {}).values():
            if prop.get("type") == "title":
                title = "".join(t.get("plain_text", "") for t in prop["title"])
                break
        pages.append({
            "id": p["id"],
            "title": title or "(untitled)",
            "url": p.get("url", ""),
        })
    return {
        "ok": True, "count": len(pages), "pages": pages,
        "hint": (None if pages else
                 "没找到任何能访问的页面。在 Notion 里把目标页面分享给 "
                 "DeckMind integration（页面右上 ⋯ → Connections → DeckMind）。"),
    }


async def notion_create_page(
    parent_page_id: str,
    title: str,
    body_markdown: str = "",
) -> dict[str, Any]:
    """Create a new page underneath `parent_page_id` with optional markdown body.

    The parent page MUST already be shared with the DeckMind integration
    (Notion permissions inherit, so children of a shared page are also
    accessible — but the parent must be explicitly connected).
    """
    if not _key():
        return {"ok": False, "error": "NOTION_API_KEY not set", "hint": _SETUP_HINT}
    if not (title or "").strip():
        return {"ok": False, "error": "title is required"}

    payload: dict[str, Any] = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": title.strip()}}],
            },
        },
    }

    blocks: list[dict[str, Any]] = []
    if body_markdown:
        blocks = _md_to_blocks(body_markdown)
        if blocks:
            payload["children"] = blocks[:_MAX_BLOCKS_PER_PAGE]

    data, err = await _request("POST", "/pages", json=payload)
    if err:
        return err

    page_id = data.get("id")
    truncated = len(blocks) > _MAX_BLOCKS_PER_PAGE

    # If the body was longer than the per-call limit, append the rest
    # via the children endpoint. Notion allows another 100 per call.
    overflow_appended = 0
    if truncated and page_id:
        leftover = blocks[_MAX_BLOCKS_PER_PAGE:]
        # Bound the overflow to avoid spamming long-running calls.
        leftover = leftover[:_MAX_BLOCKS_PER_PAGE]
        _, append_err = await _request(
            "PATCH", f"/blocks/{page_id}/children",
            json={"children": leftover},
        )
        if not append_err:
            overflow_appended = len(leftover)

    return {
        "ok": True, "created": True,
        "title": title.strip(),
        "page_id": page_id,
        "url": data.get("url"),
        "blocks_written": min(len(blocks), _MAX_BLOCKS_PER_PAGE) + overflow_appended,
        "blocks_dropped": max(0, len(blocks) - _MAX_BLOCKS_PER_PAGE - overflow_appended),
    }


async def notion_set_default_database(database_id: str) -> dict[str, Any]:
    """Persist `database_id` as the default for all future notion_* calls."""
    if not _key():
        return {"ok": False, "error": "NOTION_API_KEY not set", "hint": _SETUP_HINT}

    # Verify accessibility before saving — better to fail loudly than to
    # save a bad ID and confuse the user on the next call.
    data, err = await _request("GET", f"/databases/{database_id}")
    if err:
        return {"ok": False, **err,
                "hint": "确认 database_id 正确且已分享给 DeckMind integration。"}

    title = "".join(t.get("plain_text", "") for t in data.get("title", []))
    _save_config({
        "default_database_id": database_id,
        "default_database_title": title or "(untitled)",
        "set_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": "user_chosen",
    })
    # Invalidate cached schema so the next call re-reads this DB.
    _schema_cache.pop(database_id, None)
    return {
        "ok": True, "set_as_default": True,
        "database_id": database_id,
        "database_title": title or "(untitled)",
        "saved_to": str(_CONFIG_FILE),
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
