#!/usr/bin/env python3
"""Build repeatable portable ZIP/TAR.GZ files from explicit repository inputs.

No network, source mutation, git checkout, or package installation is performed.
Wheel/sdist builds use the separate standard setuptools backend.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from archivist import __version__

DIRECTORIES = ("source", "launchers", "scripts", "tests", "docs", "examples", ".github")
ROOT_FILES = (
    "archivist.py",
    "pyproject.toml",
    "MANIFEST.in",
    ".gitignore",
    ".gitattributes",
    "README.md",
    "CHANGELOG.md",
    "TODO.md",
    "ROADMAP.md",
    "AGENTS.md",
    "LICENSE",
    "THIRD-PARTY.md",
    "START-HERE.txt",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "requirements-dev.txt",
    "requirements-browser.txt",
    "package.json",
    "package-lock.json",
)
DEFAULT_EPOCH = 1794873600  # 2026-11-17 00:00:00 UTC; fixed for the 2.0.0 release.


def inputs() -> list[Path]:
    found = [ROOT / name for name in ROOT_FILES]
    for directory in DIRECTORIES:
        found.extend(path for path in (ROOT / directory).rglob("*") if path.is_file())
    result = []
    for path in sorted(set(found), key=lambda p: p.relative_to(ROOT).as_posix()):
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing or linked release input: {path.relative_to(ROOT)}")
        result.append(path)
    return result


def mode(path: Path) -> int:
    return (
        0o755
        if path.suffix in (".sh", ".command", ".desktop") or path.name == "archivist.py"
        else 0o644
    )


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def build(output: Path, epoch: int) -> dict:
    if not 315532800 <= epoch <= 4354819198:
        raise ValueError("SOURCE_DATE_EPOCH must fit the ZIP timestamp range (1980–2107)")
    output.mkdir(parents=True, exist_ok=True)
    prefix = f"archivist-{__version__}"
    source = inputs()
    entries = [
        (path.relative_to(ROOT).as_posix(), path.read_bytes(), mode(path)) for path in source
    ]
    seal = "".join(
        hashlib.sha256(data).hexdigest() + "  " + name + "\n" for name, data, _ in entries
    ).encode()
    entries.append(("SHA256SUMS", seal, 0o644))
    zip_path = output / (prefix + ".zip")
    tar_path = output / (prefix + ".tar.gz")
    for path in (zip_path, tar_path):
        if path.exists():
            raise FileExistsError(f"Release output already exists: {path}")
    with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data, permissions in entries:
            info = zipfile.ZipInfo(prefix + "/" + name, time.gmtime(epoch)[:6])
            info.create_system = 3
            info.external_attr = (0o100000 | permissions) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data, compresslevel=9)
    with tar_path.open("xb") as raw:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, mtime=epoch, compresslevel=9
        ) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as tar:
                for name, data, permissions in entries:
                    info = tarfile.TarInfo(prefix + "/" + name)
                    info.size, info.mode, info.mtime = len(data), permissions, epoch
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    tar.addfile(info, io.BytesIO(data))
    result = {
        "version": __version__,
        "source_date_epoch": epoch,
        "source_files": len(source),
        "input_sha256": hashlib.sha256(seal).hexdigest(),
        "artifacts": [
            {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in (zip_path, tar_path)
        ],
        "reproducibility": "Byte-identical for identical inputs, epoch and build toolchain",
    }
    (output / "SHA256SUMS").write_text(
        "".join(row["sha256"] + "  " + row["file"] + "\n" for row in result["artifacts"]),
        encoding="ascii",
    )
    (output / "build-receipt.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument(
        "--epoch", type=int, default=int(os.environ.get("SOURCE_DATE_EPOCH", DEFAULT_EPOCH))
    )
    args = parser.parse_args()
    print(json.dumps(build(args.output.resolve(), args.epoch), indent=2))


if __name__ == "__main__":
    main()
