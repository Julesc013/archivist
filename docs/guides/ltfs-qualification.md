# Mounted LTFS qualification worksheet

Status: **not performed for this release**. This is an operator-run qualification
procedure for the experimental Linux mounted-LTFS adapter, not an instruction to
format or erase media. Use an explicitly designated test cartridge with an
independent copy of any needed data.

Record OS/kernel, filesystem/driver/vendor version, drive model/firmware/interface,
cartridge type and barcode/serial, library path if relevant, and mount options.
Record the nominal capacity separately from observed mounted free space and
explicit reserve. Never claim vendor “compressed capacity” for already encoded
payloads.

## Required exercises

- Verify mount detection distinguishes actual LTFS from a normal directory and
  records the mounted source identity.
- Register the mounted test destination with explicit experimental opt-in.
- Use small none/gzip/zstd sets, empty directories, non-ASCII representable names,
  mixed packages and files large enough to exercise actual streaming.
- Compare preflight occupancy, written file lengths, observed free space and the
  driver-reported end state; explain any reserve or allocation difference.
- Exercise interrupted copy, retry, conflicting partials and no-replace failure
  without damaging unrelated media content.
- Perform the vendor-supported index/finalization procedure, unmount and unload;
  remount/reload and verify the set and restored contents from the cartridge.
- Where an independent second compatible drive exists, repeat readability there
  and record it as a distinct observation.
- Record cancellation latency, stalls, errors and actual throughput with source,
  encoder and destination phases separated. Do not infer a universal write block
  size or index-reserve percentage from a single setup.

The application cannot certify that `sync` or a successful file read proves a
physically durable tape/index. Retain vendor commands/logs and actual readback
results. Until this procedure succeeds for the declared environment, keep the
adapter experimental. Raw tape filemarks, spanning and robotics are separate
contracts and are not exercised by an LTFS directory copy.

Primary format reference: https://www.snia.org/sites/default/files/2025-03/SNIA-LTFS-Format-v2.5-Technical-Position.pdf

