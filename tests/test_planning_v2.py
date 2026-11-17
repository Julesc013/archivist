"""Regression evidence for planning, revision, and execution-budget boundaries."""

import json
from pathlib import Path

from test_core import Fixture
from archivist import capacity, planning, recovery
from archivist.progress import Progress
from archivist.store import Store
from archivist.util import Problem, hash_file


class PlanningV2Tests(Fixture):
    def package_rows(self, plan):
        return self.app.call("packages", {"plan_id": plan["id"]})["packages"]

    def test_root_direct_files_keep_directory_cohesion_below_maximum(self):
        for name in ("readme.txt", "image.jpg", "data.bin"):
            self.file(name, b"x" * 12_000)
        scan = self.scan()["snapshot_id"]
        plan = self.plan(scan, target=30_000, maximum=100_000)
        payload = [row for row in self.package_rows(plan) if row["kind"] == "data"]
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["file_count"], 3)
        # The maximum remains hard even when directory cohesion exceeds target.
        blocked = self.plan(scan, target=16_000, maximum=16_384)
        self.assertGreater(blocked["counts"]["blocked_packages"], 0)

    def test_repeating_same_observation_and_policy_has_same_decisions(self):
        self.file("Project/a.txt", b"a" * 4_000)
        self.file("Project/b.bin", b"b" * 4_000)
        snapshot = self.scan()["snapshot_id"]
        first, second = self.plan(snapshot), self.plan(snapshot)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(first["fingerprint"], second["fingerprint"])

        def decisions(plan):
            return [
                {k: value for k, value in row.items() if k != "plan_id"}
                for row in self.package_rows(plan)
            ]

        self.assertEqual(decisions(first), decisions(second))

    def test_codec_revision_keeps_grouping_reason(self):
        self.file("Project/readme.txt", b"x" * 1000)
        plan = self.plan()
        package = next(row for row in self.package_rows(plan) if row["kind"] == "data")
        change = {package["id"]: {"codec": "gzip", "level": 6}}
        revised = self.app.call("revise", {"plan_id": plan["id"], "codec_changes": change})
        current = next(row for row in self.package_rows(revised) if row["id"] == package["id"])
        self.assertEqual(current["reason"], package["reason"])
        self.assertEqual(current["logical_id"], package["logical_id"])
        self.assertEqual(current["codec"], "gzip")
        self.assertEqual(revised["provenance"]["codec_changes"], change)
        self.assertEqual(
            self.app.call("packages", {"plan_id": plan["id"]})["plan"]["fingerprint"],
            plan["fingerprint"],
        )

    def test_revert_creates_child_and_preserves_current_and_target(self):
        self.file("Project/a.txt", b"a")
        self.file("Project/b.txt", b"b")
        target = self.plan()
        package = next(row for row in self.package_rows(target) if row["kind"] == "data")
        member = self.app.call("members", {"plan_id": target["id"], "package_id": package["id"]})[
            "rows"
        ][0]
        current = self.app.call(
            "revise", {"plan_id": target["id"], "move": {"node_ids": [member["id"]]}}
        )
        original_rows, current_rows = self.package_rows(target), self.package_rows(current)
        with Store(self.workspace) as store:
            restored = planning.revert_plan(store, current["id"], target["id"], Progress())
        self.assertEqual(restored["parent_plan"], current["id"])
        self.assertEqual(restored["provenance"]["reverted_to"], target["id"])
        self.assertEqual(restored["fingerprint"], target["fingerprint"])
        self.assertTrue(restored["counts"]["exact_once"])
        self.assertEqual(self.package_rows(target), original_rows)
        self.assertEqual(self.package_rows(current), current_rows)

    def test_revert_cannot_change_observation_set(self):
        self.file("x", b"x")
        target = self.plan()
        self.file("y", b"y")
        current = self.plan()
        with Store(self.workspace) as store:
            count = store.db.execute("SELECT count(*) FROM plans").fetchone()[0]
            with self.assertRaises(Problem) as caught:
                planning.revert_plan(store, current["id"], target["id"], Progress())
            self.assertEqual(caught.exception.code, "REVERT_SCOPE")
            self.assertEqual(store.db.execute("SELECT count(*) FROM plans").fetchone()[0], count)

    def test_measured_allocation_matches_copy_preflight_at_capacity_boundary(self):
        self.file("Project/payload.bin", b"x" * (8 * 1024 * 1024))
        plan = self.plan(target=10 * 1024 * 1024, maximum=12 * 1024 * 1024, codec="gzip")
        built = self.build(plan)
        media = [{"id": "bounded-disk", "capacity": 5 * 1024 * 1024}]
        allocation = self.app.call("allocate", {"plan_id": plan["id"], "media": media})
        self.assertEqual(allocation["measurement"]["basis"], "measured")
        self.assertEqual(allocation["unallocated"], [])
        required = allocation["media"][0]["used"]
        self.assertGreater(required, capacity.COPY_SET_ALLOWANCE_BYTES)
        destination = self.app.call(
            "destination",
            {
                "path": str(self.base / "disk"),
                "label": "Exact budget",
                "capacity": required,
            },
        )
        review = self.app.call(
            "preflight_copy",
            {
                "bundle": built["path"],
                "destination": destination["id"],
            },
        )
        self.assertEqual(review["estimated_additional_bytes"], required)
        # One byte below the shared boundary must not be called a fitting plan.
        too_small = self.app.call(
            "allocate",
            {
                "plan_id": plan["id"],
                "media": [{"id": "small", "capacity": required - 1}],
            },
        )
        self.assertNotEqual(too_small["unallocated"], [])

    def test_unbuilt_allocation_explains_metadata_estimates(self):
        self.file("x", b"x")
        plan = self.plan()
        result = self.app.call(
            "allocate",
            {
                "plan_id": plan["id"],
                "media": [{"id": "disk", "capacity": 10 * 1024 * 1024}],
            },
        )
        self.assertEqual(result["measurement"]["basis"], "estimated")
        self.assertTrue(all(row["basis"] == "estimated" for row in result["package_footprints"]))
        self.assertTrue(
            all(
                row["receipt_bytes"] > 0 and row["manifest_bytes"] > 0
                for row in result["package_footprints"]
            )
        )
        self.assertEqual(
            result["media"][0]["set_allowance_bytes"], capacity.COPY_SET_ALLOWANCE_BYTES
        )

    def test_fitting_media_and_exact_copy_selection_report_missing_metadata(self):
        self.file("Project/payload.bin", b"x" * 65536)
        plan = self.plan()
        rows = self.package_rows(plan)
        payload = next(row for row in rows if row["kind"] == "data")
        metadata = next(row for row in rows if row["kind"] == "directories")
        sizes = {row["id"]: capacity.estimated_footprint(row)["package_bytes"] for row in rows}
        media = [
            {"id": "payload", "capacity": capacity.COPY_SET_ALLOWANCE_BYTES + sizes[payload["id"]]},
            {
                "id": "metadata",
                "capacity": capacity.COPY_SET_ALLOWANCE_BYTES + sizes[metadata["id"]],
            },
        ]
        allocated = self.app.call("allocate", {"plan_id": plan["id"], "media": media})
        self.assertEqual(allocated["unallocated"], [])
        self.assertFalse(allocated["metadata_dependencies_complete"])
        first, second = allocated["media"]
        self.assertEqual(first["packages"], [payload["id"]])
        self.assertEqual(second["packages"], [metadata["id"]])
        self.assertEqual(first["required_metadata_package_ids"], [metadata["id"]])
        self.assertEqual(first["missing_metadata_package_ids"], [metadata["id"]])
        self.assertEqual(first["metadata_completeness"], "missing")
        self.assertEqual(second["missing_metadata_package_ids"], [])
        self.assertEqual(first["used"], media[0]["capacity"])
        self.assertEqual(second["used"], media[1]["capacity"])

        built = self.build(plan)
        destination = self.app.call(
            "destination", {"path": str(self.base / "disk"), "label": "Selection"}
        )
        args = {
            "bundle": built["path"],
            "destination": destination["id"],
            "packages": [payload["id"]],
        }
        review = self.app.call("preflight_copy", args)
        self.assertEqual(review["packages"], [payload["id"]])
        self.assertEqual(review["metadata_completeness"], "missing")
        self.assertEqual(review["missing_metadata_package_ids"], [metadata["id"]])
        complete = self.app.call(
            "preflight_copy", {**args, "packages": [row["id"] for row in rows]}
        )
        self.assertEqual(complete["metadata_completeness"], "complete")

        # An otherwise consistent older catalogue cannot supply the declaration
        # without reading manifests; copy review must state that uncertainty.
        root = Path(built["path"])
        index = json.loads((root / "ARCHIVE.json").read_text())
        index.pop("directory_metadata_dependencies")
        (root / "ARCHIVE.json").write_text(json.dumps(index) + "\n")
        seal = root / "SHA256SUMS"
        seal.write_text(
            "".join(
                hash_file(root / "ARCHIVE.json") + "  ARCHIVE.json\n"
                if line.endswith("  ARCHIVE.json\n")
                else line
                for line in seal.read_text().splitlines(keepends=True)
            )
        )
        legacy = self.app.call("preflight_copy", args)
        self.assertEqual(legacy["packages"], [payload["id"]])
        self.assertEqual(legacy["metadata_completeness"], "unknown")

    def test_invalid_available_build_does_not_silently_become_estimates(self):
        self.file("x", b"x")
        plan = self.plan()
        built = self.build(plan)
        path = Path(built["path"]) / "README.txt"
        path.write_text(path.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
        with self.assertRaises(recovery.RecoveryError):
            self.app.call(
                "allocate",
                {
                    "plan_id": plan["id"],
                    "media": [{"id": "disk", "capacity": 10 * 1024 * 1024}],
                },
            )

    def test_large_valid_recovery_kit_is_measured_and_subject_to_file_limit(self):
        self.file("x", b"x")
        plan = self.plan()
        built = self.build(plan)
        root = Path(built["path"])
        readme = root / "README.txt"
        readme.write_text(
            readme.read_text(encoding="utf-8") + "x" * (5 * 1024 * 1024), encoding="utf-8"
        )
        # Construct a consistent externally supplied kit. Its metadata is larger
        # than the old fixed allowance; no payload or executable is changed.
        seal = root / "SHA256SUMS"
        seal.write_text(
            "".join(
                hash_file(readme) + "  README.txt\n" if line.endswith("  README.txt\n") else line
                for line in seal.read_text(encoding="utf-8").splitlines(keepends=True)
            ),
            encoding="utf-8",
        )
        allocated = self.app.call(
            "allocate",
            {
                "plan_id": plan["id"],
                "media": [{"id": "disk", "capacity": 20 * 1024 * 1024}],
            },
        )
        kit = allocated["measurement"]["recovery_kit"]
        self.assertGreater(kit["recovery_kit_bytes"], capacity.COPY_SET_ALLOWANCE_BYTES)
        self.assertEqual(allocated["media"][0]["recovery_kit_bytes"], kit["recovery_kit_bytes"])
        destination = self.app.call(
            "destination",
            {
                "path": str(self.base / "disk"),
                "label": "Measured metadata",
                "capacity": allocated["media"][0]["used"],
            },
        )
        reviewed = self.app.call(
            "preflight_copy", {"bundle": str(root), "destination": destination["id"]}
        )
        self.assertEqual(reviewed["estimated_additional_bytes"], allocated["media"][0]["used"])
        limited = self.app.call(
            "allocate",
            {
                "plan_id": plan["id"],
                "media": [
                    {"id": "small-file", "capacity": 20 * 1024 * 1024, "max_file": 1024 * 1024}
                ],
            },
        )
        self.assertEqual(len(limited["unallocated"]), plan["counts"]["packages"])

    def test_selected_build_does_not_require_unrelated_source_online(self):
        self.file("x", b"x")
        first = self.scan()["snapshot_id"]
        other = self.base / "other"
        other.mkdir()
        (other / "y").write_bytes(b"y")
        second = self.app.call("scan", {"root": str(other), "backend": "filesystem"})["snapshot_id"]
        plan = self.app.call(
            "plan",
            {
                "snapshots": [first, second],
                "policy": {"minimum": 0, "target": 100_000, "maximum": 200_000, "codec": "none"},
            },
        )
        package = next(
            row
            for row in self.package_rows(plan)
            if row["snapshot_id"] == first and row["kind"] == "data"
        )
        offline = self.base / "offline"
        other.rename(offline)
        args = {
            "plan_id": plan["id"],
            "packages": [package["id"]],
            "output": str(self.base / "selected"),
        }
        review = self.app.call("preflight_build", args)
        self.assertEqual(len(review["source_roots"]), 1)
        self.assertEqual(review["capacity_breakdown"]["mode"], "retained-build")
        built = self.app.call("build", {**args, "approval": review["approval"]})
        self.assertEqual(built["state"], "PARTIAL_PLAN")
        index = json.loads((Path(built["path"]) / "ARCHIVE.json").read_text())
        self.assertEqual(len(index["packages"]), 2)  # Selected payload and directory metadata.
