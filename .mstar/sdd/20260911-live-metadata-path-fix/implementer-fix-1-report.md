# Fix-1 implementer report — batched docs/hygiene wave (I1, M1–M5, Task-5 #7/#8)

- **Status: DONE** — every assigned finding fixed offline; no product logic, constant, assertion, or
  test outcome changed (focused suite `1 passed, 1 skipped`; full offline suite `894 passed,
  2 skipped` = the stated baseline).
- Plan: `.mstar/plans/20260911-live-metadata-path-fix.md` (fix round after Task 4/5 L2 reviews)
- Working branch: `fix/20260911-live-metadata-path-fix` (dedicated worktree
  `.worktrees/20260911-live-metadata-path-fix`), commit **`5667844`**
  `docs(metadata): reconcile page-size/live-smoke prose with the shipped 30 default`
- No push, no `main` mutation, no other branch touched. No subagent dispatched (delegation forbidden).
  The only harness file written is this report; no plan / snapshot / status / compass / spec edit.
- No live network run: `BILI_LIVE_SMOKE` was never set (verified unset in the environment before the
  runs), no credential echoed, no `--sessdata` value read.

## 1. Implemented — per-finding disposition

### I1 (Important) — `docs/metadata-storage.md` dated page-size paragraph — FIXED

Two edits, both inside the "Exact bounded live smoke command" observation list:

- `docs/metadata-storage.md:210` — the appositive that asserted a property of current code became a
  dated reading: `(the ingestor's page size of 100)` → **`(the then-shipped page size of 100)`**.
  The whole 2026-09-11 observation (risk-control refusal, `-400`, the `ps=5` probe with
  `observed_total=1691`, the later 412s) is preserved verbatim as what was observed that day.
- `docs/metadata-storage.md:219-226` — the "**Whether the endpoint also caps `ps` below 100 was not
  settled**" tail is replaced by a new settled bullet:
  `ps=30` → `code=0` (30 items) and `ps=50` → `code=0` (50 items), while `ps=100` is rejected
  (HTTP 412 on the probes, JSON `-400` on production runs); therefore **the shipped page size is
  `PAGE_SIZE = 30` in `src/bili_asr/services/metadata_ingest.py`**, which is also the pinned
  package's own documented `ps` value.

Cross-check performed (as required by the finding):
- `src/bili_asr/services/metadata_ingest.py:50` → `PAGE_SIZE = 30` (state the docs now name).
- `README.md:509` → "(the ingestor's page size is 30)" (current-behaviour line the docs now agree with).
- `src/bili_asr/config.py:30` and `src/bili_asr/sources/models.py:98-100` → both already describe 30
  as shipped / 100 as rejected; no contradiction left.
- The settled facts are inserted verbatim from plan §Problem **D4** (lines 79-83), not re-derived.

### M1 — documented live-smoke command hid the evidence line — FIXED

- `docs/metadata-storage.md:159-174` and `README.md:567-580`: both documented commands now end in
  `-s -v`, and both carry an explicit reason: pytest captures the stdout of a *passing* test, so a
  plain `-v` run hides the count-only evidence line on the happy path and "would force a second page
  request against a risk-controlled endpoint". The docs add the operator-facing instruction
  "use `-s`/`-rP` on the first live attempt"; the README states "Keep `-s` (or `-rP`) in the command
  on the first live attempt".

### M2 — credential channel described more broadly than the smoke implements — FIXED

- `docs/metadata-storage.md:186-189` — "**With a credential** (`--sessdata` or `BILI_SESSDATA`)" →
  "(`BILI_SESSDATA` only — the smoke builds its own `fetch-meta` argv and passes no `--sessdata`,
  so that flag is a CLI surface the smoke never uses)".
- `README.md:582-585` — same scoping: "the smoke's credential signal is the `BILI_SESSDATA`
  environment variable alone (sourced from `.env` above): it builds its own `fetch-meta` argv and
  passes no `--sessdata`, so that CLI flag is not a smoke input".
- **Additional M2 site, same defect, fixed in the same file:** the opted-in skip message at
  `tests/test_live_metadata_smoke.py:344-346` told the operator to "Provide a credential via
  `--sessdata` or `BILI_SESSDATA`" — for this smoke `--sessdata` can never reach it. It now reads
  "Provide a credential via `BILI_SESSDATA` in the environment for the happy-path run; this smoke
  builds its own argv, so its `--sessdata` flag is never passed." Verified no test asserts that
  message text (`git grep` for its fragments: only the site itself). Disclosed as a one-step
  widening of M2 rather than a new change: it is the same false claim, in the file M3 already
  authorises, and leaving it would have left M2 half-fixed on the operator-facing surface.
- The CLI's own credential boundary prose (`docs/metadata-storage.md:75-83`, `README.md:519-525`,
  `README.md:239-240`) correctly describes `--sessdata`/`BILI_SESSDATA` for `fetch-meta` and was
  left exactly as is.

### M3 — part-coverage comment overstated its assertion — FIXED (wording, not assertion)

**Chosen: fix the comment, not the assertion.** Two sites in `tests/test_live_metadata_smoke.py`:

- `tests/test_live_metadata_smoke.py:206-209` — "Every collected video exposes at least one part
  upstream" → "The page carries at least one part in aggregate (parts are fetched for every collected
  video; an individual video may legitimately have no parts upstream, so this is deliberately not a
  per-video claim), and each collected video is recorded once as discovered on this page."
- `tests/test_live_metadata_smoke.py:138-140` — the docstring's matching overstatement ("at least one
  part row per collected video") → "at least one part row in aggregate over the collected page (not
  one per video: an individual video may have no parts upstream)". The review's M3 cites both sites
  (`:205-206` and the docstring `:138`), so both were corrected.

Why the assertion was not strengthened (evidence, both points verified read-only):

1. `src/bili_asr/sources/bilibili_api_gateway.py:206-211` — `_normalize_video_parts` accepts an empty
   pagelist array and returns `()`. A collected video can therefore legitimately end with zero part
   rows, so `SELECT COUNT(DISTINCT bvid) FROM video_parts == video_count` is **not** an invariant of
   live upstream data; asserting it would turn a legitimate upstream shape (a listed video whose
   pagelist is empty) into a spurious live-smoke failure — precisely the "the CLI/database is broken"
   misreading the same docs paragraph warns against.
2. The per-video form the review sketches ("for each video the page reports with parts") is not
   computable from persisted state: `videos` (`src/bili_asr/storage/schema.sql`) stores
   `bvid/aid/mid/title/pubdate/created_at/updated_at` and no part count, so the page's per-video
   parts information is not recorded anywhere the smoke can read.

`assert part_count >= 1` is unchanged, as are all other assertions; the offline rehearsal
(`test_live_smoke_row_assertions_rehearse_offline_over_the_fake_seam`) still passes.

### M4 — documented commands assumed the operator's checkout layout — FIXED

Both documented command blocks now lead with `CONTROL=/root/workspace/bilibili-asr-archive`
(the control checkout), `cd "$CONTROL/bilibili-asr-archive"`, source `"$CONTROL/.env"`, and run
`"$CONTROL/bilibili-asr-archive/.venv/bin/python"`. A following paragraph states the requirement
explicitly: the control checkout owns `.env` and `.venv`; a linked feature worktree has neither, so
a worktree run must address them by absolute control-checkout path (or provision its own
environment). Verified on disk before documenting: control `.env` exists, control
`bilibili-asr-archive/.venv/bin/python` exists; neither exists in the feature worktree.

### M5 — `.env.example` comment/default tensions — FIXED

- Proxy block (`.env.example:18-24`): the self-contradiction is resolved in one clause —
  the *library* bypasses `HTTPS_PROXY`/`ALL_PROXY`; the *gateway* resolves a proxy itself before
  constructing the request, so those variables remain valid but must be applied by the gateway. The
  example line is now labelled `默认：不设置（不强制代理）。示例值（非默认）：`, so the commented
  example no longer reads as the default.
- Retention block (`.env.example:29-31`): the commented value now matches the documented default —
  `# BILI_KEEP_AUDIO=1` → `# BILI_KEEP_AUDIO=0` (code: `src/bili_asr/audio_reclaim.py:46` treats
  only `"1"` as "retain", so unset/0 = delete; the comment still names `设为 1 = 保留音频` as the
  opt-in).
- Unchanged because already consistent: `BILI_SESSDATA` (placeholder, "不填则匿名") and
  `BILI_ASR_MODEL` (commented value equals `DEFAULT_MODEL` in `src/bili_asr/asr.py:20`). The file's
  structure and the single-quote guidance (`.env.example:7`) are untouched.

### Task-5 minor #7 — `src/bili_asr/config.py` stale rationale — FIXED (comment-only)

`src/bili_asr/config.py:30-31`: "Ten pages at the ingestor's page size of 100 is a resumable,
conservative slice" → "Ten pages at the ingestor's page size of 30 (300 videos) is a resumable,
conservative slice". `DEFAULT_PAGE_LIMIT = 10` and every other line of the file are unchanged.

### Task-5 minor #8 — fixture scripted response echoed `ps: 100` — FIXED (inert literal)

`tests/fixtures/fake_bilibili_gateway.py:479`: `{"pn": 1, "ps": 100, "count": count}` →
`{"pn": 1, "ps": 30, "count": count}`. Kept the field (a real response carries `ps`; dropping it
would reduce fixture fidelity) and changed only the literal — no signature, no assertion, no other
fixture value. Independently re-confirmed inert before editing: the adapter reads only
`page.count` (`_read_observed_total`), and no test asserts the response `ps`
(`git grep '"ps": 100'` matched only this line; `"ps": "const int: 30"` at fixture line 73 is the
separate pinned-config expectation and was not touched).

### Not acted on (accepted by the assignment)

Red-proof transcript abridgement, the "7 pins vs 6" report arithmetic, the seam's documented-call
allow-list design, and the docs' `ArgsException`/412 claims were left alone. README's pre-existing
trailing whitespace in the metadata section was left byte-for-byte: no hunk of this diff touches
those lines and `git diff --check` is clean.

## 2. Tests / verification (offline only)

Interpreter for every run (the assignment's control interpreter), worktree package root as cwd:
`/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python`.

1. `BILI_LIVE_SMOKE` unset (verified: `env | grep -c BILI_LIVE_SMOKE` → `0`).
2. Focused, after all edits:
   `python -m pytest tests/test_live_metadata_smoke.py -v`
   → `2 items collected`; `test_live_smoke_fetch_meta_one_page_lands_normalized_rows SKIPPED`;
   `test_live_smoke_row_assertions_rehearse_offline_over_the_fake_seam PASSED`;
   **`1 passed, 1 skipped in 0.26s`** — identical to the pre-edit baseline run of the same command
   (`1 passed, 1 skipped in 0.30s`).
3. Full offline suite: `python -m pytest -q` → **`894 passed, 2 skipped in 50.92s`** — exactly the
   stated baseline (894 / 2), with the two skips being the live smoke and its pre-existing sibling.
4. Metadata-focused files: `python -m pytest -q tests/test_metadata_cli.py tests/test_metadata_ingest.py
   tests/test_bilibili_api_gateway.py tests/test_metadata_e2e.py` → **`197 passed, 1 skipped in 4.32s`**
   (covers every consumer of the changed fixture helper).
5. `git diff --check` (worktree root) → no output, clean; also confirms no trailing whitespace was
   introduced (`git diff -- bilibili-asr-archive/README.md | grep -c '^[+-].*[ \t]$'` → `0`).
6. Stale-`100` sweep on tracked files:
   `git grep -n "page size of 100\|ps=100\|\"ps\": 100\|ps: 100" -- .` →
   - `docs/metadata-storage.md:210` — the dated reading "then-shipped page size of 100" (**intended**).
   - `docs/metadata-storage.md:222` — "`ps=100` was rejected" (**intended**, settled evidence).
   - `src/bili_asr/services/metadata_ingest.py:46`, `src/bili_asr/sources/models.py:99`,
     `tests/test_bilibili_api_gateway.py:219` — all three describe 100 as the **rejected** former
     value (**intended**; pre-existing Task 3/5 prose, already correct).
   - `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/bilibili-api-gateway.md:60` — the
     pinned spec's "Required upstream calls #1" writing `ps=100`; plan §Locked decisions says the
     spec is **annotated, not rewritten**, and harness specs are outside this leaf's write scope.
     **Reported, not edited** — it is the one remaining `ps=100` in the tree and its disposition
     belongs to the PM (annotation already exists per the plan/Task 5 record).
   No remaining site describes 100 as the current page size.

## 3. Files changed (6, all on `fix/20260911-live-metadata-path-fix`)

| File | Change | Finding |
|------|--------|---------|
| `bilibili-asr-archive/docs/metadata-storage.md` | dated page-size reading, settled `ps` bullet, `-s -v` command + control paths, credential scoping | I1, M1, M2, M4 |
| `bilibili-asr-archive/README.md` | `-s -v` command + control paths, credential scoping | M1, M2, M4 |
| `bilibili-asr-archive/tests/test_live_metadata_smoke.py` | part-coverage docstring + comment wording; skip-message credential wording | M3, M2 |
| `.env.example` | proxy clarification + example-is-not-default label; retention commented default `1` → `0` | M5 |
| `bilibili-asr-archive/src/bili_asr/config.py` | `DEFAULT_PAGE_LIMIT` rationale comment 100 → 30 (300 videos) | Task-5 #7 |
| `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py` | scripted response literal `"ps": 100` → `30` | Task-5 #8 |

Diff: 6 files, +63 / −30. No change to any product constant, branch, control flow, assertion, DTO,
schema, CLI surface, or packaging file.

## 4. Self-review notes

- **Behaviour-free, demonstrated not asserted:** the only non-prose edits are one comment
  (`config.py`), one inert fixture literal, and one skip-message string; the focused and full suites
  reproduce the pre-edit numbers exactly (`1 passed, 1 skipped`; `894 passed, 2 skipped`), and the
  fixture literal was confirmed unread by the adapter and unasserted by tests before editing.
- **Widening disclosed, not hidden:** two edits sit slightly outside the finding's literal anchors —
  the skip message in the smoke test (M2's exact defect, same file as M3) and the docstring at
  `test_live_metadata_smoke.py:138` (cited by the M3 review text). Both are wording-only, both are
  named here, and neither changes an assertion.
- **M3 judgment recorded with evidence:** the aggregate assertion was kept because
  `_normalize_video_parts` admits an empty pagelist and no per-video part count is persisted, making
  the stronger form non-deterministic against live data. If the PM prefers the stronger form, it
  needs a fixture-level signal (persisted or page-reported parts) that does not exist today — a
  design change, not a fix-round edit.
- **Docs accuracy re-read end to end for the touched sections:** the smoke section's bullets now read
  consistently (`BILI_SESSDATA` only for the smoke; `-s` required to see the evidence line; control
  paths for `.env`/`.venv`), and the new settled bullet matches the plan's D4 evidence, the README
  current-behaviour line, and `PAGE_SIZE = 30` in code.
- **No forbidden action:** no subagent, no network run, no `BILI_LIVE_SMOKE`, no credential read or
  echo, no harness artifact edited, no push, `main` untouched (branch confirmed
  `fix/20260911-live-metadata-path-fix` at commit time).
