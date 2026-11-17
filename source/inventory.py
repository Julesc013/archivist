"""Streaming acquisition and normalized evidence. Index observations are not snapshots."""

from __future__ import annotations
import csv
import datetime as dt
import hashlib
import ntpath
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from .path_cache import PathCache
from .util import (
    Problem,
    canonical,
    collision_key,
    hash_file,
    is_link,
    no_links,
    now,
    portable_name,
    regular_source,
    rel_parts,
    require,
    root_identity,
    uid,
    within,
)

TEXT = frozenset(
    "txt text md rst csv tsv json jsonl xml yaml yml ini cfg conf log sql html htm css js mjs ts tsx jsx py pyw pyi c cc cpp cxx h hpp cs java go rs rb sh bash zsh ps1 psm1 bat cmd lua toml tex srt vtt svg".split()
)
COMPRESSED = frozenset(
    "jpg jpeg png webp avif heic heif mp3 aac m4a flac ogg opus mp4 mkv mov avi webm m4v zip 7z rar gz bz2 xz zst lz4 woff2 docx xlsx pptx".split()
)
ATTRS = {
    "R": 1,
    "H": 2,
    "S": 4,
    "D": 16,
    "A": 32,
    "V": 64,
    "N": 128,
    "T": 256,
    "L": 1024,
    "C": 2048,
    "O": 4096,
    "I": 8192,
    "E": 16384,
    "X": 131072,
    "P": 524288,
    "U": 1048576,
    "M": 4194304,
}
RISK_ATTRIBUTES = 0x1000 | 0x4000 | 0x40000 | 0x400000


def classify(name):
    ext = name.rsplit(".", 1)[1].lower() if "." in name and not name.startswith(".") else ""
    return ext, "text" if ext in TEXT else "compressed" if ext in COMPRESSED else "unknown"


def tar_cost(size, path_bytes=0):
    # Conservative PAX/header/padding estimate; output is still measured and gated.
    return ((size + 511) // 512) * 512 + 1536 + ((path_bytes + 512 + 511) // 512) * 512


def parse_attributes(value):
    value = str(value or "").strip()
    if re.fullmatch(r"(?:\d+|0[xX][0-9a-fA-F]+)", value):
        result = int(value, 16 if value[:2].lower() == "0x" else 10)
        require(0 <= result <= 0xFFFFFFFF, "ATTR_RANGE", "Attributes outside DWORD range")
        return result
    require(
        value and all(c.upper() in ATTRS for c in value),
        "ATTR_FORMAT",
        "Unknown or missing Everything attributes",
        value=value,
    )
    result = 0
    for c in value.upper():
        result |= ATTRS[c]
    return result


def timestamp_ns(value):
    value = str(value or "").strip()
    if not value:
        return None
    if value.isdigit():
        result = (int(value) - 116444736000000000) * 100
    else:
        try:
            stamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                return None
            delta = stamp.astimezone(dt.timezone.utc) - dt.datetime(
                1970, 1, 1, tzinfo=dt.timezone.utc
            )
            result = ((delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds) * 1000
        except ValueError:
            return None
    return result if -(2**63) < result < 2**63 else None


def windows_relative(full, root):
    full, root = ntpath.normpath(full), ntpath.normpath(root)
    require(
        ntpath.isabs(full) and ntpath.isabs(root),
        "ABSOLUTE_PATH",
        "Everything export paths must be absolute",
    )
    if ntpath.normcase(full) == ntpath.normcase(root):
        return ""
    prefix = root.rstrip("\\") + "\\"
    if not ntpath.normcase(full).startswith(ntpath.normcase(prefix)):
        return None
    relative = full[len(prefix) :].replace("\\", "/")
    rel_parts(relative)
    return relative


class InventoryBuilder:
    def __init__(self, store, root, label, backend, provenance, progress, source_id=None):
        self.s, self.p = store, progress
        self.sid = source_id or uid("source")
        if source_id:
            existing = store.need("sources", source_id)
            require(
                os.path.normcase(os.path.abspath(existing["root"]))
                == os.path.normcase(os.path.abspath(str(root))),
                "SOURCE_BINDING",
                "Source ID is registered to a different root; explicitly bind it first",
            )
        else:
            identity = root_identity(Path(root)) if Path(root).is_dir() else {"unbound": True}
            store.db.execute(
                "INSERT INTO sources VALUES (?,?,?,?,?)",
                (
                    self.sid,
                    label or Path(root).name or str(root),
                    str(root),
                    canonical(identity).decode(),
                    now(),
                ),
            )
        self.id = uid("scan")
        store.db.execute(
            "INSERT INTO snapshots(id,source_id,state,backend,started,provenance) VALUES (?,?,?,?,?,?)",
            (self.id, self.sid, "RUNNING", backend, now(), canonical(provenance).decode()),
        )
        self.dirs: PathCache[str, int] = PathCache()
        self.counts = {
            "input_rows": 0,
            "accepted_rows": 0,
            "excluded_rows": 0,
            "outside_root_rows": 0,
            "invalid_rows": 0,
        }
        self.pending = 0
        self.ensure_dir("")
        store.commit()

    def ensure_dir(self, path):
        if path in self.dirs:
            return self.dirs[path]
        parts = rel_parts(path, True)
        current = ""
        parent = None
        for name in [""] + parts:
            current = (current + "/" + name).strip("/")
            if current in self.dirs:
                parent = self.dirs[current]
                continue
            old = self.s.one(
                "SELECT id,kind FROM nodes WHERE snapshot_id=? AND parent IS ? AND name=?",
                (self.id, parent, name),
            )
            require(
                not old or old["kind"] == "directory",
                "ANCESTRY",
                "A non-directory is used as a parent",
                path=current,
            )
            if old:
                ident = old["id"]
            else:
                ident = self.s.db.execute(
                    "INSERT INTO nodes(snapshot_id,parent,name,kind,eligible,inferred) VALUES (?,?,?,'directory',1,1)",
                    (self.id, parent, name),
                ).lastrowid
            self.dirs[current] = ident
            parent = ident
        return parent

    def add(
        self,
        path,
        kind,
        size=0,
        mtime_ns=None,
        ctime_ns=None,
        mode=None,
        device=None,
        inode=None,
        attributes=0,
        eligible=True,
        sha256=None,
        inferred=False,
    ):
        parts = rel_parts(path, kind == "directory")
        name = parts[-1] if parts else ""
        parent = self.ensure_dir("/".join(parts[:-1])) if parts else None
        prior = self.s.one(
            "SELECT id,kind,inferred FROM nodes WHERE snapshot_id=? AND parent IS ? AND name=?",
            (self.id, parent, name),
        )
        require(
            not prior
            or (prior["kind"] == "directory" and kind == "directory" and prior["inferred"]),
            "DUPLICATE",
            "Duplicate or conflicting inventory path",
            path=path,
        )
        require(
            type(size) is int and 0 <= size < 2**63, "SIZE_RANGE", "Invalid file size", path=path
        )
        ext, cls = classify(name)
        values = (
            kind,
            size,
            mtime_ns,
            ctime_ns,
            mode,
            str(device) if device is not None else None,
            str(inode) if inode is not None else None,
            attributes,
            int(eligible),
            ext,
            cls,
            sha256,
            int(inferred),
        )
        if prior:
            ident = prior["id"]
            self.s.db.execute(
                "UPDATE nodes SET kind=?,size=?,mtime_ns=?,ctime_ns=?,mode=?,device=?,inode=?,attributes=?,eligible=?,extension=?,class=?,sha256=?,inferred=? WHERE id=?",
                values + (ident,),
            )
        else:
            ident = self.s.db.execute(
                "INSERT INTO nodes(snapshot_id,parent,name,kind,size,mtime_ns,ctime_ns,mode,device,inode,attributes,eligible,extension,class,sha256,inferred) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (self.id, parent, name) + values,
            ).lastrowid
        if kind == "directory":
            self.dirs[path] = ident
        if name and not portable_name(name):
            self.s.issue(
                self.id,
                path,
                "NONPORTABLE_NAME",
                "This name is not safely representable on Windows; ordinary portable execution is blocked",
                "error",
                ident,
            )
        self.pending += 1
        if self.pending >= 2000:
            self.s.commit()
            self.pending = 0
        return ident

    def issue(self, path, code, detail="", severity="warning", node_id=None):
        self.s.issue(self.id, path, code, detail, severity, node_id)
        self.p.event("ERROR" if severity == "error" else "WARN", code, path=path)

    def failed(self, exc):
        self.s.db.execute(
            "UPDATE snapshots SET state='FAILED',completed=?,counts=? WHERE id=?",
            (now(), canonical(self.counts).decode(), self.id),
        )
        self.s.commit()

    def finish(self):
        self.p.phase("Reconcile", None, "entries")
        # All parent IDs precede child IDs, including inferred directories.
        excluded_directories = set()
        n = 0
        for row in self.s.db.execute(
            "SELECT * FROM nodes WHERE snapshot_id=? ORDER BY id", (self.id,)
        ):
            r = dict(row)
            n += 1
            if r["parent"] in excluded_directories and r["eligible"]:
                self.s.db.execute("UPDATE nodes SET eligible=0 WHERE id=?", (r["id"],))
                r["eligible"] = 0
                self.issue(
                    self.s.path(r["id"]), "EXCLUDED_ANCESTOR", "Parent is excluded", node_id=r["id"]
                )
            if not r["eligible"] and r["kind"] == "directory":
                excluded_directories.add(r["id"])
            if r["kind"] == "file" and r["eligible"]:
                cost = tar_cost(r["size"], len(self.s.path(r["id"]).encode("utf-8")) + 80)
                self.s.db.execute(
                    "UPDATE nodes SET total_bytes=?,total_files=1,total_cost=?,text_bytes=? WHERE id=?",
                    (r["size"], cost, r["size"] if r["class"] == "text" else 0, r["id"]),
                )
            self.p.update(n, self.s.path(r["id"]))
        del excluded_directories
        # SQLite spills this sorted collision check to temporary storage instead of
        # retaining a Python dictionary containing every filename.
        self.s.db.create_function("ap_portable_key", 1, collision_key, deterministic=True)
        previous = None
        previous_id = None
        for row in self.s.db.execute(
            "SELECT id,parent,name,ap_portable_key(name) AS folded FROM nodes WHERE snapshot_id=? ORDER BY parent,folded,name",
            (self.id,),
        ):
            key = (row["parent"], row["folded"])
            if key == previous:
                self.issue(
                    self.s.path(row["id"]),
                    "PORTABLE_COLLISION",
                    "Case or Unicode-normalisation collision with node " + str(previous_id),
                    "error",
                    row["id"],
                )
            previous, previous_id = key, row["id"]
        self.p.phase("Aggregate", n, "entries")
        done = 0
        for row in self.s.db.execute(
            "SELECT * FROM nodes WHERE snapshot_id=? ORDER BY id DESC", (self.id,)
        ):
            r = dict(row)
            done += 1
            if r["kind"] == "directory":
                totals = self.s.db.execute(
                    "SELECT COALESCE(SUM(total_bytes),0),COALESCE(SUM(total_files),0),COALESCE(SUM(total_cost),0),COALESCE(SUM(text_bytes),0) FROM nodes WHERE parent=? AND eligible=1",
                    (r["id"],),
                ).fetchone()
                self.s.db.execute(
                    "UPDATE nodes SET total_bytes=?,total_files=?,total_cost=?,text_bytes=? WHERE id=?",
                    tuple(totals) + (r["id"],),
                )
            h = hashlib.sha256(
                canonical(
                    {
                        k: r[k]
                        for k in (
                            "name",
                            "kind",
                            "size",
                            "mtime_ns",
                            "ctime_ns",
                            "mode",
                            "attributes",
                            "eligible",
                            "sha256",
                            "inferred",
                        )
                    }
                )
            )
            if r["kind"] == "directory":
                for child in self.s.db.execute(
                    "SELECT name,digest FROM nodes WHERE parent=? ORDER BY name", (r["id"],)
                ):
                    h.update(canonical(child[0]))
                    h.update(child[1] or b"")
            self.s.db.execute("UPDATE nodes SET digest=? WHERE id=?", (h.digest(), r["id"]))
            self.p.update(done)
        counts = self.s.one(
            "SELECT COUNT(*) AS observations, SUM(kind='file') AS files, SUM(kind='directory') AS directories, COALESCE(SUM(CASE WHEN kind='file' THEN size ELSE 0 END),0) AS observed_bytes, COALESCE(SUM(CASE WHEN kind='file' AND eligible=1 THEN size ELSE 0 END),0) AS eligible_bytes, SUM(kind='file' AND eligible=1) AS eligible_files, SUM(eligible=0) AS excluded FROM nodes WHERE snapshot_id=?",
            (self.id,),
        )
        counts.update(self.counts)
        counts["issues"] = self.s.db.execute(
            "SELECT COUNT(*) FROM issues WHERE snapshot_id=?", (self.id,)
        ).fetchone()[0]
        counts["errors"] = self.s.db.execute(
            "SELECT COUNT(*) FROM issues WHERE snapshot_id=? AND severity='error'", (self.id,)
        ).fetchone()[0]
        root = self.s.one("SELECT * FROM nodes WHERE snapshot_id=? AND parent IS NULL", (self.id,))
        fingerprint = root["digest"].hex()
        state = "REVIEW" if counts["issues"] else "COMPLETE"
        self.s.db.execute(
            "UPDATE snapshots SET state=?,completed=?,fingerprint=?,counts=? WHERE id=?",
            (state, now(), fingerprint, canonical(counts).decode(), self.id),
        )
        self.s.commit()
        return {
            "snapshot_id": self.id,
            "source_id": self.sid,
            "state": state,
            "backend": self.s.need("snapshots", self.id)["backend"],
            "fingerprint": fingerprint,
            "counts": counts,
            "consistency": "Live observations; not a filesystem snapshot",
            "preservation": "logical-files-v1; ACL/ADS/EFS/link topology and sparse allocation not preserved",
        }


def entry_stat(entry):
    """Windows DirEntry.stat omits device/inode/link-count identity fields."""
    if sys.platform == "win32":
        return os.stat(entry.path, follow_symlinks=False)
    return entry.stat(follow_symlinks=False)


def scan_filesystem(
    store, root, label, progress, hash_files=False, source_id=None, cross_mounts=False
):
    root = no_links(Path(root))
    require(root.is_dir(), "SOURCE_DIR", "Source must be a directory")
    b = InventoryBuilder(
        store,
        str(root),
        label,
        "filesystem",
        {"hash_files": hash_files, "snapshot": False, "cross_mounts": cross_mounts},
        progress,
        source_id,
    )
    progress.phase("Scan", None, "entries")
    seen = 0
    try:
        rootstat = root.stat()
        b.add(
            "",
            "directory",
            mtime_ns=rootstat.st_mtime_ns,
            mode=stat.S_IMODE(rootstat.st_mode),
            device=rootstat.st_dev,
            inode=rootstat.st_ino,
        )
        queue = [root]
        while queue:
            directory = queue.pop()
            progress.check()
            try:
                with os.scandir(directory) as entries:
                    for e in entries:
                        progress.check()
                        path = Path(e.path)
                        rel = path.relative_to(root).as_posix()
                        seen += 1
                        b.counts["input_rows"] += 1
                        if within(path, store.root):
                            b.issue(
                                rel,
                                "WORKSPACE_EXCLUDED",
                                "Working evidence is never included in its own source",
                            )
                            b.counts["excluded_rows"] += 1
                            continue
                        try:
                            st = entry_stat(e)
                            attrs = getattr(st, "st_file_attributes", 0)
                            common = {
                                "mtime_ns": st.st_mtime_ns,
                                "ctime_ns": st.st_ctime_ns,
                                "mode": stat.S_IMODE(st.st_mode),
                                "device": st.st_dev,
                                "inode": st.st_ino,
                                "attributes": attrs,
                            }
                            if is_link(st):
                                ident = b.add(rel, "link", eligible=False, **common)
                                b.issue(
                                    rel,
                                    "LINK_EXCLUDED",
                                    "No link traversal or link reconstruction",
                                    node_id=ident,
                                )
                                b.counts["excluded_rows"] += 1
                            elif stat.S_ISDIR(st.st_mode):
                                allowed = cross_mounts or st.st_dev == rootstat.st_dev
                                ident = b.add(rel, "directory", eligible=allowed, **common)
                                if allowed:
                                    queue.append(path)
                                    b.counts["accepted_rows"] += 1
                                else:
                                    b.issue(
                                        rel,
                                        "MOUNT_EXCLUDED",
                                        "Cross-filesystem traversal is disabled",
                                        node_id=ident,
                                    )
                                    b.counts["excluded_rows"] += 1
                            elif stat.S_ISREG(st.st_mode):
                                eligible = not bool(attrs & RISK_ATTRIBUTES)
                                sha = None
                                if hash_files and eligible:
                                    h = hashlib.sha256()
                                    with regular_source(root, rel) as (stream, opened):
                                        require(
                                            (
                                                opened.st_dev,
                                                opened.st_ino,
                                                opened.st_size,
                                                opened.st_mtime_ns,
                                            )
                                            == (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns),
                                            "SOURCE_CHANGED",
                                            "File changed before hashing",
                                            path=rel,
                                        )
                                        while block := stream.read(1024 * 1024):
                                            progress.check()
                                            h.update(block)
                                        after = os.fstat(stream.fileno())
                                        require(
                                            (
                                                after.st_dev,
                                                after.st_ino,
                                                after.st_size,
                                                after.st_mtime_ns,
                                                after.st_ctime_ns,
                                            )
                                            == (
                                                st.st_dev,
                                                st.st_ino,
                                                st.st_size,
                                                st.st_mtime_ns,
                                                st.st_ctime_ns,
                                            ),
                                            "SOURCE_CHANGED",
                                            "File changed while hashing",
                                            path=rel,
                                        )
                                    sha = h.hexdigest()
                                ident = b.add(
                                    rel,
                                    "file",
                                    size=st.st_size,
                                    eligible=eligible,
                                    sha256=sha,
                                    **common,
                                )
                                b.counts["accepted_rows" if eligible else "excluded_rows"] += 1
                                if not eligible:
                                    b.issue(
                                        rel,
                                        "SPECIAL_ATTRIBUTE",
                                        "Offline, encrypted or recall-on-access file is excluded",
                                        node_id=ident,
                                    )
                                if st.st_nlink > 1:
                                    b.issue(
                                        rel,
                                        "HARDLINK_FLATTENED",
                                        "Each path is preserved as an independent regular file",
                                        "info",
                                        ident,
                                    )
                                if (
                                    getattr(st, "st_blocks", (st.st_size + 511) // 512) * 512
                                    < st.st_size
                                ):
                                    b.issue(
                                        rel,
                                        "SPARSE_EXPANDED",
                                        "Logical bytes will be archived; sparse allocation is not preserved",
                                        "info",
                                        ident,
                                    )
                            else:
                                ident = b.add(rel, "special", eligible=False, **common)
                                b.issue(
                                    rel,
                                    "SPECIAL_EXCLUDED",
                                    "Not a regular file/directory",
                                    node_id=ident,
                                )
                                b.counts["excluded_rows"] += 1
                        except (OSError, Problem, UnicodeError) as exc:
                            b.counts["invalid_rows"] += 1
                            b.issue(
                                rel.encode("utf-8", "backslashreplace").decode(),
                                "ENTRY_ERROR",
                                str(exc),
                                "error",
                            )
                        progress.update(seen, rel)
            except OSError as exc:
                b.issue(
                    directory.relative_to(root).as_posix(), "ENUMERATION_ERROR", str(exc), "error"
                )
        return b.finish()
    except BaseException as exc:
        b.failed(exc)
        raise


def import_efu(store, source, root, label, progress, source_id=None, provenance=None):
    source = Path(source)
    # Freeze the input before multiple passes; never mutate the user's export.
    with tempfile.TemporaryDirectory(prefix="ap20-efu-") as td:
        frozen = Path(td) / "input.efu"
        shutil.copyfile(source, frozen)
        meta = {
            "input_sha256": hash_file(frozen),
            "input_bytes": frozen.stat().st_size,
            "coverage": "Export observations only; index completeness unknown",
            **(provenance or {}),
        }
        b = InventoryBuilder(
            store,
            root,
            label,
            "everything" if meta.get("live_ipc") else "efu",
            meta,
            progress,
            source_id,
        )
        progress.phase("Import index", None, "rows")
        csv.field_size_limit(1024 * 1024)
        try:
            with frozen.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.reader(stream)
                header = next(reader, None)
                require(header is not None, "EFU_HEADER", "Missing export header")
                keys = [x.strip().lower() for x in header]
                require(
                    len(keys) == len(set(keys)),
                    "EFU_HEADER",
                    "Duplicate export columns are not accepted",
                )
                require(
                    "size" in keys and "attributes" in keys,
                    "EFU_HEADER",
                    "Export must contain Size and Attributes",
                )
                for line, values in enumerate(reader, 2):
                    progress.check()
                    b.counts["input_rows"] += 1
                    try:
                        require(
                            len(values) == len(keys), "EFU_ROW", "Field count mismatch", line=line
                        )
                        r = dict(zip(keys, values))
                        full = (
                            r.get("filename")
                            or r.get("full path and name")
                            or r.get("full path")
                            or ntpath.join(r["path"], r["name"])
                        )
                        rel = windows_relative(full, root)
                        if rel is None:
                            b.counts["outside_root_rows"] += 1
                            continue
                        attr = parse_attributes(r["attributes"])
                        isdir = bool(attr & 16)
                        link = bool(attr & 1024)
                        size = 0
                        if not isdir:
                            require(
                                bool(re.fullmatch(r"\d+", r["size"].strip())),
                                "EFU_SIZE",
                                "File size must be integer bytes",
                                line=line,
                            )
                            size = int(r["size"])
                        kind = "directory" if isdir else "link" if link else "file"
                        eligible = not (link or bool(attr & RISK_ATTRIBUTES))
                        mtime = timestamp_ns(r.get("date modified", r.get("date-modified", "")))
                        ident = b.add(
                            rel, kind, size=size, mtime_ns=mtime, attributes=attr, eligible=eligible
                        )
                        b.counts["accepted_rows" if eligible else "excluded_rows"] += 1
                        if not eligible:
                            b.issue(
                                rel,
                                "INDEX_EXCLUDED",
                                "Reparse/offline/encrypted/recall observation excluded",
                                node_id=ident,
                            )
                        if kind == "file" and mtime is None:
                            b.issue(
                                rel,
                                "MTIME_UNKNOWN",
                                "No unambiguous modification time; bind/rescan before building",
                                "error",
                                ident,
                            )
                    except (KeyError, ValueError, Problem, UnicodeError) as exc:
                        b.counts["invalid_rows"] += 1
                        b.issue("row:" + str(line), "INVALID_EXPORT_ROW", str(exc), "error")
                    progress.update(b.counts["input_rows"])
            if b.counts["outside_root_rows"]:
                b.issue(
                    "",
                    "OUTSIDE_ROOT",
                    str(b.counts["outside_root_rows"])
                    + " export rows were outside the selected root",
                    "info",
                )
            return b.finish()
        except BaseException as exc:
            b.failed(exc)
            raise


def es_arguments(exe, root, target, instance="1.5a"):
    args = [
        str(exe),
        "-n",
        "4294967295",
        "-size-format",
        "1",
        "-date-format",
        "2",
        "-timeout",
        "60000",
        "-no-highlight",
        "-header",
        "-no-footer",
        "-no-pause",
        "-size",
        "-attributes",
        "-date-created",
        "-date-modified",
        "-export-efu",
        str(target),
    ]
    if instance:
        args += ["-instance", instance]
    return args + ["-path", str(root)]


def scan_everything(
    store, root, label, progress, es=None, instance="1.5a", timeout=1800, source_id=None
):
    require(
        os.name == "nt",
        "EVERYTHING_PLATFORM",
        "Live Everything acquisition requires Windows; EFU import is cross-platform",
    )
    root = no_links(Path(root))
    require(root.is_dir(), "SOURCE_DIR", "Source must be a directory")
    exe = es or shutil.which("es.exe")
    require(
        exe and Path(exe).is_file(),
        "EVERYTHING_MISSING",
        "Install voidtools es.exe, start Everything and select its instance. No silent fallback was performed.",
    )
    require(1 <= timeout <= 86400, "TIMEOUT", "Export timeout must be between 1 and 86400 seconds")
    with tempfile.TemporaryDirectory(prefix="ap20-es-") as td:
        target = Path(td) / "export.efu"
        args = es_arguments(exe, root, target, instance)
        progress.phase("Everything IPC", None, "bytes")
        started = time.monotonic()
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(args, stdout=errors, stderr=errors, shell=False)
            try:
                while process.poll() is None:
                    progress.check()
                    require(
                        time.monotonic() - started < timeout,
                        "EVERYTHING_TIMEOUT",
                        "Everything export exceeded the timeout",
                    )
                    progress.update(
                        target.stat().st_size if target.exists() else 0,
                        "Indexed export; no filesystem enumeration",
                    )
                    time.sleep(0.1)
                errors.seek(0)
                message = errors.read(8192).decode(errors="replace")
                require(
                    process.returncode == 0 and target.exists(),
                    "EVERYTHING_FAILED",
                    "ES export failed; no automatic filesystem scan occurred",
                    returncode=process.returncode,
                    stderr=message,
                )
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        result = import_efu(
            store,
            target,
            str(root),
            label,
            progress,
            source_id,
            {
                "live_ipc": True,
                "argv": args,
                "instance": instance,
                "acquisition_seconds": time.monotonic() - started,
            },
        )
        if not result["counts"]["eligible_files"]:
            store.db.execute(
                "UPDATE snapshots SET state='FAILED' WHERE id=?", (result["snapshot_id"],)
            )
            store.commit()
            raise Problem(
                "EVERYTHING_EMPTY",
                "The indexed query returned no eligible files; coverage is unproven. Verify the index, or explicitly use filesystem scanning for an empty directory.",
            )
        return result
