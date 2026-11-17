"""Service, publication and interruption boundaries, not implementation mock counts."""

import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock
from test_core import Fixture, ROOT
from archivist import artifacts, recovery
from archivist.progress import Progress
from archivist.store import Store
from archivist.util import Problem, atomic_json, canonical, hash_file, json_read
from archivist.web import make_server


class HttpTests(Fixture):
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
        self.thread.join()
        super().tearDown()

    def request(self, path, body=None, auth=True, headers=None):
        h = {"X-AP20-Token": self.server.session_token} if auth else {}
        if headers:
            h.update(headers)
        raw = None
        if body is not None:
            raw = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.url + path, data=raw, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as r:
            return r.code, r.read(), r.headers

    def test_entire_public_asset_set_is_served(self):
        status, raw, headers = self.request("/", auth=False)
        self.assertEqual(status, 200)
        self.assertIn(b"Archivist", raw)
        self.assertIn(b"/app.js", raw)
        self.assertIn(b"/app.css", raw)
        for path, mime in [("/app.js", "javascript"), ("/app.css", "css")]:
            status, raw, headers = self.request(path, auth=False)
            self.assertEqual(status, 200)
            self.assertGreater(len(raw), 100)
            self.assertIn(mime, headers["Content-Type"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_source_code_and_traversal_not_served(self):
        for path in [
            "/application.py",
            "/../ap20/application.py",
            "/workspace.sqlite",
            "/missing.js",
        ]:
            self.assertEqual(self.request(path)[0], 404)

    def test_api_requires_token(self):
        self.assertEqual(self.request("/api/read?action=status", auth=False)[0], 403)
        self.assertEqual(self.request("/api/read?action=status")[0], 200)

    def test_cross_origin_write_rejected(self):
        status, body, _ = self.request(
            "/api/preferences",
            {"appearance": "dark"},
            headers={"Origin": "https://untrusted.example"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"]["code"], "ORIGIN")

    def test_dns_rebinding_host_rejected(self):
        self.assertEqual(
            self.request("/", auth=False, headers={"Host": "untrusted.example"})[0], 403
        )

    def test_http_scan_and_plan_share_real_core(self):
        self.file("A/x.txt", b"bytes")
        status, raw, _ = self.request(
            "/api/task",
            {"action": "scan", "args": {"root": str(self.source), "backend": "filesystem"}},
        )
        self.assertEqual(status, 202)
        task = json.loads(raw)["task_id"]
        end = time.time() + 10
        while time.time() < end:
            _, raw, _ = self.request("/api/task/" + task)
            record = json.loads(raw)
            if record["state"] not in ("QUEUED", "RUNNING"):
                break
            time.sleep(0.02)
        self.assertEqual(record["state"], "COMPLETE", record)
        sid = record["result"]["snapshot_id"]
        self.assertEqual(
            self.app.call("browse", {"snapshot_id": sid})["directory"]["total_bytes"], 5
        )

    def test_saved_preferences_roundtrip(self):
        self.assertEqual(
            self.request("/api/preferences", {"appearance": "dark", "view": "plan"})[0], 200
        )
        self.assertEqual(self.app.call("preferences")["appearance"], "dark")

    def test_bad_action_not_accepted_as_shell(self):
        status, raw, _ = self.request("/api/task", {"action": "rm -rf anything", "args": {}})
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(raw)["error"]["code"], "ACTION")


class FailureBoundaryTests(Fixture):
    def test_atomic_publication_refuses_existing_file_and_empty_directory(self):
        src = self.base / "part"
        src.write_text("new")
        dst = self.base / "final"
        dst.write_text("old")
        with self.assertRaises(OSError):
            recovery.publish_new(src, dst)
        self.assertEqual(dst.read_text(), "old")
        self.assertTrue(src.exists())
        a = self.base / "part-dir"
        b = self.base / "existing-dir"
        a.mkdir()
        b.mkdir()
        before = b.stat().st_ino
        with self.assertRaises(OSError):
            recovery.publish_new(a, b)
        self.assertEqual(before, b.stat().st_ino)
        self.assertTrue(a.exists())

    def test_crash_after_package_commit_before_catalogue_is_recoverable(self):
        self.file("A/x.txt", b"abc" * 500)
        p = self.plan()
        args = {"plan_id": p["id"], "output": str(self.base / "build")}
        review = self.app.call("preflight_build", args)
        with mock.patch.object(
            artifacts, "publish_bundle", side_effect=OSError("injected catalogue failure")
        ):
            with self.assertRaises(OSError):
                self.app.call("build", {**args, "approval": review["approval"]})
        committed = list((self.base / "build" / "packages").rglob("payload.tar"))
        self.assertTrue(committed)
        hashes = {str(x): hash_file(x) for x in committed}
        result = self.build(p)
        self.assertEqual(result["state"], "COMPLETE")
        self.assertEqual(hashes, {str(x): hash_file(x) for x in committed})
        self.assertEqual(recovery.run(result["path"])["logical_bytes"], 1500)

    def test_cancel_during_packaging_never_publishes_incomplete_package(self):
        self.file("big", b"x" * (3 * 1024 * 1024))
        p = self.plan(target=5 * 1024 * 1024, maximum=6 * 1024 * 1024)
        args = {"plan_id": p["id"], "output": str(self.base / "build")}
        review = self.app.call("preflight_build", args)
        progress = Progress()

        def callback(state):
            if state["phase"] == "Build package" and state["done"] > 0:
                progress.cancelled.set()

        # Use advance hook to avoid dependence on UI throttling.
        original = progress.advance

        def advance(n, path=""):
            original(n, path)
            if n and progress.name.startswith("Build"):
                progress.cancelled.set()

        progress.advance = advance
        with self.assertRaises(Problem) as cm:
            self.app.call("build", {**args, "approval": review["approval"]}, progress)
        self.assertEqual(cm.exception.code, "CANCELLED")
        self.assertFalse((self.base / "build" / "ARCHIVE.json").exists())
        self.assertEqual((self.source / "big").stat().st_size, 3 * 1024 * 1024)

    @unittest.skipIf(os.name == "nt", "POSIX no-follow descriptor fixture")
    def test_source_replaced_by_symlink_is_not_read(self):
        f = self.file("x", b"original")
        p = self.plan()
        f.unlink()
        secret = self.base / "secret"
        secret.write_bytes(b"secret!")
        f.symlink_to(secret)
        with self.assertRaises((OSError, Problem)):
            self.build(p)
        self.assertEqual(secret.read_bytes(), b"secret!")

    def test_empty_directory_only_archive(self):
        (self.source / "Empty" / "Nested").mkdir(parents=True)
        b = self.build()
        out = self.base / "restore"
        r = recovery.run(b["path"], out)
        ns = json_read(Path(b["path"]) / "ARCHIVE.json")["sources"][0]["namespace"]
        self.assertTrue((out / ns / "Empty" / "Nested").is_dir())
        self.assertEqual(r["logical_bytes"], 0)

    @unittest.skipUnless(shutil.which("zstd"), "External zstd unavailable")
    def test_compression_measurement_is_explicit_and_roundtripped(self):
        self.file("A/text.txt", b"abcd" * 16000)
        p = self.plan()
        pkg = next(
            x
            for x in self.app.call("packages", {"plan_id": p["id"]})["packages"]
            if x["kind"] == "data"
        )
        result = self.app.call(
            "sample", {"plan_id": p["id"], "package_id": pkg["id"], "max_bytes": 65536}
        )
        self.assertEqual(len(result["results"]), 5)
        self.assertTrue(
            all(x["roundtrip_sha256"] == result["sample_sha256"] for x in result["results"])
        )
        self.assertEqual(
            self.app.call("packages", {"plan_id": p["id"]})["plan"]["fingerprint"], p["fingerprint"]
        )

    def hostile_bundle(self, member_name="safe", kind="file", tar_type=None):
        root = self.base / "hostile"
        root.mkdir()
        payload = root / "payload.tar"
        info = tarfile.TarInfo(member_name)
        info.size = 1
        info.mtime = 0
        info.mode = 0o600
        if tar_type is not None:
            info.type = tar_type
            info.size = 0
            info.linkname = "../outside"
        with tarfile.open(payload, "w", format=tarfile.PAX_FORMAT) as out:
            out.addfile(info, io.BytesIO(b"x") if info.size else None)
        manifest = root / "members.jsonl.gz"
        row = {
            "name": member_name,
            "kind": kind,
            "size": info.size,
            "mtime_ns": 0,
            "mode": 0o600,
            "sha256": hashlib.sha256(b"x" if info.size else b"").hexdigest(),
        }
        with gzip.open(manifest, "wb") as out:
            out.write(canonical(row) + b"\n")
        receipt = {
            "format": "AP20Package/1",
            "package_id": "P000001",
            "codec": "none",
            "artifact": "payload.tar",
            "artifact_bytes": payload.stat().st_size,
            "artifact_sha256": hash_file(payload),
            "manifest": "members.jsonl.gz",
            "manifest_bytes": manifest.stat().st_size,
            "manifest_sha256": hash_file(manifest),
            "tar_bytes": payload.stat().st_size,
            "logical_bytes": info.size,
            "member_count": 1,
        }
        atomic_json(root / "receipt.json", receipt)
        atomic_json(
            root / "ARCHIVE.json",
            {
                "format": "AP20Archive/1",
                "packages": [
                    {
                        "package_id": "P000001",
                        "receipt": "receipt.json",
                        "receipt_sha256": hash_file(root / "receipt.json"),
                    }
                ],
                "scope": "PARTIAL_PLAN",
                "planned_packages": 2,
            },
        )
        (root / "README.txt").write_text("Synthetic hostile fixture; never execute its helper.\n")
        (root / "RESTORE.py").write_text("# Synthetic fixture helper; not executed.\n")
        names = ("ARCHIVE.json", "README.txt", "RESTORE.py", "receipt.json")
        (root / "SHA256SUMS").write_text(
            "".join(hash_file(root / name) + "  " + name + "\n" for name in names), encoding="utf-8"
        )
        return root

    def test_consistently_resealed_traversal_manifest_rejected(self):
        root = self.hostile_bundle("../outside")
        out = self.base / "restore"
        with self.assertRaises(recovery.RecoveryError):
            recovery.run(root, out)
        self.assertFalse(out.exists())
        self.assertFalse((self.base / "outside").exists())

    def test_tar_symlink_rejected_even_when_receipts_match(self):
        root = self.hostile_bundle("link", tar_type=tarfile.SYMTYPE)
        out = self.base / "restore"
        with self.assertRaises(recovery.RecoveryError):
            recovery.run(root, out)
        self.assertFalse(out.exists())

    def test_declared_decode_limit_enforced(self):
        root = self.hostile_bundle()
        r = json_read(root / "receipt.json")
        r["tar_bytes"] = 1024
        atomic_json(root / "receipt.json", r)
        index = json_read(root / "ARCHIVE.json")
        index["packages"][0]["receipt_sha256"] = hash_file(root / "receipt.json")
        atomic_json(root / "ARCHIVE.json", index)
        names = ("ARCHIVE.json", "README.txt", "RESTORE.py", "receipt.json")
        (root / "SHA256SUMS").write_text(
            "".join(hash_file(root / name) + "  " + name + "\n" for name in names), encoding="utf-8"
        )
        with self.assertRaisesRegex(recovery.RecoveryError, "Decoded stream exceeds"):
            recovery.run(root)

    def test_plan_database_tamper_is_detected(self):
        self.file("x")
        p = self.plan()
        with Store(self.workspace) as db:
            db.db.execute(
                "UPDATE packages SET codec='gzip' WHERE plan_id=? AND kind='data'", (p["id"],)
            )
            db.commit()
        self.assert_problem(
            "PLAN_CHANGED",
            "preflight_build",
            {"plan_id": p["id"], "output": str(self.base / "build")},
        )

    @unittest.skipIf(os.name == "nt", "Unix executable launchers; native Windows has its own check")
    def test_unix_launchers_resolve_installation_from_other_directory(self):
        for name in ("GUI.sh", "CLI.sh", "GUI.command", "CLI.command"):
            with self.subTest(launcher=name):
                proc = subprocess.run(
                    [str(ROOT / "launchers" / name), "--help"],
                    cwd=self.base,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn("usage:", proc.stdout)

    @unittest.skipUnless(os.name == "nt", "Native Windows launcher execution requires Windows")
    def test_windows_double_click_bootstrap(self):
        for name in ("GUI.cmd", "CLI.cmd"):
            proc = subprocess.run(
                ["cmd", "/c", str(ROOT / "launchers" / name), "--help"],
                cwd=self.base,
                input="\n",
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("usage:", proc.stdout)

    def test_windows_launchers_do_not_require_powershell(self):
        for name in ("GUI.cmd", "CLI.cmd"):
            text = (ROOT / "launchers" / name).read_text().lower()
            self.assertIn("py -3", text)
            self.assertIn("%~dp0..\\archivist.py", text)
            self.assertNotIn("powershell.exe", text)
            self.assertNotIn("executionpolicy", text)


if __name__ == "__main__":
    unittest.main()


class CliWorkflowTests(Fixture):
    def test_preflight_list_of_ids_is_printable(self):
        import contextlib
        from archivist.cli import print_result

        with contextlib.redirect_stdout(io.StringIO()) as output:
            print_result({"operation": "build", "packages": ["P000001", "P000002"]})
        self.assertIn("P000001", output.getvalue())

    def test_real_cli_scan_plan_build_copy_restore(self):
        self.file("Project/readme.txt", b"preserve this\n" * 100)
        (self.source / "Empty").mkdir()

        def run(*args):
            p = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "archivist.py"),
                    "--workspace",
                    str(self.workspace),
                    "--quiet",
                    "--json",
                    *args,
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(p.returncode, 0, p.stderr)
            return json.loads(p.stdout)

        scan = run("scan", str(self.source), "--backend", "filesystem")
        plan = run(
            "plan",
            scan["snapshot_id"],
            "--minimum",
            "0",
            "--target",
            "500KB",
            "--maximum",
            "1MB",
            "--codec",
            "gzip",
        )
        built = run("build", plan["id"], "--output", str(self.base / "build"), "--yes")
        dest = run("dest", str(self.base / "backup"), "--label", "Test destination")
        copied = run("copy", built["path"], "--destination", dest["id"], "--yes")
        self.assertEqual(copied["state"], "COPY_READBACK")
        replica = next((self.base / "backup" / "AP20-archives").glob("replica-*"))
        restored = run("restore", str(replica), "--output", str(self.base / "restored"), "--yes")
        self.assertEqual(restored["state"], "RESTORED_VERIFIED")
        ns = json.loads((replica / "ARCHIVE.json").read_text())["sources"][0]["namespace"]
        self.assertEqual(
            (self.base / "restored" / ns / "Project/readme.txt").read_bytes(),
            (self.source / "Project/readme.txt").read_bytes(),
        )
        self.assertTrue((self.base / "restored" / ns / "Empty").is_dir())
