"""Bounded catalogue queries shared by the command line and browser interface.

Searching verified manifests does not read or verify archive payload contents.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from . import recovery
from .progress import Progress
from .store import Store
from .util import require


def metadata_selection(
    index: dict[str, Any],
    matched: set[str],
    package_namespaces: dict[str, set[str]],
    metadata: dict[str, set[str]],
) -> dict[str, Any]:
    """Describe a recoverable metadata closure without inventing absent objects.

    New catalogues declare all plan dependencies, including IDs absent from a
    partial replica. A legacy partial set cannot establish that no additional
    directory-metadata packages exist elsewhere. Completeness here covers the
    matched packages' directory metadata, never all payloads in a subtree.
    """
    present = set(package_namespaces)
    directory_packages = set().union(*metadata.values()) if metadata else set()
    namespaces = set().union(*(package_namespaces[p] for p in matched)) if matched else set()
    required = set().union(*(metadata.get(ns, set()) for ns in namespaces)) if namespaces else set()
    unknown = not matched
    declarations = index.get("directory_metadata_dependencies")
    declared = "directory_metadata_dependencies" in index
    if declared:
        recovery.check(isinstance(declarations, dict), "Invalid directory-metadata dependencies")
        recovery.check(
            len(declarations) <= index["planned_packages"],
            "Too many directory-metadata dependency declarations",
        )
        for package, dependencies in declarations.items():
            recovery.check(
                isinstance(package, str) and re.fullmatch(r"P\d{6,}", package) is not None,
                "Invalid package ID in directory-metadata dependencies",
            )
            recovery.check(
                isinstance(dependencies, list)
                and len(dependencies) <= index["planned_packages"]
                and all(
                    isinstance(item, str) and re.fullmatch(r"P\d{6,}", item) is not None
                    for item in dependencies
                ),
                "Invalid directory-metadata dependency list",
            )
            recovery.check(
                len(dependencies) == len(set(dependencies)) and package not in dependencies,
                "Duplicate or self-referencing directory-metadata dependency",
            )
        payloads = matched - directory_packages
        for package in payloads:
            if package not in declarations:
                unknown = True
                continue
            for dependency in declarations[package]:
                if dependency in present:
                    recovery.check(
                        dependency in directory_packages,
                        "Required dependency is not a directory-metadata package",
                    )
                    recovery.check(
                        package_namespaces[dependency] <= package_namespaces[package],
                        "Directory-metadata dependency belongs to a different source namespace",
                    )
                required.add(dependency)
        # A partial set containing only matching directory objects may omit more
        # metadata packages. Without a present payload declaration, their full
        # source closure is not knowable from this format's namespace mapping.
        if matched and not payloads and index["scope"] != "COMPLETE_PLAN":
            unknown = True
    elif index["scope"] != "COMPLETE_PLAN":
        unknown = True
    missing = required - present
    completeness = "missing" if missing else "unknown" if unknown else "complete"
    scope = {
        "complete": "Whole selected packages; all identified directory metadata dependencies are available",
        "missing": "Whole available selected packages; required directory metadata packages are missing from this archive set",
        "unknown": "Whole available selected packages; complete directory metadata coverage is unverified",
    }[completeness]
    return {
        "package_ids": sorted(matched | (required & present)),
        "metadata_package_ids": sorted((required & present) - matched),
        "required_metadata_package_ids": sorted(required),
        "missing_metadata_package_ids": sorted(missing),
        "metadata_completeness": completeness,
        "metadata_dependency_basis": "Declared plan dependencies"
        if declared
        else "Inferred within the logical-files-v1 profile from available manifests and archive-set scope",
        "restore_scope": scope,
    }


def find_members(
    bundle: str | Path,
    query: str,
    *,
    limit: int = 100,
    offset: int = 0,
    mode: str = "substring",
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Search sealed manifests, retaining only the requested result page in RAM.

    package_ids includes directory-only packages for matching source namespaces.
    Selecting those packages restores whole packages, not only matching members.
    """
    require(isinstance(query, str) and 0 < len(query) <= 4096, "QUERY", "Enter a path or name")
    require(mode in ("substring", "subtree"), "QUERY_MODE", "Use substring or subtree")
    require(1 <= limit <= 1000 and offset >= 0, "PAGE", "Invalid page range")
    p = progress or Progress()
    p.check()
    root, index, refs = recovery.inspect(bundle, progress=p.recovery_callback())
    needle = query.casefold() if mode == "substring" else query.rstrip("/")
    if mode == "subtree":
        recovery.parts(needle)
    p.phase("Search archive manifests", len(refs), "packages")
    p.set_overall(0, len(refs), "searched packages")
    rows: list[dict[str, Any]] = []
    matched: set[str] = set()
    metadata: dict[str, set[str]] = {}
    namespaces_by_package: dict[str, set[str]] = {}
    total = 0
    for ordinal, ref in enumerate(refs, 1):
        p.check()
        p.set_package(ref["package_id"], ordinal, len(refs))
        receipt, _, manifest = recovery.validate_receipt(
            root, ref, progress=p.recovery_callback(), hash_payload=False
        )
        p.phase("Search archive manifest", receipt["member_count"], "members")
        count = amount = 0
        directories_only = True
        package_namespaces: set[str] = set()
        for row in recovery.manifest_rows(manifest):
            count += 1
            amount += row["size"]
            directories_only = directories_only and row["kind"] == "directory"
            namespace = row["name"].split("/", 1)[0]
            package_namespaces.add(namespace)
            name = row["name"]
            match = (
                needle in name.casefold()
                if mode == "substring"
                else name == needle or name.startswith(needle + "/")
            )
            if match:
                if offset <= total < offset + limit:
                    rows.append(
                        {
                            "path": name,
                            "kind": row["kind"],
                            "size": row["size"],
                            "package_id": ref["package_id"],
                        }
                    )
                total += 1
                matched.add(ref["package_id"])
            if count % 1000 == 0:
                p.update(count, row["name"])
        recovery.check(
            count == receipt["member_count"] and amount == receipt["logical_bytes"],
            "Manifest counts differ from receipt",
        )
        if directories_only:
            for namespace in package_namespaces:
                metadata.setdefault(namespace, set()).add(ref["package_id"])
        namespaces_by_package[ref["package_id"]] = package_namespaces
        p.update(count)
        p.set_overall(ordinal, len(refs), "searched packages")
    selection = metadata_selection(index, matched, namespaces_by_package, metadata)
    p.set_package(None)
    return {
        "query": query,
        "mode": mode,
        "total": total,
        "offset": offset,
        "limit": limit,
        "rows": rows,
        "matched_package_ids": sorted(matched),
        "scope": "CATALOGUE_SEARCH",
        "archive_set_scope": index.get("scope"),
        "payload_verified": False,
        **selection,
    }


def diff_plans(
    store: Store, plan_id: str, target_plan_id: str, *, limit: int = 100, offset: int = 0
) -> dict[str, Any]:
    """Compare observations' memberships and encodings without loading a tree."""
    store.need("plans", plan_id)
    store.need("plans", target_plan_id)
    require(1 <= limit <= 1000 and offset >= 0, "PAGE", "Invalid page range")
    query = """
        WITH ids AS (
            SELECT node_id FROM members WHERE plan_id=?
            UNION SELECT node_id FROM members WHERE plan_id=?
        )
        SELECT n.id, n.kind, n.size,
               old.package_id AS before_package, new.package_id AS after_package,
               op.codec AS before_codec, np.codec AS after_codec,
               op.level AS before_level, np.level AS after_level,
               CASE WHEN old.node_id IS NULL THEN 'ADDED'
                    WHEN new.node_id IS NULL THEN 'REMOVED'
                    WHEN old.package_id != new.package_id THEN 'MOVED'
                    ELSE 'ENCODING_CHANGED' END AS change
        FROM ids JOIN nodes n ON n.id=ids.node_id
        LEFT JOIN members old ON old.node_id=n.id AND old.plan_id=?
        LEFT JOIN members new ON new.node_id=n.id AND new.plan_id=?
        LEFT JOIN packages op ON op.plan_id=old.plan_id AND op.id=old.package_id
        LEFT JOIN packages np ON np.plan_id=new.plan_id AND np.id=new.package_id
        WHERE old.node_id IS NULL OR new.node_id IS NULL
           OR old.package_id != new.package_id OR op.codec != np.codec OR op.level != np.level
    """
    args = (plan_id, target_plan_id, plan_id, target_plan_id)
    total = store.db.execute("SELECT COUNT(*) FROM (" + query + ")", args).fetchone()[0]
    rows = store.rows(query + " ORDER BY n.id LIMIT ? OFFSET ?", (*args, limit, offset))
    for row in rows:
        row["path"] = store.path(row["id"])
    return {
        "before_plan": plan_id,
        "after_plan": target_plan_id,
        "rows": rows,
        "total": total,
        "offset": offset,
        "limit": limit,
        "comparison": "Observation node membership and encoding; not a filesystem rescan",
    }
