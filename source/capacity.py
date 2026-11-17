"""Shared byte accounting for planned packages, retained builds and replicas.

An estimate is not a promise of physical media occupancy. The allowances below
cover application metadata/headroom; filesystem or LTFS reserves are separate
destination policy, and execution still reconciles observed free space.
"""

from __future__ import annotations
from pathlib import Path
import re

from .util import no_links, require

COPY_SET_ALLOWANCE_BYTES = 4 * 1024 * 1024
STAGING_SET_ALLOWANCE_BYTES = 32 * 1024 * 1024
MANIFEST_ENTRY_ESTIMATE_BYTES = 512
RECEIPT_ESTIMATE_BYTES = 4096


def metadata_plan_selection(selected_ids, dependencies, *, known_metadata_ids=()) -> dict:
    """Report dependency coverage without changing selected packages or bytes.

    A missing declaration gives no evidence about metadata completeness. Callers
    with saved plan rows can identify directory-only packages explicitly; a
    standalone copy can identify only the metadata IDs named by its catalogue.
    """
    selected = set(selected_ids)
    if dependencies is None:
        return {
            "required_metadata_package_ids": [],
            "missing_metadata_package_ids": [],
            "metadata_completeness": "unknown",
            "metadata_dependency_basis": "No dependency declaration is available; byte fit does not establish complete directory metadata on this medium",
        }
    require(
        isinstance(dependencies, dict),
        "METADATA_DEPENDENCIES",
        "Invalid metadata dependency declaration",
    )
    metadata_ids = set(known_metadata_ids)
    for ident, required in dependencies.items():
        require(
            isinstance(ident, str)
            and re.fullmatch(r"P\d{6,}", ident) is not None
            and isinstance(required, list)
            and all(
                isinstance(value, str) and re.fullmatch(r"P\d{6,}", value) is not None
                for value in required
            ),
            "METADATA_DEPENDENCIES",
            "Invalid metadata dependency package IDs",
        )
        require(
            len(required) == len(set(required)) and ident not in required,
            "METADATA_DEPENDENCIES",
            "Duplicate or self-referencing metadata dependency",
        )
        metadata_ids.update(required)
    required = set().union(
        *(set(dependencies[ident]) for ident in selected if ident in dependencies)
    )
    missing = required - selected
    unknown = bool(selected - dependencies.keys() - metadata_ids)
    return {
        "required_metadata_package_ids": sorted(required),
        "missing_metadata_package_ids": sorted(missing),
        "metadata_completeness": "missing" if missing else "unknown" if unknown else "complete",
        "metadata_dependency_basis": "Coverage of the selected packages only; missing directory metadata is reported without adding packages or changing byte charges",
    }


def _bytes(value: int) -> int:
    require(
        type(value) is int and value >= 0, "CAPACITY", "Byte counts must be nonnegative integers"
    )
    return value


def package_footprint(
    artifact_bytes: int,
    manifest_bytes: int = 0,
    receipt_bytes: int = 0,
    *,
    basis: str = "measured",
) -> dict:
    """Account for every stored object belonging to one package."""
    require(basis in ("measured", "estimated"), "CAPACITY", "Unknown byte-count basis")
    artifact_bytes, manifest_bytes, receipt_bytes = map(
        _bytes, (artifact_bytes, manifest_bytes, receipt_bytes)
    )
    return {
        "artifact_bytes": artifact_bytes,
        "manifest_bytes": manifest_bytes,
        "receipt_bytes": receipt_bytes,
        "package_bytes": artifact_bytes + manifest_bytes + receipt_bytes,
        "basis": basis,
    }


def estimated_footprint(package: dict) -> dict:
    """Conservative planning inputs, with no predicted compression credit."""
    members = _bytes(package["file_count"]) + _bytes(package["dir_count"])
    return package_footprint(
        package["estimated_bytes"],
        members * MANIFEST_ENTRY_ESTIMATE_BYTES,
        RECEIPT_ESTIMATE_BYTES,
        basis="estimated",
    )


def recovery_kit_footprint(root: str | Path) -> dict:
    """Measure a previously validated kit, excluding per-package objects.

    A selected replica may use a smaller catalogue. Charging the full source kit
    is a conservative bound that both allocation and copy preflight can share.
    The extra copy allowance bounds newly generated replica/job receipts.
    """
    root = no_links(Path(root))
    names = ["ARCHIVE.json", "README.txt", "RESTORE.py", "SHA256SUMS"]
    if (root / "ARCHIVE.html").exists():
        names.append("ARCHIVE.html")
    files = {}
    for name in names:
        path = no_links(root / name)
        require(
            path.is_file(),
            "RECOVERY_KIT",
            "Recovery-kit member is not a regular file",
            path=str(path),
        )
        files[name] = path.stat().st_size
    return {
        "files": files,
        "recovery_kit_bytes": sum(files.values()),
        "largest_file_bytes": max(files.values(), default=0),
        "basis": "Measured full source recovery kit; conservative for subset replicas",
    }


def copy_requirement(remaining_package_bytes: int, *, recovery_kit_bytes: int = 0) -> dict:
    """Shared replica budget, charged once per used destination allocation."""
    remaining_package_bytes = _bytes(remaining_package_bytes)
    recovery_kit_bytes = _bytes(recovery_kit_bytes)
    return {
        "package_bytes": remaining_package_bytes,
        "recovery_kit_bytes": recovery_kit_bytes,
        "set_allowance_bytes": COPY_SET_ALLOWANCE_BYTES,
        "required_bytes": remaining_package_bytes + recovery_kit_bytes + COPY_SET_ALLOWANCE_BYTES,
        "basis": "Package objects plus recovery kit and bounded metadata headroom; destination reserve is separate",
    }


def staging_requirement(packages: list[dict]) -> dict:
    """Budget all selected packages retained in the build; no rolling eviction."""
    footprints = [estimated_footprint(package) for package in packages]
    fields = {
        key: sum(item[key] for item in footprints)
        for key in ("artifact_bytes", "manifest_bytes", "receipt_bytes", "package_bytes")
    }
    return {
        **fields,
        "set_allowance_bytes": STAGING_SET_ALLOWANCE_BYTES,
        "required_bytes": fields["package_bytes"] + STAGING_SET_ALLOWANCE_BYTES,
        "mode": "retained-build",
        "basis": "Estimated remaining selected packages retained together; no rolling staging",
    }
