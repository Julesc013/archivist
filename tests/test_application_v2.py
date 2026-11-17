"""Public operation regressions for catalogue navigation and offline recovery."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest import mock

from test_core import Fixture, ROOT
from archivist.application import Application
from archivist import recovery
from archivist.store import config_directory, default_workspace
from archivist.util import hash_file


class ApplicationV2Tests(Fixture):
    def test_package_lookup_and_filtered_total_do_not_depend_on_visible_page(self):
        for i in range(105):
            self.file(f"Project-{i:03}/file.bin", bytes([i]) * 4096)
        plan = self.plan(target=16384, maximum=16384)
        first = self.app.call("packages", {"plan_id": plan["id"], "limit": 10})
        later = self.app.call("packages", {"plan_id": plan["id"], "offset": 100})
        self.assertGreater(first["total"], 100)
        selected = later["packages"][0]
        detail = self.app.call("package", {"plan_id": plan["id"], "package_id": selected["id"]})
        self.assertEqual(detail, selected)
        filtered = self.app.call(
            "packages", {"plan_id": plan["id"], "query": selected["id"], "kind": selected["kind"]}
        )
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["packages"], [selected])
        filtered = self.app.call(
            "packages",
            {"plan_id": plan["id"], "query": selected["id"], "exclude_package_id": selected["id"]},
        )
        self.assertEqual(filtered["total"], 0)

    def test_search_uses_sealed_manifests_after_source_and_workspace_are_removed(self):
        for i in range(5):
            self.file(f"Project/file-{i}.txt", b"preserve")
        built = self.build()
        shutil.rmtree(self.source)
        shutil.rmtree(self.workspace)
        offline = Application(self.base / "new-workspace")
        result = offline.call(
            "recovery_find", {"bundle": built["path"], "query": ".TXT", "limit": 2, "offset": 2}
        )
        self.assertEqual(result["total"], 5)
        self.assertEqual(len(result["rows"]), 2)
        self.assertFalse(result["payload_verified"])
        self.assertEqual(result["scope"], "CATALOGUE_SEARCH")
        self.assertTrue(result["package_ids"])
        restored = recovery.run(built["path"], self.base / "restored", result["package_ids"])
        self.assertEqual(restored["logical_bytes"], 5 * len(b"preserve"))

    def test_subtree_search_does_not_match_sibling_prefix(self):
        self.file("Photos/a.txt")
        self.file("Photos-old/b.txt")
        built = self.build()
        index = json.loads((Path(built["path"]) / "ARCHIVE.json").read_text())
        query = index["sources"][0]["namespace"] + "/Photos"
        result = self.app.call(
            "recovery_find", {"bundle": built["path"], "query": query, "mode": "subtree"}
        )
        self.assertTrue(result["rows"])
        self.assertTrue(
            all(
                row["path"] == query or row["path"].startswith(query + "/")
                for row in result["rows"]
            )
        )
        self.assertFalse(any("Photos-old" in row["path"] for row in result["rows"]))

    def test_diff_records_encoding_change_and_revert_creates_new_revision(self):
        self.file("Project/a.txt")
        before = self.plan()
        package = next(
            p
            for p in self.app.call("packages", {"plan_id": before["id"]})["packages"]
            if p["kind"] == "data"
        )
        after = self.app.call(
            "revise",
            {
                "plan_id": before["id"],
                "codec_changes": {package["id"]: {"codec": "gzip", "level": 6}},
            },
        )
        result = self.app.call(
            "plan_diff", {"plan_id": before["id"], "target_plan_id": after["id"]}
        )
        self.assertGreater(result["total"], 0)
        self.assertTrue(all(row["change"] == "ENCODING_CHANGED" for row in result["rows"]))
        reverted = self.app.call("revert", {"plan_id": after["id"], "target_plan_id": before["id"]})
        self.assertNotEqual(reverted["id"], before["id"])
        self.assertEqual(reverted["parent_plan"], after["id"])
        unchanged = self.app.call(
            "plan_diff", {"plan_id": before["id"], "target_plan_id": reverted["id"]}
        )
        self.assertEqual(unchanged["total"], 0)

    def test_v2_default_directories_do_not_select_v20_implicitly(self):
        with mock.patch.dict(
            os.environ,
            {
                "ARCHIVIST_CONFIG_HOME": str(self.base / "config"),
                "ARCHIVIST_WORKSPACE": str(self.base / "chosen"),
                "AP20_WORKSPACE": str(self.base / "old"),
            },
            clear=False,
        ):
            self.assertEqual(config_directory(), self.base / "config")
            self.assertEqual(default_workspace(), self.base / "chosen")
            self.assertFalse((self.base / "chosen").exists())
            self.assertFalse((self.base / "old").exists())

    def test_doctor_distinguishes_presence_from_hardware_qualification(self):
        result = self.app.call("doctor")
        checks = {row["id"]: row for row in result["checks"]}
        self.assertEqual(checks["python"]["state"], "ready")
        self.assertEqual(checks["ltfs"]["state"], "unverified")
        self.assertIn(checks["everything"]["state"], ("not_applicable", "missing", "unverified"))

    def test_cli_find_and_version_from_unrelated_working_directory(self):
        self.file("Project/a.txt")
        built = self.build()
        args = [
            sys.executable,
            str(ROOT / "archivist.py"),
            "--workspace",
            str(self.workspace),
            "--quiet",
            "--json",
            "find",
            built["path"],
            "a.txt",
        ]
        result = subprocess.run(args, cwd=self.base, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["total"], 1)
        result = subprocess.run(
            [sys.executable, str(ROOT / "archivist.py"), "--version"],
            cwd=self.base,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.stdout.strip(), "2.0.0-alpha.1")

    def legacy_catalogue(self, bundle):
        """Produce a consistent older catalogue with no dependency declaration."""
        root = Path(bundle)
        index = json.loads((root / "ARCHIVE.json").read_text())
        index.pop("directory_metadata_dependencies", None)
        (root / "ARCHIVE.json").write_text(json.dumps(index) + "\n", encoding="utf-8")
        lines = (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
        (root / "SHA256SUMS").write_text(
            "\n".join(
                hash_file(root / "ARCHIVE.json") + "  ARCHIVE.json"
                if line.endswith("  ARCHIVE.json")
                else line
                for line in lines
            )
            + "\n",
            encoding="utf-8",
        )

    def payload_replica(self, bundle):
        root, _, refs = recovery.inspect(bundle)
        payload = next(
            ref["package_id"]
            for ref in refs
            if recovery.validate_receipt(root, ref, hash_payload=False)[0]["logical_bytes"]
        )
        media = self.base / "media"
        media.mkdir()
        destination = self.app.call(
            "destination", {"path": str(media), "kind": "disk", "label": "Fixture"}
        )
        arguments = {"bundle": bundle, "destination": destination["id"], "packages": [payload]}
        review = self.app.call("preflight_copy", arguments)
        copied = self.app.call("copy", {**arguments, "approval": review["approval"]})
        return copied["path"], payload

    def test_payload_only_replica_search_reports_missing_directory_metadata(self):
        self.file("Project/file.txt", b"preserve")
        (self.source / "Project/empty").mkdir()
        built = self.build()
        index = json.loads((Path(built["path"]) / "ARCHIVE.json").read_text())
        replica, payload = self.payload_replica(built["path"])
        required = index["directory_metadata_dependencies"][payload]
        self.assertTrue(required)
        found = self.app.call("recovery_find", {"bundle": replica, "query": "Project/file.txt"})
        self.assertEqual(found["metadata_completeness"], "missing")
        self.assertEqual(found["missing_metadata_package_ids"], required)
        self.assertEqual(found["required_metadata_package_ids"], required)
        self.assertEqual(found["package_ids"], [payload])
        self.assertEqual(found["metadata_package_ids"], [])
        self.assertIn("missing", found["restore_scope"])
        output = self.base / "restored-subset"
        recovery.run(replica, output, found["package_ids"])
        namespace = index["sources"][0]["namespace"]
        self.assertTrue((output / namespace / "Project/file.txt").is_file())
        self.assertFalse((output / namespace / "Project/empty").exists())

    def test_legacy_partial_search_does_not_claim_complete_metadata(self):
        self.file("Project/file.txt", b"preserve")
        built = self.build()
        replica, payload = self.payload_replica(built["path"])
        self.legacy_catalogue(replica)
        found = self.app.call("recovery_find", {"bundle": replica, "query": "Project/file.txt"})
        self.assertEqual(found["metadata_completeness"], "unknown")
        self.assertEqual(found["missing_metadata_package_ids"], [])
        self.assertEqual(found["package_ids"], [payload])
        self.assertIn("unverified", found["restore_scope"])

    def test_legacy_complete_search_includes_available_directory_metadata(self):
        self.file("Project/file.txt", b"preserve")
        built = self.build()
        self.legacy_catalogue(built["path"])
        found = self.app.call(
            "recovery_find", {"bundle": built["path"], "query": "Project/file.txt"}
        )
        self.assertEqual(found["metadata_completeness"], "complete")
        self.assertTrue(found["metadata_package_ids"])
        self.assertEqual(found["missing_metadata_package_ids"], [])
        self.assertEqual(
            set(found["package_ids"]),
            set(found["matched_package_ids"]) | set(found["metadata_package_ids"]),
        )

    def test_declared_metadata_closure_for_partial_set_can_be_complete(self):
        self.file("First/file.txt", b"first")
        self.file("Second/file.txt", b"second")
        plan = self.plan()
        packages = self.app.call("packages", {"plan_id": plan["id"]})["packages"]
        payload = next(
            row["id"] for row in packages if row["kind"] == "data" and row["anchor"] == "First"
        )
        built = self.build(plan, packages=[payload])
        found = self.app.call("recovery_find", {"bundle": built["path"], "query": "First/file.txt"})
        self.assertEqual(found["archive_set_scope"], "PARTIAL_PLAN")
        self.assertEqual(found["metadata_completeness"], "complete")
        self.assertTrue(found["metadata_package_ids"])
        self.assertEqual(found["missing_metadata_package_ids"], [])
