# Archivist

**2.0.0 — directory-first archives with independent recovery.**

[Repository](https://github.com/Julesc013/archivist) · [Releases](https://github.com/Julesc013/archivist/releases) · [Changelog](CHANGELOG.md) · [TODO](TODO.md) · [Roadmap](ROADMAP.md)

Archivist inventories directory trees, keeps related folders together where
limits permit, plans their placement on finite media, builds ordinary PAX TAR
archives, and verifies copies. Each archive set carries the information and
reader needed to recover without the original disks or application workspace.
The same operations serve a command-line interface and a local browser interface.

The [validation record](docs/validation/README.md) identifies the actual tested
interpreters, operating systems, browsers and artifacts. A successful disk test
does not qualify tape hardware. Mounted LTFS is explicitly experimental; raw tape,
robotics and optical burning are outside this release.

## Start from an extracted release or checkout

Keep `archivist.py`, `source/` and `launchers/` together. No editable installation
or third-party Python runtime package is required.

| Requirement | Purpose |
|---|---|
| Python 3.8 or newer, including its standard-library modules | Application and standalone reader |
| SQLite 3.31.0 or newer linked to the application's Python | Working evidence, verified safety settings, backup and UPSERT |
| A capable browser | Optional local GUI; the CLI works independently |
| `zstd` executable | Only for Zstandard encoding/decoding; plain TAR and gzip use Python |

Choose a maintained Python release when available. Compatibility with an older
interpreter does not renew its upstream security support; see the
[Python release status](https://devguide.python.org/versions/). SQLite is checked
independently of the Python version. The diagnostics command works before a
workspace is created and explains unavailable capabilities.

```sh
python3 archivist.py --help
python3 archivist.py doctor
python3 archivist.py --workspace ./evidence gui
```

On Windows, use `py -3` instead of `python3`, or open `launchers/GUI.cmd`.
`launchers/CLI.cmd` opens a guided command prompt. Linux launchers are
`launchers/GUI.sh` and `launchers/CLI.sh`; macOS uses the corresponding `.command`
files. Launchers locate the extracted application independently of the caller's
working directory. Unix launchers accept `ARCHIVIST_PYTHON` to select an interpreter.

An installed wheel provides the `archivist` command. Its distribution metadata
name is `archivist-archive`; the repository name is not a claim that an unrelated
package named `archivist` on a public registry belongs to this project.

## Four stages

| Stage | What you do | Evidence retained |
|---|---|---|
| Sources | Scan a root or import an Everything export; inspect exclusions and errors | Observation, source identity, counts and issue ledger |
| Plan | Review grouping reasons, change encoding, move/merge members, compare or revert revisions | Immutable memberships, policy, lineage and fingerprint |
| Archive | Review retained staging space, build and read back, then copy to registered destinations | Receipts, hashes, operation history and replica identity |
| Recover | Search manifests, review required packages, verify or restore into a new directory | Explicit selection scope and verification result |

The GUI starts with a small compatibility loader. Its full interface targets
ES2017 and the required browser APIs; missing features or a failed script leave
readable guidance instead of an empty page. Native dialogs are optional, and
basic layout/focus styles remain available without newer CSS features. Feature
detection is not proof that an old browser version has been qualified. The
[compatibility guide](docs/guides/compatibility.md) describes the boundaries.

Closing a browser tab leaves the local service and active job running. Use
**File → Quit service** after work has finished or cancellation has completed.
The server binds to `127.0.0.1`, validates its session token and request origin,
and serves an explicit set of local assets. It needs no cloud account.

## Command-line workflow

Use existing `./data` as the source. Keep the evidence workspace, retained staging,
replica destination and restore output outside that source. Replace
`SNAPSHOT_ID`, `PLAN_ID` and `DESTINATION_ID` with the IDs returned by preceding
commands; they are literal placeholders below.

```sh
python3 archivist.py --workspace ./evidence scan ./data --backend filesystem --hash-files
python3 archivist.py --workspace ./evidence plan SNAPSHOT_ID --codec gzip
python3 archivist.py --workspace ./evidence packages PLAN_ID
python3 archivist.py --workspace ./evidence build PLAN_ID --output ./staging/archive-set
python3 archivist.py --workspace ./evidence dest ./replica-disk --label "Copy A"
python3 archivist.py --workspace ./evidence copy ./staging/archive-set --destination DESTINATION_ID
python3 archivist.py --workspace ./evidence verify ./staging/archive-set
python3 archivist.py --workspace ./evidence find ./staging/archive-set Photos
python3 archivist.py --workspace ./evidence restore ./staging/archive-set --output ./restored-data
```

Build, copy and restore present a current review and ask for confirmation.
For unattended runs, add `--yes` after deciding the paths and selection;
`--quiet --json` produces machine-readable results. Global options work before
or after the subcommand. Handled operational failures use JSON on stderr and
exit 2. Argument-parser errors use ordinary text; interruption exits 130.
See the [operator guide](docs/guides/operator.md) and [operation contract](docs/specs/06-operations.md).

Windows defaults to required Everything acquisition. Choose `--backend filesystem`
explicitly for ordinary traversal. Finding `es.exe` does not establish that
Everything's service, instance or index is usable; live acquisition checks that
separately. Frozen EFU import works without the live Windows service.

## Media planning and capacity

Allocation uses deterministic first-fit decreasing groups. Each payload is
placed with its source's required directory-metadata packages. Metadata is
counted once within one medium and charged again when another medium needs a
physical copy. A group that cannot fit remains unallocated. Every medium's
`packages` list is a concrete copy selection, with replication costs disclosed.
This is a heuristic, with no claim of global packing optimality.

Measured planning counts payloads, manifests, receipts, the recovery kit and
metadata headroom. Unbuilt packages use labelled estimates. Predicted software
or hardware compression does not authorize a copy. Copy preflight rechecks
actual free space, reserve, configured capacity and individual file limits.
Checked bytes from an interrupted copy receive appropriate retry credit;
orphaned or conflicting files do not become free space.

Staging retains completed packages. It is not a rolling one-package buffer.
The [capacity contract](docs/specs/05-capacity-and-planning.md) explains units,
estimates and the distinction between file lengths and physical media occupancy.
Mounted Linux LTFS requires explicit opt-in and its own
[hardware qualification](docs/guides/ltfs-qualification.md).

## Independent recovery

Every newly built set includes `ARCHIVE.json`, `ARCHIVE.html`, `SHA256SUMS`,
`README.txt`, `RESTORE.py`, package receipts, compressed JSONL member manifests,
and `.tar`, `.tar.gz` or `.tar.zst` payloads. Open the HTML catalogue offline,
or run these commands from the archive-set directory:

```sh
python3 RESTORE.py .
python3 RESTORE.py . --to /path/to/new-directory
python3 RESTORE.py . --to /path/to/another-new-directory --permissions
```

The reader uses Python 3.8+ standard-library modules, including `sqlite3` for a
temporary path index; it does not open the original evidence database. Zstandard
payloads additionally require `zstd`. No application installation is required.
Standalone recovery does not use the application's SQLite 3.31 feature set.

Payload packages are independently decodable. Full preservation of a source's
recorded directory metadata additionally requires its directory-only packages.
Search proposes the available dependency closure and reports missing or unknown
metadata. Explicit `--package` options remain exact selections. Searching does
not verify payload contents, and restoring a package can extract more than the
files that matched the search.

The baseline preserves ordinary file bytes, source-namespaced paths, empty
directories, recorded modification times and ordinary modes where supported.
Modes are applied only with `--permissions`. It does not preserve ACLs, xattrs,
ADS, EFS, hard-link relationships, sparse allocation or a complete filesystem
image. Live reads are checked per file; they are not a cross-file snapshot.
Checksums establish consistency with the supplied catalogue, not authenticity
against coordinated replacement of the catalogue and seals.

## Maintenance and evidence

Implementation lives directly in `source/`, mapped to the unique `archivist`
Python namespace. CLI and HTTP use shared application operations. Recovery has
one independently executable source; a valid sealed helper from an existing set
is preserved rather than silently upgraded and resealed.

- [Specifications](docs/specs/README.md): preservation, formats, safety, capacity and operations.
- [Architecture](docs/architecture/README.md): module responsibilities and transaction boundaries.
- [Contributing](CONTRIBUTING.md): tests, build checks and release gates.
- [Security](SECURITY.md): threat model, safe failure and reporting.
- [TODO](TODO.md) and [roadmap](ROADMAP.md): delivered code, remaining qualification and small future releases.

Archivist 2.0.0 descends from the supplied `ArchivePlanner_v20.0.0-eval.1.zip`.
Its original name, checksum and baseline evidence are retained in the
[transition record](docs/architecture/v20-transition.md). Existing `AP20*/1`
identifiers, `.ap20` evidence bundles and schema 1 remain recognizable.
[Import into a new workspace](docs/guides/migration.md); imported sources need
explicit binding and imported destinations start disabled. The original MIT
copyright notice remains intact.
