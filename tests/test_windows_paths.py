"""Actual Windows junction guards; all paths and targets are owned fixtures."""

import ctypes
from ctypes import wintypes
import os
import subprocess
import unittest

from test_core import Fixture
from archivist import recovery, util
from archivist.store import Store


def volume_reparse_capability(path):
    """Report the actual fixture volume's FILE_SUPPORTS_REPARSE_POINTS flag."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    get_root = kernel.GetVolumePathNameW
    get_root.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
    get_root.restype = wintypes.BOOL
    root = ctypes.create_unicode_buffer(32768)
    if not get_root(str(path), root, len(root)):
        raise ctypes.WinError(ctypes.get_last_error())

    get_info = kernel.GetVolumeInformationW
    get_info.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        wintypes.DWORD,
    )
    get_info.restype = wintypes.BOOL
    flags = wintypes.DWORD()
    filesystem = ctypes.create_unicode_buffer(261)
    if not get_info(
        root.value, None, 0, None, None, ctypes.byref(flags), filesystem, len(filesystem)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return bool(flags.value & 0x80), filesystem.value


@unittest.skipUnless(os.name == "nt", "Requires actual Windows junction/reparse semantics")
class WindowsJunctionTests(Fixture):
    def test_junction_root_refused_and_descendant_excluded(self):
        supported, filesystem = volume_reparse_capability(self.source)
        if not supported:
            self.skipTest(f"Fixture volume {filesystem!r} reports no FILE_SUPPORTS_REPARSE_POINTS")

        target = self.base / "outside-target"
        target.mkdir()
        marker = target / "outside-marker.txt"
        marker_bytes = b"The external target must remain untouched and unscanned."
        marker.write_bytes(marker_bytes)
        local_bytes = b"Included source file."
        self.file("local.txt", local_bytes)
        junction = self.source / "outside-junction"
        try:
            made = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=15,
            )
            # A supported filesystem's unexpected creation failure is a test
            # failure, not a blanket permissions/platform skip.
            self.assertEqual(made.returncode, 0, made.stdout + made.stderr)
            self.assertTrue(junction.lstat().st_file_attributes & 0x400)
            with self.assertRaises(util.Problem) as caught:
                util.no_links(junction)
            self.assertEqual(caught.exception.code, "LINK_PATH")
            with self.assertRaisesRegex(recovery.RecoveryError, "Link/reparse path refused"):
                recovery.no_links(junction)
            self.assert_problem(
                "LINK_PATH", "scan", {"root": str(junction), "backend": "filesystem"}
            )

            scan = self.scan(hash_files=True)
            self.assertEqual(scan["counts"]["eligible_files"], 1)
            self.assertEqual(scan["counts"]["eligible_bytes"], len(local_bytes))
            self.assertEqual(scan["counts"]["excluded"], 1)
            self.assertEqual(scan["counts"]["errors"], 0)
            issues = self.app.call("issues", {"snapshot_id": scan["snapshot_id"]})
            self.assertEqual(
                [(item["code"], item["path"]) for item in issues],
                [("LINK_EXCLUDED", "outside-junction")],
            )
            with Store(self.workspace) as store:
                nodes = store.rows(
                    "SELECT name,kind,eligible FROM nodes WHERE snapshot_id=?",
                    (scan["snapshot_id"],),
                )
            self.assertEqual(
                {node["name"] for node in nodes}, {"", "local.txt", "outside-junction"}
            )
            link = next(node for node in nodes if node["name"] == "outside-junction")
            self.assertEqual((link["kind"], link["eligible"]), ("link", 0))
        finally:
            # Remove the junction itself, never recursively delete its target.
            if os.path.lexists(junction):
                os.rmdir(junction)
            self.assertFalse(os.path.lexists(junction))
            self.assertEqual(marker.read_bytes(), marker_bytes)
