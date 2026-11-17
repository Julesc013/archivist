# Security and integrity boundaries

Archivist is a local archival application. It does not provide multi-user access
control, archive authenticity, encryption, secure deletion or a remote service.
Its baseline guards against accidental overwrite, malformed archives, unsafe
member paths, cross-origin browser requests and ordinary source/target changes
within the documented filesystem assumptions.

## Recovery and source trust

The reader validates seals, reference identities, bounded manifests, checksums,
member paths, decoded lengths, TAR object types and metadata. It creates a new
restore directory and publishes without replacement. It does not call
`tarfile.extractall()` or execute archive metadata. RESTORE.py is a program:
obtain it from a trusted distribution or independently retained archive digest.
A replacement of the whole set and its hashes is outside checksum authenticity.

User-created links, reparse points and unsafe ancestor paths remain rejected.
On macOS only the standard `/var`, `/tmp` and `/etc` aliases may be normalized,
after checking their exact target, ownership and directory properties. This
exception does not authorize links inside a source, archive or restore tree.
Windows scanning obtains fresh filesystem identity rather than relying on
DirEntry's cached zero identity fields. Neither change promises protection from
all hostile same-user ancestor replacement races.

Runtime and linked SQLite requirements are checked before workspace creation.
The application confirms required connection settings rather than silently
falling back to a weaker database configuration. Supporting an old Python
version does not extend that interpreter's upstream security support. Prefer a
maintained interpreter and platform; see the [compatibility guide](docs/guides/compatibility.md).

## Local browser interface

The server binds to loopback and uses an ephemeral token, Host/Origin and
cross-site request checks, an explicit asset map, CSP, no-store, nosniff and
no-referrer. There is no network dependency in the operator workflow. Another
process able to read the same user's HTML or session token is outside this
boundary. Browser capability negotiation displays a readable diagnostic instead
of silently weakening request checks. It does not automatically retry mutations
after an ambiguous connection failure.

## Publication and interruption

No-replace publication uses the required native primitive or fails closed.
An ordinary overwrite-capable rename is not an accepted fallback. Concurrent
hostile ancestor replacement and filesystem/drive firmware that misreports
durability are outside the guarantee.

Archive metadata consists of several flat files, so concurrent readers can
briefly refuse a mixed generation. An owned hash-bound journal records exact
prior/candidate bytes. Preflight only inspects it; the next approved build
recovers it under the writer lock. Unknown bytes or damaged journals are refused.
Do not alter seals merely to make validation pass. Injected process termination
tests do not qualify physical power-loss behavior.

Cancellation reaches streaming and hash boundaries. zstd cancellation terminates
and reaps the owned child even when the encoder pipe is blocked; uninterruptible
kernel or device I/O still has no hard response-time guarantee. Progress observer
failures become warnings and do not reverse a completed data operation. Owned
partials may be retained for a checked retry, with unverified orphan bytes still
charged against capacity. Immediate readback is separate from offline cartridge
readability or independent-drive validation.

## Reporting

Use https://github.com/Julesc013/archivist for project reports. For a suspected
security issue, use GitHub private vulnerability reporting if the repository has
it enabled. If it is unavailable, request a private contact in an issue without
publishing sensitive exploit details. Include version, platform and a minimal
synthetic reproducer through the agreed channel. Never attach private source
data, credentials or real archive payloads. Ordinary non-sensitive correctness
bugs can be filed publicly with their expected and observed behavior.
