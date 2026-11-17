"""Byte reservations for interrupted replicas at an exact configured capacity."""

import json
from pathlib import Path
from unittest import mock

from test_core import Fixture
from archivist import recovery
from archivist.util import Problem


class CopyResumeV2Tests(Fixture):
    def interrupted_copy(self, *, before_publication=False):
        self.file("Project/file.bin", b"x" * 4096)
        plan = self.plan()
        built = self.build(plan)
        allocation = self.app.call(
            "allocate", {"plan_id": plan["id"], "media": [{"id": "one", "capacity": 100_000_000}]}
        )
        needed = allocation["media"][0]["used"]
        media = self.base / "medium"
        media.mkdir()
        destination = self.app.call(
            "destination",
            {"path": str(media), "kind": "disk", "label": "Exact budget", "capacity": needed},
        )
        arguments = {"bundle": built["path"], "destination": destination["id"]}
        review = self.app.call("preflight_copy", arguments)
        self.assertEqual(review["estimated_additional_bytes"], needed)
        final = Path(review["target"])
        partial = final.with_name("." + final.name + ".partial")
        if before_publication:
            publish = recovery.publish_new

            def interrupt(source, target):
                if Path(target) == final:
                    raise OSError("Injected publication interruption")
                return publish(source, target)

            boundary = mock.patch.object(recovery, "publish_new", side_effect=interrupt)
        else:
            boundary = mock.patch.object(
                recovery, "run", side_effect=OSError("Injected readback interruption")
            )
        with boundary, self.assertRaisesRegex(OSError, "Injected"):
            self.app.call("copy", {**arguments, "approval": review["approval"]})
        self.assertFalse(final.exists())
        self.assertTrue(partial.is_dir())
        self.assertEqual(self.app.call("replicas"), [])
        return arguments, review, partial, final

    def test_exact_capacity_retry_credits_validated_objects_and_kit(self):
        arguments, initial, partial, final = self.interrupted_copy()
        self.assertEqual(json.loads((partial / "COPY.json").read_text())["state"], "INCOMPLETE")
        review = self.app.call("preflight_copy", arguments)
        breakdown = review["capacity_breakdown"]
        self.assertEqual(breakdown["package_bytes"], 0)
        self.assertGreater(breakdown["completed_package_bytes"], 0)
        self.assertGreater(breakdown["validated_metadata_credit_bytes"], 0)
        self.assertEqual(review["estimated_additional_bytes"], review["configured_remaining_bytes"])
        self.assertEqual(initial["approval"], review["approval"])
        result = self.app.call("copy", {**arguments, "approval": review["approval"]})
        self.assertTrue(final.is_dir())
        self.assertFalse(partial.exists())
        self.assertEqual(result["state"], "COPY_READBACK")
        self.assertEqual(result["verification"]["state"], "CONTENTS_VERIFIED")
        self.assertEqual(len(self.app.call("replicas")), 1)

    def test_changed_completed_payload_gets_no_credit_or_overwrite(self):
        arguments, _, partial, final = self.interrupted_copy()
        root, _, refs = recovery.inspect(partial)
        receipt, artifact, _ = recovery.validate_receipt(root, refs[0], hash_payload=False)
        original = artifact.read_bytes()
        changed = bytes([original[0] ^ 1]) + original[1:]
        artifact.write_bytes(changed)
        with self.assertRaises(Problem) as caught:
            self.app.call("preflight_copy", arguments)
        self.assertEqual(caught.exception.code, "COPY_CONFLICT")
        self.assertEqual(artifact.read_bytes(), changed)
        self.assertEqual(artifact.stat().st_size, receipt["artifact_bytes"])
        self.assertFalse(final.exists())
        self.assertEqual(self.app.call("replicas"), [])

    def test_changed_sealed_helper_cannot_receive_metadata_credit(self):
        arguments, _, partial, final = self.interrupted_copy()
        helper = partial / "RESTORE.py"
        changed = helper.read_bytes() + b"\n# changed after interrupted copy\n"
        helper.write_bytes(changed)
        with self.assertRaisesRegex(recovery.RecoveryError, "Recovery-kit checksum mismatch"):
            self.app.call("preflight_copy", arguments)
        self.assertEqual(helper.read_bytes(), changed)
        self.assertFalse(final.exists())

    def test_orphan_temporary_bytes_remain_charged(self):
        arguments, _, partial, final = self.interrupted_copy()
        orphan = partial / ".payload.tar.partial-unfinished"
        orphan.write_bytes(b"orphan bytes")
        with self.assertRaises(Problem) as caught:
            self.app.call("preflight_copy", arguments)
        self.assertEqual(caught.exception.code, "DEST_CAPACITY")
        self.assertEqual(orphan.read_bytes(), b"orphan bytes")
        self.assertFalse(final.exists())

    def test_completed_partial_receipt_still_requires_new_readback(self):
        arguments, _, partial, final = self.interrupted_copy(before_publication=True)
        self.assertEqual(json.loads((partial / "COPY.json").read_text())["state"], "COMPLETE")
        self.assertTrue((partial / "REPLICA.json").is_file())
        review = self.app.call("preflight_copy", arguments)
        self.assertEqual(review["estimated_additional_bytes"], review["configured_remaining_bytes"])
        with mock.patch.object(recovery, "run", wraps=recovery.run) as checked:
            result = self.app.call("copy", {**arguments, "approval": review["approval"]})
        self.assertEqual(checked.call_count, 1)
        self.assertTrue(final.is_dir())
        self.assertEqual(result["verification"]["state"], "CONTENTS_VERIFIED")
        self.assertEqual(len(self.app.call("replicas")), 1)

    def test_partial_ownership_marker_must_match_current_approval(self):
        arguments, _, partial, final = self.interrupted_copy()
        marker = partial / "COPY.json"
        state = json.loads(marker.read_text())
        state["approval"] = "0" * 64
        marker.write_text(json.dumps(state) + "\n")
        with self.assertRaises(Problem) as caught:
            self.app.call("preflight_copy", arguments)
        self.assertEqual(caught.exception.code, "COPY_CONFLICT")
        self.assertFalse(final.exists())
