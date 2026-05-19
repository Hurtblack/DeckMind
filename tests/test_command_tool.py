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
            result.argv[4],
            str((Path.home() / "Downloads" / "Clash.Verge.AppImage").resolve(strict=False)),
        )
        self.assertEqual(result.argv[1], "-q")
        self.assertNotIn("~", result.argv[4])

    def test_allows_curl_header_check(self) -> None:
        result = validate_command([
            "curl",
            "-L",
            "-I",
            "https://example.com/Clash.Verge.AppImage",
        ])

        self.assertTrue(result.ok)
        self.assertTrue(result.read_only)
        self.assertEqual(result.argv[1], "-q")

    def test_wget_download_disables_user_config(self) -> None:
        from unittest.mock import patch

        module = load_command_tool()

        with patch("shutil.which", return_value="/usr/bin/wget"):
            result = module.validate_command([
                "wget",
                "-O",
                "~/Downloads/app.AppImage",
                "https://example.com/app.AppImage",
            ])

        self.assertTrue(result.ok)
        self.assertEqual(result.argv[1], "--no-config")
        self.assertEqual(
            result.argv[3],
            str((Path.home() / "Downloads" / "app.AppImage").resolve(strict=False)),
        )

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

    def test_rejects_executable_resolved_outside_trusted_dirs(self) -> None:
        from unittest.mock import patch

        module = load_command_tool()

        with patch("shutil.which", return_value="/tmp/evil-curl"):
            result = module.validate_command(["curl", "-I", "https://example.com"])

        self.assertFalse(result.ok)
        self.assertIn("resolved outside trusted executable directories", result.reason or "")

    def test_rejects_home_executable_even_when_allowlisted_name_matches(self) -> None:
        from unittest.mock import patch

        module = load_command_tool()

        with patch("shutil.which", return_value=str(Path.home() / "bin" / "curl")):
            result = module.validate_command(["curl", "-I", "https://example.com"])

        self.assertFalse(result.ok)
        self.assertIn("resolved outside trusted executable directories", result.reason or "")

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


class CommandToolArchiveAndLaunchTests(unittest.TestCase):
    def setUp(self) -> None:
        import shutil

        self.root = Path(__file__).resolve().parents[1] / ".test-command-tool"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.root, ignore_errors=True)

    def _write_tar(self, name: str, member_name: str) -> Path:
        import io
        import tarfile

        archive = self.root / name
        payload = b"#!/bin/sh\n"
        info = tarfile.TarInfo(member_name)
        info.size = len(payload)
        with tarfile.open(archive, "w:gz") as tar:
            tar.addfile(info, io.BytesIO(payload))
        return archive

    def _approved_dir_patches(self, module):
        from unittest.mock import patch

        root = str(self.root.resolve(strict=False))
        return (
            patch.object(module, "_APPROVED_WRITE_DIRS", (root,)),
            patch.object(module, "_APPROVED_READ_DIRS", (root,)),
        )

    def test_tar_extract_validates_archive_members_and_paths(self) -> None:
        from unittest.mock import patch

        module = load_command_tool()
        archive = self._write_tar("Clash.Verge_x64.app.tar.gz", "Clash Verge/clash-verge")
        dest = self.root / "extract"
        dest.mkdir()

        write_patch, read_patch = self._approved_dir_patches(module)
        with (
            patch("shutil.which", return_value="/usr/bin/tar"),
            write_patch,
            read_patch,
        ):
            result = module.validate_command(["tar", "-xzf", str(archive), "-C", str(dest)])

        self.assertTrue(result.ok)
        self.assertEqual(result.command, "tar")
        self.assertEqual(result.argv[2], str(archive.resolve(strict=False)))
        self.assertEqual(result.argv[4], str(dest.resolve(strict=False)))
        self.assertEqual(result.output_path, str(dest.resolve(strict=False)))

    def test_tar_extract_rejects_path_traversal_member(self) -> None:
        from unittest.mock import patch

        module = load_command_tool()
        archive = self._write_tar("bad.tar.gz", "../evil")
        dest = self.root / "extract"
        dest.mkdir()

        write_patch, read_patch = self._approved_dir_patches(module)
        with (
            patch("shutil.which", return_value="/usr/bin/tar"),
            write_patch,
            read_patch,
        ):
            result = module.validate_command(["tar", "-xzf", str(archive), "-C", str(dest)])

        self.assertFalse(result.ok)
        self.assertIn("unsafe tar member path", result.reason or "")

    def test_launch_file_validates_approved_executable(self) -> None:
        module = load_command_tool()
        executable = self.root / "clash-verge"
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o755)

        write_patch, read_patch = self._approved_dir_patches(module)
        with write_patch, read_patch:
            result = module.validate_command(["launch_file", str(executable)])

        self.assertTrue(result.ok)
        self.assertEqual(result.command, "launch_file")
        self.assertEqual(result.argv, [str(executable.resolve(strict=False))])

    def test_launch_file_rejects_non_executable(self) -> None:
        module = load_command_tool()
        executable = self.root / "clash-verge"
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o644)

        write_patch, read_patch = self._approved_dir_patches(module)
        with write_patch, read_patch:
            result = module.validate_command(["launch_file", str(executable)])

        self.assertFalse(result.ok)
        self.assertIn("launch target must be executable", result.reason or "")

    def test_launch_validated_uses_desktop_environment_without_preload(self) -> None:
        import asyncio
        from unittest.mock import AsyncMock, patch

        module = load_command_tool()
        executable = self.root / "clash-verge"
        executable.write_text("#!/bin/sh\n", encoding="utf-8")
        executable.chmod(0o755)
        validation = module.ValidationResult(
            True,
            [str(executable.resolve(strict=False))],
            command="launch_file",
        )
        captured = {}

        class FakeProcess:
            pid = 12345

        async def fake_create_subprocess_exec(*argv, **kwargs):
            captured["argv"] = argv
            captured["cwd"] = kwargs.get("cwd")
            captured["env"] = kwargs.get("env")
            return FakeProcess()

        async def launch_with_env_capture():
            with (
                patch.dict(module.os.environ, {"DISPLAY": ":1", "LD_PRELOAD": "bad"}, clear=False),
                patch.object(
                    module.asyncio,
                    "create_subprocess_exec",
                    AsyncMock(side_effect=fake_create_subprocess_exec),
                ),
            ):
                return await module._launch_validated(validation)

        result = asyncio.run(launch_with_env_capture())

        self.assertTrue(result["ok"])
        self.assertEqual(result["pid"], 12345)
        self.assertEqual(captured["cwd"], str(executable.parent.resolve(strict=False)))
        self.assertEqual(captured["env"]["DISPLAY"], ":1")
        self.assertNotIn("LD_PRELOAD", captured["env"])


class CommandToolExecutionPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_command_returns_dry_run_preview_without_confirmation(self) -> None:
        module = load_command_tool()

        result = await module.run_command(["which", "sh"], confirm=False)

        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["command"], "which")

    async def test_run_command_executes_harmless_which_with_confirmation(self) -> None:
        module = load_command_tool()

        result = await module.run_command(["which", "sh"], confirm=True)

        self.assertTrue(result["ok"])
        self.assertEqual(result["command"], "which")
        self.assertEqual(result["returncode"], 0)
        self.assertTrue(result["stdout_tail"])


class CommandToolExecutionFailureTests(unittest.TestCase):
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

    def test_execute_validated_uses_minimal_environment(self) -> None:
        import asyncio
        from unittest.mock import AsyncMock, patch

        module = load_command_tool()

        class FakeProcess:
            returncode = 0

            async def communicate(self):
                return b"/bin/sh\n", b""

        captured = {}

        async def fake_create_subprocess_exec(*argv, **kwargs):
            captured["argv"] = argv
            captured["env"] = kwargs.get("env")
            return FakeProcess()

        validation = module.ValidationResult(True, ["/usr/bin/which", "sh"], command="which", read_only=True)

        async def execute_with_env_capture():
            with patch.object(
                module.asyncio,
                "create_subprocess_exec",
                AsyncMock(side_effect=fake_create_subprocess_exec),
            ):
                return await module._execute_validated(validation)

        result = asyncio.run(execute_with_env_capture())

        self.assertTrue(result["ok"])
        self.assertIsNotNone(captured["env"])
        self.assertIn("PATH", captured["env"])
        self.assertNotIn("LD_PRELOAD", captured["env"])
        self.assertNotIn("CURL_HOME", captured["env"])
        self.assertNotIn("WGETRC", captured["env"])

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


class CommandToolRegistryTests(unittest.TestCase):
    def test_run_command_is_registered(self) -> None:
        from tools import get, specs

        self.assertIsNotNone(get("run_command"))
        names = {spec.name for spec in specs()}
        self.assertIn("run_command", names)


if __name__ == "__main__":
    unittest.main()
