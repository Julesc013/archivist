"""Disk and explicitly experimental mounted-LTFS replicas. Never opens tape devices."""

from __future__ import annotations
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from . import archive_html, capacity, recovery
from .artifacts import recovery_progress
from .util import (
    CHUNK,
    atomic_json,
    canonical,
    digest,
    disjoint,
    fsync_dir,
    hash_file,
    json_read,
    locked,
    no_links,
    now,
    require,
    root_identity,
    uid,
)

MARKER = ".ap20-destination.json"
DATA = "AP20-archives"


def mount_identity(path, kind):
    value = root_identity(path)
    if kind == "ltfs":
        require(
            sys.platform.startswith("linux"),
            "LTFS_PLATFORM",
            "Archivist only provides an experimental Linux mounted-LTFS adapter",
        )
        exe = shutil.which("findmnt")
        require(
            exe is not None,
            "FINDMNT_MISSING",
            "findmnt is required to identify the mounted filesystem",
        )
        p = subprocess.run(
            [exe, "--json", "--target", str(path), "--output", "TARGET,SOURCE,FSTYPE,OPTIONS"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        require(p.returncode == 0, "MOUNT_UNKNOWN", "Cannot identify the mounted filesystem")
        rows = json.loads(p.stdout).get("filesystems", [])
        require(rows, "MOUNT_UNKNOWN", "No mounted filesystem was reported")
        m = rows[0]
        require(
            "ltfs" in str(m.get("fstype", "")).lower(),
            "NOT_LTFS",
            "Directory is not identified as an LTFS mount",
            filesystem=m.get("fstype"),
        )
        require(
            "ro" not in str(m.get("options", "")).split(","), "READ_ONLY", "LTFS mount is read-only"
        )
        value["mount"] = {k: m.get(k) for k in ("target", "source", "fstype")}
    return value


def register(
    store, path, label, kind="disk", capacity=None, max_file=None, reserve=0, experimental=False
):
    require(
        kind in ("disk", "ltfs"),
        "DEST_KIND",
        "Choose disk or mounted ltfs; raw tape/optical burning are not implemented",
    )
    require(
        kind != "ltfs" or experimental,
        "LTFS_UNQUALIFIED",
        "Explicitly acknowledge experimental mounted-LTFS support; physical hardware has not been qualified",
    )
    for value in (capacity, max_file, reserve):
        require(
            value is None or (type(value) is int and 0 <= value < 2**63),
            "CAPACITY",
            "Invalid capacity value",
        )
    require(
        capacity is None or reserve < capacity, "CAPACITY", "Reserve must be smaller than capacity"
    )
    path = no_links(Path(path), missing_ok=(kind == "disk"))
    require(
        disjoint(path, store.root),
        "DEST_WORKSPACE",
        "Destination must be separate from the workspace",
    )
    for src in store.rows("SELECT root FROM sources"):
        if Path(src["root"]).is_dir():
            require(
                disjoint(path, Path(src["root"])),
                "DEST_SOURCE",
                "Destination must not overlap a source directory",
                source=src["root"],
            )
    path.mkdir(parents=True, exist_ok=True)
    identity = mount_identity(path, kind)
    marker = path / MARKER
    if marker.exists():
        record = json_read(marker)
        require(
            record.get("format") == "AP20Destination/1",
            "DEST_MARKER",
            "Unrecognised destination marker",
        )
        ident = record["id"]
    else:
        ident = uid("dest")
        record = {"format": "AP20Destination/1", "id": ident, "label": label, "created": now()}
        with marker.open("xb") as out:
            out.write(canonical(record) + b"\n")
            out.flush()
            os.fsync(out.fileno())
        fsync_dir(path)
    identity["marker_sha256"] = hash_file(marker)
    store.db.execute(
        "INSERT INTO destinations VALUES (?,?,?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET label=excluded.label,path=excluded.path,kind=excluded.kind,identity=excluded.identity,capacity=excluded.capacity,max_file=excluded.max_file,reserve=excluded.reserve,enabled=1",
        (ident, label, str(path), kind, canonical(identity).decode(), capacity, max_file, reserve),
    )
    store.commit()
    return store.need("destinations", ident)


def check_destination(store, ident):
    dest = store.need("destinations", ident)
    require(
        dest["enabled"],
        "DEST_UNBOUND",
        "Imported destination is unbound; explicitly register it again",
    )
    path = no_links(Path(dest["path"]))
    require(path.is_dir(), "DEST_OFFLINE", "Destination is unavailable")
    actual = mount_identity(path, dest["kind"])
    actual["marker_sha256"] = hash_file(path / MARKER)
    require(
        actual == json.loads(dest["identity"]),
        "DEST_CHANGED",
        "Destination identity or marker changed; no write was started",
    )
    return dest, path


def tree_size(path):
    total = 0
    if not path.exists():
        return 0
    for root, dirs, files in os.walk(path, followlinks=False):
        no_links(Path(root))
        for name in files:
            p = no_links(Path(root) / name)
            total += p.stat().st_size
    return total


def partial_copy_credit(
    partial, files, expected_index, source_kit, approval, destination, progress
):
    """Credit only checked objects owned by this exact interrupted copy.

    Unrecognised files and interrupted temporary writes remain charged by
    tree_size(). Credit is byte accounting, never evidence of readback success;
    copy() still performs its complete content verification before publication.
    """
    if not partial.exists():
        return {"package_bytes": 0, "metadata_bytes": 0}
    partial = no_links(partial)
    require(partial.is_dir(), "COPY_CONFLICT", "Partial copy path is not a directory")
    marker = partial / "COPY.json"
    if not marker.exists():
        require(
            not any(partial.iterdir()),
            "COPY_CONFLICT",
            "Nonempty partial copy has no ownership marker; refusing adoption",
        )
        return {"package_bytes": 0, "metadata_bytes": 0}
    marker = no_links(marker)
    state = json_read(marker, 16384)
    require(
        isinstance(state, dict)
        and state.get("format") == "AP20Copy/1"
        and state.get("approval") == approval
        and state.get("state") in ("INCOMPLETE", "COMPLETE"),
        "COPY_CONFLICT",
        "Partial copy belongs to a different operation",
    )
    package_bytes = 0
    for name, expected in files.items():
        path = no_links(partial.joinpath(*name.split("/")), missing_ok=True)
        if not path.exists():
            continue
        require(
            path.is_file()
            and path.stat().st_size == expected["size"]
            and recovery.file_hash(path, recovery_progress(progress), "Check copied object")
            == expected["sha256"],
            "COPY_CONFLICT",
            "Existing partial object differs; refusing capacity credit or overwrite",
            path=name,
        )
        package_bytes += expected["size"]
    metadata_bytes = marker.stat().st_size
    seal = partial / "SHA256SUMS"
    if seal.exists():
        verified = recovery.validate_kit(partial, progress=recovery_progress(progress))
        require(
            verified["index"] == expected_index,
            "COPY_CONFLICT",
            "Partial recovery catalogue differs from this copy selection",
        )
        require(
            verified["files"]["RESTORE.py"] == source_kit["files"]["RESTORE.py"],
            "COPY_CONFLICT",
            "Partial recovery helper differs from the sealed source helper",
        )
        # Receipts have already been credited as package objects. The seal is
        # validated structurally and against all covered kit/receipt hashes.
        names = {"ARCHIVE.json", "README.txt", "RESTORE.py", "ARCHIVE.html"} & verified[
            "files"
        ].keys()
        metadata_bytes += sum(no_links(partial / name).stat().st_size for name in names)
        metadata_bytes += no_links(seal).stat().st_size
    else:
        # An interrupted first kit write is not yet a sealed kit. Its helper is
        # independently hash-checkable; other unfinished metadata gets no credit.
        helper = no_links(partial / "RESTORE.py", missing_ok=True)
        if helper.exists():
            require(
                helper.is_file() and hash_file(helper) == source_kit["files"]["RESTORE.py"],
                "COPY_CONFLICT",
                "Unsealed partial recovery helper differs from the source",
            )
            metadata_bytes += helper.stat().st_size
    receipt_path = partial / "REPLICA.json"
    if receipt_path.exists():
        receipt_path = no_links(receipt_path)
        receipt = json_read(receipt_path)
        require(
            isinstance(receipt, dict)
            and receipt.get("format") == "AP20Replica/1"
            and receipt.get("build_id") == expected_index["build_id"]
            and receipt.get("destination_id") == destination
            and receipt.get("approval") == approval
            and receipt.get("state") == "COPY_READBACK"
            and re.fullmatch(r"replica-[0-9a-f]{16}", str(receipt.get("id"))) is not None,
            "COPY_CONFLICT",
            "Partial replica receipt belongs to a different operation",
        )
        require(
            seal.is_file(), "COPY_CONFLICT", "Partial replica receipt has no sealed recovery kit"
        )
        metadata_bytes += receipt_path.stat().st_size
    require(
        state["state"] != "COMPLETE" or receipt_path.is_file(),
        "COPY_CONFLICT",
        "Completed partial copy marker has no replica receipt",
    )
    return {"package_bytes": package_bytes, "metadata_bytes": metadata_bytes}


def copy_recipe(store, bundle, destination, packages, progress):
    root, index, refs = recovery.inspect(bundle, packages, recovery_progress(progress))
    kit = recovery.validate_kit(root, index, progress=recovery_progress(progress))
    kit_footprint = capacity.recovery_kit_footprint(root)
    dest, path = check_destination(store, destination)
    require(disjoint(root, path), "COPY_OVERLAP", "Archive set and destination must be separate")
    files = {}
    receipts = []
    for ref in refs:
        r, artifact, manifest = recovery.validate_receipt(root, ref, hash_payload=False)
        require(
            dest["max_file"] is None or r["artifact_bytes"] <= dest["max_file"],
            "DEST_FILE_LIMIT",
            "Artifact exceeds the destination file-size limit",
            package=r["package_id"],
        )
        for name, sha in [
            (r["artifact"], r["artifact_sha256"]),
            (r["manifest"], r["manifest_sha256"]),
            (ref["receipt"], ref["receipt_sha256"]),
        ]:
            require(
                name not in files, "COPY_DUPLICATE", "Two packages refer to the same stored object"
            )
            files[name] = {"sha256": sha, "size": root.joinpath(*name.split("/")).stat().st_size}
            require(
                dest["max_file"] is None or files[name]["size"] <= dest["max_file"],
                "DEST_FILE_LIMIT",
                "Package object exceeds the destination file-size limit",
                path=name,
            )
        receipts.append(r)
    for name, item in kit_footprint["files"].items():
        size = item["bytes"] if isinstance(item, dict) else item
        require(
            dest["max_file"] is None or size <= dest["max_file"],
            "DEST_FILE_LIMIT",
            "Recovery-kit object exceeds the destination file-size limit",
            path=name,
        )
    selection = {
        "build_id": index["build_id"],
        "plan_fingerprint": index["plan_fingerprint"],
        "packages": refs,
        "destination": destination,
        "identity": dest["identity"],
    }
    key = digest(selection)
    final = path / DATA / ("replica-" + key[:20])
    partial = final.with_name("." + final.name + ".partial")
    bytes_total = sum(f["size"] for f in files.values())
    expected_index = {
        **index,
        "packages": refs,
        "scope": "COMPLETE_PLAN" if len(refs) == index["planned_packages"] else "PARTIAL_PLAN",
    }
    if "ARCHIVE.html" in kit["files"]:
        expected_index["human_manifest"] = "ARCHIVE.html"
    credit = partial_copy_credit(partial, files, expected_index, kit, key, destination, progress)
    remaining = bytes_total - credit["package_bytes"]
    capacity_breakdown = capacity.copy_requirement(
        remaining, recovery_kit_bytes=kit_footprint["recovery_kit_bytes"]
    )
    metadata_budget = (
        capacity_breakdown["recovery_kit_bytes"] + capacity_breakdown["set_allowance_bytes"]
    )
    metadata_credit = min(credit["metadata_bytes"], metadata_budget)
    capacity_breakdown.update(
        completed_package_bytes=credit["package_bytes"],
        validated_metadata_credit_bytes=metadata_credit,
        remaining_metadata_budget_bytes=metadata_budget - metadata_credit,
    )
    capacity_breakdown["required_bytes"] -= metadata_credit
    required = capacity_breakdown["required_bytes"]
    free = shutil.disk_usage(path).free - dest["reserve"]
    capacity_left = (
        None
        if dest["capacity"] is None
        else dest["capacity"] - dest["reserve"] - tree_size(path / DATA)
    )
    if not final.exists():
        require(
            free >= required,
            "DEST_SPACE",
            "Insufficient observed destination free space",
            required=required,
            free=free,
        )
        require(
            capacity_left is None or capacity_left >= required,
            "DEST_CAPACITY",
            "Configured medium budget would be exceeded",
            required=required,
            available=capacity_left,
        )
    review = {
        "operation": "copy",
        "destination_id": destination,
        "destination_path": str(path),
        "destination_kind": dest["kind"],
        "identity": json.loads(dest["identity"]),
        "archive_set": str(root),
        "build_id": index["build_id"],
        "packages": [r["package_id"] for r in refs],
        "actual_payload_bytes": bytes_total,
        "estimated_additional_bytes": required,
        "observed_free_bytes": max(0, free),
        "configured_remaining_bytes": capacity_left,
        "capacity_breakdown": capacity_breakdown,
        "target": str(final),
        "approval": digest(selection),
        "verification": "Logical readback; does not claim an independent offline/remount or second-drive test",
        **capacity.metadata_plan_selection(
            [reference["package_id"] for reference in refs],
            index.get("directory_metadata_dependencies"),
        ),
    }
    return review, root, index, refs, files, final, partial, kit


def preflight_copy(store, bundle, destination, progress, packages=None):
    return copy_recipe(store, bundle, destination, packages, progress)[0]


def copy_file(source, target, expected, progress):
    target.parent.mkdir(parents=True, exist_ok=True)
    no_links(target.parent)
    if target.exists():
        require(
            target.stat().st_size == expected["size"] and hash_file(target) == expected["sha256"],
            "COPY_CONFLICT",
            "Existing file differs; refusing overwrite",
            path=str(target),
        )
        progress.advance(expected["size"], str(target))
        return
    partial = target.with_name("." + target.name + ".partial-" + uuid.uuid4().hex[:8])
    h = hashlib.sha256()
    before = source.stat()
    with source.open("rb") as inp, partial.open("xb") as out:
        while block := inp.read(CHUNK):
            progress.check()
            out.write(block)
            h.update(block)
            progress.advance(len(block), str(source))
        out.flush()
        os.fsync(out.fileno())
        after = os.fstat(inp.fileno())
    require(
        (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
        "ARTIFACT_CHANGED",
        "Archive changed during copy",
    )
    require(
        partial.stat().st_size == expected["size"] and h.hexdigest() == expected["sha256"],
        "COPY_HASH",
        "Read bytes differ from the package receipt",
    )
    require(not target.exists(), "COPY_CONFLICT", "Output appeared during copy; refusing overwrite")
    recovery.publish_new(partial, target)
    fsync_dir(target.parent)


def reconcile_replica(store, receipt, final, build_id, destination, approval):
    """Adopt a verified committed receipt after a publication/catalogue gap.

    This runs under both workspace and destination write locks. Existing IDs or
    paths must describe exactly the same immutable receipt; retry never creates
    a second identity or overwrites a conflicting catalogue record.
    """
    require(
        isinstance(receipt, dict) and receipt.get("format") == "AP20Replica/1",
        "REPLICA_RECEIPT",
        "Unsupported replica receipt",
    )
    ident = receipt.get("id")
    require(
        isinstance(ident, str) and re.fullmatch(r"replica-[0-9a-f]{16}", ident) is not None,
        "REPLICA_RECEIPT",
        "Invalid replica identity",
    )
    require(
        receipt.get("build_id") == build_id
        and receipt.get("destination_id") == destination
        and receipt.get("approval") == approval
        and receipt.get("state") == "COPY_READBACK",
        "REPLICA_CONFLICT",
        "Committed replica identity differs from the approved copy",
    )
    require(
        isinstance(receipt.get("created"), str) and bool(receipt["created"]),
        "REPLICA_RECEIPT",
        "Replica creation time is missing",
    )
    values = (
        ident,
        build_id,
        destination,
        str(final),
        "COPY_READBACK",
        receipt["created"],
        canonical(receipt).decode(),
    )
    rows = store.rows("SELECT * FROM replicas WHERE id=? OR path=?", (ident, str(final)))
    if rows:
        expected = dict(
            zip(("id", "build_id", "destination_id", "path", "state", "created", "detail"), values)
        )
        # Legacy V20 stored catalogue insertion time in created, separately from
        # the receipt's creation time. That timestamp is not replica identity.
        fields = ("id", "build_id", "destination_id", "path", "state", "detail")
        require(
            len(rows) == 1 and all(rows[0][key] == expected[key] for key in fields),
            "REPLICA_CONFLICT",
            "Existing replica catalogue entry differs from the committed receipt",
        )
        return False
    store.db.execute("INSERT INTO replicas VALUES (?,?,?,?,?,?,?)", values)
    store.commit()
    return True


def write_copy_readme(source, target, expected_sha, scope):
    """Derive a selected set's README only from verified source bytes."""
    data = source.read_bytes()
    require(
        hashlib.sha256(data).hexdigest() == expected_sha,
        "COPY_KIT_CHANGED",
        "Recovery documentation changed after preflight",
    )
    text = (
        data.decode("utf-8")
        .replace("\r\n", "\n")
        .replace("Scope: COMPLETE_PLAN.", "Scope: " + scope + ".")
    )
    derived = text.encode("utf-8")
    if target.exists():
        old = hash_file(no_links(target))
        require(
            old in (expected_sha, hashlib.sha256(derived).hexdigest()),
            "COPY_CONFLICT",
            "Partial recovery documentation differs; refusing overwrite",
            path=str(target),
        )
    temporary = target.with_name("." + target.name + ".updating-" + uuid.uuid4().hex[:8])
    with temporary.open("xb") as out:
        out.write(derived)
        out.flush()
        os.fsync(out.fileno())
    # This is owned copy metadata; the outer COPY.json binds it to approval.
    os.replace(temporary, target)
    fsync_dir(target.parent)


def check_copy_metadata(partial, dest, review, replacements=None):
    """Reconcile the actual generated kit against its budget before commit."""
    names = (
        "ARCHIVE.json",
        "README.txt",
        "RESTORE.py",
        "SHA256SUMS",
        "ARCHIVE.html",
        "REPLICA.json",
        "COPY.json",
    )
    total = 0
    replacements = replacements or {}
    for name in names:
        path = partial / name
        if name in replacements:
            size = replacements[name]
        elif path.exists():
            size = no_links(path).stat().st_size
        else:
            continue
        require(
            dest["max_file"] is None or size <= dest["max_file"],
            "DEST_FILE_LIMIT",
            "Generated recovery metadata exceeds the destination file-size limit",
            path=name,
            bytes=size,
        )
        total += size
    budget = (
        review["capacity_breakdown"]["recovery_kit_bytes"]
        + review["capacity_breakdown"]["set_allowance_bytes"]
    )
    require(
        total <= budget,
        "COPY_METADATA_BUDGET",
        "Generated recovery metadata exceeds its reserved space; partial copy retained",
        bytes=total,
        budget=budget,
    )


def copy(store, bundle, destination, progress, approval, packages=None):
    review, root, index, refs, files, final, partial, kit = copy_recipe(
        store, bundle, destination, packages, progress
    )
    require(
        review["approval"] == approval,
        "APPROVAL",
        "Copy requires confirmation of the current destination and selection",
        required=review["approval"],
    )
    dest, path = check_destination(store, destination)
    with locked(path / ".ap20-write.lock"):
        check_destination(store, destination)
        if final.exists():
            receipt = json_read(no_links(final / "REPLICA.json"))
            require(
                receipt.get("approval") == approval,
                "REPLICA_CONFLICT",
                "Existing replica has a different identity",
            )
            result = recovery.run(final, progress=recovery_progress(progress))
            check_destination(store, destination)
            reconciled = reconcile_replica(
                store, receipt, final, index["build_id"], destination, approval
            )
            return {
                "state": "COPY_READBACK",
                "path": str(final),
                "replica_id": receipt["id"],
                "reused": True,
                "catalogue_reconciled": reconciled,
                "verification": result,
            }
        partial.mkdir(parents=True, exist_ok=True)
        marker = partial / "COPY.json"
        if marker.exists():
            require(
                json_read(marker).get("approval") == approval,
                "COPY_CONFLICT",
                "Partial copy belongs to a different operation",
            )
        else:
            atomic_json(
                marker,
                {
                    "format": "AP20Copy/1",
                    "approval": approval,
                    "created": now(),
                    "state": "INCOMPLETE",
                },
            )
        progress.phase("Copy archives", sum(f["size"] for f in files.values()), "bytes")
        for name, expected in files.items():
            check_destination(store, destination)
            copy_file(
                no_links(root.joinpath(*name.split("/"))),
                partial.joinpath(*name.split("/")),
                expected,
                progress,
            )
        new_index = {
            **index,
            "packages": refs,
            "scope": "COMPLETE_PLAN" if len(refs) == index["planned_packages"] else "PARTIAL_PLAN",
        }
        # Never execute supplied helpers or bless changed helper bytes. Preserve
        # the sealed reader, including a valid legacy reader, byte-for-byte.
        helper = no_links(root / "RESTORE.py")
        progress.phase("Copy recovery kit", helper.stat().st_size, "bytes")
        copy_file(
            helper,
            partial / "RESTORE.py",
            {"sha256": kit["files"]["RESTORE.py"], "size": helper.stat().st_size},
            progress,
        )
        write_copy_readme(
            no_links(root / "README.txt"),
            partial / "README.txt",
            kit["files"]["README.txt"],
            new_index["scope"],
        )
        if "ARCHIVE.html" in kit["files"]:
            new_index["human_manifest"] = "ARCHIVE.html"
            archive_html.write_catalogue(partial, new_index)
        atomic_json(partial / "ARCHIVE.json", new_index)
        lines = []
        metadata_names = ["ARCHIVE.json", "README.txt", "RESTORE.py"]
        if new_index.get("human_manifest") == "ARCHIVE.html":
            metadata_names.append("ARCHIVE.html")
        for name in metadata_names + [r["receipt"] for r in refs]:
            lines.append(hash_file(partial.joinpath(*name.split("/"))) + "  " + name + "\n")
        with (partial / "SHA256SUMS").open("w", encoding="utf-8", newline="\n") as out:
            out.write("".join(lines))
            out.flush()
            os.fsync(out.fileno())
        check_copy_metadata(partial, dest, review)
        progress.event("INFO", "READBACK_BEGIN", destination=destination)
        result = recovery.run(partial, progress=recovery_progress(progress))
        check_destination(store, destination)
        receipt = {
            "format": "AP20Replica/1",
            "id": uid("replica"),
            "build_id": index["build_id"],
            "destination_id": destination,
            "approval": approval,
            "created": now(),
            "state": "COPY_READBACK",
            "verification": result,
            "finalization": "Files closed and fsynced where supported; LTFS must still be safely unmounted/reloaded and verified independently",
        }
        completion = {"format": "AP20Copy/1", "approval": approval, "state": "COMPLETE"}
        check_copy_metadata(
            partial,
            dest,
            review,
            {
                "REPLICA.json": len(canonical(receipt)) + 1,
                "COPY.json": len(canonical(completion)) + 1,
            },
        )
        atomic_json(partial / "REPLICA.json", receipt)
        atomic_json(marker, completion)
        check_copy_metadata(partial, dest, review)
        fsync_dir(partial)
        require(not final.exists(), "REPLICA_CONFLICT", "Final replica already exists")
        recovery.publish_new(partial, final)
        fsync_dir(final.parent)
        reconcile_replica(store, receipt, final, index["build_id"], destination, approval)
        return {
            "state": "COPY_READBACK",
            "path": str(final),
            "replica_id": receipt["id"],
            "reused": False,
            "verification": result,
        }
