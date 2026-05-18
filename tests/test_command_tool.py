from __future__ import annotations

import unittest

from tools.command_tool import validate_command


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
        result = validate_command([
            "systemctl",
            "--user",
            "status",
            "deckmind-agent.service",
        ])

        self.assertTrue(result.ok)
        self.assertTrue(result.read_only)

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


if __name__ == "__main__":
    unittest.main()
