# Dependencies and attribution

Archivist contains no vendored third-party Python packages, fonts, icons or native
binaries. Python and its linked SQLite library come from the operator's runtime.
The standalone reader uses the standard library, including sqlite3 for a temporary
path index, and optionally invokes an external zstd decoder.

External zstd, Everything/ES, findmnt, platform libraries and the browser retain
their own licenses and distribution terms. Setuptools, wheel, Ruff, Node.js,
Playwright and browser test binaries are development/qualification tools, not
bundled runtime dependencies. Their pinned requirements or CI configuration are
recorded in the repository.

The project derives from the supplied Archive Planner V20 evaluation source and
retains its MIT license and copyright notice. See
[transition provenance](docs/architecture/v20-transition.md). Synthetic V13
fixtures were generated from the supplied prototype using test data, not the
user's disks. External specifications and documentation consulted are listed in
[docs/SOURCES.md](docs/SOURCES.md).
