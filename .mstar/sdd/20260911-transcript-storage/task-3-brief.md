### Task 3: Reads, pending enumeration, and contract evidence

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/storage/database.py`
- Modify: `bilibili-asr-archive/tests/test_transcript_repository.py`
- Modify: `bilibili-asr-archive/tests/test_storage_schema.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces: `read_transcript`, `list_transcript_versions`, `list_pending_subtitle_parts`,
  `count_pending_subtitle_parts`, `list_selected_parts`, and the deterministic E2E evidence the
  CLI plan builds on.

- [ ] Implement the read paths (latest version by default, explicit version on request;
      `None` when absent) and `list_selected_parts(bvid, page_index=None)` over
      `v_video_parts`, returning zero rows for an unknown selector so the CLI can exit `1`
      without inventing an empty selection.
- [ ] Implement `list_pending_subtitle_parts(limit=None)` over `v_pending_subtitles` with the
      locked order (`attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC`) and
      `count_pending_subtitle_parts()`, with the shipped argument-validation discipline.
- [ ] E2E evidence: one part with two languages and two versions; a stored part excluded from
      the pending set; a part with metadata only present with `attempted = 0`; a part recorded
      `no-subtitle` still present with its last outcome, timestamp, and credential presence; the
      never-attempted part enumerated before the previously attempted one; a successful
      re-attempt after `no-subtitle` storing a transcript normally under a new run.
- [ ] Assert the enumeration contract the CLI depends on and that `work_id` stays view-only;
      assert no legacy sidecar file is created or read by any storage path.
- [ ] Re-inspect the final schema for the locked invariants (column manifests, indexes, checks)
      and pin the process-record shape chosen in the spec.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_storage_schema.py tests/test_transcript_repository.py -v`

**PM-authorized follow-ups (2026-09-11, from the Task-2 L2 review).** Both are small and recorded, not
silent relaxations:

- [ ] **M3 (coverage gap, the important one):** pin spec §5's "order preserved verbatim, overlaps included"
  with a body whose intervals are non-monotonic and overlapping (today every test body is ascending and
  non-overlapping), so a future "sort or de-overlap on write" regression fails a named test.
- [ ] **M2 (consistency):** validate `run_id` through the same path as the other identifiers (the class
  currently uses `_text` in two places and a hand-rolled check in another) and keep the messages byte-identical.

## STOP Conditions

- A single-transaction transcript write cannot satisfy the FK order or immutability rules →
  stop and update the spec rather than weakening constraints.
- The locked process-record shape cannot record bounded evidence without touching
  `ingestion_runs` semantics → stop and escalate the contract gap.
- Satisfying idempotency requires storing raw subtitle payloads → stop; content hashes only.
- The bootstrap split cannot keep a pre-iteration database usable for the metadata commands
  without a migration path → stop and report; do not add `ALTER TABLE`/backfill code.
- Existing metadata tests cannot stay green under the schema change → stop and report (the
  change must be additive and rebuild-safe).

## Durable Roadmap and Dependencies

- Consumed by `20260911-subtitle-cli-cutover`; the `asr-local` source kind and `asr_models`
  FK stay unused until the audio/ASR iteration.
- Resolves carry F-010: subtitle/transcript process records get their own explicit home
  (`acquisition_runs` + `acquisition_attempts`, keyed by `kind`), so the metadata-scoped
  `ingestion_runs` semantics stay untouched. The next iteration reuses the same pair with
  `kind='audio'` / `'asr'`, and inherits the transcript versioning rules, the enumeration of
  parts with no transcript, and one recorded handoff: activating `asr-local` with more than one
  model requires widening the model-agnostic version key, owned there.
- Deferred with a named owner (`project-manager`, trigger "this iteration delivered"):
  promoting this storage contract out of the iteration package at iteration-close
  (`mstar-compound` decides `{SPECS_DIR}` versus `{KNOWLEDGE_DIR}`); nothing is written into
  `{SPECS_DIR}` during Prepare.
- Deferred: audio objects (`audio_objects` / `part_audio_objects`) remain reservations, and
  rebuilding SRT/TXT/MD projections from stored transcripts is owned by the next iteration.

## Drift Check

Before implementing, re-read the shipped `schema.sql` reservations and the metadata
repository's canonical forms and `docs/metadata-storage.md` (its "Fresh-start behavior" and
"Reserved media boundary" sections must be updated by the CLI plan, not silently left wrong);
confirm no other module depends on the reserved tables' current shape or on `schema.sql` being
the single schema resource.

## Acceptance / Done Criteria

- [ ] Schema carries the locked transcript columns/tables/indexes/view with inspection tests
      pinning them, and the bootstrap handles fresh / current / pre-iteration databases.
- [ ] Transcript writes are transactional, versioned, immutable, and content-idempotent.
- [ ] A stored transcript answers, per part: source kind (AI/CC), language, version, creation
      time, and millisecond segments; the latest version is what a default read returns, and an
      explicit version stays readable after a newer one is written.
- [ ] "No subtitle was visible" is recorded as timestamped per-part attempt evidence, is not a
      transcript row, and does not prevent a later successful acquisition of the same part.
- [ ] Process records for subtitle acquisition are explicit and do not touch
      `ingestion_runs` semantics.
- [ ] The pending view's order and last-attempt columns are pinned by tests, so successive
      bounded runs advance instead of re-attempting the same head.
- [ ] Offline suites green with no metadata-path regressions.
- [ ] No sidecar file is created or read by any new path.
- [ ] `git diff --check` clean.

## Prepare → Execute Handoff

Execute Task 1 → Task 2 → Task 3 (serial). Then SDD review package, QC tri, QA gate, merge.

## Review Gate Summary

- Decision: pending
- Review range / Diff basis: pending
- Review bundle: `.mstar/sdd/20260911-transcript-storage/review/`
- QC inputs: `qc1.md`, `qc2.md`, `qc3.md`
- Blocking result: pending
- Residual findings: pending

## QA Gate Summary

- QA gate: mandatory
- QA mode: acceptance
- Evidence: pending

## Sign-off

- Product intent: reviewed (product-manager, 2026-09-11)
- Architecture: reviewed (architect, 2026-09-11)
- Writing/corpus hygiene: reviewed (writing-specialist, 2026-09-11)
- PM lock: pending
- Implementation owner: fullstack-dev
- QA owner: qa-engineer
- Review cleanup: zero-residual

## Plan self-review

1. Every spec decision maps to a task and an assertion, including the exact DDL deltas.
2. No task stores raw payloads or derived duplicates.
3. Immutability and idempotency are both testable, and each has a named enforcement mechanism.
4. The process-record decision is explicit, keyed by `kind`, and does not overload metadata
   runs; the next iteration's reuse is stated.
5. Audio/ASR objects stay reservations, with the model-identity handoff recorded.
6. The stored state answers the operator's questions — source, language, version, time axis —
   and records "no caption visible" as bounded per-part evidence rather than as an absence or a
   terminal state.

## Evidence Index

- Primary spec: `.mstar/iterations/iter-2026-09-subtitle-transcript-sqlite/specs/transcript-storage.md`
- Tests: `tests/test_storage_schema.py`, `tests/test_transcript_repository.py`
- SDD runtime: `.mstar/sdd/20260911-transcript-storage/`

## Status Transition

Starts `Todo`; `InProgress` after the Phase 2 lease; `InReview` after implementation;
`Done` only after QC + the mandatory QA gate and the integration merge.

## End

Transcript storage is the durable contract for every future caption/ASR source; the
gateway plan only feeds it.
