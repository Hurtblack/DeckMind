from __future__ import annotations

import asyncio
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def load_decky_plugin_tool():
    module_path = Path(__file__).resolve().parents[1] / "tools" / "decky_plugin_tool.py"
    spec = importlib.util.spec_from_file_location("decky_plugin_tool_under_test", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load decky_plugin_tool from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_source(root: Path) -> Path:
    source = root / "project" / "decky-plugin"
    (source / "dist").mkdir(parents=True)
    (source / "src").mkdir()
    (source / "scripts").mkdir()
    (source / "node_modules").mkdir()
    (source / "__pycache__").mkdir()
    (source / "plugin.json").write_text('{"name":"DeckMind"}\n', encoding="utf-8")
    (source / "main.py").write_text("class Plugin:\n    pass\n", encoding="utf-8")
    (source / "dist" / "index.js").write_text("export default {};\n", encoding="utf-8")
    (source / "src" / "index.tsx").write_text("// source\n", encoding="utf-8")
    (source / "scripts" / "deploy-local.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (source / "node_modules" / "ignored.js").write_text("ignored\n", encoding="utf-8")
    (source / "__pycache__" / "ignored.pyc").write_bytes(b"ignored")
    (source / "tsconfig.json").write_text("{}\n", encoding="utf-8")
    (source / "rollup.config.js").write_text("export default {};\n", encoding="utf-8")
    return source


def make_existing_plugin(root: Path, name: str) -> Path:
    plugin = root / name
    (plugin / "dist").mkdir(parents=True)
    (plugin / "plugin.json").write_text(f'{{"name":"{name}"}}\n', encoding="utf-8")
    (plugin / "dist" / "index.js").write_text("export default {};\n", encoding="utf-8")
    return plugin


class DeckyPluginDeployToolTests(unittest.TestCase):
    def test_dry_run_reports_plan_without_copying(self) -> None:
        module = load_decky_plugin_tool()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            target = root / "homebrew" / "plugins" / "DeckMind"
            make_existing_plugin(target.parent, "PowerTools")

            async def run():
                with patch.object(module, "_PLUGIN_SOURCE_DIR", source):
                    return await module.install_decky_plugin(
                        target_dir=str(target),
                        confirm=False,
                    )

            result = asyncio.run(run())

            self.assertTrue(result["ok"])
            self.assertTrue(result["dry_run"])
            self.assertEqual(result["source_dir"], str(source.resolve(strict=False)))
            self.assertEqual(result["target_dir"], str(target.resolve(strict=False)))
            self.assertEqual(result["plugin_root"], str(target.parent.resolve(strict=False)))
            self.assertTrue(result["plugin_root_exists"])
            self.assertTrue(result["plugin_root_matches_decky_path"])
            self.assertEqual(result["existing_plugins"][0]["directory"], "PowerTools")
            self.assertTrue(result["existing_plugins"][0]["looks_like_decky_plugin"])
            self.assertIn("plugin.json", result["included_files"])
            self.assertFalse(target.exists())

    def test_confirm_deploys_plugin_and_deletes_stale_files(self) -> None:
        module = load_decky_plugin_tool()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            target = root / "homebrew" / "plugins" / "DeckMind"
            target.mkdir(parents=True)
            (target / "stale.txt").write_text("old\n", encoding="utf-8")

            async def run():
                with patch.object(module, "_PLUGIN_SOURCE_DIR", source):
                    return await module.install_decky_plugin(
                        target_dir=str(target),
                        confirm=True,
                    )

            result = asyncio.run(run())

            self.assertTrue(result["ok"])
            self.assertTrue(result["deployed"])
            self.assertTrue((target / "plugin.json").exists())
            self.assertTrue((target / "main.py").exists())
            self.assertTrue((target / "dist" / "index.js").exists())
            self.assertFalse((target / "stale.txt").exists())
            self.assertFalse((target / "src").exists())
            self.assertFalse((target / "scripts").exists())
            self.assertFalse((target / "node_modules").exists())
            self.assertFalse((target / "__pycache__").exists())
            self.assertFalse((target / "tsconfig.json").exists())
            self.assertFalse((target / "rollup.config.js").exists())

    def test_refuses_target_outside_decky_plugins_root(self) -> None:
        module = load_decky_plugin_tool()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = make_source(root)
            target = root / "Desktop" / "DeckMind"

            async def run():
                with patch.object(module, "_PLUGIN_SOURCE_DIR", source):
                    return await module.install_decky_plugin(
                        target_dir=str(target),
                        confirm=True,
                    )

            result = asyncio.run(run())

            self.assertFalse(result["ok"])
            self.assertTrue(result["refused"])
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
