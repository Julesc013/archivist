# Archivist release roadmap

Canonical plan for [Julesc013/archivist](https://github.com/Julesc013/archivist).
The [TODO](TODO.md) holds stable acceptance IDs; the
[validation record](docs/validation/README.md) holds observed results.
Version targets express sequence and scope, not unverified calendar commitments.

## Release approach

Ship small, reviewable minor releases when a bounded capability, documentation
and its failure/recovery tests are complete. Do not accumulate every planned
storage feature into one distant release. Compatible corrections can ship as
patches independently of feature work. Release notes must distinguish changed
behaviour, compatibility implications and the exact tested environments.

Every release retains ordinary archive recovery, explicit byte accounting,
no-replace publication, source/output separation and visible unsupported states.
A dependency or framework is justified by a concrete need, not by release size.

## 2.0.0 — the stable foundation

- Directory-first planning, immutable revisions and bounded catalogue/cache work.
- Media placement includes required directory metadata and charges every physical
  copy; explicit copy/recovery selections remain operator controlled.
- Plain/gzip/zstd PAX TAR, strict kit and content validation, retained staging,
  verified copies, replayable kit journals and idempotent replica reconciliation.
- Standalone recovery and human-readable offline catalogues without an
  application workspace.
- Shared CLI/GUI operations, two-level progress, actionable diagnostics and
  capability-aware browser fallbacks.
- Python 3.8+ application compatibility with independently checked SQLite 3.31+
  requirements; no weaker path/publication/database mode to support an older host.
- Complete source, specifications, build tooling, changelog and retained release
  evidence under the chosen Archivist identity.

Stable publication requires the declared software and packaging gates to pass
for the actual release commit. It does not claim every historical browser,
filesystem, Python build or cartridge works. Mounted LTFS stays experimental
until its physical qualification succeeds. Live Everything has its own
integration gate beyond ordinary Windows filesystem tests.

## 2.0.x — focused maintenance

Prioritize reproducible data-correctness issues, platform/name/encoding fixes,
resumability, diagnostics and documentation corrections. Do not combine an urgent
fix with an unrelated architectural rewrite. Re-run affected gates, retain
compatibility fixtures and state whether existing artifacts need any action.

Schema changes follow explicit compatibility/migration rules; there is no
absolute ban on SQL changes in a patch. A patch must preserve the promised public
reader and operation behaviour. Old valid sealed helpers are not silently
rewritten during an unrelated application upgrade.

## Small compatible feature releases

| Version | Bounded theme | Exit criteria |
|---|---|---|
| 2.1.0 | Review and recovery ergonomics | Exportable plan/media review, clearer selected-package restore review, keyboard task observations and one increment of typed boundary checking |
| 2.2.0 | Measured estimates and duplicate reporting | Compression history labelled by codec/data basis and uncertainty; conservative fallback; duplicate report leaves all recovery selections independent |
| 2.3.0 | Replica lifecycle and read-only health | Distinct offline/remount verification events, media identity/provenance, optional health tools with unsupported/error states and no unsolicited device writes |
| 2.4.0 | First qualified snapshot adapter | Opt-in ownership/cleanup rules, actual native tests, correct point-in-time claim for one source/platform and visible limitations for multiple sources |
| 2.5.0 | First extended preservation profile | Explicit ACL/xattr or ADS scope, format negotiation, loss reporting and independent restore/interoperability fixtures on its supported OS |
| 2.6.0 | Optional parity sidecars | Sidecar creation and measured budget, reproducible corruption/repair exercises, documented standalone recovery and no dependence on parity for ordinary decoding |

These are separate releases, not a promise to implement every OS adapter at once.
A useful subset can ship when its contract is complete; unfinished adapters stay
unsupported or experimental. Additional small 2.x releases may address query
scaling, operator workflows and compatibility without waiting for the next row.

### Rules for measured estimates

Store actual logical/encoded lengths and codec parameters as observations.
A historical ratio is not a capacity guarantee for different data. Keep measured,
calibrated and heuristic bases distinguishable, retain conservative copy
preflight, and never add hardware-compression credit to already compressed bytes.

### Rules for preservation extensions

A snapshot adapter must state what is frozen and who owns its cleanup. Separate
snapshots of separate sources are not necessarily simultaneous. Extended
metadata must be opt-in and negotiated; do not silently change `logical-files-v1`.
Parity consumes capacity and cannot replace independent copies or verification.

## Raw tape, libraries and encryption

Direct sequential tape/filemarks/spanning and library robotics require separate
media-state and interruption designs, test hardware and independent restore
exercises. Encryption requires a defined external format, explicit key custody
and a recovery drill without the working application or a hidden remote service.
These projects can be explored independently of the smaller 2.x releases.

Use **3.0.0** when an introduced change breaks a promised public contract.
A feature's ambition alone does not require a new major version; an incompatible
format/API change does. Support old recovery formats explicitly, or provide a
reviewed migration path, before removing a reader or changing required semantics.

## Gate applied to every claimed capability

| Gate | Required evidence |
|---|---|
| Data correctness | Adversarial sealed fixtures, meaningful independent outcomes, source-change checks and no-replace results |
| Recovery | Original source/workspace absent; all claimed codecs; restored hashes/paths/metadata; external TAR oracle |
| Transactions | Interruption/retry/reconciliation, stale approvals, changed helpers and conflicting outputs |
| Packaging | Complete portable seals; isolated checkout/wheel/sdist operation; assets/helper identity; repeatable portable builds |
| Runtime | Actual interpreter plus linked SQLite version; exercised required capabilities and explicit unsupported cases |
| Browser | Actual engine versions, navigation/rendering, keyboard/focus/dialog fallback, reconnect and security-header enforcement |
| Native platform | Launchers and relevant filesystem/name/reparse/alias/metadata cases on that platform |
| Hardware adapter | Driver/device/media identity, interrupted operations, finalization/reload and recorded independent readback |

A matrix definition is a plan. Its observed results are recorded separately.
Optional hardware support may remain experimental while a qualified core release
ships, provided the support statement says so directly.

## Version and provenance rules

`source/__init__.py` owns the product version; `2.0.0` also has Python package
version `2.0.0`. The earlier development string `2.0.0-alpha.1` mapped to
`2.0.0a1`. Historical `20.0.0-eval.1` is an input lineage, not a numerically newer
release in this repository's distribution line.

Archive format, workspace schema, public operation contracts and product version
are distinct. A project rename does not rewrite `AP20*/1` identifiers, `.ap20`
bundles, old receipts, checksums or the supplied licence. Release digests are
integrity evidence; a maintainer signature requires an actual key/identity
process and is never implied by SHA256SUMS.

Version semantics reference: [Semantic Versioning 2.0.0](https://semver.org/).
