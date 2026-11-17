# Changelog

Changes to Archivist are recorded here by product version. Archive format,
workspace schema and operation-contract versions are separate. Release evidence
and actual test environments are recorded in [docs/validation](docs/validation/README.md).

## [2.0.0] — 2026-11-17

First stable Archivist release line, published from
[github.com/Julesc013/archivist](https://github.com/Julesc013/archivist).
This release incorporates the audited V2 development snapshot and the additional
compatibility, allocation and operator work below. A stable tag is gated on the
recorded software and packaging checks; it does not designate untested tape
hardware or historical browser versions as supported.

### Added

- Chosen Archivist identity, `archivist.py` portable entry point, `archivist`
  console command and flat `source/` package mapping.
- Python 3.8+ runtime negotiation with an independent SQLite 3.31+ minimum.
  Diagnostics work without first creating a workspace and report observed
  UPSERT, backup and connection-safety capabilities.
- Verification that `trusted_schema`, foreign keys, read-only import mode,
  workspace WAL and full synchronization were actually enabled. Unsupported
  capabilities produce explicit failures rather than weaker modes.
- Per-medium directory-metadata closure in allocation, including every physical
  copy in capacity accounting and disclosing repeated metadata copies.
- Separate overall package progress, current package and active-step progress.
  Unknown totals remain unknown; immediate copy readback is a distinct phase.
- ES5 browser bootstrap and readable compatibility guidance around an ES2017
  application. Native dialog, details and newer CSS support have fallbacks.
- Root `TODO.md` and `ROADMAP.md` as the single current backlog and release plan,
  with bounded minor-release goals and explicit qualification gates.
- Release gates configured for 19 native OS/Python combinations and three
  browser engines (Chromium, Firefox and WebKit), plus the optional-dialog
  fallback. Completed results belong to the recorded validation evidence.
- A Windows regression creates an actual directory junction in an owned fixture,
  checks that a junction scan root is refused and a descendant is excluded, and
  verifies that its external target remains untouched.

### Fixed

- Windows filesystem inventory now obtains device/inode/link-count fields from
  fresh `os.stat(..., follow_symlinks=False)` rather than zero-filled cached
  `DirEntry.stat()` identity fields. This prevents false mount exclusions and
  source-device changes.
- Windows inventory hashing compares `ctime` before and after reading through
  the same open descriptor, avoiding incompatible creation/change-time meanings
  in path-based `stat` and descriptor-based `fstat`. Device, inode, size and
  modification-time crosschecks remain; POSIX also retains the pre-open `ctime`
  crosscheck. See [compatibility](docs/guides/compatibility.md).
- Workspace/source containment compares both resolved paths, including Windows
  short-path aliases; workspace descendants remain forbidden scan roots.
- Verified macOS system aliases `/var`, `/tmp` and `/etc` are normalized to their
  root-owned `/private` targets. Arbitrary user and descendant symlinks remain
  refused in both application and standalone recovery.
- Avoidable newer-Python APIs and syntax no longer raise the application floor.
  Compatibility does not change no-replace publication semantics.
- Cancellation reaches receipt/manifest hashing and long allocation work.
  A cancellation monitor interrupts Archivist's own blocked zstd encoder and
  reaps it; no guarantee is made for uninterruptible kernel/device I/O.
- Progress-observer failures cannot turn a completed data operation into an
  ambiguous write outcome; observer failure is reported separately.
- Completed plan coverage reports the actual member count; bounded progress
  updates also make long coverage checks visible without per-member UI updates.
- Existing GUI selection, paging, revision, reconnect and readback state repairs
  remain shared with the CLI's underlying operations.

### Retained from the audited V2 foundation

- Validate the complete sealed recovery kit before verification, copy and resume;
  do not silently reseal a changed reader or documentation file.
- Keep archive-set scope separate from the selected verification scope. Reconcile
  receipt IDs, reference digests, planned counts and metadata.
- Reject contradictory TAR metadata, malformed endings and nonzero bytes after
  the first archive ending, including bytes buffered inside the TAR parser.
- Publish new packages, replicas and restored directories without replacement.
  Reconcile an already-published replica into SQLite exactly once on retry.
- Stage recovery-kit updates with hash-bound old/candidate bytes and a durable
  journal. Read-only preflight inspects pending recovery; an approved build
  replays it under the writer lock. Unknown changes remain errors.
- Use measured artifact/sidecar/kit lengths for allocation and copy where
  available. Credit validated completed partial-copy bytes without skipping
  final content verification or hiding orphaned space consumption.
- Restrict partial-build availability checks to needed observations while
  retaining source/output separation for every source in the plan.
- Preserve grouping reasons through encoding edits; support immutable diff and
  revert; bound both directory-path caches by entry and scalar-byte budgets.
- Generate an escaped, sealed offline HTML catalogue and provide manifest search
  with explicit complete/missing/unknown directory-metadata diagnostics.
- Build/check portable ZIP/TAR.GZ and Python wheel/sdist distributions, including
  isolated installed execution and source/DB-independent recovery checks.

### Compatibility and limits

- Product version is `2.0.0`; stored `AP20*/1` format identifiers, `.ap20` suffix,
  SQLite application ID and schema 1 are intentionally retained.
- The application has no mandatory third-party Python runtime dependencies.
  Plain TAR and gzip use the standard library; Zstandard uses external `zstd`.
- Python compatibility is distinct from upstream security support. Prefer a
  maintained interpreter; consult [Python's status table](https://devguide.python.org/versions/).
- Local disk workflows are the core. Linux mounted LTFS remains experimental;
  physical finalization/reload/readback, live Everything integration and specific
  native filesystem/browser combinations require their recorded qualification.
- No raw tape, robotics, encryption, snapshot consistency, extended metadata
  profile, cross-package deduplication dependency or rolling staging deletion.

## [2.0.0-alpha.1] — 2026-11-17

Unpublished Archive Planner V2 development snapshot derived from the verified
V20 evaluation archive. It established strict kit/recovery validation,
transactional publication, copy reconciliation, shared capacity accounting,
immutable revisions, bounded caches, HTML catalogues and operator-state fixes.
Its Python baseline was 3.12+, and its name was provisional.

The retained [alpha validation](docs/validation/alpha1/README.md) describes that
historical snapshot. Its test counts, timings and GUI limitations are not the
final Archivist 2.0.0 qualification record.

## Historical input: 20.0.0-eval.1

The supplied file was `ArchivePlanner_v20.0.0-eval.1.zip`, not an Archivist release.
See [provenance and compatibility](docs/architecture/v20-transition.md) for its
SHA-256 and baseline. Earlier prototype iteration numbers are not reconstructed
as invented Archivist semantic-version releases.
