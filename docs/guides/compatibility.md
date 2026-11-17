# Runtime and platform compatibility

Compatibility has three distinct checks: supported syntax/API floor, actual
runtime capability and qualification on a named environment. A passing feature
probe does not certify every OS/filesystem/browser combination. Current observed
results are in [validation](../validation/README.md).

## Python and SQLite

Archivist uses Python **3.8 or later**. No mandatory third-party Python package
is required. None/gzip codecs use the standard library; zstd is an optional
external executable. Prefer a maintained interpreter. Supporting old Python
syntax does not renew upstream security maintenance; consult the
[Python version status](https://devguide.python.org/versions/).

The application requires its linked SQLite library to be **3.31.0 or later**.
SQLite 3.31 introduced `trusted_schema`; the application disables it and confirms
that setting, foreign-key enforcement and the expected query-only mode. Runtime
diagnostics also probe UPSERT, backup and read-only opening. Real workspace
connections require WAL and FULL synchronous mode. A missing or ineffective
capability fails visibly instead of selecting a weaker configuration. Version
and capability checks precede new workspace creation.

Run `python3 archivist.py doctor` for these results even when a workspace cannot
be opened. A Python version string alone does not identify its linked SQLite.
See [SQLite's 3.31 release](https://www.sqlite.org/releaselog/3_31_0.html) and
[PRAGMA documentation](https://www.sqlite.org/pragma.html).

Standalone RESTORE.py also supports Python 3.8+. It uses standard-library sqlite3
for a temporary path index, but does not open the original application database
or require its schema/SQLite feature floor. Keep the sealed helper shipped with
an existing valid set; a newer application does not silently replace it.

## Filesystem behavior

No-replace publication requires the platform's exclusive native rename primitive
and a supporting filesystem. Unsupported environments fail closed. Normal file
lengths and successful flushes are not universal physical-allocation or durability
proofs; network filesystems and unusual mounts require their own qualification.

Windows scanner identity uses explicit `os.stat(..., follow_symlinks=False)`:
[DirEntry.stat documents zero device/inode/link-count fields on Windows](https://docs.python.org/3.12/library/os.html#os.DirEntry.stat).
User links/reparse points remain outside the baseline preservation profile.
Windows filename and permission semantics differ from POSIX and remain explicit
in scan/restore diagnostics. Live Everything 1.5/ES operation is an additional
integration qualification beyond the filesystem backend.

On affected Windows/Python versions, path-based `os.stat()` can report creation
time in `st_ctime_ns` while `os.fstat()` reports change time for the same file.
CPython maintainers confirmed this mismatch on 2026-09-17 in
[issue #157671](https://github.com/python/cpython/issues/157671). The
[Python 3.12 timestamp documentation](https://docs.python.org/3.12/library/os.html#os.stat_result.st_ctime_ns)
also deprecates the Windows creation-time meaning of `st_ctime_ns` in favor of
`st_birthtime_ns`; the meaning must not be assumed interchangeable across APIs.

Inventory hashing compares `fstat()` observations before and after reading the
same open descriptor, including device, inode, size, modification time and
`ctime`. The path-to-descriptor check still compares device, inode, size and
modification time; POSIX also compares the pre-open `ctime`. This avoids false
Windows source-change reports while retaining detection of descriptor metadata
changes during hashing. These live checks do not provide snapshot consistency.

A platform-specific regression creates a real Windows directory junction and
checks root refusal, descendant exclusion and preservation of the external
target. It requires Windows and a fixture volume that reports reparse-point
support; a failed junction creation on a supporting volume is a test failure.

On macOS standard `/var`, `/tmp` and `/etc` aliases may normalize to their verified
root-owned `/private` targets. Link targets, ownership and relevant writable/sticky
properties are checked. This does not permit arbitrary user-created links or links
inside source/output trees. APFS normalization, metadata and mount behavior still
need named native evidence; a Linux path simulation is not that evidence.

## Browser behavior

The full GUI uses **ES2017** syntax plus Fetch, Promises, Map/Set and iterators,
Array.from/includes, Object.assign, Number checks and String.startsWith. An
**ES5** bootstrap checks required APIs before loading the app. If loading, parsing
or startup fails, or JavaScript is disabled, the page retains readable guidance
and the CLI remains available.

Native dialog support is optional. The fallback manages focus, Tab/Shift+Tab,
Escape and focus return. Disclosure and selected DOM convenience methods also
have fallbacks; CSS supplies baseline light colors, block layout and visible
keyboard focus when newer features are unavailable. Capability negotiation never
weakens server authentication or automatically retries a mutation.

No precise historical browser version is promised from these checks alone.
Qualification uses actual browser engines, including fallback and no-JavaScript
cases; consult the recorded versions/results. The offline ARCHIVE.html catalogue
has no JavaScript dependency and is distinct from the interactive application.

The [release workflow](../../.github/workflows/test.yml) configures 19 native
OS/Python combinations and three browser-engine jobs: Chromium, Firefox and
WebKit. It also exercises the optional-dialog fallback in Chromium. This is the
configured gate coverage, not a statement that a particular run passed; completed
results and their exact environments are recorded in [validation](../validation/README.md).

## Media scope

Ordinary disk directories are the baseline destination. The Linux mounted-LTFS
adapter is experimental until the documented physical mount/finalization/remount
procedure succeeds for the specific driver, drive and cartridge. Raw tape,
filemark spanning, library robotics, snapshots and encryption are outside 2.0.0.
