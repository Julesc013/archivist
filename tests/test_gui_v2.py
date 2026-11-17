"""GUI service contracts and terminal progress regression boundaries."""

import json
import concurrent.futures
import threading
import time
import unittest
import urllib.parse
import urllib.request
from unittest import mock

from test_core import Fixture
from archivist.progress import Progress
from archivist.web import Tasks, make_server
from archivist.util import Problem


class ProgressLifecycleTests(unittest.TestCase):
    def test_failed_observer_is_disabled_without_changing_work_or_cancellation(self):
        observer = mock.Mock(side_effect=RuntimeError("x" * 1000))
        progress = Progress(observer)
        progress.phase("Build", total=100, unit="bytes")
        progress.update(50, "file")
        progress.check()
        self.assertIsNone(progress.callback)
        observer.assert_called_once()
        warnings = [
            event
            for event in progress.state()["events"]
            if event["code"] == "PROGRESS_OBSERVER_FAILED"
        ]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(len(warnings[0]["message"]), 500)
        progress.cancelled.set()
        with self.assertRaises(Problem) as error:
            progress.update(51)
        self.assertEqual(error.exception.code, "CANCELLED")

    def test_repeated_reader_phase_resets_total_and_path_for_new_objects(self):
        progress = Progress()
        reader = progress.recovery_callback()
        reader("Hash object", 0, 100, "first")
        reader("Hash object", 50, 100, "first")
        reader("Hash object", 0, 200, "second")
        state = progress.state()
        self.assertEqual((state["done"], state["total"], state["path"]), (0, 200, "second"))
        self.assertEqual(len([event for event in state["events"] if event["code"] == "PHASE"]), 2)
        progress.phase("Publish")
        self.assertEqual(progress.state()["path"], "")

    def test_job_package_scope_is_separate_from_step_and_returned_by_value(self):
        progress = Progress()
        progress.set_overall(1, 3, "built and verified packages")
        progress.set_package("P000002", 2, 3)
        progress.phase("Hash", 1024, "bytes")
        progress.update(512)
        state = progress.state()
        self.assertEqual(state["overall"]["done"], 1)
        self.assertEqual(state["package"]["index"], 2)
        self.assertEqual(state["done"], 512)
        state["overall"]["done"] = 99
        self.assertEqual(progress.state()["overall"]["done"], 1)

    def test_cancelling_a_finished_task_does_not_rewrite_its_progress(self):
        class ImmediateApplication:
            def call(self, action, arguments, progress):
                return {"complete": True}

        tasks = Tasks(ImmediateApplication())
        try:
            ident = tasks.submit("scan", {})
            tasks.items[ident]["future"].result(timeout=2)
            before = tasks.list(ident)[0]
            self.assertFalse(tasks.cancel(ident)["cancel_requested"])
            self.assertEqual(tasks.list(ident)[0], before)
        finally:
            tasks.close()

    def test_close_cancels_queued_futures_and_finishes_their_records(self):
        entered, release = threading.Event(), threading.Event()

        class WaitingApplication:
            def call(self, action, arguments, progress):
                entered.set()
                if not release.wait(timeout=5):
                    raise RuntimeError("Test worker was not released")
                progress.check()

        tasks = Tasks(WaitingApplication())
        closer = None
        try:
            tasks.submit("scan", {})
            self.assertTrue(entered.wait(timeout=2))
            queued = tasks.submit("scan", {})
            closer = threading.Thread(target=tasks.close)
            closer.start()
            with self.assertRaises(concurrent.futures.CancelledError):
                tasks.items[queued]["future"].result(timeout=2)
            record = tasks.list(queued)[0]
            self.assertEqual(record["state"], "CANCELLED")
            self.assertTrue(record["progress"]["finished"])
            self.assertIn("completed", record)
        finally:
            release.set()
            if closer:
                closer.join(timeout=3)
            else:
                tasks.close()
        self.assertFalse(closer.is_alive())

    def test_terminal_timing_is_frozen_and_finish_is_idempotent(self):
        with mock.patch("archivist.progress.time.monotonic", return_value=100) as clock:
            progress = Progress()
            progress.phase("Copy", total=4096, unit="bytes")
            clock.return_value = 110
            progress.advance(1024)
            clock.return_value = 120
            progress.finish()
            first = progress.state()
            clock.return_value = 10000
            progress.finish()
            later = progress.state()
        self.assertEqual(first, later)
        self.assertEqual(later["elapsed_seconds"], 20)
        self.assertTrue(later["finished"])
        self.assertIsNone(later["eta_seconds"])

    def test_cancelled_queued_task_has_terminal_timing_and_completion(self):
        entered = threading.Event()
        release = threading.Event()

        class WaitingApplication:
            def call(self, action, arguments, progress):
                entered.set()
                if not release.wait(timeout=5):
                    raise RuntimeError("Test worker was not released")
                progress.check()
                return {"complete": True}

        tasks = Tasks(WaitingApplication())
        try:
            tasks.submit("scan", {})
            self.assertTrue(entered.wait(timeout=2))
            queued = tasks.submit("scan", {})
            tasks.cancel(queued)
            first = tasks.list(queued)[0]
            time.sleep(0.02)
            later = tasks.list(queued)[0]
            self.assertEqual(later["state"], "CANCELLED")
            self.assertIn("completed", later)
            self.assertTrue(later["progress"]["finished"])
            self.assertEqual(
                first["progress"]["elapsed_seconds"], later["progress"]["elapsed_seconds"]
            )
        finally:
            release.set()
            tasks.close()


class GuiServiceContractTests(Fixture):
    def setUp(self):
        super().setUp()
        self.server = make_server(self.app, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server.tasks.close()
        self.thread.join(timeout=3)
        super().tearDown()

    def request(self, path, body=None):
        headers = {"X-AP20-Token": self.server.session_token}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.url + path, data=data, headers=headers)
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)

    def read(self, action, arguments):
        query = urllib.parse.urlencode({"action": action, "args": json.dumps(arguments)})
        return self.request("/api/read?" + query)

    def test_off_page_package_detail_and_move_search_use_real_catalogue(self):
        for number in range(105):
            self.file(f"Project-{number:03d}/notes.txt", b"notes")
        plan = self.plan()
        packages = self.app.call("packages", {"plan_id": plan["id"]})["packages"]
        first = next(package for package in packages if package["kind"] == "data")
        revised = self.app.call(
            "revise",
            {
                "plan_id": plan["id"],
                "codec_changes": {first["id"]: {"codec": "gzip", "level": 5}},
            },
        )
        later_page = self.read("packages", {"plan_id": revised["id"], "offset": 100})
        self.assertGreater(later_page["total"], 100)
        self.assertNotIn(first["id"], [package["id"] for package in later_page["packages"]])
        detail = self.read("package", {"plan_id": revised["id"], "package_id": first["id"]})
        self.assertEqual((detail["codec"], detail["level"]), ("gzip", 5))
        targets = self.read(
            "packages",
            {
                "plan_id": revised["id"],
                "query": "Project-104",
                "kind": "data",
                "snapshot_id": detail["snapshot_id"],
                "exclude_package_id": detail["id"],
            },
        )
        self.assertEqual(targets["total"], 1)
        self.assertEqual(targets["packages"][0]["anchor"], "Project-104")

    def test_completed_http_task_remains_complete_without_clock_growth(self):
        self.file("notes.txt", b"notes")
        submitted = self.request(
            "/api/task",
            {
                "action": "scan",
                "args": {"root": str(self.source), "backend": "filesystem"},
            },
        )
        deadline = time.monotonic() + 5
        record = None
        while time.monotonic() < deadline:
            record = self.request("/api/task/" + submitted["task_id"])
            if record["state"] not in ("RUNNING", "QUEUED"):
                break
            time.sleep(0.01)
        self.assertEqual(record["state"], "COMPLETE", record)
        time.sleep(0.03)
        later = self.request("/api/task/" + submitted["task_id"])
        self.assertEqual(record["progress"], later["progress"])
        self.assertTrue(later["progress"]["finished"])


if __name__ == "__main__":
    unittest.main()
