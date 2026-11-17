# Sources and evidence

External references were checked on 2026-11-17 where used in the V2 review.
Source inspection and retained test/benchmark JSON are the primary evidence for
claims about this implementation. External documentation does not establish
that this application satisfies a specification or has passed a hardware test.

| Topic | Primary reference |
|---|---|
| Semantic Versioning | https://semver.org/ |
| Python release/security status | https://devguide.python.org/versions/ |
| SQLite trusted-schema introduction | https://www.sqlite.org/releaselog/3_31_0.html |
| SQLite safety settings | https://www.sqlite.org/pragma.html |
| Windows DirEntry identity fields | https://docs.python.org/3.12/library/os.html#os.DirEntry.stat |
| Package-to-directory mapping | https://setuptools.pypa.io/en/latest/references/keywords.html |
| TAR compression/multi-volume limit | https://www.gnu.org/software/tar/manual/html_node/gzip.html |
| fpart directory/file planning | https://www.fpart.org/fpart/ |
| DAR open format and features | https://dar.sourceforge.io/doc/Features.html ; https://dar.sourceforge.io/doc/Notes.html |
| Amanda architecture | https://github.com/zmanda/amanda |
| LTFS format 2.5 | https://www.snia.org/sites/default/files/2025-03/SNIA-LTFS-Format-v2.5-Technical-Position.pdf |
| Zstandard CLI | https://github.com/meta/zstd/blob/dev/programs/zstd.1.md |
| GitHub workflow actions | https://github.com/actions/checkout ; https://github.com/actions/setup-python ; https://github.com/actions/setup-node ; https://github.com/actions/upload-artifact |
| Ruff | https://pypi.org/project/ruff/0.17.5/ |

Competitor claims are deliberately limited: directory packing is not unique to
this project; DAR is not proprietary; backup suites differ in formats/recovery
dependencies; ordinary compressed GNU tar does not become a multi-volume stream
by adding `-M`; LTFS still has index overhead. The product's intended value is
an understandable local workflow and explicit recovery evidence, not a proven
claim that all alternatives fail.

The chosen identity is recorded in [NAMING.md](NAMING.md). Earlier naming sources
and negative-search limits remain in the linked historical research.
