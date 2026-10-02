---
plan_id: store-route-expressiveness
project: _default
status: draft
created_at: 2026-10-02
execution_mode: inline
plan_parallelism: serial
---
# Store-route expressiveness (F7 residual + R13/R15)
## Status
- **Priority**: P1 · **Effort**: M · **Risk**: MED · **Depends on**: none · **Category**: bug · **Confidence**: HIGH
- **Evidence**: R13 (`schedule` cannot reach the legacy manifest queue route; 12 fixtures can't be pinned) + R15 (store route can't express "meta_ok, go harvest" through `pilot`; `entry_for_item` relabels a harvest-eligible row `needs_audio` which `_PILOT_SKIP_HARVEST` skips). Both share a root: the store route lacks a harvest-eligible state distinct from `needs_audio`.
## Problem
The store route cannot express a harvest-eligible row. A stored `meta_ok` row (real metadata, no caption yet) should be harvestable, but `entry_for_item` maps it to `needs_audio` (audio queue), and pilot skips `needs_audio` for harvest — so the harvest branch collapses and the 12 fixtures can't pin the intended behaviour.
## Approach
Give the store route a way to express harvest-eligible. Option (a): `entry_for_item` returns a distinct status (or a harvest-eligible flag) for a `meta_ok` row with no stored transcript, instead of relabeling it `needs_audio`. Option (b): exclude such rows from `_PILOT_SKIP_HARVEST`. Prefer (a) — a dedicated state is clearer. Ensure `download-audio --missing-subs` and the chain still select correctly. Pin the 12 test_scheduler/test_long_live fixtures to the now-expressible behaviour.
## Files: `src/bili_asr/services/queue_source.py` (entry_for_item), `src/bili_asr/cli/pilot.py` (_PILOT_SKIP_HARVEST), `src/bili_asr/cli/parser.py` (schedule --queue-source is contract-closed per §7, do NOT add), tests/test_scheduler.py + tests/test_long_live.py (the 12 fixtures).
## Verification: the 12 fixtures pin the intended behaviour; test_pilot + test_mixed_outcome_contract green; the asr/pilot/store pinning tests (test_cli_queue_source) still pass.
## STOP: if expressing harvest-eligible requires widening the frozen queue-source contract (§7), STOP + report — do not breach the contract.
## Done (RE-SCOPED 2026-10-02 — plan §STOP clause honoured)
Delivered: `entry_for_item`'s gap→status mapping names `missing_subtitle`→`meta_ok` (the
harvest-eligible state) instead of collapsing it to `needs_audio`, plus `select_pending_scope`
restating it.  NOT delivered: the 12 `test_scheduler`/`test_long_live` fixture pins — a row
holding a stored caption sits in NO gap view (`v_part_pipeline` reports it `transcribed`), so
selecting it for archive needs a selection surface that would widen the frozen queue-source
contract (§7), which this plan's STOP clause forbids.
Residue registered: **I-000156** (store route cannot express a captioned-but-unarchived row,
medium — the 6 remaining fixtures) and **I-000157** (`test_cli_pilot` manifest-snapshot
fixture gap, low).  Evidence + attribution: `.mstar/sdd/store-route-expressiveness/progress.md`.
Round-2 QC also observed the delivered mapping is behaviourally inert (the override already
forces the value) — registered as a low residual with the design note.
