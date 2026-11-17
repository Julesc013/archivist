# Changelog

## 2.0.0-alpha.1 — 2026-11-17

First implemented V2 development snapshot, derived from checksum-verified
20.0.0-eval.1. Product naming remains provisional.

### Correctness and recovery

- Validate recovery-kit seals before verification, copy and resume; do not
  silently re-seal changed helper files.
- Separate set scope from verification selection, reconcile receipt identities
  and expected package counts, and enforce TAR trailer and metadata consistency.
- Reconcile published replica receipts into SQLite after an interrupted commit.
- Share allocation/copy accounting, consume validated measured build sizes,
  count package sidecars and recovery-kit bytes, and check individual object limits.
- Restrict partial-build availability checks to required source observations.
- Keep source-root direct files coherent up to the whole-group ceiling.
- Preserve grouping reasons on codec edits and record encoding changes separately.
- Bound both directory-path caches, retaining SQLite as the authoritative store;
  remove unused migration cache retention and test eviction invariants.
- Journal recovery-kit updates and test real process exits during initial,
  subsequent and post-seal publication; preserve read-only preflight.
- Credit verified completed partial-copy objects when recalculating retry space;
  keep orphaned or conflicting objects charged and visible.

### Operator workflow

- Package detail and filtered lookup no longer depend on the current GUI page.
- Add immutable revert and bounded membership/encoding comparison operations.
- Add sealed-manifest search and explicit whole-package restore selection.
- Surface replica records, actionable diagnostics and paged object lists.
- Freeze completed progress and display throughput and reconnect status.
- Generate and seal a plain offline HTML catalogue with every new archive set.
- State missing/unknown directory metadata explicitly in partial recovery and
  allocation reviews; remove hardcoded LTFS formatting deductions from presets.

### Maintenance and distribution

- Place implementation directly in `source/`; use one Python namespace.
- Adopt a Python3.12+ application baseline and separate V2 default workspace paths.
- Add specifications, support/qualification matrix, regression tests, portable
  reproducible packaging, release checks, CI definitions and an acceptance backlog.
- Preserve schema 1 and AP20 format identifiers rather than performing a cosmetic
  format migration. Reject malformed or internally contradictory evidence.

Qualification results describe this environment only. This is not a stable
v2.0.0 tag, a public package publication, or a physical LTFS qualification.

