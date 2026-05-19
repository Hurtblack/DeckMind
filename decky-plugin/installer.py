"""Installer/client helpers for the thin DeckMind Decky plugin.

The plugin package stays small. The real agent runtime is installed under the
user's home directory on first run, then upgraded independently.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_RUNTIME_URL = (
    "https://github.com/Hurtblack/DeckMind/releases/latest/download/"
    "deckmind-runtime.tar.gz"
)
RUNTIME_HOME = Path.home() / ".local" / "share" / "deckmind" / "runtime"
CACHE_HOME = Path.home() / ".cache" / "deckmind"
MANIFEST_NAME = "deckmind-runtime.json"


class RuntimeInstaller:
    """Installs and inspects the external DeckMind runtime."""

    def __init__(
        self,
        *,
        runtime_dir: Path = RUNTIME_HOME,
        cache_dir: Path = CACHE_HOME,
        runtime_url: str | None = None,
        runtime_sha256: str | None = None,
    ) -> None:
        self.runtime_dir = runtime_dir
        self.cache_dir = cache_dir
        self.runtime_url = runtime_url or os.environ.get(
            "DECKMIND_RUNTIME_URL",
            DEFAULT_RUNTIME_URL,
        )
        self.runtime_sha256 = runtime_sha256 or os.environ.get("DECKMIND_RUNTIME_SHA256")

    @property
    def manifest_path(self) -> Path:
        return self.runtime_dir / MANIFEST_NAME

    def _manifest(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return {}
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def status(self) -> dict[str, Any]:
        manifest = self._manifest()
        entrypoint = self.runtime_dir / "main.py"
        installed = self.runtime_dir.exists() and entrypoint.exists()
        return {
            "ok": True,
            "installed": installed,
            "runtime_dir": str(self.runtime_dir),
            "version": manifest.get("version"),
            "entrypoint": str(entrypoint),
            "runtime_url": self.runtime_url,
        }

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _download(self) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        target = self.cache_dir / "deckmind-runtime.tar.gz"
        urllib.request.urlretrieve(self.runtime_url, target)
        if self.runtime_sha256:
            actual = self._sha256(target)
            if actual.lower() != self.runtime_sha256.lower():
                target.unlink(missing_ok=True)
                raise RuntimeError(
                    f"runtime sha256 mismatch: expected {self.runtime_sha256}, got {actual}"
                )
        return target

    def install(self) -> dict[str, Any]:
        archive = self._download()
        parent = self.runtime_dir.parent
        parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="deckmind-runtime-", dir=str(parent)) as tmp:
            tmp_dir = Path(tmp)
            with tarfile.open(archive, "r:gz") as tar:
                tar.extractall(tmp_dir)

            extracted_root = tmp_dir
            children = [p for p in tmp_dir.iterdir()]
            if len(children) == 1 and children[0].is_dir():
                extracted_root = children[0]

            next_dir = parent / f"{self.runtime_dir.name}.next"
            if next_dir.exists():
                shutil.rmtree(next_dir)
            shutil.copytree(extracted_root, next_dir)

            if self.runtime_dir.exists():
                shutil.rmtree(self.runtime_dir)
            next_dir.rename(self.runtime_dir)

        manifest = self._manifest()
        if "version" not in manifest:
            manifest = {"version": "unknown", "source": self.runtime_url}
            self.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        return {
            "ok": True,
            "installed": True,
            "runtime_dir": str(self.runtime_dir),
            "version": manifest.get("version"),
        }


INSTALLER = RuntimeInstaller()
