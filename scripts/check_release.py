#!/usr/bin/env python3
"""Verify a portable release seal and smoke-test its launcher in isolation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.release_support import extract_plain_tar, relative_name


def verify(archive: Path) -> dict:
    with tempfile.TemporaryDirectory(prefix="archivist-release-") as temp:
        work = Path(temp)
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as z:
                if z.testzip() is not None:
                    raise ValueError("ZIP CRC failure")
                if len(z.namelist()) != len(set(z.namelist())):
                    raise ValueError("Duplicate ZIP member")
                if (
                    len(z.infolist()) > 10000
                    or sum(info.file_size for info in z.infolist()) > 1024 * 1024 * 1024
                ):
                    raise ValueError("Distribution exceeds qualification extraction limits")
                for info in z.infolist():
                    target = work.joinpath(*relative_name(info.filename).parts)
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as contents, target.open("xb") as output:
                        shutil.copyfileobj(contents, output, 1024 * 1024)
                    permissions = (info.external_attr >> 16) & 0o777
                    if permissions:
                        target.chmod(permissions & 0o755)
        else:
            with tarfile.open(archive) as tar:
                extract_plain_tar(tar, work)
        roots = list(work.iterdir())
        if len(roots) != 1 or not roots[0].is_dir():
            raise ValueError("Expected one release root")
        root = roots[0]
        count = 0
        sealed = set()
        actual = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path.relative_to(root).as_posix() != "SHA256SUMS"
        }
        for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
            expected, name = line.split("  ", 1)
            if name in sealed:
                raise ValueError("Unsafe seal path")
            path = root.joinpath(*relative_name(name).parts)
            if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
                raise ValueError("Invalid seal hash")
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("Seal mismatch: " + name)
            sealed.add(name)
            count += 1
        if not sealed or sealed != actual or "archivist.py" not in sealed:
            raise ValueError("Release seal does not cover exactly all source files")
        run = subprocess.run(
            [
                sys.executable,
                "-I",
                str(root / "archivist.py"),
                "--quiet",
                "--json",
                "--workspace",
                str(work / "workspace"),
                "doctor",
            ],
            cwd=work,
            text=True,
            capture_output=True,
            timeout=30,
        )
        if run.returncode:
            raise RuntimeError(run.stdout + run.stderr)
        doctor = json.loads(run.stdout)
        if os.name != "nt":
            shell = subprocess.run(
                [str(root / "launchers/CLI.sh"), "--help"],
                cwd=work,
                text=True,
                capture_output=True,
                timeout=30,
            )
            if shell.returncode:
                raise RuntimeError(shell.stdout + shell.stderr)
        return {
            "archive": archive.name,
            "sealed_files": count,
            "version": doctor["version"],
            "isolated_launcher": "PASS",
            "unix_launcher": "PASS" if os.name != "nt" else "not run",
            "native_windows_macos_ltfs_qualification": False,
        }


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archives", nargs="+", type=Path)
    p.add_argument("--json-out", type=Path)
    args = p.parse_args()
    results = [verify(path.resolve()) for path in args.archives]
    text = json.dumps(results, indent=2) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    print(text, end="")
