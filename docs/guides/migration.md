# Migrate evidence safely

1. Keep the original V20 distribution and evidence unchanged. Stop its writer
   before exporting. Preserve the exported `.ap20` bundle and its digest.
2. In V2, import into a **new** directory:
   `python3 archivist.py import old.ap20 --output /new/evidence`.
3. Open that directory explicitly with `--workspace /new/evidence` and inspect
   observations, plan counts, issues and preserved decisions.
4. Bind each imported source to its current root using `bind SOURCE_ID ROOT`.
   Binding is not content verification. Build still checks recorded identities,
   metadata and available content hashes.
5. Register intended destinations in the new context. Imported destinations are
   disabled; no prior path or approval grants permission to write.
6. Test recovery of a small synthetic set and the actual chosen platform before
   relying on the migrated workflow.

The bundle transfers evidence, not source data or built payloads. It contains
exactly FORMAT.json and a checked SQLite database. The importer refuses an
existing target, unknown members, bad lengths/digests and unsupported database
schema. V12/V13 use the explicit `migrate-v13` command with sealed legacy evidence;
unsupported old decisions remain references rather than silently changing codecs.

V2 environment variables are `ARCHIVIST_WORKSPACE`,
`ARCHIVIST_CONFIG_HOME`, and `ARCHIVIST_PYTHON` for Unix launchers.
Old AP20 environment settings do not implicitly open the old default workspace.
An explicit `--workspace` remains authoritative.

Do not run V20 and V2 writers against the same database as an upgrade strategy.
Shared schema recognition supports transfer/inspection, not arbitrary concurrent
writer compatibility. Restoring an older valid AP20Archive/1 set does not require
workspace migration; use its independent recovery files or the supported reader.

