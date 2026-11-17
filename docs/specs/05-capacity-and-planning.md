# 05 — Planning and capacity

**CAP-01.** Logical bytes, estimated TAR/metadata bytes, measured encoded bytes
and observed availability are separate integer quantities with evidence bases.
Decimal GB/TB differ from binary GiB/TiB.

**CAP-02.** A package footprint is payload + compressed manifest + receipt. Each
used destination additionally budgets the recovery kit and headroom. Measured
allocation uses validated actual object lengths. Available corrupt evidence fails
visibly; unavailable builds fall back to explicitly labelled estimates.

**CAP-03.** Charge the measured full source kit plus 4 MiB metadata headroom per
used destination. This is conservative for subset replicas. Copy preflight uses
the same bound, and generated metadata MUST fit before publication. Every stored
object, including sidecars, is subject to max_file.

On an interrupted-copy retry, credit only completed owned objects whose bytes
and identity have been checked. Do not credit unrelated or orphaned temporary
files. Reusing existing bytes does not skip final replica verification.

**CAP-04.** Reconcile observed free space, configured capacity/occupancy and
reserve. Do not subtract formatting overhead twice from mounted free space.
No predicted compression or additional hardware-compression credit authorizes
copy. File lengths do not predict physical allocation on every filesystem;
reserve remains an operator/media input.

**CAP-05.** Staging retains completed packages. Budget the estimated remaining
selected payloads, manifests, receipts and 32 MiB set allowance, accounting for
already committed packages. No rolling eviction or largest-package-only budget
is implemented. Estimated fit does not replace actual output limits or failures.

**PACK-01.** Directory-first grouping and first-fit decreasing media placement
are deterministic under identical ordered inputs. Minimum/target are soft goals;
maximum is hard. Oversized files are blocked, not silently fragmented. No global
packing optimality is claimed.

**PACK-02.** Keep fitting child subtrees whole. Root direct files may stay together
up to the whole-group ceiling; this does not merge every separate top-level
project. Reasons/anchors/policy remain inspectable. Manual edits preserve
exact-once membership and lineage.

**PACK-03.** Logical membership is exact once; physical replica placement may
need directory metadata on more than one medium. Current allocation does not
automatically duplicate these dependencies. It MUST not promise complete
metadata-preserving subtree recovery on every individual allocated medium.
Allocation, copy preflight and search report required metadata as available,
missing or unknown. These diagnostics do not silently expand an exact selection.

**PERF-01.** Report workload, interpreter, filesystem, scale and phase with every
benchmark. Small fixtures do not establish million-entry memory bounds or tape
streaming speed. A buffer absorbs temporary deficits, not a sustained source/
compressor throughput shortfall.

**PERF-02.** Each directory-path cache is limited to 8,192 entries and 8 MiB of
retained scalar key/value object sizes. Container overhead is additional but
bounded by entry count. An oversized entry is not cached. Eviction never deletes
SQLite evidence, changes identities or weakens cycle detection. These cache
limits are not a whole-process memory guarantee.

