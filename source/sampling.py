"""Explicit bounded compression experiments; no extension-based savings guarantees."""

from __future__ import annotations
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from .artifacts import source_check
from .util import canonical, now, regular_source, require, uid


def run_codec(arguments, payload, progress):
    proc = subprocess.Popen(
        arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    started = time.monotonic()
    try:
        initial = payload
        while True:
            progress.check()
            require(
                time.monotonic() - started < 180,
                "SAMPLE_TIMEOUT",
                "Codec experiment exceeded its time limit",
            )
            try:
                output, error = proc.communicate(input=initial, timeout=0.25)
                require(
                    proc.returncode == 0,
                    "SAMPLE_CODEC",
                    "Codec experiment failed",
                    error=error[:4096].decode(errors="replace"),
                )
                return output
            except subprocess.TimeoutExpired:
                initial = None
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.communicate()


def sample(store, plan_id, package_id, progress, max_bytes=32 * 1024 * 1024):
    require(
        type(max_bytes) is int and 1024 <= max_bytes <= 64 * 1024 * 1024,
        "SAMPLE_LIMIT",
        "Sample limit must be 1 KiB to 64 MiB",
    )
    package = store.one("SELECT * FROM packages WHERE plan_id=? AND id=?", (plan_id, package_id))
    require(package and package["kind"] == "data", "SAMPLE_PACKAGE", "Select a payload package")
    src = store.one(
        "SELECT s.* FROM snapshots sn JOIN sources s ON s.id=sn.source_id WHERE sn.id=?",
        (package["snapshot_id"],),
    )
    require(
        not json.loads(src["identity"]).get("unbound"),
        "SOURCE_UNBOUND",
        "Bind the source before reading samples",
    )
    root = Path(src["root"])
    samples = []
    data = bytearray()
    # Deterministic large-file sample, with start/middle/end positions. It remains
    # a purposive sample, not a statistical confidence interval or an exact TAR.
    rows = store.rows(
        "SELECT n.* FROM members m JOIN nodes n ON n.id=m.node_id WHERE m.plan_id=? AND m.package_id=? AND n.size>0 ORDER BY n.size DESC,n.id LIMIT 16",
        (plan_id, package_id),
    )
    progress.phase("Read sample", max_bytes, "bytes")
    for node in rows:
        if len(data) >= max_bytes:
            break
        relative = store.path(node["id"])
        with regular_source(root, relative) as (stream, st):
            source_check(st, node, json.loads(src["identity"]).get("rebound", False))
            take = min(1024 * 1024, max_bytes - len(data), node["size"])
            for offset in sorted(
                {0, max(0, (node["size"] - take) // 2), max(0, node["size"] - take)}
            ):
                if len(data) >= max_bytes:
                    break
                stream.seek(offset)
                block = stream.read(min(take, max_bytes - len(data)))
                data.extend(block)
                samples.append({"path": relative, "offset": offset, "bytes": len(block)})
                progress.advance(len(block), relative)
            after = os.fstat(stream.fileno())
            require(
                (st.st_size, st.st_mtime_ns, st.st_ctime_ns)
                == (after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                "SAMPLE_CHANGED",
                "File changed during sampling",
            )
    require(data, "EMPTY_SAMPLE", "No nonempty files in this package")
    original = hashlib.sha256(data).hexdigest()
    results = []
    progress.phase("Measure codecs", 5, "experiments")
    for level in (3, 6):
        start = time.perf_counter()
        encoded = gzip.compress(data, compresslevel=level, mtime=0)
        encode = time.perf_counter() - start
        start = time.perf_counter()
        decoded = gzip.decompress(encoded)
        decode = time.perf_counter() - start
        require(
            hashlib.sha256(decoded).hexdigest() == original,
            "SAMPLE_ROUNDTRIP",
            "gzip round-trip mismatch",
        )
        results.append(
            {
                "codec": "gzip",
                "level": level,
                "input_bytes": len(data),
                "output_bytes": len(encoded),
                "encoded_input_ratio": len(encoded) / len(data),
                "encode_seconds": encode,
                "decode_seconds": decode,
                "roundtrip_sha256": original,
                "implementation": "Python gzip / linked zlib",
            }
        )
        progress.update(len(results))
    exe = shutil.which("zstd")
    if exe:
        version = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=10
        ).stdout.strip()
        for level in (1, 3, 6):
            progress.check()
            start = time.perf_counter()
            encoded = run_codec(
                [exe, "-q", "-" + str(level), "-T2", "--check", "-c"], data, progress
            )
            encode = time.perf_counter() - start
            start = time.perf_counter()
            decoded = run_codec([exe, "-q", "-d", "-c", "--memory=512MB"], encoded, progress)
            decode = time.perf_counter() - start
            require(
                hashlib.sha256(decoded).hexdigest() == original,
                "SAMPLE_ROUNDTRIP",
                "zstd round-trip mismatch",
            )
            results.append(
                {
                    "codec": "zstd",
                    "level": level,
                    "threads": 2,
                    "input_bytes": len(data),
                    "output_bytes": len(encoded),
                    "encoded_input_ratio": len(encoded) / len(data),
                    "encode_seconds": encode,
                    "decode_seconds": decode,
                    "roundtrip_sha256": original,
                    "implementation": version,
                }
            )
            progress.update(len(results))
    report = {
        "id": uid("sample"),
        "plan_id": plan_id,
        "package_id": package_id,
        "created": now(),
        "sample_bytes": len(data),
        "sample_sha256": original,
        "positions": samples,
        "results": results,
        "basis": "Largest 16 files; bounded start/middle/end windows concatenated. NOT the complete package, not a probability sample, not a guarantee. No settings changed.",
        "memory_peak_measured": False,
    }
    store.db.execute(
        "INSERT INTO measurements VALUES (?,?,?,?,?)",
        (report["id"], plan_id, package_id, now(), canonical(report).decode()),
    )
    store.commit()
    return report
