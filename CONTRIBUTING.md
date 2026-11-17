# Contributing to Archivist

Repository: https://github.com/Julesc013/archivist

Use an isolated checkout and synthetic data. The application supports Python
3.8 and later; a maintained Python release is the default development choice.
Do not use personal archive payloads, real cartridges or credentials as fixtures.
Local development needs no repository service or account.

## Boundaries

`application.py` exposes shared operations. CLI and HTTP parse and serialize
inputs; they do not implement alternative packing, capacity or verification
algorithms. Domain modules own scanning, planning, encoding, copying and evidence.
`recovery.py` remains independently executable with standard-library imports;
zstd is an optional external decoder. See [architecture](docs/architecture/README.md).

Keep code directly in `source/`. Setuptools maps that directory to the unique
`archivist` namespace. Avoid empty framework directories and module splits made
only to meet a line-count target. Prefer typed boundaries and explicit byte and
evidence fields where they reduce ambiguity. Estimates, measurements and verified
observations must remain distinct.

## Local checks

From the repository root:

```sh
python3 scripts/run_tests.py --json-out /path/to/local-test-results.json
node tests/gui_state.test.cjs
python3 -m compileall -q source scripts tests
```

The Python suite uses unittest. OS/tool-specific tests report explicit skips;
a skipped native test is not a passing platform qualification. Preserve tests
of independent outcomes: overwrite refusal, tampering, interrupted publication,
exact-capacity retry, metadata closure and external TAR readability. Negative
fixtures must pass baseline validation before the intended mutation. An earlier
checksum failure does not test a later path-traversal guard.

Development requirements are pinned in `requirements-dev.txt`, with interpreter
markers where tool support differs. Setuptools/wheel build Python distributions;
Ruff checks source; Playwright and its browser binaries exercise the actual UI.
These are development dependencies, not mandatory application dependencies.
Feature probes and JavaScript syntax checks do not replace real browser tests.

## Build and distribution checks

Use a new output directory for each invocation:

```sh
python3 scripts/build_release.py --output /path/to/new/portable-dist
python3 scripts/check_release.py /path/to/new/portable-dist/archivist-2.0.0.zip /path/to/new/portable-dist/archivist-2.0.0.tar.gz
python3 scripts/check_python_distribution.py --build --output /path/to/new/python-distribution-check
```

The portable packager has an explicit file allowlist, ordering, timestamps, owner
IDs and permissions. Repeated identical-input builds are checked with the same
toolchain. Cross-toolchain compressed-byte identity is not promised. Existing
output names are refused. The distribution's internal SHA256SUMS covers selected
source files; keep the separately published archive digest as well.

Python-distribution qualification builds and installs without runtime network
resolution, launches the console command outside the checkout, checks packaged
static assets, runs a small archive workflow and tests independent recovery.
An sdist must retain the portable launcher and rebuild the same package inventory.

## CI and release

`.github/workflows/test.yml` defines native Python/OS tests, actual browser engines
and fallback modes, portable distribution checks and Python distribution checks.
The [validation record](docs/validation/README.md) records the environments and
outcomes that actually ran. Workflow definitions are not evidence of success.

The release job requires its prerequisite jobs to succeed and an explicitly
marked `[release]` push to `main`. It publishes qualified GitHub release assets
and evidence; it does not publish to PyPI. `scripts/prepare_release.py` assembles
release material and does not itself publish. Do not bypass a failing gate or
remove an honest skip solely to obtain a green badge.

`source/__init__.py` owns the product version. Keep the matching bracketed
version heading in CHANGELOG.md. Archive formats, workspace schema and public
operation contracts have independent compatibility rules. Existing AP20 format
identifiers are data, not branding. See [ROADMAP.md](ROADMAP.md).

A contribution is ready when its bounded behavior, failure cases and evidence
are reviewable together. Update [TODO.md](TODO.md) acceptance IDs and affected
contracts; keep observed test counts in validation evidence rather than copying
them into every document. Physical adapters need tests on the named hardware.
