# V2 contracts

Status: **implemented alpha baseline, 2026-11-17**. These specifications describe
the intended supported behaviour of this candidate. A requirement is not evidence
of passing qualification; use the validation record and issue backlog together.

| Contract | Contents |
|---|---|
| [01 Object model](01-object-model.md) | identities, observations, revisions, artifacts, replicas |
| [02 Preservation](02-preservation.md) | included bytes and metadata; explicit loss/limits |
| [03 Archive and evidence formats](03-bundle-format.md) | seals, standalone recovery, selection, compatibility |
| [04 Safety](04-safety-rules.md) | preflight, publication, cancellation, paths, local HTTP |
| [05 Capacity and planning](05-capacity-and-planning.md) | byte accounting, limits, dependency closure, determinism |
| [06 Public operations](06-operations.md) | shared application/CLI/HTTP interface and evidence states |

MUST denotes an implementation requirement; SHOULD denotes a default with a
documented exception. Alpha contracts may change with explicit migration/release
notes. Stable public contracts require semantic-version compatibility thereafter.
No specification may turn an estimate into measured or verified evidence.

