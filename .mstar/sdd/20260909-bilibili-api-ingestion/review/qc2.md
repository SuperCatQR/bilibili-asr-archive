---
report_kind: qc
reviewer: qc-specialist-2
reviewer_index: 2
plan_id: "20260909-bilibili-api-ingestion"
verdict: "Request Changes"
generated_at: "2026-09-10"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist-2
- Runtime Agent ID: qc-specialist-2
- Runtime Model: deepseek (DSH delegated subagent, standard tier)
- Review Perspective: QC seat 2 of 3 — security / correctness / bounds / real-entry-path; whole-branch plan QC (L3), cross-task boundary and transaction semantics
- Report Timestamp: 2026-09-10

## Scope
- plan_id: 20260909-bilibili-api-ingestion
- Review range / Diff basis: `e62280a..783986a` (merge-base `e62280a` with spec integration branch `iteration/iter-2026-09-bilibili-api-sqlite`)
- Working branch (verified): `feature/20260909-bilibili-api-ingestion`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260909-bilibili-api-ingestion` (branch `feature/20260909-bilibili-api-ingestion`, HEAD `783986a` — contains all 4 commits in scope: `dfb66ba`, `0c2c379`, `6359e7d`, `783986a`)
- Files reviewed: 10 (`pyproject.toml`, `src/bili_asr/services/__init__.py`, `src/bili_asr/services/metadata_ingest.py`, `src/bili_asr/sources/__init__.py`, `src/bili_asr/sources/bilibili_api_gateway.py`, `src/bili_asr/sources/models.py`, `tests/fixtures/fake_bilibili_gateway.py`, `tests/test_bilibili_api_gateway.py`, `tests/test_metadata_ingest.py`, `uv.lock`), plus read-through of unchanged Plan-1 composition targets (`src/bili_asr/storage/database.py`, `storage/models.py`, `storage/schema.sql`) and both iteration specs
- Commit range (if not identical to Review range line, explain): `e62280a..783986a` — identical to Assignment; `git diff --stat` reproduces 10 files, +5700
- Analysis methods: git-diff, read, grep, deep-lens (no test/build/lint runs; `git diff --check` was run read-only to confirm a plan acceptance criterion)
- Deep review: triggered (S1: 5,700 insertions / 10 files ≥ thresholds; S3: new `sources/` + `services/` modules absent from `{KNOWLEDGE_DIR}`; S6: diff spans ≥3 module boundaries — sources/, services/, tests/, packaging/lock)
- Lenses applied: Security Lens, Correctness Lens, Bounds Lens, Real-Entry-Path Lens, Testing Lens, Standards Lens
- Inputs used: branch-diff.md (authoritative diff), plan, primary spec `bilibili-api-gateway.md`, companion spec `structured-metadata-storage.md`, task-1/2/3-review.md, implementer-task-1/2/3-report.md, progress.md (D1–D3 adjudications)

## Findings

### 🔴 Critical

None. No injection, credential-leak, or data-consistency path was found in the change: SESSDATA is consumed only by the package `Credential` object (`bilibili_api_gateway.py:243-251`), persisted failure state is bounded through Plan-1's `validate_error_code` (`sources/models.py:121-129`, `storage/models.py:26,47-54,258`), and the import boundary holds (grep over `src/`: only `sources/bilibili_api_gateway.py` imports `bilibili_api`; the AST tests at `test_bilibili_api_gateway.py:715-748` pin it durably).

### 🟡 Warning

- [QC2-W-001] The bounded-failure contract is leakable from inside the adapter itself: a summary whose `bvid` passes the adapter's own page normalization (any non-empty string) but not the BVID format check raises a **raw `ValueError` out of `get_video_parts`, before `_await_upstream`**, which the ingestor does not catch (it catches only `GatewayError`) — the upstream shape defect then propagates unbounded, leaves the run row stuck `outcome='running'` forever with zero page/run-failure evidence, and contradicts the plan Global Constraint "Translate upstream failures into bounded scalar error codes." -> Fix: enforce the BVID shape at summary normalization (`_normalize_video_summary_item`), e.g. reject with `GatewayShapeError` when `_BVID_PATTERN.fullmatch(bvid) is None`; every downstream path (completion, parts) then ends in the bounded taxonomy and the failed-page machinery (`_record_failed_page`) finishes the run atomically.
  - Source Type: deep-lens: Correctness Lens (cross-task boundary: adapter ↔ ingestor)
  - Verification: diff/read anchor — `bilibili_api_gateway.py:123-125` (summary normalization checks only non-empty bvid, not the BV pattern), `bilibili_api_gateway.py:272-273` (`get_video_parts` raises `ValueError("bvid must be a BV-prefixed 10-character id")` *before* the `_await_upstream` try block), `metadata_ingest.py:224-241` (`except GatewayError` only), `metadata_ingest.py:293-307` (`finish_run` skipped only for `failed`, so a non-gateway escape leaves the run `running`). Note the asymmetry is in the adapter itself: a malformed bvid on a summary **without** `aid` reaches `get_info` *inside* `_await_upstream` (`bilibili_api_gateway.py:291-294`) and is bounded (`response_error`/`transport_error`), while the identical defect on an aid-carrying summary escapes as caller-argument `ValueError`.
  - Expected vs observed: expected — any upstream response defect that the ingestor feeds back into the gateway is translated into a bounded scalar code and terminal run evidence (`failed`/`shape_error`, prior cursor intact); observed — aid-present + malformed upstream `bvid` produces an uncaught `ValueError`, a permanently `running` run row, no page row, and no `IngestionRunResult`. This is an instance of the L2-disclosed dangling-`running` window class (task-2-review Minor 4a: "a non-gateway exception raised after `start_run`"), but the disclosed rationale ("caller-argument violations … programming or contract errors", implementer-task-2-report decision 4) does not fit this trigger: the caller passed valid arguments — the malformed value originated **upstream** and passed the adapter's own page normalization. Trigger likelihood is low (real Bilibili `bvid`s are `BV`+10), so this is a tightening, not a defect seen in normal traffic. Offline ingestor tests cannot hit it: `FakeGateway.get_video_parts` performs no BVID validation, and the end-to-end seam tests use well-formed `BV1…` ids (`test_metadata_ingest.py:530-588`).
  - Confidence: Medium (mechanism verified by reading; real-world trigger requires anomalous upstream data)

### 🟢 Suggestion

- [QC2-S-001] Duplicate aid-less summaries are completed more than once: the completion list-comprehension runs over every `page.videos` entry, so a duplicated entry with `aid=None` triggers a second `get_completed_video_summary` (upstream `get_info`) for the same bvid. The ingestor already applies the stated dedup principle to parts fetches (`metadata_ingest.py:232-241` comment: "a duplicated page entry is the same video, so the identical fetch would only repeat upstream work") but not to completions. -> Dedup completions per distinct bvid alongside the parts map; behavior is otherwise idempotent and bounded (≤ page_size extra calls).
  - Source Type: deep-lens: Correctness Lens (reuse/dedup consistency)
  - Verification: diff/read anchor — `metadata_ingest.py:228-240` (completion over `page.videos` as-is; dedup only in the parts loop).
  - Expected vs observed: expected — one detail fetch per distinct video per page, per the module's own comment; observed — one per duplicate entry. Unpinned by tests (`test_duplicate_summaries_in_one_page_collapse_into_single_rows` uses an aid-carrying duplicate). Confidence: High (mechanism), low impact.
- [QC2-S-002] Within-page duplicate summaries collapse the discovery row to the **last** `source_position`: the PK `(run_id, page_number, bvid)` upsert (`database.py:456-472`) overwrites `source_position` with each subsequent duplicate occurrence, so the persisted position is the second (later) hit, not the first. No test pins which occurrence wins. -> Pin the chosen semantics with one assertion (or keep first-wins if the view consumers prefer the original position); either is fine — the gap is that the flavor is unpinned.
  - Source Type: deep-lens: Testing Lens (extends L2 task-2 Minor 5 to the within-page flavor)
  - Verification: diff/read anchor — `metadata_ingest.py:419-428` (enumerate over `summaries`, duplicates included) vs `database.py:456-472` (`DO UPDATE SET source_position = excluded.source_position`); `test_metadata_ingest.py:218-248` asserts only `COUNT(*) == 1`.
  - Expected vs observed: expected — an explicit, tested choice of first-vs-last position; observed — last-wins behavior, untested. Confidence: High (mechanism).
- [QC2-S-003] The Plan-1 cursor state `risk_interrupted` (`storage/models.py:18,25`, `schema.sql:59`) is never written by the ingestor: on a rate-limit interruption the run/page rows carry the bounded risk signal while the cursor row stays byte-for-byte untouched (`metadata_ingest.py:241-256` — no cursor argument on the failure path). This is a documented decision (implementer-task-2-report item 5: "preserve the previous cursor"; one-branch change if PM wants the cursor to mark risk pauses) and is spec-compliant with the gateway spec's "preserve the previous cursor on gateway failure" — but Plan 3's CLI reads cursor state for resume behavior, and a `ready`-state cursor after a rate-limit interruption invites an immediate blind auto-retry against a throttled upstream. -> PM/Plan-3 decision: either accept (run/page rows are the evidence SSOT, cursor stays resumable) or flip cursor `state='risk_interrupted'` on the rate-limit path before Plan 3 builds resume logic on it.
  - Source Type: deep-lens: Correctness Lens (cross-plan contract semantics; disclosed decision reported for disposition)
  - Verification: diff/read anchor — `metadata_ingest.py:241-256, 293-307` vs unused enum member `storage/models.py:18` + `schema.sql:58-60`; implementer-task-2-report.md item 5.
  - Expected vs observed: expected — cursor risk semantics consistent across Plans 1–3; observed — the enum value exists but has no producer in this branch. Confidence: High (unused-ness verified); semantics judgment deferred to PM.
- [QC2-S-004] Lint hygiene (recurring pattern across tasks — flagged by L2 on Tasks 2 and 3): dead imports `sqlite3` and `GatewayShapeError` in `tests/test_metadata_ingest.py:17,29`, `FakeApiException` in `tests/test_bilibili_api_gateway.py:47`, and `UserVideoPage` in `services/metadata_ingest.py:29`. Zero behavior impact; fold into the next fix dispatch if one opens on this branch (echo of task-2-review Minor 1 and task-3-review Minor 1/2 — recurring cross-task pattern).
  - Source Type: read
  - Verification: grep anchors — `tests/test_metadata_ingest.py:17,29`, `tests/test_bilibili_api_gateway.py:47`, `metadata_ingest.py:29` (import sites with no further references).
  - Expected vs observed: expected — imports match references; observed — four import-only names at HEAD. Confidence: High.
- [QC2-S-005] `_complete_summary_from_detail` validates the detail's owner `mid` but never cross-checks `detail["bvid"] == summary.bvid`, so the aid is trusted from any same-owner detail body rather than the identity-matched one. Spec requires only the owner check (implemented), so this is an identity-anchor tightening, not a spec violation. -> Add the one-line bvid equality check when filling `aid`.
  - Source Type: deep-lens: Security Lens (untrusted upstream data into identity fields)
  - Verification: diff/read anchor — `bilibili_api_gateway.py:206-237` (owner-mid check at 221-230; no bvid comparison; only `aid` is consumed).
  - Expected vs observed: expected — the filled `aid` provably belongs to the same video the summary names; observed — same-owner assumption only. Confidence: High (mechanism), speculative trigger.
- [QC2-S-006] Dangling-`running`-run windows (L2 task-2 Minor 4, disclosed; disposition requested at plan QC): (a) a non-gateway exception after `start_run` (e.g. a repository write error mid-page) leaves the run `running` with no terminal transition; (b) the `risk_interrupted` finish spans two transactions (no-payload page row commit at `metadata_ingest.py:243-252`, then `finish_run` at 293-307), so a crash between them leaves a `running` ghost; (c) likewise the window between the last `record_page` and `finish_run` for `complete`/`limited`. SQLite state stays consistent and resumable in all three. -> Recommendation to PM: accept (a)/(b)/(c) as bounded design limits inherent to the Plan-1 commit matrix (each leaves honest, resumable evidence; `finish_run` rejects double-finish so no outcome regression), and consider a Plan-3 CLI sweep that transitions stale `running` runs of dead processes to a terminal outcome — QC2-W-001's upstream-data path is the only instance of this class this seat judges worth a code fix.
  - Source Type: manual-reasoning (cross-task; echo of L2 disclosure for tri disposition)
  - Verification: diff/read anchor — `metadata_ingest.py:199-317` (transaction boundaries), `database.py:290-324` (`finish_run` single-write commit), `database.py:420-450` (`_record_failed_page` atomic failure transition).
  - Expected vs observed: expected — every started run reaches a terminal outcome or is explicitly known-unreliable; observed — three narrow windows where `outcome='running'` persists indefinitely. Confidence: High (windows exist; harm bounded).

### ⚪ Unconfirmed

- Full-suite and neighbor counts ("848 passed, 1 skipped" full offline suite; "147 passed" neighbors; per-task focused counts) are implementer-reported; task-2/task-3 L2 reviewers independently re-ran only the sanctioned focused pairs (17 passed; 122 passed + 1 skipped). Full-suite re-run belongs to the mandatory QA gate. — channel gap: L3 QC does not run suites.
- `uv.lock` reproducibility (`uv lock --check` no-op) is implementer-reported (task-1 report; progress.md defers to QA). Static verification done here: `uv.lock` is a new file in this range, pins `bilibili-api-python` `version = "17.4.2"` from `registry = "https://pypi.org/simple"` (`uv.lock:113-115`), declares no `{ file = … }`/`{ path = … }`/editable local sources, and `pyproject.toml` adds exactly one dependency line. — channel gap: lock re-resolution is a runtime check for QA.
- The opt-in live smoke (`test_live_smoke_single_public_page_for_archive_owner`, `BILI_LIVE_SMOKE=1`, UID 23191782, one page, temporary SQLite, no credential) was **not executed** — by policy it is never run during QC; Plan 3 / the mandatory QA gate owns the real-network run. Static review confirms the bounds in code: `page_limit=1`, `start_page=1` (`test_bilibili_api_gateway.py:885-887`), loud-fail guard on a missing pinned dist (commit `783986a`, `test_bilibili_api_gateway.py:872-879`), default `pytest.skip` otherwise. — channel gap: live execution is Plan-3/QA-owned.
- Real-wheel upstream response-shape assumptions (inner arc/search `list.vlist`/`page.count` shape; `Video.get_pages` making no internal `get_info`) mirror implementer wheel-inspection claims; the offline fake seam reproduces the assumed surface by construction, so the diff alone cannot confirm them. Failure mode is a bounded `GatewayShapeError`, surfacing in the Task-3 live smoke once run. — channel gap: requires the real package against the live API (Plan 3 / QA).

## Source Trace
- Finding ID: QC2-W-001
- Source Type: deep-lens: Correctness Lens
- Source Reference: `src/bili_asr/sources/bilibili_api_gateway.py:123-125, 269-278`; `src/bili_asr/services/metadata_ingest.py:224-241, 293-307`; `tests/test_metadata_ingest.py:530-588`
- Confidence: Medium
- Note: every finding carries `Verification` + `Expected vs observed` in its Findings entry (per report-template.md). No finding rests on a test/build run; `git diff --check e62280a..783986a` (read-only) exits 0, corroborating the implementer/L2 claims of whitespace cleanliness.

## Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 1 |
| 🟢 Suggestion | 6 |
| ⚪ Unconfirmed | 4 |

### Acceptance / Done criteria — diff evidence vs QA gate

| Plan criterion | Status from this diff |
|---|---|
| Pin `bilibili-api-python==17.4.2`, reproducible `uv.lock` | Evidenced statically (pyproject pin; lock entry `version = "17.4.2"`, PyPI source, no path deps, new-file additions only); **reproducibility itself → QA `uv lock --check` (⚪)** |
| Only `sources/bilibili_api_gateway.py` imports `bilibili_api` | Evidenced: grep over `src/` + AST tests `test_bilibili_api_gateway.py:715-748` scanning all of `src/bili_asr` |
| DTOs validate required fields, reject malformed responses | Evidenced: DTO `__post_init__` validation + adapter normalization + malformed-item parametrized tests |
| Idempotent normalized entities + discoveries, per-run evidence | Evidenced: `ON CONFLICT` upserts (Plan-1, unmodified) + tests 1–4/6 of `test_metadata_ingest.py` |
| Cursor advances only after page transaction commits; failed pages leave prior cursor | Evidenced: locked-order `record_page` composition + byte-for-byte `CursorRecord` equality tests (failure and rate-limit paths) |
| Bounded failure records (scalar codes only; no credentials/URLs/JSON/stack traces) | Evidenced: sentinel scans over all persisted rows, run result, and logs; `_await_upstream` message construction |
| Offline tests pass on Python 3.12 without network | Construction-level evidence (fake seam installs `bilibili_api` on `sys.modules`; no HTTP in offline tests); **green counts implementer-reported → QA re-run (⚪)** |
| Opt-in live smoke bounded (one page, UID 23191782, temp DB, no subtitle/playback/audio/ASR) | Code bounds evidenced (single page, `tmp_root` temp SQLite, hygiene tokens); **live execution not performed → Plan 3 / QA (⚪)** |
| `git diff --check` clean | Verified by this review (exit 0 on the range) |

### Cross-task / disposition notes for PM (zero-residual policy)

- **D1–D3 carried invariants verified independently**: D1 non-speculative `get_info` (short-circuit + `completion_calls == ["BV1NEEDS"]` test), D2 canonical codes matching the spec taxonomy verbatim, D3 transitive ownership enforced ingestor-side before any parts/detail fetch and pinned end-to-end at the seam (`test_bilibili_api_gateway_foreign_owner_page_requests_no_parts`: exactly one `user.get_videos`, zero rows, no cursor). All hold on the whole-branch diff.
- **Storage unmodified confirmed**: `git diff e62280a..783986a -- src/bili_asr/storage/` is empty; the ingestor composes Plan-1 canonical `record_page`/`start_run`/`finish_run` forms in the locked order (user → videos → parts → discoveries → cursor → page outcome → commit), and the plan's Task-2 "Modify: storage/database.py" line was correctly a no-op (no genuine gap).
- **Outcome honesty verified**: `limited` never claimed as `complete` (cursor state `limited`, dedicated test); empty-page-at-limit completes honestly (pinned); `GatewayRateLimited → risk_interrupted`, others → `failed` (matching the assignment's mapping); failed runs finish atomically inside `record_page`; non-failed runs finish via `finish_run` with a fresh record built from the run's resolved bounds.
- **STOP conditions**: none triggered. One-page metadata exists without playback/subtitle imports; no raw JSON retention; no signed URL/credential needed for resumption; pagination bounded by the cursor contract.
- **Severity disposition is PM's**: QC2-W-001 is the only change-request item this seat raises; QC2-S-001…S-006 are accept-or-strengthen items; the ⚪ list is the QA-gate channel (full suite, `uv lock --check`, live smoke execution, wheel-shape claims). Disposition of this report's findings must not be performed by QC.

**Verdict**: Request Changes

Rationale: Critical = 0, but one unresolved Warning (QC2-W-001 — an upstream-data path that escapes the bounded failure taxonomy and leaves a permanently `running` run with no evidence, violating the plan's bounded-failure Global Constraint on a path the adapter itself creates). The fix is one line (BVID shape check at summary normalization). All other findings are Suggestions or QA-channel items; the branch is otherwise spec-compliant across all three tasks.

## Revalidation

### Scope & method

- Targeted re-review (L3) of the QC fix wave: range `783986a..3dcc51b` (commit `3dcc51b` `fix(sources): enforce BVID shape at summary normalization (plan QC fix wave)`, 4 files, +278/−30) on top of this report's originally reviewed head `783986a`; N=2 targeted seats (`qc-specialist`, `qc-specialist-2`) per the consolidated gate (review/qc-consolidated.md, gate **Request Changes**). Revalidation date: 2026-09-10.
- Compliance: review-only against `/root/workspace/bilibili-asr-archive/.worktrees/20260909-bilibili-api-ingestion`; no git re-run, no checkout/commit, no tests/builds/lints. Evidence = the PM diff pack `review/fix-1-diff.md` (read once) plus read-only `read`/`grep` verification of the files it touches at the fix head.
- Inputs: this report (initial wave), review/qc-consolidated.md, implementer-qc-fix-1-report.md (claims treated as unverified until diff-checked — every accepted claim below was re-derived from the diff or the post-fix source), fix-1-diff.md, and post-fix reads of `src/bili_asr/sources/bilibili_api_gateway.py`, `src/bili_asr/services/metadata_ingest.py`, `src/bili_asr/storage/database.py` (Plan-1 upserts, read-only), both test modules, and the fixture factories (`tests/fixtures/fake_bilibili_gateway.py`).

### W-001 (Warning) — **RESOLVED**

Verified from the diff and the post-fix source (current-file anchors):

1. `_BVID_PATTERN = r"^BV[a-zA-Z0-9]{10}$"` (`bilibili_api_gateway.py:52`) is now enforced at summary normalization (`:122-124`: `_BVID_PATTERN.fullmatch(bvid) is None → GatewayShapeError(detail="video item has no valid bvid")`), replacing the non-empty-only check; the message wording stays honest for the malformed case.
2. Boundary equivalence, not merely tightening: `get_video_parts`' caller-argument check (`:274-275`) is the *identical* `_BVID_PATTERN.fullmatch` expression, so no bvid that passes the page boundary can any longer reach the parts `ValueError` — the asymmetry is closed in both directions. This additionally covers whitespace-padded bvids, which the old `bvid.strip()` check accepted and which would previously have escaped unbounded at parts.
3. Position is right: normalization runs per-item inside `_normalize_user_video_page` (`:150-152`), after `_await_upstream` returns and before the ingestor's completion/parts loops (`metadata_ingest.py:227-246`); `GatewayShapeError` ⊂ `GatewayError` is caught by the ingestor (`metadata_ingest.py:247`), mapped `failed`/`failed` (`:55-66`), and the run finishes atomically inside `record_page` (`:249-262`; `finish_run` correctly skipped for `failed`, `:299-313`). No dangling `running`; page row, terminal run row, and `IngestionRunResult` all present.
4. Classification no longer depends on aid presence: the check precedes `_read_optional_aid` (`:137`) and every aid-based branch; both aid flavors are pinned at the adapter boundary (`test_bilibili_api_gateway.py≈:331-361`, parametrized `("BV1SHORT", 111) / ("BV1SHORT", None) / ("av170001", 111)` — asserts `shape_error`, "bvid" in the bounded message, exactly one upstream call) and end-to-end at the seam (`test_metadata_ingest.py:858-919`, ids `aid-carrying`/`aid-less`).
5. End-to-end pin completeness (all consolidated prescription items): run `failed`/`shape_error`; page row `(2, "failed", "shape_error")`; terminal run row with `finished_at`; prior cursor preserved byte-for-byte (`CursorRecord` field-wise equality, `:895`); zero payload rows beyond page 1; malformed id never reaching parts/detail (`script.calls == calls_after_first + ["user.get_videos(pn=2, ps=100)"]`, `:917` — the only post-page-1 upstream call is the page-2 fetch).
6. Caller-argument contract unchanged: `get_video_parts`' raw `ValueError` remains for genuine caller arguments (documented in the `collect_user_pages` docstring, `metadata_ingest.py:160-163`); post-W1 the ingestor can no longer route an upstream-shaped malformed bvid into that path — the implementer's Batch-3 readiness note is verified by reading.

### Suggestion dispositions — all six match the consolidated table

| QC2 ID | Consolidated | Disposition | Re-validation evidence |
|---|---|---|---|
| S-001 (dedup completions) | S-fix-3, fix now | Resolved | `completed_by_video` map keyed by bvid (`metadata_ingest.py:227-237`); `summaries` keeps one entry per page item (`:237` unconditional append) so discovery enumeration/upserts are untouched; test `test_duplicate_aid_less_summaries_trigger_one_completion_call` (`≈:583-614`) pins `completion_calls == ["BV1DUPLICATE"]`, stored aid 555, one parts fetch. Flavor footnote below. |
| S-002 (pin duplicate flavor) | S-fix-5, fix now | Resolved | Last-wins flavor documented in `_record_collected_page` docstring (`:391-400`) and pinned by `test_within_page_duplicate_discovery_keeps_the_last_source_position` (`≈:247-283`, interleaved positions → `{"BV1DUPPOS": 2, "BV1INTERVAL": 1}`) against the Plan-1 `DO UPDATE SET source_position` upsert (`database.py:458-461`). |
| S-003 (`risk_interrupted` producer) | C3, carry | Carried to Batch 3 — matches | Consolidated C3 verbatim: no cursor producer in this branch (spec-compliant); Plan-3 CLI resume logic must not depend on the cursor state; accept-vs-flip decided there. No code expected in this plan — consistent with my original framing. |
| S-004 (dead imports) | S-fix-1, fix now | Resolved | `sqlite3` + `GatewayShapeError` gone from `tests/test_metadata_ingest.py` (grep-verified); `FakeApiException` gone from `tests/test_bilibili_api_gateway.py` (the fixture keeps the class live as the base/registration of the other fake exceptions — import-only removal, correct); `UserVideoPage` gone from `metadata_ingest.py` (still legitimately used by the test `_page` helper, `:29,62,65`). Recurring pattern swept: `_page`'s dead `owner_mid` param + `mid` local + misleading docstring fixed (`owner_mid` survives only on `_summary` for the D3 test, `:523`); both dead `first` locals removed with the two live uses retained. |
| S-005 (detail bvid anchor) | S-fix-4, fix now | Resolved | Identity anchor `detail_bvid != summary.bvid → GatewayShapeError` after the owner-mid check (`bilibili_api_gateway.py:230-232`); a missing or non-string detail bvid is also rejected; test `test_completed_summary_rejects_detail_for_another_video` (`≈:596-612`). Note: this adds a real-wheel dependency on `detail["bvid"]` presence — folded into the pre-dispositioned ⚪ U4 routing (same owner: wheel inspection / live smoke). |
| S-006 (dangling-`running` windows) | accepted design limits + C2/C5 carries | Accepted — matches | Consolidated accepts windows (a)/(b)/(c) with Batch-3 carries C2 (Plan-3 stale-run sweep) and C5 (non-gateway exit mapping); W-001 was the single instance of the class this seat judged code-worthy and is now fixed. Consistent with my original accept recommendation. |

### Regression lens on the fix diff — sound

- **Surgical scope**: only the 4 disclosed files; `storage/`, `pyproject.toml`, `uv.lock` untouched (4-file diff, matches +278/−30). Plan-1 canonical `record_page` composition and the cursor contract are unchanged (`metadata_ingest.py:344-460` re-read).
- **Live smoke**: untouched and still opt-in (`test_bilibili_api_gateway.py:893-968`; no fix hunk reaches it) — default runs skip it.
- **Disclosed seam-test adjustments verified sound**: both adjusted tests' page items and detail bodies now name the same video (`BV1SEAMRUNAA`, `test_metadata_ingest.py:656-662`; `BV1SEAMLEAKS`, `:719-735`), preserving each test's original intent (normalized rows / no-leak sentinel scanned over really-persisted data, `:746`). The pre-fix code genuinely accepted a cross-video detail there, which S-fix-4 now correctly rejects — the fixture alignment is the minimal honest adjustment. All other seam tests use the shared default bvid on both sides (`BVID = "BV1AbCdEfGhJ"`, fixture `:36`) or are aid-carrying (no detail call) — unaffected.
- **S-fix-2 removal verified safe**: the wrapped lambdas call only package objects (all normalization happens outside `_await_upstream`); the error-mapping parametrizations script only package-family fakes + bare `RuntimeError` (`test_bilibili_api_gateway.py:459-537`; grep confirms no application `GatewayError` is ever scripted into `videos_error`/`parts_error`/`info_error`), so the deleted `except GatewayError: raise` was unreachable and no tested classification changes; the `Exception → transport_error` fallback remains pinned (`:475, 499, 522`). The AST import-boundary tests are unaffected (`GatewayError` was a `bili_asr.sources.models` import, not `bilibili_api`).
- **Offline-only intact**: no new network surface; no networked test added; seam-construction unchanged.
- **Flavor footnote (no action, recorded for honesty)**: via the completion dedup, within-page duplicates are now completed through the *first* entry's summary, so in the pathological case of two entries sharing a bvid while diverging in other fields, entity-field flavor flips from last-wins to first-wins (`videos` upsert `title = excluded.title`, `database.py:195-198`; aid stays sticky via `COALESCE(videos.aid, excluded.aid)`). The implementer's "entity upsert behavior unchanged" claim is exact for identical duplicates and inexact only in this upstream-contradiction case; discovery `source_position` remains last-wins and is pinned (S-fix-5). Consistent with the module's own "a duplicated page entry is the same video" semantics; no plan criterion affected; no new finding raised.

### Updated severity counts

| Severity | Initial wave | Revalidation |
|----------|--------------|--------------|
| 🔴 Critical | 0 | 0 |
| 🟡 Warning | 1 (QC2-W-001) | 0 (resolved) |
| 🟢 Suggestion | 6 | 0 open — S-001/S-002/S-004/S-005 fixed with tests; S-003 carried to Batch 3 (C3); S-006 accepted as bounded design limits (C2/C5 carries); 1 no-action flavor footnote recorded in the regression lens |
| ⚪ Unconfirmed | 4 | 4 — unchanged, QA-gate routed. U1/U2 counts refreshed to the post-fix baseline (focused **131 passed + 1 skipped**, full **857 passed + 1 skipped** — implementer-reported; QA re-runs both). U4's surface is extended by S-fix-4's `detail["bvid"]` real-wheel dependency (same pre-dispositioned routing). |

### Verdict (updated): **Approve**

Rationale: the single Warning is resolved and verified from the diff and the post-fix source — the bounded-failure contract is now symmetric on both aid paths with exactly the evidence pins the consolidated fix prescription required; all six of this seat's suggestions land precisely as dispositioned in the consolidated table (zero-residual); the fix diff is surgical (4 files, storage/packaging untouched); the two disclosed test adjustments are the minimal honest ones; and the regression lens found no defect (one no-action flavor footnote recorded above). The four ⚪ items remain the PM-pre-dispositioned runtime-evidence routings owned by the immediate mandatory QA gate — per the consolidated verdict math, plan-level Approve still requires that gate to close U1–U4 (full-suite re-run at the post-fix baseline, `uv lock --check`, live smoke execution, wheel-shape inspection now including `get_info`'s `bvid` field). This seat's re-review channels are fully intact and unblocked; the original frontmatter verdict above records the initial wave and is superseded by this section for the fix wave.
