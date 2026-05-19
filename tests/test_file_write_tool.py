from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path


def load_file_write_tool():
    module_path = Path(__file__).resolve().parents[1] / "tools" / "file_write_tool.py"
    spec = importlib.util.spec_from_file_location("file_write_tool_under_test", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load file_write_tool from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module


class FileWriteHighRiskTests(unittest.TestCase):
    def setUp(self) -> None:
        import shutil

        self.root = Path(__file__).resolve().parents[1] / ".test-file-write-tool"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.root, ignore_errors=True)

    def test_sensitive_path_dry_run_requires_high_risk_confirmation(self) -> None:
        from unittest.mock import patch

        module = load_file_write_tool()
        target = self.root / "secret-token-store"

        async def preview():
            with patch.object(module, "_WRITE_BASES", (str(self.root),)):
                return await module.write_text_file(str(target), "TOKEN=abc123", confirm=False)

        result = asyncio.run(preview())

        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertTrue(result["requires_high_risk_confirm"])
        self.assertTrue(result["preview_redacted"])
        self.assertNotIn("abc123", str(result))

    def test_sensitive_path_refuses_normal_confirmation(self) -> None:
        from unittest.mock import patch

        module = load_file_write_tool()
        target = self.root / "secret-token-store"

        async def write_without_high_risk_confirm():
            with patch.object(module, "_WRITE_BASES", (str(self.root),)):
                return await module.write_text_file(str(target), "TOKEN=abc123", confirm=True)

        result = asyncio.run(write_without_high_risk_confirm())

        self.assertFalse(result["ok"])
        self.assertTrue(result["refused"])
        self.assertTrue(result["requires_high_risk_confirm"])
        self.assertFalse(target.exists())

    def test_sensitive_path_writes_after_explicit_high_risk_confirmation(self) -> None:
        from unittest.mock import patch

        module = load_file_write_tool()
        target = self.root / "secret-token-store"

        async def write_with_high_risk_confirm():
            with patch.object(module, "_WRITE_BASES", (str(self.root),)):
                return await module.write_text_file(
                    str(target),
                    "TOKEN=abc123",
                    confirm=True,
                    high_risk_confirm=True,
                )

        result = asyncio.run(write_with_high_risk_confirm())

        self.assertTrue(result["ok"])
        self.assertTrue(result["written"])
        self.assertEqual(target.read_text(encoding="utf-8"), "TOKEN=abc123")


if __name__ == "__main__":
    unittest.main()
