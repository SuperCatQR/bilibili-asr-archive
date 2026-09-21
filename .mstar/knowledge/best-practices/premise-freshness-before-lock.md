---
module: planning process (iteration scope, E2E scope, plan authoring)
date: 2026-09-20
problem_type: best_practice
category: best-practices
severity: medium
plan_id: 20260920-transcript-projections
applies_when:
  - writing an E2E scope or an iteration scope whose branch depends on upstream or store state
  - inheriting a fact from a stored artifact (a previous run's manifest, a report, a snapshot)
  - authoring scenarios whose expected outcome may differ per branch
tags:
  - planning
  - e2e
  - scope
  - premise
  - evidence
related_components:
  - iterations
  - workflows
  - plans
---

# Re-verify a premise against its live source before you lock it

## Context

An E2E scope was written on 2026-09-20 from a fact that was true three days earlier: two long videos
"have no captions", read out of the *previous* run's manifest. The live source had since begun
serving AI captions for both. The chain correctly took its documented subtitles-first branch, the
queue correctly excluded them, and four of nine scenarios failed — not one of them a product defect.
The same scope had also allowed **two** outcomes in the scenario that discovered the branch (A3:
"a stored transcript, or an attempted-with-no-caption row — either is determinate") while its
downstream scenarios (A4/A5/A6/A8) assumed one of them.

## Guidance

1. **A stored artifact is evidence of the past, not a premise for the future.** Before locking any
   scope that depends on mutable external state (upstream availability, a store's contents, a
   remote service's behaviour), run the **cheapest probe that decides the branch** — here
   `probe-subs` over candidate parts, or a one-line count over the store's own relation — and record
   its output as the premise. Inheriting the fact from a report is exactly how a stale premise
   survives review.
2. **Never mix conditional and unconditional expectations in one scenario chain.** If one scenario
   admits two outcomes, every downstream scenario must either be written conditionally too, or the
   fixture must **force** one branch (and say so). A scope that is internally inconsistent will
   produce a run whose failures all trace to the inconsistency, which reads like a product failure
   until someone does the causal analysis.
3. **Say which premise the run would falsify, and what would change if it flipped.** One sentence per
   branch-conditional scope: "if the source now serves X, scenarios 4-8 have no work; that is a
   premise failure, not a defect."
4. **When the premise does flip, report the consequence in the run's own results** — the three
   failures here were reported as one finding (F5) with the causal chain, not as three defects. That
   is what let the fix be scoped to one iteration instead of three repair plans.

## Why This Matters

The cost is asymmetric. The probe costs seconds; the stale premise cost a 30-minute host gate, a
re-dispatch, an hour of GPU-host work, and a QC round to explain — and, worse, it nearly produced a
false product conclusion ("the caption path is broken") when the truth was "the caption path had no
work to do".

## When to Apply

- Writing an E2E scope (`mstar-e2e` step 1) or an iteration's acceptance criteria.
- Any plan that asserts something about a live corpus, a network service, or another team's system.
- Reviewing such a scope: ask *when was this premise measured, and by what command?*
