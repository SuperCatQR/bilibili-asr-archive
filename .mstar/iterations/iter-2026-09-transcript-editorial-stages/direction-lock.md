# Direction lock（autonomous route）

> Lock-time record, lands **before** the `direction-lock` anchor and before the compass draft (§1.2).
> Kept in the package permanently after the draft carries its five fields across.

## Locked direction

Add **校对 (proofread)** and **精校 (polish)** to the pipeline as two **supported, verifiable stages**: the
mechanical half ships as commands that build the two-route alignment artifact and verify proofread /
reading-edition candidates against the criteria the 2026-09-22/23 wave established, and the **judgement
half ships as two loadable agent skills** so the stages are repeatable instead of ad hoc.

> **Amended 2026-09-23 (user direction, at lock review).** The judgement half was originally "a contract
> so the stages are repeatable instead of ad hoc". The user's ruling: **design 校对/精校 as skills, let the
> AI do them, and let the programs check them** — i.e. the AI half must be a *loadable skill*
> (`SKILL.md`), not prose in an iteration spec, while the checking half stays the CLI commands. The
> original wording is kept above rather than overwritten; the amendment is the operative text from this
> date. Delivery of the skill: **committed in-repo as the single source of truth + one documented install
> step** (the host does not auto-scan repository directories, so an uninstalled skill does not load — that
> limitation is disclosed on the skill's own surface, not hidden).

## Rationale

- **User instruction (this round)**: "为项目的流程新增两个环节，校对&精校". The direction is user-locked;
  candidates below were ranked only to pick the *shape*, not the goal.
- **Measured absence of the capability**: the six-item wave produced proofread (`md/`) and reading-edition
  (`reading/`) products, but every tool that made and checked them lives outside the product —
  `.tmp/proofread-work/tools/{measure_reading,regen_merged}.py` (scratch, gitignored) and
  `/mnt/123pan/bili-asr-e2e/proofread-transcripts/` (target host). No shipped command can build the
  alignment source, verify a candidate, or refuse a bad one.
- **The wave's own defect record is the acceptance material**, registered in
  `{PROJECT_DIR}/_default/residuals.json`:
  - `20260922-proofread-wave · R2` (low): the alignment table's midpoint assignment **silently dropped 251
    of 9607 caption cues** — the durable lesson is a *counting* rule (every input item accounted, with an
    explicit "not attached" bucket), and it belongs in the artifact builder.
  - `20260922-proofread-wave · R1` (high): the ASR hotword list is also an **insertion source**. The
    verifiers must screen hotword-table tokens; the upstream fix stays its own registered row (non-goal here).
  - The `此在` blind spot (2026-09-23, reading-edition close): a hotword-table term *correctly retained* by
    the base was deleted by a "repeat" rule — the deletion-classification criterion needs a **term guard**.
- **Repo precedent for the shape**: `transcript-projection-publication.md` ("split the pure decision from
  the write") and the wave's own rule — **mechanical work in commands, judgement by agents** — so the
  stages ship the mechanical half only; the judgement protocol is a contract, not code.

## Ranked candidates (2–4) and why one won

| # | Candidate | Verdict |
|---|-----------|---------|
| 1 | **Proofread + polish as verifiable stages** (commands + contract + six-item corpus replay) | **Locked.** User-locked direction; closes the measured "we built it once, by hand" gap; fits repo precedent; replayable acceptance. |
| 2 | ASR hotword-insertion guard (`20260922-proofread-wave · R1`, high) — guard or document per-token provenance | **Deferred to next iteration.** It is upstream of both stages (evidence for why they matter), but its `target` is `src/bili_asr/asr.py` + the measurement family, a different blast radius; folding it in would exceed the M budget and mix directions. Kept in `## Roadmap Position`. |
| 3 | Consolidate the reading-edition delivery (index/README polish) into the product | **Folded into #1's polish plan.** Same files, no separate plan. |
| 4 | Pre-store archive-root reconciliation (`20260922-target-host-reconciliation · R4`) | **Not this direction**: operator archive hygiene, unrelated to the two stages. Stays a register row. |

## Acceptance criteria (iteration-level Done)

1. For a stored part carrying both routes (ASR + caption), an operator can **build the two-route
   alignment artifact** with every input cue/segment accounted (`count in == count out` + an explicit
   bucket for the unattached), and the counts are printed.
2. A **proofread candidate** can be verified against the contract: marker vocabulary and parity, per-change
   record completeness, character-level containment against both routes, and a **hotword-table screen** —
   refusing with named reasons, never with a bare failure.
3. A **reading-edition candidate** can be verified: no timestamps, character containment against its
   proofread base, **zero unexplained insertions**, every deletion classified
   (filler·noise / adjacent-repeat-with-retained-twin / fragment) with a **term guard**, marker parity,
   and — for multi-part items — seam checks plus concatenation fidelity.
4. The **six-item corpus replays** through both verifiers offline and reproduces the wave's recorded
   numbers (`gap 0`, per-item ratios, marker counts) — or any difference is explained by name.
5. Both stages are **documented on the surfaces an operator reads** (command `--help` + README/knowledge),
   including what the stage does *not* prove (no audio listening, judgement is the agent's).

## Non-goals

- **No re-proofreading / re-polishing of the six existing items** — their products are acceptance evidence, not subject matter.
- **No ASR hotword-configuration change** — `20260922-proofread-wave · R1` keeps its own trigger (next iteration).
- **No LLM/judgement inside deterministic commands** — the split is the point (repo precedent: split the pure decision from the write).
- **No new exit codes and no change to the frozen `0/1/2` taxonomy** for existing commands.
- **No real-device/GPU E2E** — the corpus replay reads files; it opens no socket and touches no device.
- **No migration/republication of existing products** — the stages add verification and recording, not a new artifact layout for what is already published.

## Scale budget

**`M`** → **3 business plans** (`20260923-transcript-proofread`, `20260923-reading-edition`,
`20260923-editorial-skills`). Amended 2026-09-23 with the user's skill direction: the third plan carries
the judgement half (two `SKILL.md` packages + the install/registration step), which the original two-plan
split had assumed would ride along as contract text. Still no process plans; the review chain / QC / QA /
close remain gates outside the budget.

## Branch resolve (autonomous)

1. Workflow snapshot for this iteration: **does not exist yet** (first lock) → skip.
2. Prior iteration compasses (all completed): `iteration_base_branch: main`, `target_branch: main`
   (repo convention, `AGENTS.md`); this iteration follows the same recorded policy.
3. `spec_integration_branch` defaults to `iteration/iter-2026-09-transcript-editorial-stages`.
   → **base `main`, target `main`, integration `iteration/iter-2026-09-transcript-editorial-stages`**.
