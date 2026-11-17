"""Regression evidence for V2 kit integrity, TAR interpretation and copy commits.

Crafted fixtures are correctly sealed before the intended inconsistency is
tested, so an unrelated missing checksum cannot make a safety test pass.
"""

import gzip
import hashlib
import io
import os
import shutil
import tarfile
import unittest
from pathlib import Path
from unittest import mock

from test_core import Fixture
from archivist import destinations, recovery
from archivist.store import Store
from archivist.util import Problem, atomic_json, canonical, hash_file, json_read


class RecoveryV2Tests(Fixture):
    def reseal(self, root):
        index = json_read(root / "ARCHIVE.json")
        for ref in index["packages"]:
            ref["receipt_sha256"] = hash_file(root / ref["receipt"])
        atomic_json(root / "ARCHIVE.json", index)
        names = ["ARCHIVE.json", "README.txt", "RESTORE.py"]
        if index.get("human_manifest") == "ARCHIVE.html":
            names.append("ARCHIVE.html")
        names.extend(ref["receipt"] for ref in index["packages"])
        (root / "SHA256SUMS").write_text(
            "".join(hash_file(root / name) + "  " + name + "\n" for name in names),
            encoding="utf-8",
            newline="\n",
        )

    def tar_bytes(self, name="safe.txt", data=b"x", mode=0o600, mtime=0):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as stream:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = mode
            info.mtime = mtime
            stream.addfile(info, io.BytesIO(data))
        return buffer.getvalue()

    def bundle(self, name="fixture", payload=None, mode=0o600, mtime_ns=0):
        root = self.base / name
        root.mkdir()
        if payload is None:
            payload = self.tar_bytes()
        (root / "payload.tar").write_bytes(payload)
        row = {
            "name": "safe.txt",
            "kind": "file",
            "size": 1,
            "mtime_ns": mtime_ns,
            "mode": mode,
            "sha256": hashlib.sha256(b"x").hexdigest(),
        }
        with gzip.open(root / "members.jsonl.gz", "wb") as stream:
            stream.write(canonical(row) + b"\n")
        receipt = {
            "format": "AP20Package/1",
            "package_id": "P000001",
            "codec": "none",
            "artifact": "payload.tar",
            "artifact_bytes": len(payload),
            "artifact_sha256": hash_file(root / "payload.tar"),
            "manifest": "members.jsonl.gz",
            "manifest_bytes": (root / "members.jsonl.gz").stat().st_size,
            "manifest_sha256": hash_file(root / "members.jsonl.gz"),
            "tar_bytes": len(payload),
            "logical_bytes": 1,
            "member_count": 1,
        }
        atomic_json(root / "receipt.json", receipt)
        index = {
            "format": "AP20Archive/1",
            "planned_packages": 1,
            "scope": "COMPLETE_PLAN",
            "packages": [
                {
                    "package_id": "P000001",
                    "receipt": "receipt.json",
                    "receipt_sha256": hash_file(root / "receipt.json"),
                }
            ],
        }
        atomic_json(root / "ARCHIVE.json", index)
        (root / "README.txt").write_text("Synthetic v1 archive set. Scope: COMPLETE_PLAN.\n")
        (root / "RESTORE.py").write_bytes(Path(recovery.__file__).read_bytes())
        self.reseal(root)
        return root

    def copy_args(self, bundle, max_file=None):
        args = {"path": str(self.base / "disk"), "label": "Test disk"}
        if max_file is not None:
            args["max_file"] = max_file
        dest = self.app.call("destination", args)
        return {"bundle": str(bundle), "destination": dest["id"]}

    def test_legacy_v1_without_html_still_restores_independently(self):
        root = self.bundle()
        result = recovery.run(root, self.base / "restored")
        self.assertEqual(result["state"], "RESTORED_VERIFIED")
        self.assertEqual((self.base / "restored" / "safe.txt").read_bytes(), b"x")
        self.assertEqual(result["recovery_kit"], "KIT_VERIFIED")

    def test_modified_recovery_helper_rejected_before_copy_or_resume(self):
        self.file("x")
        plan = self.plan()
        built = self.build(plan)
        root = Path(built["path"])
        args = self.copy_args(root)
        old_seals = (root / "SHA256SUMS").read_bytes()
        (root / "RESTORE.py").write_text("# corrupted recovery helper\n")
        for operation in (
            lambda: self.app.call("verify", {"bundle": str(root)}),
            lambda: self.app.call("preflight_copy", args),
            lambda: self.build(plan),
        ):
            with self.assertRaisesRegex(recovery.RecoveryError, "checksum mismatch: RESTORE.py"):
                operation()
        self.assertEqual((root / "SHA256SUMS").read_bytes(), old_seals)
        self.assertFalse((self.base / "disk" / "AP20-archives").exists())

    def test_documentation_and_declared_html_are_sealed(self):
        self.file("x")
        root = Path(self.build()["path"])
        for name in ("README.txt", "ARCHIVE.html"):
            original = (root / name).read_bytes()
            with self.subTest(name=name):
                (root / name).write_bytes(original + b" changed")
                with self.assertRaisesRegex(
                    recovery.RecoveryError, "Recovery-kit checksum mismatch"
                ):
                    recovery.run(root)
                (root / name).write_bytes(original)
        recovery.run(root)

    def test_missing_and_duplicate_kit_seals_refused(self):
        root = self.bundle()
        original = (root / "SHA256SUMS").read_text()
        variants = (
            original.splitlines(keepends=True)[0] + original,
            "".join(
                line
                for line in original.splitlines(keepends=True)
                if not line.endswith("  RESTORE.py\n")
            ),
        )
        for variant in variants:
            with self.subTest(seal=variant):
                (root / "SHA256SUMS").write_text(variant)
                with self.assertRaises(recovery.RecoveryError):
                    recovery.run(root)

    def test_selected_verification_reports_partial_selection(self):
        self.file("x")
        root = Path(self.build()["path"])
        index = json_read(root / "ARCHIVE.json")
        selected = index["packages"][0]["package_id"]
        self.assertGreater(len(index["packages"]), 1)
        result = recovery.run(root, packages=[selected])
        self.assertEqual(result["scope"], "PARTIAL_PLAN")
        self.assertEqual(result["archive_set_scope"], "COMPLETE_PLAN")
        self.assertEqual(result["verification_selection_scope"], "SELECTED_PACKAGES")
        self.assertEqual(result["selected_package_ids"], [selected])
        self.assertEqual(result["available_packages"], len(index["packages"]))
        self.assertEqual(
            recovery.run(root)["verification_selection_scope"], "ALL_AVAILABLE_PACKAGES"
        )

    def test_mismatching_receipt_identity_refused_even_when_resealed(self):
        root = self.bundle()
        index = json_read(root / "ARCHIVE.json")
        index["packages"][0]["package_id"] = "P999999"
        atomic_json(root / "ARCHIVE.json", index)
        self.reseal(root)
        with self.assertRaisesRegex(recovery.RecoveryError, "package IDs differ"):
            recovery.run(root)

    def test_complete_scope_cannot_hide_missing_planned_packages(self):
        root = self.bundle()
        index = json_read(root / "ARCHIVE.json")
        index["planned_packages"] = 999
        atomic_json(root / "ARCHIVE.json", index)
        self.reseal(root)
        with self.assertRaisesRegex(recovery.RecoveryError, "scope differs from package counts"):
            recovery.run(root)

    def test_package_cannot_alias_replica_control_metadata(self):
        root = self.bundle()
        shutil.copyfile(root / "payload.tar", root / "REPLICA.json")
        receipt = json_read(root / "receipt.json")
        receipt["artifact"] = "REPLICA.json"
        atomic_json(root / "receipt.json", receipt)
        self.reseal(root)
        with self.assertRaisesRegex(recovery.RecoveryError, "reserved control path"):
            recovery.run(root)

    def test_concatenated_tar_rejected_inside_and_beyond_parser_buffer(self):
        for padding in (0, 2 * recovery.CHUNK):
            with self.subTest(padding=padding):
                payload = (
                    self.tar_bytes() + b"\0" * padding + self.tar_bytes("hidden.txt", b"hidden")
                )
                root = self.bundle("trailing-" + str(padding), payload)
                with self.assertRaisesRegex(recovery.RecoveryError, "Nonzero data follows"):
                    recovery.run(root)

    def test_complete_zero_padding_remains_readable(self):
        root = self.bundle(payload=self.tar_bytes() + b"\0" * 2048)
        self.assertEqual(recovery.run(root)["state"], "CONTENTS_VERIFIED")

    def test_missing_or_single_end_marker_refused(self):
        valid = self.tar_bytes()
        for length in (1024, 1536):
            with self.subTest(length=length):
                root = self.bundle("short-" + str(length), valid[:length])
                with self.assertRaises(recovery.RecoveryError):
                    recovery.run(root)

    def test_invalid_late_tar_header_is_not_treated_as_end(self):
        root = self.bundle(payload=self.tar_bytes()[:1024] + b"X" * 512 + b"\0" * 1024)
        with self.assertRaisesRegex(recovery.RecoveryError, "Invalid or missing TAR"):
            recovery.run(root)

    def test_tar_metadata_must_match_manifest(self):
        variants = ((0o777, 0, "mode differs"), (0o600, 123456, "time differs"))
        for mode, mtime, message in variants:
            with self.subTest(mode=mode, mtime=mtime):
                root = self.bundle("metadata-" + str(mtime), self.tar_bytes(mode=mode, mtime=mtime))
                with self.assertRaisesRegex(recovery.RecoveryError, message):
                    recovery.run(root)

    def test_pax_nanosecond_timestamp_verifies_and_restores(self):
        source = self.file("x")
        os.utime(source, ns=(1234567890123456789, 1234567890123456789))
        root = Path(self.build()["path"])
        restored = self.base / "restored"
        recovery.run(root, restored, permissions=True)
        namespace = json_read(root / "ARCHIVE.json")["sources"][0]["namespace"]
        self.assertEqual((restored / namespace / "x").stat().st_mtime_ns, source.stat().st_mtime_ns)

    def test_copy_adopts_published_replica_after_catalogue_gap_idempotently(self):
        self.file("x")
        root = Path(self.build()["path"])
        args = self.copy_args(root)
        review = self.app.call("preflight_copy", args)
        original = recovery.publish_new

        def publish_then_fail(source, target):
            original(source, target)
            if Path(target).name.startswith("replica-"):
                raise OSError("Injected gap after replica publication")

        with mock.patch.object(recovery, "publish_new", side_effect=publish_then_fail):
            with self.assertRaisesRegex(OSError, "Injected gap"):
                self.app.call("copy", {**args, "approval": review["approval"]})
        self.assertEqual(self.app.call("status")["counts"]["replicas"], 0)
        retry = self.app.call("copy", {**args, "approval": review["approval"]})
        self.assertTrue(retry["reused"])
        self.assertTrue(retry["catalogue_reconciled"])
        self.assertEqual(self.app.call("status")["counts"]["replicas"], 1)
        again = self.app.call("copy", {**args, "approval": review["approval"]})
        self.assertFalse(again["catalogue_reconciled"])
        self.assertEqual(again["replica_id"], retry["replica_id"])
        self.assertEqual(self.app.call("status")["counts"]["replicas"], 1)

    def test_conflicting_replica_catalogue_is_not_overwritten(self):
        self.file("x")
        args = self.copy_args(Path(self.build()["path"]))
        review = self.app.call("preflight_copy", args)
        copied = self.app.call("copy", {**args, "approval": review["approval"]})
        with Store(self.workspace) as store:
            store.db.execute(
                "UPDATE replicas SET build_id=? WHERE id=?", ("wrong-build", copied["replica_id"])
            )
            store.commit()
        with self.assertRaises(Problem) as cm:
            self.app.call("copy", {**args, "approval": review["approval"]})
        self.assertEqual(cm.exception.code, "REPLICA_CONFLICT")
        with Store(self.workspace) as store:
            self.assertEqual(store.one("SELECT build_id FROM replicas")["build_id"], "wrong-build")

    def test_helper_file_limit_is_checked_before_copy(self):
        self.file("x")
        root = Path(self.build()["path"])
        payload_max = max(path.stat().st_size for path in root.rglob("payload.tar"))
        self.assertGreater((root / "RESTORE.py").stat().st_size, payload_max)
        args = self.copy_args(root, max_file=payload_max)
        with self.assertRaises(Problem) as cm:
            self.app.call("preflight_copy", args)
        self.assertEqual(cm.exception.code, "DEST_FILE_LIMIT")
        self.assertFalse((self.base / "disk" / "AP20-archives").exists())

    def test_unicode_receipt_paths_verify_and_copy(self):
        self.file("日本語/readme.txt")
        root = Path(self.build(self.plan(outer_depth=1))["path"])
        recovery.run(root)
        args = self.copy_args(root)
        review = self.app.call("preflight_copy", args)
        result = self.app.call("copy", {**args, "approval": review["approval"]})
        self.assertEqual(result["state"], "COPY_READBACK")

    def test_subset_copy_regenerates_partial_human_catalogue(self):
        self.file("x")
        root = Path(self.build()["path"])
        index = json_read(root / "ARCHIVE.json")
        args = {**self.copy_args(root), "packages": [index["packages"][0]["package_id"]]}
        review = self.app.call("preflight_copy", args)
        result = self.app.call("copy", {**args, "approval": review["approval"]})
        replica = Path(result["path"])
        self.assertIn("Set scope: PARTIAL_PLAN", (replica / "ARCHIVE.html").read_text())
        self.assertNotIn("Set scope: COMPLETE_PLAN", (replica / "ARCHIVE.html").read_text())
        self.assertEqual(recovery.validate_kit(replica)["state"], "KIT_VERIFIED")

    def test_helper_change_during_copy_never_gets_a_new_seal(self):
        self.file("x")
        root = Path(self.build()["path"])
        args = self.copy_args(root)
        review = self.app.call("preflight_copy", args)
        old_seals = (root / "SHA256SUMS").read_bytes()
        original = destinations.copy_file
        changed = False

        def copy_and_change(source, target, expected, progress):
            nonlocal changed
            original(source, target, expected, progress)
            if not changed:
                (root / "RESTORE.py").write_text("# changed during payload copying\n")
                changed = True

        with mock.patch.object(destinations, "copy_file", side_effect=copy_and_change):
            with self.assertRaises(Problem):
                self.app.call("copy", {**args, "approval": review["approval"]})
        self.assertEqual((root / "SHA256SUMS").read_bytes(), old_seals)
        self.assertFalse(any((self.base / "disk" / "AP20-archives").glob("replica-*")))

    @unittest.skipUnless(shutil.which("zstd"), "Optional zstd executable unavailable")
    def test_cancelled_decode_reaps_external_process(self):
        self.file("large", b"abc" * (1024 * 1024))
        root = Path(self.build(self.plan(codec="zstd"))["path"])
        processes = []
        original = recovery.subprocess.Popen

        def start(*args, **kwargs):
            process = original(*args, **kwargs)
            processes.append(process)
            return process

        def cancel(phase, done, total, path):
            if phase == "Decode verify" and done:
                raise recovery.RecoveryError("Injected decode cancellation")

        with mock.patch.object(recovery.subprocess, "Popen", side_effect=start):
            with self.assertRaisesRegex(recovery.RecoveryError, "Injected decode cancellation"):
                recovery.run(root, progress=cancel)
        self.assertTrue(processes)
        self.assertTrue(all(process.poll() is not None for process in processes))
