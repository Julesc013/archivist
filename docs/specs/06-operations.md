# 06 — Shared operations

CLI and HTTP call `Application.call(action, arguments, progress)`. Write actions
hold the workspace writer lock and record outcomes. UI/CLI MUST not implement
different capacity, packing or recovery semantics.

| Operation | Arguments | Result / semantics |
|---|---|---|
| package | plan_id, package_id | Full row independent of visible page |
| packages | plan_id | Paged packages and filtered total; optional query, kind, snapshot_id, exclude_package_id |
| plan_diff | plan_id, target_plan_id | Bounded changed-node membership/encoding rows; no rescan |
| revert | plan_id, target_plan_id | New immutable child with target decisions and provenance |
| allocate | plan_id, media, optional bundle | Placements, unallocated IDs, footprints, measurement basis and per-medium metadata dependencies |
| replicas | optional build_id/destination_id | Paged records; not proof of media currently online |
| recovery_find | bundle, query | Bounded manifest matches and whole-package selection; payload_verified=false |
| preflight_build/copy/restore | Operation paths/IDs | Read-only review and bound approval digest |
| build/copy/restore | Same plus approval | Validated execution or structured failure and retained partial |

Default page 100, maximum 1,000. Recovery search supports Unicode-casefold substring
or exact-case subtree matching; `Photos` does not match `Photos-old` in subtree
mode. It streams manifests to calculate total, retaining only a result page.
`matched_package_ids` identify hits; `package_ids` includes available required
directory metadata. Missing/unknown metadata must remain visible. Search is not
payload verification or individual-member extraction.

CLI aliases are `diff`, `revert`, `find`, `allocate`, and `list replicas`.
`--json` writes escaped JSON to stdout; structured errors use stderr. Success
exits 0, operational errors exit 2, keyboard interruption exits 130. Help/version
must not create a workspace.

Alpha responses may acquire additive fields. Consumers should not infer stable
schemas from SQLite column order. Future required format features need explicit
version/feature negotiation; do not silently change an existing field's meaning.
