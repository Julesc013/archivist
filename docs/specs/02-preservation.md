# 02 — Preservation profile

Profile identifier: **logical-files-v1**.

**PRES-01.** Preserve included ordinary file bytes, source-namespaced relative
paths, empty directories, recorded modification times and ordinary permission
bits where the destination platform supports them. Restore applies modes only
with explicit `--permissions`; platform limitations remain visible.

**PRES-02.** Treat links/reparse points, special files, unreadable entries,
unsupported attributes and nonportable/colliding names according to the scanner's
explicit issue/exclusion ledger. Never silently dereference a link, rename a
collision or replace one file with a normalized equivalent. Restore preflight
rejects unsafe traversal, absolute paths, file-as-parent conflicts and case/
Unicode collisions. Windows additionally rejects invalid and reserved names.

**PRES-03.** This profile does not preserve ACLs, xattrs, NTFS ADS, EFS, link
relationships, sparse allocation, ownership semantics or complete filesystem
images. Such features require separately qualified profiles. A successful scan
does not establish properties its acquisition backend cannot observe.

**PRES-04.** A live scan/build is not a point-in-time snapshot. Build checks the
recorded source identity, size and modification time and hashes bytes actually
archived; recorded scan hashes strengthen change detection when present.
These checks do not establish cross-file application consistency or defeat every
same-size/mtime-restored change when no prior content hash exists.

**PRES-05.** A payload package is independently decodable. In the current format,
directory metadata may reside in separate directory-only packages. A complete
metadata-preserving recovery selection consists of chosen payload packages plus
the relevant source's directory-metadata packages. A complete archive set
contains both. Explicit package selection selects exactly the listed IDs;
manifest search proposes the metadata dependencies as additional selected IDs.

**PRES-06.** Whole-package recovery can extract additional files beyond a search
match. The interface MUST say so. Search verifies catalogue/manifest evidence,
not the encoded payloads, and MUST return `payload_verified: false`.

**PRES-07.** Content hashes verify consistency with supplied evidence, not
authenticity against coordinated replacement of catalogue, helper, receipts and
seals. Independently retain digests or introduce a separately specified signature
scheme when authenticity is required. No encryption is supplied by this profile.

