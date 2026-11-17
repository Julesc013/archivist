"""Behavioural acceptance tests. All writes are confined to temporary fixtures."""

import csv
import gzip
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from archivist.application import Application
from archivist import __version__, artifacts, inventory, planning, recovery
from archivist.progress import Progress
from archivist.store import Store
from archivist.util import Problem, bytes_value, hash_file, json_read, locked


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ap20-test-")
        self.base = Path(self.tmp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        self.workspace = self.base / "workspace"
        self.app = Application(self.workspace)

    def tearDown(self):
        self.tmp.cleanup()

    def file(self, name, data=b"hello"):
        p = self.source / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def scan(self, **kw):
        return self.app.call("scan", {"root": str(self.source), "backend": "filesystem", **kw})

    def plan(self, sid=None, **policy):
        sid = sid or self.scan()["snapshot_id"]
        opts = {"minimum": 0, "target": 2_000_000, "maximum": 4_000_000, "codec": "none"}
        opts.update(policy)
        return self.app.call("plan", {"snapshots": [sid], "policy": opts})

    def build(self, plan=None, **kw):
        plan = plan or self.plan()
        args = {"plan_id": plan["id"], "output": str(self.base / "build"), **kw}
        review = self.app.call("preflight_build", args)
        return self.app.call("build", {**args, "approval": review["approval"]})

    def assert_problem(self, code, action, args):
        with self.assertRaises(Problem) as cm:
            self.app.call(action, args)
        self.assertEqual(cm.exception.code, code)
        return cm.exception

    def efu(self, rows, headers=None):
        path = self.base / "input.efu"
        with path.open("w", newline="", encoding="utf-8-sig") as out:
            w = csv.writer(out)
            w.writerow(headers or ["Filename", "Size", "Date Modified", "Attributes"])
            w.writerows(rows)
        return path

    def import_rows(self, rows, headers=None):
        return self.app.call(
            "import_efu",
            {"input": str(self.efu(rows, headers)), "root": "D:\\", "label": "test disk"},
        )


class InventoryTests(Fixture):
    def test_direct_recursive_zero_and_empty(self):
        self.file("root.txt", b"123")
        self.file("A/x", b"12345")
        self.file("A/B/zero", b"")
        (self.source / "Empty").mkdir()
        scan = self.scan()
        self.assertEqual(scan["counts"]["eligible_bytes"], 8)
        self.assertEqual(scan["counts"]["eligible_files"], 3)
        self.assertEqual(scan["counts"]["directories"], 4)
        tree = self.app.call("browse", {"snapshot_id": scan["snapshot_id"]})
        self.assertEqual(tree["directory"]["total_bytes"], 8)
        a = next(r for r in tree["rows"] if r["name"] == "A")
        self.assertEqual(a["total_bytes"], 5)
        self.assertEqual(a["total_files"], 2)
        self.assertEqual(self.app.call("types", {"snapshot_id": scan["snapshot_id"]})["total"], 2)

    def test_scan_hashes_unicode(self):
        self.file("Données/日本語.txt", "hello café".encode())
        s = self.scan(hash_files=True)
        with Store(self.workspace) as db:
            row = db.one("SELECT sha256 FROM nodes WHERE kind='file'")
        self.assertEqual(row["sha256"], hashlib.sha256("hello café".encode()).hexdigest())
        self.assertEqual(s["state"], "COMPLETE")

    @unittest.skipIf(os.name == "nt", "POSIX fixture; native Windows is a separate qualification")
    def test_links_and_special_files_not_followed(self):
        self.file("inside", b"yes")
        (self.source / "link").symlink_to(self.source / "inside")
        os.mkfifo(self.source / "fifo")
        s = self.scan()
        self.assertEqual(s["counts"]["eligible_files"], 1)
        self.assertEqual(s["counts"]["excluded"], 2)
        p = self.plan(s["snapshot_id"])
        self.assert_problem(
            "EXCLUSIONS", "preflight_build", {"plan_id": p["id"], "output": str(self.base / "out")}
        )
        self.build(p, accept_exclusions=True)

    @unittest.skipIf(os.name == "nt", "Case-sensitive filesystem fixture")
    def test_case_collision_blocks_execution(self):
        self.file("a/File.txt")
        self.file("a/file.txt")
        s = self.scan()
        self.assertGreater(s["counts"]["errors"], 0)
        p = self.plan(s["snapshot_id"])
        self.assert_problem(
            "SOURCE_ERRORS",
            "preflight_build",
            {"plan_id": p["id"], "output": str(self.base / "out")},
        )

    @unittest.skipIf(os.name == "nt", "Reserved-name fixture is POSIX-only")
    def test_nonportable_name_reported(self):
        self.file("AUX.txt")
        s = self.scan()
        self.assertEqual(s["counts"]["errors"], 1)
        self.assertEqual(s["counts"]["files"], 1)

    def test_workspace_cannot_be_source(self):
        self.assert_problem(
            "SOURCE_WORKSPACE", "scan", {"root": str(self.workspace), "backend": "filesystem"}
        )

    def test_efu_accounting_and_inferred_directories(self):
        ftime = "133000000000000000"
        s = self.import_rows(
            [
                ["D:\\A\\x.txt", "12", ftime, "32"],
                ["E:\\outside", "99", ftime, "32"],
                ["D:\\Empty", "", ftime, "16"],
            ]
        )
        self.assertEqual(s["counts"]["eligible_bytes"], 12)
        self.assertEqual(s["counts"]["outside_root_rows"], 1)
        self.assertEqual(s["counts"]["input_rows"], 3)
        self.assertEqual(s["backend"], "efu")
        self.assertEqual(s["counts"]["directories"], 3)

    def test_efu_invalid_attributes_not_silently_included(self):
        s = self.import_rows([["D:\\x", "12", "133000000000000000", "banana"]])
        self.assertEqual(s["counts"]["invalid_rows"], 1)
        self.assertEqual(s["counts"]["eligible_files"], 0)
        self.assertGreater(s["counts"]["errors"], 0)

    def test_efu_formatted_size_is_error(self):
        s = self.import_rows([["D:\\x", "12 GB", "133000000000000000", "32"]])
        self.assertEqual(s["counts"]["errors"], 1)

    def test_efu_missing_timestamp_blocks_build(self):
        s = self.import_rows([["D:\\x", "12", "", "32"]])
        self.assertGreater(s["counts"]["errors"], 0)

    def test_efu_duplicate_column_fails_and_keeps_failure(self):
        self.assert_problem(
            "EFU_HEADER",
            "import_efu",
            {
                "input": str(self.efu([], ["Filename", "Size", "Size", "Attributes"])),
                "root": "D:\\",
            },
        )
        self.assertEqual(self.app.call("scans")[0]["state"], "FAILED")

    def test_efu_reparse_descendants_excluded(self):
        t = "133000000000000000"
        s = self.import_rows([["D:\\L\\child", "5", t, "32"], ["D:\\L", "", t, "1040"]])
        self.assertEqual(s["counts"]["eligible_bytes"], 0)
        self.assertEqual(s["counts"]["eligible_files"], 0)
        self.assertGreaterEqual(s["counts"]["excluded"], 2)

    def test_efu_duplicate_path_is_audited(self):
        t = "133000000000000000"
        s = self.import_rows([["D:\\x", "5", t, "32"], ["D:\\x", "5", t, "32"]])
        self.assertEqual(s["counts"]["files"], 1)
        self.assertGreater(s["counts"]["errors"], 0)

    def test_everything_arguments_are_literal_not_shell(self):
        a = inventory.es_arguments("C:/Tools/es.exe", "D:/a & b", "C:/x y/out.efu", "1.5a")
        self.assertIn("-path", a)
        self.assertIn("D:/a & b", a)
        self.assertIn("-export-efu", a)
        self.assertIn("1.5a", a)

    @unittest.skipIf(os.name == "nt", "Failure branch asserted on non-Windows")
    def test_required_everything_never_falls_back(self):
        self.assert_problem(
            "EVERYTHING_PLATFORM", "scan", {"root": str(self.source), "backend": "everything"}
        )
        self.assertEqual(self.app.call("scans"), [])

    def test_indexed_hash_request_not_silently_ignored(self):
        self.assert_problem(
            "INDEX_HASH_MODE",
            "scan",
            {"root": str(self.source), "backend": "everything", "hash_files": True},
        )


class PlanningTests(Fixture):
    def test_whole_mixed_directory_kept_together(self):
        self.file("Project/a.jpg", b"x" * 20000)
        self.file("Project/readme.txt", b"t" * 1000)
        p = self.plan()
        packages = self.app.call("packages", {"plan_id": p["id"]})["packages"]
        data = [r for r in packages if r["kind"] == "data"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["file_count"], 2)
        self.assertEqual(data[0]["reason"], "WHOLE_DIRECTORY")

    def test_outer_depth_does_not_change_membership(self):
        self.file("A/B/C/D/E/x.txt", b"x" * 80000)
        s = self.scan()["snapshot_id"]
        a = self.plan(s, outer_depth=1)
        b = self.plan(s, outer_depth=5)

        def member_sets(plan):
            with Store(self.workspace) as db:
                return [
                    tuple(
                        r["node_id"]
                        for r in db.rows(
                            "SELECT node_id FROM members WHERE plan_id=? AND package_id=? ORDER BY node_id",
                            (plan["id"], p["id"]),
                        )
                    )
                    for p in db.rows(
                        "SELECT * FROM packages WHERE plan_id=? ORDER BY id", (plan["id"],)
                    )
                ]

        self.assertEqual(member_sets(a), member_sets(b))

    def test_loose_files_split_locally_not_between_projects(self):
        for name in ["A/x.txt", "A/a.bin", "B/x.txt", "B/a.bin"]:
            self.file(name, b"x" * 12000)
        p = self.plan(target=20000, maximum=35000, keep_whole=20000)
        with Store(self.workspace) as db:
            for package in db.rows(
                "SELECT * FROM packages WHERE plan_id=? AND kind='data'", (p["id"],)
            ):
                parents = {
                    db.path(r["node_id"]).split("/")[0]
                    for r in db.rows(
                        "SELECT node_id FROM members WHERE plan_id=? AND package_id=?",
                        (p["id"], package["id"]),
                    )
                }
                self.assertEqual(len(parents), 1)

    def test_oversized_file_is_blocked_not_fragmented(self):
        self.file("large.iso", b"a" * 50000)
        p = self.plan(target=16000, maximum=16384)
        self.assertEqual(p["counts"]["files"], 1)
        self.assertEqual(p["counts"]["blocked_packages"], 1)
        self.assert_problem(
            "PACKAGE_LIMIT",
            "preflight_build",
            {"plan_id": p["id"], "output": str(self.base / "out")},
        )

    def test_zero_files_do_not_bypass_budget(self):
        for i in range(80):
            self.file(f"z{i:03}", b"")
        p = self.plan(target=20000, maximum=30000)
        self.assertEqual(p["counts"]["blocked_packages"], 0)
        self.assertGreater(p["counts"]["packages"], 2)

    def test_codec_edit_is_immutable(self):
        self.file("A/text.txt", b"x" * 1000)
        p = self.plan()
        data = next(
            r
            for r in self.app.call("packages", {"plan_id": p["id"]})["packages"]
            if r["kind"] == "data"
        )
        q = self.app.call(
            "revise",
            {"plan_id": p["id"], "codec_changes": {data["id"]: {"codec": "gzip", "level": 6}}},
        )
        old = self.app.call("packages", {"plan_id": p["id"]})
        self.assertEqual(old["plan"]["fingerprint"], p["fingerprint"])
        self.assertEqual(next(r for r in old["packages"] if r["id"] == data["id"])["codec"], "none")
        self.assertNotEqual(q["fingerprint"], p["fingerprint"])

    def test_manual_move_exact_once(self):
        self.file("A/a.txt", b"x")
        self.file("A/b.txt", b"y")
        p = self.plan()
        package = next(
            r
            for r in self.app.call("packages", {"plan_id": p["id"]})["packages"]
            if r["kind"] == "data"
        )
        member = self.app.call("members", {"plan_id": p["id"], "package_id": package["id"]})[
            "rows"
        ][0]
        q = self.app.call("revise", {"plan_id": p["id"], "move": {"node_ids": [member["id"]]}})
        self.assertEqual(q["counts"]["files"], 2)
        self.assertTrue(q["counts"]["exact_once"])
        self.assertEqual(q["counts"]["packages"], p["counts"]["packages"] + 1)

    def test_duplicate_merge_ids_rejected(self):
        self.file("a", b"x")
        p = self.plan()
        self.assert_problem(
            "MERGE", "revise", {"plan_id": p["id"], "merge": ["P000001", "P000001"]}
        )

    def test_sources_have_separate_restore_namespaces(self):
        self.file("same.txt", b"a")
        a = self.scan()["snapshot_id"]
        other = self.base / "other"
        other.mkdir()
        (other / "same.txt").write_bytes(b"b")
        b = self.app.call("scan", {"root": str(other), "backend": "filesystem"})["snapshot_id"]
        p = self.app.call(
            "plan",
            {
                "snapshots": [a, b],
                "policy": {"minimum": 0, "target": 100000, "maximum": 200000, "codec": "none"},
            },
        )
        sources = self.app.call("packages", {"plan_id": p["id"]})["sources"]
        self.assertEqual(len({s["namespace"] for s in sources}), 2)
        self.assertEqual(p["counts"]["files"], 2)

    def test_allocation_conservation_and_file_limit(self):
        out = planning.allocate(
            [
                {"id": "a", "estimated_bytes": 70},
                {"id": "b", "estimated_bytes": 40},
                {"id": "c", "estimated_bytes": 20},
            ],
            [
                {"id": "one", "capacity": 100, "reserve": 10, "max_file": 60},
                {"id": "two", "capacity": 50},
            ],
        )
        self.assertEqual(out["unallocated"], ["a"])
        self.assertEqual(sum(b["used"] for b in out["media"]), 60)
        self.assertFalse(out["globally_optimal"])

    def test_randomized_coverage_and_cohesion(self):
        rng = random.Random(431)
        for i in range(100):
            self.file(
                f"D{i % 9}/Sub{i % 3}/f{i}.{['txt', 'bin', 'jpg'][i % 3]}",
                bytes(rng.randrange(0, 256) for _ in range(rng.randrange(0, 1200))),
            )
        s = self.scan()["snapshot_id"]
        for maxsize in (20000, 40000, 150000):
            with self.subTest(maximum=maxsize):
                p = self.plan(s, target=maxsize // 2, maximum=maxsize)
                self.assertTrue(p["counts"]["exact_once"])
                self.assertEqual(p["counts"]["files"], 100)
                with Store(self.workspace) as db:
                    ids = [
                        r[0]
                        for r in db.db.execute(
                            "SELECT node_id FROM members WHERE plan_id=?", (p["id"],)
                        )
                    ]
                    self.assertEqual(len(ids), len(set(ids)))


class ArchiveTests(Fixture):
    def roundtrip(self, codec):
        self.file("Project/readme ü.txt", "hello\n".encode() * 2000)
        self.file("Project/image.bin", bytes(range(256)) * 100)
        self.file("zero", b"")
        (self.source / "Empty").mkdir()
        s = self.scan(hash_files=True)
        p = self.plan(s["snapshot_id"], codec=codec)
        built = self.build(p)
        bundle = Path(built["path"])
        ns = json_read(bundle / "ARCHIVE.json")["sources"][0]["namespace"]
        wanted = {
            f.relative_to(self.source).as_posix(): f.read_bytes()
            for f in self.source.rglob("*")
            if f.is_file()
        }
        copied = self.base / "independent"
        shutil.copytree(bundle, copied)
        shutil.rmtree(self.source)
        shutil.rmtree(bundle)
        shutil.rmtree(self.workspace)
        out = self.base / "restored"
        proc = subprocess.run(
            [sys.executable, "-I", str(copied / "RESTORE.py"), str(copied), "--to", str(out)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        actual = {
            f.relative_to(out / ns).as_posix(): f.read_bytes()
            for f in (out / ns).rglob("*")
            if f.is_file()
        }
        self.assertEqual(actual, wanted)
        self.assertTrue((out / ns / "Empty").is_dir())

    def test_independent_plain_tar_recovery(self):
        self.roundtrip("none")

    def test_independent_gzip_recovery(self):
        self.roundtrip("gzip")

    @unittest.skipUnless(shutil.which("zstd"), "External zstd not installed")
    def test_independent_zstd_recovery(self):
        self.roundtrip("zstd")

    @unittest.skipUnless(shutil.which("tar"), "Independent tar unavailable")
    def test_plain_archive_readable_by_system_tar(self):
        self.file("deep/alpha.txt", b"hello world")
        b = self.build()
        bundle = Path(b["path"])
        index = json_read(bundle / "ARCHIVE.json")
        out = self.base / "system-restore"
        out.mkdir()
        for ref in index["packages"]:
            receipt = json_read(bundle / ref["receipt"])
            r = subprocess.run(
                ["tar", "-xf", str(bundle / receipt["artifact"]), "-C", str(out)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(next(out.rglob("alpha.txt")).read_bytes(), b"hello world")

    def test_source_change_before_build_is_rejected(self):
        f = self.file("x", b"a")
        p = self.plan()
        f.write_bytes(b"bb")
        review = self.app.call(
            "preflight_build", {"plan_id": p["id"], "output": str(self.base / "build")}
        )
        self.assert_problem(
            "SOURCE_SIZE_CHANGED",
            "build",
            {
                "plan_id": p["id"],
                "output": str(self.base / "build"),
                "approval": review["approval"],
            },
        )
        self.assertEqual(json_read(self.base / "build" / "BUILD.json")["state"], "INTERRUPTED")
        self.assertTrue(list((self.base / "build").rglob("*.partial-*")))

    def test_scanned_hash_detects_equal_size_restored_mtime(self):
        f = self.file("x", b"abcd")
        s = self.scan(hash_files=True)
        p = self.plan(s["snapshot_id"])
        st = f.stat()
        f.write_bytes(b"wxyz")
        os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
        with self.assertRaises(Problem) as cm:
            self.build(p)
        self.assertEqual(cm.exception.code, "SOURCE_HASH_CHANGED")

    def test_stale_approval_does_not_write(self):
        self.file("x")
        p = self.plan()
        self.assert_problem(
            "APPROVAL",
            "build",
            {"plan_id": p["id"], "output": str(self.base / "build"), "approval": "wrong"},
        )
        self.assertFalse((self.base / "build").exists())

    def test_output_inside_source_refused(self):
        self.file("x")
        p = self.plan()
        self.assert_problem(
            "OUTPUT_OVERLAP",
            "preflight_build",
            {"plan_id": p["id"], "output": str(self.source / "out")},
        )

    def test_existing_unowned_output_refused(self):
        self.file("x")
        p = self.plan()
        (self.base / "build").mkdir()
        self.assert_problem(
            "OUTPUT_EXISTS",
            "preflight_build",
            {"plan_id": p["id"], "output": str(self.base / "build")},
        )

    def test_completed_package_retry_reuses_bytes(self):
        self.file("A/a", b"hello")
        p = self.plan()
        b = self.build(p)
        hashes = {
            f.relative_to(Path(b["path"])).as_posix(): hash_file(f)
            for f in Path(b["path"]).rglob("*")
            if f.is_file() and "packages/" in f.as_posix()
        }
        again = self.build(p)
        self.assertEqual(again["build_id"], b["build_id"])
        self.assertEqual(
            hashes,
            {
                f.relative_to(Path(b["path"])).as_posix(): hash_file(f)
                for f in Path(b["path"]).rglob("*")
                if f.is_file() and "packages/" in f.as_posix()
            },
        )

    def test_cancel_before_work_preserves_source(self):
        self.file("x")
        p = Progress()
        p.cancelled.set()
        with self.assertRaises(Problem):
            self.app.call("scan", {"root": str(self.source), "backend": "filesystem"}, p)
        self.assertEqual((self.source / "x").read_bytes(), b"hello")
        self.assertEqual(self.app.call("history")[0]["state"], "FAILED")

    def test_actual_output_limit_enforced(self):
        self.file("x", os.urandom(10000))
        p = self.plan()
        # Force a tighter final-size gate without changing planning state: exercise the writer boundary directly.
        with Store(self.workspace) as s:
            package = s.one("SELECT * FROM packages WHERE plan_id=? AND kind='data'", (p["id"],))
            src = s.one(
                "SELECT s.*,ps.namespace FROM plan_sources ps JOIN snapshots sn ON sn.id=ps.snapshot_id JOIN sources s ON s.id=sn.source_id WHERE ps.plan_id=?",
                (p["id"],),
            )
            folder = self.base / "tiny" / "package"
            folder.parent.mkdir()
            with self.assertRaises(Problem) as cm:
                artifacts.build_package(
                    s,
                    p["id"],
                    package,
                    self.source,
                    src["namespace"],
                    folder,
                    "package",
                    100,
                    Progress(),
                )
            self.assertEqual(cm.exception.code, "ACTUAL_SIZE_LIMIT")
            self.assertFalse(folder.exists())

    def test_tampered_archive_rejected(self):
        self.file("x")
        b = self.build()
        root = Path(b["path"])
        ref = json_read(root / "ARCHIVE.json")["packages"][0]
        receipt = json_read(root / ref["receipt"])
        f = root / receipt["artifact"]
        data = bytearray(f.read_bytes())
        data[100] ^= 1
        f.write_bytes(data)
        with self.assertRaises(recovery.RecoveryError):
            recovery.run(root)

    def test_existing_restore_target_refused(self):
        self.file("x")
        b = self.build()
        out = self.base / "existing"
        out.mkdir()
        (out / "precious").write_text("keep")
        with self.assertRaises(recovery.RecoveryError):
            recovery.run(b["path"], out)
        self.assertEqual((out / "precious").read_text(), "keep")

    def test_subset_is_labelled_partial(self):
        self.file("A/x", b"a" * 30000)
        self.file("B/y", b"b" * 30000)
        p = self.plan(target=40000, maximum=100000, merge_below=1)
        pid = next(
            r["id"]
            for r in self.app.call("packages", {"plan_id": p["id"]})["packages"]
            if r["kind"] == "data"
        )
        b = self.build(p, packages=[pid])
        index = json_read(Path(b["path"]) / "ARCHIVE.json")
        self.assertEqual(index["scope"], "PARTIAL_PLAN")
        self.assertEqual(len(index["packages"]), 2)


class DestinationEvidenceTests(Fixture):
    def test_disk_copy_readback_and_retry(self):
        self.file("x", b"a" * 1000)
        b = self.build()
        d = self.app.call("destination", {"path": str(self.base / "disk"), "label": "copy"})
        args = {"bundle": b["path"], "destination": d["id"]}
        review = self.app.call("preflight_copy", args)
        result = self.app.call("copy", {**args, "approval": review["approval"]})
        self.assertEqual(result["state"], "COPY_READBACK")
        again = self.app.call("copy", {**args, "approval": review["approval"]})
        self.assertTrue(again["reused"])
        self.assertEqual(recovery.run(result["path"])["logical_bytes"], 1000)

    def test_changed_destination_marker_refused(self):
        self.file("x")
        b = self.build()
        root = self.base / "disk"
        d = self.app.call("destination", {"path": str(root), "label": "disk"})
        (root / ".ap20-destination.json").write_text("{}")
        self.assert_problem(
            "DEST_CHANGED", "preflight_copy", {"bundle": b["path"], "destination": d["id"]}
        )

    def test_max_destination_file_limit(self):
        self.file("x", b"a" * 1000)
        b = self.build()
        d = self.app.call(
            "destination", {"path": str(self.base / "disk"), "label": "tiny", "max_file": 100}
        )
        self.assert_problem(
            "DEST_FILE_LIMIT", "preflight_copy", {"bundle": b["path"], "destination": d["id"]}
        )

    def test_destination_overlap_refused(self):
        self.assert_problem(
            "DEST_SOURCE", "destination", {"path": str(self.source / "disk"), "label": "bad"}
        ) if self.scan() else None
        self.assertFalse((self.source / "disk").exists())

    def test_ordinary_directory_not_treated_as_ltfs(self):
        d = self.base / "nottape"
        d.mkdir()
        with self.assertRaises(Problem):
            self.app.call(
                "destination",
                {"path": str(d), "label": "fake", "kind": "ltfs", "experimental": True},
            )
        self.assertFalse((d / ".ap20-destination.json").exists())

    def test_portable_bundle_preserves_plan_and_requires_rebinding(self):
        self.file("x")
        p = self.plan()
        self.app.call("destination", {"path": str(self.base / "disk"), "label": "disk"})
        bundle = self.base / "scan.ap20"
        self.app.call("export", {"output": str(bundle)})
        dest = self.base / "imported"
        self.app.call("import", {"input": str(bundle), "output": str(dest)})
        other = Application(dest)
        self.assertEqual(other.call("plans")[0]["fingerprint"], p["fingerprint"])
        self.assertEqual(other.call("destinations")[0]["enabled"], 0)
        self.assert_problem("EXPORT_EXISTS", "export", {"output": str(bundle)})
        with self.assertRaises(Problem) as cm:
            other.call(
                "preflight_build", {"plan_id": p["id"], "output": str(self.base / "newbuild")}
            )
        self.assertEqual(cm.exception.code, "SOURCE_UNBOUND")
        src = other.call("sources")[0]
        other.call("bind", {"source_id": src["id"], "root": str(self.source)})
        self.assertIn(
            "approval",
            other.call(
                "preflight_build", {"plan_id": p["id"], "output": str(self.base / "newbuild")}
            ),
        )

    def test_export_inventory_is_complete_gzip_jsonl(self):
        self.file("x")
        s = self.scan()
        path = self.base / "list.jsonl.gz"
        r = self.app.call(
            "export_inventory", {"snapshot_id": s["snapshot_id"], "output": str(path)}
        )
        with gzip.open(path, "rt") as stream:
            rows = [json.loads(x) for x in stream]
        self.assertEqual(rows[0]["format"], "AP20InventoryJSONL/1")
        self.assertEqual(len([r for r in rows if r.get("record") == "node"]), 2)
        self.assertEqual(r["sha256"], hash_file(path))

    def test_bundle_extra_member_and_traversal_rejected(self):
        z = self.base / "bad.ap20"
        with zipfile.ZipFile(z, "w") as out:
            out.writestr("../escape", "evil")
            out.writestr("FORMAT.json", "{}")
        self.assert_problem(
            "BUNDLE_MEMBERS", "import", {"input": str(z), "output": str(self.base / "badout")}
        )
        self.assertFalse((self.base / "escape").exists())
        self.assertFalse((self.base / "badout").exists())

    def test_bundle_corruption_rejected(self):
        self.file("x")
        self.plan()
        good = self.base / "good.ap20"
        self.app.call("export", {"output": str(good)})
        bad = self.base / "bad.ap20"
        with zipfile.ZipFile(good) as inp, zipfile.ZipFile(bad, "w") as out:
            for name in inp.namelist():
                b = inp.read(name)
                if name == "workspace.sqlite":
                    b = bytes([b[0] ^ 1]) + b[1:]
                out.writestr(name, b)
        self.assert_problem(
            "BUNDLE_HASH", "import", {"input": str(bad), "output": str(self.base / "new")}
        )

    def test_workspace_lock_blocks_parallel_writer(self):
        with locked(self.workspace / ".writer.lock"):
            self.assert_problem("BUSY", "set_preferences", {"appearance": "dark"})

    def test_compact_database_no_automatic_expanded_exports(self):
        for i in range(200):
            self.file(f"A/f{i}.txt", b"a")
        self.plan()
        names = {p.name for p in self.workspace.iterdir()}
        self.assertIn("workspace.sqlite", names)
        self.assertFalse(any(n.endswith((".jsonl", ".json", ".html", ".txt")) for n in names))


class SmallContracts(unittest.TestCase):
    def test_size_units(self):
        self.assertEqual(bytes_value("100GB"), 100_000_000_000)
        self.assertEqual(bytes_value("1.5GiB"), 1610612736)
        with self.assertRaises(Problem):
            bytes_value("-1GB")

    def test_unknown_progress_has_no_eta(self):
        p = Progress()
        p.phase("Scan")
        p.update(10)
        self.assertIsNone(p.state()["total"])
        self.assertIsNone(p.state()["eta_seconds"])

    def test_recovery_traversal_rejected(self):
        for value in ("../x", "/root", "C:/x", "x/../y", "x\\y", "x//y"):
            with self.subTest(path=value), self.assertRaises(recovery.RecoveryError):
                recovery.parts(value)

    def test_json_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "x.json"
            p.write_text('{"x":1,"x":2}')
            with self.assertRaises(Problem):
                json_read(p)

    def test_cli_json_is_machine_readable(self):
        with tempfile.TemporaryDirectory() as t:
            p = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "archivist.py"),
                    "doctor",
                    "--json",
                    "--quiet",
                    "--workspace",
                    t,
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(p.stdout)["version"], __version__)

    def test_cli_help_no_application_side_effect(self):
        p = subprocess.run(
            [sys.executable, str(ROOT / "archivist.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(p.returncode, 0)
        self.assertIn("scan", p.stdout)


if __name__ == "__main__":
    unittest.main()
