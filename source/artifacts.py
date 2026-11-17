"""Stream PAX archives, commit verified packages, and publish portable catalogues."""

from __future__ import annotations
import contextlib
import gzip
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import threading
import uuid
from decimal import Decimal
from pathlib import Path
from . import __version__, capacity, kit_publication
from . import recovery
from .planning import Policy, finalize
from .util import (
    CHUNK,
    atomic_json,
    canonical,
    digest,
    disjoint,
    fsync_dir,
    hash_file,
    json_read,
    no_links,
    now,
    regular_source,
    require,
    root_identity,
    uid,
    within,
)

EXTENSIONS = {"none": ".tar", "gzip": ".tar.gz", "zstd": ".tar.zst"}


class CountWriter:
    def __init__(self, stream):
        self.stream, self.done = stream, 0

    def write(self, data):
        written = self.stream.write(data)
        if written is None:
            written = len(data)
        self.done += written
        return written


@contextlib.contextmanager
def encoded_writer(path, codec, level, progress=None):
    require(codec in EXTENSIONS, "CODEC", "Unsupported encoder")
    proc = None
    stop_monitor = threading.Event()
    monitor = None
    with path.open("xb") as raw, tempfile.TemporaryFile() as errors:
        stream = raw
        try:
            if codec == "gzip":
                stream = gzip.GzipFile(
                    filename="", fileobj=raw, mode="wb", compresslevel=level, mtime=0
                )
            elif codec == "zstd":
                exe = shutil.which("zstd")
                require(
                    exe is not None,
                    "ZSTD_MISSING",
                    "Install zstd or explicitly choose plain TAR/gzip; no silent substitution",
                )
                proc = subprocess.Popen(
                    [exe, "-q", "-" + str(level), "-T2", "--check", "-c"],
                    stdin=subprocess.PIPE,
                    stdout=raw,
                    stderr=errors,
                    shell=False,
                )
                stream = proc.stdin
                if progress is not None:
                    # GUI cancellation cannot interrupt a worker blocked while
                    # a stalled encoder holds a full stdin pipe. Killing this
                    # owned child releases that write; finally always reaps it.
                    def watch_cancellation():
                        while not stop_monitor.wait(0.1):
                            if progress.cancelled.is_set():
                                try:
                                    if proc.poll() is None:
                                        proc.kill()
                                except OSError:
                                    pass
                                return

                    monitor = threading.Thread(target=watch_cancellation, daemon=True)
                    monitor.start()
            counter = CountWriter(stream)
            yield counter
            if progress is not None:
                progress.check()
            if stream is not raw:
                stream.close()
            if proc:
                code = proc.wait(timeout=120)
                errors.seek(0)
                require(
                    code == 0,
                    "ENCODER_FAILED",
                    "Zstandard encoder failed",
                    stderr=errors.read(4096).decode(errors="replace"),
                )
            raw.flush()
            os.fsync(raw.fileno())
        except BaseException:
            if progress is not None:
                progress.check()
            raise
        finally:
            stop_monitor.set()
            if monitor is not None:
                monitor.join(timeout=1)
            if proc and proc.poll() is None:
                proc.kill()
                proc.wait()
            if stream is not raw and not stream.closed:
                try:
                    stream.close()
                except (BrokenPipeError, OSError):
                    pass


class HashReader:
    def __init__(self, stream, progress, path):
        self.stream, self.p, self.path = stream, progress, path
        self.hash = hashlib.sha256()
        self.done = 0

    def read(self, n=-1):
        self.p.check()
        data = self.stream.read(n if n >= 0 else CHUNK)
        self.hash.update(data)
        self.done += len(data)
        self.p.advance(len(data), self.path)
        return data


def source_check(st, node, rebound=False):
    require(stat.S_ISREG(st.st_mode), "SOURCE_TYPE", "Source is not a regular file")
    require(
        st.st_size == node["size"],
        "SOURCE_SIZE_CHANGED",
        "File length changed since scan",
        node=node["id"],
    )
    require(
        node["mtime_ns"] is not None and st.st_mtime_ns == node["mtime_ns"],
        "SOURCE_TIME_CHANGED",
        "File timestamp changed or was not recorded",
        node=node["id"],
    )
    if not rebound:
        if node["device"] is not None:
            require(
                str(st.st_dev) == node["device"],
                "SOURCE_DEVICE_CHANGED",
                "File device changed; explicitly rebind and revalidate the source",
            )
        if node["inode"] is not None:
            require(
                str(st.st_ino) == node["inode"],
                "SOURCE_OBJECT_CHANGED",
                "File object identity changed since scan",
                node=node["id"],
            )
    attrs = getattr(st, "st_file_attributes", 0)
    require(
        not attrs & (0x400 | 0x1000 | 0x4000 | 0x40000 | 0x400000),
        "SOURCE_ATTRIBUTE",
        "Source became a reparse/offline/encrypted/recall object",
    )


def validate_plan(store, plan_id, progress):
    plan = store.need("plans", plan_id)
    policy = Policy(**json.loads(plan["policy"])).validate()
    result = finalize(store, plan_id, policy, progress, persist=False)
    require(
        result["fingerprint"] == plan["fingerprint"],
        "PLAN_CHANGED",
        "Saved plan decisions or membership do not match their fingerprint",
    )
    return plan, policy, result["counts"]


def preflight_build(store, plan_id, output, progress, packages=None, accept_exclusions=False):
    plan, policy, counts = validate_plan(store, plan_id, progress)
    output = no_links(Path(output), missing_ok=True)
    requested = set(packages or [])
    all_packages = store.rows("SELECT * FROM packages WHERE plan_id=? ORDER BY kind,id", (plan_id,))
    known = {p["id"] for p in all_packages}
    require(
        not requested - known,
        "PACKAGE",
        "Unknown selected package",
        unknown=sorted(requested - known),
    )
    selected = [p for p in all_packages if not requested or p["id"] in requested]
    # Include directory metadata for the selected source(s); partial coverage stays labelled.
    owners = {p["snapshot_id"] for p in selected}
    selected = [
        p
        for p in all_packages
        if p in selected or (p["kind"] == "directories" and p["snapshot_id"] in owners)
    ]
    require(selected, "NO_PACKAGES", "No packages selected")
    # A partial operation depends on its selected observations, not every source
    # that happens to be present in the larger saved plan.
    selected_counts = [json.loads(store.need("snapshots", sid)["counts"]) for sid in owners]
    source_errors = sum(item.get("errors", 0) for item in selected_counts)
    exclusions = sum(item.get("excluded", 0) for item in selected_counts)
    require(
        not source_errors,
        "SOURCE_ERRORS",
        "Selected source has unresolved inventory errors. Rescan or correct the source before building.",
        errors=source_errors,
    )
    require(
        not exclusions or accept_exclusions,
        "EXCLUSIONS",
        "Review and explicitly accept recorded exclusions before building",
        excluded=exclusions,
    )
    require(
        not any(p["status"] == "BLOCKED" for p in selected),
        "PACKAGE_LIMIT",
        "Selected package exceeds the configured maximum; revise the plan",
    )
    sources = store.rows(
        "SELECT s.*,ps.snapshot_id,ps.namespace FROM plan_sources ps JOIN snapshots sn ON sn.id=ps.snapshot_id JOIN sources s ON s.id=sn.source_id WHERE ps.plan_id=?",
        (plan_id,),
    )
    # Every known source constrains output placement, even when another source
    # is intentionally offline for a partial build. Missing roots need no I/O.
    for src in sources:
        root = no_links(Path(src["root"]), missing_ok=True)
        require(
            disjoint(root, output),
            "OUTPUT_OVERLAP",
            "Staging output must be disjoint from all plan source roots",
            root=src["root"],
            output=str(output),
        )
    sources = [source for source in sources if source["snapshot_id"] in owners]
    for src in sources:
        root = no_links(Path(src["root"]))
        require(
            root.is_dir(), "SOURCE_OFFLINE", "Source directory is unavailable", root=src["root"]
        )
        require(
            disjoint(root, output),
            "OUTPUT_OVERLAP",
            "Staging output must be disjoint from source roots",
            root=src["root"],
            output=str(output),
        )
        identity = json.loads(src["identity"])
        require(
            not identity.get("unbound"),
            "SOURCE_UNBOUND",
            "Imported source is not bound. Explicitly bind its source ID before building.",
            source=src["id"],
        )
        if not identity.get("unbound"):
            actual = root_identity(root)
            require(
                all(actual[k] == identity.get(k) for k in ("device", "inode", "platform")),
                "SOURCE_ROOT_CHANGED",
                "Source root identity changed; explicitly bind the source to the intended location",
                source=src["id"],
            )
    require(
        not within(store.root, output), "OUTPUT_WORKSPACE", "Output cannot contain the workspace"
    )
    if output.exists():
        marker = output / "BUILD.json"
        require(
            marker.is_file(),
            "OUTPUT_EXISTS",
            "Existing output is not an owned compatible build; choose a new directory",
        )
        state = json_read(marker)
        require(
            state.get("plan_fingerprint") == plan["fingerprint"],
            "OUTPUT_PLAN",
            "Output belongs to another plan",
        )
    parent = output
    while not parent.exists():
        parent = parent.parent
    remaining = selected
    # Completed package directories are reusable, not assumed safe without a readback.
    kit_view = kit_publication.inspect(output, recovery_progress(progress))
    if kit_view["index"] is not None:
        old = kit_view["index"]
        existing = {r["package_id"] for r in old.get("packages", [])}
        remaining = [package for package in selected if package["id"] not in existing]
    staging = capacity.staging_requirement(remaining)
    need = staging["required_bytes"]
    free = shutil.disk_usage(parent).free
    require(
        free >= need,
        "STAGING_SPACE",
        "Insufficient estimated staging space",
        estimated_required=need,
        available=free,
    )
    if any(p["codec"] == "zstd" for p in selected):
        require(
            shutil.which("zstd") is not None,
            "ZSTD_MISSING",
            "This plan needs zstd. Install it or create a plain-TAR/gzip revision.",
        )
    summary = {
        "operation": "build",
        "plan_id": plan_id,
        "plan_fingerprint": plan["fingerprint"],
        "output": str(output),
        "packages": [p["id"] for p in selected],
        "estimated_required_bytes": need,
        "capacity_breakdown": staging,
        "free_bytes": free,
        "excluded_observations": exclusions,
        "accept_exclusions": bool(accept_exclusions),
        "kit_publication": {key: value for key, value in kit_view.items() if key != "index"},
        "source_roots": [
            {"id": s["id"], "root": s["root"], "identity": json.loads(s["identity"])}
            for s in sources
        ],
        "contract": "logical-files-v1; no ACLs, ADS, EFS, link topology or sparse allocation; per-file consistency checks, not a snapshot",
    }
    # Free-space fluctuations are not approval identity; all capacities are checked again.
    binding = {
        k: v
        for k, v in summary.items()
        if k
        not in ("estimated_required_bytes", "capacity_breakdown", "free_bytes", "kit_publication")
    }
    summary["approval"] = digest(binding)
    return summary


def build_package(
    store,
    plan_id,
    package,
    root,
    namespace,
    folder,
    relative_folder,
    maximum,
    progress,
    rebound=False,
):
    temp = folder.with_name("." + folder.name + ".partial-" + uuid.uuid4().hex[:8])
    temp.mkdir(parents=True, mode=0o700)
    artifact = temp / ("payload" + EXTENSIONS[package["codec"]])
    manifest = temp / "members.jsonl.gz"
    member_count = logical_bytes = 0
    progress.phase("Build " + package["id"], package["logical_bytes"], "bytes")
    with manifest.open("xb") as raw_manifest:
        with contextlib.ExitStack() as stack:
            rows = stack.enter_context(
                gzip.GzipFile(filename="", fileobj=raw_manifest, mode="wb", mtime=0)
            )
            encoded = stack.enter_context(
                encoded_writer(artifact, package["codec"], package["level"], progress)
            )
            with tarfile.open(
                fileobj=encoded, mode="w|", format=tarfile.PAX_FORMAT, bufsize=CHUNK
            ) as tar:
                tar.copybufsize = CHUNK
                for row in store.db.execute(
                    "SELECT n.* FROM members m JOIN nodes n ON n.id=m.node_id WHERE m.plan_id=? AND m.package_id=? ORDER BY n.id",
                    (plan_id, package["id"]),
                ):
                    node = dict(row)
                    progress.check()
                    relative = store.path(node["id"])
                    name = namespace + ("/" + relative if relative else "")
                    t = tarfile.TarInfo(name)
                    t.uid = t.gid = 0
                    t.uname = t.gname = ""
                    mode = (
                        node["mode"]
                        if node["mode"] is not None
                        else (0o755 if node["kind"] == "directory" else 0o644)
                    )
                    mtime = node["mtime_ns"]
                    if node["kind"] == "directory":
                        source = no_links(root.joinpath(*relative.split("/")) if relative else root)
                        require(
                            source.is_dir(),
                            "DIRECTORY_CHANGED",
                            "Recorded directory is not present",
                            path=relative,
                        )
                        # Inferred directories have no recorded time; disclose build-time observation.
                        if mtime is None:
                            mtime = source.stat().st_mtime_ns
                    require(
                        mtime is not None, "MTIME_UNKNOWN", "A file modification time is required"
                    )
                    t.mode = mode & 0o777
                    t.mtime = mtime // 1_000_000_000
                    t.pax_headers = {"mtime": str(Decimal(mtime) / Decimal(1_000_000_000))}
                    record = {
                        "name": name,
                        "kind": node["kind"],
                        "size": node["size"] if node["kind"] == "file" else 0,
                        "mtime_ns": mtime,
                        "mode": mode & 0o777,
                        "mtime_basis": "build-observed"
                        if node["mtime_ns"] is None
                        else "inventory",
                        "source_relative_path": relative,
                    }
                    if node["kind"] == "directory":
                        t.type = tarfile.DIRTYPE
                        t.size = 0
                        tar.addfile(t)
                    else:
                        t.type = tarfile.REGTYPE
                        t.size = node["size"]
                        with regular_source(root, relative) as (stream, opened):
                            source_check(opened, node, rebound)
                            reader = HashReader(stream, progress, relative)
                            tar.addfile(t, reader)
                            after = os.fstat(stream.fileno())
                            require(
                                (
                                    opened.st_dev,
                                    opened.st_ino,
                                    opened.st_size,
                                    opened.st_mtime_ns,
                                    opened.st_ctime_ns,
                                )
                                == (
                                    after.st_dev,
                                    after.st_ino,
                                    after.st_size,
                                    after.st_mtime_ns,
                                    after.st_ctime_ns,
                                ),
                                "SOURCE_CHANGED",
                                "Source changed during packaging",
                                path=relative,
                            )
                            sha = reader.hash.hexdigest()
                            require(
                                reader.done == node["size"],
                                "SOURCE_SHORT",
                                "Source became shorter during packaging",
                                path=relative,
                            )
                            if node["sha256"]:
                                require(
                                    sha == node["sha256"],
                                    "SOURCE_HASH_CHANGED",
                                    "Content differs from the optional scan hash",
                                    path=relative,
                                )
                            record["sha256"] = sha
                            logical_bytes += reader.done
                    rows.write(canonical(record) + b"\n")
                    member_count += 1
                    # tarfile's writer also retains TarInfo entries unless cleared.
                    tar.members.clear()
            tar_bytes = encoded.done
        raw_manifest.flush()
        os.fsync(raw_manifest.fileno())
    actual = artifact.stat().st_size
    require(
        actual <= maximum,
        "ACTUAL_SIZE_LIMIT",
        "Completed encoded package exceeds the maximum; partial output retained, not committed",
        actual=actual,
        maximum=maximum,
        path=str(temp),
    )
    progress.phase("Hash package", actual, "bytes")
    artifact_hash = hash_file(artifact, progress)
    receipt = {
        "format": "AP20Package/1",
        "package_id": package["id"],
        "logical_package_id": package["logical_id"],
        "plan_id": plan_id,
        "source_namespace": namespace,
        "codec": package["codec"],
        "level": package["level"],
        "artifact": relative_folder + "/" + artifact.name,
        "artifact_bytes": actual,
        "artifact_sha256": artifact_hash,
        "manifest": relative_folder + "/" + manifest.name,
        "manifest_bytes": manifest.stat().st_size,
        "manifest_sha256": hash_file(manifest),
        "tar_bytes": tar_bytes,
        "logical_bytes": logical_bytes,
        "member_count": member_count,
        "preservation": "logical-files-v1",
        "created": now(),
        "verification": "DECODE_PENDING",
    }
    # Verify while still staged. Temporarily map receipt paths to this owned directory.
    local = {**receipt, "artifact": artifact.name, "manifest": manifest.name}
    atomic_json(temp / "receipt.json", local)
    ref = {
        "package_id": package["id"],
        "receipt": "receipt.json",
        "receipt_sha256": hash_file(temp / "receipt.json"),
    }
    recovery.verify_package(temp, ref, progress=recovery_progress(progress))
    receipt["verification"] = "DECODE_VERIFIED"
    atomic_json(temp / "receipt.json", receipt)
    fsync_dir(temp)
    require(not folder.exists(), "PACKAGE_EXISTS", "Package output appeared; refusing overwrite")
    recovery.publish_new(temp, folder)
    fsync_dir(folder.parent)
    return {
        "package_id": package["id"],
        "receipt": relative_folder + "/receipt.json",
        "receipt_sha256": hash_file(folder / "receipt.json"),
        "artifact_sha256": artifact_hash,
        "actual_bytes": actual,
        "logical_bytes": logical_bytes,
    }


def recovery_progress(progress):
    return progress.recovery_callback()


def build(store, plan_id, output, progress, approval, packages=None, accept_exclusions=False):
    review = preflight_build(store, plan_id, output, progress, packages, accept_exclusions)
    require(
        approval == review["approval"],
        "APPROVAL",
        "Build requires confirmation of the current preflight",
        required=review["approval"],
    )
    output = Path(review["output"])
    if review["kit_publication"]["pending"]:
        recovered = kit_publication.recover(output, recovery_progress(progress))
        progress.event("INFO", "RECOVERED_KIT_PUBLICATION", **recovered)
        review = preflight_build(store, plan_id, output, progress, packages, accept_exclusions)
        require(
            approval == review["approval"],
            "APPROVAL",
            "Build preflight changed during publication recovery",
            required=review["approval"],
        )
    plan = store.need("plans", plan_id)
    policy = Policy(**json.loads(plan["policy"]))
    output.mkdir(parents=True, exist_ok=True)
    marker = output / "BUILD.json"
    if marker.exists():
        state = json_read(marker)
    else:
        state = {
            "format": "AP20Build/1",
            "id": uid("build"),
            "plan_id": plan_id,
            "plan_fingerprint": plan["fingerprint"],
            "created": now(),
            "state": "RUNNING",
        }
        atomic_json(marker, state)
    build_id = state["id"]
    store.db.execute(
        "INSERT INTO builds VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,updated=excluded.updated,detail=excluded.detail",
        (
            build_id,
            plan_id,
            str(output),
            "RUNNING",
            state["created"],
            now(),
            canonical({"approval": approval}).decode(),
        ),
    )
    store.commit()
    sources = {
        r["snapshot_id"]: r
        for r in store.rows(
            "SELECT ps.snapshot_id,ps.namespace,s.* FROM plan_sources ps JOIN snapshots sn ON sn.id=ps.snapshot_id JOIN sources s ON s.id=sn.source_id WHERE ps.plan_id=?",
            (plan_id,),
        )
    }
    previous = json_read(output / "ARCHIVE.json") if (output / "ARCHIVE.json").is_file() else None
    refs = {r["package_id"]: r for r in previous.get("packages", [])} if previous else {}
    try:
        progress.set_overall(0, len(review["packages"]), "built and verified packages")
        for position, pid in enumerate(review["packages"], 1):
            progress.check()
            progress.set_package(pid, position, len(review["packages"]))
            p = store.one("SELECT * FROM packages WHERE plan_id=? AND id=?", (plan_id, pid))
            src = sources[p["snapshot_id"]]
            rel = "packages/" + src["namespace"]
            outer = p["anchor"].split("/")[: policy.outer_depth] if p["anchor"] else []
            if outer:
                rel += "/" + ("/".join(outer))
            rel += "/" + pid
            folder = output.joinpath(*rel.split("/"))
            no_links(folder, missing_ok=True)
            folder.parent.mkdir(parents=True, exist_ok=True)
            if folder.exists():
                # A crash after package commit but before catalogue publication is recoverable.
                ref = {
                    "package_id": pid,
                    "receipt": rel + "/receipt.json",
                    "receipt_sha256": hash_file(folder / "receipt.json"),
                }
                r, _, _ = recovery.validate_receipt(output, ref, hash_payload=False)
                require(
                    r["plan_id"] == plan_id
                    and r["logical_package_id"] == p["logical_id"]
                    and r["codec"] == p["codec"]
                    and r["level"] == p["level"],
                    "RESUME_MISMATCH",
                    "Existing package does not match the plan",
                )
                recovery.verify_package(output, ref, recovery_progress(progress))
                refs[pid] = {
                    **ref,
                    "artifact_sha256": r["artifact_sha256"],
                    "actual_bytes": r["artifact_bytes"],
                    "logical_bytes": r["logical_bytes"],
                }
                progress.event("INFO", "REUSED_VERIFIED_PACKAGE", package=pid)
            else:
                refs[pid] = build_package(
                    store,
                    plan_id,
                    p,
                    Path(src["root"]),
                    src["namespace"],
                    folder,
                    rel,
                    policy.maximum,
                    progress,
                    json.loads(src["identity"]).get("rebound", False),
                )
            # Each committed package is catalogued. A partial plan is clearly labelled.
            publish_bundle(
                output, store, plan, sources, list(refs.values()), build_id, progress=progress
            )
            progress.set_overall(position, len(review["packages"]), "built and verified packages")
        recovery.validate_kit(output, progress=recovery_progress(progress))
        # Observer notifications can fail or request cancellation. Emit before
        # the durable completion fence, never convert a committed build later.
        progress.set_package(None)
        progress.check()
        state["state"] = (
            "COMPLETE" if len(refs) == json.loads(plan["counts"])["packages"] else "PARTIAL_PLAN"
        )
        state["updated"] = now()
        atomic_json(marker, state)
        store.db.execute(
            "UPDATE builds SET state=?,updated=?,detail=? WHERE id=?",
            (
                state["state"],
                now(),
                canonical(
                    {"packages": len(refs), "catalogue_sha256": hash_file(output / "ARCHIVE.json")}
                ).decode(),
                build_id,
            ),
        )
        store.commit()
        return {
            "build_id": build_id,
            "path": str(output),
            "state": state["state"],
            "packages": len(refs),
            "catalogue_sha256": hash_file(output / "ARCHIVE.json"),
        }
    except BaseException as exc:
        state["state"] = "INTERRUPTED"
        state["error"] = str(exc)
        atomic_json(marker, state)
        store.db.execute(
            "UPDATE builds SET state='INTERRUPTED',updated=?,detail=? WHERE id=?",
            (now(), canonical({"error": str(exc)}).decode(), build_id),
        )
        store.commit()
        raise


def publish_bundle(output, store, plan, sources, refs, build_id, progress=None):
    expected = json.loads(plan["counts"])["packages"]
    all_packages = store.rows(
        "SELECT id,snapshot_id,kind FROM packages WHERE plan_id=? ORDER BY id", (plan["id"],)
    )
    dependencies, metadata_ids = capacity.package_metadata_dependencies(all_packages)
    index = {
        "format": "AP20Archive/1",
        "producer": __version__,
        "collection_id": store.db.execute(
            "SELECT value FROM meta WHERE key='collection_id'"
        ).fetchone()[0],
        "build_id": build_id,
        "plan_id": plan["id"],
        "plan_fingerprint": plan["fingerprint"],
        "scope": "COMPLETE_PLAN" if len(refs) == expected else "PARTIAL_PLAN",
        "planned_packages": expected,
        "preservation": "logical-files-v1",
        "human_manifest": "ARCHIVE.html",
        "consistency": "Per-file checked live reads; not a filesystem snapshot",
        "directory_metadata_dependencies": dependencies,
        "directory_metadata_packages": metadata_ids,
        "sources": [
            {
                "source_id": r["id"],
                "snapshot_id": r["snapshot_id"],
                "namespace": r["namespace"],
                "label": r["label"],
                "original_root": r["root"],
            }
            for r in sources.values()
        ],
        "packages": sorted(refs, key=lambda r: r["package_id"]),
        "excluded_observations": json.loads(plan["counts"])["excluded_observations"],
    }
    readme = (
        "ARCHIVIST — PORTABLE ARCHIVE SET\n\n"
        "1. Keep ARCHIVE.json, package receipts, manifests and payloads together.\n"
        "2. Verify: python RESTORE.py .\n"
        "3. Restore to a NEW directory: python RESTORE.py . --to /path/to/new-folder\n"
        "   Use --permissions to restore ordinary permission bits where supported.\n"
        "4. Current Archivist readers support Python 3.8+. A resumed legacy set\n"
        "   may retain an older RESTORE.py with its original Python requirement.\n"
        "   .tar.zst requires the zstd command.\n"
        "5. Without this script: decode zstd/gzip if necessary, then extract PAX TAR\n"
        "   into one destination; members are source-namespaced relative paths.\n"
        "   Directory-metadata packages follow payloads to restore directory times.\n\n"
        "SHA256SUMS covers receipts and metadata. Receipts hash payloads and gzip\n"
        "JSONL manifests; manifests hash individual files. Keep a catalogue digest\n"
        "separately. These hashes are not digital signatures.\n\n"
        "Scope: " + index["scope"] + ". A partial plan is NOT a complete backup.\n"
        "Preserves ordinary files, paths, empty directories, modification times and\n"
        "recorded ordinary modes. Does not preserve ACL/ADS/EFS, link relationships,\n"
        "sparse allocation or an exact filesystem image. Sources were not snapshots.\n"
        "Immediate readback is not proof of offline tape readability. Finalize,\n"
        "unmount/reload and verify through a qualified LTFS implementation.\n"
    )
    kit_publication.publish(
        output,
        index,
        readme.encode("utf-8"),
        progress=recovery_progress(progress) if progress is not None else None,
    )
