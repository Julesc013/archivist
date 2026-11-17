"""Read-only migration of evidence produced by the actual old application."""

import json
import shutil
from test_core import Fixture, ROOT
from archivist.store import Store
from archivist.util import hash_file


class LegacyMigrationTests(Fixture):
    def test_actual_v13_fixture_preserves_files_and_reuses_identity(self):
        old = self.base / "old-results"
        shutil.copytree(ROOT / "tests/fixtures/legacy-v13", old)
        before = {
            p.relative_to(old).as_posix(): hash_file(p) for p in old.rglob("*") if p.is_file()
        }
        result = self.app.call("migrate", {"input": str(old)})
        self.assertEqual(len(result["inventories"]), 1)
        self.assertEqual(len(result["plans"]), 1)
        sid = result["inventories"][0]["snapshot_id"]
        pid = result["plans"][0]["plan_id"]
        with Store(self.workspace) as db:
            scan = db.need("snapshots", sid)
            self.assertTrue(
                json.loads(db.need("sources", scan["source_id"])["identity"])["unbound"]
            )
            files = [
                (db.path(r["id"]), r["size"])
                for r in db.rows(
                    "SELECT id,size FROM nodes WHERE snapshot_id=? AND kind='file'", (sid,)
                )
            ]
            assigned = db.db.execute(
                "SELECT count(*) FROM members m JOIN nodes n ON n.id=m.node_id WHERE m.plan_id=? AND n.kind='file'",
                (pid,),
            ).fetchone()[0]
        self.assertEqual(files, [("Photos/note.txt", 15)])
        self.assertEqual(assigned, 1)
        self.assertEqual(self.app.call("packages", {"plan_id": pid})["plan"]["counts"]["files"], 1)
        again = self.app.call("migrate", {"input": str(old)})
        self.assertTrue(again["inventories"][0]["reused"])
        self.assertTrue(again["plans"][0]["reused"])
        self.assertEqual(
            before,
            {p.relative_to(old).as_posix(): hash_file(p) for p in old.rglob("*") if p.is_file()},
        )
        self.plan(sid)

    def test_legacy_tampering_is_rejected_before_migration(self):
        old = self.base / "old-results"
        shutil.copytree(ROOT / "tests/fixtures/legacy-v13", old)
        descriptor = next(old.glob("*/inventory.json"))
        descriptor.write_text(descriptor.read_text() + " ")
        self.assert_problem("LEGACY_HASH", "migrate", {"input": str(old)})

    def test_explicit_source_id_cannot_silently_bind_another_root(self):
        self.scan()
        source_id = self.app.call("scans")[0]["source_id"]
        other = self.base / "other"
        other.mkdir()
        self.assert_problem(
            "SOURCE_BINDING",
            "scan",
            {"root": str(other), "source_id": source_id, "backend": "filesystem"},
        )

    def test_indexed_hash_request_is_not_silently_ignored(self):
        self.assert_problem(
            "INDEX_HASH_MODE",
            "scan",
            {"root": str(self.source), "backend": "everything", "hash_files": True},
        )
