"""Portable, data-only evidence transfers and explicit one-way V12/V13 migration."""

from __future__ import annotations
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
import zlib
from pathlib import Path
from .compat import configure_sqlite, require_runtime
from .inventory import InventoryBuilder
from .recovery import publish_new
from .planning import Planner, Policy
from .util import (
    APP_ID,
    atomic_json,
    canonical,
    disjoint,
    fsync_dir,
    hash_file,
    json_read,
    no_links,
    now,
    rel_parts,
    require,
    uid,
    within,
)

MAX_DATABASE = 16 * 1024**3


def readonly(path):
    require_runtime()
    path = no_links(Path(path))
    for ending in ("-wal", "-journal"):
        journal = Path(str(path) + ending)
        require(
            not (journal.exists() and journal.stat().st_size),
            "LIVE_DATABASE",
            "Stop the old writer before importing evidence with a live journal",
            path=str(path),
        )
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        db.row_factory = sqlite3.Row
        configure_sqlite(db, read_only=True)
        require(
            not db.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('view','trigger') OR UPPER(sql) LIKE 'CREATE VIRTUAL%'"
            ).fetchone(),
            "SQL_SCHEMA",
            "Executable/virtual schema objects are not accepted",
        )
    except BaseException:
        db.close()
        raise
    return db


def check_database(db):
    require(
        db.execute("PRAGMA application_id").fetchone()[0] == APP_ID
        and db.execute("PRAGMA user_version").fetchone()[0] == 1,
        "EVIDENCE_VERSION",
        "Unsupported V20 database",
    )
    require(
        db.execute("PRAGMA quick_check").fetchone()[0] == "ok",
        "SQL_INTEGRITY",
        "SQLite integrity check failed",
    )
    require(
        db.execute("PRAGMA foreign_key_check").fetchone() is None,
        "SQL_REFERENCES",
        "Broken evidence references",
    )
    require(
        not db.execute(
            "SELECT n.id FROM nodes n JOIN nodes p ON p.id=n.parent WHERE n.snapshot_id!=p.snapshot_id OR n.id<=p.id OR p.kind!='directory' LIMIT 1"
        ).fetchone(),
        "PARENT_GRAPH",
        "Invalid inventory ancestry",
    )
    require(
        not db.execute(
            "SELECT m.node_id FROM members m JOIN nodes n ON n.id=m.node_id JOIN packages p ON p.plan_id=m.plan_id AND p.id=m.package_id WHERE n.snapshot_id!=p.snapshot_id OR n.eligible!=1 LIMIT 1"
        ).fetchone(),
        "MEMBERSHIP",
        "Invalid package member references",
    )


def export_workspace(store, output, progress):
    output = no_links(Path(output), missing_ok=True)
    require(not output.exists(), "EXPORT_EXISTS", "Export destination exists; choose a new file")
    output.parent.mkdir(parents=True, exist_ok=True)
    for src in store.rows("SELECT root FROM sources"):
        if Path(src["root"]).is_dir():
            require(
                disjoint(Path(src["root"]), output),
                "EXPORT_SOURCE",
                "Evidence export must not be written inside a source",
            )
    progress.phase("Export evidence", None, "pages")
    temp = output.with_name("." + output.name + ".partial-" + uid("export"))
    with tempfile.TemporaryDirectory(prefix=".ap20-export-", dir=output.parent) as td:
        dbpath = Path(td) / "workspace.sqlite"
        target = sqlite3.connect(dbpath)
        try:
            configure_sqlite(target)
            store.db.backup(
                target,
                pages=256,
                progress=lambda status, left, total: progress.update(
                    total - left, "SQLite snapshot"
                ),
            )
            target.execute("PRAGMA journal_mode=DELETE")
            target.close()
        finally:
            try:
                target.close()
            except sqlite3.Error:
                pass
        metadata = {
            "format": "AP20Workspace/1",
            "created": now(),
            "database": "workspace.sqlite",
            "bytes": dbpath.stat().st_size,
            "sha256": hash_file(dbpath),
            "contains_payload": False,
            "contains_reusable_approvals": False,
            "description": "Observations, plans and operation history; no source files or built archives",
        }
        progress.phase("Compress evidence", metadata["bytes"], "bytes")
        with zipfile.ZipFile(
            temp, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=3, allowZip64=True
        ) as z:
            z.writestr("FORMAT.json", canonical(metadata) + b"\n")
            with z.open("workspace.sqlite", "w", force_zip64=True) as out, dbpath.open("rb") as inp:
                while block := inp.read(1024 * 1024):
                    progress.check()
                    out.write(block)
                    progress.advance(len(block))
        with temp.open("r+b") as stream:
            os.fsync(stream.fileno())
        require(not output.exists(), "EXPORT_EXISTS", "Export destination appeared")
        publish_new(temp, output)
        fsync_dir(output.parent)
    return {
        "path": str(output),
        "bytes": output.stat().st_size,
        "sha256": hash_file(output),
        "format": "AP20Workspace/1",
        "contains_payload": False,
    }


def import_workspace(source, destination, progress):
    source = no_links(Path(source))
    destination = no_links(Path(destination), missing_ok=True)
    require(not destination.exists(), "IMPORT_EXISTS", "Import requires a NEW workspace directory")
    require(
        not within(source, destination),
        "IMPORT_OVERLAP",
        "Input is inside the proposed destination",
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_name("." + destination.name + ".partial-" + uid("import"))
    temp.mkdir()
    try:
        with zipfile.ZipFile(source) as z:
            require(
                sorted(z.namelist()) == ["FORMAT.json", "workspace.sqlite"],
                "BUNDLE_MEMBERS",
                "Evidence bundle must contain exactly FORMAT.json and workspace.sqlite",
            )
            info = z.getinfo("FORMAT.json")
            require(info.file_size <= 65536, "BUNDLE_HEADER", "Oversized format descriptor")
            m = json.loads(z.read(info))
            require(
                m.get("format") == "AP20Workspace/1" and m.get("database") == "workspace.sqlite",
                "BUNDLE_VERSION",
                "Unsupported evidence bundle",
            )
            require(
                type(m.get("bytes")) is int and 0 < m["bytes"] <= MAX_DATABASE,
                "BUNDLE_SIZE",
                "Database exceeds the 16 GiB import safety limit",
            )
            require(
                z.getinfo("workspace.sqlite").file_size == m["bytes"],
                "BUNDLE_SIZE",
                "Database length differs from descriptor",
            )
            require(
                shutil.disk_usage(destination.parent).free >= m["bytes"] + 32 * 1024 * 1024,
                "IMPORT_SPACE",
                "Insufficient space for the expanded workspace",
            )
            progress.phase("Import evidence", m["bytes"], "bytes")
            h = hashlib.sha256()
            n = 0
            with z.open("workspace.sqlite") as inp, (temp / "workspace.sqlite").open("xb") as out:
                while block := inp.read(1024 * 1024):
                    progress.check()
                    n += len(block)
                    require(
                        n <= m["bytes"],
                        "BUNDLE_SIZE",
                        "Expanded database exceeds its declared size",
                    )
                    h.update(block)
                    out.write(block)
                    progress.advance(len(block))
                out.flush()
                os.fsync(out.fileno())
            require(
                n == m["bytes"] and h.hexdigest() == m.get("sha256"),
                "BUNDLE_HASH",
                "Evidence digest mismatch",
            )
        db = readonly(temp / "workspace.sqlite")
        try:
            check_database(db)
        finally:
            db.close()
        # Import is a new local binding context, not authority to write to old devices.
        db = sqlite3.connect(temp / "workspace.sqlite")
        try:
            configure_sqlite(db)
            db.execute("UPDATE destinations SET enabled=0")
            db.execute("UPDATE operations SET state='INTERRUPTED' WHERE state='RUNNING'")
            for row in db.execute("SELECT id,identity FROM sources").fetchall():
                identity = json.loads(row[1])
                identity["unbound"] = True
                db.execute(
                    "UPDATE sources SET identity=? WHERE id=?",
                    (canonical(identity).decode(), row[0]),
                )
            db.commit()
        finally:
            db.close()
        atomic_json(
            temp / "IMPORT.json",
            {
                "format": "AP20Import/1",
                "source_sha256": hash_file(source),
                "original_database_sha256": m["sha256"],
                "created": now(),
                "sources_require_binding": True,
                "destinations_disabled": True,
            },
        )
        require(not destination.exists(), "IMPORT_EXISTS", "Import destination appeared")
        publish_new(temp, destination)
        fsync_dir(destination.parent)
        return {
            "workspace": str(destination),
            "state": "IMPORTED_UNBOUND",
            "source_sha256": hash_file(source),
            "contains_payload": False,
        }
    except BaseException:
        # Owned partial directory is retained; the intended workspace is not published.
        raise


def export_inventory(store, snapshot, output, progress):
    scan = store.need("snapshots", snapshot)
    output = no_links(Path(output), missing_ok=True)
    require(not output.exists(), "EXPORT_EXISTS", "Inventory export must use a new filename")
    output.parent.mkdir(parents=True, exist_ok=True)
    for src in store.rows("SELECT root FROM sources"):
        if Path(src["root"]).is_dir():
            require(
                disjoint(Path(src["root"]), output),
                "EXPORT_SOURCE",
                "Do not write an export inside a source",
            )
    progress.phase("Export records", json.loads(scan["counts"]).get("observations"), "records")
    n = 0
    partial = output.with_name(output.name + ".partial-" + uuid_short())
    with partial.open("xb") as raw, gzip.GzipFile(
        filename="", fileobj=raw, mode="wb", mtime=0
    ) as out:
        out.write(
            canonical(
                {
                    "format": "AP20InventoryJSONL/1",
                    "snapshot": scan,
                    "source": store.need("sources", scan["source_id"]),
                }
            )
            + b"\n"
        )
        for row in store.db.execute(
            "SELECT * FROM nodes WHERE snapshot_id=? ORDER BY id", (snapshot,)
        ):
            r = dict(row)
            r["path"] = store.path(r["id"])
            r["digest"] = r["digest"].hex() if r["digest"] else None
            out.write(canonical({"record": "node", **r}) + b"\n")
            n += 1
            progress.update(n)
        for row in store.db.execute(
            "SELECT * FROM issues WHERE snapshot_id=? ORDER BY id", (snapshot,)
        ):
            out.write(canonical({"record": "issue", **dict(row)}) + b"\n")
    with partial.open("r+b") as f:
        os.fsync(f.fileno())
    publish_new(partial, output)
    fsync_dir(output.parent)
    return {
        "path": str(output),
        "records": n,
        "sha256": hash_file(output),
        "format": "AP20InventoryJSONL/1",
    }


def uuid_short():
    return uid("export")


def unpack_legacy(value):
    if isinstance(value, bytes):
        require(value.startswith(b"APJ1\0"), "LEGACY_ENCODING", "Unknown legacy JSON encoding")
        d = zlib.decompressobj()
        raw = d.decompress(value[5:], 64 * 1024 * 1024 + 1)
        require(
            len(raw) <= 64 * 1024 * 1024 and d.eof and not d.unused_data and not d.unconsumed_tail,
            "LEGACY_LIMIT",
            "Invalid or oversized legacy metadata",
        )
        value = raw.decode("utf-8")
    return json.loads(value)


def verified_legacy_database(folder, descriptor_name, database_name):
    seals = json_read(folder / "SHA256SUMS.json")
    for name in (descriptor_name, database_name):
        require(
            name in seals and hash_file(no_links(folder / name)) == seals[name],
            "LEGACY_HASH",
            "Legacy evidence failed its seal",
            path=str(folder / name),
        )
    return readonly(folder / database_name)


def migrate_legacy(store, source, progress):
    """Read-only conversion, no import of legacy executable modules or approvals.

    Logical membership is preserved for supported PAX codecs. An unsupported old
    plan is retained as a reference entry, never silently converted to another codec.
    """
    source = no_links(Path(source))
    require(
        disjoint(source, store.root), "MIGRATION_OVERLAP", "Old and new workspaces must be separate"
    )
    inventories = (
        [source]
        if (source / "inventory.json").is_file()
        else sorted(p.parent for p in source.glob("*/inventory.json"))
    )
    require(inventories, "LEGACY_MISSING", "No completed legacy inventories were found")
    mapping = {}
    results = []
    plans = []
    notes = []
    for folder in inventories:
        progress.check()
        old = json_read(folder / "inventory.json")
        oldid = folder.name
        require(
            old.get("schema_version") in (4, 5, 6)
            and old.get("state") in ("COMPLETE", "COMPLETE_WITH_ISSUES"),
            "LEGACY_VERSION",
            "Only completed V12/V13-compatible inventories can migrate",
        )
        prior = store.one(
            "SELECT * FROM legacy_refs WHERE kind='inventory' AND legacy_id=?", (oldid,)
        )
        if prior:
            require(
                prior["fingerprint"] == old.get("metadata_fingerprint"),
                "LEGACY_COLLISION",
                "Legacy ID now refers to different evidence",
            )
            mapping[oldid] = prior["new_id"]
            results.append({"legacy_id": oldid, "snapshot_id": prior["new_id"], "reused": True})
            continue
        db = verified_legacy_database(folder, "inventory.json", "inventory.sqlite")
        builder = None
        try:
            builder = InventoryBuilder(
                store,
                old["root"],
                old.get("source_id") or oldid,
                "legacy-import",
                {
                    "legacy_id": oldid,
                    "legacy_fingerprint": old.get("metadata_fingerprint"),
                    "database_sha256": hash_file(folder / "inventory.sqlite"),
                    "source_completeness_proven": False,
                },
                progress,
            )
            # Migration never binds an old absolute path as permission to read it.
            store.db.execute(
                "UPDATE sources SET identity=? WHERE id=?",
                (canonical({"unbound": True, "legacy": True}).decode(), builder.sid),
            )
            progress.phase(
                "Migrate inventory",
                old.get("file_count", 0) + old.get("directory_count", 0),
                "entries",
            )
            for n, row in enumerate(db.execute("SELECT * FROM entries ORDER BY path"), 1):
                r = dict(row)
                meta = unpack_legacy(r["metadata"])
                path = r["path"]
                builder.counts["input_rows"] += 1
                mode = int(meta["st_mode"]) & 0o777 if meta.get("st_mode") is not None else None
                builder.add(
                    path,
                    r["kind"]
                    if r["kind"] in ("file", "directory", "link", "special")
                    else "special",
                    size=r["size"] or 0,
                    mtime_ns=int(r["mtime_ns"]) if r["mtime_ns"] is not None else None,
                    ctime_ns=int(meta["st_ctime_ns"])
                    if meta.get("st_ctime_ns") is not None
                    else None,
                    mode=mode,
                    device=meta.get("st_dev"),
                    inode=meta.get("st_ino"),
                    attributes=r.get("attributes") or 0,
                    eligible=bool(r["eligible"]),
                    sha256=r.get("sha256"),
                    inferred=bool(r.get("inferred")),
                )
                builder.counts["accepted_rows" if r["eligible"] else "excluded_rows"] += 1
                progress.update(n, path)
            for issue in db.execute("SELECT * FROM issues"):
                r = dict(issue)
                builder.issue(
                    r.get("path", ""),
                    r.get("code", "LEGACY_ISSUE"),
                    r.get("detail", ""),
                    r.get("severity", "warning"),
                )
            record = builder.finish()
            mapping[oldid] = record["snapshot_id"]
            store.db.execute(
                "INSERT INTO legacy_refs VALUES (?,?,?,?)",
                ("inventory", oldid, record["snapshot_id"], old.get("metadata_fingerprint")),
            )
            store.commit()
            results.append(
                {"legacy_id": oldid, "snapshot_id": record["snapshot_id"], "reused": False}
            )
        except BaseException as exc:
            if builder:
                builder.failed(exc)
            raise
        finally:
            db.close()
    plan_root = source / "plans"
    for descriptor in sorted(plan_root.glob("*/plan.json")) if plan_root.is_dir() else []:
        progress.check()
        oldid = descriptor.parent.name
        desc = json_read(descriptor)
        if desc.get("format") != "org.archiveplanner.plan":
            notes.append(
                {
                    "plan": oldid,
                    "status": "REFERENCE_ONLY",
                    "reason": "Older non-compact plan; replan its imported inventory",
                }
            )
            continue
        prior = store.one("SELECT * FROM legacy_refs WHERE kind='plan' AND legacy_id=?", (oldid,))
        if prior:
            require(
                prior["fingerprint"] == desc.get("decision_fingerprint"),
                "LEGACY_COLLISION",
                "Legacy plan identity collision",
            )
            plans.append({"legacy_id": oldid, "plan_id": prior["new_id"], "reused": True})
            continue
        db = verified_legacy_database(descriptor.parent, "plan.json", "plan.sqlite")
        try:
            header = unpack_legacy(db.execute("SELECT value FROM document").fetchone()[0])
            templates = [
                unpack_legacy(r[0])
                for r in db.execute("SELECT template FROM packages ORDER BY ord")
            ]
            supported = all(
                p.get("codec", {}).get("name") in ("none", "gzip", "zstd")
                and p.get("codec", {}).get("container", "pax") == "pax"
                for p in templates
            )
            if not supported:
                notes.append(
                    {
                        "plan": oldid,
                        "status": "REFERENCE_ONLY",
                        "reason": "Contains a container or codec not executable in V20; imported scans remain available",
                    }
                )
                continue
            sources = [s["inventory_id"] for s in header["sources"]]
            require(
                all(s in mapping for s in sources),
                "LEGACY_SOURCES",
                "Legacy plan references an inventory outside this migration",
            )
            opt = header["options"]
            policy = Policy(
                minimum=int(opt.get("min_bytes", 0)),
                target=int(
                    opt.get("target_bytes")
                    or min(100_000_000_000, opt.get("max_bytes", 200_000_000_000))
                ),
                maximum=int(opt.get("max_bytes", 200_000_000_000)),
                outer_depth=int(opt.get("depth", 4)),
            )
            planner = Planner(
                store,
                policy,
                progress,
                header.get("label", "Migrated plan"),
                [mapping[s] for s in sources],
            )
            ns_to_inv = {
                s["source_id"] + "/" + s["run_id"]: s["inventory_id"] for s in header["sources"]
            }
            for template in templates:
                inv = ns_to_inv[template["source_namespace"]]
                snapshot = mapping[inv]
                pid = planner.new_package(
                    snapshot,
                    "directories" if template["kind"] == "directories" else "data",
                    template.get("anchor", ""),
                    "MIGRATED_MEMBERSHIP",
                    template["codec"]["name"],
                )
                level = 6 if template["codec"]["name"] == "gzip" else 3
                for arg in template["codec"].get("arguments", []):
                    if re_numeric_flag(arg):
                        level = int(arg[1:])
                Policy(codec=template["codec"]["name"], level=level).validate()
                store.db.execute(
                    "UPDATE packages SET level=? WHERE plan_id=? AND id=?", (level, planner.id, pid)
                )
                for block in db.execute(
                    "SELECT value,digest FROM member_blocks WHERE package_id=? ORDER BY first_member",
                    (template["id"],),
                ):
                    rows = unpack_legacy(block[0])
                    raw = (
                        json.dumps(
                            rows, ensure_ascii=True, allow_nan=False, separators=(",", ":")
                        ).encode()
                        + b"\n"
                    )
                    require(
                        hashlib.sha256(raw).hexdigest() == block[1],
                        "LEGACY_BLOCK",
                        "Legacy plan membership block digest mismatch",
                    )
                    for member in rows:
                        path = member["path"]
                        parent = None
                        node = None
                        for name in [""] + rel_parts(path, True):
                            node = store.one(
                                "SELECT id,kind FROM nodes WHERE snapshot_id=? AND parent IS ? AND name=?",
                                (snapshot, parent, name),
                            )
                            require(
                                node is not None,
                                "LEGACY_MEMBER",
                                "Old plan member is absent from its imported inventory",
                                path=path,
                            )
                            parent = node["id"]
                        planner.add_node(pid, node["id"])
            # V20 additionally preserves the source-root directory metadata once.
            for snapshot in [mapping[s] for s in sources]:
                root = store.one(
                    "SELECT id FROM nodes WHERE snapshot_id=? AND parent IS NULL", (snapshot,)
                )["id"]
                if not store.one(
                    "SELECT node_id FROM members WHERE plan_id=? AND node_id=?", (planner.id, root)
                ):
                    pid = planner.new_package(
                        snapshot, "directories", "", "SOURCE_ROOT_METADATA", "none"
                    )
                    planner.add_node(pid, root)
            migrated = planner.finish(
                {
                    "legacy_plan": oldid,
                    "legacy_decision_fingerprint": desc["decision_fingerprint"],
                    "file_membership_preserved": True,
                    "root_directory_metadata_added": True,
                    "execution_approvals_imported": False,
                }
            )
            store.db.execute(
                "INSERT INTO legacy_refs VALUES (?,?,?,?)",
                ("plan", oldid, migrated["id"], desc["decision_fingerprint"]),
            )
            store.commit()
            plans.append({"legacy_id": oldid, "plan_id": migrated["id"], "reused": False})
        except BaseException:
            store.db.rollback()
            raise
        finally:
            db.close()
    return {
        "inventories": results,
        "plans": plans,
        "notes": notes,
        "old_evidence_modified": False,
        "sources_require_binding": True,
    }


def re_numeric_flag(value):
    return isinstance(value, str) and value.startswith("-") and value[1:].isdigit()
