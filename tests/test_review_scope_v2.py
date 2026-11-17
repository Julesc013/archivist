"""Preflight and execution must describe the same selected verification scope."""

from pathlib import Path

from test_core import Fixture
from archivist import recovery


class ReviewScopeTests(Fixture):
    def test_restore_review_is_not_complete_for_selected_payload(self):
        self.file("A/one.txt")
        self.file("B/two.txt")
        plan = self.plan()
        built = self.build(plan)
        package = next(
            p
            for p in self.app.call("packages", {"plan_id": plan["id"]})["packages"]
            if p["kind"] == "data"
        )
        selection = [package["id"]]
        review = self.app.call(
            "preflight_restore",
            {"bundle": built["path"], "packages": selection, "output": str(self.base / "restore")},
        )
        checked = recovery.run(Path(built["path"]), packages=selection)
        for key in ("scope", "archive_set_scope", "verification_selection_scope"):
            self.assertEqual(review[key], checked[key])
        self.assertEqual(review["scope"], "PARTIAL_PLAN")
        self.assertEqual(review["verification_selection_scope"], "SELECTED_PACKAGES")
