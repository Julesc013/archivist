# GUI and local-service validation for V2 development

Recorded: 2026-11-17. This is development evidence, not a production qualification statement.

## Changes implemented

The existing four-area interface and shared application boundary were retained.

- A selected package retains its identity and metadata across list pages. The Encoding dialog reads the actual package record, including its codec and level.
- File moves use a searchable, paged query across compatible packages, including packages outside the displayed plan page. A chosen destination remains selected when paging the chooser.
- Clearing a plan clears dependent rows, inspector state and contextual actions.
- Plan labels include creation time and identity. The inspector identifies the parent revision and can reopen it. Existing immutable revision storage is reused.
- Scans, plans, built archive sets and stored copies expose Load older controls. Selected older observations/plans can remain visible outside the current newest page.
- Diagnostics show individual capability states and concrete next steps, with exact technical details under a disclosure. Executable presence is not represented as live Everything or physical LTFS qualification.
- The Archive area shows registered copies separately from staging sets.
- Recovery can search recorded member manifests and select the matching packages plus available directory metadata. Missing metadata package IDs and unknown metadata completeness are shown explicitly; partial kits are not described as complete directory recovery. The interface states that complete selected packages are restored; this is not individual-member extraction. Search is not a payload verification.
- One task poller drives progress and completion. Package selection no longer fetches its member list twice. Disconnects remain visible and do not silently resubmit work.
- Terminal task timing freezes. Completed tasks no longer receive active-stall notices or ETAs. Running tasks show observed throughput when fresh samples exist.
- Session token, loopback binding, Host/Origin checks and CSP controls remain in place. Explicit service quit still refuses to stop active work.

## Executed checks

| Command / group | Result | Evidence provided |
|---|---|---|
| `node tests/gui_state.test.cjs` | 13 checks passed | Shipped JavaScript handlers executed in a minimal DOM with controlled API responses. |
| `python -m unittest discover -s tests -p test_gui_v2.py -v` | 4 tests passed | Real HTTP catalogue paging/search and terminal/queued-cancellation timing. |
| `test_runtime.HttpTests` | 8 tests passed | Actual loopback auth, origin/host rejection, public assets, path rejection, preference roundtrip and core scan operation. |
| `node --check source/static/app.js` | Passed | JavaScript syntax only. |
| Python compilation of changed service/progress and GUI harness files | Passed | Python syntax only. |

The 13 JavaScript checks cover off-page codec correctness; clearing stale state; full-catalogue move lookup; one member fetch per selection; distinguishable revisions; object pagination beyond 100 entries; completed-progress wording and live throughput; one terminal-result fetch; pending work on disconnect; explicit recovery package scope; missing/unknown directory metadata in partial kits; actionable diagnostics; and native-capacity input with explicit missing-metadata warnings after byte fit.

The real HTTP catalogue regression fixture creates 105 distinct project directories, creates an immutable gzip revision of an early package, browses a later package page, retrieves the earlier package by identity and finds a target beyond the first page. It does not mock the planner or SQLite store.

The four new Python tests are part of normal unittest discovery. Node is needed only for the JavaScript development checks, not normal application or recovery use.

## Browser qualification

Native browser execution is **not qualified in this environment**. The earlier audit found that Playwright's bundled browser was absent; the installed Chromium aborted with `socket() failed: Operation not permitted`. No restricted-browser workaround was attempted and no visual or CSP-enforcement pass is claimed.

`scripts/check_gui.py --output <directory>` now defaults to native localhost navigation and uses the real server's headers. Its optional `--bridge` mode is explicitly a diagnostic harness; it does not qualify browser navigation or CSP enforcement. This harness has been syntax checked, but its new native mode has not completed here.

The minimal DOM tests deliberately do not simulate layout, focus behavior, screen readers, browser event defaults, CSS, network origin enforcement or CSP. They execute application handlers and state transitions only. The existing historical V20 screenshots are not evidence of the new V2 layout.

## Remaining limits

- Native Windows/macOS launchers, live Everything IPC and physical LTFS remain separate qualification gates.
- Recovery search reads manifests. Large-set latency and cancellation of a long catalogue query need measurement on representative archives.
- Selected-package recovery restores complete packages. Fine-grained file extraction is not implied.
- The job footer represents one current phase. An independently measured overall package-count/two-level progress model remains future work.
- Connection loss leaves acknowledged tasks pending while the UI retries. After a server process dies, operators must inspect durable operation history and resume according to the execution contract; this UI does not promise a distributed job manager.
- Load older controls are intentionally simple. Large-catalogue global search and richer revision comparison can be added using the same application queries.

No original V20 source files were edited for this work.
