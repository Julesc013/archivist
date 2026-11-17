# Architecture

One local application boundary and one authoritative recovery reader. Source
modules remain directly under `source/`; a unique Python package namespace is
mapped there by setuptools and the portable launcher. No generic global `core`
or `planner` Python package is installed.

| Module | Responsibility |
|---|---|
| application.py | Shared operations, locking, orchestration and preflight boundary |
| compat.py | Runtime floor and verified SQLite connection/capability requirements |
| store.py | Normalized SQLite schema, queries and working evidence |
| path_cache.py | Disposable LRU path caches with finite entry/scalar-byte budgets |
| inventory.py | Filesystem/Everything observations, reconciliation and issues |
| planning.py | Deterministic grouping, exact-once membership, immutable revisions and allocation |
| capacity.py | Explicit package/kit/staging byte accounting |
| artifacts.py | Source guards, encoders, committed package builds and archive-set publication |
| kit_publication.py | Staged recovery-kit transaction/journal and interrupted-update handling |
| destinations.py | Registered disk/experimental LTFS roots, copy/readback and replica reconciliation |
| recovery.py | Standalone parser, path checks, seals, decoder, validation and extraction |
| catalogue.py | Bounded plan diffs and archive-manifest search/dependency diagnostics |
| archive_html.py | Escaped offline catalogue view from the same set selection |
| evidence.py | Data-only transfer and sealed V12/V13 migration |
| sampling.py | Explicit bounded codec samples; no silent plan rewrite |
| progress.py | Structured progress/cancellation and terminal timing |
| cli.py / web.py | Thin operator adapters to shared operations |
| static/ | One browser interface; no separate planning algorithm |
| util.py | Shared path, hashing, identity, serialization and publication primitives |

## State and transactions

The database retains normalized observations and memberships rather than repeated
expanded JSON trees. Writes use a cross-process workspace lock, checked SQLite foreign
keys, WAL and full synchronous mode. Runtime compatibility is checked before
workspace creation; safety settings are confirmed on actual connections. Builds publish individually verified package
directories; a set catalogue is a separately sealed scope of those packages.

Filesystem publication and SQL insertion are not one atomic transaction. Replica
receipts are therefore durable identity evidence for idempotent reconciliation.
Archive-set metadata is several flat files, so kit updates stage complete
generations with a journal rather than pretending a single file rename makes all
files atomic. Readers do not execute journal or helper data. Actual power-cut
behaviour depends on qualified OS/filesystem/device durability semantics.

## Deliberate limits

No daemon framework, plugin ecosystem, ORM, remote service, UI component
framework or mandatory Python dependency was added. This is not a prohibition
against future dependencies; each must solve a measured need and preserve
independent recovery. The standalone reader must not import application internals. Application path
guards reuse its narrow system-alias normalization without introducing a reverse
dependency. Keep external-decoding and independently executable recovery tests
rather than generating an unreadable mini-application.

Critical modules retain untyped historical interfaces in places. Syntax/lint and
runtime invariants are checked; a claim of universal strict static typing is not
made. Grow typed boundary models where they reduce ambiguity instead of wrapping
every SQLite row solely to increase the dataclass count.

