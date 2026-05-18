from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


def load_command_tool():
    module_path = Path(__file__).resolve().parents[1] / "tools" / "command_tool.py"
    spec = importlib.util.spec_from_file_location("command_tool_under_test", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load command_tool from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module


def validate_command(argv: list[str]):
    return load_command_tool().validate_command(argv)


class CommandToolValidationTests(unittest.TestCase):
    def test_allows_curl_download_to_downloads(self) -> None:
        result = validate_command([
            "curl",
            "-L",
            "-o",
            "~/Downloads/Clash.Verge.AppImage",
            "https://example.com/Clash.Verge.AppImage",
        ])

        self.assertTrue(result.ok)
        self.assertEqual(result.command, "curl")
        self.assertFalse(result.read_only)

    def test_which_argv_uses_trusted_absolute_executable(self) -> None:
        result = validate_command(["which", "sh"])

        self.assertTrue(result.ok)
        self.assertNotEqual(result.argv[0], "which")
        self.assertTrue(Path(result.argv[0]).is_absolute())

    def test_curl_download_argv_uses_expanded_output_path(self) -> None:
        result = validate_command([
            "curl",
            "-L",
            "-o",
            "~/Downloads/Clash.Verge.AppImage",
            "https://example.com/Clash.Verge.AppImage",
        ])

        self.assertTrue(result.ok)
        self.assertNotEqual(result.argv[0], "curl")
        self.assertTrue(Path(result.argv[0]).is_absolute())
        self.assertEqual(
            result.argv[3],
            str((Path.home() / "Downloads" / "Clash.Verge.AppImage").resolve(strict=False)),
        )
        self.assertNotIn("~", result.argv[3])

    def test_allows_curl_header_check(self) -> None:
        result = validate_command([
            "curl",
            "-L",
            "-I",
            "https://example.com/Clash.Verge.AppImage",
        ])

        self.assertTrue(result.ok)
        self.assertTrue(result.read_only)

    def test_rejects_shell_compound_command(self) -> None:
        result = validate_command([
            "curl",
            "-L",
            "-o",
            "~/Downloads/app",
            "https://example.com/app",
            "&&",
            "chmod",
            "+x",
            "~/Downloads/app",
        ])

        self.assertFalse(result.ok)
        self.assertIn("shell metacharacter", result.reason or "")

    def test_rejects_missing_allowlisted_command(self) -> None:
        from unittest.mock import patch

        module = load_command_tool()

        with patch("shutil.which", return_value=None):
            result = module.validate_command(["which", "sh"])

        self.assertFalse(result.ok)
        self.assertIn("allowlisted command not found", result.reason or "")

    def test_rejects_writes_outside_allowed_dirs(self) -> None:
        result = validate_command([
            "curl",
            "-L",
            "-o",
            "/tmp/app.AppImage",
            "https://example.com/app.AppImage",
        ])

        self.assertFalse(result.ok)
        self.assertIn("outside allowed write directories", result.reason or "")

    def test_mkdir_argv_uses_expanded_directory_path(self) -> None:
        result = validate_command([
            "mkdir",
            "-p",
            "~/.deckmind/apps",
        ])

        self.assertTrue(result.ok)
        self.assertEqual(
            result.argv[2],
            str((Path.home() / ".deckmind" / "apps").resolve(strict=False)),
        )
        self.assertNotIn("~", result.argv[2])

    def test_rejects_dollar_expansion_in_path(self) -> None:
        result = validate_command([
            "mkdir",
            "-p",
            "$HOME/Downloads/app",
        ])

        self.assertFalse(result.ok)
        self.assertIn("shell metacharacter", result.reason or "")

    def test_rejects_sensitive_path_fragment(self) -> None:
        result = validate_command([
            "mkdir",
            "-p",
            "~/.deckmind/secret-token-store",
        ])

        self.assertFalse(result.ok)
        self.assertIn("sensitive path fragment", result.reason or "")

    def test_rejects_recursive_chmod(self) -> None:
        result = validate_command([
            "chmod",
            "-R",
            "+x",
            "~/Downloads/app.AppImage",
        ])

        self.assertFalse(result.ok)
        self.assertIn("only chmod +x", result.reason or "")

    def test_rejects_numeric_chmod(self) -> None:
        result = validate_command([
            "chmod",
            "777",
            "~/Downloads/app.AppImage",
        ])

        self.assertFalse(result.ok)
        self.assertIn("only chmod +x", result.reason or "")

    def test_rejects_system_systemctl(self) -> None:
        result = validate_command([
            "systemctl",
            "restart",
            "sshd.service",
        ])

        self.assertFalse(result.ok)
        self.assertIn("systemctl --user", result.reason or "")

    def test_allows_user_systemctl_status(self) -> None:
        from unittest.mock import patch

        module = load_command_tool()
        with patch("shutil.which", return_value="/usr/bin/systemctl"):
            result = module.validate_command([
                "systemctl",
                "--user",
                "status",
                "deckmind-agent.service",
            ])

        self.assertTrue(result.ok)
        self.assertTrue(result.read_only)
        self.assertEqual(result.argv[0], "/usr/bin/systemctl")

    def test_rejects_credential_like_url(self) -> None:
        result = validate_command([
            "curl",
            "-L",
            "-o",
            "~/Downloads/app.AppImage",
            "https://example.com/app.AppImage?token=abc",
        ])

        self.assertFalse(result.ok)
        self.assertIn("credential-like URL parameter", result.reason or "")

    def test_execute_validated_times_out(self) -> None:
        import asyncio
        from unittest.mock import AsyncMock, patch

        module = load_command_tool()

        class FakeProcess:
            returncode = None

            async def communicate(self):
                return b"", b""

            def kill(self) -> None:
                return None

            async def wait(self) -> None:
                return None

        fake_proc = FakeProcess()
        validation = module.ValidationResult(True, ["which", "sh"], command="which", read_only=True)

        async def execute_timeout():
            with (
                patch.object(module.asyncio, "create_subprocess_exec", AsyncMock(return_value=fake_proc)),
                patch.object(module.asyncio, "wait_for", AsyncMock(side_effect=asyncio.TimeoutError)),
            ):
                return await module._execute_validated(validation)

        result = asyncio.run(execute_timeout())

        self.assertFalse(result["ok"])
        self.assertEqual(result["returncode"], -1)
        self.assertIn("timed out after 60 seconds", result["error"])

    def test_execute_validated_returns_structured_startup_failure(self) -> None:
        import asyncio

        module = load_command_tool()
        validation = module.ValidationResult(
            True,
            ["/definitely/missing"],
            command="which",
            read_only=True,
        )

        result = asyncio.run(module._execute_validated(validation))

        self.assertFalse(result["ok"])
        self.assertEqual(result["command"], "which")
        self.assertIn("failed to start command", result["error"])


if __name__ == "__main__":
    unittest.main()
