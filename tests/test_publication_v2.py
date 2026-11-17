"""Observed process interruption, rollback and publication-boundary regressions."""

import json
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from test_core import Fixture, ROOT
from archivist import archive_html, kit_publication, recovery
from archivist.util import Problem, hash_file, json_read


class PublicationV2Tests(Fixture):
    def build_args(self):
        self.file("A/x", b"A" * 4096)
        self.file("B/x", b"B" * 4096)
        plan = self.plan()
        args = {"plan_id": plan["id"], "output": str(self.base / "build")}
        review = self.app.call("preflight_build", args)
        return plan, args, review

    def control_bytes(self, root):
        return {
            name: (root / name).read_bytes()
            for name in kit_publication.FILES
            if (root / name).exists()
        }

    def interrupted_child(self, archive_generation, after_seal=False):
        plan, args, review = self.build_args()
        script = """
import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from archivist.application import Application
from archivist import kit_publication
original = kit_publication.replace_file
count = 0
def interrupted(source, destination, expected):
    global count
    if source.parent.name == 'new' and destination.name == sys.argv[5]:
        count += 1
        if count == int(sys.argv[4]):
            if sys.argv[5] == 'SHA256SUMS':
                original(source, destination, expected)
            os._exit(73)
    return original(source, destination, expected)
kit_publication.replace_file = interrupted
Application(sys.argv[2]).call('build', json.loads(sys.argv[3]))
"""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                str(ROOT),
                str(self.workspace),
                json.dumps({**args, "approval": review["approval"]}),
                str(archive_generation),
                "SHA256SUMS" if after_seal else "ARCHIVE.json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 73, result.stderr)
        return plan, args, review

    def test_handled_failure_restores_previous_exact_kit_and_resume(self):
        plan, args, review = self.build_args()
        root = Path(args["output"])
        prior = {}
        original_publish = kit_publication.publish
        original_replace = kit_publication.replace_file
        index_writes = 0

        def record_publish(*values, **kwargs):
            result = original_publish(*values, **kwargs)
            prior.update(self.control_bytes(root))
            return result

        def fail_second_index(source, destination, expected):
            nonlocal index_writes
            if source.parent.name == "new" and destination.name == "ARCHIVE.json":
                index_writes += 1
                if index_writes == 2:
                    raise OSError("Injected interruption after new HTML")
            return original_replace(source, destination, expected)

        with ExitStack() as patches:
            patches.enter_context(
                mock.patch.object(kit_publication, "publish", side_effect=record_publish)
            )
            patches.enter_context(
                mock.patch.object(kit_publication, "replace_file", side_effect=fail_second_index)
            )
            with self.assertRaisesRegex(OSError, "Injected interruption"):
                self.app.call("build", {**args, "approval": review["approval"]})
        self.assertEqual(self.control_bytes(root), prior)
        self.assertFalse((root / kit_publication.TRANSACTION).exists())
        self.assertEqual(len(recovery.validate_kit(root)["index"]["packages"]), 1)
        self.assertEqual(len(list((root / "packages").rglob("receipt.json"))), 2)
        result = self.build(plan)
        self.assertEqual(result["state"], "COMPLETE")
        self.assertEqual(recovery.run(root)["state"], "CONTENTS_VERIFIED")

    def test_real_process_exit_has_read_only_preflight_then_writer_recovery(self):
        plan, args, review = self.interrupted_child(2)
        root = Path(args["output"])
        self.assertTrue((root / kit_publication.TRANSACTION).is_dir())
        before = {
            str(path.relative_to(root)): (hash_file(path), path.stat().st_mtime_ns)
            for path in root.rglob("*")
            if path.is_file()
        }
        pending = self.app.call("preflight_build", args)
        after = {
            str(path.relative_to(root)): (hash_file(path), path.stat().st_mtime_ns)
            for path in root.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)
        self.assertTrue(pending["kit_publication"]["pending"])
        self.assertEqual(pending["kit_publication"]["action"], "rollback")
        self.assertEqual(pending["approval"], review["approval"])
        result = self.app.call("build", {**args, "approval": pending["approval"]})
        self.assertEqual(result["state"], "COMPLETE")
        self.assertFalse((root / kit_publication.TRANSACTION).exists())
        self.assertEqual(recovery.run(root)["state"], "CONTENTS_VERIFIED")

    def test_failed_rollback_preserves_primary_exception_and_secondary_evidence(self):
        plan, args, review = self.build_args()
        primary = OSError("Injected primary publication failure")
        secondary = RuntimeError("Injected secondary rollback failure")
        with ExitStack() as patches:
            patches.enter_context(
                mock.patch.object(kit_publication, "replace_file", side_effect=primary)
            )
            patches.enter_context(
                mock.patch.object(kit_publication, "recover", side_effect=secondary)
            )
            with self.assertRaises(OSError) as caught:
                self.app.call("build", {**args, "approval": review["approval"]})
        self.assertIs(caught.exception, primary)
        self.assertEqual(caught.exception.kit_recovery_error, str(secondary))
        root = Path(args["output"])
        self.assertTrue((root / kit_publication.TRANSACTION).is_dir())
        failure = next(row["error"] for row in self.app.call("history") if row["kind"] == "build")
        self.assertEqual(failure["code"], "OSError")
        self.assertEqual(failure["kit_recovery_error"], str(secondary))
        self.assertEqual(self.build(plan)["state"], "COMPLETE")
        self.assertEqual(recovery.run(root)["state"], "CONTENTS_VERIFIED")

    def test_initial_generation_process_exit_recovers_without_prior_kit(self):
        plan, args, review = self.interrupted_child(1)
        root = Path(args["output"])
        self.assertFalse((root / "ARCHIVE.json").exists())
        pending = self.app.call("preflight_build", args)
        self.assertTrue(pending["kit_publication"]["pending"])
        self.assertEqual(pending["approval"], review["approval"])
        self.assertEqual(self.build(plan)["state"], "COMPLETE")
        recovery.validate_kit(root)

    def test_completed_generation_is_kept_after_exit_before_journal_cleanup(self):
        plan, args, review = self.interrupted_child(2, after_seal=True)
        root = Path(args["output"])
        before = self.control_bytes(root)
        pending = self.app.call("preflight_build", args)
        self.assertEqual(pending["kit_publication"]["action"], "commit")
        self.assertEqual(pending["approval"], review["approval"])
        recovered = kit_publication.recover(root)
        self.assertEqual(recovered["action"], "commit")
        self.assertEqual(self.control_bytes(root), before)
        self.assertEqual(len(recovery.validate_kit(root)["index"]["packages"]), 2)
        self.assertFalse((root / kit_publication.TRANSACTION).exists())
        self.assertEqual(self.build(plan)["state"], "COMPLETE")

    def test_pending_journal_never_overwrites_unrecorded_helper_bytes(self):
        _, args, review = self.interrupted_child(2)
        root = Path(args["output"])
        changed = (root / "RESTORE.py").read_bytes() + b"\n# unrecorded change\n"
        (root / "RESTORE.py").write_bytes(changed)
        for operation in ("preflight_build", "build"):
            with self.assertRaises(Problem) as cm:
                self.app.call(
                    operation,
                    {**args, **({"approval": review["approval"]} if operation == "build" else {})},
                )
            self.assertEqual(cm.exception.code, "KIT_TRANSACTION_CONFLICT")
        self.assertEqual((root / "RESTORE.py").read_bytes(), changed)
        self.assertTrue((root / kit_publication.TRANSACTION).exists())

    def test_generated_oversize_kit_refused_before_publication(self):
        _, args, review = self.build_args()
        root = Path(args["output"])

        def oversized_html(source, index, *, output_root=None):
            (output_root / "ARCHIVE.html").write_bytes(b"x" * (recovery.MAX_JSON + 1))

        with mock.patch.object(archive_html, "write_catalogue", side_effect=oversized_html):
            with self.assertRaisesRegex(
                recovery.RecoveryError, "Oversized recovery-kit file: ARCHIVE.html"
            ):
                self.app.call("build", {**args, "approval": review["approval"]})
        self.assertFalse((root / "ARCHIVE.json").exists())
        self.assertFalse((root / kit_publication.TRANSACTION).exists())
        self.assertEqual(json_read(root / "BUILD.json")["state"], "INTERRUPTED")

    def test_all_source_roots_constrain_partial_build_output_even_offline(self):
        self.file("A/x")
        first = self.scan()
        other = self.base / "other-source"
        other.mkdir()
        (other / "y").write_bytes(b"B")
        second = self.app.call("scan", {"root": str(other), "backend": "filesystem"})
        plan = self.app.call(
            "plan",
            {
                "snapshots": [first["snapshot_id"], second["snapshot_id"]],
                "policy": {
                    "minimum": 0,
                    "target": 2_000_000,
                    "maximum": 4_000_000,
                    "codec": "none",
                },
            },
        )
        packages = self.app.call("packages", {"plan_id": plan["id"]})["packages"]
        selected = next(
            p["id"]
            for p in packages
            if p["snapshot_id"] == first["snapshot_id"] and p["kind"] == "data"
        )
        args = {
            "plan_id": plan["id"],
            "output": str(other / "unsafe-output"),
            "packages": [selected],
        }
        self.assert_problem("OUTPUT_OVERLAP", "preflight_build", args)
        other.rename(self.base / "offline-source")
        self.assert_problem("OUTPUT_OVERLAP", "preflight_build", args)
        result = self.build(plan, packages=[selected])
        self.assertEqual(result["state"], "PARTIAL_PLAN")
