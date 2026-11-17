"""Cancellation and observer failures around durable worker boundaries."""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from unittest import mock

from test_core import Fixture
from archivist import artifacts, destinations, recovery
from archivist.progress import Progress
from archivist.util import Problem, hash_file


class ExecutionBoundaryTests(Fixture):
    def test_gui_cancellation_unblocks_stalled_encoder_and_reaps_child(self):
        original = subprocess.Popen
        children, errors = [], []
        started = threading.Event()
        progress = Progress()

        def stalled_encoder(*args, **kwargs):
            child = original([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
            children.append(child)
            started.set()
            return child

        def worker():
            try:
                with artifacts.encoded_writer(self.base / "out.zst", "zstd", 3, progress) as writer:
                    writer.write(b"x" * (8 * 1024 * 1024))
            except BaseException as exc:
                errors.append(exc)

        with mock.patch.object(
            artifacts.shutil, "which", return_value="fixture-encoder"
        ), mock.patch.object(artifacts.subprocess, "Popen", side_effect=stalled_encoder):
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            try:
                self.assertTrue(started.wait(3))
                progress.cancelled.set()
                thread.join(5)
                self.assertFalse(thread.is_alive(), "Cancellation left the writer blocked")
                self.assertTrue(children)
                self.assertIsNotNone(children[0].poll())
                self.assertEqual(len(errors), 1)
                self.assertIsInstance(errors[0], Problem)
                self.assertEqual(errors[0].code, "CANCELLED")
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.wait(timeout=3)
                thread.join(3)

    def test_observer_failure_does_not_change_the_durable_build_outcome(self):
        self.file("A/file", b"a" * 4096)
        self.file("B/file", b"b" * 4096)
        plan = self.plan()
        args = {"plan_id": plan["id"], "output": str(self.base / "build")}
        review = self.app.call("preflight_build", args)

        def broken_observer(state):
            overall = state.get("overall")
            if overall and overall["done"] == 1:
                raise RuntimeError("Injected observer failure after committed package")

        progress = Progress(broken_observer)
        result = self.app.call("build", {**args, "approval": review["approval"]}, progress)
        root = Path(args["output"])
        self.assertEqual(result["state"], "COMPLETE")
        self.assertEqual(
            len(recovery.validate_kit(root)["index"]["packages"]), plan["counts"]["packages"]
        )
        self.assertEqual(recovery.run(root)["state"], "CONTENTS_VERIFIED")
        self.assertEqual(self.app.call("builds")[0]["state"], "COMPLETE")
        self.assertIsNone(progress.callback)
        self.assertTrue(
            any(event["code"] == "PROGRESS_OBSERVER_FAILED" for event in progress.events)
        )

    def test_reused_object_hash_respects_cancellation_without_mutation(self):
        source, target = self.base / "source-object", self.base / "target-object"
        source.write_bytes(b"x" * (2 * 1024 * 1024))
        target.write_bytes(source.read_bytes())
        expected = {"size": source.stat().st_size, "sha256": hash_file(source)}
        progress = Progress()
        advance = progress.advance

        def cancelled_after_chunk(amount, path=""):
            advance(amount, path)
            progress.cancelled.set()

        progress.advance = cancelled_after_chunk
        with self.assertRaises(Problem) as caught:
            destinations.copy_file(source, target, expected, progress)
        self.assertEqual(caught.exception.code, "CANCELLED")
        self.assertEqual(hash_file(target), expected["sha256"])
        self.assertEqual(hash_file(source), expected["sha256"])
