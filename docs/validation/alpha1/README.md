# V2 alpha qualification record

Recorded **2026-11-17**, for product **2.0.0-alpha.1**. This is a local Linux
software qualification record. It does not certify native Windows/macOS,
physical media, browser usability or production archival readiness.

## Executed checks

| Check | Observed result | Retained evidence |
|---|---|---|
| Python 3.12.14 aggregate | 156 run; 155 passed; 1 skipped; 0 failures/errors | [unit-tests-python312.json](unit-tests-python312.json) |
| Python 3.13.5 aggregate | 156 run; 155 passed; 1 skipped; 0 failures/errors | [unit-tests-python313.json](unit-tests-python313.json) |
| JavaScript state handlers | 13 checks passed in a minimal DOM using the shipped app.js | [gui-v2.json](gui-v2.json), [scope and limits](gui-v2.md) |
| Ruff 0.17.5 | Lint and format checks passed for all 39 Python files | [software-snapshot.json](software-snapshot.json) |
| Syntax | Python compileall and Node syntax checks passed | [software-snapshot.json](software-snapshot.json) |
| Original V20 baseline | 86 run; 85 passed; 1 skipped | [v20-transition-baseline.json](v20-transition-baseline.json) |
| Scaling experiment | Five bounded synthetic cases; single-run before/after measurements | [scaling-v2.md](scaling-v2.md), [current measurements](scaling-v2.json) |

Both aggregate runs skipped only
`test_runtime.FailureBoundaryTests.test_windows_double_click_bootstrap`, because
execution requires native Windows. Optional zstd tests ran: the executable was
available. The two aggregate suites ran concurrently with separate temporary
workspaces, so their elapsed times are not performance benchmarks.

The suite has 70 more test cases than the reproduced V20 baseline. Counts alone
do not measure assurance. The added cases exercise reproduced failure modes:
changed recovery helpers, catalogue/scope inconsistencies, contradictory sealed
TAR data, interrupted publication, copy resumption at capacity, metadata
dependency visibility, path-cache eviction and GUI state handling.

## What recovery and interruption checks establish

- Plain TAR, gzip and zstd fixtures are verified and restored without their
  original source or workspace. An independent system-TAR extraction path checks
  interoperability; the standalone reader is not its own only oracle.
- Journal tests include handled exceptions and child-process termination at
  publication boundaries, followed by replay or refusal of conflicting bytes.
  They do not simulate a real filesystem/device losing power.
- Copy tests check immediate readback, publication/catalogue reconciliation and
  verified-object reuse. They do not qualify a cartridge after unload/reload.
- Cache tests exercise finite budgets, oversized-entry refusal, reconstruction,
  identity/count preservation and ancestry-cycle rejection. Limits apply to
  retained scalar cache entries; allocator/container overhead and whole-process
  memory have separate costs.

## Distribution evidence

`scripts/build_release.py` produces portable ZIP/TAR.GZ files and a source-file
seal. `scripts/check_release.py` validates complete seal coverage before running
extracted launchers from an unrelated working directory. Empty, incomplete and
duplicate seals have regression tests.

`scripts/check_python_distribution.py` builds or accepts wheel/sdist inputs,
installs the wheel into an isolated disposable environment without dependency
downloads, exercises its actual entry point and assets, and performs a standalone
restore after deleting the source, workspace and installed environment. It also
checks the sdist launcher and compares application file hashes in a wheel rebuilt
from the sdist.

The exact final distribution hashes and checker outcomes belong to the separately
supplied release review and qualification records. They are kept outside the
artifacts they hash to avoid a circular self-hash. A prepared CI workflow is not
evidence that its remote jobs ran.

## Environment

Linux 6.18.57 x86-64 with glibc 2.41; local Python 3.12.14 and 3.13.5; SQLite
3.53.1 for the primary runtime; Node 24.22.1; zstd 1.5.7; GNU tar 1.35.
Build tools: setuptools 84.2.1 and wheel 0.48.0. The source snapshot records file
hashes for the tested implementation and harnesses. Benchmark records retain
their own pre-format source hashes and timing conditions; final formatting must
not be represented as an identical benchmark source snapshot.

## Open qualification gates

| Area | Status and required evidence |
|---|---|
| Real browser | Unqualified. Chromium failed to start in this environment; handler tests do not test CSS, keyboard focus, screen readers or browser CSP enforcement. |
| Native Windows | Unqualified. Requires actual launchers, Everything 1.5 IPC/es.exe, names, long paths and reparse-point behaviour. |
| Native macOS | Unqualified. Requires .command launchers, APFS/case/normalization and metadata checks. |
| Python 3.14 | CI definition prepared; no local execution claim. |
| Physical Linux LTFS | Experimental. Requires identified drive/media/driver, finalization, unload/reload and recorded readback. |
| Large-scale performance | No million-entry, multi-terabyte payload or physical disk/tape throughput claim. |
| Power loss | Injected process termination is covered; real filesystem/device power-loss behaviour is not qualified. |
| Static typing | Basic lint/format gates pass; strict typing is a separate incremental backlog item. |

See [the acceptance backlog](../BACKLOG.md) and [release roadmap](../ROADMAP.md).
