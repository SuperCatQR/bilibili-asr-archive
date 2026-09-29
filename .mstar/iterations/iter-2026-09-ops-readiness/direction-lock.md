# Direction lock — iter-2026-09-ops-readiness (autonomous, 2026-09-27)

## Locked direction
Close the archive's operational-readiness gaps: land the queue SSOT CLI wiring and operator
queue view deferred by iter-2026-09-coverage-truth, fix the hotword insertion-error source
(high residual), productize the proofread pipeline into the CLI, and add the missing
transcript retrieval (search) layer.

## Rationale
User instruction (this session): "挑搞优先级的做了，可用agentteam XL". Autonomous ranking
(heuristic 1 — deferred/roadmap-next) applied against `.mstar/projects/_default/roadmap.md`
(P0/P1 rows), plan 20260927-archive-db-queue-cutover `## Deferred` (D-1..D-5), plan
20260927-evidence-dashboard `## Deferred` (B-D1/B-D2), and residual `20260922-proofread-wave ·
R1` (high). These are the densest residual cluster and every downstream automation (cron,
dashboard, proofreading at scale) is blocked on the D-1 wiring. Roadmap P0 row says the same:
queue SSOT "一次迭代可消 5+ 条 medium residual".

Candidates scoped and their disposition:
1. queue-cutover CLI wiring + evidence-dashboard status view + tail docs (D-1..D-5, B-D1/B-D2)
   — WINNER-adjacent: merged into plan 20260928-queue-cli-cutover.
2. Hotword/provenance injection governance (roadmap P3 排版注入治理, high residual
   20260922-proofread-wave R1) — WINNER-adjacent: plan 20260928-hotword-injection-governance.
3. Proofread pipeline productization (roadmap P1: `bili-asr proofread` subcommand, merge-v2
   into CLI) — plan 20260928-proofread-pipeline.
4. Transcript FTS5 retrieval layer (roadmap "新增展望 — 检索层", no existing plan; repo already
   has a sealed 20260825-search-export-fts5 plan that was never implemented) —
   plan 20260928-transcript-search.
5. Interrupt resilience / large-input protection (roadmap P3) — DEFERRED to a later iteration
   (smaller shippable slices win when otherwise equal; capacity already at the XL cap).
6. Knowledge hygiene / README GPU self-check (roadmap P3) — DEFERRED, same reason.

## Acceptance criteria (iteration-level)
- `download-audio` / `asr` / `pilot` read the queue from `MediaQueueRepository` with a
  `--queue-source {store,manifest}` rollback flag; manifest is attempt-ledger-only on the
  read side; `derive-manifest` is deleted; a fresh archive.db-only root completes
  download-audio → asr (the cutover's final Done definition, D-1..D-5).
- `status` shows the three gap groups (contract §4: never sum) with top-20 default + `--all`
  + summary header; `coverage` prints a provenance note with reproduction command (B-D1/B-D2).
- `provenance.hotwords` can no longer inject characters into transcripts: word-boundary guard
  or removal from the inference path, with A/B measurement on the 6/9 unverified hotwords
  deciding keep-vs-drop per token.
- `bili-asr proofread` exists as a subcommand: two transcript routes in → side-by-side table
  + alignment jsonl out, with count-guard assertions (the 20260922-proofread-wave lesson).
- `bili-asr search <query>` returns matching blocks over archived transcripts (FTS5) with
  bvid + time-range, filterable by pubdate window; coverage figure reproducible locally.
- All five plans pass plan QC tri + QA gate; iteration closes with compound + roadmap update.

## Non-goals
- Interrupt resilience / SIGKILL journaling, large-input streaming caps (deferred; roadmap).
- Knowledge-base hygiene fixes and README GPU self-check (deferred; roadmap).
- Batch/campaign automation, cron daemon, GPU batch inference (later; needs D-1 landed first).
- Speaker diarization, hotword benefit A/B beyond the governance decision's own measurement.
- Any change to the parked transcript-editorial-stages integration branch (separate lifecycle).

## Scale budget
XL (>4 business plans). Resulting cap: 5 business plans (at cap).
Budget counting (HARD): only business delivery plans count; harness process (Review chain,
QC tri, QA gates, compound, close, PR, merge-ready) is mandatory but outside the budget.
