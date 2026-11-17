"""Human-readable, offline archive catalogue; no scripts or remote resources."""

from __future__ import annotations

import html
import os
from pathlib import Path

from . import recovery
from .util import fsync_dir


def write_catalogue(root: Path, index: dict, *, output_root: Path | None = None) -> None:
    """Render the supplied set selection; callers seal the resulting file."""
    root = Path(root)
    output_root = root if output_root is None else Path(output_root)
    target = output_root / "ARCHIVE.html"
    temporary = output_root / "ARCHIVE.html.partial"

    def esc(value: object) -> str:
        return html.escape(str(value), quote=True)

    with temporary.open("w", encoding="utf-8", newline="\n") as out:
        out.write("""<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Archive catalogue</title>
<style>body{font:16px/1.5 system-ui,sans-serif;max-width:1100px;margin:40px auto;padding:0 20px;color:#17252b;background:#fafbf8}h1{font-size:2rem}table{width:100%;border-collapse:collapse}th,td{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid #bdc9c7}code{overflow-wrap:anywhere;font-size:.86em}.scope{padding:12px;border-left:5px solid #356962;background:#eaf2ed}.small{font-size:.9em}a{color:#195950}@media print{body{margin:0;max-width:none}tr{break-inside:avoid}}</style>
<main><h1>Archive catalogue</h1>
<p>This page describes the accompanying archive set. It works offline and contains no JavaScript.</p>
""")
        out.write(
            '<p class="scope"><strong>Set scope: '
            + esc(index.get("scope", "UNSPECIFIED"))
            + "</strong><br>"
        )
        out.write(
            esc(len(index["packages"]))
            + " packages present; "
            + esc(index.get("planned_packages", "unknown"))
            + " planned.</p>"
        )
        out.write(
            "<p><strong>Plan:</strong> <code>"
            + esc(index.get("plan_id", "unknown"))
            + "</code><br>"
        )
        out.write(
            "<strong>Build:</strong> <code>" + esc(index.get("build_id", "unknown")) + "</code></p>"
        )
        out.write(
            "<h2>Verify and recover</h2><p>With Python 3.12 or newer, run these commands from this folder. Install the zstd command when .tar.zst payloads are present.</p>"
        )
        out.write(
            "<pre><code>python RESTORE.py .\npython RESTORE.py . --to NEW_DIRECTORY</code></pre>"
        )
        out.write(
            "<p>The output directory must be new. Keep ARCHIVE.json, SHA256SUMS, RESTORE.py, package receipts, manifests and payloads together. A payload package and its source directory-metadata packages form the full metadata-preserving recovery selection.</p>"
        )
        out.write(
            "<p>Successful verification checks the selected bytes against the supplied checksums. Checksums do not authenticate an archive whose catalogue and checksums were replaced together. Immediate readback does not establish offline tape readability.</p>"
        )
        out.write("<h2>Sources</h2><ul>")
        for source in index.get("sources", []):
            out.write(
                "<li>"
                + esc(source.get("label", "Source"))
                + " — restore prefix <code>"
                + esc(source.get("namespace", ""))
                + "</code></li>"
            )
        out.write(
            "</ul><h2>Packages</h2><table><thead><tr><th>Package</th><th>Payload / logical bytes</th><th>Encoded SHA-256</th></tr></thead><tbody>"
        )
        for ref in index["packages"]:
            receipt = recovery.read_json(recovery.located(root, ref["receipt"]))
            out.write(
                "<tr><td><code>"
                + esc(ref["package_id"])
                + "</code><br>"
                + esc(receipt.get("member_count", 0))
                + " members</td>"
            )
            out.write(
                "<td><code>"
                + esc(receipt["artifact"])
                + "</code><br>"
                + esc(receipt["artifact_bytes"])
                + " / "
                + esc(receipt["logical_bytes"])
                + " B</td>"
            )
            out.write("<td><code>" + esc(receipt["artifact_sha256"]) + "</code></td></tr>")
        out.write(
            "</tbody></table><h2>Preservation boundary</h2><p>Ordinary files, recorded paths, empty directories, modification times and ordinary modes. ACLs, alternate data streams, EFS, link relationships, sparse allocation and complete filesystem images are outside this profile. Live reads are checked per file; they are not a point-in-time filesystem snapshot.</p>"
        )
        out.write(
            '<p class="small">ARCHIVE.json is the machine-readable catalogue. Compressed JSONL manifests list individual members. This HTML page is a convenience view of the same selected set.</p></main></html>\n'
        )
        out.flush()
        os.fsync(out.fileno())
    os.replace(temporary, target)
    fsync_dir(output_root)
