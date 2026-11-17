"""Directory-first planning using indexed observations; never reads source payloads."""

from __future__ import annotations
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from . import capacity
from .util import canonical, now, require, uid

PACKAGE_OVERHEAD = 10240


@dataclass(frozen=True)
class Policy:
    minimum: int = 10_000_000_000
    target: int = 100_000_000_000
    maximum: int = 200_000_000_000
    keep_whole: int = 0
    merge_below: int = 0
    codec: str = "auto"
    level: int = 3
    text_fraction: float = 0.60
    text_minimum: int = 1_000_000_000
    outer_depth: int = 4

    def validate(self):
        require(
            all(
                type(v) is int and 0 <= v < 2**63
                for v in (
                    self.minimum,
                    self.target,
                    self.maximum,
                    self.keep_whole,
                    self.merge_below,
                    self.text_minimum,
                )
            ),
            "POLICY_SIZE",
            "Sizes must be nonnegative integers",
        )
        require(
            0 <= self.minimum <= self.target <= self.maximum
            and 16384 <= self.maximum <= 256 * 1024**4,
            "POLICY_LIMIT",
            "Require minimum <= target <= maximum; maximum must be 16 KiB to 256 TiB",
        )
        require(
            self.codec in ("auto", "none", "zstd", "gzip"),
            "CODEC",
            "Supported choices: auto, none, zstd, gzip",
        )
        require(
            type(self.level) is int and 1 <= self.level <= (9 if self.codec == "gzip" else 19),
            "CODEC_LEVEL",
            "Compression level outside supported range",
        )
        require(
            0 <= self.text_fraction <= 1
            and type(self.outer_depth) is int
            and 0 <= self.outer_depth <= 32,
            "POLICY_RANGE",
            "Invalid ratio or layout depth",
        )
        return self


def codec_for(policy, size, text):
    if policy.codec != "auto":
        return policy.codec
    return (
        "zstd"
        if size and text >= policy.text_minimum and text / size >= policy.text_fraction
        else "none"
    )


def namespace(source, snapshot):
    name = re.sub("[^A-Za-z0-9._-]+", "-", source["label"]).strip(".-")[:30] or "source"
    return name + "-" + snapshot[-8:]


class Planner:
    def __init__(self, store, policy, progress, label, snapshots, origin=None):
        self.s, self.policy, self.p = store, policy.validate(), progress
        self.id = uid("plan")
        self.seq = 0
        store.db.execute(
            "INSERT INTO plans VALUES (?,?,?,?,?,?,?, ?,?)",
            (
                self.id,
                label,
                now(),
                canonical(asdict(policy)).decode(),
                "",
                origin,
                "DRAFT",
                "{}",
                "{}",
            ),
        )
        require(
            snapshots and len(set(snapshots)) == len(snapshots),
            "PLAN_SOURCES",
            "Select one or more distinct inventories",
        )
        for sid in snapshots:
            scan = store.need("snapshots", sid)
            require(
                scan["state"] in ("COMPLETE", "REVIEW"),
                "SCAN_INCOMPLETE",
                "Cannot plan from an incomplete scan",
                snapshot=sid,
                state=scan["state"],
            )
            src = store.need("sources", scan["source_id"])
            store.db.execute(
                "INSERT INTO plan_sources VALUES (?,?,?)", (self.id, sid, namespace(src, sid))
            )

    def new_package(self, snapshot, kind, anchor, reason, codec):
        self.seq += 1
        pid = f"P{self.seq:06d}"
        self.s.db.execute(
            "INSERT INTO packages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                self.id,
                pid,
                "",
                snapshot,
                kind,
                anchor,
                reason,
                codec,
                self.policy.level,
                0,
                PACKAGE_OVERHEAD,
                0,
                0,
                "DRAFT",
            ),
        )
        return pid

    def add_node(self, pid, node):
        self.s.db.execute("INSERT INTO members VALUES (?,?,?)", (self.id, node, pid))

    def add_subtree(self, pid, node):
        self.s.db.execute(
            """WITH RECURSIVE tree(id) AS (
          SELECT ? UNION ALL SELECT n.id FROM nodes n JOIN tree t ON n.parent=t.id WHERE n.eligible=1
        ) INSERT INTO members SELECT ?,n.id,? FROM nodes n JOIN tree t ON n.id=t.id WHERE n.kind='file' AND n.eligible=1""",
            (node, self.id, pid),
        )

    def direct(self, node):
        s = self.s
        policy = self.policy
        row = s.one(
            "SELECT COALESCE(SUM(total_cost),0) cost,COALESCE(SUM(size),0) bytes,COALESCE(SUM(text_bytes),0) text,COUNT(*) count FROM nodes WHERE parent=? AND kind='file' AND eligible=1",
            (node["id"],),
        )
        if not row["count"]:
            return
        anchor = s.path(node["id"])
        # A source root is a directory too: keep its direct files together up to
        # the same whole-directory threshold used for a selected child subtree.
        # Child-directory packages remain separate; the target guides splitting,
        # whereas maximum/keep_whole is the cohesion boundary.
        together_limit = (
            min(policy.keep_whole or policy.maximum, policy.maximum)
            if node["parent"] is None
            else policy.target
        )
        if row["cost"] + PACKAGE_OVERHEAD <= together_limit:
            pid = self.new_package(
                node["snapshot_id"],
                "data",
                anchor,
                "DIRECT_FILES_TOGETHER",
                codec_for(policy, row["bytes"], row["text"]),
            )
            s.db.execute(
                "INSERT INTO members SELECT ?,id,? FROM nodes WHERE parent=? AND kind='file' AND eligible=1",
                (self.id, pid, node["id"]),
            )
            return
        # Only files immediately in THIS directory may be split by classification.
        classes = [
            r[0]
            for r in s.db.execute(
                "SELECT DISTINCT class FROM nodes WHERE parent=? AND kind='file' AND eligible=1 ORDER BY class",
                (node["id"],),
            )
        ]
        for cls in classes:
            pid = None
            cost = PACKAGE_OVERHEAD
            amount = 0
            text = 0
            for r in s.db.execute(
                "SELECT id,size,total_cost,text_bytes FROM nodes WHERE parent=? AND kind='file' AND eligible=1 AND class=? ORDER BY name",
                (node["id"], cls),
            ):
                self.p.check()
                if pid is None or (
                    cost + r["total_cost"] > policy.target and cost > PACKAGE_OVERHEAD
                ):
                    if pid:
                        c = codec_for(policy, amount, text)
                        s.db.execute(
                            "UPDATE packages SET codec=? WHERE plan_id=? AND id=?",
                            (c, self.id, pid),
                        )
                    pid = self.new_package(
                        node["snapshot_id"], "data", anchor, "LOOSE_FILES_SPLIT_LOCALLY", "none"
                    )
                    cost = PACKAGE_OVERHEAD
                    amount = text = 0
                self.add_node(pid, r["id"])
                cost += r["total_cost"]
                amount += r["size"]
                text += r["text_bytes"]
            if pid:
                s.db.execute(
                    "UPDATE packages SET codec=? WHERE plan_id=? AND id=?",
                    (codec_for(policy, amount, text), self.id, pid),
                )

    def source(self, snapshot):
        policy = self.policy
        s = self.s
        root = s.one("SELECT * FROM nodes WHERE snapshot_id=? AND parent IS NULL", (snapshot,))
        require(root is not None, "SCAN_ROOT", "Inventory root is missing")
        todo = [root]
        visited = 0
        intact = min(policy.keep_whole or policy.maximum, policy.maximum)
        while todo:
            node = todo.pop()
            visited += 1
            self.p.check()
            self.direct(node)
            small = {}
            for child in s.db.execute(
                "SELECT * FROM nodes WHERE parent=? AND kind='directory' AND eligible=1 ORDER BY name",
                (node["id"],),
            ):
                child = dict(child)
                if not child["total_files"]:
                    continue
                if child["total_cost"] + PACKAGE_OVERHEAD > intact:
                    todo.append(child)
                    continue
                codec = codec_for(policy, child["total_bytes"], child["text_bytes"])
                tiny = child["total_bytes"] < (policy.merge_below or policy.minimum)
                group = small.get(codec) if tiny else None
                if group and group["cost"] + child["total_cost"] <= policy.target:
                    self.add_subtree(group["id"], child["id"])
                    group["cost"] += child["total_cost"]
                    s.db.execute(
                        "UPDATE packages SET anchor=?,reason='WHOLE_SIBLINGS_COMBINED' WHERE plan_id=? AND id=?",
                        (s.path(node["id"]), self.id, group["id"]),
                    )
                else:
                    pid = self.new_package(
                        snapshot, "data", s.path(child["id"]), "WHOLE_DIRECTORY", codec
                    )
                    self.add_subtree(pid, child["id"])
                    if tiny:
                        small[codec] = {"id": pid, "cost": child["total_cost"] + PACKAGE_OVERHEAD}
            self.p.update(visited, s.path(node["id"]))
        # Store directory objects once, independent of payload groups. Large directory
        # catalogues also respect the package limit; no recursive payload inclusion.
        pid = None
        cost = PACKAGE_OVERHEAD
        for d in s.db.execute(
            "SELECT id FROM nodes WHERE snapshot_id=? AND kind='directory' AND eligible=1 ORDER BY id",
            (snapshot,),
        ):
            from .inventory import tar_cost

            entry_cost = tar_cost(0, len(s.path(d["id"]).encode()) + 80)
            if pid is None or cost + entry_cost > policy.maximum:
                pid = self.new_package(snapshot, "directories", "", "DIRECTORY_METADATA", "none")
                cost = PACKAGE_OVERHEAD
            self.add_node(pid, d["id"])
            cost += entry_cost

    def finish(self, provenance=None):
        return finalize(self.s, self.id, self.policy, self.p, provenance)


def finalize(store, plan_id, policy, progress, provenance=None, persist=True):
    from .inventory import tar_cost

    h = hashlib.sha256(canonical(asdict(policy)))
    sources = store.rows(
        "SELECT ps.*,s.fingerprint,s.counts FROM plan_sources ps JOIN snapshots s ON s.id=ps.snapshot_id WHERE plan_id=? ORDER BY ps.snapshot_id",
        (plan_id,),
    )
    expected_files = expected_dirs = errors = excluded = 0
    for source in sources:
        counts = json.loads(source["counts"])
        expected_files += counts["eligible_files"] or 0
        expected_dirs += store.db.execute(
            "SELECT COUNT(*) FROM nodes WHERE snapshot_id=? AND kind='directory' AND eligible=1",
            (source["snapshot_id"],),
        ).fetchone()[0]
        errors += counts.get("errors", 0)
        excluded += counts.get("excluded", 0)
        h.update(canonical([source["snapshot_id"], source["fingerprint"], source["namespace"]]))
    count = logical = assigned_files = assigned_dirs = blocked = small = 0
    for package in store.rows("SELECT * FROM packages WHERE plan_id=? ORDER BY id", (plan_id,)):
        ph = hashlib.sha256(package["snapshot_id"].encode())
        budget = PACKAGE_OVERHEAD
        size = files = dirs = 0
        for row in store.db.execute(
            "SELECT n.* FROM members m JOIN nodes n ON n.id=m.node_id WHERE m.plan_id=? AND m.package_id=? ORDER BY n.id",
            (plan_id, package["id"]),
        ):
            r = dict(row)
            progress.check()
            require(
                r["eligible"] == 1 and r["snapshot_id"] == package["snapshot_id"],
                "MEMBERSHIP",
                "Foreign/excluded member in package",
            )
            require(
                (package["kind"] == "data" and r["kind"] == "file")
                or (package["kind"] == "directories" and r["kind"] == "directory"),
                "PACKAGE_KIND",
                "Mixed payload/directory metadata membership",
            )
            path = store.path(r["id"])
            ph.update(canonical([path, r["digest"].hex()]))
            budget += (
                r["total_cost"] if r["kind"] == "file" else tar_cost(0, len(path.encode()) + 80)
            )
            size += r["size"] if r["kind"] == "file" else 0
            files += int(r["kind"] == "file")
            dirs += int(r["kind"] == "directory")
        if not files and not dirs:
            if persist:
                store.db.execute(
                    "DELETE FROM packages WHERE plan_id=? AND id=?", (plan_id, package["id"])
                )
            continue
        status = (
            "BLOCKED"
            if budget > policy.maximum
            else "METADATA"
            if package["kind"] == "directories"
            else "SMALL"
            if size < policy.minimum
            else "READY"
        )
        blocked += status == "BLOCKED"
        small += status == "SMALL"
        logical += size
        assigned_files += files
        assigned_dirs += dirs
        count += 1
        lid = ph.hexdigest()
        if persist:
            store.db.execute(
                "UPDATE packages SET logical_id=?,logical_bytes=?,estimated_bytes=?,file_count=?,dir_count=?,status=? WHERE plan_id=? AND id=?",
                (lid, size, budget, files, dirs, status, plan_id, package["id"]),
            )
        h.update(
            canonical(
                [
                    package["id"],
                    lid,
                    package["codec"],
                    package["level"],
                    package["anchor"],
                    package["reason"],
                ]
            )
        )
    require(
        (assigned_files, assigned_dirs) == (expected_files, expected_dirs),
        "COVERAGE",
        "Package membership does not exactly cover eligible observations",
        expected=[expected_files, expected_dirs],
        assigned=[assigned_files, assigned_dirs],
    )
    counts = {
        "packages": count,
        "logical_bytes": logical,
        "files": assigned_files,
        "directories": assigned_dirs,
        "excluded_observations": excluded,
        "source_errors": errors,
        "blocked_packages": blocked,
        "small_packages": small,
        "exact_once": True,
    }
    state = "BLOCKED" if errors or blocked else "REVIEW" if excluded else "READY"
    if persist:
        store.db.execute(
            "UPDATE plans SET fingerprint=?,state=?,counts=?,provenance=? WHERE id=?",
            (
                h.hexdigest(),
                state,
                canonical(counts).decode(),
                canonical(provenance or {}).decode(),
                plan_id,
            ),
        )
    if persist:
        store.commit()
    return {
        **store.need("plans", plan_id),
        "fingerprint": h.hexdigest(),
        "state": state,
        "policy": asdict(policy),
        "counts": counts,
        "provenance": provenance or {},
    }


def create_plan(store, snapshots, progress, label="Archive plan", policy=None):
    policy = Policy(**(policy or {})).validate()
    try:
        planner = Planner(store, policy, progress, label, snapshots)
        progress.phase("Plan directories", None, "directories")
        for snapshot in snapshots:
            planner.source(snapshot)
        progress.phase("Check coverage", None, "members")
        return planner.finish()
    except BaseException:
        store.db.rollback()
        raise


def _clone_plan(store, source_id, parent_id):
    """Clone frozen decisions inside the caller's transaction."""
    new = uid("plan")
    store.db.execute(
        "INSERT INTO plans SELECT ?,label,?,policy,?,?,?,counts,provenance FROM plans WHERE id=?",
        (new, now(), "", parent_id, "DRAFT", source_id),
    )
    store.db.execute(
        "INSERT INTO plan_sources SELECT ?,snapshot_id,namespace FROM plan_sources WHERE plan_id=?",
        (new, source_id),
    )
    store.db.execute(
        "INSERT INTO packages SELECT ?,id,logical_id,snapshot_id,kind,anchor,reason,codec,level,logical_bytes,estimated_bytes,file_count,dir_count,status FROM packages WHERE plan_id=?",
        (new, source_id),
    )
    store.db.execute(
        "INSERT INTO members SELECT ?,node_id,package_id FROM members WHERE plan_id=?",
        (new, source_id),
    )
    return new


def revise_plan(store, plan_id, progress, codec_changes=None, merge=None, move=None):
    """Create a new immutable revision. Never mutate a saved plan used by a build."""
    old = store.need("plans", plan_id)
    policy = Policy(**json.loads(old["policy"]))
    try:
        new = _clone_plan(store, plan_id, plan_id)
        for pid, setting in (codec_changes or {}).items():
            require(isinstance(setting, dict), "EDIT_CODEC", "Codec setting must be an object")
            codec = setting.get("codec")
            level = setting.get("level", 3)
            Policy(codec=codec, level=level).validate()
            require(
                codec != "auto", "EDIT_CODEC", "A package override must select none, zstd or gzip"
            )
            row = store.one("SELECT * FROM packages WHERE plan_id=? AND id=?", (new, pid))
            require(row is not None, "PACKAGE", "Unknown package")
            require(
                row["kind"] == "data" or codec == "none",
                "DIRECTORY_CODEC",
                "Directory metadata stays uncompressed",
            )
            # Encoding changes do not change why files were grouped together.
            store.db.execute(
                "UPDATE packages SET codec=?,level=? WHERE plan_id=? AND id=?",
                (codec, level, new, pid),
            )
        if merge:
            require(
                len(set(merge)) >= 2 and len(merge) == len(set(merge)),
                "MERGE",
                "Select at least two distinct packages",
            )
            rows = [
                store.one("SELECT * FROM packages WHERE plan_id=? AND id=?", (new, p))
                for p in merge
            ]
            require(all(rows), "PACKAGE", "Unknown merge package")
            first = rows[0]
            require(
                all(
                    r["snapshot_id"] == first["snapshot_id"]
                    and r["kind"] == "data"
                    and r["codec"] == first["codec"]
                    and r["level"] == first["level"]
                    for r in rows
                ),
                "MERGE_SCOPE",
                "Merge requires payload packages from one scan with the same codec settings",
            )
            for r in rows[1:]:
                store.db.execute(
                    "UPDATE members SET package_id=? WHERE plan_id=? AND package_id=?",
                    (first["id"], new, r["id"]),
                )
                store.db.execute("DELETE FROM packages WHERE plan_id=? AND id=?", (new, r["id"]))
            store.db.execute(
                "UPDATE packages SET reason='MANUAL_MERGE',anchor='' WHERE plan_id=? AND id=?",
                (new, first["id"]),
            )
        if move:
            ids = move.get("node_ids", [])
            target = move.get("target")
            require(
                ids and len(ids) == len(set(ids)) and all(type(i) is int for i in ids),
                "MOVE",
                "Choose distinct member IDs",
            )
            rows = []
            for ident in ids:
                r = store.one(
                    "SELECT n.*,m.package_id FROM nodes n JOIN members m ON n.id=m.node_id WHERE m.plan_id=? AND n.id=?",
                    (new, ident),
                )
                require(
                    r and r["kind"] == "file", "MOVE", "Only payload members in this plan can move"
                )
                rows.append(r)
            require(
                len({r["snapshot_id"] for r in rows}) == 1,
                "MOVE_SCOPE",
                "Do not merge separate source snapshots",
            )
            if not target:
                target = "P" + str(
                    max(
                        [
                            int(r["id"][1:])
                            for r in store.rows("SELECT id FROM packages WHERE plan_id=?", (new,))
                        ]
                    )
                    + 1
                ).zfill(6)
                store.db.execute(
                    "INSERT INTO packages VALUES (?,?,?,?,?,'','MANUAL_MOVE','none',3,0,0,0,0,'DRAFT')",
                    (new, target, "", rows[0]["snapshot_id"], "data"),
                )
            t = store.one("SELECT * FROM packages WHERE plan_id=? AND id=?", (new, target))
            require(
                t and t["snapshot_id"] == rows[0]["snapshot_id"] and t["kind"] == "data",
                "MOVE_SCOPE",
                "Target must be a payload package from the same scan",
            )
            store.db.executemany(
                "UPDATE members SET package_id=? WHERE plan_id=? AND node_id=?",
                [(target, new, r["id"]) for r in rows],
            )
            store.db.execute(
                "UPDATE packages SET reason='MANUAL_MOVE' WHERE plan_id=? AND id=?", (new, target)
            )
        return finalize(
            store,
            new,
            policy,
            progress,
            {"revision_of": plan_id, "manual_edit": True, "codec_changes": codec_changes or {}},
        )
    except BaseException:
        store.db.rollback()
        raise


def revert_plan(store, plan_id, target_plan_id, progress):
    """Create a new child of the current plan containing a prior plan's decisions."""
    store.need("plans", plan_id)
    target = store.need("plans", target_plan_id)

    def observations(ident):
        return {
            tuple(row)
            for row in store.db.execute(
                "SELECT snapshot_id,namespace FROM plan_sources WHERE plan_id=?", (ident,)
            )
        }

    require(
        observations(plan_id) == observations(target_plan_id),
        "REVERT_SCOPE",
        "Revert requires identical observations and restore namespaces",
    )
    try:
        new = _clone_plan(store, target_plan_id, plan_id)
        return finalize(
            store,
            new,
            Policy(**json.loads(target["policy"])),
            progress,
            {
                "revision_of": plan_id,
                "reverted_to": target_plan_id,
                "manual_edit": True,
            },
        )
    except BaseException:
        store.db.rollback()
        raise


def _allocation_size(package):
    if "allocation_bytes" in package:
        value = package["allocation_bytes"]
    elif "actual_bytes" in package:
        value = package["actual_bytes"]
    else:
        value = package["estimated_bytes"]
    require(type(value) is int and value >= 0, "CAPACITY", "Invalid package byte count")
    return value


def allocate(
    packages, media, set_allowance_bytes=0, *, recovery_kit_bytes=0, set_largest_file_bytes=0
):
    """Explainable first-fit decreasing allocation, not a global optimiser."""
    require(
        media and len({m["id"] for m in media}) == len(media),
        "MEDIA",
        "Choose distinct destination labels",
    )
    require(
        type(set_allowance_bytes) is int and set_allowance_bytes >= 0,
        "CAPACITY",
        "Invalid archive-set allowance",
    )
    require(
        all(
            type(value) is int and value >= 0
            for value in (recovery_kit_bytes, set_largest_file_bytes)
        ),
        "CAPACITY",
        "Invalid recovery-kit byte counts",
    )
    set_cost = set_allowance_bytes + recovery_kit_bytes
    bins = []
    for m in media:
        cap = m.get("capacity")
        reserve = m.get("reserve", 0)
        occupied = m.get("occupied", 0)
        maxfile = m.get("max_file")
        if maxfile is None:
            maxfile = cap
        require(
            all(type(v) is int and v >= 0 for v in (cap, reserve, occupied, maxfile))
            and cap > 0
            and reserve + occupied <= cap,
            "CAPACITY",
            "Invalid destination capacity/reserve/occupancy",
        )
        bins.append(
            {
                **m,
                "max_file": maxfile,
                "usable": cap - reserve - occupied,
                "used": 0,
                "package_bytes": 0,
                "recovery_kit_bytes": 0,
                "set_allowance_bytes": 0,
                "packages": [],
            }
        )
    unfit = []
    for p in sorted(packages, key=lambda p: (-_allocation_size(p), p["id"])):
        n = _allocation_size(p)
        largest = p.get("largest_file_bytes", n)
        match = next(
            (
                b
                for b in bins
                if max(largest, set_largest_file_bytes) <= b["max_file"]
                and b["used"] + n + (0 if b["packages"] else set_cost) <= b["usable"]
            ),
            None,
        )
        if match:
            if not match["packages"]:
                match["set_allowance_bytes"] = set_allowance_bytes
                match["recovery_kit_bytes"] = recovery_kit_bytes
                match["used"] += set_cost
            match["packages"].append(p["id"])
            match["used"] += n
            match["package_bytes"] += n
        else:
            unfit.append(p["id"])
    return {
        "media": bins,
        "unallocated": unfit,
        "basis": "Measured package objects when available; otherwise TAR and metadata estimates. No predicted compression credit.",
        "globally_optimal": False,
    }


def allocation_packages(store, plan_id, bundle=None):
    """Return stored-object footprints, using a validated saved build when available.

    Missing build media is explicitly reported as estimates. A present but invalid
    build never silently falls back: integrity failures must remain visible.
    """
    from . import recovery

    plan = store.need("plans", plan_id)
    packages = store.rows("SELECT * FROM packages WHERE plan_id=? ORDER BY id", (plan_id,))
    measurement = {"basis": "estimated", "reason": "No completed build is available"}
    explicit = bundle is not None
    if not explicit:
        build = store.one(
            "SELECT * FROM builds WHERE plan_id=? AND state IN ('COMPLETE','PARTIAL_PLAN') ORDER BY updated DESC,id DESC LIMIT 1",
            (plan_id,),
        )
        if build:
            bundle = build["path"]
            measurement = {
                "basis": "estimated",
                "reason": "Saved build is unavailable",
                "bundle": str(bundle),
            }
    receipts = {}
    if bundle is not None and (explicit or (Path(bundle) / "ARCHIVE.json").is_file()):
        root, index, refs = recovery.inspect(bundle)
        require(
            index.get("plan_id") == plan_id
            and index.get("plan_fingerprint") == plan["fingerprint"],
            "ALLOCATION_PLAN",
            "Measured archive set belongs to a different plan",
        )
        by_id = {package["id"]: package for package in packages}
        for ref in refs:
            receipt, artifact, manifest = recovery.validate_receipt(root, ref, hash_payload=False)
            package = by_id.get(receipt["package_id"])
            require(
                package is not None
                and receipt["logical_package_id"] == package["logical_id"]
                and receipt["codec"] == package["codec"]
                and receipt["level"] == package["level"],
                "ALLOCATION_PACKAGE",
                "Measured artifact does not match the saved package",
            )
            receipt_path = recovery.located(root, ref["receipt"])
            receipts[package["id"]] = capacity.package_footprint(
                artifact.stat().st_size, manifest.stat().st_size, receipt_path.stat().st_size
            )
        measurement = {
            "basis": "measured" if len(receipts) == len(packages) else "mixed",
            "bundle": str(root),
            "measured_packages": len(receipts),
            "estimated_packages": len(packages) - len(receipts),
            "validation": "Sealed kit and recorded object lengths; payload hashes are rechecked during copy",
            "recovery_kit": capacity.recovery_kit_footprint(root),
        }
    for package in packages:
        footprint = receipts.get(package["id"]) or capacity.estimated_footprint(package)
        package["footprint"] = footprint
        package["allocation_bytes"] = footprint["package_bytes"]
        package["largest_file_bytes"] = max(
            footprint[key] for key in ("artifact_bytes", "manifest_bytes", "receipt_bytes")
        )
    return packages, measurement


def allocate_plan(store, plan_id, media, *, bundle=None):
    packages, measurement = allocation_packages(store, plan_id, bundle)
    kit = measurement.get("recovery_kit", {})
    result = allocate(
        packages,
        media,
        capacity.COPY_SET_ALLOWANCE_BYTES,
        recovery_kit_bytes=kit.get("recovery_kit_bytes", 0),
        set_largest_file_bytes=kit.get("largest_file_bytes", 0),
    )
    result["measurement"] = measurement
    result["package_footprints"] = [
        {"package_id": package["id"], **package["footprint"]} for package in packages
    ]
    metadata = {}
    for package in packages:
        if package["kind"] == "directories":
            metadata.setdefault(package["snapshot_id"], []).append(package["id"])
    dependencies = {
        package["id"]: metadata.get(package["snapshot_id"], [])
        for package in packages
        if package["kind"] == "data"
    }
    metadata_ids = {package["id"] for package in packages if package["kind"] == "directories"}
    for medium in result["media"]:
        medium.update(
            capacity.metadata_plan_selection(
                medium["packages"], dependencies, known_metadata_ids=metadata_ids
            )
        )
    result["metadata_dependencies_complete"] = not result["unallocated"] and all(
        medium["metadata_completeness"] == "complete" for medium in result["media"]
    )
    result["basis"] += (
        " A byte fit does not imply complete directory metadata on each medium."
        " Required metadata packages are listed per medium; no automatic duplication is charged."
    )
    return result
