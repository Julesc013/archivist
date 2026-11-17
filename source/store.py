"""One normalized SQLite workspace. No repeated full JSON inventories or trees."""

from __future__ import annotations
import json
import os
import sqlite3
import sys
from pathlib import Path
from .compat import configure_sqlite, require_runtime
from .path_cache import PathCache
from .util import APP_ID, canonical, no_links, now, require, uid, atomic_json, json_read

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sources(id TEXT PRIMARY KEY, label TEXT NOT NULL, root TEXT NOT NULL, identity TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE snapshots(id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id), state TEXT NOT NULL, backend TEXT NOT NULL, started TEXT NOT NULL, completed TEXT, fingerprint TEXT, provenance TEXT NOT NULL, counts TEXT NOT NULL DEFAULT '{}');
CREATE TABLE nodes(id INTEGER PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES snapshots(id), parent INTEGER REFERENCES nodes(id), name TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('file','directory','link','special')), size INTEGER NOT NULL DEFAULT 0 CHECK(size>=0), mtime_ns INTEGER, ctime_ns INTEGER, mode INTEGER, device TEXT, inode TEXT, attributes INTEGER NOT NULL DEFAULT 0, eligible INTEGER NOT NULL CHECK(eligible IN (0,1)), extension TEXT NOT NULL DEFAULT '', class TEXT NOT NULL DEFAULT 'unknown', sha256 TEXT, inferred INTEGER NOT NULL DEFAULT 0, total_bytes INTEGER NOT NULL DEFAULT 0, total_files INTEGER NOT NULL DEFAULT 0, total_cost INTEGER NOT NULL DEFAULT 0, text_bytes INTEGER NOT NULL DEFAULT 0, digest BLOB, UNIQUE(snapshot_id,parent,name));
CREATE UNIQUE INDEX node_root ON nodes(snapshot_id) WHERE parent IS NULL;
CREATE INDEX node_children ON nodes(parent,kind,name);
CREATE INDEX node_scan ON nodes(snapshot_id,kind,eligible);
CREATE TABLE issues(id INTEGER PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES snapshots(id), node_id INTEGER, path TEXT NOT NULL, severity TEXT NOT NULL, code TEXT NOT NULL, detail TEXT NOT NULL);
CREATE INDEX issue_scan ON issues(snapshot_id);
CREATE TABLE plans(id TEXT PRIMARY KEY, label TEXT NOT NULL, created TEXT NOT NULL, policy TEXT NOT NULL, fingerprint TEXT NOT NULL, parent_plan TEXT, state TEXT NOT NULL, counts TEXT NOT NULL, provenance TEXT NOT NULL);
CREATE TABLE plan_sources(plan_id TEXT NOT NULL REFERENCES plans(id), snapshot_id TEXT NOT NULL REFERENCES snapshots(id), namespace TEXT NOT NULL, PRIMARY KEY(plan_id,snapshot_id), UNIQUE(plan_id,namespace));
CREATE TABLE packages(plan_id TEXT NOT NULL REFERENCES plans(id), id TEXT NOT NULL, logical_id TEXT NOT NULL, snapshot_id TEXT NOT NULL REFERENCES snapshots(id), kind TEXT NOT NULL, anchor TEXT NOT NULL, reason TEXT NOT NULL, codec TEXT NOT NULL, level INTEGER NOT NULL, logical_bytes INTEGER NOT NULL, estimated_bytes INTEGER NOT NULL, file_count INTEGER NOT NULL, dir_count INTEGER NOT NULL, status TEXT NOT NULL, PRIMARY KEY(plan_id,id));
CREATE TABLE members(plan_id TEXT NOT NULL, node_id INTEGER NOT NULL REFERENCES nodes(id), package_id TEXT NOT NULL, PRIMARY KEY(plan_id,node_id), FOREIGN KEY(plan_id,package_id) REFERENCES packages(plan_id,id));
CREATE INDEX package_members ON members(plan_id,package_id,node_id);
CREATE TABLE builds(id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES plans(id), path TEXT NOT NULL UNIQUE, state TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE destinations(id TEXT PRIMARY KEY, label TEXT NOT NULL, path TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, identity TEXT NOT NULL, capacity INTEGER, max_file INTEGER, reserve INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE replicas(id TEXT PRIMARY KEY, build_id TEXT, destination_id TEXT, path TEXT NOT NULL, state TEXT NOT NULL, created TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE operations(id TEXT PRIMARY KEY, kind TEXT NOT NULL, state TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL, arguments TEXT NOT NULL, result TEXT, error TEXT);
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE measurements(id TEXT PRIMARY KEY,plan_id TEXT NOT NULL,package_id TEXT NOT NULL,created TEXT NOT NULL,report TEXT NOT NULL);
CREATE TABLE legacy_refs(kind TEXT NOT NULL, legacy_id TEXT NOT NULL, new_id TEXT NOT NULL, fingerprint TEXT, PRIMARY KEY(kind,legacy_id));
"""


def config_directory() -> Path:
    if os.environ.get("ARCHIVIST_CONFIG_HOME"):
        return Path(os.environ["ARCHIVIST_CONFIG_HOME"]).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Archivist"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Archivist"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "archivist"


def default_workspace() -> Path:
    if os.environ.get("ARCHIVIST_WORKSPACE"):
        return Path(os.environ["ARCHIVIST_WORKSPACE"]).expanduser()
    config = config_directory() / "launcher.json"
    if config.is_file():
        data = json_read(config, 16384)
        chosen = data.get("workspace")
        require(
            isinstance(chosen, str) and Path(chosen).is_absolute(),
            "WORKSPACE_CONFIG",
            "Invalid remembered workspace; use --workspace to override",
        )
        require(
            (Path(chosen) / "workspace.sqlite").is_file(),
            "WORKSPACE_OFFLINE",
            "The remembered workspace is unavailable; reconnect it or use --workspace PATH",
            path=chosen,
        )
        return Path(chosen)
    if sys.platform == "win32":
        return config_directory() / "workspace"
    if sys.platform == "darwin":
        return config_directory() / "workspace"
    return (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        / "archivist"
        / "workspace"
    )


def remember_workspace(path):
    path = no_links(Path(path))
    require(
        (path / "workspace.sqlite").is_file(),
        "WORKSPACE_CONFIG",
        "Only an existing Archivist workspace can be remembered",
    )
    config = no_links(config_directory(), missing_ok=True)
    atomic_json(config / "launcher.json", {"format": "AP20Launcher/1", "workspace": str(path)})


class Store:
    def __init__(self, workspace: str | Path, create=True):
        require_runtime()
        self.root = no_links(Path(workspace), missing_ok=create)
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / "workspace.sqlite"
        new = not path.exists()
        require(not new or create, "WORKSPACE_MISSING", "Workspace database not found")
        require(not path.is_symlink(), "DATABASE_LINK", "Database cannot be a symbolic link")
        self.db = sqlite3.connect(path, timeout=10)
        try:
            self.db.row_factory = sqlite3.Row
            configure_sqlite(self.db)
            self.db.execute("PRAGMA busy_timeout=10000")
            self.db.execute("PRAGMA temp_store=FILE")
            self.db.execute("PRAGMA cache_size=-8192")
            if new:
                self.db.executescript(SCHEMA)
                self.db.execute(f"PRAGMA application_id={APP_ID}")
                self.db.execute("PRAGMA user_version=1")
                self.db.execute("INSERT INTO meta VALUES ('collection_id',?)", (uid("collection"),))
                self.db.execute("INSERT INTO meta VALUES ('created',?)", (now(),))
                self.db.commit()
            require(
                self.db.execute("PRAGMA application_id").fetchone()[0] == APP_ID
                and self.db.execute("PRAGMA user_version").fetchone()[0] == 1,
                "WORKSPACE_VERSION",
                "Not a supported workspace; import an evidence bundle or use explicit migration for older evidence",
            )
            mode = self.db.execute("PRAGMA journal_mode=WAL").fetchone()
            require(
                mode and str(mode[0]).lower() == "wal",
                "SQLITE_JOURNAL",
                "Workspace filesystem/runtime did not enable the required WAL journal",
            )
            self.db.execute("PRAGMA synchronous=FULL")
            require(
                self.db.execute("PRAGMA synchronous").fetchone()[0] == 2,
                "SQLITE_DURABILITY",
                "SQLite did not confirm FULL synchronization",
            )
        except BaseException:
            self.db.close()
            raise
        self._paths: PathCache[int, str] = PathCache()

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def commit(self):
        self.db.commit()

    def issue(self, snapshot, path, code, detail="", severity="warning", node_id=None):
        self.db.execute(
            "INSERT INTO issues(snapshot_id,node_id,path,severity,code,detail) VALUES (?,?,?,?,?,?)",
            (snapshot, node_id, path, severity, code, str(detail)),
        )

    def one(self, sql, args=()):
        r = self.db.execute(sql, args).fetchone()
        return dict(r) if r else None

    def rows(self, sql, args=()):
        return [dict(r) for r in self.db.execute(sql, args)]

    def need(self, table, key):
        require(
            table in ("sources", "snapshots", "plans", "destinations", "builds"),
            "TABLE",
            "Invalid object type",
        )
        row = self.one(f"SELECT * FROM {table} WHERE id=?", (key,))
        require(row is not None, "NOT_FOUND", "Object not found", kind=table, id=key)
        return row

    def path(self, node_id):
        if node_id is None:
            return ""
        if node_id in self._paths:
            return self._paths[node_id]
        chain = []
        cursor = node_id
        visited = set()
        while cursor is not None and cursor not in self._paths:
            require(
                cursor not in visited and len(visited) < 32768,
                "PARENT_CYCLE",
                "Cyclic or excessive inventory ancestry",
            )
            visited.add(cursor)
            r = self.db.execute(
                "SELECT parent,name,kind FROM nodes WHERE id=?", (cursor,)
            ).fetchone()
            require(r is not None, "NODE_MISSING", "Inventory parent is missing", node=cursor)
            chain.append((cursor, r["name"], r["kind"]))
            cursor = r["parent"]
        base = self._paths.get(cursor, "")
        for ident, name, kind in reversed(chain):
            base = (base + "/" + name).strip("/")
            # Cache directories only; never retain every complete filename in memory.
            if kind == "directory":
                self._paths[ident] = base
        return base

    def settings(self):
        return {r[0]: json.loads(r[1]) for r in self.db.execute("SELECT key,value FROM settings")}

    def set_setting(self, key, value):
        require(
            key in ("appearance", "view", "selected_plan", "selected_snapshot"),
            "SETTING",
            "Unsupported preference",
        )
        self.db.execute(
            "INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, canonical(value).decode()),
        )
        self.commit()

    def operation(self, kind, args):
        # Called only while holding the cross-process workspace writer lock.
        self.db.execute(
            "UPDATE operations SET state='INTERRUPTED',updated=? WHERE state='RUNNING'", (now(),)
        )
        op = uid("op")
        self.db.execute(
            "INSERT INTO operations VALUES (?,?,?,?,?,?,NULL,NULL)",
            (op, kind, "RUNNING", now(), now(), canonical(args).decode()),
        )
        self.commit()
        return op

    def finish(self, op, result=None, error=None):
        self.db.execute(
            "UPDATE operations SET state=?,updated=?,result=?,error=? WHERE id=?",
            (
                "FAILED" if error else "COMPLETE",
                now(),
                canonical(result).decode() if result is not None else None,
                canonical(error).decode() if error else None,
                op,
            ),
        )
        self.commit()
