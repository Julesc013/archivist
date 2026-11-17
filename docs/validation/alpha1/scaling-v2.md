# V2 bounded scaling experiment and directory-cache fix

Final measured snapshot: **2026-11-17 18:54 AEDT / 07:54 UTC**. Baseline: **18:36 AEDT / 07:36 UTC**. Raw measurements, environment facts and selected source hashes are in `scaling-v2.json` and `scaling-v2-before-path-cache.json`. The reproducible harness is `scripts/benchmark_v2.py`.

## Result and scope

**Both retained directory-path caches now have finite limits.** `Store._paths` and `InventoryBuilder.dirs` use the same small `PathCache` implementation, with at most **8,192 entries and 8 MiB of accounted scalar key/value bytes per cache**. Container bookkeeping is additional and bounded by the entry limit. These are cache budgets, not an 8 MiB or 16 MiB whole-process memory guarantee. A miss reloads directory identity or ancestry from SQLite; eviction never removes recorded evidence. A path too large for the byte budget is resolved without retaining it.

The bounded synthetic experiment completed all five cases before and after the change. All recorded file counts, directory counts and logical-byte totals matched the fixtures, and every plan was READY. The final frozen-source run took **23.09 seconds**, including fixture creation and separate cache diagnostics. No archive build, compression, restore throughput, tape operation, live Everything query, native GUI rendering or million-file test was performed.

The observed trade-off was mixed. In the broad-directory case, worker peak RSS was **43.39 → 38.56 MiB**, while planning took **0.894 → 1.169 s**. In the deep-directory case, peak RSS was **36.25 → 37.01 MiB** and planning took **0.298 → 0.383 s**. The cache change establishes a finite retained-path policy; it does not promise lower memory or faster processing on every tree. These are one-shot observations on a shared host, not a statistically controlled attribution of each timing or RSS difference to the cache.

## Why the fix was warranted

The original diagnostic retained **3.95 MiB** of Python cache objects for 30,151 shallow directory paths, but **5.90 MiB** for only 8,225 deep paths. Complete expanded path strings make total path length relevant in addition to directory count. Source inspection confirmed that both dictionaries had no explicit entry or byte limit.

The implementation uses a least-recently-used `OrderedDict` mapping restricted to immutable integer/string keys and values. Reads update recency; membership and iteration do not. Insertion evicts older entries until both limits hold, and an oversized replacement removes any stale old value before declining the new one. There is no environment-controlled hidden cache policy. SQLite is the authority, and the existing indexed lookup, deterministic ancestry reconstruction and parent-cycle rejection remain in place.

The legacy evidence importer also retained each builder's cache in an unused `folders` dictionary. Removing that unused variable and assignment avoids keeping every imported builder's cache alive. No legacy fixture or evidence format was changed.

The tests exercise both entry and byte eviction with deliberately tiny budgets. The measured broad/deep probes reach the production **entry** cap; their accounted key/value sizes remain below 8 MiB, so those measurements alone do not demonstrate production-size byte eviction.

## Environment and method

The environment reported Linux 6.18.57, Python 3.12.14, SQLite 3.53.1, an AMD EPYC 9V74 CPU model and nine visible/affinity CPUs. This is a shared execution environment, not a dedicated nine-core machine qualification.

All generated sources and SQLite workspaces resided under owned temporary directories on **tmpfs**, with 4,096-byte filesystem blocks. The filesystem case is actual directory enumeration, but it is **RAM-backed and recently generated**. These results do not measure HDD/SSD latency or throughput and must not be presented as predictions for the operator's storage hardware.

Each acquisition/planning case ran once in a fresh Python process. Each cache diagnostic ran in another fresh process. There was no cache flush, workload isolation or repeated timing distribution. Concurrent host activity was uncontrolled. In addition to the cache edits, the before/after source snapshots include unrelated application/allocation changes recorded by their hashes; this is an illustrative engineering comparison, not a strict one-variable performance trial.

Application acquisition and planning were timed separately. Fixture creation, application module imports, independent count reconciliation and cache diagnostics were outside those phase timers. Package/member timings call the actual application API directly; they exclude HTTP, browser JavaScript and rendering latency. Each application call opens its own Store, while operating-system page caches remain warm.

Peak RSS is cumulative within a worker and must not be summed across phase snapshots. Current RSS from `/proc/self/statm` and the resource high-water sample can differ slightly at a sampling boundary. Workspace bytes are regular-file logical sizes after connections close, not allocated blocks or payload bytes. MiB means 1,048,576 bytes.

## Final measurements

Times are single observed samples, rounded for display. The JSON retains full precision.

| Synthetic case | Files | Directories, including root | Acquisition s | Plan s | Worker peak RSS MiB | Evidence MiB | Packages |
|---|---:|---:|---:|---:|---:|---:|---:|
| Frozen EFU, fixed tree | 50,000 | 1,126 | 3.431 | 1.064 | 35.47 | 23.30 | 26 |
| Frozen EFU, same fixed tree | 100,000 | 1,126 | 6.429 | 2.165 | 37.14 | 46.31 | 26 |
| Actual tmpfs enumeration | 10,000 | 2,001 | 1.428 | 0.228 | 27.83 | 6.51 | 2,001 |
| Frozen EFU, broad directories | 30,000 | 30,151 | 2.998 | 1.169 | 38.56 | 25.05 | 2 |
| Frozen EFU, deep directories | 8,192 | 8,225 | 1.850 | 0.383 | 37.01 | 6.46 | 2 |

The fixed-topology pair doubles the file count without doubling measured worker memory: 35.47 → 37.14 MiB. Import and planning time and evidence size increase substantially. This observation applies to those two fixtures, not an unmeasured million-entry population.

### Before/after comparison

| Case | Acquisition s, before → after | Plan s, before → after | Peak RSS MiB, before → after |
|---|---:|---:|---:|
| EFU 50k | 3.220 → 3.431 | 0.971 → 1.064 | 34.56 → 35.47 |
| EFU 100k | 6.243 → 6.429 | 2.093 → 2.165 | 36.94 → 37.14 |
| Filesystem 10k | 1.449 → 1.428 | 0.232 → 0.228 | 27.66 → 27.83 |
| Broad directories | 3.141 → 2.998 | 0.894 → 1.169 | 43.39 → 38.56 |
| Deep directories | 1.585 → 1.850 | 0.298 → 0.383 | 36.25 → 37.01 |

The broad-case peak is about 11% lower in the later sample, while its planning time is about 31% higher. The deep-case cache contains almost as many entries as before and adds ordered-mapping bookkeeping, so a universal memory improvement would be an unsupported claim. Cache misses can require more SQLite lookups and path reconstruction. Single-run timing differences also contain shared-host noise and the effects of the other recorded source changes.

### Fixture definitions

- **Fixed tree:** 25 collection directories, 100 groups and 1,000 project directories. The 50k and 100k cases share the same topology. Files have deterministic mixed suffixes and synthetic byte sizes representing approximately 2.475 TB and 4.953 TB of logical data. Those multi-terabyte payloads were not materialised.
- **Actual filesystem:** 2,000 direct child directories, each with five 1 KiB binary files: exactly 10,240,000 physical file-content bytes. Scanning enumerates metadata without file-content hashing. Creation took 0.268 s on tmpfs in the final run, excluded from acquisition time.
- **Broad directories:** 150 bucket directories, each containing 200 child directories with one 128-byte logical file per child. This raises the directory/file ratio deliberately.
- **Deep directories:** 32 branches, each with 256 nested directories and one 128-byte logical file at every level. The maximum directory path has 257 named components / 1,288 characters. These are EFU records, not native Windows long-path qualification.

All EFU cases use the normal 10 GB minimum goal / 100 GB target / 200 GB maximum policy and plain TAR selection. The actual-filesystem case sets the minimum goal to zero so its 2,000 coherent leaf directories become distinct packages; this exercises queries beyond the first 100 packages. Different-shape results are therefore not a controlled one-variable planner comparison. The 50k/100k pair shares topology and policy.

### Final application query latency

| Case | First package page ms | First page rows | Last package page ms | First member page ms | Member rows |
|---|---:|---:|---:|---:|---:|
| EFU 50k | 0.705 | 26 | 0.501 | 4.849 | 100 |
| EFU 100k | 0.836 | 26 | 0.664 | 7.844 | 100 |
| Filesystem 10k | 0.931 | 100 | 0.537 | 0.413 | 5 |
| Broad directories | 0.976 | 2 | 0.620 | 14.319 | 100 |
| Deep directories | 0.756 | 2 | 0.810 | 7.021 | 100 |

The filesystem case's final page contains one record after 2,000 earlier packages. Below 100 packages, the first and last page are the same logical page; the later observation follows prior queries. Single-package detail queries took approximately 0.340–0.508 ms. These are application-call observations, not user-perceived UI latency or guaranteed service-level targets.

## Directory-cache diagnostic

The separate diagnostic opens the existing SQLite workspace and asks `Store.path()` for every directory in ID order. It records the retained entries and path characters, plus `sys.getsizeof` of the mapping object, its container and retained scalar keys/values. The accounted key/value bytes are the part governed by the 8 MiB budget.

| Case | Entries, before → after | Final retained path characters | Key/value bytes MiB, after | Total measured cache objects MiB, before → after |
|---|---:|---:|---:|---:|
| EFU 50k and 100k | 1,126 → 1,126 | 35,400 | 0.108 | 0.143 → 0.193 |
| Filesystem 10k | 2,001 → 2,001 | 30,000 | 0.160 | 0.231 → 0.323 |
| Broad directories | 30,151 → 8,192 | 204,119 | 0.734 | 3.951 → 1.796 |
| Deep directories | 8,225 → 8,192 | 5,326,248 | 5.619 | 5.905 → 6.275 |

This object-size calculation is diagnostic. It is not exclusive allocated memory, allocator overhead or a substitute for process RSS. It does not separately measure `InventoryBuilder.dirs`, although that cache uses the same finite policy and is exercised by the scan tests. Transient path reconstruction, current SQL rows, the SQLite cache and other application structures are outside these cache budgets.

## Correctness checks for the bounded policy

The six focused tests in `tests/test_cache_v2.py` passed. They cover:

1. LRU eviction and safe mapping iteration/copying, with consistent byte accounting.
2. Byte-budget eviction and an oversized replacement that cannot leave a stale cached value.
3. Finite default limits, disabled caching and invalid-limit/value rejection.
4. Idempotent `ensure_dir` and exact path reconstruction after forced tiny-cache eviction, including deep Unicode paths and distinct case variants.
5. Parent-cycle rejection even when caching is disabled.
6. A real synthetic filesystem comparison between the original unbounded dictionary behavior and a two-entry / 160-byte cache. Recorded path sets, observation fingerprints/counts, plan fingerprints/counts and exact-once membership remain identical, including empty directories.

The four existing migration tests also passed, including the sealed legacy fixture checks and reuse behavior. The cache implementation changes retained working state, not the archival object identities or interchange format.

The benchmark itself reconciles file counts, directory counts and logical-byte totals. It is not an independent per-path/content restore comparison. The focused regression and clean-room tests serve different purposes and are not replaced by these timings.

## Provenance, cleanup and remaining limits

The pre-change baseline is preserved separately as `scaling-v2-before-path-cache.json`. An initial post-change attempt completed while `source/planning.py` was being edited concurrently; that result is retained as `scaling-v2-path-cache-source-drift.json`, with `source_unchanged_during_run: false`. It is not the final comparison column.

The final run used a temporary frozen copy of `source/`, the checkout bootstrap and the benchmark script. Its JSON records the selected inventory/store/planning/application/path-cache source hashes and confirms that those files did not change during measurement. This avoids claiming one source snapshot for workers that ran across a live edit. Later formatting or implementation changes do not retroactively change the measured hashes; no post-format performance claim is implied.

All synthetic sources, working evidence and the frozen source copy were created in owned temporary directories. Both cleanup checks recorded that those directories no longer existed. No user's source tree or destination media was used.

The unresolved scaling work is **representative qualification**, rather than leaving the known path dictionaries unbounded: larger/deeper real trees, cold HDD/SSD/network filesystem behavior, repeated samples on a defined environment, and separately measured build/compression/restore performance. No million-file, tape or live Everything qualification follows from this run. Establish regression envelopes from repeated measurements on a defined host, not this one-shot comparison.

Do not compare these memory figures directly with the historical V13/V20 report. The old harness also materialised and sorted a full path/size list for independent reconciliation; this harness avoids that extra memory surface and runs in a different environment without rerunning the old release.

The baseline JSON discloses one reporting-only correction: a package-detail action returns an object, so its inapplicable list-row count was changed from zero to null and its response kind labelled. No timing or memory measurement was changed.

To reproduce the bounded run:

```sh
python scripts/benchmark_v2.py --output docs/validation/scaling-v2.json
```

The script uses a 240-second total worker budget and per-worker timeouts, reports incomplete cases explicitly, and requires no external benchmark library. Save any previous JSON under a different filename before reproducing it.
