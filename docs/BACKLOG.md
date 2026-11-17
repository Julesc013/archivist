# Acceptance backlog

Status means implementation/evidence in this snapshot, not a public issue created.
DONE entries still require their declared platform/release gates. Priorities:
P0 data correctness; P1 qualification/operator correctness; P2 later capability.

| ID | Priority | Status | Work and acceptance condition |
|---|---|---|---|
| AP-001 | P0 | DONE | Freeze V20 input and checksum provenance; retain original unchanged |
| AP-002 | P0 | IN REVIEW | Normative contracts match code, tests and documented limits |
| AP-003 | P0 | DONE | Corrupt helper/README/catalogue seal refuses verify/copy/resume without resealing |
| AP-004 | P0 | DONE | Publication-before-catalogue fault reconciles exactly one replica on retry |
| AP-005 | P0 | DONE | Set/selection scope and receipt IDs/counts reconcile in execution and preflight |
| AP-006 | P0 | DONE | Fully resealed trailing TAR/metadata contradictions rejected at intended checks |
| AP-007 | P0 | DONE | Measured allocation and copy agree, including >4 MiB kit and all file-size limits |
| AP-008 | P0 | DONE | Public allocator consumes validated actual build sizes; corrupt available kit refuses fallback |
| AP-009 | P0 | DONE | A-only build tolerates offline B while retaining global source/output separation |
| AP-010 | P1 | DONE | Root direct-file grouping respects whole-group ceiling and hard maximum |
| AP-011 | P0 | PARTIAL | Declare dependencies; allocation/copy/search expose missing/unknown metadata; automatic per-medium replication remains open |
| AP-012 | P1 | DONE | Off-page package settings retained; clear-plan/filtered-move/list paging regressions |
| AP-013 | P1 | DONE | Visible revision lineage plus immutable diff/revert through shared operations |
| AP-014 | P1 | PARTIAL | Actionable tool diagnostics implemented; live Everything/native checks open |
| AP-015 | P1 | PARTIAL | Frozen terminal progress/reconnect/throughput implemented; overall+package progress open |
| AP-016 | P0 | DONE | Flat source packaging and portable bootstrap use a unique namespace |
| AP-017 | P0 | LOCAL PASS | Clean-room restore and independent TAR oracle; native combinations remain gated |
| AP-018 | P0 | LOCAL PASS | ZIP/TAR.GZ/wheel/sdist isolated checks and complete seals; native launch gates open |
| AP-019 | P1 | OPEN | Real-browser navigation, rendering, keyboard/focus and CSP enforcement |
| AP-020 | P1 | OPEN | Native Windows + live Everything 1.5/es.exe, long paths/reparse points |
| AP-021 | P1 | OPEN | Native macOS/APFS/.command qualification |
| AP-022 | P0 | OPEN | Physical LTFS finalization, unload/reload and independent readback |
| AP-023 | P1 | PARTIAL | Bounded path caches and measured broad/deep/file-heavy cases; million-entry and target-hardware qualification remain open |
| AP-024 | P1 | PARTIAL | Retained staging accurately budgeted; rolling staging scheduler intentionally absent |
| AP-025 | P1 | PARTIAL | Core state bugs fixed; user task observation and end-to-end browser usability open |
| AP-026 | P1 | DONE | Escaped offline ARCHIVE.html sealed and regenerated for replica selection |
| AP-027 | P0 | IN REVIEW | Release artifacts, CI definitions, honest matrix and final identity/signing workflow |
| AP-028 | P2 | OPEN | Empirical compression calibration with measured/estimated separation |
| AP-029 | P2 | PARTIAL | Replica listing/reconciliation implemented; health/offline-verification lifecycle open |
| AP-030 | P2 | OPEN | Snapshot, metadata and parity extensions require independent specs and tests |
| AP-031 | P0 | LOCAL PASS | Transactional kit publication, strict journal replay and injected process termination; physical power-loss qualification remains open |
| AP-032 | P0 | DONE | Release checker rejects empty/incomplete/duplicate seals before running any launcher |
| AP-033 | P1 | OPEN | Incremental type contracts and strict checking at critical module boundaries |

## Definition of done

Each correctness ticket needs a minimal synthetic reproducer, a regression that
fails for the original reason, the shared-operation fix, and an explicit limit.
Each qualification ticket needs actual environment/version/hardware records,
commands, outcomes and retained machine-readable evidence. A test stub, mocked
device or copied CI YAML does not satisfy native or physical qualification.

No calendar estimate is assigned to hardware-dependent work without access.

