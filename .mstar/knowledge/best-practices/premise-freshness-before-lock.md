---
module: planning process (iteration scope, E2E scope, plan authoring)
date: 2026-09-20
problem_type: best_practice
category: best-practices
severity: medium
plan_id: 20260920-transcript-projections; 20260924-qwen3-asr-transformers
applies_when:
  - writing an E2E scope or an iteration scope whose branch depends on upstream or store state
  - inheriting a fact from a stored artifact (a previous run's manifest, a report, a snapshot)
  - authoring scenarios whose expected outcome may differ per branch
  - a script is about to remove or overwrite data whose source it has not read yet
  - a source path is a network mount, where a listing can succeed while reads fail
tags:
  - planning
  - e2e
  - scope
  - premise
  - evidence
  - irreversible-operations
  - destructive-setup
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

5. **On a destructive step, verify the source BEFORE removing anything — and the cost changes
   category.** Added 2026-09-26 from a real loss: a measurement script re-seeded its arm directories with
   `rm -rf` and then copied audio in from a WebDAV mount. The mount had begun answering every **read** with
   `401` while directory **listings** still succeeded from cache, so it looked healthy; the copy failed and
   the previous arms' audio was already gone. The only other copy was behind the same failing auth. Two
   rules follow, and both are cheap:
   - **Order: probe, then delete.** Check that the source is readable for **every** item you are about to
     depend on (a one-byte read per file is enough) and refuse otherwise. A guard that runs after the
     `rm` guards nothing.
   - **Prefer reuse over rebuild.** If the staged data is already present, keep it; make rebuilding an
     explicit opt-in flag. The common reason to re-run a setup step (changing an order, re-reading a
     config) then costs nothing at all.

   This is the same principle as items 1–4 with one difference that matters: for a scope premise the cost
   is wasted work, and for a destructive step the cost is **irreversible**. A reviewer who sees `rm -rf`
   and a remote source in one script should ask *what proves that source is live* before approving it.

## Why This Matters

The cost is asymmetric. The probe costs seconds; the stale premise cost a 30-minute host gate, a
re-dispatch, an hour of GPU-host work, and a QC round to explain — and, worse, it nearly produced a
false product conclusion ("the caption path is broken") when the truth was "the caption path had no
work to do".

## When to Apply

- Writing an E2E scope (`mstar-e2e` step 1) or an iteration's acceptance criteria.
- Any plan that asserts something about a live corpus, a network service, or another team's system.
- Reviewing such a scope: ask *when was this premise measured, and by what command?*
- Reviewing a script that deletes or overwrites: ask *what proves its source is readable, and does that
  check run first?*
- Whenever a source is a network mount or a remote service: listings can be cached while reads fail, so a
  successful `ls` is not evidence the data is there.
