# 01 — Object model

## Entities and identity

**MODEL-01.** A collection is the identity of a workspace's evidence, not a
physical source volume. A source records a selected root and explicit binding.
An observation records acquisition time/backend/provenance and indexed objects.
The historical SQLite table name `snapshots` MUST NOT imply snapshot consistency.

**MODEL-02.** A plan revision references an ordered selection of observations,
restore namespaces, policy and exact-once package memberships. A package is a
logical group. An encoded artifact is its immutable payload plus a receipt and
manifest. A destination is a separately registered storage root. A replica is
one published copy of a selected archive set on that destination.

**MODEL-03.** Encoded-byte identity is SHA-256 of the encoded artifact. Path,
codec label or package ID alone is not that identity. Copying an already built
artifact MUST preserve its bytes and checksum. The 2.0.0 schema stores
artifact evidence in build/package receipts rather than a separate artifact table.

## Observations and plans

**PLAN-01.** Every included file/directory node belongs to exactly one package in
a plan. Unsupported/excluded/error observations remain evidence and MUST NOT
silently become included. Empty directories and source-root metadata count.

**PLAN-02.** Approved plan decisions are immutable. Editing codecs, moving or
merging members creates a new plan with `parent_plan`. Revert creates a new child
of the current plan using the target's decisions; it never changes either parent.
Revert requires identical observations and restore namespaces.

**PLAN-03.** Determinism is conditional on identical observations, **ordered**
source inputs and policy. Source order can change package numbering. It is not
claimed that independent live rescans or reordered inputs produce identical IDs.

**PLAN-04.** Encoding edits retain the original grouping reason and record codec
changes in revision provenance. A plan fingerprint detects changes to recorded
decisions/membership before execution; it is not a signature authenticating a
workspace controlled by an attacker.

## Working state versus archival evidence

**MODEL-04.** The SQLite database is working evidence, not a dependency of
standalone recovery. Workspace transfer MUST not convey source-read authority or
destination-write approval. Imported sources require binding; destinations start
disabled. A stored path is not proof that a source or replica is available now.

**MODEL-05.** A committed replica receipt can outlive a failed catalogue insertion.
Retry MUST verify the existing replica and reconcile the same receipt identity
idempotently. A conflicting ID/path/receipt MUST fail instead of creating another
record or silently overwriting one.

**MODEL-06.** Verification states describe observations: planned, built,
content-verified and immediate-copy-readback are distinct from hardware-qualified
offline/reloaded readability. No transition to the latter is implied by software-only verification.

