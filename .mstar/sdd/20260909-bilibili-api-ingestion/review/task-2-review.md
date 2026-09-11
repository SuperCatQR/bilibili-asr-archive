# Task 2 Review — Resumable Normalized Metadata Ingestion

- **Role**: code-reviewer (L2, Mode A diff-first) — leaf executor, delegation forbidden
- **Plan**: `20260909-bilibili-api-ingestion` · Task 2 of 3
- **Range**: `dfb66ba..0c2c379` on `feature/20260909-bilibili-api-ingestion`
- **Diff**: `{SDD_DIR}/review/task-2-diff.md` (read once; no `git` re-run; worktree unmutated)
- **Reviewer verification run** (sanctioned focused command, once):
  `pytest tests/test_metadata_ingest.py -v` → **17 passed in 0.35s** (confirmed independently)
- **Files in diff**: `services/__init__.py` (new), `services/metadata_ingest.py` (new),
  `tests/test_metadata_ingest.py` (new). **Zero `storage/database.py` hunks — the
  implementer claim "database.py NOT modified" is verified against the diff.**

Line references below use the worktree files; diff-file line ≈ file line for these
new-file hunks (`metadata_ingest.py` diff line − 26, test file diff line − 485).

## Spec Compliance — ✅ Spec compliant

**Brief checklist, item by item:**

| Brief item | Verdict | Evidence |
|---|---|---|
| Start `ingestion_run` with requested bounds + package version | ✅ | `metadata_ingest.py:199-214` — run row carries `source_version = gateway.get_package_version()` (line 208), resolved `requested_start_page` (explicit arg → stored cursor's `next_page` → 1, lines 207/219-223), `requested_page_limit`; `source_package` constant matches the schema `CHECK (source_package = 'bilibili-api-python')` (`schema.sql:40`). User row upserted first in its own transaction (lines 205-208) — required because `ingestion_runs.mid` FKs into `bilibili_users`. |
| Per-page: fetch summaries → parts → persist user/video/part + discoveries in ONE transaction in Plan-1 locked order | ✅ | Ingestor composes; it never opens a competing transaction. `_record_collected_page` calls the repository's `record_page(page, user=, videos=, parts=, discoveries=, cursor=)` (`metadata_ingest.py:429-450`), whose single transaction applies user → videos → parts → discoveries → cursor → page outcome → commit in exactly the locked order (`database.py:407-418`). Parts fetched once per distinct bvid (`metadata_ingest.py:232-241`). |
| Idempotent repeated pages; separate run/page evidence per run; `ON CONFLICT DO UPDATE` upserts | ✅ | users `ON CONFLICT(mid)` (`database.py:170-179`); videos `ON CONFLICT(bvid)` with first-non-None aid backfill `COALESCE(videos.aid, excluded.aid)` (`database.py:190-209`); parts `ON CONFLICT(bvid, page_index)` (`database.py:223-245`); discoveries PK `(run_id, page_number, bvid)` + `DO UPDATE` (`schema.sql:79-88`, `database.py:456-472`). Separate per-run evidence pinned in `test_page_limit_ends_run_as_limited_and_resume_completes` (two `run_id`s, per-run page rows) and `test_gateway_failure_...`. |
| Outcomes `complete`/`limited`/`risk_interrupted`/`failed`; never claim completion under explicit page limit | ✅ | `complete` set only on empty page (`metadata_ingest.py:258-269`); `limited` when the limit stops collection (`metadata_ingest.py:270,288-290`) — empty page at the limit boundary still completes, pinned by `test_empty_page_completes_even_when_it_reaches_the_page_limit`; `GatewayRateLimited` → `risk_interrupted`, every other bounded gateway error → `failed` (`metadata_ingest.py:56-67`). No path sets `complete` while a limit cut collection short. |
| Preserve prior cursor on gateway failure; rollback whole page transaction; scalar code in separate page/run outcome transaction | ✅ | Failures are caught during the fetch phase, before any page transaction opens (`metadata_ingest.py:224-256`) — no partial page state can exist. The scalar `error.code` (bounded, validated) is persisted in the no-payload `record_page` call, which the repository handles atomically via `_record_failed_page` (`database.py:420-450`): page row + run failure transition in one transaction, guarded against terminal-run regression (`WHERE outcome = 'running'`, lines 443-450) and page clock vs stored `started_at` (lines 436-441). Prior cursor asserted byte-for-byte via `CursorRecord` equality (`test_gateway_failure_...`, `read_cursor(MID) == cursor_before_failure`). |
| Required test cases (all seven) | ✅ | single-part (`test_single_part_run_completes_with_normalized_rows`), multipart zero-based/ms (`test_multipart_video_persists_zero_based_parts_in_milliseconds`), duplicate page results (`test_duplicate_summaries_in_one_page_collapse_into_single_rows`), empty-page completion (pinned boundary test + page 2 in tests 1–2), explicit page limit (`test_page_limit_ends_run_as_limited_and_resume_completes`), rollback on failure (`test_gateway_failure_...`), cursor preservation/resume (tests 4, 6, 7). |

**Global constraints (plan, verbatim list) — each ✅:**

- Pinned package as API reference + version exposure: `source_version` from the gateway's
  `get_package_version()` persisted per run (`metadata_ingest.py:208, 210-214`); no
  credentials, URLs, or raw response bodies anywhere in the new code or tests.
- Only `sources/bilibili_api_gateway.py` imports `bilibili_api`: verified by grep (zero
  matches under `src/bili_asr/services/`) and structurally — Task 1's AST test
  `test_only_the_gateway_module_imports_bilibili_api` enumerates `src/bili_asr`
  recursively (`test_bilibili_api_gateway.py:850-852`), so the new `services` package is
  scanned automatically; the green full suite includes it.
- One bounded page per gateway call: one `get_user_video_page(mid, page_number, 100)` per
  iteration (`metadata_ingest.py:224-227`); ingestor advances the stored cursor only
  inside the committed page transaction (locked order item 5) — failure stores no cursor.
- One-based → zero-based mapping happens at the gateway DTO boundary (Task 1); the
  ingestor passes DTOs through and never touches page indexes; `work_id` is computed
  only at the view boundary (`schema.sql:175-183`) — the ingestor never computes it.
- No subtitle/playback/audio/ASR/export calls: ingestor touches only the four protocol
  methods (`metadata_ingest.py:224-240, 335`).
- Bounded scalar codes only: page/run rows carry `error.code` from the validated taxonomy
  (`sources/models.py:111-159`); `GatewayShapeError(detail=...)` raised ingestor-side
  persists only `"shape_error"` — detail text stays process-local.
- SESSDATA: no credential surface exists in the ingestor at all — nothing to
  serialize/log/return.
- Current display labels only: `upsert_user`/`upsert_video`/`upsert_part` are
  current-state upserts; no history table, no full upstream documents persisted
  (`database.py:166-257`).
- No network in fake-gateway tests: `FakeGateway` is a plain scripted double (no
  `bilibili_api` import, no network; unexpected fetches raise `AssertionError`);
  storage is local SQLite (`tmp_root` / `:memory:`).

**Prior-task invariants (Task 1, PM-adjudicated) honored:**

- **D1** ✅ — `get_completed_video_summary` called exactly when `summary.aid is None`
  (`metadata_ingest.py:331-333`); zero speculative completion calls asserted
  (`test_missing_aid_is_completed_through_the_gateway_without_speculation`:
  `completion_calls == ["BV1NEEDS"]` with an aid-carrying summary present).
- **D3 (ingestor-side)** ✅ — `_completed_summary` rejects `summary.mid != mid` with
  `GatewayShapeError` before the parts loop (`metadata_ingest.py:330-332`); the
  foreign-owner test asserts zero `get_video_parts` calls and zero completion calls.
- **Plan-1 canonical forms** ✅ — single `finish_run(record)` form
  (`metadata_ingest.py:293-307`); single `videos=` param in locked order
  (`database.py:348-356`); failed page + payloads rejected `ValueError`
  (`database.py:396-397`); failure path = no-payload `record_page` in a separate
  transaction; `database.py` unmodified (verified: no hunks in diff).

**Implementer decisions — implementation matches all five PM dispositions**
(D3 ingestor-side; D1-exactly-when-absent; `display_name = str(mid)` helper isolated at
`metadata_ingest.py:95-105`; outcome mapping incl. byte-for-byte cursor equality at
`test_gateway_failure_...` and `test_rate_limited_...`; count semantics mirroring
`v_ingestion_run_stats` — confirmed against `schema.sql:161-173`: `page_count =
COUNT(DISTINCT ip.page_number)` includes interrupted/failed page rows, `video_count =
COUNT(DISTINCT id.bvid)`; `part_count` has no view equivalent and is documented as
upsert coverage, `metadata_ingest.py:138-157`).

## Strengths

- **Failure safety is structural, not incidental.** Gateway fetches complete before any
  page transaction opens, so "a failed page cannot advance the cursor" holds by
  construction; the scalar-only persistence rule then rides Plan-1's guarded
  `_record_failed_page` instead of ad-hoc write paths.
- **Faithful composition over duplication.** The ingestor opens no competing
  transaction; the locked ordering, terminal-run guards, and atomic commit semantics all
  come from the Plan-1 repository unchanged — and the zero-diff on `database.py` is the
  right call (no genuine gap existed; the brief's "Modify" was conditional).
- **Honest outcome semantics.** `limited` never masquerades as `complete`, and the
  empty-page-at-limit edge is pinned by a dedicated test instead of left to convention.
- **Negative-shape assertions.** The D3 test asserts the *absence* of downstream calls
  (zero parts, zero completion fetches) — behavior-level verification, not
  implementation-mirroring.
- **Cross-layer consistency.** Counts, outcome literals, and cursor states were checked
  against `storage/models.py` Literals and `schema.sql` views — every persisted value
  the ingestor produces is a valid repository contract value.
- **Test realism.** Tests drive a real Plan-1 repository over temporary SQLite and read
  back normalized rows (`work_id` only from the view), not fake echoes.

## Issues

### Critical

None.

### Important

None.

### Minor

1. **Unused imports** — `UserVideoPage` imported but never referenced in
   `metadata_ingest.py:29`; `GatewayShapeError` imported but never referenced in
   `tests/test_metadata_ingest.py:23` (the foreign-owner test asserts the persisted
   `error_code` string, not the exception). Lint-level; no behavior impact.
2. **Dead parameter + misleading docstring in the test `_page` helper**
   (`tests/test_metadata_ingest.py:84-92`) — `owner_mid` is accepted and folded into a
   local `mid` that is never used; the built `UserVideoPage` always carries `mid=MID`.
   The docstring ("owner_mid overrides the requested mid") describes behavior the helper
   does not have (the override actually happens in `_summary(..., owner_mid=...)`).
   Related lint-level nit: locals `first` in `test_gateway_failure_...` and
   `test_rate_limited_...` are assigned but never read.
3. **Report arithmetic inaccuracy (report-only)** — the report's "17 passed (16
   functional + 8 validation params inside 2 test items)" does not add up; the actual
   composition is 9 functional tests + 8 parametrized validation cases = 17 items (I
   re-ran the focused suite: 17 passed). Code and coverage are correct; only the
   parenthetical is wrong.
4. **Dangling `running`-run windows (disclosed design limits; PM disposition)** —
   (a) a non-gateway exception raised after `start_run` (e.g. a repository write error
   mid-page) propagates by design and leaves the run row `outcome='running'` with no
   terminal transition; (b) the `risk_interrupted` finish spans two transactions (page
   row commit, then `finish_run`), so a crash in between leaves the run `running`. Both
   are inherent to the Plan-1 commit matrix, leave SQLite consistent and resumable, and
   are documented in the report's known-limits — reported here per zero-residual
   discipline so PM can disposition (accept as bounded / track as residual / fold into
   Task 3 CLI hardening).
5. **Unpinned idempotency flavor (optional strengthening)** — within-page duplicate
   summaries, per-run evidence, and resume behavior are all pinned, but no test drives
   the same bvid discovered on two *pages* of one run (or re-discovered across runs) to
   show cross-page/cross-run discovery evidence alongside a single entity row. The
   behavior is structurally idempotent (same upsert keys, per-run discovery PK), so this
   is coverage polish for plan QC, not a defect.

## ⚠️ Cannot verify from diff (for PM to check)

- **Full-suite and neighbor-suite claims**: "840 passed" full offline suite and "147
  passed" neighbors are implementer-reported; I did not re-run them per assignment
  instructions. The focused file's 17-passed claim was independently confirmed.
- **Commit subject** `feat(services): add resumable normalized metadata ingestor` and
  `git status` cleanliness are not carried in the diff file; not verifiable here.
- **Spec §Acceptance evidence live smoke** (one-page run for UID 23191782 against a
  temporary database) is Task 3's deliverable per the plan — confirm it is tracked there
  before plan-level QC.

## Assessment

**Task quality:** Approved

Spec-first check is clean: every brief item, every global constraint, and both
carried-over Task-1 invariants are implemented as adjudicated, with the repository's
locked transaction order and failure guards doing exactly the work the plan assigned to
them. Findings are Minor and lint/report-level; no fix loop is required before Task 3.
(Zero-residual: PM owns disposition of Minor items 4 and the ⚠️ list above.)
