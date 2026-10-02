---
plan_id: stem-contract-consolidation
project: _default
status: draft
created_at: 2026-10-02
execution_mode: sdd
plan_parallelism: serial
---
# Stem contract — consolidate the three divergent canonical-stem implementations
## Status
- **Priority**: P2 · **Effort**: M · **Risk**: MED · **Depends on**: none · **Category**: tech-debt · **Confidence**: MED
- **Evidence**: 010 cluster 5 STOP — quality._canonical_stem / integrity._canonical_stem / coordinator.archive_stem_for_entry diverge on edge rows (divergence table at `.mstar/sdd/010-dedupe-shared-helpers/cluster5-divergence.md`). Compass D5 decides the contract.
## Contract (D5, authoritative)
A part's stem derives from its `(bvid, page_index)` identity, parseable back to that identity. `page_label` is a DISPLAY concern, NOT part of the stem. A row missing `bvid` raises (fail-loud). This matches `archive_stem` (the publication stem the archive writes).
## Approach
Define one `canonical_stem(row)` in `page_identity.py` (or `archive.py`) implementing D5. Migrate the three call sites (quality.py, integrity.py, coordinator.py) to delegate. Verify each consumer still behaves correctly under the chosen contract (quality's page_label display uses a SEPARATE display helper, not the stem). Pin with a characterization test covering the divergence-table rows.
## Files: src/bili_asr/page_identity.py (or archive.py), src/bili_asr/quality.py, src/bili_asr/integrity.py, src/bili_asr/coordinator.py, tests.
## Verification: one canonical_stem definition; the three callers delegate; a characterization test pins the D5 contract on the divergence rows; quality/integrity/coordinator owning suites green.
## STOP: if a consumer's behaviour genuinely depends on the OLD divergent fallback (not display), STOP + report which consumer + why before changing it.
## Done: single stem; divergence table resolved; suites green.
