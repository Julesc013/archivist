# Release roadmap

Decisions anchored to 2026-11-17. Dates for unperformed work are not promised.
The working name and local distribution are provisional; no repository or
registry has been published or reserved.

## 2.0.0-alpha.1 — this candidate

Integrate the reproduced V20 correctness fixes, explicit source/ layout, shared
operations, operator-state corrections, standalone recovery contracts, human
catalogue, bounded path caches, journalled kit publication, tests and reproducible
portable packaging. Preserve provenance back
to the verified V20 input. An alpha can be repository-ready as a development
snapshot without being qualified for production archival reliance.

## 2.0.0-alpha.2 / beta — close the remaining software gaps

- Extend the injected process-termination evidence to supported native filesystem
  implementations; keep physical power-loss behaviour a separate hardware gate.
- Define per-medium metadata dependency closure. Allocation may replicate small
  directory-metadata packages without changing exact-once logical membership.
- Build an explicit selected-package/overall job progress model and separate
  staging/destination capacity displays; keep unknown ETA honest.
- Qualify the real GUI in a browser: keyboard-only use, focus, narrow screens,
  light/dark, stale async responses, disconnected/reconnected jobs and CSP.
- Establish supported interpreter/native OS matrix; add strict type checking
  incrementally at core boundaries without false claims that the legacy core
  already satisfies a strict typing policy.
- Retain explicit path-cache limits; qualify million-entry workloads and work-queue
  budgets on representative storage before setting performance promises.
- Complete machine-readable external operation/schema documentation and compatibility
  fixtures before declaring the API stable.

## 2.0.0-rc.1 — release gates

| Gate | Required evidence |
|---|---|
| Correctness | Regression suite including adversarial sealed fixtures, source-change checks and no-replace outcomes |
| Recovery | Source/DB absent; none/gzip/zstd; independent system-TAR extraction and checksum comparisons |
| Transactions | Reproducible interruption/retry/reconciliation, stale approvals, changed helpers and conflicting outputs |
| Packaging | Portable ZIP/TAR.GZ, isolated wheel and sdist launch, file seals, duplicate/unsealed input rejection, reproducibility |
| Browser | Actual navigation and rendering in supported browsers; accessibility/focus/security enforcement checks |
| Windows | Native launchers; Everything 1.5/es.exe; long paths, reparse points and names |
| macOS | Native launchers; APFS name/case/normalization and supported metadata behaviour |
| LTFS claim | Real mounted Linux LTFS, driver/media identification, finalization, unload/reload, readback and recorded limitations |

A platform/adapter gate may remain explicitly experimental in a stable core
release if the support statement excludes production support for it. It may not
be silently marked passed because another platform or ordinary disk passed.
Require the physical gate if the release promises production LTFS support.

## 2.0.0 — stable public baseline

Freeze the documented supported contracts, qualify the declared platforms,
publish complete source and readable release evidence, choose the final name,
and prepare the user's chosen repository. Establish reproducible builds and a
release review checklist. A checksum alone is not a maintainer signature;
signing requires an actual chosen identity/key process, not an invented signature.

## 2.0.x — compatible corrections

Bug fixes, supported-platform path/encoding repairs, diagnostics and documentation.
Schema changes are governed by compatibility and migrations, not an absolute
“no SQL changes” rule. A patch must not break the promised public reader/API.
Retain test fixtures for older supported archive sets and workspace transfers.

## 2.1 — measured operation and replicas

Use measured compression history with explicit evidence/uncertainty; improve
multi-replica lifecycle and offline verification events; offer non-destructive
duplicate reports; add optional read-only drive health where genuinely supported.
No content deduplication dependency between self-contained recovery selections.

## 2.2 — separately qualified preservation extensions

Opt-in point-in-time source snapshots, ACL/xattr/ADS profiles and optional PAR2
sidecars, each with capability checks, resource accounting, format documentation,
recovery tests and failure behaviour. Do not imply independent snapshots across
multiple sources are simultaneous. Parity is not a replacement for independent
copies or routine verification.

## Later compatible additions or 3.0

Raw sequential tape/filemarks/spanning, libraries/robotics and optional encryption
are substantial separate projects. They require hardware, media state models,
key/restore procedures and interruption tests. A major version is needed when
public compatibility breaks, not simply because a feature is ambitious.

## Version semantics

Product `2.0.0-alpha.1` maps to Python-package `2.0.0a1`. The move from historical
`20.0.0-eval.1` is a new declared release line, not numerical upgrade ordering
within the old distribution. Explain the transition; do not automatically install
it over an old named package or mutate old evidence. Archive format version,
workspace schema version and public API version are separate contracts.

Reference: https://semver.org/ .

