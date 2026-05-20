"""Persistent DeckMind configuration for the Decky shell plugin."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _deck_user_home() -> Path:
    """deck 用户的 home 目录（即使当前进程以 root 运行）。"""
    env = os.environ.get("DECKY_USER_HOME")
    if env:
        return Path(env)
    return Path.home()


CONFIG_HOME = _deck_user_home() / ".config" / "deckmind"
CONFIG_PATH = CONFIG_HOME / "config.json"


DEFAULT_CONFIG: dict[str, Any] = {
    "provider": "openai",
    "model": "",
    "api_keys": {},
}


class ConfigStore:
    """Reads and writes local DeckMind settings.

    API keys are stored locally in the user's config directory. Public payloads
    only report whether a key exists; they never echo the secret value.
    """

    def __init__(self, *, path: Path = CONFIG_PATH) -> None:
        self.path = path

    def _read_raw(self) -> dict[str, Any]:
        if not self.path.exists():
            return dict(DEFAULT_CONFIG)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return dict(DEFAULT_CONFIG)
        merged = dict(DEFAULT_CONFIG)
        merged.update(data if isinstance(data, dict) else {})
        if not isinstance(merged.get("api_keys"), dict):
            merged["api_keys"] = {}
        return merged

    def _write_raw(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def get(self) -> dict[str, Any]:
        return self._public(self._read_raw())

    def get_runtime_config(self) -> dict[str, Any]:
        return self._read_raw()

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._read_raw()
        provider = str(payload.get("provider") or data["provider"]).strip().lower()
        model = str(payload.get("model") or "").strip()
        api_key = str(payload.get("api_key") or "").strip()

        data["provider"] = provider
        data["model"] = model
        if api_key:
            data.setdefault("api_keys", {})[provider] = api_key

        self._write_raw(data)
        return self._public(data)

    def _public(self, data: dict[str, Any]) -> dict[str, Any]:
        provider = str(data.get("provider") or "openai")
        api_keys = data.get("api_keys") if isinstance(data.get("api_keys"), dict) else {}
        return {
            "ok": True,
            "provider": provider,
            "model": str(data.get("model") or ""),
            "has_api_key": bool(api_keys.get(provider)),
        }


CONFIG_STORE = ConfigStore()
