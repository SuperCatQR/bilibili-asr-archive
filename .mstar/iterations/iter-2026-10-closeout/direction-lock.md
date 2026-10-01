# Direction Lock — iter-2026-10-closeout

**Mode**: autonomous (`/iteration-loop`; user: "开始下一轮")

## Locked direction

Close out the open store/correctness residuals from the prior two iterations: finish the R14
ASR→store transcript write-back (coordinator/run-batch + subtitle-arm routes), decide and land
the 010 cluster-5 canonical-stem contract, and fix the pre-existing test drift (18 failures) so
the suites go green and stop masking regressions.

## Rationale

Ranking (autonomous-direction-lock § heuristics):

1. **Deferred / roadmap-next** — the prior iteration (`iter-2026-10-followup`) explicitly left
   as next: R14 coordinator/run + subtitle-arm write-back; 010 cluster-5 stem contract (needs a
   PM decision); the pre-existing 18-failure test drift (registered as a medium issue). This
   iteration picks those up.
2. **Product completeness** — R14 is the load-bearing store↔chain bridge; leaving the
   coordinator/run + subtitle routes unwired means the gap view still diverges on those paths.
3. **Risk / blast radius** — the drift fix is the highest-leverage (18 red tests mask real
   regressions); the R14 routes and stem contract are well-scoped follow-ons.

## Acceptance criteria

- R14: the coordinator/run-batch ASR path AND the subtitle-arm write-back record transcripts
  rows; the gap view converges on all routes; F7 (high) closed.
- 010 cluster 5: the canonical-stem contract is DECIDED (PM) and the three divergent stem
  implementations consolidated to the chosen contract, with the divergence table resolved.
- Test drift: the 18 pre-existing failures in test_scheduler/test_coordinator/test_metadata_cli
  are fixed; those suites go green.
- Findings cleanup allow-residual; no unresolved critical; one PR to `main`.

## Non-goals

- The other ~50 open residuals (security leads, WAL, raw-sidecar size, etc.) — not this round.
- R13/R15 (store-route expressiveness) — folded into the R14 route work context only.

## Scale budget

**L** → 3–4 business plans. Scope: R14-routes (1) + stem-contract (1) + test-drift (1) = 3.
