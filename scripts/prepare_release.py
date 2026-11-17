#!/usr/bin/env python3
"""Prepare a release from this workflow's qualified artifacts; never publish it.

The calling workflow requires every native, browser and build job to succeed.
This second gate checks the evidence and bytes before assembling download assets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from archivist import __version__


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def prepare(inputs, output, commit, run_url):
    require(
        re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", __version__),
        "Only a stable SemVer may be published",
    )
    require(re.fullmatch(r"[0-9a-f]{40}", commit), "Expected an exact source commit")
    require(not output.exists(), "Release output must be new")
    qualified = inputs / "qualified-distributions"
    native = sorted(inputs.glob("tests-*/native-validation.json"))
    require(bool(native), "Native qualification evidence is missing")
    for path in native:
        row = read(path)
        require(row.get("source_commit") == commit, "Native evidence is for a different commit")
        require(row.get("product_version") == __version__, "Native evidence version mismatch")
        require(
            row.get("run", 0) > 0 and row.get("failed") == 0 and row.get("errors") == 0,
            "Native qualification is incomplete or failed",
        )
    browser = []
    for engine in ("chromium", "firefox", "webkit"):
        path = inputs / ("browser-" + engine) / "native" / "gui-validation.json"
        row = read(path)
        require(
            row.get("status") == "PASS" and row.get("browser") == engine,
            "Native browser qualification is incomplete or failed",
        )
        browser.append(row)
    fallback = read(inputs / "browser-chromium" / "fallback" / "gui-validation.json")
    require(
        fallback.get("status") == "PASS" and fallback.get("forced_dialog_fallback"),
        "Dialog fallback qualification is incomplete or failed",
    )
    package = read(qualified / "python-distribution-check" / "qualification.json")
    floor = read(inputs / "python38-distribution-proof" / "qualification.json")
    for row in (package, floor):
        require(
            row.get("state") == "PASS" and row.get("product_version") == __version__,
            "Python distribution qualification is incomplete or failed",
        )
    portable = read(qualified / "dist" / "build-receipt.json")
    require(portable.get("version") == __version__, "Portable distribution version mismatch")
    checks = read(qualified / "packaging-validation.json")
    require(
        len(checks) == 2 and all(row.get("isolated_launcher") == "PASS" for row in checks),
        "Portable distribution qualification is incomplete or failed",
    )
    assets = []
    for row in portable["artifacts"]:
        path = qualified / "dist" / row["file"]
        require(
            path.name == row["file"] and sha256(path) == row["sha256"],
            "Portable distribution checksum mismatch",
        )
        assets.append(path)
    for row in package["artifacts"]:
        path = qualified / "python-distribution-check" / Path(row["file"]).name
        require(sha256(path) == row["sha256"], "Python distribution checksum mismatch")
        assets.append(path)
    require(
        len(assets) == 4 and len({path.name for path in assets}) == 4,
        "Expected four distinct, qualified distributions",
    )
    output.mkdir(parents=True)
    for path in assets:
        shutil.copyfile(path, output / path.name)
    receipt = {
        "version": __version__,
        "source_commit": commit,
        "workflow_run": run_url,
        "native_jobs": len(native),
        "browser_engines": [
            {"engine": row["browser"], "version": row["browser_version"]} for row in browser
        ],
        "python_floor_build": "PASS",
        "dialog_fallback": "PASS",
        "physical_tape_qualification": "NOT_PERFORMED",
        "authenticity": "Checksums detect changes; this release is not cryptographically signed.",
    }
    (output / "release-receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    with zipfile.ZipFile(
        output / "qualification-evidence.zip", "x", zipfile.ZIP_DEFLATED
    ) as archive:
        for path in sorted(inputs.rglob("*")):
            if path.is_file() and path.suffix in (".json", ".log", ".png"):
                require(not path.is_symlink(), "Linked qualification input")
                archive.write(path, path.relative_to(inputs).as_posix())
    seal = "".join(sha256(path) + "  " + path.name + "\n" for path in sorted(output.iterdir()))
    (output / "SHA256SUMS").write_text(seal, encoding="ascii")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    marker = "## [" + __version__ + "]"
    require(marker in changelog, "Changelog has no entry for this version")
    section = changelog.split(marker, 1)[1].split("\n## ", 1)[0]
    notes = "# Archivist " + __version__ + section + "\n\n"
    notes += (
        "Qualified source commit: `"
        + commit
        + "`. [Complete workflow evidence]("
        + run_url
        + ").\n\n"
    )
    notes += "Downloads include portable ZIP/TAR.GZ, wheel, source distribution, SHA-256 checksums and qualification evidence. No PyPI publication is performed.\n"
    (ROOT / "release-notes.md").write_text(notes, encoding="utf-8")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-url", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.inputs, args.output, args.commit, args.run_url), indent=2))


if __name__ == "__main__":
    main()
