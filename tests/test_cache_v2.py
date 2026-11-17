"""Bounded path caches must not change SQLite identity or archival decisions."""

import sys
import unittest
from contextlib import ExitStack
from unittest import mock

from test_core import Fixture
from archivist.inventory import InventoryBuilder
from archivist.path_cache import PathCache
from archivist.progress import Progress
from archivist.store import Store
from archivist.util import Problem


class CacheBudgetTests(unittest.TestCase):
    def test_lru_eviction_and_mapping_iteration(self):
        cache = PathCache(max_entries=2, max_bytes=4096)
        cache["a"] = 1
        cache["b"] = 2
        self.assertEqual(cache["a"], 1)
        cache["c"] = 3
        self.assertNotIn("b", cache)
        self.assertEqual(dict(cache), {"a": 1, "c": 3})
        self.assertEqual(list(cache.values()), [1, 3])
        self.assertEqual(
            cache.accounted_bytes,
            sum(sys.getsizeof(k) + sys.getsizeof(v) for k, v in cache.items()),
        )
        cache.clear()
        self.assertEqual((len(cache), cache.accounted_bytes), (0, 0))

    def test_byte_budget_and_oversized_replacement_never_keep_stale_value(self):
        cost = sys.getsizeof(1) + sys.getsizeof("x" * 100)
        cache = PathCache(max_entries=50, max_bytes=cost)
        cache[1] = "x" * 100
        cache[2] = "y" * 100
        self.assertNotIn(1, cache)
        self.assertEqual(cache.accounted_bytes, cost)
        cache[2] = "z" * 1000
        self.assertNotIn(2, cache)
        self.assertEqual(cache.accounted_bytes, 0)

    def test_defaults_are_finite_and_cache_may_be_disabled(self):
        cache = PathCache()
        self.assertEqual((cache.max_entries, cache.max_bytes), (8192, 8 * 1024 * 1024))
        disabled = PathCache(max_entries=0)
        disabled["path"] = 1
        self.assertEqual(len(disabled), 0)
        for limits in ({"max_entries": -1}, {"max_bytes": float("inf")}, {"max_entries": True}):
            with self.subTest(limits=limits), self.assertRaises(ValueError):
                PathCache(**limits)
        with self.assertRaises(TypeError):
            cache["path"] = []


class PathCacheBehaviorTests(Fixture):
    def test_ensure_dir_survives_eviction_and_long_uncached_paths(self):
        with Store(self.workspace) as store:
            builder = InventoryBuilder(
                store, str(self.source), "Cache test", "fixture", {}, Progress()
            )
            builder.dirs = PathCache(max_entries=2, max_bytes=160)
            wanted = "Case/子目录/" + "/".join(f"Level-{i:02d}" for i in range(40))
            original = builder.ensure_dir(wanted)
            lowercase = builder.ensure_dir("case")
            uppercase = builder.ensure_dir("Case")
            self.assertNotEqual(lowercase, uppercase)
            for number in range(30):
                builder.ensure_dir(f"Other-{number:03d}/Nested")
            before = store.db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            self.assertEqual(builder.ensure_dir(wanted), original)
            self.assertEqual(store.db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0], before)
            self.assertLessEqual(len(builder.dirs), 2)
            self.assertLessEqual(builder.dirs.accounted_bytes, 160)
            store._paths = PathCache(max_entries=1, max_bytes=100)
            self.assertEqual(store.path(original), wanted)
            self.assertEqual(store.path(lowercase), "case")
            self.assertEqual(store.path(uppercase), "Case")
            self.assertEqual(store.path(original), wanted)
            self.assertLessEqual(store._paths.accounted_bytes, 100)

    def test_disabled_cache_still_rejects_parent_cycle(self):
        with Store(self.workspace) as store:
            builder = InventoryBuilder(store, str(self.source), "Cycle", "fixture", {}, Progress())
            a = builder.ensure_dir("A")
            b = builder.ensure_dir("A/B")
            store.db.execute("UPDATE nodes SET parent=? WHERE id=?", (b, a))
            store._paths = PathCache(max_entries=0)
            with self.assertRaises(Problem) as problem:
                store.path(b)
            self.assertEqual(problem.exception.code, "PARENT_CYCLE")

    def test_eviction_preserves_inventory_fingerprint_and_exact_once_plan(self):
        for number in range(32):
            self.file(f"Sibling-{number:02d}/data.bin", b"data")
        for branch in range(4):
            parts = [f"Deep-{branch}"]
            for depth in range(32):
                parts.append(f"L{depth:02d}")
                self.file("/".join(parts) + "/note.txt", b"x")
        for name in ("Café/naïve.txt", "CaseA/value.txt", "caseB/value.txt"):
            self.file(name, b"case")
        (self.source / "Empty" / "Nested").mkdir(parents=True)
        expected = {""} | {p.relative_to(self.source).as_posix() for p in self.source.rglob("*")}

        with ExitStack() as contexts:
            contexts.enter_context(mock.patch("archivist.store.PathCache", dict))
            contexts.enter_context(mock.patch("archivist.inventory.PathCache", dict))
            reference = self.scan()
            reference_plan = self.plan(reference["snapshot_id"])

        def tiny_cache():
            return PathCache(max_entries=2, max_bytes=160)

        with ExitStack() as contexts:
            contexts.enter_context(mock.patch("archivist.store.PathCache", tiny_cache))
            contexts.enter_context(mock.patch("archivist.inventory.PathCache", tiny_cache))
            evicting = self.scan()
            evicting_plan = self.plan(reference["snapshot_id"])
            with Store(self.workspace) as store:
                observed = {
                    store.path(row["id"])
                    for row in store.db.execute(
                        "SELECT id FROM nodes WHERE snapshot_id=?", (evicting["snapshot_id"],)
                    )
                }
                membership = store.db.execute(
                    "SELECT COUNT(*),COUNT(DISTINCT node_id) FROM members WHERE plan_id=?",
                    (evicting_plan["id"],),
                ).fetchone()

        self.assertEqual(observed, expected)
        self.assertEqual(reference["fingerprint"], evicting["fingerprint"])
        self.assertEqual(reference["counts"], evicting["counts"])
        self.assertEqual(reference_plan["fingerprint"], evicting_plan["fingerprint"])
        self.assertEqual(reference_plan["counts"], evicting_plan["counts"])
        self.assertTrue(evicting_plan["counts"]["exact_once"])
        self.assertEqual(tuple(membership), (len(expected), len(expected)))


if __name__ == "__main__":
    unittest.main()
