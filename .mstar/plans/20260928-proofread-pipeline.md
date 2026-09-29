---
plan_id: 20260928-proofread-pipeline
iteration: iter-2026-09-ops-readiness
iteration_compass: .mstar/iterations/iter-2026-09-ops-readiness/delivery-compass.md
primary_spec: .mstar/specs/asr-archive-cli.md
blocked_by: []
qa_gate: mandatory
qa_mode: targeted
execution_mode: inline
execution_mode_reason: >-
  CORRECTED 2026-09-28. The original note claimed the host refused delegation on that session.
  That was wrong: `subagent` was available and four implementers DID run, each reporting DONE
  (they committed on their own worktrees; an early worktree check in the coordinating thread read
  "no commits yet" and wrongly concluded dispatch had failed, so the PM then re-implemented inline
  in parallel — the duplicate files later mistaken for phantom work came from those live
  implementers). The honest record: implementation was split between the dispatched implementers
  and the PM's parallel inline work on the same plans. `inline` is kept as the declared mode
  because the per-task SDD artifacts (brief/report/diff under {SDD_DIR}) are absent by
  construction — the implementer worktrees carry no `.mstar/` (gitignored) — so the SDD trail
  cannot be reconstructed from disk. The QC tri-review ran as a full N=3 read-only fan-out and is
  unaffected. For this new iteration, dispatch works and the Review chain is dispatched per spec.
status: registered
gate_decision: pass
gate_decision_reason: Prepare satisfied — method proofread-merge-v2 already validated on the 123pan corpus (78.6% block agreement vs 22.8% raw-segment), productization is roadmap P1
gate_decided_at: 2026-09-27
registered_at: 2026-09-27
planned_at_sha: main
agents:
  implementer: fullstack-dev
  task_reviewer: code-reviewer
  plan_qc: qc-specialist
  qa: qa-engineer
---

# `bili-asr proofread`: the merge-v2 method as a CLI subcommand

> **For agentic workers:** REQUIRED SUB-SKILL: `mstar-sdd`. Checkbox syntax.
>
> **Method source.** `proofread-merge-v2`, validated 2026-09-22 on `/mnt/123pan`
  (block size ~12 s from ASR VAD segments; similarity ≥0.85 agree / 0.75–0.85 minor /
  <0.75 review; the "midpoint-outside-VAD" criterion fabricates 23–27% false gaps and is
  banned; zero-overlap criterion shows the true gap count is ~0). The 20260922 wave's
  hard lessons are encoded as count-guard assertions in Task 2.

## Goal (intent gate)

**真实目标**：任何 operator 用一条命令得到机器预对齐的并排表 + alignment jsonl，
不必手工复现 2026-09-22 的临时脚本。**成功判据**：DoD。**非目标**：人工定稿循环
本身（sidebyside 判断仍由人/代理做——本 plan 只产出 inputs 与 merge 工具）；
review 波编排（已有手工协议）。

## Task 1: The `proofread` subcommand — two routes in, side-by-side out

> **Live-code fact (architect, Phase 1 review 2026-09-28):** a `proofread` implementation
> exists **only on the unmerged branch `feat/20260923-transcript-proofread`** (as
> `align-transcripts` + a corpus-validated verifier + `docs/editorial-stages.md` +
> `tests/test_editorial_cli.py`). It is **not on `main`**; nothing under
> `src/bili_asr/` on `main` references proofread. This plan therefore lands the
> merge-v2 method fresh on the integration branch and **reuses the branch's shipped
> readers/paths where they survive review** — Task 1's first step is a diff read of
> that branch against this plan's method spec (merge-v2 thresholds and the banned
> midpoint criterion below win over the branch's alignment criteria where they
> differ; the branch's editorial-stages doc is the adjudication protocol, which this
> plan explicitly does not rebuild). No cherry-pick without that read.

- [x] `bili-asr proofread <bvid> [--part N]` reads both routes for a part: the archived
  ASR transcript and the archived AI/live subtitles (existing readers:
  `list_stored_transcripts` + subtitle store).
- [x] VAD-block builder: cluster ASR segments into ~12 s blocks (the measured plateau;
  12→16 s adds nothing).
- [x] Similarity alignment per block (≥0.85 agree / 0.75–0.85 minor / <0.75 review),
  emitting `.tmp/proofread-work/inputs/<bvid>.p<N>.sidebyside.md` (time | ASR | 字幕,
  pure mechanical alignment — no adjudication) + `align/<bvid>.p<N>.alignment.jsonl`.
- Files: new `src/bili_asr/proofread.py` + `cli.py` wiring + `tests/test_proofread.py`.

## Task 2: Count-guards (the 20260922 lessons as assertions)

- [x] Guard A (coverage): every subtitle entry and every ASR character appears in exactly
  one block; a guard failure aborts with a non-zero exit and names the block.
- [x] Guard B (no fabrication): the banned "midpoint-outside" criterion must not exist in
  the codebase — a test greps the module for the pattern and fails if it returns.
- [x] Guard C (stability): re-running on the same inputs is byte-identical (determinism).
- Files: guards inside `proofread.py`; the three tests pinned.

## Task 3: `proofread-merge` — formalize the merge tool

- [x] Formalize the merge tool as a package module:
  `bili-asr proofread-merge <bvid> [--part N]` applies a completed sidebyside定稿
  (a marked-up copy with per-block decisions) back into a final transcript artifact,
  writing corrections accounting (per-block decision counts) next to the output.
  **Archive-source check (2026-09-28): no `tools/merge_proofread.py` exists on `main`
  or on `feat/20260923-transcript-proofread`** — the 123pan copy is fixture material
  only; it is imported/copied into `tests/fixtures/` (per Global Constraints), reviewed,
  and rewritten to package standards. Do not assume a repo copy to promote.
- Files: merge module (`proofread.py`'s merge half — no second top-level module)
  + CLI wiring + round-trip test (定稿 → merge → transcript equals the adjudicated
  text, corrections counted).

## Global Constraints

- Blocks are built from ASR VAD segments only; subtitles never define block boundaries
  (that was the 22.8% drift mistake).
- No filesystem writes outside the artifact root's `.tmp/proofread-work/` and the
  published transcript dirs.
- New names via `naming-analyzer`.
- `/mnt/123pan` paths appear only as test fixtures copied into `tests/fixtures/`, never
  as runtime dependencies.
- Contract home (architect, 2026-09-28): proofread thresholds (12 s blocks; ≥0.85 agree
  / 0.75–0.85 minor / <0.75 review), the banned midpoint-outside-VAD criterion, and
  count-guards A/B/C belong in a **new** warehouse spec `{SPECS_DIR}/proofread.md`,
  written by this plan's Task 3/DoD-4 step via PM change-control — **not** in the frozen
  `asr-archive-cli.md` (its README records frozen specs are never back-edited).

## Definition of Done

1. `bili-asr proofread BV...` produces the sidebyside table + alignment jsonl for any part
   holding both routes; exits non-zero with a clear message when a route is missing.
2. Guards A/B/C hold; the banned criterion cannot regress silently.
3. `bili-asr proofread-merge` round-trips a completed定稿 into the final artifact with
   corrections accounting.
4. The new spec `{SPECS_DIR}/proofread.md` names the thresholds and cites the
   2026-09-22 measurement. **MET 2026-09-28**: the spec is written and committed with this
   reconciliation (`feat` branch off main → merged), after being found untracked.

## Verification

- Fixture-driven tests from the archived wave's public shapes (synthetic bvids, both
  routes, including one disagreement-heavy part and one clean part).
- Task-scoped RED-before/GREEN-after per SDD brief.
