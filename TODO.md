# Archivist TODO and acceptance backlog

This is the canonical current backlog. [ROADMAP.md](ROADMAP.md) groups future
work into small compatible releases. Historical `docs/BACKLOG.md` points here.
The [validation record](docs/validation/README.md) is authoritative for actual
runs, versions and environments; this file does not duplicate changing test counts.

**Implemented** means the code and a relevant regression are present. It does
not imply every native or hardware combination passed. **Gate** requires retained
execution evidence before the associated support claim is published. **Open**
is planned work with no completion claim. P0 concerns data correctness or release
integrity; P1 concerns qualification and operator correctness; P2 is extension work.

## Implemented foundation

| ID | Priority | Status | Acceptance represented in the tree |
|---|---|---|---|
| AP-001 | P0 | Implemented | Preserve the verified V20 input identity, licence and original bytes |
| AP-003 | P0 | Implemented | Changed helper/README/catalogue seal refuses verify/copy/resume without resealing |
| AP-004 | P0 | Implemented | Publication-before-catalogue interruption reconciles one verified replica identity on retry |
| AP-005 | P0 | Implemented | Preflight and execution distinguish set/selection scope and validate receipt IDs/counts |
| AP-006 | P0 | Implemented | Correctly resealed TAR trailer/metadata contradictions fail at their intended checks |
| AP-007 | P0 | Implemented | Measured allocation/copy agree on payloads, sidecars, kit/headroom and file limits |
| AP-008 | P0 | Implemented | Public allocation consumes checked actual build sizes; corrupt available evidence cannot become an estimate |
| AP-009 | P0 | Implemented | A-only build tolerates offline B while output stays disjoint from all plan-source paths |
| AP-010 | P1 | Implemented | Root direct-file grouping respects its whole-group ceiling and hard maximum |
| AP-011 | P0 | Implemented | Media allocation includes required directory metadata, charges replication, and leaves non-fitting payload groups unallocated |
| AP-012 | P1 | Implemented | Off-page package settings, move targets, paging and stale selection state are tested |
| AP-013 | P1 | Implemented | Revisions retain lineage; diff/revert use shared operations without mutating history |
| AP-015 | P1 | Implemented | Overall/package/step progress are distinct; completion freezes timing and unknown totals are not percentages |
| AP-016 | P0 | Implemented | Flat physical source layout installs only the unique `archivist` namespace |
| AP-023 | P1 | Implemented / further scale open | Finite path caches and measured synthetic fixtures; no million-entry or whole-process bound inferred |
| AP-024 | P1 | Implemented boundary | Retained staging is budgeted; rolling eviction is absent and never promised |
| AP-026 | P1 | Implemented | Escaped offline `ARCHIVE.html` is sealed and regenerated for selected replicas |
| AP-029 | P2 | Implemented / lifecycle open | Replica listing/reconciliation exist; offline verification history remains future work |
| AP-031 | P0 | Implemented | Journalled kit updates recover known generations after process termination; unknown changes remain errors |
| AP-032 | P0 | Implemented | Portable release checks reject empty/incomplete/duplicate seals before executing a launcher |
| AP-034 | P0 | Implemented | Python/SQLite capability checks fail before workspace creation; older APIs retain safety semantics |
| AP-035 | P0 | Implemented | Windows inventory uses complete stat identity; macOS root aliases are narrowly normalized without accepting user links |
| AP-036 | P1 | Implemented | Browser bootstrap gives useful fallback diagnostics; full app targets ES2017 and optional native dialog support |
| AP-037 | P0 | Implemented | Blocked zstd encoding, metadata hashing and allocation honor cancellation; child processes are reaped |
| AP-038 | P1 | Implemented | Progress observer failures are isolated and visible rather than corrupting operation state |

## Release and support gates

| ID | Priority | Gate | Required evidence |
|---|---|---|---|
| AP-002 | P0 | Contract review | Specs, public examples, actual responses and test expectations agree for the release commit |
| AP-014 | P1 | Tool diagnostics | Distinguish presence, usable runtime, live Everything IPC/index and deliberately unavailable features |
| AP-017 | P0 | Independent recovery | Source/workspace absent; none/gzip/zstd where provided; exact restored contents and independent TAR oracle |
| AP-018 | P0 | Distribution | Complete portable seals, isolated wheel/sdist launch, static assets, installed helper identity and repeatable portable builds |
| AP-019 | P1 | Supported browsers | Actual engine versions; navigation, rendering, keyboard/focus, dialog fallback, reconnect and CSP enforcement |
| AP-020 | P1 | Windows support statement | Native launchers/filesystem/reparse/name cases; live Everything remains a separate integration exercise |
| AP-021 | P1 | macOS support statement | Native launchers, standard aliases and APFS name/case/metadata cases |
| AP-022 | P0 | Production LTFS claim | Identified hardware/driver/media, finalization, unload/reload and independently recorded readback |
| AP-025 | P1 | Operator usability | Observe complete tasks, including mistaken selection, failed preflight, cancellation, resume and recovery |
| AP-027 | P0 | Release publication | Exact commit/version, passing declared gates, artifact digests, complete source, current evidence and release notes |

Native fixes and simulated regressions do not close a native gate on their own.
The current validation record records rerun outcomes. Physical LTFS qualification
is excluded from the 2.0 production-support claim rather than marked complete.
A workflow file, skipped test or future test plan is not evidence of a successful run.

## Open work for frequent minor releases

| ID | Priority | Target | Concrete next acceptance condition |
|---|---|---|---|
| AP-039 | P1 | 2.1 | Export a bounded review of plan revision, media selections and recovery commands without reading payloads |
| AP-040 | P1 | 2.1 | Improve recovery search/filter review while preserving explicit whole-package extraction and missing-dependency diagnostics |
| AP-033 | P1 | 2.1 onward | Introduce checked type contracts at one critical module boundary at a time, with no fictional strict-typing claim |
| AP-028 | P2 | 2.2 | Calibrate future estimates from measured build ratios; report sample basis, codec and uncertainty, with conservative fallback |
| AP-041 | P2 | 2.2 | Report content duplicates without altering membership, deleting data or creating cross-package restore dependencies |
| AP-042 | P1 | 2.3 | Record offline/remount verification as a separate event bound to replica and media identity |
| AP-043 | P2 | 2.3 | Read-only drive/media health adapters report unsupported tools and preserve their raw evidence |
| AP-044 | P2 | 2.4 | Qualify one explicit snapshot adapter with creation/cleanup ownership and source-consistency semantics |
| AP-045 | P2 | 2.5 | Define and independently restore one extended metadata profile, including explicit loss/error reporting |
| AP-046 | P2 | 2.6 | Optional parity sidecars have measured capacity cost, independent repair instructions and corrupt-fixture recovery tests |
| AP-030 | P2 | Each extension | Snapshot/metadata/parity format and failure contracts reviewed before implementation |
| AP-047 | P2 | Separate design | Raw tape, spanning and robotics get hardware state models and interruption/restore evidence before support claims |
| AP-048 | P2 | Separate design | Encryption gets an external format, key custody and tested independent recovery before release |
| AP-049 | P1 | Ongoing | Measure million-entry and target-storage workloads with explicit RSS, cache, query and phase reports |

## Definition of done

A correctness change needs a small synthetic reproducer that fails for the
original reason, the shared-operation fix, a meaningful regression and a stated
boundary. A qualification claim needs actual environment versions, commands,
outcomes and retained evidence. Do not weaken a guard, erase a meaningful skip
or substitute a simulated device merely to make a status green.

Issue IDs remain stable when tickets move between releases. Small compatible
features may ship earlier once their own gate is met; unrelated open work need
not hold them together. Hardware-dependent dates are not promised without access.
