"""Release preparation rejects failed/stale evidence and changed qualified bytes."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from archivist import __version__
from scripts import prepare_release


class ReleasePreparationTests(unittest.TestCase):
    def fixture(self, root):
        inputs = root / "inputs"
        commit = "a" * 40

        def write(name, value):
            path = inputs / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value), encoding="utf-8")

        write(
            "tests-linux/native-validation.json",
            {
                "source_commit": commit,
                "product_version": __version__,
                "run": 1,
                "failed": 0,
                "errors": 0,
            },
        )
        for engine in ("chromium", "firefox", "webkit"):
            write(
                "browser-" + engine + "/native/gui-validation.json",
                {
                    "status": "PASS",
                    "browser": engine,
                    "browser_version": "fixture",
                },
            )
        write(
            "browser-chromium/fallback/gui-validation.json",
            {
                "status": "PASS",
                "forced_dialog_fallback": True,
            },
        )
        qualified = inputs / "qualified-distributions"
        artifacts = []
        for name, directory in (
            ("portable.zip", "dist"),
            ("portable.tar.gz", "dist"),
            ("installed.whl", "python-distribution-check"),
            ("source.tar.gz", "python-distribution-check"),
        ):
            path = qualified / directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic distribution gate fixture: " + name.encode("ascii"))
            artifacts.append(
                {"file": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            )
        write(
            "qualified-distributions/dist/build-receipt.json",
            {
                "version": __version__,
                "artifacts": artifacts[:2],
            },
        )
        write(
            "qualified-distributions/python-distribution-check/qualification.json",
            {
                "state": "PASS",
                "product_version": __version__,
                "artifacts": artifacts[2:],
            },
        )
        write(
            "python38-distribution-proof/qualification.json",
            {
                "state": "PASS",
                "product_version": __version__,
            },
        )
        write(
            "qualified-distributions/packaging-validation.json",
            [
                {"isolated_launcher": "PASS"},
                {"isolated_launcher": "PASS"},
            ],
        )
        (root / "CHANGELOG.md").write_text("## [" + __version__ + "]\nFixture release.\n")
        return inputs, commit

    def test_changed_distribution_is_rejected_before_assets_are_created(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, commit = self.fixture(root)
            (inputs / "qualified-distributions/dist/portable.zip").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                prepare_release.prepare(inputs, root / "out", commit, "https://example.invalid/run")
            self.assertFalse((root / "out").exists())

    def test_stale_commit_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, _ = self.fixture(root)
            with self.assertRaisesRegex(ValueError, "different commit"):
                prepare_release.prepare(
                    inputs, root / "out", "b" * 40, "https://example.invalid/run"
                )
            self.assertFalse((root / "out").exists())

    def test_success_seals_all_assets_and_retains_exact_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs, commit = self.fixture(root)
            with mock.patch.object(prepare_release, "ROOT", root):
                receipt = prepare_release.prepare(
                    inputs, root / "out", commit, "https://example.invalid/run"
                )
            self.assertEqual(receipt["source_commit"], commit)
            self.assertEqual(receipt["physical_tape_qualification"], "NOT_PERFORMED")
            out = root / "out"
            sealed = set()
            for line in (out / "SHA256SUMS").read_text().splitlines():
                expected, name = line.split("  ", 1)
                self.assertEqual(hashlib.sha256((out / name).read_bytes()).hexdigest(), expected)
                sealed.add(name)
            self.assertEqual(sealed, {path.name for path in out.iterdir()} - {"SHA256SUMS"})
            self.assertIn(commit, (root / "release-notes.md").read_text())
