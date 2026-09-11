# QA Report (L4 Acceptance Gate) — 20260911-subtitle-gateway

- Iteration: `iter-2026-09-subtitle-transcript-sqlite` · Plan: `20260911-subtitle-gateway`
- Seat: `qa-engineer` (L4 acceptance) · Delegation: forbidden · QA gate: mandatory · QA mode: acceptance-only + routed runtime items
- Review cwd: `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-gateway`
- Working branch: `feature/20260911-subtitle-gateway` · HEAD `9322239` · worktree base `2bd333f` (iteration integration branch)
- Diff basis verified: `2bd333f..9322239` (7 files, +3362/−59)
- QC input: `review/qc-consolidated.md` (FINAL GATE DECISION **Approve**; range `2bd333f..6002f99` + revalidated fix wave `6002f99..9322239`)
- **Verdict: Approve — recommend merge into `iteration/iter-2026-09-subtitle-transcript-sqlite`.**
  Plan `Done` is **not** marked here (merge precedes Done; PM owns it).

## Scope tested

1. Checkout alignment against the locked QC tri-review pack (read-only git probes).
2. Full offline suite at HEAD, from the worktree package dir.
3. The plan's core acceptance: the opt-in **live subtitle probe** at HEAD, recording `part_source` and `sessdata=present|absent` plus bounded facts.
4. The QC-routed runtime items: AST import-boundary + no-leak scans green; the offline **discriminating** `floor` row; independent confirmation of "no archive DB on this host"; the two deferred obligations (F3, R1) owned elsewhere; residual register shape.
5. DoD mapping over the plan's `## Acceptance / Done Criteria`, splitting fresh-run evidence from reused L1/L2/L3 evidence.

Not in scope (assignment): no `floor` proof from raw subtitle JSON (forbidden by the plan's Global Constraints), no anonymous-tier re-run without the credential, no fabricated archive to exercise the archive-db branch.

## Findings

| ID | Finding | Severity | Effect on verdict |
|----|---------|----------|-------------------|
| O1 | `review/branch-diff.md`'s header declares `Range: 2bd333f..6002f99` (`Head: 6002f99`), i.e. the QC-tri-time head, **not** HEAD `9322239`. The delta is covered by the separately recorded `review/qc-fix-diff.md` (`Base: 6002f99` → `Head: 9322239`, 4 files), and `qc-consolidated.md` documents both ranges. Composition verified: file sets union to exactly the 7 files of `2bd333f..9322239`, and the diffstat arithmetic composes (3172+202−12 = 3362 insertions; −59 deletions) | Informational (review-bundle currency) | **None** — no unreviewed code: the fix wave was revalidated by QC seats 1 and 3 (`6002f99..9322239`), and the only HEAD-level artifact I verified is this pack's own header label |
| O2 | The plan's `## Acceptance / Done Criteria` boxes are all still `[ ]`, and `## Review Gate Summary` still reads `pending` | Bookkeeping (PM-owned) | **None** — both are PM-owned durable artifacts outside this dispatch's write scope; flagged as hand-off |
| O3 | Plan DoD records the *plan-open* baseline `903 passed, 2 skipped`; HEAD is `1096 passed, 3 skipped` | Informational | **None** — expected growth from the plan's own tasks (+193 tests, +1 gated live test); no regression |

No Critical / Warning-class defect was found in the delivered revision.

## Reproduction steps (fresh, this round)

### 1. Checkout alignment (read-only)

```
cd /root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-gateway
git rev-parse --abbrev-ref HEAD   # feature/20260911-subtitle-gateway
git rev-parse HEAD                # 932223941318cc2a12b7d6a066eaacafdd814247
git status --porcelain            # (empty)
git merge-base 2bd333f HEAD       # 2bd333f…  → base is the branch cut
git diff --stat 2bd333f..HEAD     # 7 files, +3362/−59
git diff --check 2bd333f..HEAD    # clean, exit 0
```

### 2. Offline suite at HEAD (worktree package dir; control venv interpreter; no worktree `.venv` exists)

```
cd /root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-gateway/bilibili-asr-archive
/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest -q -rs
```

- Result: **`1096 passed, 3 skipped in 43.90s`**, exit 0 (pytest 9.1.1, Python 3.12.3, `configfile: pyproject.toml`, rootdir = the worktree package dir).
- The 3 skips are **exactly** the opt-in live gates — no other skips:
  - `tests/test_bilibili_api_gateway.py:3300` — *live smoke is opt-in: set BILI_LIVE_SMOKE=1 to request it*
  - `tests/test_live_metadata_smoke.py:329` — same message
  - `tests/test_live_subtitle_smoke.py:438` — *live subtitle probe is opt-in: set BILI_LIVE_SMOKE=1 to request it*
- Boundary / no-leak / conversion rows re-run **by name** (8 passed in 0.54s, exit 0):
  `test_only_the_gateway_module_imports_bilibili_api` (AST scan, 1690),
  `test_gateway_imports_stay_on_metadata_surface` (AST scan, 1702),
  `test_gateway_source_never_names_forbidden_seam_methods` (1746),
  `test_gateway_protocol_surface_is_locked` (1637),
  `test_the_subtitle_url_sentinel_is_scanned_like_every_other_secret` (2181),
  `test_subtitle_failure_messages_never_carry_the_upstream_text_or_the_url` (3207),
  `test_caption_seconds_are_floored_rather_than_rounded_to_milliseconds` (2686),
  `test_subtitle_dtos_carry_no_work_id_and_no_url_field` (1540).
- Import resolution is the worktree source, not the control editable install: `tests/conftest.py` inserts `<worktree pkg>/src` at `sys.path[0]`, and the suite's subtitle rows exercise the new adapter surface, which the control install does not contain — 1096 green is only reachable with the worktree tree imported.

### 3. Live subtitle probe reproduction (the plan's core acceptance)

```
cd /root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-gateway/bilibili-asr-archive
set -a; source /root/workspace/bilibili-asr-archive/.env; set +a     # credential loaded, never echoed
BILI_HTTP_PROXY=http://127.0.0.1:7890 BILI_LIVE_SMOKE=1 \
  /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_live_subtitle_smoke.py -s -v
```

- Result: **`17 passed in 1.43s`**, exit 0. First run; no retry needed (no throttle).
- Bounded evidence, reproduced **verbatim** against the plan's recorded run:

| Fact | Fresh run (this round) | Plan record |
|------|------------------------|-------------|
| `sessdata` | `present` (presence label only; `config.redact_sessdata`) | present |
| `proxy` | `present` | required on this host |
| `part_source` | `fixed-sample` | `fixed-sample` |
| part | `bvid=BV1S8hA6MEvy cid=41314223900` | same |
| listing | `track_count=1 tracks=ai-zh:ai` | same |
| body | `segments=2913 first_start_ms=460 last_end_ms=7896020 timeline=non-decreasing` | same |

- Genuineness of the live path: the probe test (line 425) monkeypatches nothing — it resolves the credential, builds the **real** `BilibiliApiGateway`, and lists/fetches upstream; the only `monkeypatch` uses in that module belong to the offline rehearsals (part-selection, loud-fail). No URL, body, cookie, or credential value appears in the output; the evidence line prints counts, `ai|cc`, and milliseconds only. Proxy port `127.0.0.1:7890` confirmed reachable.
- "No archive DB on this host" verified **independently**, not from the claim: the probe's default is `<worktree pkg>/archive/archive.db` (`tests/test_live_subtitle_smoke.py:166-172` ← `cli.DEFAULT_ARCHIVE_ROOT` + `config.ARCHIVE_DATABASE_NAME`); that path and its `archive/` parent **do not exist**, and `BILI_LIVE_ARCHIVE_DB` is unset. The only `archive.db` files on the filesystem are `/tmp/...` scratch leftovers from unrelated test suites (e.g. `test_cli_dispatch_locks_every_0`) plus `bilibili-asr-archive/refactor/archive-v2/index.db` — none is an operator archive, so `part_source=fixed-sample` is the only reachable outcome here.

### 4. `floor` discriminating row (offline proof — live proof deliberately not attempted)

- `tests/test_bilibili_api_gateway.py:2686` `test_caption_seconds_are_floored_rather_than_rounded_to_milliseconds` drives `3.14159`/`3.24159` through the **seam-driven adapter** and asserts `start_ms=3141, end_ms=3241`.
- Discrimination confirmed arithmetically: `3.14159*1000 = 3141.5899999999997` → `floor 3141` vs `round 3142`; `3.24159*1000 = 3241.59` → `3241` vs `3242`. **Both endpoints discriminate**; its docstring states it is the module's only non-exact conversion literal (all others multiply out exactly).
- Per the plan's Global Constraints (no raw subtitle JSON) this offline row is the accepted proof; no live `floor` claim is made or needed.

### 5. Deferred obligations and residual (verified from artifacts)

- **F3** (`FakeGateway` protocol double extension): deferred in this plan's `## Durable Roadmap and Dependencies`, and **absorbed** by `20260911-subtitle-cli-cutover` Task 2's file list — *"Modify: `tests/fixtures/fake_bilibili_gateway.py` — scripting only, **plus** the deferred Task-1 finding F3: add the two subtitle methods to the shared `FakeGateway` protocol double"* (plan line 191).
- **R1** (`user` module bound whole): `.mstar/projects/_default/residuals.json` holds exactly **one** entry, `20260911-subtitle-gateway/R1`, `severity: low`, `decision: defer`, `owner: @project-manager`, non-empty `target` (*the next plan whose file list includes `src/bili_asr/sources/bilibili_api_gateway.py`; expected: the audio/ASR iteration*), `tracking:` → the plan's Durable Roadmap entry. The retargeted predicate is **true by exclusion** for every authored downstream plan: neither `20260911-transcript-storage` nor `20260911-subtitle-cli-cutover` lists a `src/bili_asr/sources/**` file (their file lists are `storage/**`, `tests/**`, `tests/fixtures/fake_bilibili_gateway.py`, `tests/test_subtitle_*`).
- Residual-check outcome: R1 remains the only open entry; `defer` + non-empty `target` is the shape the zero-residual rule accepts (`mstar-project-governance` / engine `findingsCleanupGate` semantics), and its discharge requires a plan that does not exist yet. **The plan may proceed to Done with R1 open.**

## DoD mapping (plan `## Acceptance / Done Criteria`)

| # | Acceptance / Done criterion | Evidence | Source |
|---|------------------------------|----------|--------|
| 1 | Subtitle DTOs + two protocol methods exist with validation, covered offline | `sources/models.py` (`SubtitleTrack`/`SubtitleSegment` + `__post_init__`), `test_subtitle_dtos_are_frozen`, `test_subtitle_dtos_carry_no_work_id_and_no_url_field`, `test_gateway_protocol_surface_is_locked` (exact method-set) | Reused L1/L2 + fresh (rows re-run) |
| 2 | WBI-signed player call in the locked shape; tracks/segments normalized so a probe distinguishes language, label, AI vs CC | `test_fake_player_endpoint_mirror_matches_the_installed_pinned_description`, `test_fake_seam_mirrors_the_player_endpoint_description`, `test_subtitle_listing_request_carries_the_locked_call_shape`, `test_subtitle_document_request_carries_the_locked_transport_shape`; **live**: `track_count=1 tracks=ai-zh:ai` (language + `ai` marker distinguishable, real endpoint accepted the shape) | Reused + **fresh live** |
| 3 | No usable track → empty tuple from listing, `not_found` from body fetch (bounded, non-error) | `test_get_subtitle_tracks_returns_an_empty_tuple_for_an_empty_inventory` (2422), `test_fetch_subtitle_segments_signals_not_found_when_nothing_survives` (3147), `test_fetch_subtitle_segments_normalizes_the_document_and_drops_degenerate_rows` (2649) | Reused L2 + fresh (rows in suite) |
| 4 | Every failure → bounded scalar code; no signed URL/credential in DTO, message, log, fixture, row | `test_subtitle_listing_failures_map_onto_bounded_taxonomy` (2604), `test_fetch_subtitle_segments_relists_for_a_fresh_signed_url` (3105), `test_the_subtitle_url_sentinel_is_scanned_like_every_other_secret` (2181), `test_subtitle_failure_messages_never_carry_the_upstream_text_or_the_url` (3207), `test_shape_failure_does_not_expose_credential` (1037), `test_fetch_subtitle_segments_rejects_a_document_url_it_cannot_normalize` (2815, the fix-wave S1 refusal branch); live output carries no URL/body/credential | Reused L1/L2 + **fresh re-run** |
| 5 | Offline suite green (incl. AST import-boundary + no-leak scans) | **`1096 passed, 3 skipped`** (exit 0) at HEAD; AST scans `test_only_the_gateway_module_imports_bilibili_api` / `test_gateway_imports_stay_on_metadata_surface` green; skips = the 3 opt-in live gates only. Baseline at plan open was 903/2 → +193 tests (expected) | **Fresh run** |
| 6 | Opt-in live probe recorded (real track list or explicit bounded blocker), bounded facts only | **Fresh live run**: exit 0, `part_source=fixed-sample`, `track_count=1 tracks=ai-zh:ai`, `segments=2913 first_start_ms=460 last_end_ms=7896020 timeline=non-decreasing`, `sessdata=present` — identical to the plan's record; bounded-blocker path exists and is rehearsed offline (`test_probe_records_each_bounded_blocker_and_never_reads_green[×4]`) | **Fresh live run** |
| 7 | `git diff --check` clean | `git diff --check 2bd333f..HEAD` → exit 0, no output | **Fresh run** |

## Bounded deviations (recorded, not defects)

1. **Archive-DB part selection is not exercised live** (`part_source=archive-db`). Unreachable on this host: no operator archive exists (independently re-established above), and the plan's recorded governing reading (QC3-002) authorizes the fixed-sample fallback and forbids "fixing" it by fabricating an archive. Coverage that does exist and ran green in the fresh suite: the whole archive-db selection branch is rehearsed offline over a **real** storage-schema DB — `test_archive_part_selection_reads_the_shipped_schema_and_stays_read_only` (asserts read-only `mode=ro`), `test_probe_part_selection_prefers_the_archive_and_falls_back_to_the_sample`, `…_ignores_an_archive_without_a_part`, `…_skips_a_part_the_archive_marked_gone`, `…_ignores_a_row_that_is_not_a_bv_id`. Per the governing reading this is **not** a failed acceptance item; the CLI plan is the first plan that can run the archive-backed variant live.
2. **Anonymous credential tier not exercised live** (QC3-004 / S7, carried). The probe structurally supports it (`resolve_sessdata → None`, `sessdata=present|absent` recorded) and the adapter's anonymous behaviour is covered offline by the taxonomy rows; the *live* anonymous arm exists only in `tests/test_live_metadata_smoke.py` and was not triggered (`sessdata=present`). Deliberately not weakened or re-run without the credential. Ownership stays with the QA gate/CLI plan's live coverage.
3. **No live `floor` proof** — would require reading raw subtitle JSON, forbidden by the plan's Global Constraints; the offline discriminating row (item 4 above) is the proof.

## Residual check

- `.mstar/projects/_default/residuals.json` → `entries["20260911-subtitle-gateway"]` contains **R1 only** (`low`, `decision: defer`, owner `@project-manager`, executable target, tracking pointer). No other open residual for this plan; none for the iteration's other plans. Nothing to close or re-open this round; R1's defer is legitimate and its target predicate is checkable and currently true by exclusion.
- **The plan may proceed to Done with R1 open.**

## Limitations

- One live run only (upstream state can drift); the acceptance claim is "the locked shape reaches the real endpoint and normalizes a real document", bounded to the fixed sample at that moment. The fresh run matched the plan's recorded run exactly.
- The performance observation (`17 passed in 1.43s` including the network round trip through the local proxy) relies on the probe's genuine-path structure (no monkeypatch, real gateway, real credential); no second live run was spent to time it.
- The `## Acceptance / Done Criteria` boxes were left unchecked and `## Review Gate Summary` untouched: this dispatch's write scope is the report plus the plan's `## QA Gate Summary` section (branch policy read-only).
- No control-checkout state, no commits, no venv changes were made; the worktree tree is still clean after all runs (`git status --porcelain` empty).

## Recommended owners

- `@project-manager`: tick the plan's Acceptance boxes and fill `## Review Gate Summary` (still `pending`) when performing the merge + Done transition; optionally regenerate `review/branch-diff.md` to HEAD or annotate its header (O1) — not required for merge.
- `@project-manager` / future audio-ASR plan: R1 stays open by design; discharge when a plan's file list includes `src/bili_asr/sources/bilibili_api_gateway.py`.
- `20260911-subtitle-cli-cutover`: owns F3 (already written into its Task 2 file list) and the first live archive-backed + anonymous-tier coverage opportunity.

## Verdict

**Approve — recommend merge** into `iteration/iter-2026-09-subtitle-transcript-sqlite`.

- Mandatory checks all reproduced fresh at HEAD `9322239` on the assignment's checkout: offline `1096 passed, 3 skipped`; live probe exit 0 with `part_source=fixed-sample`, `sessdata=present`, and bounded facts identical to the plan's record; AST import-boundary + no-leak scans green; `git diff --check` clean.
- DoD: 7/7 criteria mapped to evidence; 4 of 7 rest on fresh runs, the rest on reused L1/L2 rows that were re-executed inside the fresh suite run.
- Zero-residual: R1 is the only open entry (`low`, `defer`, executable target) and is explicitly permitted to remain open at Done.
- No Critical or Warning-class finding; the recorded items (archive-db branch, anonymous tier, no live `floor`) are bounded deviations authorized by the plan's governing reading, and O1–O3 are bookkeeping/currency notes only.
- Plan `Done` deliberately not marked: the merge precedes Done and is PM-owned.
