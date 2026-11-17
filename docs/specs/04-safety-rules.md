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
processes must be reaped on interrupted operations.

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
for completed work or a precise percentage for unknown totals. Show verification
evidence and capacity basis, not a generic green “safe” label.

**HTTP-01.** Bind only to loopback; validate the random session token, Host,
Origin and cross-site request metadata. Serve explicit assets; set CSP, no-store,
nosniff and no-referrer. The workflow needs no external network. A tab disconnect
does not cancel the underlying job. This is not a boundary against a hostile
same-user local process that can read the served HTML/token.

**BOUNDARY-01.** No automatic formatting, erasing, source deletion, cross-package
deduplication dependence, encryption/key custody, raw tape, robotics or mandatory
cloud account. Add such capabilities only through separate explicit contracts.

