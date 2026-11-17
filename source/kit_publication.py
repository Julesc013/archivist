"""Recoverable publication of the small, flat standalone recovery kit.

Package files are immutable and committed separately. A prepared journal binds
the old and candidate control-file bytes before any public name is replaced.
Readers may refuse an incomplete generation; the next approved build recovers
it under the workspace writer lock. This is a filesystem protocol, not a claim
that a storage device honors flushes or that several renames are atomic as one.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from pathlib import Path

from . import archive_html, recovery
from .util import atomic_json, canonical, fsync_dir, hash_file, json_read, require


# These persisted identifiers predate the product rename and remain readable.
TRANSACTION = ".archive-planner-kit"
FORMAT = "ArchivePlannerKitTransaction/1"
# Seal last: an intermediate mixture must never advertise a matching seal.
FILES = ("RESTORE.py", "README.txt", "ARCHIVE.html", "ARCHIVE.json", "SHA256SUMS")
MANDATORY = {"RESTORE.py", "README.txt", "ARCHIVE.json", "SHA256SUMS"}


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _limit(name):
    return 4 * recovery.MAX_JSON if name == "SHA256SUMS" else recovery.MAX_JSON


def _read(path, expected=None):
    path = recovery.no_links(Path(path))
    require(
        path.is_file() and path.stat().st_size <= _limit(path.name),
        "KIT_TRANSACTION_FILE",
        "Missing or oversized publication file",
        path=str(path),
    )
    data = path.read_bytes()
    require(
        expected is None or _digest(data) == expected,
        "KIT_TRANSACTION_CONFLICT",
        "Publication file changed; no automatic recovery",
        path=str(path),
    )
    return data


def _write_new(path, data):
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def replace_file(source, destination, expected):
    """Keep the staged copy intact so an interrupted replacement can be replayed."""
    data = _read(source, expected)
    temporary = destination.with_name(destination.name + ".kit-" + uuid.uuid4().hex)
    _write_new(temporary, data)
    os.replace(temporary, destination)
    fsync_dir(destination.parent)


def _file_state(root, name):
    path = root / name
    recovery.no_links(path, missing=True)
    if not path.exists():
        return None
    return _digest(_read(path))


def _check_current(root, journal):
    states = {}
    for name in FILES:
        states[name] = _file_state(root, name)
        allowed = {journal["old_files"].get(name), journal["new_files"].get(name)}
        require(
            states[name] in allowed,
            "KIT_TRANSACTION_CONFLICT",
            "Public recovery-kit bytes differ from both recorded generations; no automatic recovery",
            file=name,
        )
    return states


def _load(root, progress=None):
    folder = recovery.no_links(root / TRANSACTION)
    require(folder.is_dir(), "KIT_TRANSACTION", "Publication journal is not a directory")
    journal = json_read(recovery.located(folder, "STATE.json"))
    require(
        isinstance(journal, dict) and journal.get("format") == FORMAT,
        "KIT_TRANSACTION",
        "Unrecognized publication journal",
    )
    require(
        journal.get("phase") in ("PREPARED", "COMMITTED", "ROLLED_BACK")
        and type(journal.get("old_complete")) is bool,
        "KIT_TRANSACTION",
        "Invalid publication journal phase",
    )
    marker = json_read(recovery.located(root, "BUILD.json"))
    require(
        journal.get("build_id") == marker.get("id")
        and journal.get("plan_fingerprint") == marker.get("plan_fingerprint"),
        "KIT_TRANSACTION_OWNER",
        "Publication journal belongs to another build",
    )
    for side in ("old", "new"):
        entries = journal.get(side + "_files")
        require(
            isinstance(entries, dict)
            and set(entries) <= set(FILES)
            and all(recovery.sha_text(value) for value in entries.values()),
            "KIT_TRANSACTION",
            "Invalid publication snapshot inventory",
        )
        snapshot = recovery.no_links(folder / side)
        require(
            snapshot.is_dir() and {p.name for p in snapshot.iterdir()} == set(entries),
            "KIT_TRANSACTION",
            "Publication snapshot inventory differs from journal",
        )
        for name, checksum in entries.items():
            _read(snapshot / name, checksum)
    require(
        MANDATORY <= set(journal["new_files"]),
        "KIT_TRANSACTION",
        "Candidate recovery kit is incomplete",
    )
    new_index = recovery.validate_kit(root, control_root=folder / "new", progress=progress)["index"]
    require(
        new_index.get("build_id") == journal["build_id"]
        and new_index.get("plan_fingerprint") == journal["plan_fingerprint"],
        "KIT_TRANSACTION_OWNER",
        "Candidate catalogue belongs to another build",
    )
    old_index = None
    if journal["old_complete"]:
        require(
            MANDATORY <= set(journal["old_files"]),
            "KIT_TRANSACTION",
            "Previous recovery kit is incomplete",
        )
        old_index = recovery.validate_kit(root, control_root=folder / "old", progress=progress)[
            "index"
        ]
        require(
            old_index.get("build_id") == journal["build_id"]
            and old_index.get("plan_fingerprint") == journal["plan_fingerprint"],
            "KIT_TRANSACTION_OWNER",
            "Previous catalogue belongs to another build",
        )
    else:
        require(
            set(journal["old_files"]) <= {"RESTORE.py"},
            "KIT_TRANSACTION",
            "An initial publication has unexpected previous metadata",
        )
    states = _check_current(root, journal)
    all_new = all(states[name] == journal["new_files"].get(name) for name in FILES)
    all_old = all(states[name] == journal["old_files"].get(name) for name in FILES)
    if journal["phase"] == "COMMITTED":
        require(
            all_new,
            "KIT_TRANSACTION_CONFLICT",
            "Committed recovery kit changed before journal cleanup",
        )
    if journal["phase"] == "ROLLED_BACK":
        require(
            all_old,
            "KIT_TRANSACTION_CONFLICT",
            "Rolled-back recovery kit changed before journal cleanup",
        )
    action = "commit" if all_new and journal["phase"] != "ROLLED_BACK" else "rollback"
    return journal, new_index if action == "commit" else old_index, action


def inspect(root, progress=None):
    """Read-only preflight view; never replay or remove a pending transaction."""
    root = Path(root)
    recovery.no_links(root / TRANSACTION, missing=True)
    if (root / TRANSACTION).exists():
        journal, index, action = _load(root, progress)
        return {
            "pending": True,
            "action": action,
            "index": index,
            "transaction_id": journal.get("id"),
        }
    if (root / "ARCHIVE.json").exists():
        return {
            "pending": False,
            "action": None,
            "index": recovery.validate_kit(root, progress=progress)["index"],
        }
    return {"pending": False, "action": None, "index": None}


def _retire(root, journal, phase):
    folder = root / TRANSACTION
    atomic_json(folder / "STATE.json", {**journal, "phase": phase})
    retired = root / (TRANSACTION + "-retired-" + uuid.uuid4().hex)
    recovery.publish_new(folder, retired)
    fsync_dir(root)
    # Once renamed, the active journal is absent and the public kit is sealed.
    # A cleanup failure leaves bounded, recognizable metadata, not an active job.
    try:
        shutil.rmtree(retired)
        fsync_dir(root)
    except OSError:
        pass


def recover(root, progress=None):
    """Replay only a validated, hash-bound transaction; caller holds writer lock."""
    root = Path(root)
    if not (root / TRANSACTION).exists():
        return {"recovered": False}
    journal, index, action = _load(root, progress)
    if action == "rollback":
        for name in FILES:
            _check_current(root, journal)
            checksum = journal["old_files"].get(name)
            if checksum is not None:
                replace_file(root / TRANSACTION / "old" / name, root / name, checksum)
            elif (root / name).exists():
                # _check_current proved this is exactly the staged candidate.
                (root / name).unlink()
                fsync_dir(root)
        if journal["old_complete"]:
            recovery.validate_kit(root, progress=progress)
        _retire(root, journal, "ROLLED_BACK")
    else:
        recovery.validate_kit(root, progress=progress)
        _retire(root, journal, "COMMITTED")
    return {"recovered": True, "action": action, "packages": len(index["packages"]) if index else 0}


def publish(root, index, readme, progress=None):
    """Validate and publish a new kit, restoring prior exact bytes on failure."""
    root = Path(root)
    require(
        not (root / TRANSACTION).exists(),
        "KIT_TRANSACTION_PENDING",
        "Recover the pending publication before starting another",
    )
    previous = (
        recovery.validate_kit(root, progress=progress) if (root / "ARCHIVE.json").exists() else None
    )
    old_files = {}
    for name in FILES:
        if not (root / name).exists():
            continue
        if previous:
            require(
                name == "SHA256SUMS" or name in previous["files"],
                "KIT_UNSEALED_FILE",
                "Existing metadata is not covered by the previous seal",
                file=name,
            )
        else:
            require(
                name == "RESTORE.py",
                "KIT_UNSEALED_FILE",
                "Unsealed metadata exists without a recovery catalogue",
                file=name,
            )
            require(
                hash_file(root / name) == hash_file(Path(recovery.__file__)),
                "RECOVERY_HELPER_CONFLICT",
                "An unsealed recovery helper differs from this application",
            )
        old_files[name] = _file_state(root, name)
        if previous:
            expected = previous["seal_sha256"] if name == "SHA256SUMS" else previous["files"][name]
            require(
                old_files[name] == expected,
                "KIT_TRANSACTION_CONFLICT",
                "Previously verified metadata changed before staging",
                file=name,
            )
    helper = (
        _read(root / "RESTORE.py", old_files["RESTORE.py"])
        if "RESTORE.py" in old_files
        else _read(Path(recovery.__file__))
    )
    prepared = root / (TRANSACTION + "-prepared-" + uuid.uuid4().hex)
    prepared.mkdir(mode=0o700)
    try:
        old, new = prepared / "old", prepared / "new"
        old.mkdir()
        new.mkdir()
        for name, checksum in old_files.items():
            _write_new(old / name, _read(root / name, checksum))
        _write_new(new / "RESTORE.py", helper)
        _write_new(new / "README.txt", readme)
        _write_new(new / "ARCHIVE.json", canonical(index) + b"\n")
        archive_html.write_catalogue(root, index, output_root=new)
        checks = []
        for name in FILES[:-1]:
            checks.append(hash_file(new / name) + "  " + name + "\n")
        for ref in index["packages"]:
            receipt = recovery.located(root, ref["receipt"])
            require(
                hash_file(receipt) == ref["receipt_sha256"],
                "KIT_RECEIPT_CHANGED",
                "Receipt changed before kit publication",
                file=ref["receipt"],
            )
            checks.append(ref["receipt_sha256"] + "  " + ref["receipt"] + "\n")
        _write_new(new / "SHA256SUMS", "".join(checks).encode("utf-8"))
        # Bound all generated files using the independent reader before any
        # public control file is replaced or a complete set is advertised.
        recovery.validate_kit(root, control_root=new, progress=progress)
        if previous:
            recovery.validate_kit(root, control_root=old, progress=progress)
        journal = {
            "format": FORMAT,
            "id": uuid.uuid4().hex,
            "phase": "PREPARED",
            "build_id": index["build_id"],
            "plan_fingerprint": index["plan_fingerprint"],
            "old_complete": previous is not None,
            "old_files": old_files,
            "new_files": {name: hash_file(new / name) for name in FILES},
        }
        fsync_dir(old)
        fsync_dir(new)
        atomic_json(prepared / "STATE.json", journal)
        fsync_dir(prepared)
        recovery.publish_new(prepared, root / TRANSACTION)
        fsync_dir(root)
        try:
            for name in FILES:
                _check_current(root, journal)
                replace_file(
                    root / TRANSACTION / "new" / name, root / name, journal["new_files"][name]
                )
            recovery.validate_kit(root, progress=progress)
            _retire(root, journal, "COMMITTED")
        except BaseException as exc:
            try:
                # Cancellation should stop new work, not interrupt rollback.
                recover(root)
            except BaseException as rollback_error:
                # Python 3.8 has no add_note(). Retain the secondary failure as
                # structured diagnostic evidence without masking the primary one.
                exc.kit_recovery_error = str(rollback_error)
                if hasattr(exc, "detail") and isinstance(exc.detail, dict):
                    exc.detail["kit_recovery_error"] = str(rollback_error)
                if hasattr(exc, "add_note"):
                    exc.add_note("Kit recovery remains pending: " + str(rollback_error))
                # progress is the standalone reader's callback, not a Progress
                # instance. Application records kit_recovery_error separately.
            raise
    finally:
        if prepared.exists():
            shutil.rmtree(prepared)
