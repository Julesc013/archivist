"""Runtime negotiation and narrowly scoped native-filesystem compatibility."""

import contextlib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import sqlite3
import stat
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

from test_core import Fixture
from archivist import compat, evidence, inventory, recovery, util
from archivist.store import Store


class RuntimeCompatibilityTests(Fixture):
    def test_observed_runtime_capabilities_need_no_workspace(self):
        before = set(self.base.rglob("*"))
        report = compat.runtime_capabilities()
        self.assertTrue(report["compatible"], report)
        self.assertEqual(
            report["sqlite_pragmas"], {"trusted_schema": 0, "foreign_keys": 1, "query_only": 0}
        )
        self.assertTrue(report["sqlite_upsert"])
        self.assertTrue(report["sqlite_backup"])
        self.assertTrue(report["sqlite_read_only"])
        self.assertEqual(set(self.base.rglob("*")), before)

    def test_old_sqlite_is_rejected_before_creating_workspace(self):
        output = self.base / "unsupported-workspace"
        with mock.patch.object(compat.sqlite3, "sqlite_version_info", (3, 30, 1)):
            with self.assertRaises(util.Problem) as caught:
                Store(output)
            self.assertEqual(caught.exception.code, "SQLITE_VERSION")
            self.assertFalse(output.exists())
            report = compat.runtime_capabilities()
            self.assertFalse(report["compatible"])
            self.assertEqual(report["error"]["code"], "SQLITE_VERSION")

    def test_unknown_pragma_is_not_silently_treated_as_protection(self):
        connection = mock.Mock()
        connection.execute.return_value.fetchone.return_value = None
        with self.assertRaises(util.Problem) as caught:
            compat.configure_sqlite(connection)
        self.assertEqual(caught.exception.code, "SQLITE_CAPABILITY")
        self.assertEqual(caught.exception.detail["setting"], "trusted_schema")

    def test_ignored_foreign_keys_setting_in_transaction_is_refused(self):
        db = sqlite3.connect(":memory:")
        try:
            db.execute("CREATE TABLE values_for_probe(value INTEGER)")
            db.execute("INSERT INTO values_for_probe VALUES (1)")
            with self.assertRaises(util.Problem) as caught:
                compat.configure_sqlite(db)
            self.assertEqual(caught.exception.detail["setting"], "foreign_keys")
        finally:
            db.close()

    def test_foreign_key_enforcement_and_read_only_import_are_observed(self):
        path = self.base / "evidence.sqlite"
        db = sqlite3.connect(path)
        try:
            compat.configure_sqlite(db)
            db.execute("CREATE TABLE parent(id INTEGER PRIMARY KEY)")
            db.execute("CREATE TABLE child(parent_id INTEGER REFERENCES parent(id))")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO child VALUES (999)")
            db.rollback()
        finally:
            db.close()
        db = evidence.readonly(path)
        try:
            self.assertEqual(db.execute("PRAGMA trusted_schema").fetchone()[0], 0)
            self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(db.execute("PRAGMA query_only").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("INSERT INTO parent VALUES (1)")
        finally:
            db.close()

    def test_older_path_containment_keeps_component_and_drive_boundaries(self):
        self.assertTrue(util.within(PurePosixPath("/archive/set"), PurePosixPath("/archive")))
        self.assertFalse(util.within(PurePosixPath("/archives"), PurePosixPath("/archive")))
        self.assertTrue(util.within(PureWindowsPath("C:/Archive/x"), PureWindowsPath("c:/archive")))
        self.assertFalse(
            util.within(PureWindowsPath("D:/Archive/x"), PureWindowsPath("C:/Archive"))
        )

    @unittest.skipIf(os.name == "nt", "Tests the POSIX unsupported-primitive branch")
    def test_missing_exclusive_rename_never_uses_overwriting_fallback(self):
        source, destination = self.base / "new", self.base / "existing"
        source.write_bytes(b"new")
        destination.write_bytes(b"keep")
        with mock.patch.object(recovery, "sys", SimpleNamespace(platform="unsupported-posix")):
            with mock.patch.object(recovery.os, "rename") as ordinary:
                with self.assertRaisesRegex(
                    recovery.RecoveryError, "no-replace rename is unavailable"
                ):
                    recovery.publish_new(source, destination)
                ordinary.assert_not_called()
        self.assertEqual(source.read_bytes(), b"new")
        self.assertEqual(destination.read_bytes(), b"keep")

    def test_receipt_manifest_validation_can_be_cancelled(self):
        self.file("x")
        root = Path(self.build()["path"])
        index = recovery.read_json(root / "ARCHIVE.json")

        def cancel_manifest(phase, done, total, path):
            if path.endswith("members.jsonl.gz"):
                raise RuntimeError("cancel manifest hashing")

        with self.assertRaisesRegex(RuntimeError, "cancel manifest hashing"):
            recovery.validate_receipt(
                root, index["packages"][0], cancel_manifest, hash_payload=False
            )


class WindowsIdentityTests(Fixture):
    @contextlib.contextmanager
    def ctime_api_model(self, path, *, platform="win32", mutate=False):
        """Model Windows path birth time vs descriptor change time without sleeps."""
        original = path.stat()
        birthtime = original.st_ctime_ns - 1_000_000_000
        evidence = {"change_time": original.st_ctime_ns, "handles": [], "mutated": False}
        real_fstat = os.fstat
        real_source = inventory.regular_source

        def replacement(observed, ctime):
            fields = {
                name: getattr(observed, name) for name in dir(observed) if name.startswith("st_")
            }
            fields.update(st_ctime_ns=ctime, st_birthtime_ns=birthtime)
            return SimpleNamespace(**fields)

        def path_stat(entry):
            return replacement(os.stat(entry.path, follow_symlinks=False), birthtime)

        def descriptor_stat(descriptor):
            observed = replacement(real_fstat(descriptor), evidence["change_time"])
            evidence["handles"].append(observed)
            return observed

        class MutatingReader:
            def __init__(self, stream):
                self.stream = stream

            def fileno(self):
                return self.stream.fileno()

            def read(self, size):
                data = self.stream.read(size)
                if data and not evidence["mutated"]:
                    # Actual same-size mutation with restored mtime; descriptor
                    # change time is the remaining guard under test.
                    path.write_bytes(b"X" * original.st_size)
                    os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
                    evidence["change_time"] += 1_000_000_000
                    evidence["mutated"] = True
                return data

        @contextlib.contextmanager
        def opened_source(root, relative):
            with real_source(root, relative) as (stream, opened):
                yield MutatingReader(stream) if mutate else stream, opened

        with contextlib.ExitStack() as patches:
            patches.enter_context(
                mock.patch.object(inventory, "sys", SimpleNamespace(platform=platform))
            )
            patches.enter_context(mock.patch.object(inventory, "entry_stat", path_stat))
            patches.enter_context(mock.patch.object(inventory.os, "fstat", descriptor_stat))
            patches.enter_context(mock.patch.object(inventory, "regular_source", opened_source))
            yield evidence

    def test_windows_modified_before_scan_uses_descriptor_ctime_consistently(self):
        path = self.file("data.txt", b"before")
        path.write_bytes(b"prepared")
        with self.ctime_api_model(path) as evidence:
            scanned = self.scan(hash_files=True)
        issues = self.app.call("issues", {"snapshot_id": scanned["snapshot_id"]})
        self.assertEqual(scanned["counts"]["eligible_files"], 1, issues)
        self.assertEqual(scanned["counts"]["errors"], 0, issues)
        self.assertEqual(len(evidence["handles"]), 2)
        before, after = evidence["handles"]
        self.assertNotEqual(before.st_birthtime_ns, before.st_ctime_ns)
        self.assertEqual(before.st_ctime_ns, after.st_ctime_ns)
        with Store(self.workspace) as store:
            row = store.one(
                "SELECT sha256 FROM nodes WHERE snapshot_id=? AND kind='file'",
                (scanned["snapshot_id"],),
            )
        self.assertEqual(row["sha256"], hashlib.sha256(b"prepared").hexdigest())

    def test_windows_descriptor_ctime_mutation_during_hash_is_rejected(self):
        path = self.file("data.txt", b"prepared")
        with self.ctime_api_model(path, mutate=True) as evidence:
            scanned = self.scan(hash_files=True)
        self.assertTrue(evidence["mutated"])
        self.assertEqual(path.read_bytes(), b"XXXXXXXX")
        self.assertEqual(len(evidence["handles"]), 2)
        before, after = evidence["handles"]
        for name in ("st_dev", "st_ino", "st_size", "st_mtime_ns"):
            self.assertEqual(getattr(before, name), getattr(after, name), name)
        self.assertNotEqual(before.st_ctime_ns, after.st_ctime_ns)
        self.assertEqual(scanned["counts"]["eligible_files"], 0)
        self.assertEqual(scanned["counts"]["errors"], 1)
        issues = self.app.call("issues", {"snapshot_id": scanned["snapshot_id"]})
        self.assertEqual(issues[0]["code"], "ENTRY_ERROR")
        self.assertEqual(issues[0]["detail"], "File changed while hashing")

    def test_posix_path_to_descriptor_ctime_change_is_rejected_before_hash(self):
        path = self.file("data.txt", b"prepared")
        with self.ctime_api_model(path, platform="linux") as evidence:
            scanned = self.scan(hash_files=True)
        self.assertEqual(len(evidence["handles"]), 1)
        self.assertEqual(scanned["counts"]["eligible_files"], 0)
        self.assertEqual(scanned["counts"]["errors"], 1)
        issues = self.app.call("issues", {"snapshot_id": scanned["snapshot_id"]})
        self.assertEqual(issues[0]["code"], "ENTRY_ERROR")
        self.assertEqual(issues[0]["detail"], "File changed before hashing")

    def test_scan_uses_full_stat_identity_when_direntry_reports_zeros(self):
        self.file("Tree/child/x", b"one")
        self.file("Tree/y", b"two")
        (self.source / "Tree/empty").mkdir()
        real_scandir = os.scandir
        real_entry_stat = inventory.entry_stat
        real_fstat = os.fstat
        cached_reads = []
        entry_stats = []
        handle_stats = []

        def stat_values(observed):
            return {
                name: getattr(observed, name)
                for name in (
                    "st_dev",
                    "st_ino",
                    "st_nlink",
                    "st_mode",
                    "st_size",
                    "st_mtime_ns",
                    "st_ctime_ns",
                    "st_birthtime_ns",
                    "st_file_attributes",
                )
                if hasattr(observed, name)
            }

        def recorded_entry_stat(entry):
            observed = real_entry_stat(entry)
            entry_stats.append({"path": str(entry.path), **stat_values(observed)})
            return observed

        def recorded_fstat(descriptor):
            observed = real_fstat(descriptor)
            handle_stats.append({"descriptor": descriptor, **stat_values(observed)})
            return observed

        class CachedEntry:
            def __init__(self, entry):
                self.path, self.name, self.entry = entry.path, entry.name, entry

            def stat(self, *, follow_symlinks=True):
                cached_reads.append(self.path)
                observed = self.entry.stat(follow_symlinks=follow_symlinks)
                values = {
                    name: getattr(observed, name)
                    for name in dir(observed)
                    if name.startswith("st_")
                }
                values.update(st_dev=0, st_ino=0, st_nlink=0)
                return SimpleNamespace(**values)

        class CachedScandir:
            def __init__(self, path):
                self.entries = real_scandir(path)

            def __enter__(self):
                return (CachedEntry(entry) for entry in self.entries)

            def __exit__(self, *args):
                self.entries.close()

        with contextlib.ExitStack() as patches:
            patches.enter_context(
                mock.patch.object(inventory, "sys", SimpleNamespace(platform="win32"))
            )
            patches.enter_context(mock.patch.object(inventory.os, "scandir", CachedScandir))
            patches.enter_context(mock.patch.object(inventory, "entry_stat", recorded_entry_stat))
            patches.enter_context(mock.patch.object(inventory.os, "fstat", recorded_fstat))
            scanned = self.scan(hash_files=True)
        diagnostic = json.dumps(
            {
                "python": sys.version,
                "os": os.name,
                "scan": scanned,
                "issues": self.app.call("issues", {"snapshot_id": scanned["snapshot_id"]}),
                "entry_stats": entry_stats,
                "handle_stats": handle_stats,
                "cached_reads": cached_reads,
            },
            sort_keys=True,
        )
        self.assertEqual(scanned["counts"]["eligible_files"], 2, diagnostic)
        self.assertEqual(scanned["counts"]["excluded"], 0, diagnostic)
        self.assertEqual(scanned["counts"]["errors"], 0, diagnostic)
        self.assertEqual(cached_reads, [], diagnostic)
        with Store(self.workspace) as store:
            for row in store.rows(
                "SELECT * FROM nodes WHERE snapshot_id=? AND kind='file'", (scanned["snapshot_id"],)
            ):
                observed = (self.source / store.path(row["id"])).stat()
                self.assertEqual(row["device"], str(observed.st_dev))
                self.assertEqual(row["inode"], str(observed.st_ino))
        self.assertEqual(self.build(self.plan(scanned["snapshot_id"]))["state"], "COMPLETE")


@unittest.skipIf(
    os.name == "nt", "POSIX pathname simulation; native Windows has no /private aliases"
)
class MacSystemAliasTests(unittest.TestCase):
    @contextlib.contextmanager
    def alias_model(self):
        def directory(mode=0o755, uid=0):
            return SimpleNamespace(st_mode=stat.S_IFDIR | mode, st_uid=uid, st_dev=1, st_ino=2)

        def link(uid=0):
            return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_uid=uid, st_dev=1, st_ino=3)

        entries = {"/": directory(), "/private": directory()}
        targets = {}
        for name in ("var", "tmp", "etc"):
            entries["/" + name] = link()
            entries["/private/" + name] = directory(0o1777 if name == "tmp" else 0o755)
            targets["/" + name] = "private/" + name

        def lstat(path):
            return entries.get(str(path), directory(uid=1000))

        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(recovery, "sys", SimpleNamespace(platform="darwin"))
            )
            stack.enter_context(mock.patch.object(Path, "lstat", lstat))
            stack.enter_context(
                mock.patch.object(recovery.os, "readlink", lambda path: targets[str(path)])
            )
            yield entries, targets, directory, link

    def test_only_verified_standard_aliases_normalize_in_both_path_guards(self):
        with self.alias_model():
            for name in ("var", "tmp", "etc"):
                with self.subTest(alias=name):
                    expected = Path("/private") / name / "data"
                    self.assertEqual(util.no_links(Path("/") / name / "data"), expected)
                    self.assertEqual(recovery.no_links(Path("/") / name / "data"), expected)

    def test_untrusted_owner_or_unexpected_target_is_not_followed(self):
        for change in ("owner", "target", "private-link", "writable-private", "nonsticky-tmp"):
            with self.subTest(change=change), self.alias_model() as (
                entries,
                targets,
                directory,
                link,
            ):
                alias = "tmp" if change == "nonsticky-tmp" else "var"
                if change == "owner":
                    entries["/var"] = link(uid=1000)
                elif change == "target":
                    targets["/var"] = "/Users/attacker"
                elif change == "private-link":
                    entries["/private"] = link()
                elif change == "writable-private":
                    entries["/private"] = directory(0o777)
                else:
                    entries["/private/tmp"] = directory(0o777)
                with self.assertRaises(util.Problem):
                    util.no_links(Path("/") / alias / "data")
                with self.assertRaises(recovery.RecoveryError):
                    recovery.no_links(Path("/") / alias / "data")

    def test_descendant_user_link_stays_forbidden_after_alias_expansion(self):
        with self.alias_model() as (entries, _, _, link):
            entries["/private/var/data/link"] = link(uid=1000)
            with self.assertRaises(util.Problem) as caught:
                util.no_links(Path("/var/data/link/file"))
            self.assertEqual(caught.exception.code, "LINK_PATH")
            with self.assertRaises(recovery.RecoveryError):
                recovery.no_links(Path("/var/data/link/file"))
