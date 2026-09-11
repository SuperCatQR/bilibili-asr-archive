### Task 2: TranscriptRepository writes with content-based idempotency

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/storage/database.py`
- Modify: `bilibili-asr-archive/src/bili_asr/storage/models.py`
- Create: `bilibili-asr-archive/tests/test_transcript_repository.py`

**Interfaces:**
- Consumes: Task-1 schema/vocabulary and the existing canonical repository forms and commit
  matrix.
- Produces: `TranscriptRepository` with `start_acquisition_run`, `finish_acquisition_run`,
  `record_acquired_transcript`, `record_subtitle_attempt`.

- [ ] Bound the converted timeline (carried from plan `20260911-subtitle-gateway` QC S11 / QC3-008):
      reject a segment whose millisecond product exceeds a documented ceiling (e.g. `> 10**12`, ≈31 years)
      with the bounded validation error, so an upstream JSON integer cannot reach SQLite as an unbounded
      `OverflowError`. Record the chosen ceiling in the spec's normalization section and pin it with a test.
- [ ] Implement `start_acquisition_run` / `finish_acquisition_run` with the shipped run
      discipline (own commit; terminal outcomes cannot be regressed; when no explicit outcome
      is given, derive `complete | partial | failed` from the attempt rows).
- [ ] Implement `record_acquired_transcript` as **one** transaction: validate the part and the
      arguments, compute the content hash from the canonical segment JSON, write nothing when a
      version of `(video_part_id, source_kind, language)` already carries that hash (attempt
      outcome `unchanged`, referencing the existing version), otherwise append
      `version = MAX(version) + 1` with its segments (attempt outcome `stored`), write the
      attempt row, and commit — or roll back wholly. Reject an empty segment tuple, a
      non-positive `video_part_id`, and a `start_ms`/`end_ms` violation.
- [ ] Implement `record_subtitle_attempt` for the `no-subtitle` / `failed` outcomes only, with
      the CHECK matrix enforced in code as well (bounded `error_code` required for `failed`,
      `NULL` or `not_found` for `no-subtitle`, no transcript reference for either).
- [ ] Document the class's commit-boundary matrix in its docstring in the same style as
      `MetadataRepository`, including the "do not compose inside `transaction()`" rule.
- [ ] Tests: first write; idempotent repeat (`unchanged`, no new row, no duplicate segments);
      changed content → version 2 with version 1 and its segments unchanged; revert-to-older
      content → `unchanged` referencing version 1; FK rejections (unknown part, unknown run,
      unknown transcript); RESTRICTed deletes; CHECK violations; transactional rollback when the
      attempt row cannot be written; run-outcome derivation for all three cases plus the
      abnormal `failed`.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_transcript_repository.py -v`

