"""Reject unsealed distribution code before any extracted launcher is executed."""

import hashlib
import io
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from scripts.check_release import verify
from scripts.release_support import extract_plain_tar


class ReleaseSealTests(unittest.TestCase):
    def test_tar_links_and_traversal_are_refused_before_any_write(self):
        for kind, name in (
            (tarfile.SYMTYPE, "safe/link"),
            (tarfile.REGTYPE, "../escape"),
            (tarfile.REGTYPE, "C:escape"),
        ):
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    encoded = io.BytesIO()
                    with tarfile.open(fileobj=encoded, mode="w") as archive:
                        entry = tarfile.TarInfo(name)
                        entry.type = kind
                        entry.linkname = "/outside" if kind == tarfile.SYMTYPE else ""
                        archive.addfile(entry)
                    encoded.seek(0)
                    with tarfile.open(fileobj=encoded, mode="r") as archive:
                        with self.assertRaises(ValueError):
                            extract_plain_tar(archive, root / "new")
                    self.assertEqual(list((root / "new").iterdir()), [])

    def test_zip_drive_relative_path_is_not_a_release_member(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "unsafe.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("C:escape", b"x")
            with mock.patch("scripts.check_release.subprocess.run") as run:
                with self.assertRaises(ValueError):
                    verify(path)
                run.assert_not_called()

    def archive(self, root, seal, extra=False):
        path = root / "candidate.zip"
        with zipfile.ZipFile(path, "w") as out:
            out.writestr("candidate/archivist.py", b'raise RuntimeError("must not execute")\n')
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
