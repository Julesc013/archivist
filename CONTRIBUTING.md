# Development

Use Python3.12+ and an isolated checkout. Never use personal archive payloads as
test fixtures. No repository service or credentials are needed for local work.

## Ownership boundaries

`application.py` exposes shared operations. CLI and HTTP parse/serialize inputs;
they do not implement alternative packing, capacity or verification algorithms.
`planning.py`, `capacity.py`, `artifacts.py`, `destinations.py`, `inventory.py`,
`evidence.py` and `store.py` own their respective domain operations.
`catalogue.py` owns bounded read queries. `archive_html.py` renders a catalogue.
`recovery.py` must remain independently executable with only standard-library
imports and an optional zstd subprocess.

Do not create empty directory frameworks or split modules to meet an arbitrary
file/line target. Introduce a new module for a coherent responsibility. Prefer
typed boundaries and explicit byte/evidence fields over dictionaries that mix
estimates with measured or verified claims.

## Checks

```sh
python3 scripts/run_tests.py --json-out docs/validation/unit-tests-local.json
node tests/gui_state.test.cjs
python3 -m compileall -q source scripts tests
```

The Python suite uses unittest and the standard library. Tests with OS/tool
requirements report explicit skips. Preserve tests that verify independent
outcomes, no-replace behaviour, tamper rejection, crash recovery and external
TAR readability. A negative fixture must be valid before the one intended
mutation; an earlier seal failure is not evidence of traversal protection.

Optional tools: install setuptools/wheel to build wheels/sdists, Ruff for lint,
and Playwright plus its browser for GUI tests. These are development dependencies.
The pinned development requirements and CI workflow are release gates when run;
their presence alone is not validation. Browser/CSP enforcement, accessibility
and native dialogs must be tested in an actual browser before claiming them.

## Builds

```sh
python3 scripts/build_release.py --output dist
python3 scripts/check_release.py dist/archivist-2.0.0-alpha.1.zip dist/archivist-2.0.0-alpha.1.tar.gz
python3 -c 'import setuptools.build_meta as b; b.build_wheel("dist"); b.build_sdist("dist")'
python3 scripts/check_python_distribution.py --build --output /path/to/new/build-check
```

The portable packager uses an explicit input allowlist and fixed file ordering,
timestamps, owner IDs and permissions. Repeated builds are compared with the
same inputs and toolchain. A different Python/zlib toolchain can encode the
same source differently; no cross-toolchain identity is asserted. Existing
output names are refused. The internal SHA256SUMS covers all selected source
files; keep an externally recorded distribution digest for authenticity context.

## Versioning and release

`source/__init__.py` owns the product version. Python package metadata translates
`2.0.0-alpha.1` to PEP440 `2.0.0a1`. Archive schemas, workspace schema and public
operation contracts have their own compatibility rules. Renaming the project
is not permission to rewrite stored format IDs. See docs/ROADMAP.md.

Changes touching format readers, publication, extraction or capacity need a
review of their documented failure modes. Qualify each native adapter on its
actual platform. Do not remove an honest skip or lower a gate merely to obtain
a green badge.

