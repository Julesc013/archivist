#!/usr/bin/env python3
"""Bounded synthetic scaling evidence in fresh processes; no live indexing or media.

Creates all test sources/workspaces inside its own TemporaryDirectory and removes
only that directory. The JSON report is the only persistent output. Timings are
single samples on a shared host, not a performance guarantee or million-file test.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = {
    "minimum": 10_000_000_000,
    "target": 100_000_000_000,
    "maximum": 200_000_000_000,
    "codec": "none",
}


def rss():
    current = None
    try:
        pages = int(Path("/proc/self/statm").read_text().split()[1])
        current = pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError, AttributeError):
        pass
    peak = None
    try:
        import resource

        raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak = int(raw if sys.platform == "darwin" else raw * 1024)
    except ImportError:
        pass
    return {"current_rss_bytes": current, "peak_rss_bytes": peak}


def filesystem_facts(path):
    resolved = Path(path).resolve()
    answer = {"path": str(resolved), "device": resolved.stat().st_dev}
    if hasattr(os, "statvfs"):
        values = os.statvfs(resolved)
        answer.update(block_size=values.f_bsize, fragment_size=values.f_frsize)
    try:
        best = None
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            left, right = line.split(" - ", 1)
            fields = left.split()
            mount = Path(fields[4].replace("\\040", " "))
            if resolved.is_relative_to(mount) and (
                best is None or len(str(mount)) > len(best["mount"])
            ):
                best = {"mount": str(mount), "filesystem_type": right.split()[0]}
        if best:
            answer.update(best)
    except (OSError, ValueError, IndexError):
        pass
    return answer


def environment(path):
    cpu = None
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version,
        "sqlite": sqlite3.sqlite_version,
        "cpu_model_reported": cpu or platform.processor() or None,
        "logical_cpus_visible": os.cpu_count(),
        "cpu_affinity_count": len(os.sched_getaffinity(0))
        if hasattr(os, "sched_getaffinity")
        else None,
        "filesystem": filesystem_facts(path),
        "isolation": "Fresh Python workers; shared host and uncontrolled concurrent load; no cold-cache flush.",
    }


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def fixture(spec, directory):
    """Create deterministic synthetic input outside the timed application phases."""
    started = time.perf_counter()
    expected_bytes = 0
    if spec["mode"] == "filesystem":
        source = directory / "source"
        source.mkdir()
        content = b"0123456789abcdef" * 64
        for group in range(2000):
            folder = source / f"Directory-{group:05d}"
            folder.mkdir()
            for member in range(5):
                (folder / f"file-{member}.bin").write_bytes(content)
                expected_bytes += len(content)
        return {
            **spec,
            "input": str(source),
            "expected_files": 10000,
            "expected_directories": 2001,
            "expected_bytes": expected_bytes,
            "source_create_seconds": time.perf_counter() - started,
            "filesystem": filesystem_facts(source),
            "shape": "2,000 direct child directories, five 1 KiB files each; 10,000 files; recently created and cache-warm; no content hashing during scan.",
            "policy": {**DEFAULT_POLICY, "minimum": 0},
        }
    export = directory / "fixture.efu"
    expected_files = spec["files"]
    expected_directories = 0
    with export.open("w", encoding="utf-8", newline="") as stream:
        output = csv.writer(stream)
        output.writerow(["Filename", "Size", "Date Modified", "Attributes"])
        if spec["shape_name"] == "fixed_tree":
            expected_directories = 1126
            for i in range(expected_files):
                extension = [
                    "txt",
                    "jpg",
                    "iso",
                    "json",
                    "mp4",
                    "bin",
                    "flac",
                    "zip",
                    "py",
                    "unknown",
                ][i % 10]
                name = f"D:\\Collection{i % 25:02d}\\Group{i % 100:03d}\\Project{i % 1000:04d}\\record-{i:08d}.{extension}"
                size = 1000 + (i * 7919) % 100_000_000
                output.writerow([name, size, "133000000000000000", 32])
                expected_bytes += size
            shape = "25 collections / 100 groups / 1,000 projects; fixed 1,126 directories including root; mixed suffixes; synthetic sizes of 1,000 to 100,000,999 bytes."
        elif spec["shape_name"] == "broad":
            expected_directories = 1 + 150 + expected_files
            for i in range(expected_files):
                name = f"D:\\Bucket{i // 200:03d}\\Directory{i:06d}\\file.bin"
                output.writerow([name, 128, "133000000000000000", 32])
                expected_bytes += 128
            shape = "150 bucket directories, 200 single-file child directories per bucket; 30,000 files and 30,151 directories including root; root/bucket/directory hierarchy."
        else:
            expected_directories = 1 + 32 + 32 * 256
            for branch in range(32):
                parts = [f"Branch{branch:02d}"]
                for depth in range(256):
                    parts.append(f"L{depth:03d}")
                    name = "D:\\" + "\\".join(parts) + "\\file.bin"
                    output.writerow([name, 128, "133000000000000000", 32])
                    expected_bytes += 128
            shape = "32 independent branches, each 256 nested directories with one 128-byte file at every level; 8,192 files / 8,225 directories including root; maximum 257 directory components."
    return {
        **spec,
        "input": str(export),
        "expected_files": expected_files,
        "expected_directories": expected_directories,
        "expected_bytes": expected_bytes,
        "input_bytes": export.stat().st_size,
        "input_sha256": file_hash(export),
        "source_create_seconds": time.perf_counter() - started,
        "shape": shape,
        "policy": dict(DEFAULT_POLICY),
    }


def query_timing(app, action, arguments):
    started = time.perf_counter()
    answer = app.call(action, arguments)
    duration = time.perf_counter() - started
    if isinstance(answer, dict) and ("packages" in answer or "rows" in answer):
        count = len(answer.get("packages", answer.get("rows", [])))
        response_kind = "page"
    elif isinstance(answer, dict):
        count = None
        response_kind = "object"
    else:
        count = len(answer)
        response_kind = "list"
    return {"seconds": duration, "rows_returned": count, "response_kind": response_kind}, answer


def application_worker(spec):
    sys.path.insert(0, str(ROOT))
    from archivist.application import Application
    from archivist.store import Store

    workspace = Path(spec["workspace"])
    app = Application(workspace)
    memory = {"before_acquisition": rss()}
    start = time.perf_counter()
    if spec["mode"] == "filesystem":
        observation = app.call(
            "scan", {"root": spec["input"], "backend": "filesystem", "label": spec["name"]}
        )
    else:
        observation = app.call(
            "import_efu", {"input": spec["input"], "root": "D:\\", "label": spec["name"]}
        )
    acquired = time.perf_counter()
    memory["after_acquisition"] = rss()
    plan = app.call("plan", {"snapshots": [observation["snapshot_id"]], "policy": spec["policy"]})
    planned = time.perf_counter()
    memory["after_plan"] = rss()
    queries = {}
    queries["first_package_page"], first = query_timing(
        app, "packages", {"plan_id": plan["id"], "limit": 100}
    )
    last_offset = ((first["total"] - 1) // 100) * 100 if first["total"] else 0
    queries["last_package_page"], _ = query_timing(
        app, "packages", {"plan_id": plan["id"], "limit": 100, "offset": last_offset}
    )
    if first["packages"]:
        package = first["packages"][0]["id"]
        queries["package_detail"], _ = query_timing(
            app, "package", {"plan_id": plan["id"], "package_id": package}
        )
        queries["first_member_page"], _ = query_timing(
            app, "members", {"plan_id": plan["id"], "package_id": package, "limit": 100}
        )
    memory["after_queries"] = rss()
    with Store(workspace, create=False) as store:
        actual = store.one(
            "SELECT SUM(kind='file') files, SUM(kind='directory') directories, SUM(CASE WHEN kind='file' THEN size ELSE 0 END) logical_bytes FROM nodes WHERE snapshot_id=?",
            (observation["snapshot_id"],),
        )
        included = store.db.execute(
            "SELECT COUNT(*) FROM members WHERE plan_id=?", (plan["id"],)
        ).fetchone()[0]
        state = store.one("SELECT state FROM snapshots WHERE id=?", (observation["snapshot_id"],))[
            "state"
        ]
    expected = {
        "files": spec["expected_files"],
        "directories": spec["expected_directories"],
        "logical_bytes": spec["expected_bytes"],
    }
    if actual != expected:
        raise AssertionError({"expected": expected, "actual": actual})
    result = {
        "acquisition_seconds": acquired - start,
        "plan_seconds": planned - acquired,
        "acquisition_state": state,
        "counts": actual,
        "counts_match_fixture": True,
        "plan_state": plan["state"],
        "packages": plan["counts"]["packages"],
        "recorded_members": included,
        "queries": queries,
        "memory": memory,
        "workspace_bytes": sum(
            item.stat().st_size for item in workspace.rglob("*") if item.is_file()
        ),
        "workspace_definition": "Sum of regular-file logical sizes after Store connections close; not allocated blocks and not source/payload bytes.",
    }
    return result


def cache_worker(spec):
    """Separate fresh-process diagnostic; does not contaminate acquisition RSS."""
    sys.path.insert(0, str(ROOT))
    from archivist.store import Store

    before = rss()
    started = time.perf_counter()
    with Store(spec["workspace"], create=False) as store:
        for row in store.db.execute("SELECT id FROM nodes WHERE kind='directory' ORDER BY id"):
            store.path(row["id"])
        elapsed = time.perf_counter() - started
        after = rss()
        paths = store._paths
        footprint = (
            paths.object_bytes
            if hasattr(paths, "object_bytes")
            else sys.getsizeof(paths)
            + sum(sys.getsizeof(key) + sys.getsizeof(value) for key, value in paths.items())
        )
        characters = sum(len(value) for value in paths.values())
        result = {
            "seconds": elapsed,
            "entries": len(paths),
            "path_characters": characters,
            "average_characters_per_directory": characters / len(paths) if paths else 0,
            "maximum_path_characters": max(map(len, paths.values()), default=0),
            "python_cache_object_bytes": footprint,
            "memory_before": before,
            "memory_after": after,
            "cache_limits": {
                "max_entries": paths.max_entries,
                "max_key_value_bytes": paths.max_bytes,
                "accounted_key_value_bytes": paths.accounted_bytes,
            }
            if hasattr(paths, "accounted_bytes")
            else None,
            "scope": "Explicitly visits every directory path in a separate fresh worker. Python dict/key/value getsizeof total is diagnostic object size, not an exclusive allocation or process-RSS measure. Does not measure InventoryBuilder.dirs separately.",
        }
    return result


def execute_worker(kind, spec_file, timeout):
    process = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker", kind, str(spec_file)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if process.returncode:
        raise RuntimeError(process.stderr[-5000:] or process.stdout[-5000:])
    return json.loads(process.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/validation/scaling-v2.json")
    parser.add_argument("--max-seconds", type=int, default=240)
    parser.add_argument("--worker", nargs=2, metavar=("KIND", "SPEC"))
    args = parser.parse_args()
    if args.worker:
        spec = json.loads(Path(args.worker[1]).read_text())
        function = application_worker if args.worker[0] == "application" else cache_worker
        print(json.dumps(function(spec)))
        return
    cases = [
        {"name": "efu-50000-fixed-tree", "mode": "efu", "shape_name": "fixed_tree", "files": 50000},
        {
            "name": "efu-100000-fixed-tree",
            "mode": "efu",
            "shape_name": "fixed_tree",
            "files": 100000,
        },
        {"name": "filesystem-10000-files-2000-dirs", "mode": "filesystem"},
        {
            "name": "efu-30000-broad-directories",
            "mode": "efu",
            "shape_name": "broad",
            "files": 30000,
        },
        {"name": "efu-8192-deep-directories", "mode": "efu", "shape_name": "deep", "files": 8192},
    ]
    started = time.monotonic()
    report = {
        "recorded_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "scope": "Single samples of bounded synthetic inventory/planning operations in fresh processes. No tape, live Everything, compression, restore throughput, native GUI, million-file scale or cold-cache performance claim.",
        "interpretation": "Compare the 50k/100k pair at fixed topology and policy. Other shapes intentionally vary directory ratio/depth and sometimes planning policy. Peak RSS is cumulative within each worker, not additive per phase.",
        "runs": [],
        "tested_source_sha256": {
            str(path.relative_to(ROOT)): file_hash(path)
            for path in [
                ROOT / "source/inventory.py",
                ROOT / "source/store.py",
                ROOT / "source/planning.py",
                ROOT / "source/application.py",
                ROOT / "source/path_cache.py",
            ]
            if path.exists()
        },
    }
    with tempfile.TemporaryDirectory(prefix="archivist-scaling-") as temporary:
        base = Path(temporary)
        report["environment"] = environment(base)
        for case in cases:
            directory = base / case["name"]
            directory.mkdir()
            spec = fixture(case, directory)
            spec["workspace"] = str(directory / "workspace")
            spec_file = directory / "case.json"
            spec_file.write_text(json.dumps(spec))
            remaining = args.max_seconds - (time.monotonic() - started)
            if remaining < 1:
                report["runs"].append({"name": case["name"], "status": "NOT_RUN_TIME_BUDGET"})
                break
            try:
                measurement = execute_worker("application", spec_file, min(90, remaining))
                remaining = args.max_seconds - (time.monotonic() - started)
                if remaining < 1:
                    raise TimeoutError("Time budget expired before cache diagnostic")
                cache = execute_worker("cache", spec_file, min(45, remaining))
                run = {
                    "name": case["name"],
                    "status": "COMPLETE",
                    "fixture": spec,
                    "measurement": measurement,
                    "directory_cache_probe": cache,
                }
            except (subprocess.TimeoutExpired, RuntimeError, TimeoutError) as exc:
                run = {
                    "name": case["name"],
                    "status": "INCOMPLETE",
                    "fixture": spec,
                    "error": str(exc),
                }
            report["runs"].append(run)
            print(
                json.dumps(
                    {
                        "case": run["name"],
                        "status": run["status"],
                        "measurement": run.get("measurement"),
                    }
                ),
                flush=True,
            )
        report["temporary_root_removed_after_run"] = str(base)
    report["temporary_root_exists_after_cleanup"] = Path(
        report["temporary_root_removed_after_run"]
    ).exists()
    report["elapsed_total_seconds"] = time.monotonic() - started
    report["source_unchanged_during_run"] = all(
        file_hash(ROOT / path) == digest for path, digest in report["tested_source_sha256"].items()
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print("REPORT=" + str(args.output))


if __name__ == "__main__":
    main()
