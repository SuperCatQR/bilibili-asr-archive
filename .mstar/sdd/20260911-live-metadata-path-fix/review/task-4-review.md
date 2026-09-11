# Task 4 Review — Bounded live verification + operator documentation

- Plan: `20260911-live-metadata-path-fix` (task 4)
- Reviewer: `code-reviewer` (L2 SDD task reviewer; Mode A, diff-first, read-only)
- Diff basis: `3a96dd1..f4af1aa` (`review/task-4-diff.md`; implementation commit `f4af1aa`)
- Worktree: `/root/workspace/bilibili-asr-archive/.worktrees/20260911-live-metadata-path-fix`
  (branch `fix/20260911-live-metadata-path-fix`, now at `f44066c` — Task 5 landed after this
  diff; the diff was reviewed as given, the worktree was read only for context)
- Inputs verified present and absolute: brief, plan, implementer report, diff file. Verdict below.
- Read-only discipline: no git mutation, no worktree write, no `BILI_LIVE_SMOKE`, no live
  network call. The only command executed was the dispatch-sanctioned offline suite.

## Spec Compliance

- ✅ **Opt-in, skip-by-default gate intact.** Verified by execution, offline, without
  `BILI_LIVE_SMOKE`:
  `/root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_live_metadata_smoke.py -v`
  → `1 passed, 1 skipped` (live probe SKIPPED, offline rehearsal PASSED).
- ✅ **Bound bounded to one page for UID 23191782 into a temporary root.**
  `tests/test_live_metadata_smoke.py:262-275` (`--mid 23191782 --start-page 1 --limit-pages 1
  --archive-root <tmp_root>`); no subtitle/playback/audio/ASR path invoked; legacy-sidecar
  absence asserted (`:304-305`).
- ✅ **No success claimed on a bounded failure.** Exit 2 → `_assert_bounded_failure_rows`
  (`:327`) runs *before* the branch decision; anonymous ⇒ reasoned `pytest.skip` (`:334-343`),
  credential present ⇒ `pytest.fail` (`:344-348`). The skip cannot mask a credentialed failure:
  the smoke builds its own argv and never passes `--sessdata`, so `BILI_SESSDATA` is the only
  credential channel.
- ✅ **Happy-path assertions are non-vacuous and materially stronger than before** — exact
  page-row count (`:158-160`), `error_code IS NULL` on a committed page (`:165`),
  discovery→video FK orphan scan (`:183-187`), `discovery_count == video_count` (`:208`),
  `part_count >= 1` (`:207`), cursor advanced past the committed page
  (`:212`, `next_page == page_number + 1`, with `page_number == 1` asserted at `:164`).
  No previously asserted invariant was weakened; the old presence-only `fetchone()` page check
  was upgraded to an exact count.
- ✅ **Docs describe the runtime HTTP backend, the `BILI_HTTP_PROXY` knob with its
  `HTTPS_PROXY`/`ALL_PROXY` fallbacks and *why* the knob is needed, and the corrected
  live-smoke expectations** (`docs/metadata-storage.md:102-155, 157-196`; `README.md:526-543,
  559-590`; `.env.example:16-22`). Claims I could trace to source/behaviour are listed under
  Strengths §5; the proxy precedence documented is exactly `config.py:40-51` +
  `bilibili_api_gateway.py:277-279`.
- ✅ **Live arm of the brief honoured within its own evidence boundary.** One attempt, cooldown
  (~170 s), one retry, both bounded `response_error`; blocker recorded with per-table row counts
  (implementer report §3.1-§3.3), STOP conditions respected (no fingerprint spoofing, no retry
  storm, 6 live calls total, no page-size edit inside this task). The plan's acceptance language
  admits this blocker arm ("or records an explicit, cooled-down upstream blocker with evidence").
  The happy arm was satisfied later at `f44066c` (Task 5 live re-run: `outcome=limited videos=30
  parts=33 discoveries=30 page_rows=1 cursor_next_page=2 cursor_state=limited`, exit 0).
- ✅ **Scope guard respected.** The diff touches exactly the four allowed paths
  (`.env.example`, `bilibili-asr-archive/README.md`, `bilibili-asr-archive/docs/metadata-storage.md`,
  `bilibili-asr-archive/tests/test_live_metadata_smoke.py`). No adapter, config, DTO, ingestor,
  repository, schema, CLI, `pyproject.toml`, or `uv.lock` change.
- ✅ **No credential/raw-payload leakage in the diff.** Differential scan of the diff for
  cookie-shaped, `SESSDATA=<value>`, signature, and playback-CDN tokens found no match. New
  prints emit counts and one scalar code only (`:318`, `:329`); docs carry only the loopback
  proxy example, which the plan classifies as configuration, not a credential.
- ❌ **Issues found:** `bilibili-asr-archive/docs/metadata-storage.md:197-210` — see Important 1.
- ⚠️ **Cannot verify from diff:** items 1-4 under `## Cannot verify from diff` below.

## Strengths

1. **Non-vacuity is real, and the red evidence matches it.** The implementer's mutation check
   (report §2(b)) shows the two decisive new assertions fail when rows are missing/duplicated;
   I confirmed by inspection that each new assertion has a reachable failing state
   (`ingestion_pages` count ≠ 1, `error_code` non-null, `discoveries ≠ videos`, `parts == 0`,
   cursor not advanced). `ingestion_discoveries` has `PRIMARY KEY (run_id, page_number, bvid)`
   (`storage/schema.sql:79-87`), so `discovery_count == video_count` is the correct one-page
   semantics and not an over-tight assertion.
2. **The bounded-failure branch is still a bounded-failure branch** — asserted, then skipped
   (anonymous) or failed loudly (credentialed). No path turns a bounded upstream refusal into a
   pass.
3. **The new assertions are rehearsed offline on all three branches** (limited happy path,
   `complete` empty-first-page, bounded failure) and the rehearsal now guards the evidence line's
   shape (`:403-408`), so the strengthened assertions cannot rot silently between live runs.
4. **The docs claims that matter operationally are traceable, not aspirational:**
   `curl_cffi>=0.16` is a runtime dependency (`pyproject.toml:14`) and `.[dev]` resolves
   (`:21-26`); `PROXY_ENV_VAR = "BILI_HTTP_PROXY"` with the exact fallback tuple
   (`config.py:40-51`); `set_proxy` applied only when a proxy resolves
   (`bilibili_api_gateway.py:277-279`); the live-smoke expectations each map to a line in the
   test (exit 0 / `limited` / `complete` → `:203-218`; sidecar absence → `:304-305`;
   credential + playback scans → `:105-129`; loud credentialed failure → `:344-348`).
5. **Diagnosis honesty is preserved in the shipped text.** The implementer did not convert an
   unsettled hypothesis into a documented fact (report §3.5/§3.6); the docs' dated note says
   what that observation set actually showed. The defect in Important 1 is supersession by later
   evidence, not overstatement at `f4af1aa`.
6. **Live-run discipline matches the brief's bound** — one retry after a cooldown, no retry
   storm, no credential/alternate-endpoint improvisation, and the out-of-scope page-size question
   correctly escalated instead of silently patched inside a docs task.

## Issues

### Critical

None.

### Important

**I1 — `docs/metadata-storage.md:197-210` is inaccurate as shipped (PM-flagged C2 — I agree),
and the branch now documents neither the shipped page size nor the upstream `ps` bound.**

Evidence (all at branch HEAD `f44066c`, verified read-only):

- `docs/metadata-storage.md:198-199` reads "The CLI's one production page (the ingestor's page
  size of 100)", but the shipped constant is now
  `src/bili_asr/services/metadata_ingest.py:50: PAGE_SIZE = 30` (Task 5, plan §Locked decisions
  "Page size"). The appositive asserts a property of current code, so the dated-observation
  framing does not rescue it.
- The same branch contradicts itself: `README.md:509` says "(the ingestor's page size is 30)"
  (Task 5's edit) while `docs/metadata-storage.md:199` says 100.
- `docs/metadata-storage.md:207-210` — "Whether the endpoint also caps `ps` below 100 was not
  settled by these observations" — is superseded by plan §Problem **D4** (`ps=30` → `code=0`
  with 30 items, `ps=50` → `code=0` with 50 items, `ps=100` → HTTP 412) and by Task 5's live
  success (`videos=30`, one accepted page, exit 0). `ps=100` is also the reason the shipped
  default was changed.
- Completeness half of the same block: `docs/metadata-storage.md` never mentions the `ps` bound
  or the 30 default anywhere (grep: no `ps=30`/`ps=50`/`ps=100`/`PAGE_SIZE` outside the stale
  line), while the plan's §Locked decisions "Docs" bullet requires the docs to record the
  corrected live-smoke behaviour.

Severity rationale: **Important**, not Critical — no functional, security, or leakage impact;
it is a documentation-accuracy defect, and docs accuracy is an explicit acceptance criterion of
this plan (§Acceptance: "`docs/metadata-storage.md`, README, and `.env.example` describe the
backend, the proxy knob, and the live-smoke expectations accurately"). It is not an execution
fault of Task 4: at `f4af1aa` the statement was true of Task 4's own observations (report §3.5:
probe 4 answered 412 at `ps=5` too, so a clean A/B was genuinely unavailable inside the retry
budget). It is a supersession by D4/Task 5 that the branch must still reconcile before merge.

Required fix (docs-only, no live re-run, no test/adapter change): rewrite the tail of that
bullet to (a) state the settled evidence (`ps=30`/`ps=50` accepted, `ps=100` rejected with
`-400`/412) and the resulting 30 default, and (b) reword line 199 as a dated reading ("the
then-shipped page size of 100"). PM owns disposition/routing per `zero-residual`.

### Minor

**M1 — the documented live-smoke command suppresses the evidence line it promises to print.**
`docs/metadata-storage.md:161-163` and `README.md:565-570` document `... -v` (no `-s`/`-rP`),
while `docs:186-188` / `README:578-580` state "It prints one count-only evidence line …".
pytest captures stdout of *passing* tests, so on the happy path the operator sees no line. This
is not hypothetical: Task 5's report §4 (C3) records the first `-v` run exiting 0 with "the
count-only evidence line went to pytest's capture and was therefore not visible", forcing a
second live invocation with `-s` — i.e. an extra page request against a risk-controlled
endpoint. Fix: add `-s` (or `-rP`) to both documented commands, or state explicitly that `-s`
is needed on success. **QA advisory:** use `-s`/`-rP` on the first live re-run.

**M2 — the credential channel is described more broadly than the smoke implements.**
`docs/metadata-storage.md:177` and `README.md:566-568` offer the credential as "`--sessdata` or
`BILI_SESSDATA`", but the smoke builds its own argv (`tests/test_live_metadata_smoke.py:262-275`,
no `--sessdata`) and its skip-vs-loud-fail gate reads only `os.environ.get(SESSDATA_ENV_VAR)`
(`:334`). The credential signal for this smoke is the environment variable alone. Fix: say so.

**M3 — a new comment/docstring overstates its assertion.**
`tests/test_live_metadata_smoke.py:205-206` claims "Every collected video exposes at least one
part upstream" and the docstring `:138` says "at least one part row per collected video", but
the assertion at `:207` is the aggregate `assert part_count >= 1`, which holds even if one
collected video has zero parts. Either tighten
(`SELECT COUNT(DISTINCT bvid) FROM video_parts` == `video_count`) or soften the wording. Not a
spec violation — the brief asks for parts to be present.

**M4 — the documented command assumes the operator's checkout layout (review/QA alignment
note).** `docs:161,163` use `source ../.env` and `.venv/bin/python`, which resolve from the main
checkout but not from a linked SDD worktree: I verified presence-only that the feature worktree
root has no `.env`, and the worktree package has no `.venv`. Both live runs therefore used
`/root/workspace/bilibili-asr-archive/.env` and the control interpreter (Task 4 report §3,
Task 5 report §4). The docs are correct for the operator's normal working checkout, so this is
an alignment note for the QA gate's live re-run, not a docs error.

**M5 — `.env.example:16-19` reads as self-contradictory on first pass.** "会绕过 HTTPS_PROXY /
ALL_PROXY 等环境变量，只认这里配置的代理" is immediately followed by a precedence line that
lists `HTTPS_PROXY`/`ALL_PROXY` as fallbacks. The intent (the *library* ignores env vars; the
*gateway* resolves one itself) is recoverable from the surrounding lines, but a one-clause
clarification would remove the ambiguity.

## Cannot verify from diff (⚠️ — PM to resolve)

1. **Commit-message hygiene for `f4af1aa`** — commit messages are not part of the diff artifact
   and the dispatch forbids re-running git. Implementer report §2(d)/§5 asserts a clean scan.
2. **Two docs claims with no pin in this diff:** the `ArgsException("尚未安装第三方请求库或未注册
   自定义第三方请求库")` string and "the endpoint answers HTTP 412 to the `dm` shape and to a missing
   `w_webid`" (`docs:104-130`). Both trace to plan §Problem D1/D3 and Task 3's implementation;
   no test in this diff asserts them, so a line-by-line docs-accuracy audit should confirm
   against Task 3's evidence.
3. **Plan §Acceptance baseline drift:** the plan still states "865 passed, 2 skipped" while Task
   4 and Task 5 reports record 892 passed, 2 skipped. Plan-text staleness, not a diff defect.
4. **Post-diff governance:** that the Important 1 docs correction and the Task-3/Task-5 spec
   annotations land before merge (PM-owned; I did not judge them here).

## Assessment

**Task quality: Needs fixes**

Scope of the required fix: **docs-only, one block** (`docs/metadata-storage.md:197-210`, with the
one-line reword at `:199`), optionally the four Minor wording/command clarifications — cheapest
bundled into the same edit pass. No test, adapter, DTO, ingestor, schema, or CLI change is
implied, and no live re-run is required to close it.

Everything Task 4 executed is verified sound: the strengthened happy-path assertions are
non-vacuous and strictly stronger than the previous set (and are now live-satisfiable — Task 5's
successful run exercised every one of them on the real path: `videos=30 parts=33 discoveries=30
page_rows=1 cursor_next_page=2`); the anonymous bounded-failure branch still cannot be mistaken
for success; the skip-by-default gate, the one-page/temporary-root bound, and the scope guard all
hold; and I found no unsupported technical claim in the backend, proxy, or live-smoke
documentation other than Important 1. The Important finding is a supersession by D4/Task 5, not a
defect in Task 4's execution — but it is inaccurate as shipped, so the task is not clean until
the docs block is corrected.

## Revalidation

**Round:** fix wave 1 (targeted re-review of my own Task-4 findings).
**Range:** `f44066c..5667844` — exactly one commit, `5667844` *"docs(metadata): reconcile page-size/live-smoke prose
with the shipped 30 default"*, 6 files, +63/−30. `git log f44066c~1..5667844` confirms the wave is that single commit.
**Worktree state at revalidation:** branch `fix/20260911-live-metadata-path-fix`, HEAD `5667844`,
`git status --porcelain` empty.
**Diff-artifact integrity:** `review/fix-1-diff.md` is **byte-identical** to `git diff f44066c..5667844`
(204 lines, `diff -u` empty) — the claims below were checked against the diff, the artifacts, and the post-fix
worktree, not against the fix report.
**Discipline:** read-only; no git mutation, no checkout/push, no `BILI_LIVE_SMOKE` (verified unset), no live
network call, no credential value read or echoed (only presence checks on `.env` / `.venv` paths). The only
command executed was the dispatch-sanctioned offline focused suite plus read-only `git diff`/`log`/`status`
and greps.

### Per-finding verification

**I1 (Important) — RESOLVED, verified.**
- `docs/metadata-storage.md:210` now reads `(the then-shipped page size of 100)` — the appositive is a dated
  reading, and the whole 2026-09-11 observation (risk-control refusal, `-400`, the `ps=5` probe with
  `observed_total=1691`, the later 412s) is preserved verbatim as what was observed that day (`:208-218`).
- The superseded tail is gone; `:219-226` is a new settled bullet: `ps=30` → `code=0` with 30 items, `ps=50`
  → `code=0` with 50 items, `ps=100` rejected (HTTP 412 on the probes, JSON `-400` on production runs), and
  the shipped `PAGE_SIZE = 30`. The un-settled sentence ("Whether the endpoint also caps `ps` below 100 was
  not settled") no longer exists anywhere.
- Cross-checks all hold: `src/bili_asr/services/metadata_ingest.py:50` → `PAGE_SIZE = 30`;
  `README.md:509` → "(the ingestor's page size is 30)"; `src/bili_asr/sources/models.py:98-100` → protocol
  default 30 + "upstream answers `ps=100` with its bounded `-400`/HTTP 412 rejection"; `src/bili_asr/config.py:30`
  → "page size of 30 (300 videos)". The intra-branch contradiction I cited (docs 100 vs README 30) is gone.
- Consistency with the plan's evidence: the settled bullet matches plan §Problem **D4** (`ps=30`/`ps=50`
  → `code=0`; `ps=100` → HTTP 412 + JSON `-400`) and its §Locked decisions "Docs" bullet. The claim "which is
  also the pinned package's own documented `ps` value" is consistent with the pinned-config mirror
  (`tests/fixtures/fake_bilibili_gateway.py:73`, `"ps": "const int: 30"`) and plan D4.
- Repo-wide sweep for stale "current page size = 100": none left. The remaining `ps=100` / "100" sites are all
  either explicitly the rejected former value (`metadata_ingest.py:46`, `models.py:99`,
  `test_bilibili_api_gateway.py:219`, `docs:222`) or the dated reading (`docs:210`); `README.md:321-322` is an
  unrelated 100-target batch limit. No `ps=100`/page-size-100 claim remains in `{KNOWLEDGE_DIR}` or `docs/`.

**M1 (Minor) — RESOLVED, verified.** Both documented commands now end `-s -v` (`docs:164-165`,
`README.md:571-572`) and both carry the rationale — pytest captures the stdout of a *passing* test, so a plain
`-v` run hides the evidence line on the happy path and forces a second page request (`docs:171-174`,
`README.md:577-580`) — plus the operator instruction to use `-s`/`-rP` on the first live attempt. A grep for
`test_live_metadata_smoke.py` across `docs/` and README finds only those two command sites, so no third
`-v`-only recipe survives. The technical claim is accurate (`-s` disables capture; `-rP` reports passed tests'
captured output).

**M2 (Minor) — RESOLVED, including the disclosed widening, verified.**
- `docs/metadata-storage.md:186-188` and `README.md:582-584`: the credential is now scoped to `BILI_SESSDATA`
  only, with the reason stated (the smoke builds its own `fetch-meta` argv and passes no `--sessdata`).
- Disclosed widening checked: `tests/test_live_metadata_smoke.py:341-347` (f-string at `:344`) no longer offers
  `--sessdata`. It is a string literal in a `pytest.skip(...)` message, and **nothing asserts it**: grep for
  `.msg` / message fragments in the smoke file finds no consumer, the skip path is unreachable offline, and the
  focused suite reproduces `1 passed, 1 skipped`. Same defect, same file as M3, disclosed in the fix report
  §1 (M2) and §4 — a legitimate one-step widening, not piggyback scope creep.
- The CLI-level credential boundary prose that legitimately still says "`--sessdata` or `BILI_SESSDATA`" for
  `fetch-meta` (`README.md:519-525`, `docs:75-83`) is untouched and correct for that surface.

**M3 (Minor) — RESOLVED by wording; the implementer's pushback is technically correct and I uphold it.**
- Wording now matches the assertion at both cited sites: docstring `:138-140` ("at least one part row in
  aggregate over the collected page (not one per video: an individual video may have no parts upstream)") and
  the inline comment `:206-209`. The assertion itself is unchanged (`assert part_count >= 1`, `:210`).
- Rationale verified against source, not taken on trust: `bilibili_api_gateway.py:206-211`
  `_normalize_video_parts` raises only when the pagelist is **not** a list and otherwise returns
  `tuple(...)` — an empty pagelist is therefore a legitimate `()`, so a per-video non-empty claim is not an
  upstream invariant; the ingestor fetches parts once per distinct video and aggregates them
  (`metadata_ingest.py:242-249`, `part_count=len(upserted_parts)` at `:325`) without any per-video requirement;
  and `videos` (`storage/schema.sql:10-19`) persists `bvid/aid/mid/title/pubdate/created_at/updated_at` — **no
  part count** — so the stronger per-video form the review sketched is not computable from persisted state.
  Asserting it would convert a legitimate live shape into a spurious smoke failure. My original M3 offered
  "tighten **or** soften"; the soften branch is the correct one, evidenced.

**M4 (Minor) — RESOLVED, verified.** Both command blocks now build on `CONTROL=/root/workspace/bilibili-asr-archive`
for `.env` and the interpreter (`docs:160-165`, `README.md:567-572`) and both state that the control checkout owns
`.env`/`.venv` while a linked worktree has neither (`docs:168-174`, `README.md:574-577`). Presence-verified
read-only: control `.env` and control `bilibili-asr-archive/.venv/bin/python` exist; the feature worktree has
neither. The commands are syntactically sound — running the closure of the documented command is exactly the
sanctioned command I executed (`cd <package>; <control python> -m pytest tests/test_live_metadata_smoke.py -v`),
which resolved and ran.

**M5 (Minor) — RESOLVED, verified.** `.env.example:18-20` no longer contradicts itself: the *library* bypasses
`HTTPS_PROXY`/`ALL_PROXY`, the *gateway* resolves a proxy itself (including those variables) before the request —
coherent with the precedence line at `:21-22` and with `config.py`/`bilibili_api_gateway.py` as reviewed in the
Task-4 round. `:24` now labels the example value as non-default. `:30-31` `# BILI_KEEP_AUDIO=0` matches the
documented default and the code path that retains audio only on `== "1"`
(`src/bili_asr/audio_reclaim.py:46`), so the commented value no longer contradicts its own comment.

**Task-5 minors (#7, #8) — RESOLVED, inertness independently confirmed.**
- `config.py:30-31` comment "page size of 30 (300 videos)"; `DEFAULT_PAGE_LIMIT = 10` and every other line
  unchanged (comment-only, verified by reading the post-fix file).
- `tests/fixtures/fake_bilibili_gateway.py:479` `"ps": 30`: **inert, proven**, not assumed. Nothing reads the
  scripted response's `ps` — the adapter reads only `page.count` (`bilibili_api_gateway.py:87-100`) and no
  `src/` code reads a response `ps` at all; no test indexes `["page"]["ps"]`. The request-side `ps` assertions
  in tests (`"space.arc.search(pn=1, ps=30)"` / `ps=50`) come from the adapter default and the per-call argument,
  not from this helper; the seam's `params.get("ps")` (fixture `:392`) reads the *request* dict. The `ps` field
  itself was kept, preserving fixture fidelity.

### Regression lens (fix diff)

- **No product logic changed.** Every hunk classifies as prose, comment, or inert string literal:
  `.env.example` (comments), `README.md` + `docs/metadata-storage.md` (prose and command recipes),
  `config.py` (`#:` comment only), `fake_bilibili_gateway.py` (one dict literal, proven unread/unasserted),
  `test_live_metadata_smoke.py` (one docstring, one comment, one skip-message string literal). No assertion,
  branch, control flow, constant, DTO, schema, CLI surface, dependency, or packaging line was touched —
  confirmed by reading the full real diff, not the artifact summary.
- **Stale-prose sweep:** no site anywhere still describes 100 as the current page size (see I1 above).
- **Hygiene:** `git diff --check f44066c..5667844` → clean (exit 0, no output). Worktree tree clean at HEAD.
- **Sanctioned offline command:** `1 passed, 1 skipped` (live arm SKIPPED without `BILI_LIVE_SMOKE`; offline
  rehearsal PASSED) — count-identical to the pre-fix baseline the fix report records (`1 passed, 1 skipped`).
- **PM-owned spec corrections consistent with shipped code:** `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/
  specs/bilibili-api-gateway.md:48` protocol default `page_size: int = 30` == `models.py:99-100`; the page-size
  annotation (spec `:70-77`) states the same settled evidence as the new docs bullet and plan D4; the clause-1
  rewrite (spec `:80`) reads "One bounded page of the user's videos, `ps=30`". The spec's own `ps=100` mentions
  now sit only inside the amendment text as the rejected value. The implementer's "reported, not edited" note for
  that file is correct: it is PM-owned and already dispositioned.
- **No new documentation inaccuracy introduced** by the fix hunks: each new claim is traceable (pytest capture
  semantics; the smoke's argv and its `os.environ.get(SESSDATA_ENV_VAR)` gate at `:337`; control `.env`/`.venv`
  presence; `_normalize_video_parts` empty-list shape; `audio_reclaim.py:46`).

### Cannot verify from this round (⚠️ — unchanged residual risk)

1. **Full-suite `894 passed, 2 skipped`** — implementer-reported; the dispatch forbids re-running the full suite.
   Statically corroborated here in the only way available: the changed lines cannot alter behaviour (prose /
   comment / string-literal / proven-inert fixture literal), and the focused suite reproduces its baseline
   counts. The plan's own acceptance line has been updated to the same 894/2 figure (PM-owned).
2. **Task-5's live evidence** (`videos=30`, exit 0) is not re-run here — no live network run is sanctioned for
   this seat; it remains Task-5 evidence.
3. **Commit-message body hygiene** for `5667844` — subject line read via `git log`; body not audited (not part
   of this revalidation's scope).

### Updated severity counts

| Severity | Before revalidation | After revalidation |
|---|---|---|
| Critical | 0 | 0 |
| Important | 1 (I1) | **0** |
| Minor | 5 (M1–M5) | **0** |

M1–M5 all closed by the wave; M3 closed as resolved-by-wording with the reviewer's pushback upheld on verified
evidence. One non-blocking advisory remains (below), and it does not change the verdict.

**O1 (advisory, no action required).** The documented live-smoke recipe now hardcodes the absolute path
`/root/workspace/bilibili-asr-archive` as `CONTROL` (`docs:160`, `README.md:567`), which is new — no prior
absolute path existed in those docs. This is acceptable here: the recipe is already host-specific (fixed UID,
count-only bound, loopback proxy example, "on this host"), the value is the workspace's real control checkout,
and the following paragraph tells the operator what the path must point at. If the docs are ever published for
other operators, `CONTROL` is the single line to parameterise.

### Verdict

**Approve.**

All five Minor findings and the one Important finding I raised in the Task-4 round are resolved in `5667844`,
verified against the post-fix worktree rather than the fix report; the two disclosed widenings (the smoke's
skip-message string and the M3 docstring site) are the same defects in already-authorised files, are string/
wording-only, and are honestly disclosed; the wave is behaviour-free with the inert fixture literal and the
failure-free `-s -v` commands as its only non-prose deltas besides comments; the diff is clean
(`git diff --check`), the artifact matches the real diff byte-for-byte, and the PM-owned spec/spec-text
corrections agree with the shipped code (`PAGE_SIZE = 30`, protocol default 30, `ps=100` rejected).
No blocker remains on this seat for the plan's continue-to-QA decision. Disposition/staleness of the remaining
historical `ps=100` references (the annotation in the pinned iteration spec) stays PM-owned, as recorded.
