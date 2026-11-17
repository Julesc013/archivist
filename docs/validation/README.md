# Archivist 2.0.0 qualification

Status as of 2026-11-17: **candidate under native qualification; no stable tag yet**.
The release workflow, rather than this status paragraph, determines whether a
particular commit may be published. [Workflow runs](https://github.com/Julesc013/archivist/actions)
retain the exact source SHA, operating-system image, interpreter and test output.

## Observed candidate results

- Linux CPython 3.12.14: 190 tests run, 189 passed, one platform-specific skip;
  zero failures/errors. Earlier full Python 3.8.20 candidate run passed all 186
  applicable tests with one platform-specific skip. The subsequent publication,
  diagnostic and release-gate regressions passed their focused checks.
- Shipped JavaScript: 21 handler checks and four controlled-capability checks
  passed. Acorn 8.19.0 parsed the loader as ES5 and the application as ES2017.
- Python 3.8.20 wheel/sdist qualification passed with setuptools 75.3.4 and
  wheel 0.45.1: isolated installation and CLI, package static assets, source
  distribution rebuild equality, and standalone restoration after removing the
  application environment, source and workspace.
- Ruff 0.17.5 lint and formatting checks passed. Local Python 3.8 syntax
  compilation passed. These local outcomes precede final native CI evidence.

The initial imported snapshot passed the Linux 3.12/3.13/3.14 jobs but failed on
macOS system aliases and Windows cached file identities. Those failures are
retained in [run 44057635313](https://github.com/Julesc013/archivist/actions/runs/44057635313).
The candidate corrects the demonstrated causes; only a successful native rerun
can establish the final support statement.

## Required publication gates

The workflow runs 19 Python/OS combinations, including Python 3.8, Windows,
macOS Intel and Apple silicon, plus current Chromium, Firefox and WebKit on
Linux. Browser checks navigate the actual localhost service and exercise scan,
plan, revision, fit, build, copy, restore, focus behavior, CSP, a narrow viewport,
disabled JavaScript and missing capabilities. Chromium also runs the dialog
fallback. Local browser launch was blocked by the execution environment's socket
permissions; no sandbox bypass was used and that is not a native browser pass.

Both portable archives must pass complete-seal and isolated-launch checks; two
portable builds must be byte-identical with the same inputs, epoch and toolchain.
Wheel/sdist checks run on Python 3.8 and 3.12. `prepare_release.py` checks evidence
and hashes before preparing the four distribution assets. Matrix completeness
and common-commit provenance also depend on the workflow's required jobs and its
same-run artifact download; the helper alone is not a complete matrix runner.

A main-branch commit intentionally marked `[release]` publishes only after every
required job succeeds. The attached `release-receipt.json` identifies the exact
source SHA and workflow. `qualification-evidence.zip` retains actual reports;
`SHA256SUMS` covers distribution and evidence assets. Checksums provide integrity,
not a cryptographic author signature. PyPI publication is not performed.

## Limits of qualification

CI operating systems do not establish support for every older consumer OS,
filesystem, driver or browser. ES5/ES2017 syntax checks and capability simulations
do not qualify historical engine versions or assistive technologies. Python 3.8
compatibility does not restore upstream security maintenance.

Live Everything 1.5 IPC, physical LTO/LTFS finalization and unload/reload readback,
drive cleaning/health, library robotics and real multi-terabyte throughput remain
unqualified. Mounted LTFS is experimental. Filesystem readback may hit caches and
is recorded separately from offline media readability. Snapshot consistency,
extended metadata, raw tape and encryption are outside the 2.0 preservation
profile. Standalone recovery needs Python's standard-library SQLite module for a
temporary path index, but never needs the Archivist workspace/catalogue database.

## Historical evidence

[alpha1/](alpha1/README.md) retains the original development snapshot's logs and
checksums unchanged. Its version, test counts, timings and browser limitations
are historical evidence, not a qualification claim for the stable release.
