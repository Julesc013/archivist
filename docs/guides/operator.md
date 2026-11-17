# Operator workflow

Start with [README.md](../../README.md) for installation and a complete small CLI
example. Keep five roles separate: source data, working evidence, build staging,
registered replica destination and new restore output. Do not place an output
inside any registered source, including an offline source omitted from a partial
build.

## Sources: establish what was observed

Run `python3 archivist.py doctor` before the first job. It reports runtime and
actual tool capability. On Windows the default scanner requires Everything;
choose `scan ROOT --backend filesystem` explicitly for the filesystem backend.
A tool being present is not evidence of successful live Everything IPC.

Scanning records an observation, not a storage snapshot. Review included,
excluded and error entries before planning. `--hash-files` adds recorded content
hashes and costs an additional source read. It improves later change detection
but cannot freeze a running application across multiple files. Keep source data
available until artifacts have been built and independently checked.

## Plan: review grouping and media fit

A plan keeps fitting subtrees together and records its decisions. Minimum and
target sizes are goals; maximum limits are enforced. Package identities and
membership drive selection, including packages outside the visible page.
Changes and reverts produce new immutable revisions; use `diff` to review them.

`allocate PLAN_ID --media media.json` reads a JSON list of media descriptions.
An illustrative entry is:

```json
[{"id":"disk-a","capacity":1000000000000,"reserve":50000000000,"occupied":0,"max_file":250000000000}]
```

These values are examples, not an LTO profile. Capacity, reserve, occupied and
max_file are bytes. Add `--bundle PATH` to use checked actual build lengths.
Unbuilt plans use conservative estimates without predicted compression credit.
An estimated fit still requires real destination preflight.

Each allocated medium includes a payload's directory-metadata dependencies.
Shared metadata is stored once within a medium and charged again on any other
medium that needs it. A group that cannot fit intact remains unallocated.
Use the returned `media.packages` as the concrete copy selection. Explicit copy
`--package` arguments remain exact and may deliberately omit dependencies; read
the resulting missing/unknown metadata diagnostics.

## Archive: build, verify, then copy

Build preflight binds approval to the plan, paths and selected identities. It
checks relevant sources and retained staging needs. Current staging retains the
whole completed set; a largest-package scratch estimate is insufficient.
The CLI prompts before execution; `--yes` approves the current preflight and
does not disable safety checks.

Progress reports the current step and package separately. A build package counts
complete only after content verification and recoverable kit publication. Copy
counts completed copies, then performs replica readback; an unknown verification
total stays unknown rather than being presented as a false percentage.

Cancel through the GUI or Ctrl+C. Hash and streaming boundaries observe
cancellation, and owned zstd children are terminated and reaped. Kernel/device
I/O can still delay return. Check reported paths and state before retrying.
Do not remove a journal or edit seals to force a resume. Exact-capacity retries
credit only checked, owned existing bytes; orphan fragments still consume space.

Register the chosen destination with `dest PATH --label LABEL`. A registration
is not a tape-format operation. Use mounted LTFS only with its explicit
experimental option and the [qualification worksheet](ltfs-qualification.md).
Copy verifies the sealed source kit, writes without replacement and reads the
replica back. A replica receipt permits idempotent catalogue reconciliation after
a publication/catalogue interruption. It does not certify cartridge unload/reload.

## Recover: check scope before extraction

`find BUNDLE QUERY` searches checked manifests and proposes whole-package IDs.
It reports whether directory metadata is present, missing or unknown, and does
not verify payload bytes. A selected package may contain files beyond the match.
Review the proposed selection and required copies before restoring.

`verify BUNDLE` checks the stored selection; `--package` narrows that selection.
The result distinguishes stored set scope from verification scope. A successful
check of one package does not verify other packages in a complete set.

Restore always requires a new output path. It does not merge into existing data.
Use `--permissions` only when restoring ordinary recorded mode bits is intended
and supported by the target platform. This profile does not restore ACLs, ADS,
xattrs, link relationships or filesystem images.

On another machine, keep the set together and invoke:

```sh
python3 RESTORE.py .
python3 RESTORE.py . --to /path/to/new/restored-output
```

Python 3.8+ with its standard-library modules suffices for none/gzip. zstd payloads
also need the external decoder. The helper does not need the original application
workspace, source disks or installed Archivist package. Retain trusted digests
separately: coherent replacement of a set and all its hashes defeats a checksum's
authenticity, even though accidental corruption remains detectable.

## Local browser lifecycle

The GUI is a loopback service opened with a session token. Its compatibility
loader leaves readable guidance when the browser lacks required features.
Use **File → Quit service** to shut it down. Closing the tab leaves a running job
and service alive. After a lost connection, inspect status before retrying a
mutation; the interface does not blindly resend it.
