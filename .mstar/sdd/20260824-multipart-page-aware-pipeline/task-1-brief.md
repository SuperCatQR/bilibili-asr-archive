### Task 1: Define identity and migrate legacy rows

- [ ] Add `bili_asr.page_identity` with `PageIdentity`, `format_work_id`, `parse_work_id`, `artifact_stem`.
- [ ] Key `ManifestStore` by `work_id`; keep `bvid` as a required field; add `get_compatible(bvid)`.
- [ ] Atomic, deterministic migration only when pagelist length is 1 and no colliding `{bvid}.pN` artifacts exist.
- [ ] Preserve ambiguous legacy rows byte-for-byte plus additive `unresolved` / `unresolved_reason=ambiguous_bare_bvid` / `excluded_from_page_processing`; report count and identifiers; no automatic page assignment.
- [ ] Tests: stem has no `:`; migrate single-page; freeze multi-page bare row.

