# QC Consolidated — 20260911-subtitle-gateway

- Iteration: `iter-2026-09-subtitle-transcript-sqlite` · Plan: `20260911-subtitle-gateway`
- Review range / Diff basis: `2bd333f..6002f99` (4 commits, 6 files, +3172/−59)
- Working branch (verified by all seats): `feature/20260911-subtitle-gateway`, HEAD `6002f99`, worktree clean
- Seats: `qc-specialist` (qc1.md), `qc-specialist-2` (qc2.md), `qc-specialist-3` (qc3.md) — initial tri wave, N=3

## Seat verdicts

| Seat | Verdict | Critical | Warning | Suggestion | Unconfirmed |
|------|---------|----------|---------|------------|-------------|
| qc-specialist (qc1) | Approve | 0 | 0 | 4 | 0 |
| qc-specialist-2 (qc2) | Approve | 0 | 0 | 3 | 0 |
| qc-specialist-3 (qc3) | **Request Changes** | 0 | **3** | 6 | 0 |

## Gate decision: Request Changes → fix wave, then targeted re-review

No Critical anywhere; the implementation is spec-compliant and every boundary holds (all three seats
verified against the **installed pin**, not the seams). Seat 3's three Warnings are coverage/traceability
scoped; two were PM-owned and are already fixed, one needs a test change.

### Warnings

| ID | Finding | Sources | Disposition |
|----|---------|---------|-------------|
| W1 | The locked `floor(seconds*1000)` rule has **no discriminating evidence**: every conversion literal in the suite multiplies out exactly, so a floor→round regression passes, and the live probe cannot discriminate (it prints converted ms only) | qc3 QC3-001 | **Fix now** — one discriminating row (e.g. `3.14159` → 3141 vs round 3142) in the seam-driven conversion test |
| W2 | Spec §9's "one `(bvid,cid)` from the operator's own archive" is unmet by the recorded run (`part_source=fixed-sample`; no archive DB on this host) with no governing reading — QA would have to guess | qc3 QC3-002 | **PM-fixed** — governing reading recorded in the plan's live-evidence section (authorized fallback; archive-db variant = bounded deviation, never "fixed" by fabricating an archive) |
| W3 | R1's registered target cannot discharge it (the CLI plan's file list does not include the adapter, and it is the iteration's last plan) | qc3 QC3-003 | **PM-fixed** — R1 retargeted to *the next plan whose file list includes `sources/bilibili_api_gateway.py`* (expected: the audio/ASR iteration); seat 3 re-verifies |

### Suggestions (deduped)

**Fix now (batched implementer round):**
- S1 (qc1 F-001, hardening): `_read_subtitle_document_url` rewrites only `//`; an absolute `http://` signed
  URL would be fetched in clear → upgrade non-https to `https:` or reject it, plus one test row.
- S4 (qc1 F-004): the test docstring denies a `user.User` delegate the adapter actually calls → re-word.
- S5 (qc2 QC2-002): add the offline assertion pinning the cancellation contract (seam already supports it).
- S8 (qc3 QC3-005): the probe docstring's live-surface bound understates the pin's one-time buvid bootstrap
  and retry budget → state the real bound.
- S9 (qc3 QC3-006): the README documents 1 of the 3 now-gated `BILI_LIVE_SMOKE` tests → complete the list.

**PM-fixed in this round:** S2 (qc1 F-002 — spec §1.3 dated framing note: the AI marker is an
upstream-document field, not pin-declared), S3 (qc1 F-003 / qc2 QC2-001 — HTTP-404 clarification; **location corrected 2026-09-11**: the first clarification landed in §1.3's transport-class sentence and the follow-up N-item carries the same exception into §4 item 3, so both point at section 5's table), S10 (qc3 QC3-007 — the
CLI plan's fixture line now names the deferred F3 double extension).

**Carried (recorded, not this plan's code):** S7 (qc3 QC3-004 — the anonymous credential tier is never
exercised live; QA gate / CLI plan own any live coverage), S11 (qc3 QC3-008 — no upper bound on converted
ms at any boundary; belongs to the storage plan's validation decisions), S12 (qc3 QC3-009 — the probe's
monotonic-timeline canary exceeds the storage contract; keep as a canary, do not read a failure as an
acceptance failure).

### Revalidation round (N=2: qc-specialist, qc-specialist-3)

Seat 1 revalidated the QC fix wave (`6002f99..9322239`) as **Approve**: F-001/F-002/F-003/F-004 all closed;
the S1 refusal branch **accepted** (strictly better diagnostics and network budget than the pre-wave
`transport_error` after arming the re-list; message provably cannot leak the URL); regression lens clean
(0 changed/removed assertions; exactly one production behaviour change plus an inert constants insertion;
metadata path unhunked). It raised two new PM-owned one-liners, both applied in this round: **N-1** (spec
§1.3's URL bullet now records the three accepted forms and the refusal) and **N-2** (spec §4 item 3 now
carries the "HTTP 404 excepted — section 5 governs" clause). Seat 3's revalidation is appended to qc3.md.

## Residuals

R1 (`user` module bound whole; `low`; `decision: defer`) — all three seats judged the defer legitimate;
seat 1 additionally verified against the engine's own `findingsCleanupGate` semantics that
`defer` + non-empty `target` is exactly what zero-residual accepts. Target corrected this round (W3).

## ⚠️ Hand-off to the mandatory QA gate

1. Reproduce the live probe against the shipped revision from the **worktree package dir** (so `conftest`'s
   `sys.path` insert wins; no worktree `.venv`), recording `part_source` and `sessdata=present|absent`.
2. Do **not** attempt to prove `floor` live (it would require raw subtitle JSON, forbidden by the plan's
   Global Constraints) — require the discriminating offline assertion instead.
3. Record the archive-db branch and the anonymous tier as bounded deviations if unreproducible.
4. Confirm the offline suite totals at HEAD and that the CLI plan has absorbed F3 (double extension) and R1.

## FINAL GATE DECISION (after the N=2 targeted re-review)

**Approve** — Critical 0 · Warning 0 · open Suggestions 0 · Unconfirmed 0 · open residual 1 (R1, `low`, `defer`).

- Seat 1 (`qc1.md` `## Revalidation`): **Approve** — F-001/F-002/F-003/F-004 all closed; the S1 refusal
  branch accepted (kept over the upgrade-only revert); regression lens clean (0 changed/removed
  assertions; one production behaviour change; metadata path unhunked). Two new PM-owned documentation
  one-liners (N-1 §1.3 scheme rule, N-2 §4 item 3's 404 clause) applied in the control checkout.
- Seat 3 (`qc3.md` `## Revalidation`, frontmatter `verdict: Approve`, `verdict_pass_1: Request Changes`):
  **Approve** — W1 closed on static grounds (the new row is the suite's only discriminating
  floor-vs-round case), W2 closed (durable governing reading in the plan; "unreachable here" independently
  re-established), W3 closed (R1's retargeted predicate is checkable and true by exclusion); S8/S9/S10
  verified landed; carries S7/S11/S12 accepted, with S11 now folded into the storage plan's Task 2.
- Seat 2 (`qc2.md`): initial **Approve** (3 suggestions, all PM-applied) — no re-review required.

Remaining open item is the registered defer R1 only (owner `@project-manager`, target = the next plan whose
file list includes `sources/bilibili_api_gateway.py`), which all three seats judged legitimate and which the
engine's zero-residual rule accepts (`decision: defer` + non-empty `target`).

Hand-off to the mandatory QA gate stands as listed above (live probe reproduction from the worktree package
dir recording `part_source` + `sessdata=present|absent`; the archive-db branch and the anonymous tier
recorded as bounded deviations if unreproducible; do NOT attempt to prove `floor` live; confirm the suite
totals at HEAD and that the CLI plan absorbed F3 + R1).
