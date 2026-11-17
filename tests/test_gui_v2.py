"""GUI service contracts and terminal progress regression boundaries."""

import json
import threading
import time
import unittest
import urllib.parse
import urllib.request
from unittest import mock

from test_core import Fixture
from archivist.progress import Progress
from archivist.web import Tasks, make_server


class ProgressLifecycleTests(unittest.TestCase):
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
