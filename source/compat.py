"""Small, explicit runtime gates; compatibility never disables an integrity guard.

The Python interpreter and its linked SQLite library have independent versions.
SQLite 3.31 introduced trusted_schema; an older library must not silently ignore
that safety setting. Connection-local pragma results are checked on each opened
workspace/import connection, not inferred from the Python version.
"""

from __future__ import annotations

import sqlite3
import sys

from .util import Problem, require


MIN_PYTHON = (3, 8)
MIN_SQLITE = (3, 31, 0)


def require_runtime():
    require(
        sys.version_info[:2] >= MIN_PYTHON,
        "PYTHON_VERSION",
        "Archivist requires Python 3.8 or newer",
        actual=".".join(map(str, sys.version_info[:3])),
        minimum="3.8",
    )
    require(
        sqlite3.sqlite_version_info >= MIN_SQLITE,
        "SQLITE_VERSION",
        "Archivist requires SQLite 3.31.0 or newer linked to Python; trusted_schema protection cannot be disabled",
        actual=sqlite3.sqlite_version,
        minimum="3.31.0",
    )


def configure_sqlite(db, *, read_only=False):
    """Apply and read back required connection settings, or fail closed."""
    require_runtime()
    wanted = {"trusted_schema": 0, "foreign_keys": 1, "query_only": int(read_only)}
    observed = {}
    for name, expected in wanted.items():
        try:
            db.execute("PRAGMA " + name + "=" + str(expected))
            row = db.execute("PRAGMA " + name).fetchone()
        except sqlite3.Error as exc:
            raise Problem(
                "SQLITE_CAPABILITY",
                "SQLite cannot apply a required connection setting",
                setting=name,
                expected=expected,
                error=str(exc),
            ) from exc
        actual = row[0] if row else None
        require(
            actual == expected,
            "SQLITE_CAPABILITY",
            "SQLite did not confirm a required connection setting; no weaker mode was selected",
            setting=name,
            expected=expected,
            actual=actual,
        )
        observed[name] = actual
    return observed


def runtime_capabilities():
    """Return observed runtime capabilities using disposable in-memory databases.

    This can run before a workspace exists. It does not import payloads, create
    persistent files, test a particular filesystem, or qualify an operating OS.
    """
    result = {
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "python_minimum": "3.8",
        "python_supported": sys.version_info[:2] >= MIN_PYTHON,
        "sqlite_version": sqlite3.sqlite_version,
        "sqlite_minimum": "3.31.0",
        "sqlite_version_supported": sqlite3.sqlite_version_info >= MIN_SQLITE,
        "sqlite_pragmas": {},
        "sqlite_upsert": False,
        "sqlite_backup": False,
        "sqlite_read_only": False,
        "compatible": False,
        "error": None,
    }
    databases = []
    try:
        require_runtime()
        source = sqlite3.connect(":memory:")
        databases.append(source)
        result["sqlite_pragmas"] = configure_sqlite(source)
        source.execute("CREATE TABLE capabilities(key TEXT PRIMARY KEY,value INTEGER NOT NULL)")
        source.execute("INSERT INTO capabilities VALUES ('probe',1)")
        source.execute(
            "INSERT INTO capabilities VALUES ('probe',2) ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        )
        source.commit()
        result["sqlite_upsert"] = (
            source.execute("SELECT value FROM capabilities").fetchone()[0] == 2
        )
        destination = sqlite3.connect(":memory:")
        databases.append(destination)
        configure_sqlite(destination)
        source.backup(destination, pages=1)
        result["sqlite_backup"] = (
            destination.execute("SELECT value FROM capabilities").fetchone()[0] == 2
        )
        settings = configure_sqlite(source, read_only=True)
        result["sqlite_read_only"] = settings["query_only"] == 1
        require(
            result["sqlite_upsert"] and result["sqlite_backup"] and result["sqlite_read_only"],
            "SQLITE_CAPABILITY",
            "SQLite did not satisfy a required capability probe",
        )
        result["compatible"] = True
    except (Problem, sqlite3.Error, AttributeError) as exc:
        result["error"] = (
            exc.record()
            if isinstance(exc, Problem)
            else {"code": "SQLITE_CAPABILITY", "message": str(exc)}
        )
    finally:
        for db in reversed(databases):
            db.close()
    return result
