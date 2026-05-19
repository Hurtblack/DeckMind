from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


def load_installer_module():
    module_path = Path(__file__).resolve().parents[1] / "decky-plugin" / "installer.py"
    spec = importlib.util.spec_from_file_location("decky_plugin_installer_under_test", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load installer from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DeckyPluginInstallerTests(unittest.TestCase):
    def test_status_reports_not_installed_without_entrypoint(self) -> None:
        module = load_installer_module()
        with tempfile.TemporaryDirectory() as root:
            runtime_dir = Path(root) / "runtime"
            installer = module.RuntimeInstaller(runtime_dir=runtime_dir, cache_dir=Path(root) / "cache")

            status = installer.status()

        self.assertTrue(status["ok"])
        self.assertFalse(status["installed"])
        self.assertEqual(status["runtime_dir"], str(runtime_dir))

    def test_status_reads_version_from_manifest_when_installed(self) -> None:
        module = load_installer_module()
        with tempfile.TemporaryDirectory() as root:
            runtime_dir = Path(root) / "runtime"
            runtime_dir.mkdir()
            (runtime_dir / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (runtime_dir / module.MANIFEST_NAME).write_text(
                json.dumps({"version": "0.2.0"}),
                encoding="utf-8",
            )
            installer = module.RuntimeInstaller(runtime_dir=runtime_dir, cache_dir=Path(root) / "cache")

            status = installer.status()

        self.assertTrue(status["installed"])
        self.assertEqual(status["version"], "0.2.0")


if __name__ == "__main__":
    unittest.main()
