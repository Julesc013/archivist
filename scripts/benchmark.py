#!/usr/bin/env python3
"""Reproducible metadata benchmark; never reads source-file contents or tape.

An optional --legacy installation compares the actual V13 code in fresh processes.
It is not a claim that differing schemas preserve identical optional metadata.
"""

import argparse
import csv
import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parents[1]


def worker(version, installation, root, export):
    import resource

    sys.path.insert(0, str(installation if version == "20" else installation / "src"))
    started = time.perf_counter()
    if version == "20":
        from archivist.application import Application
        from archivist.store import Store

        app = Application(root)
        result = app.call("import_efu", {"input": str(export), "root": "D:\\", "label": "BENCH"})
        scan_end = time.perf_counter()
        plan = app.call(
            "plan",
            {
                "snapshots": [result["snapshot_id"]],
                "policy": {
                    "minimum": 10_000_000_000,
                    "target": 100_000_000_000,
                    "maximum": 200_000_000_000,
                    "codec": "none",
                },
            },
        )
        plan_end = time.perf_counter()
        first = time.perf_counter()
        app.call("members", {"plan_id": plan["id"], "package_id": "P000001", "limit": 100})
        member_seconds = time.perf_counter() - first
        with Store(root) as store:
            files = result["counts"]["files"]
            logical = result["counts"]["eligible_bytes"]
            packages = plan["counts"]["packages"]
            h = hashlib.sha256()
            # Independent canonical path/length reconciliation, not the implementation's own fingerprint.
            paths = sorted(
                (store.path(r["id"]), r["size"])
                for r in store.rows("SELECT id,size FROM nodes WHERE kind='file' AND eligible=1")
            )
            for path, size in paths:
                h.update(json.dumps([path, size], separators=(",", ":")).encode() + b"\n")
    else:
        from archiveplanner.collection import collect
        from archiveplanner.service import Service

        folder = collect(
            "D:\\",
            root,
            source_id="BENCH",
            input_export=export,
            level="error",
            color="never",
            progress="never",
        )
        scan_end = time.perf_counter()
        service = Service(root, level="error")
        plan = service.plan_create(
            [folder.name],
            options={
                "min_bytes": 10000000000,
                "target_bytes": 100000000000,
                "max_bytes": 200000000000,
                "strategy": "directory-first",
            },
            persist=True,
        )
        plan_end = time.perf_counter()
        member_seconds = None
        import sqlite3

        db = sqlite3.connect(folder / "inventory.sqlite")
        files, logical = db.execute(
            "SELECT COUNT(*),SUM(size) FROM entries WHERE kind='file' AND eligible=1"
        ).fetchone()
        h = hashlib.sha256()
        for path, size in db.execute(
            "SELECT path,size FROM entries WHERE kind='file' AND eligible=1 ORDER BY path"
        ):
            h.update(json.dumps([path, size], separators=(",", ":")).encode() + b"\n")
        db.close()
        packages = plan.get("summary", {}).get("packages")
    summary = {
        "version": version,
        "input_files": files,
        "logical_bytes": logical,
        "path_size_sha256": h.hexdigest(),
        "scan_seconds": scan_end - started,
        "plan_seconds": plan_end - scan_end,
        "first_member_page_seconds": member_seconds,
        "workspace_bytes": sum(p.stat().st_size for p in root.rglob("*") if p.is_file()),
        "rss_peak_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "packages": packages,
    }
    print("BENCHMARK_RESULT=" + json.dumps(summary))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--directory", required=True)
    p.add_argument("--legacy")
    p.add_argument("--files", type=int, default=50000)
    p.add_argument("--rounds", type=int, default=2)
    p.add_argument("--worker", nargs=4)
    a = p.parse_args()
    if a.worker:
        worker(a.worker[0], Path(a.worker[1]), Path(a.worker[2]), Path(a.worker[3]))
        return
    root = Path(a.directory)
    root.mkdir(parents=True, exist_ok=False)
    export = root / "fixture.efu"
    with export.open("w", encoding="utf-8", newline="") as stream:
        out = csv.writer(stream)
        out.writerow(["Filename", "Size", "Date Modified", "Attributes"])
        for i in range(a.files):
            path = f"D:\\Collection{i % 25:02}\\Group{i % 100:03}\\Project{i % 1000:04}\\record-{i:08}.{['txt', 'jpg', 'iso', 'json', 'mp4', 'bin', 'flac', 'zip', 'py', 'unknown'][i % 10]}"
            out.writerow([path, 1000 + (i * 7919) % 100_000_000, "133000000000000000", 32])
    results = []
    versions = [("20", APP)]
    if a.legacy:
        versions.insert(0, ("13", Path(a.legacy)))
    for r in range(a.rounds):
        for version, installation in versions if r % 2 == 0 else reversed(versions):
            destination = root / f"v{version}-run{r + 1}"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__)),
                    "--directory",
                    str(root),
                    "--worker",
                    version,
                    str(installation),
                    str(destination),
                    str(export),
                ],
                capture_output=True,
                text=True,
                timeout=240,
            )
            (root / f"v{version}-run{r + 1}.log").write_text(proc.stdout + "\n" + proc.stderr)
            if proc.returncode:
                raise RuntimeError(f"Benchmark worker {version}: " + proc.stderr[-3000:])
            result = json.loads(
                next(
                    line.split("=", 1)[1]
                    for line in proc.stdout.splitlines()
                    if line.startswith("BENCHMARK_RESULT=")
                )
            )
            results.append(result)
            print(json.dumps(result), flush=True)
    data = {
        "platform": platform.platform(),
        "python": sys.version,
        "files": a.files,
        "rounds": a.rounds,
        "fixture_sha256": hashlib.sha256(export.read_bytes()).hexdigest(),
        "scope": "Synthetic frozen EFU; metadata import/aggregation/planning. NOT live Everything, filesystem acquisition, compression, GUI or media throughput. Sequential alternating fresh processes; schemas differ.",
        "reconciliation": len({r["path_size_sha256"] for r in results}) == 1,
        "runs": results,
    }
    (root / "benchmark.json").write_text(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
