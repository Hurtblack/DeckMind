"""Deploy the DeckMind Decky plugin into Decky's plugin directory."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


_PROJECT_DIR = Path(__file__).resolve().parent.parent
_PLUGIN_SOURCE_DIR = _PROJECT_DIR / "decky-plugin"
_DEFAULT_PLUGIN_ROOT = Path.home() / "homebrew" / "plugins"
_DECK_USER_PLUGIN_ROOT = Path("/home/deck/homebrew/plugins")
_DEFAULT_TARGET_DIR = Path.home() / "homebrew" / "plugins" / "DeckMind"
_EXCLUDED_DIRS = {"node_modules", "src", "scripts", "__pycache__", ".git"}
_EXCLUDED_FILES = {"tsconfig.json", "rollup.config.js", ".DS_Store"}
_REQUIRED_FILES = ("plugin.json", "main.py", "dist/index.js")


def _resolve_target(raw_target: str | None) -> Path:
    if raw_target:
        return Path(raw_target).expanduser().resolve(strict=False)

    return _discover_plugin_root() / "DeckMind"


def _candidate_plugin_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for root in (_DEFAULT_PLUGIN_ROOT, _DECK_USER_PLUGIN_ROOT):
        resolved = root.expanduser().resolve(strict=False)
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def _matches_decky_plugin_root_pattern(root: Path) -> bool:
    return root.name == "plugins" and root.parent.name == "homebrew"


def _plugin_shape(plugin_dir: Path) -> dict[str, Any]:
    has_plugin_json = (plugin_dir / "plugin.json").is_file()
    has_package_json = (plugin_dir / "package.json").is_file()
    has_dist_index = (plugin_dir / "dist" / "index.js").is_file()
    has_main_py = (plugin_dir / "main.py").is_file()
    return {
        "directory": plugin_dir.name,
        "has_plugin_json": has_plugin_json,
        "has_package_json": has_package_json,
        "has_dist_index": has_dist_index,
        "has_main_py": has_main_py,
        "looks_like_decky_plugin": has_plugin_json and has_dist_index,
    }


def _existing_plugins(root: Path) -> list[dict[str, Any]]:
    if not root.exists() or not root.is_dir():
        return []
    plugins: list[dict[str, Any]] = []
    for child in sorted(root.iterdir(), key=lambda path: path.name.lower()):
        if child.is_dir() and not child.is_symlink():
            shape = _plugin_shape(child)
            if shape["looks_like_decky_plugin"] or shape["has_plugin_json"]:
                plugins.append(shape)
    return plugins


def _discover_plugin_root() -> Path:
    fallback = _DEFAULT_PLUGIN_ROOT.expanduser().resolve(strict=False)
    for root in _candidate_plugin_roots():
        if not _matches_decky_plugin_root_pattern(root):
            continue
        if _existing_plugins(root):
            return root
    for root in _candidate_plugin_roots():
        if _matches_decky_plugin_root_pattern(root) and root.exists():
            return root
    return fallback


def _discovery_result(root: Path) -> dict[str, Any]:
    existing_plugins = _existing_plugins(root)
    return {
        "plugin_root": str(root),
        "plugin_root_exists": root.exists() and root.is_dir(),
        "plugin_root_matches_decky_path": _matches_decky_plugin_root_pattern(root),
        "existing_plugins": existing_plugins,
        "existing_plugin_count": len(existing_plugins),
    }


def _validate_source(source: Path) -> str | None:
    if not source.exists() or not source.is_dir():
        return f"Decky plugin source directory does not exist: {source}"
    for relative in _REQUIRED_FILES:
        if not (source / relative).is_file():
            return f"Decky plugin source is missing required file: {relative}"
    return None


def _validate_target(target: Path) -> str | None:
    if target.name != "DeckMind":
        return "target directory must be named DeckMind"
    if target.is_symlink():
        return "refusing to deploy into a symlink target"
    if not _matches_decky_plugin_root_pattern(target.parent):
        return "target directory must be under a homebrew/plugins directory"
    if target.parent.exists() and target.parent.is_symlink():
        return "refusing to deploy through a symlink plugins directory"
    return None


def _is_excluded(path: Path) -> bool:
    if any(part in _EXCLUDED_DIRS for part in path.parts):
        return True
    if path.name in _EXCLUDED_FILES:
        return True
    if path.suffix == ".pyc":
        return True
    return False


def _included_files(source: Path) -> tuple[list[str], str | None]:
    files: list[str] = []
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if _is_excluded(relative):
            continue
        if path.is_symlink():
            return [], f"refusing to deploy symlink: {relative}"
        if path.is_file():
            files.append(relative.as_posix())
    return files, None


def _copy_included_files(source: Path, target: Path, files: list[str]) -> None:
    temp_target = target.parent / f".{target.name}.next"
    if temp_target.exists():
        shutil.rmtree(temp_target)
    temp_target.mkdir(parents=True)

    try:
        for relative in files:
            source_file = source / relative
            target_file = temp_target / relative
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)

        if target.exists():
            shutil.rmtree(target)
        temp_target.rename(target)
    except Exception:
        if temp_target.exists():
            shutil.rmtree(temp_target)
        raise


async def install_decky_plugin(
    target_dir: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Deploy the bundled DeckMind Decky plugin.

    confirm=False returns a dry-run preview. confirm=True replaces the target
    plugin directory with a filtered copy of the local decky-plugin package.
    """
    source = _PLUGIN_SOURCE_DIR.resolve(strict=False)
    target = _resolve_target(target_dir)

    source_reason = _validate_source(source)
    if source_reason:
        return {"ok": False, "refused": True, "reason": source_reason}

    target_reason = _validate_target(target)
    if target_reason:
        return {"ok": False, "refused": True, "reason": target_reason}

    files, files_reason = _included_files(source)
    if files_reason:
        return {"ok": False, "refused": True, "reason": files_reason}

    if not confirm:
        return {
            "ok": True,
            "dry_run": True,
            "source_dir": str(source),
            "target_dir": str(target),
            **_discovery_result(target.parent),
            "included_files": files,
            "file_count": len(files),
            "message": "Decky plugin deployment validated. Call again with confirm=true after user approval.",
        }

    target.parent.mkdir(parents=True, exist_ok=True)
    _copy_included_files(source, target, files)

    return {
        "ok": True,
        "deployed": True,
        "source_dir": str(source),
        "target_dir": str(target),
        **_discovery_result(target.parent),
        "included_files": files,
        "file_count": len(files),
        "message": "DeckMind Decky plugin deployed. Restart Decky/plugin_loader if the UI does not refresh.",
    }
