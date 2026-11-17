"""One application boundary used by CLI and HTTP. No presentation code lives here."""

from __future__ import annotations
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from . import __version__
from . import artifacts, catalogue, destinations, evidence, inventory, planning, recovery, sampling
from .compat import require_runtime, runtime_capabilities
from .progress import Progress
from .store import Store, default_workspace
from .util import (
    Problem,
    canonical,
    digest,
    disjoint,
    hash_file,
    locked,
    no_links,
    require,
    root_identity,
    within,
)

READ_ACTIONS = frozenset(
    (
        "status",
        "sources",
        "scans",
        "browse",
        "types",
        "issues",
        "plans",
        "packages",
        "package",
        "plan_diff",
        "members",
        "destinations",
        "builds",
        "replicas",
        "recovery_find",
        "history",
        "doctor",
        "preflight_build",
        "preflight_copy",
        "preflight_restore",
        "allocate",
        "preferences",
    )
)
WRITE_ACTIONS = frozenset(
    (
        "scan",
        "import_efu",
        "plan",
        "revise",
        "revert",
        "bind",
        "destination",
        "build",
        "copy",
        "verify",
        "restore",
        "export",
        "import",
        "migrate",
        "sample",
        "set_preferences",
        "export_inventory",
    )
)


def decoded_record(row, keys):
    if row:
        for key in keys:
            if isinstance(row.get(key), str):
                row[key] = json.loads(row[key])
    return row


def diagnose_runtime(workspace=None):
    """Read-only environment diagnostics, usable before creating a workspace."""
    runtime = runtime_capabilities()
    version = None
    exe = shutil.which("zstd")
    if exe:
        try:
            version = subprocess.run(
                [exe, "--version"], capture_output=True, text=True, timeout=5
            ).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    es = shutil.which("es.exe") if os.name == "nt" else None
    checks = [
        {
            "id": "python",
            "label": "Python",
            "state": "ready" if runtime["python_supported"] else "unsupported",
            "detail": runtime["python_version"],
            "action": "Python 3.8 or newer is required; use a maintained interpreter where available.",
        },
        {
            "id": "sqlite",
            "label": "Evidence database",
            "state": "ready" if runtime["compatible"] else "unsupported",
            "detail": runtime["sqlite_version"],
            "action": "SQLite 3.31+ with working UPSERT, backup and verified safety pragmas is required. "
            + (
                runtime["error"]["message"]
                if runtime["error"]
                else "Use export to transfer a checked workspace."
            ),
        },
        {
            "id": "zstd",
            "label": "Zstandard (optional)",
            "state": "ready" if version else ("unverified" if exe else "missing"),
            "detail": version or exe or "Not on PATH",
            "action": "Install zstd for .tar.zst; uncompressed TAR and gzip are available without it.",
        },
        {
            "id": "everything",
            "label": "Everything acquisition",
            "state": ("unverified" if es else "missing") if os.name == "nt" else "not_applicable",
            "detail": es
            or (
                "es.exe was not found on PATH"
                if os.name == "nt"
                else "Windows-only optional acquisition adapter"
            ),
            "action": "On Windows run Everything 1.5 and configure es.exe. Presence does not prove live IPC; a scan checks it. Choose filesystem scanning explicitly if desired.",
        },
        {
            "id": "ltfs",
            "label": "Mounted LTFS",
            "state": "unverified",
            "detail": "Experimental Linux adapter; no physical hardware qualification in this release",
            "action": "Use the documented mount, flush, reload and readback procedure before relying on a cartridge.",
        },
    ]
    selected_workspace = None
    workspace_error = None
    try:
        selected_workspace = str(Path(workspace or default_workspace()).expanduser().absolute())
    except Exception as exc:
        # Diagnostics must remain available when remembered configuration cannot
        # resolve. This block performs no workspace creation or state repair.
        workspace_error = (
            exc.record()
            if isinstance(exc, Problem)
            else {"code": type(exc).__name__, "message": str(exc)}
        )
        candidate = (
            workspace_error.get("detail", {}).get("path")
            if workspace_error["code"] == "WORKSPACE_OFFLINE"
            else None
        )
        if isinstance(candidate, str):
            selected_workspace = candidate
        checks.append(
            {
                "id": "workspace",
                "label": "Workspace selection",
                "state": "unavailable",
                "detail": workspace_error["message"],
                "action": "Reconnect the remembered workspace or use --workspace PATH to select another location.",
            }
        )
    return {
        "version": __version__,
        "python": sys.version,
        "platform": platform.platform(),
        "sqlite": sqlite3.sqlite_version,
        "workspace": selected_workspace,
        "workspace_error": workspace_error,
        "runtime": runtime,
        "zstd": {"path": exe, "version": version},
        "everything_cli": es,
        "checks": checks,
        "capabilities": {
            "pax_tar": True,
            "gzip": True,
            "zstd": bool(version),
            "disk": True,
            "ltfs_linux": "experimental, mounted only",
            "raw_tape": False,
            "optical_burning": False,
            "full_filesystem_image": False,
        },
        "running_as_root": bool(hasattr(os, "geteuid") and os.geteuid() == 0),
    }


class Application:
    def __init__(self, workspace=None):
        require_runtime()
        self.workspace = no_links(Path(workspace or default_workspace()), missing_ok=True)
        with locked(self.workspace / ".initialise.lock"):
            with Store(self.workspace):
                pass

    def call(self, action, arguments=None, progress=None):
        require(
            action in READ_ACTIONS | WRITE_ACTIONS, "ACTION", "Unknown operation", action=action
        )
        args = arguments or {}
        require(isinstance(args, dict), "ARGUMENTS", "Operation arguments must be an object")
        p = progress or Progress()
        if action in READ_ACTIONS:
            with Store(self.workspace) as s:
                return self._read(s, action, args, p)
        with locked(self.workspace / ".writer.lock"):
            with Store(self.workspace) as s:
                op = s.operation(action, args)
                try:
                    result = self._write(s, action, args, p)
                    s.finish(op, result=result)
                    return result
                except BaseException as exc:
                    s.db.rollback()
                    error = (
                        exc.record()
                        if isinstance(exc, Problem)
                        else {"code": type(exc).__name__, "message": str(exc)}
                    )
                    if hasattr(exc, "kit_recovery_error"):
                        error["kit_recovery_error"] = exc.kit_recovery_error
                    error["events"] = list(p.events)[-50:]
                    s.finish(op, error=error)
                    raise

    def _read(self, s, action, a, p):
        limit = int(a.get("limit", 100))
        offset = int(a.get("offset", 0))
        require(1 <= limit <= 1000 and offset >= 0, "PAGE", "Invalid page range")
        if action == "status":
            counts = {
                name: s.db.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
                for name in ("sources", "snapshots", "plans", "builds", "destinations", "replicas")
            }
            return {
                "version": __version__,
                "workspace": str(s.root),
                "collection_id": s.db.execute(
                    "SELECT value FROM meta WHERE key='collection_id'"
                ).fetchone()[0],
                "counts": counts,
                "storage_bytes": sum(f.stat().st_size for f in s.root.iterdir() if f.is_file()),
                "preferences": s.settings(),
                "preservation": "logical-files-v1",
                "hardware_qualified": False,
            }
        if action == "sources":
            return [
                decoded_record(r, ["identity"])
                for r in s.rows("SELECT * FROM sources ORDER BY created DESC")
            ]
        if action == "scans":
            return [
                decoded_record(r, ["provenance", "counts"])
                for r in s.rows(
                    "SELECT sn.*,so.label,so.root FROM snapshots sn JOIN sources so ON so.id=sn.source_id ORDER BY started DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            ]
        if action == "browse":
            scan = s.need("snapshots", a["snapshot_id"])
            parent = a.get("node_id")
            if parent is None:
                parent = s.one(
                    "SELECT id FROM nodes WHERE snapshot_id=? AND parent IS NULL", (scan["id"],)
                )["id"]
            node = s.one(
                "SELECT id,parent,name,kind,total_bytes,total_files FROM nodes WHERE id=? AND snapshot_id=?",
                (int(parent), scan["id"]),
            )
            require(node is not None, "NODE", "Directory not found")
            rows = s.rows(
                "SELECT id,parent,name,kind,size,mtime_ns,mode,eligible,extension,class,total_bytes,total_files,sha256 FROM nodes WHERE parent=? ORDER BY CASE kind WHEN 'directory' THEN 0 ELSE 1 END,name LIMIT ? OFFSET ?",
                (parent, limit, offset),
            )
            for r in rows:
                r["path"] = s.path(r["id"])
            return {
                "directory": {**node, "path": s.path(node["id"])},
                "rows": rows,
                "total": s.db.execute(
                    "SELECT COUNT(*) FROM nodes WHERE parent=?", (parent,)
                ).fetchone()[0],
                "offset": offset,
                "limit": limit,
                "scan": decoded_record(scan, ["counts", "provenance"]),
            }
        if action == "types":
            sid = a["snapshot_id"]
            s.need("snapshots", sid)
            return {
                "rows": s.rows(
                    "SELECT extension,class,COUNT(*) files,SUM(size) bytes,SUM(eligible=0) excluded FROM nodes WHERE snapshot_id=? AND kind='file' GROUP BY extension,class ORDER BY bytes DESC,extension LIMIT ? OFFSET ?",
                    (sid, limit, offset),
                ),
                "total": s.db.execute(
                    "SELECT COUNT(DISTINCT extension) FROM nodes WHERE snapshot_id=? AND kind='file'",
                    (sid,),
                ).fetchone()[0],
            }
        if action == "issues":
            return s.rows(
                "SELECT * FROM issues WHERE snapshot_id=? ORDER BY CASE severity WHEN 'error' THEN 0 ELSE 1 END,id LIMIT ? OFFSET ?",
                (a["snapshot_id"], limit, offset),
            )
        if action == "plans":
            return [
                decoded_record(r, ["policy", "counts", "provenance"])
                for r in s.rows(
                    "SELECT * FROM plans ORDER BY created DESC LIMIT ? OFFSET ?", (limit, offset)
                )
            ]
        if action == "packages":
            plan = decoded_record(s.need("plans", a["plan_id"]), ["policy", "counts", "provenance"])
            clauses = ["plan_id=?"]
            values = [plan["id"]]
            if a.get("query"):
                require(
                    isinstance(a["query"], str) and len(a["query"]) <= 4096,
                    "QUERY",
                    "Invalid package search",
                )
                clauses.append("(INSTR(LOWER(id),LOWER(?))>0 OR INSTR(LOWER(anchor),LOWER(?))>0)")
                values.extend([a["query"], a["query"]])
            if a.get("kind"):
                require(
                    a["kind"] in ("data", "directories"), "PACKAGE_KIND", "Unknown package kind"
                )
                clauses.append("kind=?")
                values.append(a["kind"])
            if a.get("snapshot_id"):
                clauses.append("snapshot_id=?")
                values.append(a["snapshot_id"])
            if a.get("exclude_package_id"):
                clauses.append("id!=?")
                values.append(a["exclude_package_id"])
            where = " AND ".join(clauses)
            packages = s.rows(
                "SELECT * FROM packages WHERE " + where + " ORDER BY id LIMIT ? OFFSET ?",
                (*values, limit, offset),
            )
            total = s.db.execute("SELECT COUNT(*) FROM packages WHERE " + where, values).fetchone()[
                0
            ]
            return {
                "plan": plan,
                "packages": packages,
                "total": total,
                "offset": offset,
                "limit": limit,
                "sources": s.rows(
                    "SELECT ps.*,so.label,so.root FROM plan_sources ps JOIN snapshots sn ON sn.id=ps.snapshot_id JOIN sources so ON so.id=sn.source_id WHERE plan_id=?",
                    (plan["id"],),
                ),
            }
        if action == "package":
            s.need("plans", a["plan_id"])
            row = s.one(
                "SELECT * FROM packages WHERE plan_id=? AND id=?", (a["plan_id"], a["package_id"])
            )
            require(row is not None, "NOT_FOUND", "Package not found", package_id=a["package_id"])
            return row
        if action == "plan_diff":
            return catalogue.diff_plans(
                s, a["plan_id"], a["target_plan_id"], limit=limit, offset=offset
            )
        if action == "members":
            pid = a["plan_id"]
            package = a["package_id"]
            rows = s.rows(
                "SELECT n.id,n.name,n.kind,n.size,n.mtime_ns,n.mode,n.class,n.extension,n.sha256 FROM members m JOIN nodes n ON n.id=m.node_id WHERE m.plan_id=? AND m.package_id=? ORDER BY n.id LIMIT ? OFFSET ?",
                (pid, package, limit, offset),
            )
            for r in rows:
                r["path"] = s.path(r["id"])
            return {
                "rows": rows,
                "total": s.db.execute(
                    "SELECT COUNT(*) FROM members WHERE plan_id=? AND package_id=?", (pid, package)
                ).fetchone()[0],
            }
        if action == "destinations":
            return [
                decoded_record(r, ["identity"])
                for r in s.rows("SELECT * FROM destinations ORDER BY label")
            ]
        if action == "builds":
            return [
                decoded_record(r, ["detail"])
                for r in s.rows(
                    "SELECT * FROM builds ORDER BY created DESC LIMIT ? OFFSET ?", (limit, offset)
                )
            ]
        if action == "replicas":
            clauses = []
            values = []
            for key in ("build_id", "destination_id"):
                if a.get(key):
                    clauses.append(key + "=?")
                    values.append(a[key])
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            return [
                decoded_record(r, ["detail"])
                for r in s.rows(
                    "SELECT * FROM replicas" + where + " ORDER BY created DESC,id LIMIT ? OFFSET ?",
                    (*values, limit, offset),
                )
            ]
        if action == "recovery_find":
            return catalogue.find_members(
                a["bundle"],
                a["query"],
                limit=limit,
                offset=offset,
                mode=a.get("mode", "substring"),
                progress=p,
            )
        if action == "history":
            return [
                decoded_record(r, ["arguments", "result", "error"])
                for r in s.rows(
                    "SELECT * FROM operations ORDER BY created DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            ]
        if action == "doctor":
            return diagnose_runtime(self.workspace)
        if action == "preflight_build":
            return artifacts.preflight_build(s, progress=p, **a)
        if action == "preflight_copy":
            return destinations.preflight_copy(s, progress=p, **a)
        if action == "preflight_restore":
            return self.restore_review(**a)
        if action == "allocate":
            return planning.allocate_plan(
                s, a["plan_id"], a["media"], bundle=a.get("bundle"), progress=p
            )
        if action == "preferences":
            return s.settings()
        raise Problem("ACTION", "Unknown read operation")

    def _write(self, s, action, a, p):
        if action == "scan":
            root = a["root"]
            backend = a.get("backend") or ("everything" if os.name == "nt" else "filesystem")
            require(
                backend in ("everything", "filesystem", "auto"),
                "BACKEND",
                "Unknown acquisition backend",
            )
            require(
                not within(Path(root).resolve(), s.root),
                "SOURCE_WORKSPACE",
                "A source cannot be the working-evidence directory or its descendant",
            )
            label = a.get("label")
            source_id = a.get("source_id")
            if backend == "everything" or (backend == "auto" and os.name == "nt"):
                require(
                    not a.get("hash_files"),
                    "INDEX_HASH_MODE",
                    "Indexed acquisition does not read file contents. Choose the filesystem backend with --hash-files for a content-hashed inventory; every build hashes the actual archived bytes.",
                )
                require(
                    not a.get("cross_mounts"),
                    "INDEX_MOUNT_MODE",
                    "Cross-mount policy applies to filesystem scanning, not Everything indexing.",
                )
                try:
                    return inventory.scan_everything(
                        s,
                        root,
                        label,
                        p,
                        es=a.get("es"),
                        instance=a.get("instance", "1.5a"),
                        timeout=a.get("timeout", 1800),
                        source_id=source_id,
                    )
                except (OSError, Problem) as exc:
                    if backend != "auto":
                        raise
                    p.event("WARN", "EVERYTHING_FALLBACK", reason=str(exc))
                    result = inventory.scan_filesystem(
                        s, root, label, p, hash_files=bool(a.get("hash_files")), source_id=source_id
                    )
                    scan = s.need("snapshots", result["snapshot_id"])
                    provenance = json.loads(scan["provenance"])
                    provenance.update(backend_requested="auto", fallback_reason=str(exc))
                    s.db.execute(
                        "UPDATE snapshots SET provenance=? WHERE id=?",
                        (canonical(provenance).decode(), result["snapshot_id"]),
                    )
                    s.commit()
                    result["fallback_reason"] = str(exc)
                    return result
            return inventory.scan_filesystem(
                s,
                root,
                label,
                p,
                hash_files=bool(a.get("hash_files")),
                source_id=source_id,
                cross_mounts=bool(a.get("cross_mounts")),
            )
        if action == "import_efu":
            return inventory.import_efu(s, a["input"], a["root"], a.get("label"), p)
        if action == "plan":
            return planning.create_plan(
                s, a["snapshots"], p, label=a.get("label", "Archive plan"), policy=a.get("policy")
            )
        if action == "revise":
            return planning.revise_plan(
                s,
                a["plan_id"],
                p,
                codec_changes=a.get("codec_changes"),
                merge=a.get("merge"),
                move=a.get("move"),
            )
        if action == "revert":
            return planning.revert_plan(s, a["plan_id"], a["target_plan_id"], p)
        if action == "bind":
            src = s.need("sources", a["source_id"])
            root = no_links(Path(a["root"]))
            require(root.is_dir(), "SOURCE_DIR", "Binding needs an existing directory")
            require(
                disjoint(root, s.root),
                "BIND_WORKSPACE",
                "Bound root must be separate from the working evidence",
            )
            identity = {**root_identity(root), "rebound": True, "binding_only": True}
            s.db.execute(
                "UPDATE sources SET root=?,identity=? WHERE id=?",
                (str(root), canonical(identity).decode(), src["id"]),
            )
            s.commit()
            return {
                "source_id": src["id"],
                "root": str(root),
                "state": "BOUND",
                "warning": "Binding is not a content verification. Build still checks each recorded file and any scan hashes.",
            }
        if action == "destination":
            return destinations.register(s, **a)
        if action == "build":
            return artifacts.build(s, progress=p, **a)
        if action == "copy":
            return destinations.copy(s, progress=p, **a)
        if action == "verify":
            return recovery.run(
                a["bundle"], packages=a.get("packages"), progress=artifacts.recovery_progress(p)
            )
        if action == "restore":
            review = self.restore_review(
                a["bundle"], a["output"], a.get("packages"), bool(a.get("permissions"))
            )
            require(
                a.get("approval") == review["approval"],
                "APPROVAL",
                "Restore requires current destination confirmation",
                required=review["approval"],
            )
            for src in s.rows("SELECT root FROM sources"):
                if Path(src["root"]).is_dir():
                    require(
                        disjoint(Path(src["root"]), Path(a["output"])),
                        "RESTORE_SOURCE",
                        "Restore must not overlap a source",
                    )
            return recovery.run(
                a["bundle"],
                a["output"],
                a.get("packages"),
                artifacts.recovery_progress(p),
                bool(a.get("permissions")),
            )
        if action == "export":
            return evidence.export_workspace(s, a["output"], p)
        if action == "import":
            return evidence.import_workspace(a["input"], a["output"], p)
        if action == "migrate":
            return evidence.migrate_legacy(s, a["input"], p)
        if action == "sample":
            return sampling.sample(
                s, a["plan_id"], a["package_id"], p, a.get("max_bytes", 32 * 1024 * 1024)
            )
        if action == "export_inventory":
            return evidence.export_inventory(s, a["snapshot_id"], a["output"], p)
        if action == "set_preferences":
            for key, value in a.items():
                if key == "appearance":
                    require(
                        value in ("system", "light", "dark"),
                        "APPEARANCE",
                        "Choose system, light or dark",
                    )
                elif key == "view":
                    require(
                        value in ("sources", "plan", "archive", "restore"), "VIEW", "Unknown view"
                    )
                else:
                    require(
                        value is None or (isinstance(value, str) and len(value) < 128),
                        "PREFERENCE",
                        "Invalid selection",
                    )
                s.set_setting(key, value)
            return s.settings()
        raise Problem("ACTION", "Unknown write operation")

    @staticmethod
    def restore_review(bundle, output, packages=None, permissions=False):
        root, index, refs = recovery.inspect(bundle, packages)
        output = no_links(Path(output), missing_ok=True)
        require(
            not output.exists() and output.parent.is_dir(),
            "RESTORE_OUTPUT",
            "Choose a new directory under an existing parent",
        )
        require(
            disjoint(root, output),
            "RESTORE_OVERLAP",
            "Restore output must not overlap the archive set",
        )
        total = members = 0
        for ref in refs:
            receipt, _, _ = recovery.validate_receipt(root, ref, hash_payload=False)
            total += receipt["logical_bytes"]
            members += receipt["member_count"]
        require(
            shutil.disk_usage(output.parent).free >= total + 16 * 1024 * 1024,
            "RESTORE_SPACE",
            "Insufficient expanded restore space",
        )
        value = {
            "operation": "restore",
            "archive_set": str(root),
            "catalogue_sha256": hash_file(root / "ARCHIVE.json"),
            "output": str(output),
            "packages": [r["package_id"] for r in refs],
            "logical_bytes": total,
            "members": members,
            "permissions": bool(permissions),
            **recovery.selection_evidence(index, refs),
        }
        value["approval"] = digest(value)
        return value
