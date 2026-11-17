#!/usr/bin/env python3
"""AP20Archive/1 independent recovery. Qualified on Python 3.12+; optional zstd.

This file is copied, unmodified, into every archive set as RESTORE.py. It does not
import Archivist, open its workspace, trust executable metadata, or use
extractall(). Checksums establish integrity relative to the supplied catalogue,
not authenticity against an attacker who can replace that catalogue.
"""

from __future__ import annotations
import argparse
import contextlib
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

CHUNK = 1024 * 1024
MAX_JSON = 16 * 1024 * 1024
MAX_LINE = 128 * 1024
MAX_MEMBERS = 20_000_000
MAX_BYTES = 256 * 1024**4
ROOT_CONTROL_FILES = frozenset(
    (
        "ARCHIVE.json",
        "ARCHIVE.html",
        "README.txt",
        "RESTORE.py",
        "SHA256SUMS",
        "BUILD.json",
        "COPY.json",
        "REPLICA.json",
    )
)


class RecoveryError(Exception):
    pass


def check(ok, message):
    if not ok:
        raise RecoveryError(message)


def canonical(value):
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("ascii")


def _unique(pairs):
    value = {}
    for k, v in pairs:
        check(k not in value, "Duplicate JSON key: " + k)
        value[k] = v
    return value


def read_json(path, limit=MAX_JSON):
    check(
        path.is_file() and path.stat().st_size <= limit, "Missing or oversized JSON: " + str(path)
    )
    with path.open("r", encoding="utf-8") as stream:
        return json.load(
            stream,
            object_pairs_hook=_unique,
            parse_constant=lambda v: (_ for _ in ()).throw(RecoveryError("Nonfinite JSON number")),
        )


def number(value, label):
    check(type(value) is int and 0 <= value <= MAX_BYTES, "Invalid " + label)
    return value


def sha_text(value):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def parts(path):
    check(
        isinstance(path, str) and path and len(path.encode("utf-8")) <= 32768, "Invalid member path"
    )
    check(
        not path.startswith(("/", "\\"))
        and "\\" not in path
        and "\0" not in path
        and not re.match("^[A-Za-z]:", path),
        "Unsafe member path: " + repr(path),
    )
    out = path.split("/")
    check(all(p not in ("", ".", "..") for p in out), "Traversing member path: " + repr(path))
    return out


def is_link(st):
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)


def no_links(path, missing=False):
    path = Path(os.path.abspath(str(path)))
    for p in reversed([path, *path.parents]):
        try:
            s = p.lstat()
        except FileNotFoundError:
            check(missing, "Missing path: " + str(p))
            continue
        check(not is_link(s), "Link/reparse path refused: " + str(p))
    return path


def publish_new(source, destination):
    """Atomic no-replace publication, or fail closed with the partial retained.

    A prior exists() check is insufficient: POSIX rename can replace a competing
    file or an empty directory. Use the OS's exclusive rename primitive instead.
    This does not protect against an attacker changing ancestor directories.
    """
    source, destination = Path(source), Path(destination)
    if os.name == "nt":
        os.rename(source, destination)  # Windows rename fails if destination exists.
        return
    import ctypes
    import errno

    libc = ctypes.CDLL(None, use_errno=True)
    src, dst = os.fsencode(source), os.fsencode(destination)
    if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        rename = libc.renameat2
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(-100, src, -100, dst, 1)  # AT_FDCWD, RENAME_NOREPLACE.
    elif sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(src, dst, 4)  # RENAME_EXCL.
    else:
        raise RecoveryError("Atomic no-replace rename is unavailable; partial output retained")
    if result != 0:
        code = ctypes.get_errno()
        if code in (errno.ENOSYS, errno.EINVAL, errno.ENOTSUP):
            raise RecoveryError(
                "Filesystem does not support atomic no-replace publication; partial output retained"
            )
        raise OSError(code, os.strerror(code), str(destination))


def located(root, path):
    target = root.joinpath(*parts(path))
    no_links(target)
    check(target.is_file(), "Archive object is not a regular file: " + str(target))
    return target


def pulse(progress, phase, done, total, path=""):
    if progress:
        progress(phase, done, total, path)


def file_hash(path, progress=None, phase="Check archive"):
    h = hashlib.sha256()
    n = 0
    total = path.stat().st_size
    with path.open("rb") as stream:
        while block := stream.read(CHUNK):
            h.update(block)
            n += len(block)
            pulse(progress, phase, n, total, str(path))
    return h.hexdigest()


def manifest_rows(path):
    with gzip.open(path, "rb") as stream:
        count = 0
        while True:
            line = stream.readline(MAX_LINE + 1)
            if not line:
                break
            count += 1
            check(count <= MAX_MEMBERS and len(line) <= MAX_LINE, "Manifest record limit exceeded")
            row = json.loads(line, object_pairs_hook=_unique)
            check(isinstance(row, dict), "Manifest row is not an object")
            parts(row.get("name"))
            check(row.get("kind") in ("file", "directory"), "Unsupported manifest object")
            number(row.get("size"), "member size")
            check(
                type(row.get("mtime_ns")) is int and -(2**63) < row["mtime_ns"] < 2**63,
                "Invalid modification time",
            )
            check(type(row.get("mode")) is int and 0 <= row["mode"] <= 0o777, "Invalid mode")
            if row["kind"] == "file":
                check(sha_text(row.get("sha256")), "Invalid member digest")
            else:
                check(row["size"] == 0, "Directory payload is forbidden")
            yield row


class LimitedTarInfo(tarfile.TarInfo):
    @classmethod
    def fromtarfile(cls, tarfile_obj):
        # TarFile.next() normally treats a malformed later header like EOF. A
        # sealed package instead requires a real end marker, followed by zeros.
        try:
            return super().fromtarfile(tarfile_obj)
        except tarfile.EOFHeaderError:
            tarfile_obj._archive_end_marker = True
            raise
        except tarfile.HeaderError as exc:
            raise RecoveryError("Invalid or missing TAR end/header: " + str(exc)) from exc

    def _proc_pax(self, tarfile_obj):
        check(self.size <= 1024 * 1024, "Oversized PAX metadata")
        return super()._proc_pax(tarfile_obj)

    def _proc_gnulong(self, tarfile_obj):
        check(self.size <= 1024 * 1024, "Oversized GNU metadata")
        return super()._proc_gnulong(tarfile_obj)


def validate_tar_trailer(tar, tar_bytes, progress=None):
    """Consume the parser's buffered stream, not its underlying input.

    A TAR end marker is two zero blocks. Only complete zero padding blocks may
    follow it; concatenated archives and ignored invalid headers are rejected.
    Reading through tar.fileobj is essential because streaming tarfile may have
    read well beyond the end marker into its own buffer already.
    """
    check(getattr(tar, "_archive_end_marker", False), "Missing TAR end marker")
    check(
        tar.fileobj.read(tarfile.BLOCKSIZE) == b"\0" * tarfile.BLOCKSIZE,
        "TAR end marker must contain two zero blocks",
    )
    while True:
        pulse(progress, "Check TAR trailer", tar.fileobj.tell(), tar_bytes)
        block = tar.fileobj.read(CHUNK)
        if not block:
            break
        check(not block.strip(b"\0"), "Nonzero data follows the TAR end marker")
    check(
        tar.fileobj.tell() == tar_bytes and tar_bytes % tarfile.BLOCKSIZE == 0,
        "TAR framing does not match the recorded length",
    )


def validate_member_metadata(entry, row):
    """Keep ordinary TAR recovery and manifest-guided recovery consistent."""
    check(entry.mode == row["mode"], "TAR mode differs from manifest: " + row["name"])
    try:
        timestamp = Decimal(entry.pax_headers.get("mtime", str(entry.mtime)))
        expected = Decimal(row["mtime_ns"]) / Decimal(1_000_000_000)
        matches = timestamp.is_finite() and timestamp == expected
    except (InvalidOperation, TypeError, ValueError):
        matches = False
    check(matches, "TAR modification time differs from manifest: " + row["name"])


class BoundedReader:
    def __init__(self, stream, limit):
        self.stream, self.limit, self.done = stream, limit, 0

    def read(self, n=-1):
        n = min(n if n >= 0 else CHUNK, CHUNK, self.limit - self.done + 1)
        data = self.stream.read(max(1, n))
        self.done += len(data)
        check(self.done <= self.limit, "Decoded stream exceeds its recorded size")
        return data


@contextlib.contextmanager
def decoded(path, codec, tar_bytes):
    raw = path.open("rb")
    stream = raw
    proc = None
    with tempfile.TemporaryFile() as errors:
        try:
            if codec == "gzip":
                stream = gzip.GzipFile(fileobj=raw, mode="rb")
            elif codec == "zstd":
                exe = shutil.which("zstd")
                check(exe is not None, "zstd is required to decode this archive")
                proc = subprocess.Popen(
                    [exe, "-q", "-d", "-c", "--memory=512MB"],
                    stdin=raw,
                    stdout=subprocess.PIPE,
                    stderr=errors,
                    shell=False,
                )
                stream = proc.stdout
            else:
                check(codec == "none", "Unsupported codec: " + str(codec))
            reader = BoundedReader(stream, tar_bytes)
            yield reader
            while reader.read(CHUNK):
                pass
            check(reader.done == tar_bytes, "Decoded TAR length does not match receipt")
            if proc:
                stream.close()
                code = proc.wait(timeout=30)
                errors.seek(0)
                check(code == 0, "Decoder failed: " + errors.read(4096).decode(errors="replace"))
        finally:
            if stream is not raw:
                stream.close()
            if proc and proc.poll() is None:
                proc.kill()
                proc.wait()
            raw.close()


def catalogue_references(index):
    """Validate the catalogue's own identity and completeness claims."""
    check(
        isinstance(index, dict) and index.get("format") == "AP20Archive/1",
        "Not an AP20 archive set",
    )
    refs = index.get("packages")
    planned = index.get("planned_packages")
    check(isinstance(refs, list) and 0 < len(refs) <= 100000, "Invalid package catalogue")
    check(type(planned) is int and len(refs) <= planned <= 100000, "Invalid planned package count")
    scope = index.get("scope")
    check(scope in ("COMPLETE_PLAN", "PARTIAL_PLAN"), "Invalid archive-set scope")
    check(
        (scope == "COMPLETE_PLAN") == (len(refs) == planned),
        "Archive-set scope differs from package counts",
    )
    identifiers = set()
    receipt_paths = set()
    for ref in refs:
        check(isinstance(ref, dict), "Invalid package reference")
        ident = ref.get("package_id")
        check(
            isinstance(ident, str) and re.fullmatch(r"P\d{6,}", ident) is not None,
            "Invalid catalogue package ID",
        )
        check(ident not in identifiers, "Duplicate package ID in catalogue")
        identifiers.add(ident)
        name = ref.get("receipt")
        parts(name)
        check(
            name not in receipt_paths and name not in ROOT_CONTROL_FILES,
            "Duplicate or reserved receipt path",
        )
        receipt_paths.add(name)
        check(sha_text(ref.get("receipt_sha256")), "Invalid receipt checksum")
    return refs


def validate_kit(root, index=None, progress=None, *, control_root=None):
    """Verify the complete recovery kit without executing any supplied code.

    AP20Archive/1 seals its catalogue, documentation, reader and each package
    receipt in SHA256SUMS. Payloads and member manifests are sealed by receipts.
    Hashes establish consistency with the supplied seals, not authenticity.
    A valid older reader may be preserved; its bytes are never silently resealed.
    """
    root = no_links(Path(root))
    # The application publisher validates a staged generation before replacing
    # public metadata. Receipts remain immutable in the archive root. Normal
    # standalone recovery always reads both from the same root.
    controls = root if control_root is None else no_links(Path(control_root))
    index_path = located(controls, "ARCHIVE.json")
    if index is None:
        index = read_json(index_path)
    refs = catalogue_references(index)
    expected = {"ARCHIVE.json", "README.txt", "RESTORE.py"} | {r["receipt"] for r in refs}
    check(
        index.get("human_manifest") in (None, "ARCHIVE.html"),
        "Unsupported human-readable catalogue path",
    )
    if index.get("human_manifest") == "ARCHIVE.html":
        expected.add("ARCHIVE.html")
    optional = {"ARCHIVE.html"} - expected
    seal_path = located(controls, "SHA256SUMS")
    check(seal_path.stat().st_size <= 4 * MAX_JSON, "Oversized recovery-kit seal list")
    seals = {}
    seal_hash = hashlib.sha256()
    with seal_path.open("rb") as stream:
        while True:
            raw = stream.readline(MAX_LINE + 1)
            if not raw:
                break
            seal_hash.update(raw)
            check(
                len(raw) <= MAX_LINE and len(seals) < len(expected | optional),
                "Recovery-kit seal list exceeds its expected entries",
            )
            try:
                line = raw.decode("utf-8").rstrip("\r\n")
            except UnicodeDecodeError as exc:
                raise RecoveryError("Recovery-kit seal list is not UTF-8") from exc
            match = re.fullmatch(r"([0-9a-f]{64}) [ *](.+)", line)
            check(match is not None, "Malformed recovery-kit checksum entry")
            sha, name = match.groups()
            parts(name)
            check(
                name in expected | optional and name not in seals,
                "Unexpected or duplicate recovery-kit checksum entry: " + name,
            )
            seals[name] = sha
    check(expected <= set(seals), "Recovery-kit checksums are missing required files")
    for ref in refs:
        check(
            seals[ref["receipt"]] == ref["receipt_sha256"],
            "Catalogue and recovery-kit receipt checksums differ",
        )
    for name in sorted(seals):
        path = located(controls if name in ROOT_CONTROL_FILES else root, name)
        check(path.stat().st_size <= MAX_JSON, "Oversized recovery-kit file: " + name)
        check(
            file_hash(path, progress, "Check recovery kit") == seals[name],
            "Recovery-kit checksum mismatch: " + name,
        )
    return {
        "state": "KIT_VERIFIED",
        "catalogue_sha256": seals["ARCHIVE.json"],
        "seal_sha256": seal_hash.hexdigest(),
        "files": seals,
        "index": index,
    }


def validate_receipt(root, reference, progress=None, hash_payload=True):
    check(
        isinstance(reference, dict) and sha_text(reference.get("receipt_sha256")),
        "Invalid package reference",
    )
    check(
        isinstance(reference.get("package_id"), str)
        and re.fullmatch(r"P\d{6,}", reference["package_id"]) is not None,
        "Invalid reference package ID",
    )
    receipt_path = located(root, reference["receipt"])
    check(
        file_hash(receipt_path) == reference["receipt_sha256"], "Package receipt checksum mismatch"
    )
    r = read_json(receipt_path)
    check(isinstance(r, dict) and r.get("format") == "AP20Package/1", "Unsupported package format")
    check(
        isinstance(r.get("package_id"), str)
        and re.fullmatch(r"P\d{6,}", r["package_id"]) is not None,
        "Invalid package ID",
    )
    check(r["package_id"] == reference["package_id"], "Receipt and catalogue package IDs differ")
    check(r.get("codec") in ("none", "gzip", "zstd"), "Unsupported codec")
    check(
        sha_text(r.get("artifact_sha256")) and sha_text(r.get("manifest_sha256")),
        "Invalid checksum",
    )
    for k in ("artifact_bytes", "manifest_bytes", "tar_bytes", "logical_bytes", "member_count"):
        number(r.get(k), k)
    check(r["member_count"] <= MAX_MEMBERS, "Too many members")
    check(
        r["tar_bytes"] >= 2 * tarfile.BLOCKSIZE and r["tar_bytes"] % tarfile.BLOCKSIZE == 0,
        "Invalid recorded TAR framing length",
    )
    for key, receipt_key in (
        ("artifact_sha256", "artifact_sha256"),
        ("actual_bytes", "artifact_bytes"),
        ("logical_bytes", "logical_bytes"),
    ):
        if key in reference:
            if key != "artifact_sha256":
                number(reference[key], key)
            check(reference[key] == r[receipt_key], "Catalogue and receipt differ: " + key)
    object_names = [reference["receipt"], r.get("artifact"), r.get("manifest")]
    for name in object_names:
        parts(name)
        check(
            name not in ROOT_CONTROL_FILES, "Package object uses a reserved control path: " + name
        )
    check(len(set(object_names)) == len(object_names), "Package objects must use distinct paths")
    artifact = located(root, r["artifact"])
    manifest = located(root, r["manifest"])
    check(
        artifact.stat().st_size == r["artifact_bytes"]
        and manifest.stat().st_size == r["manifest_bytes"],
        "Stored length differs from receipt",
    )
    check(file_hash(manifest) == r["manifest_sha256"], "Manifest checksum mismatch")
    if hash_payload:
        check(file_hash(artifact, progress) == r["artifact_sha256"], "Archive checksum mismatch")
    return r, artifact, manifest


def inspect(root, packages=None, progress=None):
    root = no_links(Path(root))
    index = validate_kit(root, progress=progress)["index"]
    refs = index["packages"]
    check(
        packages is None
        or (isinstance(packages, (list, tuple)) and all(isinstance(p, str) for p in packages)),
        "Package selection must be a list of IDs",
    )
    requested = set(packages or [])
    selected = []
    seen = set()
    for ref in refs:
        check(
            isinstance(ref, dict) and isinstance(ref.get("package_id"), str),
            "Invalid package reference",
        )
        check(ref["package_id"] not in seen, "Duplicate package ID in catalogue")
        seen.add(ref["package_id"])
        if not requested or ref["package_id"] in requested:
            selected.append(ref)
    check(not requested - seen, "Unknown requested packages: " + str(sorted(requested - seen)))
    check(selected, "No packages selected")
    return root, index, selected


def selection_evidence(index, refs):
    """Separate what the set contains from what this operation actually checks."""
    selected_all = len(refs) == len(index["packages"])
    return {
        "scope": index["scope"] if selected_all else "PARTIAL_PLAN",
        "archive_set_scope": index["scope"],
        "verification_selection_scope": "ALL_AVAILABLE_PACKAGES"
        if selected_all
        else "SELECTED_PACKAGES",
        "available_packages": len(index["packages"]),
        "planned_packages": index["planned_packages"],
        "selected_package_ids": [ref["package_id"] for ref in refs],
    }


def prepare_paths(root, refs, db, progress=None):
    """Preflight every path into a disk-backed table before creating output files."""
    db.executescript(
        "CREATE TABLE paths(path TEXT PRIMARY KEY, folded TEXT UNIQUE, kind TEXT NOT NULL, explicit INTEGER NOT NULL, size INTEGER, mtime_ns INTEGER, mode INTEGER);"
    )
    receipts = []
    total = 0
    count = 0
    for ref in refs:
        r, artifact, manifest = validate_receipt(root, ref, progress, hash_payload=False)
        n = amount = 0
        for row in manifest_rows(manifest):
            n += 1
            count += 1
            amount += row["size"]
            segments = parts(row["name"])
            for depth in range(1, len(segments) + 1):
                name = "/".join(segments[:depth])
                explicit = int(depth == len(segments))
                kind = row["kind"] if explicit else "directory"
                key = unicodedata.normalize("NFC", name).casefold()
                prior = db.execute(
                    "SELECT path,kind,explicit FROM paths WHERE folded=?", (key,)
                ).fetchone()
                if prior:
                    check(prior[0] == name, "Case/Unicode collision on restore: " + name)
                    check(
                        prior[1] == "directory" and kind == "directory",
                        "Duplicate file or file-as-parent: " + name,
                    )
                    check(not (prior[2] and explicit), "Duplicate explicit directory: " + name)
                    if explicit:
                        db.execute(
                            "UPDATE paths SET explicit=1,size=?,mtime_ns=?,mode=? WHERE path=?",
                            (row["size"], row["mtime_ns"], row["mode"], name),
                        )
                else:
                    db.execute(
                        "INSERT INTO paths VALUES (?,?,?,?,?,?,?)",
                        (
                            name,
                            key,
                            kind,
                            explicit,
                            row["size"] if explicit else None,
                            row["mtime_ns"] if explicit else None,
                            row["mode"] if explicit else None,
                        ),
                    )
            if os.name == "nt":
                for part in segments:
                    stem = part.split(".")[0].upper()
                    reserved = {
                        "CON",
                        "PRN",
                        "AUX",
                        "NUL",
                        *(f"COM{i}" for i in range(1, 10)),
                        *(f"LPT{i}" for i in range(1, 10)),
                    }
                    check(
                        not re.search(r'[<>:"|?*\x00-\x1f]', part)
                        and not part.endswith((".", " "))
                        and stem not in reserved,
                        "Name cannot be restored safely on Windows: " + repr(part),
                    )
            if count % 1000 == 0:
                pulse(progress, "Check paths", count, None, row["name"])
                db.commit()
        check(
            n == r["member_count"] and amount == r["logical_bytes"],
            "Manifest counts differ from receipt",
        )
        total += amount
        check(total <= MAX_BYTES, "Restore exceeds configured safety limit")
        receipts.append((r, artifact, manifest))
    db.commit()
    return receipts, total, count


def verify_package(root, reference, progress=None, output=None, permissions=False, check_hash=True):
    r, artifact, manifest = validate_receipt(root, reference, progress, hash_payload=check_hash)
    expected = iter(manifest_rows(manifest))
    count = done = 0
    with decoded(artifact, r["codec"], r["tar_bytes"]) as raw:
        with tarfile.open(fileobj=raw, mode="r|", tarinfo=LimitedTarInfo, bufsize=CHUNK) as tar:
            # Prevent tarfile from retaining millions of previously read TarInfo objects.
            for entry in tar:
                tar.members.clear()
                row = next(expected, None)
                check(row is not None, "Unexpected extra TAR member")
                name = entry.name.rstrip("/") if entry.isdir() else entry.name
                check(name == row["name"], "TAR/member sequence differs: " + repr(name))
                parts(name)
                check(
                    (entry.isfile() and row["kind"] == "file")
                    or (entry.isdir() and row["kind"] == "directory"),
                    "Link or unsupported TAR object",
                )
                check(entry.size == row["size"], "TAR member length differs")
                check(not entry.issparse(), "Sparse TAR members are not part of this profile")
                validate_member_metadata(entry, row)
                count += 1
                dst = output.joinpath(*parts(name)) if output else None
                if entry.isdir():
                    if dst:
                        dst.mkdir(parents=True, exist_ok=True)
                        no_links(dst)
                    continue
                sink = None
                try:
                    if dst:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        no_links(dst.parent)
                        sink = dst.open("xb")
                    source = tar.extractfile(entry)
                    h = hashlib.sha256()
                    length = 0
                    while block := source.read(CHUNK):
                        h.update(block)
                        length += len(block)
                        done += len(block)
                        if sink:
                            sink.write(block)
                        pulse(
                            progress,
                            "Restore" if output else "Decode verify",
                            done,
                            r["logical_bytes"],
                            name,
                        )
                    check(
                        length == row["size"] and h.hexdigest() == row["sha256"],
                        "Member content checksum mismatch: " + name,
                    )
                    if sink:
                        sink.flush()
                        if permissions:
                            os.chmod(dst, row["mode"] & 0o777)
                        os.utime(dst, ns=(row["mtime_ns"], row["mtime_ns"]))
                        os.fsync(sink.fileno())
                finally:
                    if sink:
                        sink.close()
            check(next(expected, None) is None, "TAR archive is missing manifest members")
            validate_tar_trailer(tar, r["tar_bytes"], progress)
    check(
        count == r["member_count"] and done == r["logical_bytes"], "Verified member totals differ"
    )
    return {
        "package_id": r["package_id"],
        "artifact_sha256": r["artifact_sha256"],
        "members": count,
        "logical_bytes": done,
        "state": "CONTENTS_VERIFIED",
    }


def run(root, output=None, packages=None, progress=None, permissions=False):
    root, index, refs = inspect(root, packages, progress)
    output = no_links(Path(output), missing=True) if output is not None else None
    if output:
        check(not output.exists(), "Restore destination must not already exist")
        check(output.parent.is_dir(), "Restore parent directory must exist")
        check(
            not root.is_relative_to(output) and not output.is_relative_to(root),
            "Restore destination overlaps archive set",
        )
    partial = None
    with tempfile.TemporaryDirectory(prefix="ap20-recovery-") as td:
        db = sqlite3.connect(str(Path(td) / "paths.sqlite"))
        try:
            receipts, total, members = prepare_paths(root, refs, db, progress)
            if output:
                check(
                    shutil.disk_usage(output.parent).free >= total + 16 * 1024 * 1024,
                    "Insufficient restore space for expanded logical bytes",
                )
                partial = output.with_name("." + output.name + ".partial-" + uuid.uuid4().hex[:8])
                partial.mkdir(mode=0o700)
            results = []
            for reference in refs:
                results.append(verify_package(root, reference, progress, partial, permissions))
            if partial:
                for path, mtime, mode, explicit in db.execute(
                    "SELECT path,mtime_ns,mode,explicit FROM paths WHERE kind='directory' ORDER BY LENGTH(path) DESC"
                ):
                    dst = partial.joinpath(*parts(path))
                    dst.mkdir(parents=True, exist_ok=True)
                    # Open before applying restrictive directory modes. Sync
                    # every directory, including inferred parents, bottom-up.
                    fd = (
                        os.open(dst, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                        if os.name != "nt"
                        else None
                    )
                    try:
                        if explicit:
                            if permissions:
                                os.chmod(dst, mode & 0o777)
                            os.utime(dst, ns=(mtime, mtime))
                        if fd is not None:
                            os.fsync(fd)
                    finally:
                        if fd is not None:
                            os.close(fd)
                if os.name != "nt":
                    fd = os.open(partial, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
                check(
                    not output.exists(),
                    "Restore destination appeared while restoring; refusing overwrite",
                )
                publish_new(partial, output)
                if os.name != "nt":
                    fd = os.open(output.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
            return {
                "state": "RESTORED_VERIFIED" if output else "CONTENTS_VERIFIED",
                "output": str(output) if output else None,
                "packages": len(results),
                "members": members,
                "logical_bytes": total,
                **selection_evidence(index, refs),
                "recovery_kit": "KIT_VERIFIED",
                "catalogue_sha256": file_hash(root / "ARCHIVE.json"),
                "results": results,
                "authenticity": "Checksums relative to the supplied catalogue; no signature or external trust anchor",
            }
        except BaseException:
            # Never publish incomplete data under the requested final destination.
            if partial and partial.exists():
                print("Partial restore retained: " + str(partial), file=sys.stderr)
            raise
        finally:
            db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive_set", type=Path)
    parser.add_argument(
        "--to", type=Path, help="New destination directory; omit for verification only"
    )
    parser.add_argument("--package", action="append", help="Optional package ID; can be repeated")
    parser.add_argument(
        "--permissions",
        action="store_true",
        help="Restore ordinary mode bits where supported; never ownership, ACLs or set-id bits",
    )
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                run(args.archive_set, args.to, args.package, permissions=args.permissions), indent=2
            )
        )
    except (OSError, ValueError, RecoveryError, tarfile.TarError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
