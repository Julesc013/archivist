"""Reject unsealed distribution code before any extracted launcher is executed."""

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from scripts.check_release import verify


class ReleaseSealTests(unittest.TestCase):
    def archive(self, root, seal, extra=False):
        path = root / "candidate.zip"
        with zipfile.ZipFile(path, "w") as out:
            out.writestr(
                "candidate/archivist.py", b'raise RuntimeError("must not execute")\n'
            )
            out.writestr("candidate/SHA256SUMS", seal)
            if extra:
                out.writestr("candidate/unsealed.py", b"pass\n")
        return path

    def test_empty_seal_rejects_before_launcher(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = self.archive(Path(temp), "")
            with mock.patch("scripts.check_release.subprocess.run") as run:
                with self.assertRaisesRegex(ValueError, "exactly all source files"):
                    verify(archive)
                run.assert_not_called()

    def test_extra_unsealed_file_rejects_before_launcher(self):
        with tempfile.TemporaryDirectory() as temp:
            sha = hashlib.sha256(b'raise RuntimeError("must not execute")\n').hexdigest()
            archive = self.archive(Path(temp), sha + "  archivist.py\n", extra=True)
            with mock.patch("scripts.check_release.subprocess.run") as run:
                with self.assertRaisesRegex(ValueError, "exactly all source files"):
                    verify(archive)
                run.assert_not_called()

    def test_duplicate_checksum_entry_rejects_before_launcher(self):
        with tempfile.TemporaryDirectory() as temp:
            sha = hashlib.sha256(b'raise RuntimeError("must not execute")\n').hexdigest()
            archive = self.archive(Path(temp), (sha + "  archivist.py\n") * 2)
            with mock.patch("scripts.check_release.subprocess.run") as run:
                with self.assertRaisesRegex(ValueError, "Unsafe seal path"):
                    verify(archive)
                run.assert_not_called()
