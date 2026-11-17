# Archivist 2 contracts

These contracts define the **2.0.0 baseline**. A requirement is not evidence of
passing qualification: consult [validation](../validation/README.md) and the
[root acceptance backlog](../../TODO.md) together.

| Contract | Contents |
|---|---|
| [01 Object model](01-object-model.md) | Identities, observations, revisions, artifacts and replicas |
| [02 Preservation](02-preservation.md) | Included bytes and metadata; explicit losses and limits |
| [03 Archive and evidence formats](03-bundle-format.md) | Seals, independent recovery, scope and compatibility |
| [04 Safety](04-safety-rules.md) | Preflight, publication, cancellation, paths and local HTTP |
| [05 Capacity and planning](05-capacity-and-planning.md) | Byte accounting, limits, dependency closure and determinism |
| [06 Public operations](06-operations.md) | Shared application/CLI/HTTP interface and evidence states |

MUST denotes an implementation requirement; SHOULD denotes a default with a
documented exception. Stable public contracts follow semantic-version rules;
format/schema versions remain independent of product branding. Unsupported or
corrupt inputs need not remain accepted merely because an older validator missed
them. No contract may turn an estimate into measured or verified evidence.
