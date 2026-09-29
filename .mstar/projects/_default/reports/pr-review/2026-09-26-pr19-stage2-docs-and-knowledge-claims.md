---
stage: 2
seat: docs-and-knowledge-claims
domain: docs-and-knowledge-claims
pr: 19
head: 84e9767146c03977812591a48a991e0fce7de985
diff_base: 9d530cd646e50142cd92789b2494c72806025ffd
---

# Stage 2 evidence — docs-and-knowledge-claims (PR #19)

## [DOC-01] The README's `audioread` decode-chain claim is false in the repo's own closure

- **Evidence**: `bilibili-asr-archive/README.md:143-144` and the same claim in the code docstring at
  `bilibili-asr-archive/src/bili_asr/asr.py:387-389`
- **Impact**: an operator is told a dependency fact about the shipping configuration that the resolution denies
- **Effort**: S · **Risk**: LOW · **Confidence**: HIGH · **Merge class**: should-fix
- **Fix sketch**: name the librosa range in which the fallback is audioread-backed, or say it is unverified

## [DOC-02] `related_components` points at a file with no read-back surface

- **Evidence**: `.mstar/knowledge/testing-patterns/hotword-list-measurement.md:29` names
  `manifest.py (read-back surface)`; `manifest.py` has 0 `frontmatter`/`yaml` references. The arm identity is
  read from the produced transcript's frontmatter, written at `bilibili-asr-archive/src/bili_asr/archive.py:493`
- **Effort**: XS · **Risk**: LOW · **Confidence**: HIGH · **Merge class**: nit
- **Fix sketch**: repoint to `archive.py (write_archive -> asr_* frontmatter)`

## [DOC-03] A stale `L456-467` citation

- **Evidence**: `.mstar/knowledge/testing-patterns/hotword-list-measurement.md:63`; `_extra_hotwords` is at
  `bilibili-asr-archive/src/bili_asr/asr.py:316` at HEAD. It is the only `L<digits>` citation in the corpus
- **Effort**: XS · **Risk**: LOW · **Confidence**: HIGH · **Merge class**: nit
- **Fix sketch**: change to `asr.py:316`, keeping the function name

## [DOC-04] "double restoration proof" contradicts the document's own new text

- **Evidence**: `…/hotword-list-measurement.md:191` still advertises the proof this PR rewrote as **unsound** at `:71-78`
- **Impact**: When-to-Apply routes a future author to the approach the same doc condemns
- **Effort**: XS · **Risk**: LOW · **Confidence**: HIGH · **Merge class**: nit
- **Fix sketch**: reword to "byte-anchored restore proof"

## [DOC-05] `last_updated` missing on both substantively-updated docs

- **Evidence**: neither `.mstar/knowledge/testing-patterns/hotword-list-measurement.md` nor
  `.mstar/knowledge/best-practices/premise-freshness-before-lock.md` carries the field; earlier-refreshed docs do
  (e.g. `.mstar/knowledge/best-practices/claim-scope-discipline.md:4`)
- **Effort**: XS · **Risk**: LOW · **Confidence**: MED · **Merge class**: nit
- **Fix sketch**: add `last_updated: 2026-09-26`

## Checked and TRUE

The section's premise — "`soundfile` cannot decode AAC" — holds: `subprocess`-verified against a real AAC
`.m4a` (`soundfile.LibsndfileError: Format not recognised`). The defect is confined to the mechanism sentence.
