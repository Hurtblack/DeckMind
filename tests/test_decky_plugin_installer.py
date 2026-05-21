from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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

    def test_sync_plugin_repairs_permissions_before_copy_when_root(self) -> None:
        module = load_installer_module()
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            runtime_plugin = root_path / "runtime" / "decky-plugin"
            runtime_plugin.mkdir(parents=True)
            (runtime_plugin / "main.py").write_text("print('new')\n", encoding="utf-8")
            plugin_dir = root_path / "homebrew" / "plugins" / "DeckMind"
            plugin_dir.mkdir(parents=True)
            module.__file__ = str(plugin_dir / "installer.py")
            resolved_plugin_dir = plugin_dir.resolve(strict=False)

            installer = module.RuntimeInstaller(
                runtime_dir=root_path / "runtime",
                cache_dir=root_path / "cache",
            )

            with (
                patch.object(installer, "_fix_plugin_dir_permissions", create=True) as fix_permissions,
                patch.object(module.os, "getuid", return_value=0),
            ):
                result = installer._sync_plugin()

        self.assertTrue(result["ok"])
        fix_permissions.assert_called_once_with(resolved_plugin_dir)

    def test_sync_plugin_retries_copy_after_permission_repair(self) -> None:
        module = load_installer_module()
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            runtime_plugin = root_path / "runtime" / "decky-plugin"
            runtime_plugin.mkdir(parents=True)
            source_file = runtime_plugin / "main.py"
            source_file.write_text("print('new')\n", encoding="utf-8")
            plugin_dir = root_path / "homebrew" / "plugins" / "DeckMind"
            plugin_dir.mkdir(parents=True)
            module.__file__ = str(plugin_dir / "installer.py")
            resolved_plugin_dir = plugin_dir.resolve(strict=False)

            installer = module.RuntimeInstaller(
                runtime_dir=root_path / "runtime",
                cache_dir=root_path / "cache",
            )
            copy_calls = 0

            def flaky_copy(src: Path, target: Path) -> None:
                nonlocal copy_calls
                copy_calls += 1
                if copy_calls == 1:
                    raise OSError("permission denied")
                target.write_text(Path(src).read_text(encoding="utf-8"), encoding="utf-8")

            with (
                patch.object(installer, "_fix_plugin_dir_permissions", create=True) as fix_permissions,
                patch.object(module.shutil, "copy2", side_effect=flaky_copy),
                patch.object(module.os, "getuid", return_value=0),
            ):
                result = installer._sync_plugin()
                copied_text = (resolved_plugin_dir / "main.py").read_text(encoding="utf-8")

            self.assertTrue(result["ok"])
            self.assertEqual(result["files"], 1)
            self.assertEqual(copy_calls, 2)
            self.assertGreaterEqual(fix_permissions.call_count, 2)
            self.assertEqual(copied_text, "print('new')\n")

    def test_install_syncs_plugin_before_dependency_install(self) -> None:
        module = load_installer_module()
        with tempfile.TemporaryDirectory() as root:
            runtime_dir = Path(root) / "runtime"
            (runtime_dir / ".git").mkdir(parents=True)
            installer = module.RuntimeInstaller(
                runtime_dir=runtime_dir,
                cache_dir=Path(root) / "cache",
            )
            order: list[str] = []

            def fake_sync_plugin() -> dict[str, object]:
                order.append("plugin")
                return {"ok": True, "files": 3}

            def fake_install_deps() -> dict[str, object]:
                order.append("deps")
                return {"ok": False, "error": "pip failed"}

            with (
                patch.object(installer, "_run_git"),
                patch.object(installer, "_git_commit", return_value="abc123"),
                patch.object(installer, "_fix_permissions"),
                patch.object(installer, "_sync_plugin", side_effect=fake_sync_plugin),
                patch.object(installer, "_install_python_deps", side_effect=fake_install_deps),
            ):
                result = installer.install()

        self.assertEqual(order, ["plugin", "deps"])
        self.assertEqual(result["plugin"], {"ok": True, "files": 3})
        self.assertEqual(result["deps"], {"ok": False, "error": "pip failed"})

    def test_dependency_failure_hint_does_not_include_abi_flag(self) -> None:
        module = load_installer_module()
        with tempfile.TemporaryDirectory() as root:
            runtime_dir = Path(root) / "runtime"
            runtime_dir.mkdir()
            (runtime_dir / "requirements.txt").write_text("openai\n", encoding="utf-8")
            installer = module.RuntimeInstaller(
                runtime_dir=runtime_dir,
                cache_dir=Path(root) / "cache",
            )

            with (
                patch.object(installer, "_decky_python_version", return_value=(3, 11)),
                patch.object(installer, "_find_matching_python", return_value=None),
                patch.object(installer, "_find_system_python", return_value="python3"),
                patch.object(installer, "_probe_python", return_value=(3, 13)),
                patch.object(installer, "_pip_install_to_vendor", return_value=(False, "pip failed")),
            ):
                result = installer._install_python_deps()

        self.assertFalse(result["ok"])
        self.assertIn("--platform manylinux2014_x86_64", result["error"])
        self.assertNotIn("--abi", result["error"])

    def test_find_system_python_emits_probe_progress(self) -> None:
        module = load_installer_module()
        with tempfile.TemporaryDirectory() as root:
            installer = module.RuntimeInstaller(
                runtime_dir=Path(root) / "runtime",
                cache_dir=Path(root) / "cache",
            )

            with patch.object(
                installer,
                "_probe_python",
                side_effect=[None, (3, 13)],
            ):
                found = installer._find_system_python()

            progress = installer.get_progress(0)["events"]

        self.assertEqual(found, "/usr/bin/python")
        probe_messages = [
            event["message"]
            for event in progress
            if event["stage"] == "deps.python_probe"
        ]
        self.assertIn("探测 /usr/bin/python3", probe_messages)
        self.assertIn("探测 /usr/bin/python", probe_messages)
        self.assertIn("找到 /usr/bin/python (Python 3.13)", probe_messages)

    def test_python_probe_timeout_is_short(self) -> None:
        module = load_installer_module()

        self.assertLessEqual(module.PYTHON_PROBE_TIMEOUT, 3)


if __name__ == "__main__":
    unittest.main()
