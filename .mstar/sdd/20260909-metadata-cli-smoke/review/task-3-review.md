# Task 3 Review — Bounded live API smoke test and operator notes

- **Reviewer**: code-reviewer (SDD L2, Mode A diff-first, read-only leaf; no delegation)
- **Plan**: 20260909-metadata-cli-smoke · Task 3
- **Branch / range**: `feature/20260909-metadata-cli-smoke` · `cf490ff..c86daa7`
- **Diff basis**: control artifact `.mstar/sdd/20260909-metadata-cli-smoke/review/task-3-diff.md` (read once; no git re-run, no checkout mutation)
- **Inputs**: task-3-brief.md · implementer-task-3-report.md · spec `metadata-cli-contract.md`
- **Paths pre-flight**: all assignment paths absolute and present ✔ (brief, spec, implementer report, diff, worktree files)

---

## Spec Compliance

**✅ Spec compliant** — every brief checkbox and Task-3-specific check verified against the diff **and** against the actual worktree sources (fixture module, `cli.py`, `config.py`, `schema.sql`, `database.py`, `.gitignore`). No product-source change anywhere in the diff.

| Check | Evidence |
|---|---|
| Live execution opt-in via `BILI_LIVE_SMOKE=1`; default runs skip without failure | `test_live_metadata_smoke.py:73-74,250` (env gate `== "1"`, `pytest.skip` before any I/O). Independently re-ran the sanctioned focused command (NO `BILI_LIVE_SMOKE`): `1 passed, 1 skipped in 0.16s` — live smoke SKIPPED, offline rehearsal PASSED. Matches implementer's reported output. |
| One public page, UID 23191782, temporary DB | `LIVE_SMOKE_MID = 23191782` literal (line 48, independent of the config default so a default change cannot widen the bound); `_bounded_live_argv` pins `--start-page 1 --limit-pages 1` (lines 220-233); archive root is the function-scoped `tmp_root` conftest fixture (fresh `bilibili-asr-archive/.test-tmp/manifest-test-<pid>-<n>` per test, removed in teardown, `.gitignore:25` covers the base). |
| Normalized table relationships asserted on success | `_assert_collected_page_rows` (lines 131-186): one user row per mid; every `videos` row joins `bilibili_users` via `mid` (LEFT JOIN orphan count = 0); every `video_parts` row joins `videos` via `bvid`; terminal run row (`requested_start_page=1`, `requested_page_limit=1`, `finished_at`); exactly one page row `(1,'ok')` or `(1,'empty')`; fresh cursor advanced `(2,'limited')` / `(1,'complete')`; `observed_total >= video_count` when present. |
| Docs: fresh layout, no-migration, credential boundary, exact smoke command | `docs/metadata-storage.md` covers all four (layout incl. reserved media-boundary tables + three views; "no migration, import, reset, or rewrite path — deleting `archive.db` is the only restart path"; credential boundary flag-wins/presence-label; verbatim bounded command). Every schema claim traced to `schema.sql` (tables/views/`PRAGMA foreign_keys = ON`/`error_code <= 64`/outcome+state enums), every CLI claim to `cli.py` (`_open_read_repository` exit-1-no-create, `_cmd_runs` newest-first/`runs: empty`/`--limit` positivity/`running` rows rendered, `_cmd_fetch_meta` exit 0/1/2), every credential claim to `config.py` (`resolve_sessdata` flag-wins, `redact_sessdata` presence label, `ARCHIVE_DATABASE_NAME = "archive.db"`). No inaccuracies found. |
| No raw JSON / signed URLs / credentials documented or exposed | Docs and README contain only redacted-label semantics and bounded-code examples (`response_error`, `rate_limited` as *code names*). Test file references Plan-2 sentinel constants by name; their values in `tests/fixtures/fake_bilibili_gateway.py:51-79` are placeholders (`SESSDATA-VALUE-THAT-MUST-NOT-LEAK`, example.com signed-URL shape, `RAW-JSON-BODY-THAT-MUST-NOT-LEAK`). Live surfaces scanned for static tokens + the operator's `BILI_SESSDATA` **value** on both output and persisted rows (lines 104-128). |
| Adjudicated spec reading (anonymous exit-2 = documented expected no-credential behavior; credential-in-play or `unexpected error` = loud) | Implementation matches the stated reading exactly: exit-2 branch first fails loudly on `"unexpected error" in err` (line 275-279, checked before row assertions), then runs the full bounded-failure row assertions (`_assert_bounded_failure_rows`, lines 290 + 156-217) **before** the skip/fail decision; anonymous → `pytest.skip` with a reason naming the observed `error_code` and the credential requirement (lines 283-291); credential in play → `pytest.fail` (292-296). Hygiene scans run before the branch on both surfaces (lines 267-274), so the skip case is never assertion-free. Offline rehearsal drives both outcome branches through the real `main(argv)` over the fake seam in every default run (lines 302-381). Grounding verified: Plan-2 QA gate U3 (`.mstar/sdd/20260909-bilibili-api-ingestion/review/qa-gate.md:22,89,126`) documents precisely this anonymous `response_error` rejection and routes happy-path demonstration to this plan's credential-supporting CLI. |
| Scope: tests + docs only | Diff contains exactly `tests/test_live_metadata_smoke.py` (new), `docs/metadata-storage.md` (new), `README.md` (modified). No `src/`, no `pyproject.toml`. |
| No legacy sidecars created or read | Live smoke asserts `manifest/manifest.jsonl`, `meta-cursor.json`, `run-ledger.jsonl` absent after the run (lines 251-252, rehearsal repeats at 358-359, 380-381); `LEGACY_SIDECAR_PATHS` matches the constraint list. `_cmd_fetch_meta` verified to contain no `run_ledger` usage; ledger imports remain only in the pilot/run/schedule handlers (cli.py:1432,1738,1800), matching the README correction. |

### ⚠️ Cannot verify from diff (for PM / plan QC / QA)

1. **Actual live-network execution of the smoke** — by design it stays skipped here; the QA gate owns the opted-in run. Verified only by code review + offline rehearsal of both outcome branches (the rehearsal is itself a default-suite check that passed).
2. **Full-suite green (`858 passed, 2 skipped`)** — implementer-reported pre-commit evidence; the assignment forbids re-running the full suite from this seat. Plan-level QC/QA owns the whole-branch run.
3. **README Workflow block pre-existing lines** — `status`/`runs` lines in the Workflow block (README:102-107) predate this task (diff touches only the `fetch-meta` line); they are accurate *now* but were not authored in this diff.

---

## Strengths

- **The offline rehearsal is the standout**: the live smoke's SQL assertion helpers — the task's actual non-trivial logic — now execute in every default suite run through the same real `main(argv)` path over the fake seam, with seam sentinels riding the payload and a positive control (`BV1REHEARSE1` persisted) so the no-leak scans are provably non-vacuous. Without it, a broken assertion/query would first surface at the QA gate's live run.
- **Evidence-before-skip ordering is done right**: leak scans and failure-shape assertions run before the anonymous skip in all paths — the skip reports a fully-verified outcome, never a silent pass.
- **Bound hardening**: `LIVE_SMOKE_MID` is a literal independent of the config default; `tmp_root` is function-scoped so the live smoke and rehearsal cannot contaminate each other within one opted-in invocation; the credential-in-play check reads only `BILI_SESSDATA` (the bounded argv never carries `--sessdata`, so the env scan covers the only credential channel in play).
- **Docs are code-accurate**: every exit-code row, label, view name, reserved table, FK relationship, and the `observed_total` semantics traced to actual source; the `fetch-meta`-no-longer-writes-ledger correction and the `status`-reads-SQLite rewrite both match the Task-1 wiring.
- **README accuracy fixes are genuine bug fixes to stale claims** (the old `fetch-meta --resume` workflow line would exit 1 on a fresh archive; the old ledger/status text described removed sidecar behavior).

## Issues

### Critical

None.

### Important

None.

### Minor

1. **README.md:256 — internal anchor likely broken on GitHub-class renderers.** The link target `#fresh-start-metadata-collection-fetchmeta--status--runs` omits the internal hyphen of `fetch-meta`; the heading at README:485 (`### Fresh-start metadata collection (`fetch-meta` / `status` / `runs`)`) slugifies to `...-fetch-meta--status--runs` (hyphens inside words are preserved; backticks/parens/slashes are stripped). The anchor as written won't resolve where the README is rendered with GitHub-style slugs. Cosmetic docs fix: `fetchmeta` → `fetch-meta`.
2. **tests/test_live_metadata_smoke.py:283-291 — the anonymous-skip branch is broader than the adjudicated instance.** The pre-accepted reading names anonymous exit-2 `response_error` as the expected no-credential behavior; the implementation skips for *any* bounded anonymous exit-2 (e.g. `rate_limited`). Defensible — the spec defines exit 2 generically ("gateway failure after bounded retry"), the failure-shape assertions still run first, and the skip reason names the actual observed code — but the tolerance is wider than the literal instance in the adjudication. PM should confirm this breadth is intended (or pin the code / add a differentiated message for non-`response_error` codes).
3. **tests/test_live_metadata_smoke.py:179-183 — the `complete` sub-branch of `_assert_collected_page_rows` is not exercised by the offline rehearsal** (rehearsal covers `limited` happy path + bounded failure only; `--limit-pages 1` forces `limited` on a non-empty page). It executes only in a live run where upstream returns an empty page 1 — practically never for UID 23191782. The seam could script an empty first page to cover it offline. Dead-in-practice defensive branch; observation for plan QC, not a defect.

**Review-seat notes (not defects):** the focused verification run left the empty gitignored `bilibili-asr-archive/.test-tmp/` base directory in the worktree (conftest removes per-test dirs but keeps the base — pre-existing Plan-1/2 conftest behavior; left untouched per the read-only seat).

---

## Assessment

**Task quality:** Approved

No Critical or Important findings. The three Minor items (broken README anchor, skip-branch breadth vs. the adjudicated instance, unrehearsed `complete` sub-branch) are for PM disposition / plan QC — none blocks the task; per zero-residual cleanup the PM owns their tracking or closure.

**Verification performed by this reviewer:** read the diff once; read the implementer report and spec; verified every test/doc claim against the worktree sources (`conftest.py`, `fixtures/fake_bilibili_gateway.py`, `cli.py`, `config.py`, `storage/schema.sql`, `storage/database.py`, `pyproject.toml`, `.gitignore`); ran exactly the one sanctioned focused command (`pytest tests/test_live_metadata_smoke.py -v`, no opt-in) — `1 passed, 1 skipped`; confirmed the cited Plan-2 QA-gate U3 note exists and says what the spec reading claims. No git commands re-run, no test suite re-run, no worktree mutation, no delegation.
