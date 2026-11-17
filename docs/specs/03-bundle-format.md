# 03 — Archive and evidence formats

## Stable format identifiers

The V2 product version does not rename stored formats: `AP20Archive/1`,
`AP20Package/1`, `AP20Workspace/1`, `AP20Replica/1`, and related format 1 identifiers
remain recognizable. The internal journal identifier
`ArchivePlannerKitTransaction/1` also remains unchanged. `.ap20` is an
evidence-transfer suffix, not an archive
payload format. SQLite application ID `0x41503230`, user_version 1 remain in use.
Compatibility means accepting valid supported data, not continuing to accept
contradictory or malformed data that an earlier validator missed.

## Archive set

**FMT-01.** A set includes ARCHIVE.json, README.txt, RESTORE.py, SHA256SUMS and
referenced package receipts, manifests and payloads. New V2 sets additionally
declare `human_manifest: "ARCHIVE.html"` and seal that file. Legacy sets without
the declaration remain readable. A declared human manifest MUST exist and match
its seal. New sets also declare directory-metadata dependencies and the full
metadata-package inventory, including directory-only sources. Subset copies
preserve absent dependency IDs so missing metadata is distinguishable from
complete recovery. Older sets without these optional fields remain readable;
metadata completeness can be unknown.

**FMT-02.** SHA256SUMS is UTF-8, one lowercase SHA-256 and relative pathname per
line. The kit validator rejects missing, duplicate, unexpected or malformed
entries. The catalogue, README, helper and every referenced receipt MUST match.
Receipts seal manifest and encoded payload bytes; manifest rows seal file contents.
Changing a helper MUST be reported before copying or resuming, not blessed by a
fresh checksum list. The helper is never executed by kit validation.

**FMT-03.** Catalogue package IDs and receipt paths are unique. Every reference
must identify the same package as its receipt. `planned_packages` is a positive
bounded integer and must be at least the number present. COMPLETE_PLAN means
present count equals planned count; PARTIAL_PLAN means it is smaller. Claims
contradicting those counts MUST fail.

**FMT-04.** A package contains ordinary PAX TAR, optionally gzip or zstd encoded.
Its receipt records encoded/manifest/decoded lengths, hashes, logical byte and
member counts, codec and identities. The member manifest is gzip JSONL, with
bounded line/member sizes and explicit kind, path, length, mtime, mode and file
hash. Unsupported codecs/types are rejected, not guessed.

**FMT-05.** Decoded TAR has one supported interpretation: manifest and TAR member
order, names, types, lengths, ordinary modes and timestamps MUST agree. After
the end marker only zero padding is allowed, with a valid block-aligned length.
The validator must inspect parser-buffered bytes as well as the underlying
decoder. Concatenated nonzero TAR data is rejected even when another reader
could optionally continue beyond the first ending.

**FMT-06.** Limits in the standalone reader are defensive boundaries, not size
promises: 16 MiB JSON/individual kit file (SHA256SUMS allows 64 MiB), 128 KiB
manifest line, 20 million members per package, 100,000 package references and
256 TiB recorded byte limits. Builders
MUST fail rather than advertise a set the supplied reader cannot inspect.
Validate all actual generated outputs; these are upper limits, not recommended
package sizes or evidence of qualification at those scales.

## Verification and recovery selection

**REC-01.** `archive_set_scope` describes the stored set. The distinct
`verification_selection_scope`, selected/available/planned counts and selected
IDs describe the current check. Verifying one package from a complete set MUST
not imply that unchecked payloads were verified. `scope` remains conservative
for callers using the older aggregate field.

**REC-02.** RESTORE.py is copied from the authoritative recovery module, imports
no application modules, opens no application database and needs only Python's
standard library on Python 3.8+, plus external zstd for zstd payloads. Standard-
library sqlite3 maintains a temporary path index; the application database and
its SQLite feature floor are not required. Recovery must be exercised
with the original source and working database absent. Keep a separate external
TAR extraction oracle for interoperability. A valid sealed helper in an existing
set MUST be preserved rather than silently replaced with a newer one.

**REC-03.** Recovery creates a new output directory and publishes it without
replacement after validation. On failure after partial creation, preserve the owned partial
directory and report it. The reader does not merge into existing trees.

## Workspace transfer

**EVID-01.** A workspace bundle contains exactly FORMAT.json and workspace.sqlite,
with bounded lengths and SHA-256 validation. Import checks SQLite integrity,
references and allowed schema, requires a new destination and disables imported
write permissions/bindings. It is not source payload or a complete backup.

**EVID-02.** V12/V13 migration reads sealed data only; it must not import old
executable code. Unsupported historical plans remain evidence/reference records.
The old workspace remains unchanged. Cross-version writer coexistence is not a
supported sharing model; use an exported/imported copy for the V2 transition.

