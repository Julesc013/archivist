# Archivist

**2.0.0-alpha.1 — working project name, local development distribution.**

Plan directory trees into bounded packages, build ordinary PAX TAR archives,
verify their contents, copy them to selected destinations, and recover them
without the original source disks or application database.

This is the first implementation release following the V20 audit. It is an
alpha for evaluation with disposable or independently backed-up data. The
qualification record is in [docs/validation/README.md](docs/validation/README.md).
Windows, macOS, browser rendering and physical LTFS qualification are separate
gates; their presence in a CI definition does not establish a successful run.

## Start

Install **Python 3.12 or newer**. No third-party Python runtime packages are
required. Install the `zstd` command only if you choose Zstandard compression.
The GUI requires a browser. Python, the browser and optional external commands
are runtime dependencies, even though no `pip install` is needed for a checkout.

```sh
python3 archivist.py --help
python3 archivist.py --workspace /path/to/evidence doctor
python3 archivist.py --workspace /path/to/evidence gui
```

On Windows, use `py -3` in place of `python3`, or open `launchers/GUI.cmd`.
`launchers/CLI.cmd` opens a small command prompt. Unix launchers use their own
installation path rather than the current working directory. The macOS
`.command` launchers still require native qualification.

The interface has four stages: **Sources → Plan → Archive → Recover**. Closing
its tab leaves the local process and any running job alive. Use **Shutdown**
after work finishes. The service binds to `127.0.0.1`, checks a random session
token and request origin, and serves only its three static assets.

## Command-line workflow

Replace the angle-bracketed IDs below with IDs printed by the preceding command.
Use an evidence directory outside your source. Build and restore destinations
must also be separate from the source.

```sh
python3 archivist.py --workspace /evidence scan /data --backend filesystem
python3 archivist.py --workspace /evidence plan <snapshot-id> --codec gzip
python3 archivist.py --workspace /evidence packages <plan-id>
python3 archivist.py --workspace /evidence build <plan-id> --output /staging/archive
python3 archivist.py --workspace /evidence dest /media/backup --label "Copy A"
python3 archivist.py --workspace /evidence copy /staging/archive --destination <destination-id>
python3 archivist.py --workspace /evidence verify /staging/archive
python3 archivist.py --workspace /evidence find /staging/archive Photos
python3 archivist.py --workspace /evidence restore /staging/archive --output /restore/new
```

Build, copy and restore show a current preflight review and request confirmation.
For automation, `--yes` authorizes the reviewed operation; `--quiet --json`
produces machine-readable output. Global options work before or after the
command. Handled operational errors use JSON on standard error and exit status 2.
Command-line usage errors are plain text; interruption reports cancellation and
exits 130. IDs are data; do not execute untrusted strings as shell commands.

Windows defaults to required Everything acquisition. Choose `--backend
filesystem` explicitly for ordinary traversal. Everything executable presence
does not prove that its service/IPC is working; acquisition checks that separately.

## What this alpha changes

- Checks the complete sealed recovery kit before verifying, copying or resuming
  a set, so an altered helper cannot silently acquire a fresh seal.
- Reconciles a published replica back into the database after a publication /
  catalogue interruption.
- Separates archive-set completeness from the packages actually verified.
- Rejects contradictory TAR metadata and nonzero data after the archive ending.
- Uses one capacity model, distinguishes measured from estimated sizes, counts
  package objects and recovery-kit overhead, and labels retained staging.
- Limits a partial build's availability checks to its required source observations.
- Preserves grouping reasons through codec edits and creates immutable reverts.
- Fixes package selections across pages, stale UI state, hidden list truncation,
  move-target lookup and completed-job progress.
- Bounds both directory-path caches by entry count and retained scalar bytes;
  evicted paths are reconstructed from indexed evidence.
- Adds manifest search, replica visibility and an offline `ARCHIVE.html` catalogue.
- Maps the unique Python package `archivist` directly onto physical `source/`.

See [CHANGELOG.md](CHANGELOG.md), [specifications](docs/specs/README.md), and
[the backlog](docs/BACKLOG.md) for acceptance evidence and open work.

## Recovery contract

Every new archive set contains `ARCHIVE.json`, `ARCHIVE.html`, `SHA256SUMS`,
`README.txt`, `RESTORE.py`, package receipts, compressed JSONL member manifests,
and `.tar`, `.tar.gz` or `.tar.zst` payloads. The recovery script imports only
Python's standard library and invokes `zstd` when required. It does not import
this application or open its evidence database.

```sh
python3 RESTORE.py .
python3 RESTORE.py . --to /path/to/new-directory
```

Payload packages are independently decodable. Complete preservation of a
source's recorded directory metadata additionally requires its directory-only
packages. The GUI search proposes that dependency closure; explicit `--package`
options select exactly the supplied packages. Searching manifests does not
verify payload contents, and restoring matching packages can restore more than
the matching files.

The baseline preserves ordinary files, representable paths, empty directories,
recorded modification times and ordinary permission bits where supported. It
does not promise a filesystem image, application consistency, ACLs, ADS, EFS,
hard-link relationships or sparse allocation. Live scans are observations, not
point-in-time snapshots. SHA-256 checksums establish consistency with the given
catalogue, not authenticity if the catalogue and seals were replaced together.

## Media and capacity

Local directory destinations are implemented. Mounted LTFS on Linux is
**experimental** and requires explicit opt-in; no physical cartridge was
qualified for this release. Raw tape, spanning a compressed stream across tapes,
robotics, media formatting and optical burning are outside v2.0 scope.

Allocation is deterministic first-fit decreasing, not an exact optimizer. No
predicted compression saving or hardware-compression credit can authorize a
copy. Preflight rechecks observed free space and configured limits. A retained
build keeps all completed packages until the operator manages its storage; the
application does not implement rolling deletion or claim that only one package
of scratch space is required.

## Repository and development

Code is directly in `source/`, with cohesive modules and `source/static/` for
the GUI. CLI and HTTP call the same application operations. The independent
recovery reader has one authoritative source file; builds copy it unchanged.

```sh
python3 scripts/run_tests.py --json-out docs/validation/unit-tests-local.json
node tests/gui_state.test.cjs
python3 scripts/build_release.py --output dist
python3 scripts/check_release.py dist/archivist-2.0.0-alpha.1.zip
python3 scripts/check_python_distribution.py --build --output /path/to/new/build-check
```

The Node command is a logic test, not browser qualification. Optional browser
tests require Playwright and a working browser runtime. Portable packaging uses
the standard library; wheel/sdist packaging uses setuptools and wheel as build
dependencies. See [CONTRIBUTING.md](CONTRIBUTING.md).

The temporary distribution name `archivist-archive` and command
`archivist` have not been published or reserved. Naming research continues
in [docs/NAMING.md](docs/NAMING.md). Renaming the product must not rename existing
archive format identifiers or invalidate preserved evidence.

## Existing evidence

V20's `AP20*/1` file-format identifiers, `.ap20` evidence bundles and schema 1
remain intentionally recognizable. Import into a **new** V2 workspace; imported
sources require explicit binding and imported destinations start disabled.
The V2 default data/config directories differ from V20's. See
[migration](docs/guides/migration.md). Preserve the supplied MIT licence.

