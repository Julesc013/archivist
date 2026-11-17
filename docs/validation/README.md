# Archivist 2.0.0 qualification

The authoritative evidence for a published version is attached to its
[GitHub release](https://github.com/Julesc013/archivist/releases/tag/v2.0.0):
`release-receipt.json` identifies the exact source commit, workflow and native
results; `qualification-evidence.zip` contains the detailed test reports and
browser screenshots. `SHA256SUMS` covers the distributions and evidence assets.
The receipt is produced only after all required jobs succeed for that commit.

A workflow definition is a test plan. Only its completed results establish
qualification. The [workflow history](https://github.com/Julesc013/archivist/actions)
also retains failed investigations rather than replacing them with later passes.

## Release gate

| Environment | Python versions in the native gate |
|---|---|
| Linux x64, Ubuntu 22.04 | 3.8 |
| Linux x64, Ubuntu 24.04 | 3.9, 3.10, 3.11, 3.12, 3.13, 3.14 |
| Windows x64, Server 2022 | 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14 |
| macOS Intel, 15 | 3.8, 3.12, 3.14 |
| macOS Apple silicon, 26 | 3.12, 3.14 |

These are 19 native Python/OS combinations. Each runs the implementation suite
and the shipped JavaScript handler/capability checks. The Windows 3.12 job also
repeats the identity regression 20 times as a targeted stability check after the
observed timestamp failure. Platform/capability skips remain explicit in each
report; a skipped fixture is never counted as a pass.

Three Playwright engines run on Ubuntu 22.04: Chromium, Firefox and WebKit.
The harness navigates the actual localhost service and exercises scan, plan,
encoding revision, media fit, build, copy, restore, keyboard focus, CSP, narrow
layout, disabled JavaScript and missing capabilities. Chromium additionally
runs without native dialog support. The reports record the actual engine
versions and completed checks, with screenshots and JavaScript errors.

Both portable archives must pass complete-seal and isolated-launch checks. Two
independent portable builds must be byte-identical with the same inputs, epoch
and toolchain. Wheel/sdist checks run on Python 3.8 and 3.12, including installation
from an unrelated directory, all static assets, source-distribution rebuild
contents and standalone restoration after removing source, workspace and the
installed application environment. Ruff checks formatting and code; Acorn checks
ES5 bootstrap and ES2017 application syntax.

A main-branch push intentionally marked `[release]` publishes only after every
required job succeeds. `prepare_release.py` checks the evidence and qualified
artifact hashes, then assembles four distributions and the evidence assets.
Complete matrix coverage and common-commit provenance also depend on the
workflow's required jobs and its same-run artifact download; the helper alone
is not a complete matrix runner. Existing release tags are never replaced.
No PyPI publication is performed. SHA-256 checksums are integrity evidence,
not a cryptographic author signature.

## Pre-release investigation, 2026-11-17

[Initial imported snapshot, run 44057635313](https://github.com/Julesc013/archivist/actions/runs/44057635313)
passed the Linux jobs and exposed macOS system-alias and Windows cached
file-identity failures. The implementation now narrowly normalizes verified
macOS system aliases and reads complete Windows identity through `os.stat`.

[First stable candidate, run 44061552172](https://github.com/Julesc013/archivist/actions/runs/44061552172)
passed all seven Linux runtimes and both distribution builds. Native results
exposed a case-sensitive test-fixture assumption and asymmetric Windows
workspace-path normalization. The case-collision guard now has an unconditional
controlled-export regression plus a capability-specific physical fixture. Both
workspace/source containment operands are resolved before comparison, while the
original input still passes through strict link/reparse checks.

[Corrected candidate, run 44062528783](https://github.com/Julesc013/archivist/actions/runs/44062528783)
passed all three browser engines, the dialog fallback, packaging, all Linux/macOS
jobs and six Windows jobs. Its Windows 3.12 failure led to the independent discovery
of a real mixed-API timestamp comparison: Windows path `stat` and descriptor
`fstat` can report different ctime semantics, documented in
[CPython issue 157671](https://github.com/python/cpython/issues/157671). The scanner
now compares the same descriptor's pre/post-read metadata, retaining ctime as a
change guard; shared identity/size/mtime and POSIX pre-open ctime checks remain.
Deterministic tests cover unchanged differing-semantics values, a real mutation
with restored mtime, and POSIX pre-open ctime drift.

Local final-candidate Linux checks ran 197 tests on CPython 3.8.20 and 3.12.14:
195 passed, two Windows-specific skips, zero failures/errors on each. The local
installed-distribution check also passed on both Python versions. These are
pre-release observations; the release receipt, generated by the final gated run,
is authoritative for the published commit.

The local execution environment could not start sandboxed Chromium because of
socket restrictions. No bypass was used. Native browser evidence instead comes
from the actual GitHub runner. The corrected browser run recorded Chromium
159.0.8154.6, Firefox 159.0 and WebKit 27.2 with Playwright 1.65.2: 18 completed
checks per run, including the extra Chromium fallback run, and no JavaScript
errors. A screenshot review also found and corrected a zero-member completion
counter; the final planning regression checks the actual coverage count.

## Limits of qualification

A named CI operating system does not establish support for every older consumer
OS, filesystem, driver or browser. Windows Server tests do not stand in for live
Everything IPC on Windows 10/11. Linux WebKit is not a claim about every Safari
installation. Syntax checks and capability simulations do not qualify historical
browser versions or assistive technologies. Python 3.8 compatibility does not
restore upstream security maintenance.

The Windows suite includes an actual owned junction fixture: both path guards
must reject the junction root, the scanner must exclude the descendant link,
and removing the junction must leave its external target untouched. The test
reports a capability skip only when the volume reports no reparse support;
unexpected creation failure on a capable filesystem fails the gate.

Live Everything 1.5 IPC, physical LTO/LTFS finalization and unload/reload readback,
drive cleaning/health, library robotics and real multi-terabyte throughput remain
unqualified. Mounted LTFS is experimental. Filesystem readback may hit caches and
is distinct from offline media readability. Snapshot consistency, extended
metadata, raw tape and encryption are outside the 2.0 preservation profile.
Standalone recovery uses standard-library SQLite for a temporary path index,
but never needs the Archivist workspace/catalogue database.

## Historical evidence

[alpha1/](alpha1/README.md) retains the original development snapshot's logs and
checksums unchanged. Its version, test counts, timings and browser limitations
are historical evidence, not qualification for the stable release.
