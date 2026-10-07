# Direction Lock — iter-2026-10-converge

**Historical proposal, corrected 2026-10-06:** the acceptance criteria below
record the original lock-time target. Delivery was re-scoped under the
[plan's STOP clause](../../plans/store-route-expressiveness.md): only the
missing-subtitle status mapping landed; the 12 fixture pins and full F7/R13/R15
closure did not. I-000156/I-000157 record the remaining obligations. The
[delivery compass](delivery-compass.md) records the corrected outcome and
historical baseline limits.

**Mode**: autonomous (`/iteration-loop`; user: "开始下一轮")

## Locked direction

Fix the 006 attempt-ledger regression (high), converge the store-route expressiveness gap
(F7 residual + R13/R15), and fix the search N+1 (search_blocks one-query-per-hit).

## Rationale

1. **Deferred / roadmap-next** — 006 regression is the highest-leverage open item (registered
   high last iteration, blocks 2 persistence_scale tests). F7's code converged but R13/R15
   (store-route expressiveness) remain. O-R3 (search N+1) is a registered pure-code perf item.
2. **Product completeness** — the store↔chain bridge (R13/R15) is the last load-bearing store
   gap; search N+1 is a user-visible perf defect on the read path.
3. **Risk / blast radius** — 006 is a surgical restore of a dropped contract; R13/R15 reuses
   the proven write-back seam; O-R3 is a localized query fix.

## Acceptance criteria

- 006: cross-process attempt numbering + strict malformed-history check restored under the
  flock; the 2 persistence_scale tests go green; single-writer batch perf preserved.
- Store-route expressiveness: `pilot`/`schedule` can express "meta_ok, go harvest"; the 12
  test_scheduler/test_long_live fixtures pinned; F7 issue + R13/R15 residuals closed.
- Search N+1: search_blocks issues bounded queries (no one-per-hit); snippet reads batched.
- Findings cleanup allow-residual; no unresolved critical; one PR to `main`.

## Non-goals

- The other open high (torch lock, 123pan WebDAV, SESSDATA dead-credential) — runtime/ops,
  need live measurement, not pure code.
- The other ~37 medium (raw-sidecar size, WAL, etc.) — future rounds.

## Scale budget

**M** → 2–3 business plans. Scope: 006-fix (1) + store-route-expressiveness (1) + search-N1 (1) = 3.
