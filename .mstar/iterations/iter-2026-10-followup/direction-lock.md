# Direction Lock — iter-2026-10-followup

**Mode**: autonomous (`/iteration-loop` opt-in; user direction = "继续迭代，解决掉issues，然后推进P3和R14")

## Locked direction

Land the 2026-10-02 QC residuals (W1–W4 + S1), the ASR→store transcript write-back (high
residual R14), and the four deferred P3 audit plans (005, 006, 008, 010).

## Rationale

Ranking (autonomous-direction-lock § heuristics):

1. **Deferred / roadmap-next** — the prior iteration (`iter-2026-10-audit-burndown`) explicitly
   recorded as next-iteration: P3 plans 005/006/008/010, high residual R14, and the QC
   W1–W4+S1 residuals it registered. This iteration picks that up directly.
2. **User instruction** — "解决掉 issues，然后推进 P3 和 R14" is the direction constraint; all
   candidates below map to it.
3. **Risk / blast radius** — the QC residuals are small, well-scoped, and reviewer-evidenced;
   R14 is the largest (a real store-architecture change) but is the load-bearing correctness
   gap; the P3 plans are the audit's own prioritised tail.

## Acceptance criteria

- QC residuals W1–W4 + S1 fixed and verified (scoped tests green).
- R14: the ASR/archive path records a `transcripts` row through the repository's own writer so
  `v_missing_transcript` converges; the two pinning tests
  (`test_asr_store_source_selects_transcript_gap_part`, `test_pilot_store_source_uses_gap_views`)
  pass.
- P3 plans 005, 006, 008, 010 implemented + merged.
- All plans through per-plan lifecycle; one PR to `main`; no unresolved critical.

## Non-goals

- The P3 security Needs-verification leads (httpx TLS posture; WBI seeding) — runtime probes.
- The other already-registered residuals beyond W1–W4+S1 (they stay registered, not in scope).
- R13/R15 (store-route expressiveness) — folded into R14's owning plan context but not separate
  plans this iteration.

## Scale budget

**XL** → 5+ business plans. Scope: W1–W4 (4 fixes) + S1 (folded into W4) + R14 (1) + P3
005/006/008/010 (4) = **9 business plans** (S1 rides with W4).
