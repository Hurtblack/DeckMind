"""Tool registry.

Each entry maps a tool name (string the LLM will emit) to:
  - the coroutine that implements it
  - a neutral ToolSpec describing its arguments

The LLM client translates ToolSpec into whatever shape its API expects
(OpenAI Responses, Chat Completions, etc.). Tool code is provider-agnostic.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from llm.base import ToolSpec

from . import (
    capability_tool, command_tool, decky_plugin_tool, file_tool, file_write_tool,
    macro_tool, notion_tool, package_tool, pacman_tool, profile_tool, steam_tool,
    steamos_lock as steamos_lock_tool, system_tool, update_tool,
)


# Every tool is an async callable returning a dict.
ToolFn = Callable[..., Awaitable[dict[str, Any]]]


# name -> (callable, neutral spec)
# Note: the LLM ends a turn by simply producing natural-language text
# (which is streamed to the user). There is no `final_answer` tool.
TOOLS: dict[str, tuple[ToolFn, ToolSpec]] = {
    "launch_game": (
        steam_tool.launch_game,
        ToolSpec(
            name="launch_game",
            description="Launch a Steam game by friendly name (e.g. 'cs2').",
            parameters={
                "type": "object",
                "properties": {"game_name": {"type": "string"}},
                "required": ["game_name"],
            },
        ),
    ),
    "close_game": (
        steam_tool.close_game,
        ToolSpec(
            name="close_game",
            description="Kill a running game process by name (uses pkill -f).",
            parameters={
                "type": "object",
                "properties": {"process_name": {"type": "string"}},
                "required": ["process_name"],
            },
        ),
    ),
    "list_running_games": (
        steam_tool.list_running_games,
        ToolSpec(
            name="list_running_games",
            description="List currently running known games.",
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "install_game": (
        steam_tool.install_game,
        ToolSpec(
            name="install_game",
            description=(
                "Open Steam's install dialog for a known game. DESTRUCTIVE — "
                "call first with confirm=false for a dry-run preview, then "
                "again with confirm=true after the user explicitly approves."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "game_name": {"type": "string"},
                    "confirm": {"type": "boolean", "default": False},
                },
                "required": ["game_name"],
            },
        ),
    ),
    "uninstall_game": (
        steam_tool.uninstall_game,
        ToolSpec(
            name="uninstall_game",
            description=(
                "Open Steam's uninstall dialog for a known game. DESTRUCTIVE — "
                "call first with confirm=false for a dry-run preview, then "
                "again with confirm=true after the user explicitly approves."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "game_name": {"type": "string"},
                    "confirm": {"type": "boolean", "default": False},
                },
                "required": ["game_name"],
            },
        ),
    ),
    "list_flatpak_apps": (
        package_tool.list_flatpak_apps,
        ToolSpec(
            name="list_flatpak_apps",
            description="List every installed Flatpak app with its on-disk size.",
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "search_flatpak": (
        package_tool.search_flatpak,
        ToolSpec(
            name="search_flatpak",
            description="Search Flathub for apps matching a keyword (e.g. 'dolphin', 'nes emulator').",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
    ),
    "install_flatpak": (
        package_tool.install_flatpak,
        ToolSpec(
            name="install_flatpak",
            description=(
                "Install a Flatpak app from Flathub by its app_id "
                "(e.g. 'org.DolphinEmu.dolphin-emu'). DESTRUCTIVE — call "
                "first with confirm=false for dry-run, then with confirm=true "
                "after the user explicitly approves."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "app_id": {"type": "string"},
                    "confirm": {"type": "boolean", "default": False},
                },
                "required": ["app_id"],
            },
        ),
    ),
    "uninstall_flatpak": (
        package_tool.uninstall_flatpak,
        ToolSpec(
            name="uninstall_flatpak",
            description=(
                "Uninstall a Flatpak app by its app_id. DESTRUCTIVE — call "
                "first with confirm=false for dry-run (returns current size), "
                "then with confirm=true after the user explicitly approves."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "app_id": {"type": "string"},
                    "confirm": {"type": "boolean", "default": False},
                },
                "required": ["app_id"],
            },
        ),
    ),
    "pacman_search": (
        pacman_tool.pacman_search,
        ToolSpec(
            name="pacman_search",
            description=(
                "Search Arch Linux pacman repos for a package. Read-only, "
                "no sudo. Use for 'arch 有没有 X' / 'search pacman for X'."
            ),
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
    ),
    "pacman_install": (
        pacman_tool.pacman_install,
        ToolSpec(
            name="pacman_install",
            description=(
                "Install Arch packages via pacman. DESTRUCTIVE — 2-step "
                "confirm. Requires writable /usr (on SteamOS the user "
                "must `sudo steamos-readonly disable` first; this tool "
                "refuses if /usr is RO). ALWAYS warn the user that "
                "anything installed will be WIPED on the next SteamOS "
                "update — prefer Flatpak (persistent) or distrobox "
                "(containerized) when those are options. sudo prompts "
                "for the password on the user's terminal."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Package names, e.g. ['htop','neovim']",
                    },
                    "confirm": {"type": "boolean", "default": False},
                },
                "required": ["packages"],
            },
        ),
    ),
    "steamos_lock_status": (
        steamos_lock_tool.steamos_lock_status,
        ToolSpec(
            name="steamos_lock_status",
            description=(
                "Report whether /usr is read-only on this SteamOS device, "
                "AND whether we have a 'dangling unlock' (we previously "
                "called disable but never enabled back). Use first when "
                "the user mentions unlock/relock/pacman state."
            ),
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "steamos_lock": (
        steamos_lock_tool.steamos_lock,
        ToolSpec(
            name="steamos_lock",
            description=(
                "Re-enable SteamOS's /usr read-only protection (runs "
                "`sudo steamos-readonly enable`) and clear any dangling "
                "unlock record. Use when steamos_lock_status reports "
                "dangling_unlock=true, or when the user says '锁回去' / "
                "'re-lock /usr'."
            ),
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "steamos_unlock": (
        steamos_lock_tool.steamos_unlock,
        ToolSpec(
            name="steamos_unlock",
            description=(
                "Disable SteamOS's /usr read-only protection (runs "
                "`sudo steamos-readonly disable`) and persist a record "
                "of the unlock. ONLY use this when the user explicitly "
                "asks to manually unlock — pacman_install handles the "
                "unlock/relock automatically, so you almost never need "
                "to call this directly."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "reason": {"type": "string",
                               "description": "Short reason for the record"},
                },
            },
        ),
    ),
    "set_pacman_mirror_china": (
        pacman_tool.set_pacman_mirror_china,
        ToolSpec(
            name="set_pacman_mirror_china",
            description=(
                "Replace /etc/pacman.d/mirrorlist with Chinese mirrors "
                "(USTC, Tsinghua, SJTU, Aliyun, 163 + global fallback). "
                "DESTRUCTIVE — 2-step confirm. Backs the original up to "
                "mirrorlist.deckmind.bak first time. Use when user says "
                "'换成国内镜像' / 'switch pacman mirror to China'."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "confirm": {"type": "boolean", "default": False},
                },
            },
        ),
    ),
    "disk_usage": (
        package_tool.disk_usage,
        ToolSpec(
            name="disk_usage",
            description="Show human-readable disk usage for / and /home.",
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "find_files": (
        file_tool.find_files,
        ToolSpec(
            name="find_files",
            description=(
                "Search for files by glob pattern under a directory. Use "
                "when the user asks 'where is X' / 'find the X file' / "
                "'X 装在哪了'. Skips noisy paths (caches, trash, .git, "
                "node_modules). Case-insensitive by default. Examples: "
                "find_files('*clash*verge*'); "
                "find_files('*.AppImage', '~/Downloads'); "
                "find_files('config.toml', '~/.config', max_depth=3)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string",
                                "description": "Glob, e.g. '*clash*' or '*.desktop'"},
                    "base_dir": {"type": "string", "default": "~",
                                 "description": "Directory to search from (~ ok)"},
                    "max_depth": {"type": "integer", "default": 6},
                    "max_results": {"type": "integer", "default": 30},
                    "case_insensitive": {"type": "boolean", "default": True},
                },
                "required": ["pattern"],
            },
        ),
    ),
    "list_processes": (
        file_tool.list_processes,
        ToolSpec(
            name="list_processes",
            description=(
                "List running processes, optionally filtered by substring "
                "(case-insensitive, matches command + args). Use to answer "
                "'is X running?' / 'X 在跑吗?' / 'kill 哪个 pid'. Caps "
                "results so the LLM context stays manageable."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "filter": {"type": "string",
                               "description": "Optional substring filter"},
                    "limit": {"type": "integer", "default": 30},
                },
            },
        ),
    ),
    "read_text_file": (
        file_write_tool.read_text_file,
        ToolSpec(
            name="read_text_file",
            description=(
                "Read a small text file (up to 64 KB). Useful for "
                "inspecting configs the user mentioned — autostart "
                ".desktop entries, ~/.bashrc, ~/.config/<app>/*.toml, "
                "/etc/os-release etc. Refuses ~/.ssh, ~/.gnupg, anything "
                "containing 'secret'/'credential'/'id_rsa' style names, "
                "and refuses to follow symlinks."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_bytes": {"type": "integer", "default": 16384,
                                  "description": "Truncate at this many bytes (hard cap 65536)"},
                },
                "required": ["path"],
            },
        ),
    ),
    "write_text_file": (
        file_write_tool.write_text_file,
        ToolSpec(
            name="write_text_file",
            description=(
                "Write text content to a file. DESTRUCTIVE — call first "
                "with confirm=false for a dry-run preview, then with "
                "confirm=true after the user explicitly approves.\n"
                "Allowed paths (writes outside refused):\n"
                "  ~/.config/autostart/   — KDE/GNOME autostart .desktop\n"
                "  ~/.config/systemd/user/— user systemd services\n"
                "  ~/.local/share/applications/ — custom .desktop entries\n"
                "  ~/.deckmind/           — our own config dir\n"
                "  ~/Documents/ ~/Desktop/ ~/Downloads/\n"
                "High-risk writes additionally allow ~/.config/, "
                "~/.local/share/, and ~/.ssh/.\n"
                "Sensitive paths such as ~/.ssh, .env, token, secret, "
                "credential, and password paths require high_risk_confirm=true "
                "after explicit one-time user approval; their dry-run previews "
                "redact content. Refuses symlinks. Max content 100 KB.\n"
                "Typical use: create an autostart .desktop for an AppImage."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "Destination path, ~ expansion supported"},
                    "content": {"type": "string"},
                    "confirm": {"type": "boolean", "default": False},
                    "high_risk_confirm": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Set true only after the user explicitly approves "
                            "a high-risk sensitive-path write."
                        ),
                    },
                },
                "required": ["path", "content"],
            },
        ),
    ),
    "run_command": (
        command_tool.run_command,
        ToolSpec(
            name="run_command",
            description=(
                "Run a restricted allowlisted user-level command. "
                "DESTRUCTIVE — call first with confirm=false for a dry-run "
                "preview, then with confirm=true after the user explicitly "
                "approves. Does not use a shell. Normal allowed command "
                "families include curl/wget downloads to approved user "
                "directories, chmod +x on approved files, mkdir -p in "
                "approved directories, safe tar -xzf extraction into approved "
                "directories, launch_file for approved executable files, "
                "file/which read-only checks, and systemctl --user for simple "
                "user service actions. If advanced=true, commands outside "
                "the normal allowlist may run from trusted executable dirs "
                "only, still without shell metacharacters, but require "
                "high_risk_confirm=true after explicit one-time user approval. "
                "Hardline commands such as reboot/shutdown, mkfs, dd to raw "
                "devices, shells/interpreters, sudo/su/doas, pacman, rm, and "
                "system-level systemctl are refused."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Command argv, e.g. ['which', 'sh']",
                    },
                    "confirm": {"type": "boolean", "default": False},
                    "advanced": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Enable the high-risk advanced command path for "
                            "commands outside the normal allowlist."
                        ),
                    },
                    "high_risk_confirm": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Set true only after the user explicitly approves "
                            "a high-risk advanced command."
                        ),
                    },
                },
                "required": ["argv"],
            },
        ),
    ),
    "install_decky_plugin": (
        decky_plugin_tool.install_decky_plugin,
        ToolSpec(
            name="install_decky_plugin",
            description=(
                "Deploy the bundled DeckMind Decky plugin into Decky's "
                "homebrew/plugins directory. DESTRUCTIVE — call first with "
                "confirm=false for a dry-run preview, then with confirm=true "
                "after the user explicitly approves. Copies only the packaged "
                "plugin files and excludes source, node_modules, scripts, and "
                "build config files."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "target_dir": {
                        "type": "string",
                        "description": (
                            "Optional target directory. Defaults to "
                            "~/homebrew/plugins/DeckMind and must be under "
                            "a homebrew/plugins directory."
                        ),
                    },
                    "confirm": {"type": "boolean", "default": False},
                },
            },
        ),
    ),
    "remember": (
        profile_tool.remember,
        ToolSpec(
            name="remember",
            description=(
                "Save a fact about the user that should persist across "
                "sessions (name, preferences, schedule, gaming style, etc.). "
                "Use a short snake_case key. Overwrites any prior value at "
                "the same key. Examples: "
                "remember('name','赖天宇'); "
                "remember('favorite_genre','soulslike'); "
                "remember('play_window','weekends 1-2h')."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["key", "value"],
            },
        ),
    ),
    "forget": (
        profile_tool.forget,
        ToolSpec(
            name="forget",
            description="Remove a previously saved fact by key.",
            parameters={
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
            },
        ),
    ),
    "list_profile": (
        profile_tool.list_profile,
        ToolSpec(
            name="list_profile",
            description=(
                "Return every fact currently stored about the user. "
                "Usually you don't need to call this — the profile is "
                "already injected into your system prompt at startup. "
                "Use it only when the user asks 'what do you know about me?' "
                "and you want to confirm against the latest on-disk state."
            ),
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "notion_status": (
        notion_tool.notion_status,
        ToolSpec(
            name="notion_status",
            description=(
                "Show Notion connection status. If only NOTION_API_KEY is "
                "set, this also auto-discovers the database: silently picks "
                "the only accessible one, or returns the list with "
                "`needs_user_choice: true` if there are multiple. Call this "
                "first whenever the user wants to 'connect Notion' / '绑定 "
                "notion' / '看看 notion 状态'."
            ),
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "notion_databases": (
        notion_tool.notion_databases,
        ToolSpec(
            name="notion_databases",
            description=(
                "List every Notion database the integration can access. "
                "Read-only. Useful when the user has multiple databases "
                "shared with DeckMind and wants to switch which one is "
                "active."
            ),
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "notion_set_default_database": (
        notion_tool.notion_set_default_database,
        ToolSpec(
            name="notion_set_default_database",
            description=(
                "Persist a Notion database ID as the active default "
                "(saved to ~/.deckmind/notion.json). Use this after "
                "notion_status returns `needs_user_choice: true`, or when "
                "the user asks to switch to a different shared database."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "database_id": {"type": "string",
                                    "description": "The 32-char hex ID of the database"},
                },
                "required": ["database_id"],
            },
        ),
    ),
    "notion_pages": (
        notion_tool.notion_pages,
        ToolSpec(
            name="notion_pages",
            description=(
                "List all regular Notion PAGES (not database rows) the "
                "integration has been shared into. Use to find a parent "
                "for notion_create_page, e.g. when the user says '记到我"
                "的主页里' / 'put it under my workspace homepage'."
            ),
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "notion_create_page": (
        notion_tool.notion_create_page,
        ToolSpec(
            name="notion_create_page",
            description=(
                "Create a new page UNDER an existing page that's shared "
                "with the DeckMind integration. `body_markdown` accepts "
                "simple markdown: # / ## / ### headings, - or * bullets, "
                "1. numbered lists, --- dividers, ```lang fenced code, "
                "everything else becomes paragraphs. Inline bold/italic "
                "is NOT parsed. Use for snapshot reports, notes, etc."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "parent_page_id": {"type": "string",
                                       "description": "ID of the page to nest under"},
                    "title": {"type": "string"},
                    "body_markdown": {"type": "string",
                                      "description": "Lightweight markdown body (optional)"},
                },
                "required": ["parent_page_id", "title"],
            },
        ),
    ),
    "notion_log_session": (
        notion_tool.notion_log_session,
        ToolSpec(
            name="notion_log_session",
            description=(
                "Append one play-session row to the Notion database. "
                "Use when the user reports having played something "
                "(e.g. '记一笔我刚玩了 1 小时 CS2'). `minutes` is integer "
                "minutes. `date` defaults to today (YYYY-MM-DD). `notes` "
                "is optional free-text."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "game": {"type": "string"},
                    "minutes": {"type": "integer", "minimum": 1},
                    "notes": {"type": "string"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": ["game", "minutes"],
            },
        ),
    ),
    "notion_recent": (
        notion_tool.notion_recent,
        ToolSpec(
            name="notion_recent",
            description="Return the N most-recently-logged play sessions.",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
                },
            },
        ),
    ),
    "notion_total": (
        notion_tool.notion_total,
        ToolSpec(
            name="notion_total",
            description=(
                "Sum playtime over the last `days` days, with a top-5 "
                "per-game breakdown. Use for '本周玩了多少' / "
                "'这个月谁玩得最多' / weekly summary."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "minimum": 1, "maximum": 365,
                             "description": "Look back this many days (7=week, 30=month)"},
                },
            },
        ),
    ),
    "check_for_updates": (
        update_tool.check_for_updates,
        ToolSpec(
            name="check_for_updates",
            description=(
                "Fetch from the project's git origin and report whether "
                "a newer commit is available. Read-only, safe."
            ),
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "apply_update": (
        update_tool.apply_update,
        ToolSpec(
            name="apply_update",
            description=(
                "Pull the latest code from origin (fast-forward only) and "
                "run `uv sync`. SIDE-EFFECT — when the user explicitly asks "
                "to update/upgrade/pull latest, call with confirm=true "
                "directly. Use confirm=false only when the user asks to check "
                "or preview updates. Refuses if there are uncommitted local "
                "changes. The new code only takes effect after the user "
                "restarts the agent."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "confirm": {"type": "boolean", "default": False},
                },
            },
        ),
    ),
    "get_battery": (
        system_tool.get_battery,
        ToolSpec(
            name="get_battery",
            description="Read battery percentage and charging status.",
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "get_volume": (
        system_tool.get_volume,
        ToolSpec(
            name="get_volume",
            description="Read current audio output volume as a percent (0-100).",
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "set_volume": (
        system_tool.set_volume,
        ToolSpec(
            name="set_volume",
            description="Set audio output volume. `percent` is 0-100.",
            parameters={
                "type": "object",
                "properties": {"percent": {"type": "integer", "minimum": 0, "maximum": 100}},
                "required": ["percent"],
            },
        ),
    ),
    "list_capabilities": (
        capability_tool.list_capabilities,
        ToolSpec(
            name="list_capabilities",
            description=(
                "List registered DeckMind capabilities with descriptions, "
                "argument schemas, risk levels, and confirmation requirements."
            ),
            parameters={"type": "object", "properties": {}},
        ),
    ),
    "run_capability": (
        capability_tool.run_capability,
        ToolSpec(
            name="run_capability",
            description=(
                "Run a registered DeckMind capability by name. Safe and "
                "side-effect capabilities execute directly when requested. "
                "For destructive capabilities, call first with confirm=false "
                "for preview, then again with confirm=true after the user "
                "approves. Unknown capabilities return unknown_capability "
                "and must not be replaced with shell commands."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "args": {
                        "type": "object",
                        "description": "Capability arguments matching its args_schema.",
                    },
                    "confirm": {"type": "boolean", "default": False},
                },
                "required": ["name"],
            },
        ),
    ),
    "press_key": (
        macro_tool.press_key,
        ToolSpec(
            name="press_key",
            description="Press and release a single key once (e.g. 'space', 'a', 'enter').",
            parameters={
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
            },
        ),
    ),
    "start_key_loop": (
        macro_tool.start_key_loop,
        ToolSpec(
            name="start_key_loop",
            description="Start a background loop that presses `key` every `interval_seconds`.",
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "interval_seconds": {"type": "number", "minimum": 0.05},
                },
                "required": ["key", "interval_seconds"],
            },
        ),
    ),
    "stop_all_macros": (
        macro_tool.stop_all_macros,
        ToolSpec(
            name="stop_all_macros",
            description="Cancel every running key-loop macro.",
            parameters={"type": "object", "properties": {}},
        ),
    ),
}


def specs() -> list[ToolSpec]:
    """Return all tool specs for the planner to advertise to the LLM."""
    return [spec for _, spec in TOOLS.values()]


def get(name: str) -> ToolFn | None:
    """Look up the implementation for a tool name. None if unknown."""
    entry = TOOLS.get(name)
    return entry[0] if entry else None
