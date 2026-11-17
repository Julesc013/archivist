# Security and integrity boundaries

This local tool does not provide multi-user access control, archive authenticity,
encryption, secure deletion or remote service hardening. Its baseline protects
against accidental overwrite, untrusted member paths, malformed formats,
cross-origin browser requests and ordinary source/target changes within the
documented filesystem assumptions.

The recovery reader validates seals, references, bounded manifests, checksums,
member paths, decoded lengths, TAR object types and metadata. It creates a new
output directory and uses no-replace publication. It does not run archive
metadata as code or call tarfile.extractall(). A malicious replacement of the
entire catalogue and its seals is outside checksum authenticity guarantees.
Keep a trusted copy of catalogue/distribution digests separately.

The loopback server uses an ephemeral random token, Host and Origin checks,
Sec-Fetch-Site checks, a restricted asset map, CSP, no-store, nosniff and
no-referrer. Local processes with access to this same user account or the served
HTML can obtain the token. This is not an isolation boundary against a hostile
process running as the same user.

Hostile ancestor-directory replacement and filesystem/drive firmware lying about
durability are outside the no-replace guarantee. Cancellation is cooperative;
kernel/device I/O may block. Multi-file metadata publication is not one atomic
filesystem operation: concurrent readers may temporarily refuse the set. An
owned, hash-bound journal lets the next approved build recover an interrupted
update; preflight itself does not modify it. Unknown bytes are refused, and a
missing/damaged journal is not silently reconstructed. Do not edit checksums
merely to make verification pass. Process-termination tests do not qualify
physical power-loss behaviour.

No public vulnerability-report address exists until the repository identity is
chosen. For now, preserve a minimal synthetic reproducer and report it through
the project discussion. Never include personal data, credentials or real payloads.
