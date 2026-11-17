#!/usr/bin/env python3
"""Run the actual implementation suite and optionally save a machine-readable result."""

import argparse
import json
import os
import platform
import sqlite3
import shutil
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from archivist import __version__


class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []

    def startTest(self, test):
        self.clock = time.perf_counter()
        super().startTest(test)

    def addSuccess(self, test):
        self.records.append(
            {"test": test.id(), "status": "PASS", "seconds": time.perf_counter() - self.clock}
        )
        super().addSuccess(test)

    def addFailure(self, test, error):
        self.records.append({"test": test.id(), "status": "FAIL"})
        super().addFailure(test, error)

    def addError(self, test, error):
        self.records.append({"test": test.id(), "status": "ERROR"})
        super().addError(test, error)

    def addSkip(self, test, reason):
        self.records.append({"test": test.id(), "status": "SKIP", "reason": reason})
        super().addSkip(test, reason)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--json-out")
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args()
    started = time.perf_counter()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=1 if a.quiet else 2, resultclass=Result).run(suite)
    data = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": sys.version,
        "sqlite": sqlite3.sqlite_version,
        "product_version": __version__,
        "source_commit": os.environ.get("GITHUB_SHA"),
        "runtime": {"zstd": shutil.which("zstd"), "tar": shutil.which("tar")},
        "run": result.testsRun,
        "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
        "failed": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "seconds": time.perf_counter() - started,
        "tests": result.records,
    }
    if a.json_out:
        out = Path(a.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
