# Task 3 Review — Reads, pending enumeration, and contract evidence

- Plan: `.mstar/plans/20260911-transcript-storage.md` (task 3 of 3, final)
- Review mode: **A, L2, diff-first** — read-only, leaf executor, no delegation
- Range: base `f3cd735` → head `1019000` (`feature/20260911-transcript-storage`)
- Worktree: `.worktrees/20260911-transcript-storage` (control harness: `/root/workspace/bilibili-asr-archive`)
- Authoritative spec: `.mstar/iterations/iter-2026-09-subtitle-transcript-sqlite/specs/transcript-storage.md`
- Diff: `.mstar/sdd/20260911-transcript-storage/review/task-3-diff.md` (5 files, +1089/−4)
- Implementer report: `.mstar/sdd/20260911-transcript-storage/implementer-task-3-report.md` (claims treated as unverified)
- Carried items judged here: Task-2 review **M3** (verbatim order/overlap pin) and **M2** (`run_id` one shared path)
- Special circumstance: the first run was cancelled mid-flight; `1019000` is a fresh implementer's audited, resumed version of that WIP. The audit's five claimed fixes (D1–D5) are judged **by the committed result**, not by the report.

## Spec Compliance

**✅ Spec compliant — 0 Critical, 0 Important; 3 Minor (one test-strength, one report accuracy, one
evidence-scope note) plus ⚠️ items for PM. None blocks Task 3.**

Every brief item, every spec §4 signature and every §6 acceptance clause this task owns is present and
pinned by an assertion that fails when the guard is reverted:

| Brief / spec requirement | Artifact (shipped line) | Pinning test |
|---|---|---|
| `read_transcript` — latest by default, explicit version, `None` when absent; typed record (§4 signature, §5 verbatim body) | `database.py:1011-1035` (`ORDER BY version DESC LIMIT 1` / exact match), `:1036-1064` (`list_transcript_versions`, `ORDER BY version`), `:1183-1200` (`_stored_segments`, `ORDER BY ordinal`) | `test_read_transcript_returns_the_latest_version_and_keeps_an_older_one_readable`, `test_list_transcript_versions_lists_one_identitys_versions_oldest_first`, `test_reads_of_absent_versions_identities_and_parts_are_empty` |
| `list_pending_subtitle_parts(limit=None)` / `count_pending_subtitle_parts()` over `v_pending_subtitles`, never re-derived, locked key list | `database.py:1087-1115`, `:1116-1122` | `test_pending_enumeration_orders_never_attempted_before_the_oldest_attempt`, `…carries_the_last_attempt_evidence_and_excludes_stored_parts`, `test_read_paths_consume_the_views_instead_of_re_deriving_them` |
| Shipped argument-validation discipline for the reads (§4) | `database.py:1092-1096`, `:1194-1198`, `_language_code` `:695`, `_choice`/`_text`/`_integer` (`models.py:49-90`) | `test_pending_enumeration_reuses_the_shipped_limit_validation` (compares against `MetadataRepository.list_pending_parts` **at runtime**), `test_read_arguments_follow_the_module_validation_discipline` (14 cases) |
| `list_selected_parts(bvid, page_index=None)` over `v_video_parts`, `[]` for an unknown selector, no status filter | `database.py:1127-1165` | `test_list_selected_parts_selects_explicitly_or_returns_no_rows` |
| E2E: two languages + two versions; stored part excluded; `attempted = 0` part present; `no-subtitle` evidence; never-attempted before attempted; re-attempt under a new run | `database.py` reads + views (Task 1) | the three E2E tests above; `test_a_part_recorded_no_subtitle_leaves_the_pending_set_when_a_later_run_stores_it` |
| `work_id` stays view/computed (§4, constraint 1) | views only; no column added | `test_work_id_is_computed_by_the_views_and_never_stored` |
| No sidecar read/written by any storage path (§6) | no file I/O in `src/bili_asr/storage/*.py` except the two package-resource schema reads (`database.py:160`, `:163`) | `test_storage_paths_never_read_or_write_a_legacy_sidecar` |
| Read paths never write or commit (§4) | no `commit`, no DML in the five reads | `…returns_the_latest_version…` (`_empty_store` unchanged, `connection.in_transaction is False`), M2 test's unchanged store |
| Process-record pair stays `kind`-scoped | view's `WHERE ar.kind = 'subtitle'` | `test_pending_subtitles_view_is_scoped_to_subtitle_attempts` (new) |
| Task-1 structural guards extended, never weakened | `EXPECTED_CHECK_ENUMERATIONS["transcript_segments"]` **added** (3 fragments verbatim in `schema-transcripts.sql:39-41`) | `test_schema_…` loop at `test_storage_schema.py:919-926` (fragment presence; no `len()` census exists, so the entry is purely additive) |

### Verification I performed (independent of the report)

1. **Focused suite reproduced:** `tests/test_transcript_repository.py tests/test_storage_schema.py` →
   **`117 passed in 4.79s`** (bytecode and pytest cache disabled; `git status --porcelain` empty before and
   after → worktree byte-identical to `1019000`). Per-file collection is exactly the claimed split:
   repository **80** (= Task-2's 48 + 32), schema **37** (= 36 + 1) — the report's arithmetic reconciles.
2. **Diff census re-derived mechanically** from `task-3-diff.md`: 5 files, **+1089/−4**; per file
   `database.py +180/−4`, `models.py +44`, `__init__.py +2`, `test_storage_schema.py +69`,
   `test_transcript_repository.py +794` — **identical to the report** (unlike Task 2's report, whose
   per-file counts did not reconcile). No added line carries trailing whitespace or a tab, so the
   `git diff --check` claim is corroborated from the artifact (git itself not re-run).
3. **The 4 deleted lines are exactly the hand-rolled `run_id` check** in `finish_acquisition_run`
   (`-4/+1` at `database.py:796-803`); **no assertion is deleted, renamed or relaxed anywhere in the
   range** — both test files are pure additions.
4. **Provenance of the green run:** the shared venv's editable install resolves `bili_asr` to the control
   checkout (no `TranscriptRepository`), so the focused run can only be collecting the worktree's tests
   and exercising the worktree's `src` through `tests/conftest.py`; a wrong tree would fail at import,
   not pass silently.
5. **Source inspection for what a diff cannot prove:** no `UPDATE`/`DELETE`/`INSERT OR REPLACE` on any
   transcript table; the sidecar names appear nowhere under `src/`; `ALLOWED_SOURCE_KINDS` is the full
   column vocabulary (`models.py:33`); `_language_code` returns `_text(...).strip()` (`:702`) — the read
   identity is the write identity; the only `ORDER BY` in `schema-transcripts.sql` is the view's
   `ROW_NUMBER()` window, so the work order is genuinely imposed by the repository, not by the view.

## Focus areas

**1. Reads and enumeration — correct, including the ordering pin that Task-1's review left open (⚠️4).**
`read_transcript` defaults to `ORDER BY version DESC LIMIT 1`, honours an explicit version, returns `None`
for a well-formed identity the archive does not hold (absent version, language, kind, part, and the
`asr-local` reservation), and returns the stored segments verbatim in ordinal order. `list_transcript_versions`
is identity-scoped and oldest-first. `list_selected_parts` filters `v_video_parts` by a join on
`video_parts` for `bvid` — a real need, since the view computes `work_id` but does not carry `bvid`
(`schema.sql:125-140`) — and the returned key set is exactly the view's 11 columns (asserted by set
equality). `list_pending_subtitle_parts` / `count_pending_subtitle_parts` read `v_pending_subtitles` and
nothing else; no Python-side filter, sort or re-derivation exists.

**The ordering pin is genuinely discriminating — and I found the exact limit of its discrimination.** The
fixture's insertion order differs from the work order (BV1A's four parts first, then BV0Z, then a `gone`
video) and the two probes are ordered against it (`p2` newest at 500, `p3` oldest at 300), so a missing
`ORDER BY` (bvid/page order → `BV1A:p2` before `p3`), an `attempted DESC` order, or a
`last_attempt_at DESC` order all produce a different asserted list. Mutation A's claimed **2 failures**
(the ordering test plus the retry test, whose `[p1, p0, p2]` also depends on attempted-first) are
consistent with the fixture. The residual: the last two keys are **not** discriminated — with BV0Z holding
a single part, the locked `…, bvid ASC, page_index ASC` and the swapped `…, page_index ASC, bvid ASC`
yield the identical list (see Minor-1). The semantically load-bearing half (`attempted`, `last_attempt_at`,
head-of-bounded-run rotation for `limit=1/2/5`, and `count == 5`) is pinned.

**2. The five claimed audit fixes — all five verified closed on the committed result.**

- **D1 — real.** The coincidence assertion is gone (no `transcript_id == rows[0]` occurrence anywhere in
  `tests/`). The replacement asserts the claim the comment makes: `rows[0]` is `parts[0]`
  (`test_transcript_repository.py:892`), the store holds that part's version 1, and
  `read_transcript(parts[0], "subtitle-cc", "zh-CN") is not None`. Non-coincidental (the transcript was
  written for exactly that part, and the selection is shown not to be transcript-filtered).
- **D2 — real, and the most valuable finding of the audit.** An unarmed intercept is worse than no test:
  it asserts absence of a channel it never observed. The committed test now proves the intercept fires
  *before* it is trusted — a deliberate `open(tmp_root/meta-cursor.json)` must raise, and the recorded
  list must be exactly `["meta-cursor.json"]` — then clears the record and requires `opened == []` for the
  whole storage path (five reads + both writes + run start/finish). That is strictly stronger than the
  inherited "subset of `{archive.db, archive.db-journal}`" check. The write-side layers (exact file set
  `["archive.db", *poison]`, poison bytes unchanged) are unchanged, and the poison set is asserted equal
  to the shipped `LEGACY_SIDECAR_PATHS` (`test_metadata_e2e.py:53-57`), so the transcript guard cannot
  drift from the metadata suite's legacy-file set. Residual reach noted as Minor-3.
- **D3 — real.** All four `run_id`-carrying public methods are in one parametrized loop with the same six
  cases; I grepped the class and there is no fifth (`_require_acquisition_run` / `_run_outcome_from_attempts`
  are private helpers). The four-method claim holds.
- **D4 — real.** `tests/test_transcript_repository.py` now maxes at **93** characters (`:551`), matching
  the shipped `database.py` max (93); the 108-char outlier is gone. (Pre-existing, untouched:
  `test_storage_schema.py:771` is 123 chars — not this task's file region, and the project has no linter.)
- **D5 — real and live.** Dropping `v_pending_subtitles` then `v_video_parts` makes the three view-backed
  readers raise `sqlite3.OperationalError` naming the missing view; a re-derived query over the base tables
  would keep answering. Mutation G (count re-derived from `video_parts`) fails this test — the pin is not
  vacuous. Report wording says "four read methods"; the pin covers three (Minor-2).

**3. Contract evidence — present.** Multi-language / multi-version reads (one part, `subtitle-cc/zh-CN`
v1+v2 and `subtitle-ai/ai-zh` v1, the older version still readable byte-identically, padded language
trimming onto the stored identity), `ON DELETE RESTRICT` in **both** directions (inherited and unchanged:
`DELETE FROM transcripts` rejected by the segment FK, `DELETE FROM video_parts` rejected by the transcript
FK, in `test_schema_foreign_keys_reject_orphans_and_restrict_deletes`), `work_id` view/computed only (the
three views compute it; `UPDATE … SET work_id` is rejected on all four transcript-contract tables for
"no such column"), no sidecar read or written, and Task-1's structural guards **only extended**.

**4. M3 (folded) — closed and non-vacuous.** The body is reversed *and* overlapping
(`(1200,2400)`, `(600,1800)`, `(0,1200)`); the test asserts the raw segment rows `(ordinal, start_ms,
end_ms, text)` in caller order, the digest equals the independently computed digest of the caller order
(`_expected_content_sha256` re-implements §2.2 in the test file), the same body is `unchanged` at version
1, and the read path returns the caller order. It also self-guards its own premise
(`assert sorted_body != body`, and the sorted digest must differ), so it cannot quietly become vacuous.
A write-path `sorted(...)` or a de-overlap fails both halves (the raw rows and the digest) — mutations
B1/B2 each claim 1 failure, consistent with the assertions on file.

**5. Disclosures — (a) correct reading of a real spec gap; (b) no contract lost.**

- **(a) `TranscriptRecord`.** Spec §4 **locks** `read_transcript(...) -> TranscriptRecord | None`, while its
  DTO list enumerates only `TranscriptSegmentRecord`, `TranscriptWriteResult`, `AcquisitionRunRecord`; the
  plan's Interfaces block repeats the omission. The type must therefore exist for the signature to mean
  anything, and a `sqlite3.Row` return would contradict the locked signature and push unpacking into every
  caller. Implementing it as a validated frozen dataclass (non-empty segment tuple of
  `TranscriptSegmentRecord`, vocabulary-checked `source_kind` against the full three-value set, hash shape)
  and exporting it from `models.py:__all__` and the package root is **the correct reading, not a spec
  violation** — but the *spec text* is incomplete and should be recorded by the PM (one-line amendment to
  §4's DTO list; the natural home is the same dated-PM-note mechanism §5 already uses, or the
  iteration-close promotion to `{SPECS_DIR}`/`{KNOWLEDGE_DIR}`). No code change.
- **(b) The M2 message change.** No contract is lost. Spec §4 pins no message text for `run_id`; `_text` is
  literally one shared helper (`models.py:65-72`) reached by all four methods (three direct call sites plus
  `AcquisitionRunRecord.__post_init__` at `models.py:412`, which `start_acquisition_run` constructs), and
  the M2 test asserts type **and** message for all four. The old literal
  `"run_id must be a non-empty string"` survives only in the metadata-scoped `MetadataRepository.run_stats`
  (`database.py:689`) — untouched, out of scope, and not on any task-3 path. The committed Task-2 test
  asserted only the exception type, so nothing regressed; and the change is a **strict improvement**: a
  `run_id` carrying `\r`/`\n`/`\x00` now raises a bounded `ValueError` instead of reaching SQL and raising
  an `IntegrityError` that embeds the raw control character — which was Task-2 Minor-2's exact complaint.
  `_text` returns its argument unmoved, so a padded `run_id` is still looked up as given (no silent
  trimming behaviour change).

**6. Non-vacuity — spot-checked, highest-value first, and each named failing test is discriminating.**

| Claimed mutation | Named failing test / assertion I verified exists | Verdict |
|---|---|---|
| A — locked `ORDER BY` dropped to `bvid, page_index` | `…orders_never_attempted_before_the_oldest_attempt` (order differs) + `…no_subtitle_leaves_the_pending_set…` | discriminating (2 failures consistent) |
| C — `finish_acquisition_run` back to the hand-rolled check | M2 test: `""`/`"   "` would carry the old message, `"r\n1"`/`"r\x001"` would not raise → exactly **4** of 6 cases fail | discriminating, and the arithmetic matches the old code precisely |
| D — `read_transcript` opens `meta-cursor.json` | the armed intercept raises `AssertionError("a storage path opened the sidecar …")` | discriminating (only because D2 armed it) |
| G — `count_pending_subtitle_parts` re-derived from `video_parts` | D5 test's `pytest.raises(OperationalError, match="v_pending_subtitles")` for the count | discriminating |
| B1/B2 — read-path sort by `start_ms` / write-path `sorted(...)` | M3 test's read-order half / raw-ordinal + digest halves | discriminating |
| F1/F2 — `os.open` stray file / sidecar append | archive-root file-set equality / poison-bytes equality | discriminating |

An unclaimed but real one: the new schema test fails if the view's `WHERE ar.kind = 'subtitle'` is dropped
(the `kind='audio'` attempt would make the part look attempted).

**7. Regression lens — clean.** All 4 deleted lines are the hand-rolled `run_id` check; both test files are
pure additions; the only change inside a pre-existing structure is the additive
`EXPECTED_CHECK_ENUMERATIONS` entry, and I verified its three fragments are verbatim present in the shipped
`transcript_segments` DDL with no `len()` census that could hide a swap. `MetadataRepository` is untouched
by this range. No STOP condition was triggered (nothing weakened, no `ALTER TABLE`/backfill, no raw payload,
`ingestion_runs` untouched).

## ⚠️ Cannot verify from diff (for PM to close)

1. **Full offline suite** (`1201 passed, 3 skipped`; baseline `1168/3`, `+33`) is implementer evidence — not
   re-run (prohibited). Mitigations: the focused suite is independently reproduced (`117 passed`), the `+33`
   arithmetic reconciles exactly (repository 48→80, schema 36→37), the diff touches no other test file, and
   all removed lines are accounted for.
2. **The eight mutation runs and the "recorded list is `[]`" probe** are self-reported. Every target
   assertion exists and is discriminating (table above), but reproducing a mutation requires mutating the
   checkout, which this seat may not do.
3. **`git diff --check` clean** — corroborated from the diff artifact (no trailing whitespace, no tabs, no
   space-before-tab in any added line), not by running git.
4. **The audit's provenance claim "the inherited production code was kept byte-identical"** is not directly
   falsifiable: the WIP was never committed, so no artifact holds it. It *is* consistent with the ledger
   once its own per-file typo is corrected — `progress.md:69-71` states `database.py (+184)` but the stated
   `+1041` aggregate only adds up as `180 + 44 + 2 + 69 + 746`, i.e. the WIP's `database.py` was already
   `+180`, equal to the final commit. Since all five D-defects are test-side, no production behaviour is at
   stake; PM should record that the claim rests on arithmetic, not on a stored WIP copy.
5. **Cross-plan discipline for the CLI plan** (not a Task-3 defect, the same class of note Task 2's review
   raised): the CLI must call `list_pending_subtitle_parts` rather than re-deriving the backlog (D5's pin is
   the guard), treat `list_selected_parts(...) == []` as "unknown selector → exit 1" without inventing a
   selection, and use the 12-column work-item set the test pins (it includes `cid`, so the subtitle path
   never re-fetches a pagelist). These belong in the CLI plan's brief, not here.

## Strengths

- **The audit was real work, not a claim.** D2 was a genuine defect — an unarmed intercept *proves* absence
  of a channel it never observed — and the fix converts it into a self-proving guard whose final requirement
  (`opened == []`) is stricter than the inherited one. D1 was a true coincidence assertion. D5 closed a real
  hole in exactly the "never re-derived" property this task owns.
- **The views are pinned structurally, not only behaviourally.** Dropping the relations is the cheapest
  falsifiable proof of "consume the view", and mutation G shows a future CLI-side re-derivation breaks a
  named test — this is the guard the CLI plan inherits.
- **Validation parity is asserted, not copied.** `test_pending_enumeration_reuses_the_shipped_limit_validation`
  runs both repositories and compares the raised exception type *and* message at runtime, so either class
  drifting fails the test. The read paths reject malformed arguments (including `bool`-for-`int`) instead of
  answering an empty result that a caller would mistake for "no caption".
- **The M3 pin is double-sided and self-guarding.** Raw `(ordinal, start_ms, end_ms, text)` rows plus an
  independently re-derived order-sensitive digest plus the read-back order, with a premise assertion that
  cannot silently become vacuous.
- **Evidence hygiene.** Per-file diff census reconciles exactly with the report (unlike Task 2's report), the
  mutation restores were hash-verified, and the environment caveat (shared venv → control checkout;
  `conftest.py` supplies the worktree `src`) is disclosed for QC/QA rather than left for the reviewer to
  discover.
- **Disclosure quality.** All four judgement calls carry the rejected alternative: the DTO, the message
  change, the `bvid` join, and read-path validation for malformed identifiers.

## Issues

### Critical

None.

### Important

None.

### Minor

**Minor-1 — the locked `ORDER BY`'s last two keys are not discriminated by the fixture.**
`test_pending_enumeration_orders_never_attempted_before_the_oldest_attempt` (`:1360`) cannot distinguish
`attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC` from the swapped `…, page_index ASC, bvid ASC`:
the never-attempted set is `{BV0Z:p0, BV1A:p0, BV1A:p1}` and both spellings yield
`BV0Z:p0, BV1A:p0, BV1A:p1` (the `page_index = 0` tie exists in both videos and is broken by `bvid` either
way). The headline semantics are pinned (attempted-first, oldest-attempt-first, bounded-run head, `count`),
so this is a test-strength gap, not a correctness one. *Suggested fixture:* give the second video at least
two pages (or add never-attempted parts under two videos with overlapping page indexes) and update the
expected list and `count` accordingly; the interleaving then differs and the precedence becomes
falsifiable. Non-blocking — it could ride the CLI plan's touch-ups or a small Task-3 follow-up.

**Minor-2 — report/ledger accuracy: "the four read methods".**
`implementer-task-3-report.md:71-74` and `progress.md:97-98` describe D5 as "the four read methods are
required to raise". The committed pin covers **three** view-backed readers
(`list_pending_subtitle_parts`, `count_pending_subtitle_parts`, `list_selected_parts`); the other two reads
legitimately target the `transcripts` base table per §4, so nothing is missing — only the prose is off by
one, and a re-derivation check that "cannot be reconciled" invites exactly the doubt this review exists to
remove. *Disposition:* PM may correct the wording in the ledger; no code or test change.

**Minor-3 — the armed sidecar guard's reach is the Python `open` channel (evidence scope, informational).**
The intercept patches `io.open` / `builtins.open` (which also covers `pathlib.Path.open`/`read_text`), so
the empty record is meaningful evidence for that channel, and the file-set / poison-bytes layers cover
`os.open` **writes** (mutations F1/F2). An `os.open`-based *read* of a sidecar would evade all three layers
(mutation D would have caught a read only because it used `open`). The property still holds by construction —
`src/bili_asr/storage/*.py` contains no file I/O besides the two package-resource schema reads and no sidecar
path literal at all — so this is a note about the test's declared scope, not a defect. If the PM wants it
airtight later: intercept `os.open` as well, or add a one-line source scan for sidecar names.

## Assessment

**Task quality: Approved**

The committed `1019000` is a faithful implementation of the locked §4 signature set, §5's verbatim-order
rule and §6's read/enumeration acceptance clauses: latest-version default with explicit versions still
readable, absent identities answering empty rather than invented, `list_selected_parts` returning `[]` for an
unknown selector, the pending backlog read from `v_pending_subtitles` (never re-derived) with the locked
repository-imposed order, read-only semantics throughout, `work_id` computed only, no sidecar path, and the
Task-1 structural guards extended without weakening anything. The resumed audit's five claimed fixes are all
real on the committed result, judged from the diff and the shipped code rather than the report: D1 replaced a
genuine coincidence assertion, D2 turned a provably unarmed guard into a self-proving one, D3 completed the
M2 method coverage, D4 fixed the outlier line, and D5 closed the "never re-derived" gap with a
mutation-verified pin. The two folded items (M2, M3) are closed, M3 with a non-vacuous, self-guarding pin.
Regression risk is low: exactly four deleted lines, both test files pure additions, one additive schema
expectation entry whose fragments match the shipped DDL, and the deleted logic was replaced by a shared
helper the rest of the class already used. I independently reproduced the focused suite (`117 passed`) with a
clean worktree and re-derived the diff census per file. The three Minor findings are one test-strength gap
(the `bvid`/`page_index` precedence), one off-by-one in the report's prose, and one note about the sidecar
guard's declared reach; the PM also has the `TranscriptRecord` DTO-list omission to record as a spec
amendment. None requires touching `1019000`.

---

## Revalidation

- Fix wave: `1019000..5f93e05` (one commit, `test(storage): make the pending order's last two keys falsifiable`),
  diff read once from `review/fix-1-diff.md`; no git run, no checkout mutation, no product file touched by this seat.
- Scope: **Minor-1** (the actionable finding) is re-judged against the committed fixture by execution;
  Minor-2 / Minor-3 and disclosure (a) are verified as dispositions, not re-litigated.

### Minor-1 — CLOSED (falsifiability demonstrated, not argued)

**Expected order re-derived by hand from the committed fixture** (not from the implementer's printed lists).
`_video_with_parts` maps `cids` positionally onto `page_index` (`:77-86`), so BV1A holds pages 0-3
(`first_video[2]`/`[3]` = `BV1A:p2`/`BV1A:p3`, probed at `finished_at` 500 / 300 in runs `caption-run-1`/`-2`),
BV0Z holds pages 0-1, BV1GONE page 0 and is excluded by the view's `processing_status <> 'gone'`; no part
holds a transcript, so the pending relation holds **6** rows. Under the locked
`attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC`: the four never-attempted rows tie on
`attempted = 0` and `last_attempt_at IS NULL`, so `bvid` decides — `BV0Z` < `BV1A` (`'0'` < `'1'`) — and
`page_index` orders within each video: `BV0Z:p0, BV0Z:p1, BV1A:p0, BV1A:p1`; then the attempted pair splits on
300 vs 500: `BV1A:p3, BV1A:p2`. Full list `[BV0Z:p0, BV0Z:p1, BV1A:p0, BV1A:p1, BV1A:p3, BV1A:p2]` — identical to
the committed assertion (`:1378-1385`). With **only** the last two keys swapped, the never-attempted block
interleaves as `BV0Z:p0, BV1A:p0, BV0Z:p1, BV1A:p1` (page-0 tie broken by `bvid`) → first difference at index 1.
The fixture now contains the distinguishing pair the old one lacked — `(BV0Z,1)` vs `(BV1A,0)`, where
`bvid_i < bvid_j` **and** `page_i > page_j`; pre-fix, every pair was same-page or same-`bvid`, which is exactly
Minor-1.

**Live confirmation — three in-process probes, no file written, no repository mutation.** A
`sqlite3.Connection` subclass injected through the documented `factory=` parameter rewrites only the guarded SQL
text at call time; the loaded module was printed and confirmed to be the worktree's
`.worktrees/20260911-transcript-storage/bilibili-asr-archive/src/bili_asr/storage/database.py`.

| Probe | Mutation applied | Observed |
|---|---|---|
| control (`SWAP=none`) | instrumentation only, SQL untouched | `1 passed` → the subclass is behaviour-neutral **and** the committed file carries the locked spelling (a leftover swap would fail here) |
| `SWAP=unbounded` | `:1117` only (guarded query, no bound) | `1 failed` at `:1378` — `At index 1 diff: 'BV1A:p0' != 'BV0Z:p1'` |
| `SWAP=limit` | `:1110` only (the `LIMIT` query) | `1 failed` at `:1395` — `['BV0Z:p0', 'BV1A:p0'] == ['BV0Z:p0', 'BV0Z:p1']` |
| `SWAP=both` | both queries | `1 failed` at `:1378`, same index-1 diff |

The mutated order observed at index 1 equals my hand-derived interleave exactly, which also validates the new
comment's claim (`:1381-1382`) that page-index-first would interleave the block as
`BV0Z:p0, BV1A:p0, BV0Z:p1, BV1A:p1`. **Both guarded queries are therefore individually falsifiable** — the
answer to the PM's question is yes, established by execution. Cross-checked against the fix report's S1/S2/S3:
identical failure sites and identical index-1 diff, so the report reconciles with an independent run.

**Count and bounded-run assertions are consistent:** `6 = 4 (BV1A) + 2 (BV0Z)`;
`count_pending_subtitle_parts() == len(work_ids) == 6` passes; `limit=1` is untouched and heads both spellings;
`limit=2` was updated to the locked head `[BV0Z:p0, BV0Z:p1]` and is itself falsified by the `LIMIT`-only swap
above; `limit=6` reproduces the unlocked list at the fixture's new size. Sanctioned focused run at `5f93e05`:
**`80 passed in 3.00s`** — the same 80 tests as at `1019000`, i.e. the same test, strengthened.

### Regression lens

- **Test-only — confirmed to the limit of the permitted evidence.** `fix-1-diff.md` contains exactly **1 file**
  (`bilibili-asr-archive/tests/test_transcript_repository.py`); I re-counted it mechanically from the artifact:
  **+12 / −8**, matching the Assignment and the ledger's `5f93e05` entry. Corroboration from the checked-out
  tree: both guarded spellings are still the locked ones (`database.py:1110`, `:1117`), and my Task-3 exact
  anchors land unchanged — `database.py:689` (`"run_id must be a non-empty string"`), `:695`
  (`_language_code`), `:1011` (`read_transcript`), `:1035` (`ORDER BY version DESC LIMIT 1`), `:1087`
  (`list_pending_subtitle_parts`); `models.py:33` (`_ALLOWED_SOURCE_KINDS`, the three-value vocabulary),
  `:49`/`:65`/`:85` (`_integer`/`_text`/`_choice`), `:412` (`_text(self.run_id, "run_id")` in
  `AcquisitionRunRecord.__post_init__`); `schema-transcripts.sql:39-41` (the three checked fragments). A
  leftover mutation in the product file is additionally ruled out by the passing `SWAP=none` control.
  *Limit, stated plainly:* byte-identity to `1019000` cannot be proven by this seat (no git), and three of my
  original range citations (`:1036-1064`, `:1116-1122`, `:1183-1200`) were hunk-derived approximations — the
  exact anchors above are the ones I rely on.
- **No assertion deleted or relaxed — 0 deleted assertion lines.** All 8 deleted lines enumerated: 1 fixture
  comment, 1 fixture argument, 3 expected-list entries, 1 `count` assertion, 1 `limit=2` expectation, 1
  `limit=5` bound. Every one is re-added in updated form; the test's assertion count is unchanged (`limit=1`,
  `"BV1GONE:p0" not in work_ids` and the docstring assertion are untouched). `limit=5 == work_ids` →
  `limit=6 == work_ids` preserves its intent ("an explicit bound reproduces the unlocked list") at the fixture's
  new size, and the `limit=2` change is a **strengthening** — it now pins bvid-first precedence on the bounded
  path. Nothing was quieted to accommodate the bigger fixture.
- **No cross-test coupling.** `BV0Z` occurs only inside this one test (`grep` over `tests/`); `_video_with_parts`
  itself is unchanged — only its argument tuple moved — and its positional contract is what makes pages 0-1
  correct; each test gets a fresh store through `tmp_root`; the sibling pending tests (`BV1EVID`, `BV1RETRY`,
  `BV1SELECT`) are single-video fixtures and cannot reach the last two keys as a tie-break. The untouched
  80-test focused run is the behavioural confirmation.

### Mutation-hygiene incident — no doubt remains about this wave's evidence

I verified the incident's premise independently instead of accepting the disclosure: the control checkout's
`database.py` is 23,871 B and contains **neither** `TranscriptRepository` **nor** the `ORDER BY attempted ASC`
anchor, so a helper pointed there substitutes 0 occurrences and writes back identical bytes — the disclosed
failure mode is benign *by construction* and cannot have altered the control tree's content. No stray
`*.orig`/`*.bak`/`*.rej`/mutation artefacts exist in either checkout, and the control file holds no transcript
code. Two further reasons the incident cannot taint this wave's conclusion: **(1)** the direction of the error —
a wrong-path mutation yields a *pass*, never a false failure, and failures were reported; **(2)** decisive — I
reproduced those failures myself, live, on the worktree's code with nothing but the guarded SQL text rewritten,
so the substance of the mutation evidence no longer rests on the implementer's harness at all. The report also
records that the re-runs used an absolute path with a printed substitution count of `1` each, which is the
durable fix for this error class. **Judgement: no residual, no doubt.** The incident is a correctly disclosed
process note, already mitigated; if the PM wants one ledger line it is "mutation helpers use absolute paths and
assert a non-zero substitution count" — a convention the report's §3 output shows is now in place.

### Dispositions verified (not re-litigated)

- **Minor-2 — closed.** `progress.md:97-98` now reads "…makes the **three view-backed readers** fail"; the
  phrase "four read methods" appears nowhere under `{SDD_DIR}` anymore. The fix-round report was written after
  the review and carries the correct scope, so no stale copy remains.
- **Minor-3 — accepted as informational, rationale intact.** `progress.md:119-121` records the `os.open`-read
  evasion as a declared-reach note with the by-construction argument; I agree it is not a defect (no file I/O
  and no sidecar literal in `src/bili_asr/storage/*.py` beyond the two package-resource schema reads).
- **Disclosure (a) — recorded.** The spec carries the dated PM note in its §4 DTO block
  (`specs/transcript-storage.md:415-416`), naming `TranscriptRecord` as the originally omitted return type; no
  code change, as recommended.

### Residual scope of the new pin — recorded, **no action requested**

The pin is now falsifiable for the precedence **swap** (the class Minor-1 named) and for **dropping `bvid`**
(probe `drop_bvid` → `1 failed`, index 0). One mutation class still passes: dropping `page_index ASC` entirely
(`ORDER BY attempted, last_attempt_at, bvid`) — the within-`bvid` tie is then resolved by SQLite's scan/rowid
order, which for this fixture coincides with page order, so the list is unchanged (probe `drop_page` →
`1 passed`). Closing it deterministically needs a page inserted *before* a lower-index sibling of the same
video, which `_video_with_parts` (page index == tuple position) cannot express — a helper-expressiveness limit,
not a flaw in this fix; the alternative pin is a static assertion that both queries carry the verbatim key list.
Recorded for the PM's judgement; I am not proposing a fix wave and do not treat it as a finding for this plan.

### Updated severity counts

| Severity | Before (Task-3 review) | Now |
|---|---|---|
| Critical | 0 | 0 |
| Important | 0 | 0 |
| Minor | 3 (test strength, report wording, evidence scope) | **0 open** — Minor-1 closed by `5f93e05` (live-verified); Minor-2 fixed in the ledger; Minor-3 accepted informational |
| Informational (no action) | — | 1 (dropped-key mutation class, above) |

Regression risk after the fix: **low**. One test file modified (+12/−8), no product line, no assertion removed,
the changed expectations strengthened, no cross-test coupling, focused suite `80 passed`, and each guarded query
fails its own assertion under a swapped spelling.

### Verdict

**Approve** — Minor-1 is genuinely closed (falsifiability demonstrated by execution, on both guarded queries,
not by reasoning), the change is surgical and test-only, no existing assertion was relaxed or removed, and the
mutation-hygiene incident leaves no doubt about this fix wave's evidence. Plan-2 Task 3 remains approved with
**0 open findings**; what is left for the PM is records, not work — the spec §4 note (already written) and the
optional dropped-key observation above.
