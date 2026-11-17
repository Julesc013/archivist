# 04 — Execution and safety

**EXEC-01.** Build, copy and restore require current preflight. Its approval is
bound to selected identities, paths, plan and policy. Recheck mutable capacity
and device conditions at execution; free-space movement is not approval identity.
CLI `--yes` authorizes this reviewed operation, not arbitrary erasure or guard bypass.

**EXEC-02.** Source and output roles MUST be disjoint. A partial build checks
availability of its required source observations; unrelated offline sources MUST
not block it. The global non-overlap invariant still applies to unselected source
paths. A directory's absence does not make its path a valid output location.

**EXEC-03.** New package/replica/restore publication uses the platform's atomic
no-replace primitive or fails closed. An exists() check followed by ordinary
overwriting rename is insufficient. Existing matching output may be verified and
reused; mismatching output MUST not be overwritten.

**EXEC-04.** Retain owned partials on failure/cancellation. Do not delete source
files. Cancellation is cooperative at streaming and validation boundaries;
blocking kernel I/O has no claimed hard latency limit. Decoder/encoder child
processes must be reaped on interrupted operations. A blocked zstd encoder pipe
must still respond to the cancellation signal by terminating only its owned
child. Cancellation must reach existing-object, receipt and manifest hashing.

**EXEC-05.** Successful copy means immediate logical readback, not cartridge
unload/reload, independent-drive readability or a power-loss durability guarantee.
fsync/flush return values do not establish unsupported hardware properties.

**EXEC-06.** Kit validation precedes copying/resealing. If publication precedes
catalogue insertion, retry reconciles the same verified replica receipt.
Multi-file kit updates require an owned transaction record and exact hash-bound
old/candidate bytes. Recovery MUST reject unknown changes instead of blessing
modified helpers. Preflight remains read-only; journal replay occurs under the
workspace writer lock. The validation record distinguishes injected process
failures from real power-loss experiments.

**UI-01.** Selection is identified by plan/package identity, not the visible page.
Off-page selection MUST not supply default encoding settings. Clearing/changing
the plan clears stale results. Navigable lists must not silently truncate.

**UI-02.** Completion freezes elapsed/idle state. Do not display stale-I/O warnings
for completed work or a precise percentage for unknown totals. Overall package
counts and active-step byte progress are separate. Build completion advances
after content verification and successful kit publication. Copy readback keeps
an unknown verification count unknown until measured. Observer failure is a
warning and must not reverse a completed operation. Show verification evidence
and capacity basis, not a generic green “safe” label.

**HTTP-01.** Bind only to loopback; validate the random session token, Host,
Origin and cross-site request metadata. Serve explicit assets; set CSP, no-store,
nosniff and no-referrer. The workflow needs no external network. A tab disconnect
does not cancel the underlying job. This is not a boundary against a hostile
same-user local process that can read the served HTML/token. No automatic
mutation retry follows an ambiguous connection/session error.

**UI-03.** The ES5 compatibility bootstrap loads the ES2017 application only
when required APIs are available and retains readable failure guidance. Native
dialog support is optional through keyboard/focus fallbacks. Capability checks
do not imply qualification of every historic browser version.

**RUNTIME-01.** The application requires Python 3.8+ and linked SQLite 3.31+.
Required safety settings and database capabilities MUST be checked, with no
silent weaker fallback, before new workspace artifacts are created. Connections
MUST confirm their required settings. Standalone recovery remains independent
of the application database.

**PATH-01.** User links and unsafe ancestor paths remain rejected. Only verified
root-owned macOS `/var`, `/tmp` and `/etc` aliases to the expected `/private`
targets may normalize under the shared path guard. Child links remain forbidden.
Windows scanning MUST obtain fresh identity with explicit filesystem stat where
DirEntry supplies zero device/inode/link-count fields.

**BOUNDARY-01.** No automatic formatting, erasing, source deletion, cross-package
deduplication dependence, encryption/key custody, raw tape, robotics or mandatory
cloud account. Add such capabilities only through separate explicit contracts.

