"""Physical metadata replication and concrete per-medium copy selections."""

from __future__ import annotations

import json
from pathlib import Path

from test_core import Fixture
from archivist import capacity, planning
from archivist.store import Store


class AllocationClosureTests(Fixture):
    def test_measured_metadata_is_copied_and_charged_on_each_medium(self):
        self.file("A/file.bin", b"a" * 65536)
        self.file("B/file.bin", b"b" * 65536)
        plan = self.plan()
        built = self.build(plan)
        with Store(self.workspace) as store:
            packages, measurement = planning.allocation_packages(store, plan["id"])
            before = store.rows(
                "SELECT * FROM members WHERE plan_id=? ORDER BY node_id", (plan["id"],)
            )
        metadata = next(row for row in packages if row["kind"] == "directories")
        payloads = [row for row in packages if row["kind"] == "data"]
        kit = measurement["recovery_kit"]["recovery_kit_bytes"] + capacity.COPY_SET_ALLOWANCE_BYTES
        media = [
            {
                "id": "medium-" + str(n),
                "capacity": kit + row["allocation_bytes"] + metadata["allocation_bytes"],
            }
            for n, row in enumerate(payloads)
        ]
        result = self.app.call("allocate", {"plan_id": plan["id"], "media": media})
        self.assertEqual(result["unallocated"], [])
        self.assertTrue(result["metadata_dependencies_complete"])
        self.assertEqual(result["physical_replication"]["additional_metadata_copies"], 1)
        self.assertEqual(
            result["physical_replication"]["additional_metadata_bytes"],
            metadata["allocation_bytes"],
        )
        self.assertEqual(result["physical_replication"]["physical_package_copies"], 4)
        for medium in result["media"]:
            self.assertEqual(len(medium["payload_package_ids"]), 1)
            self.assertEqual(medium["directory_metadata_package_ids"], [metadata["id"]])
            self.assertEqual(medium["replicated_metadata_package_ids"], [metadata["id"]])
            self.assertEqual(medium["metadata_completeness"], "complete")
            self.assertEqual(medium["missing_metadata_package_ids"], [])
            self.assertEqual(medium["used"], medium["capacity"])
            destination = self.app.call(
                "destination",
                {
                    "path": str(self.base / medium["id"]),
                    "label": medium["id"],
                    "capacity": medium["capacity"],
                },
            )
            arguments = {
                "bundle": built["path"],
                "destination": destination["id"],
                "packages": medium["packages"],
            }
            reviewed = self.app.call("preflight_copy", arguments)
            self.assertEqual(reviewed["estimated_additional_bytes"], medium["used"])
            self.assertEqual(reviewed["metadata_completeness"], "complete")
            copied = self.app.call("copy", {**arguments, "approval": reviewed["approval"]})
            self.assertEqual(copied["verification"]["state"], "CONTENTS_VERIFIED")
            self.assertEqual(copied["verification"]["scope"], "PARTIAL_PLAN")
        with Store(self.workspace) as store:
            after = store.rows(
                "SELECT * FROM members WHERE plan_id=? ORDER BY node_id", (plan["id"],)
            )
        self.assertEqual(before, after)
        together = self.app.call(
            "allocate",
            {
                "plan_id": plan["id"],
                "media": [
                    {
                        "id": "one",
                        "capacity": kit + sum(row["allocation_bytes"] for row in packages),
                    }
                ],
            },
        )
        self.assertEqual(together["unallocated"], [])
        self.assertEqual(together["physical_replication"]["additional_metadata_bytes"], 0)
        self.assertEqual(together["media"][0]["packages"], sorted(row["id"] for row in packages))

    def test_dependency_maximum_file_size_is_checked_before_payload_placement(self):
        result = planning.allocate(
            [
                {"id": "P000001", "allocation_bytes": 20, "largest_file_bytes": 20},
                {"id": "P000002", "allocation_bytes": 100, "largest_file_bytes": 90},
            ],
            [
                {"id": "limited", "capacity": 1000, "max_file": 50},
                {"id": "compatible", "capacity": 125, "max_file": 100},
            ],
            5,
            dependencies={"P000001": ["P000002"]},
            metadata_package_ids=["P000002"],
        )
        self.assertEqual(result["media"][0]["packages"], [])
        self.assertEqual(result["media"][1]["packages"], ["P000001", "P000002"])
        self.assertEqual(result["media"][1]["used"], 125)
        self.assertEqual(result["unallocated"], [])

    def test_mixed_measurements_reuse_measured_metadata_without_compression_predictions(self):
        self.file("A/file.bin", b"a" * 65536)
        self.file("B/file.bin", b"b" * 65536)
        plan = self.plan(codec="gzip")
        original = self.app.call("packages", {"plan_id": plan["id"]})["packages"]
        first = next(row for row in original if row["kind"] == "data" and row["anchor"] == "A")
        self.build(plan, packages=[first["id"]])
        with Store(self.workspace) as store:
            packages, measurement = planning.allocation_packages(store, plan["id"])
        self.assertEqual(measurement["basis"], "mixed")
        metadata = next(row for row in packages if row["kind"] == "directories")
        self.assertEqual(metadata["footprint"]["basis"], "measured")
        unbuilt = next(
            row for row in packages if row["kind"] == "data" and row["id"] != first["id"]
        )
        self.assertEqual(unbuilt["footprint"]["basis"], "estimated")
        self.assertEqual(unbuilt["footprint"]["artifact_bytes"], unbuilt["estimated_bytes"])
        kit = measurement["recovery_kit"]["recovery_kit_bytes"] + capacity.COPY_SET_ALLOWANCE_BYTES
        media = [
            {
                "id": row["id"],
                "capacity": kit + row["allocation_bytes"] + metadata["allocation_bytes"],
            }
            for row in packages
            if row["kind"] == "data"
        ]
        result = self.app.call("allocate", {"plan_id": plan["id"], "media": media})
        self.assertEqual(result["unallocated"], [])
        self.assertTrue(result["metadata_dependencies_complete"])
        self.assertEqual(
            result["physical_replication"]["additional_metadata_bytes"],
            metadata["allocation_bytes"],
        )

    def test_source_with_only_empty_directories_has_a_complete_copy_selection(self):
        (self.source / "empty").mkdir()
        plan = self.plan()
        built = self.build(plan)
        allocated = self.app.call(
            "allocate",
            {"plan_id": plan["id"], "media": [{"id": "medium", "capacity": 10 * 1024 * 1024}]},
        )
        self.assertTrue(allocated["metadata_dependencies_complete"])
        self.assertEqual(allocated["media"][0]["payload_package_ids"], [])
        ids = allocated["media"][0]["packages"]
        self.assertTrue(ids)
        index = json.loads((Path(built["path"]) / "ARCHIVE.json").read_text())
        self.assertEqual(index["directory_metadata_packages"], ids)
        destination = self.app.call(
            "destination", {"path": str(self.base / "medium"), "label": "Empty tree"}
        )
        reviewed = self.app.call(
            "preflight_copy",
            {"bundle": built["path"], "destination": destination["id"], "packages": ids},
        )
        self.assertEqual(reviewed["packages"], ids)
        self.assertEqual(reviewed["metadata_completeness"], "complete")
