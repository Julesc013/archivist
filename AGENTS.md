# Working on Archivist

Read `README.md`, `docs/specs/`, `TODO.md` and `ROADMAP.md` before changing behavior.
Keep code directly in `source/`; the portable launcher and installed package use
the same modules. CLI and HTTP adapters call `Application` operations rather than
implementing separate workflows.

## Compatibility and safety

- The core runtime floor is Python 3.8 with SQLite 3.31.0 and checked capabilities.
  Keep annotations deferred and avoid APIs absent from the floor without guards.
- Browser bootstrap syntax is ES5; the interactive application is ES2017.
  Detect capabilities and explain missing ones. Do not weaken CSP or path checks.
- Keep historical AP20 format IDs and frozen fixture bytes intact. Product naming
  and software versions are separate from on-media format versions.
- Preserve immutable observations and revisions, exact-once logical membership,
  source-change detection, no-replace publication, cancellation and readback.
- Recovery must work without the application workspace or an installed Archivist
  package. `source/recovery.py` is also the generated standalone `RESTORE.py`.
- Preserve the primary failure when cleanup or a progress observer also fails.
  Never turn an incomplete operation into a successful one.

## Verification and releases

Run focused behavioral regressions for the change, then the relevant CI gates.
`python scripts/run_tests.py --quiet` runs the Python suite. `npm ci --ignore-scripts`
and `npm run check:syntax` check browser syntax; `npm test` tests UI state handling.
Development dependencies are optional and are not application dependencies.

Keep `CHANGELOG.md` factual; put unfinished work in `TODO.md` and sequencing in
`ROADMAP.md`. Record the exact environment, commit, failures and skips for claimed
qualification. Historical evidence is never proof of a newer build. Real hardware
claims require hardware evidence.

The release workflow publishes only a stable version on a main-branch push whose
commit message contains `[release]`, after every required job succeeds. Use that
marker only for an intended release. Never overwrite a published tag or artifact.
