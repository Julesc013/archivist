"""Runtime capability failures remain diagnosable without workspace writes."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from archivist.application import Application, diagnose_runtime
from archivist.util import Problem


class DiagnosticsTests(unittest.TestCase):
    def test_doctor_does_not_create_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "absent-workspace"
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(ROOT / "archivist.py"),
                    "--workspace",
                    str(workspace),
                    "--json",
                    "doctor",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertIn("compatible", report["runtime"])
            self.assertFalse(workspace.exists())

    def test_incompatible_sqlite_diagnosed_before_workspace_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "absent-workspace"
            with mock.patch("archivist.compat.sqlite3.sqlite_version_info", (3, 30, 0)):
                report = diagnose_runtime(workspace)
                self.assertFalse(report["runtime"]["compatible"])
                self.assertEqual(
                    next(x for x in report["checks"] if x["id"] == "sqlite")["state"], "unsupported"
                )
                with self.assertRaises(Problem):
                    Application(workspace)
            self.assertFalse(workspace.exists())

    def test_doctor_reports_offline_or_malformed_remembered_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "offline-workspace"
            config = root / "config"
            config.mkdir()
            launcher = config / "launcher.json"
            environment = dict(os.environ)
            environment.pop("ARCHIVIST_WORKSPACE", None)
            environment["ARCHIVIST_CONFIG_HOME"] = str(config)
            variants = [
                (json.dumps({"workspace": str(workspace)}), "WORKSPACE_OFFLINE"),
                ("{broken JSON", "JSONDecodeError"),
            ]
            for contents, code in variants:
                with self.subTest(code=code):
                    launcher.write_text(contents, encoding="utf-8")
                    result = subprocess.run(
                        [sys.executable, "-I", str(ROOT / "archivist.py"), "--json", "doctor"],
                        capture_output=True,
                        text=True,
                        timeout=15,
                        env=environment,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    report = json.loads(result.stdout)
                    self.assertIn("compatible", report["runtime"])
                    self.assertEqual(report["workspace_error"]["code"], code)
                    self.assertEqual(
                        next(row for row in report["checks"] if row["id"] == "workspace")["state"],
                        "unavailable",
                    )
                    self.assertEqual(launcher.read_text(encoding="utf-8"), contents)
                    self.assertFalse(workspace.exists())

    def test_ascii_console_can_show_diagnostics_for_unicode_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "日本語"
            environment = dict(os.environ, PYTHONIOENCODING="ascii:strict")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "archivist.py"),
                    "--workspace",
                    str(workspace),
                    "doctor",
                ],
                capture_output=True,
                env=environment,
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout.decode("ascii"))
            self.assertEqual(Path(report["workspace"]), workspace)
            self.assertFalse(workspace.exists())


if __name__ == "__main__":
    unittest.main()
