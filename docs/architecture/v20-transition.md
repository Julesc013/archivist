# V20 → V2 provenance and compatibility

Input: supplied `Archivist_v20.0.0-eval.1.zip`, 449,040 bytes.

SHA-256:
`bdb3778922a3abe1e550c303e953de6effe4b744eec17b73aa70f55c21e63015`

The input's 69 sealed files were verified before inspection. A differently sized
file with the same name existed among the supplied material; it was not chosen.
The checksum-matched final archive was the reference. All original source bytes
remain separate and unmodified.

The V20 baseline ran 86 tests: 85 passed and one native Windows launcher test was
skipped on Linux. The copied source/ bootstrap initially reproduced that result
before functional changes. Baseline timings are not compared with historic
reports from different environments.

The V2 tree retains 14 original module responsibilities and adds cohesive modules
for capacity, catalogue queries, human manifest rendering, transactional kit
publication and bounded directory-path caching. It preserves the MIT licence and
frozen synthetic V13 fixture.
Historic GUI screenshots and benchmark reports are not carried forward as proof
of V2 behaviour; current evidence is in docs/validation/.

Working product/distribution versions are 2.0.0-alpha.1/2.0.0a1. The old
archivist-20 distribution is not automatically replaced. The new default
workspace/config location is separate. `.ap20`, SQLite schema 1 and AP20 format 1
identifiers remain compatibility contracts rather than marketing versions.

All corrected failure cases use synthetic data. They establish the described
outcome in the tested environment, not complete adversarial assurance or physical
media qualification.

