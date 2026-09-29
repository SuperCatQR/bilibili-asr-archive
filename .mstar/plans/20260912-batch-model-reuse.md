# Batch model reuse on the documented path

> Iteration `iter-2026-09-asr-ops-hardening`, spec point 2 → acceptance **A2**.
> Primary spec: `.mstar/iterations/iter-2026-09-asr-ops-hardening/specs/02-batch-reuse.md`.
> Execution mode: `sdd` (3 tasks).

## Status

- Priority: P0
- Task category: `logic` / CLI throughput contract
- Status: Done
- Depends on: nothing (independent of P1/P3/P4)
- Owner: fullstack-dev · QA gate: pm-acceptance
- Findings cleanup: zero-residual
- Evidence: audit guide §4.2; `{KNOWLEDGE_DIR}/architecture-patterns/run-scoped-asr-provenance.md`

## Goal

A batch that transcribes N items constructs the model once, says so in its own output, and
the documentation states which command to use so the reuse is not forfeited.

## Specify (measured defects)

- **B1.** The run-scoped reuse contract is designed and implemented on the coordinator path
  (`coordinator.py:494` builds one `ASRRunner` per run scope), but the ten-video batch was
  driven by a per-item `bili-asr asr --bvid …` loop: 21.8 min total ≈ 16.3 min decode +
  ≈ 5.6 min per-item overhead (26 %) — dominated by reconstructing a 2 GB checkpoint per
  video.
- **B2.** Nothing in the CLI output tells the operator whether reuse happened; the only
  reuse oracle lives in the test fixtures.
- **B3.** `README.md` documents the batch commands but never says that a per-item loop
  forfeits reuse, nor that the in-process loops of a single `asr --pending --limit N`
  invocation are themselves a run scope that must hold one runner.

## Clarify (decisions — spec 02 owns the detail)

1. **Observable proof**: `ASRRunner.model_constructions` (a monotonic counter) is surfaced as
   `RunSummary.model_constructions` for the batch delta plus `RunSummary.asr_items`, printed
   once as `model constructions=<n> for <m> asr item(s)`.
2. **No new CLI surface**: the documented path is the existing coordinator command
   (`bili-asr run --scope pending`; `schedule`/`campaign` wrap the same run-batch).
3. **In-process loops must hold one runner**: `_cmd_asr` and `_pilot_archive_asr` construct
   one runner for all items of the invocation, so the printed count is true for them too.
   `asr.transcribe()` keeps its one-shot contract.
4. **Docs carry the literal strings** the acceptance check greps: `model constructions=`,
   `forfeits that reuse`, `bili-asr asr --bvid <bvid>`.

## Non-goals

- Any wall-clock speed-up claim or benchmark; parallel transcription; changing the
  coordinator's ownership/release semantics; a new batch subcommand.

## Architecture

| Surface | Change |
|---|---|
| `src/bili_asr/asr.py` | `ASRRunner.model_constructions` counter; provenance unchanged |
| `src/bili_asr/coordinator.py` | `RunSummary.model_constructions` / `.asr_items`; one printed line |
| `src/bili_asr/cli.py` | `_cmd_asr`, `_pilot_archive_asr` hold one runner per invocation |
| `README.md` | Batch guidance + the reuse warning |
| `tests/test_asr_reproducibility.py`, `tests/test_cli_asr.py`, `tests/test_cli_pilot.py` | Construction-count assertions; CLI stubs move to the runner seam |

## Tasks

### Task 1: Construction counter and the run-summary line

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/asr.py`
- Modify: `bilibili-asr-archive/src/bili_asr/coordinator.py`
- Test: `bilibili-asr-archive/tests/test_asr_reproducibility.py`

**Interfaces:**
- Consumes: the existing `ASRRunner` construction seam (`model_factory`) the fixtures already count.
- Produces: `ASRRunner.model_constructions` (monotonic int); `RunSummary.model_constructions` (per-batch delta) and `RunSummary.asr_items`; one printed line.

- [x] Add the monotonic counter to `ASRRunner`, incremented exactly where the model is constructed.
- [x] Surface the per-batch delta plus the ASR item count on the run summary.
- [x] Print exactly one line per batch: `model constructions=<n> for <m> asr item(s)`.
- [x] Test: a ≥3-item run through the documented path asserts `model_constructions == 1`, extending the existing counting fixture and the reuse oracle; the line format is asserted once.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_asr_reproducibility.py -v`

### Task 2: One runner per CLI invocation

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/cli.py`
- Modify: `bilibili-asr-archive/src/bili_asr/campaign.py` (label wiring for `campaign`'s line)
- Test: `bilibili-asr-archive/tests/test_cli_asr.py`
- Test: `bilibili-asr-archive/tests/test_cli_pilot.py`
- Test: `bilibili-asr-archive/tests/test_campaign.py` (assert `campaign`'s stdout stays a single JSON document)

**PM decisions carried into this task (Task-1 review):**
- The constructions line goes to **`stderr`** (spec D2.6 as amended): `campaign` prints its summary as pure JSON on
  stdout, so a stdout line breaks every JSON consumer. Task 1 measured this against the real coordinator.
- `schedule`/`campaign` must print their own command label, not `run` (the seam exists; the wiring is here).
- `asr`/`pilot` never enter `run_batch`, so they print via the shared helper from their own in-process loops.

**Interfaces:**
- Consumes: Task 1's counter and `RunSummary` fields.
- Produces: `_cmd_asr` and `_pilot_archive_asr` each holding one runner for all items of their invocation, released at the end.

- [x] Build one runner per invocation in `_cmd_asr` and `_pilot_archive_asr`; release it in a `finally` so an exception cannot leak the model.
- [x] Keep `asr.transcribe()`'s one-shot contract untouched.
- [x] Move the CLI test stubs from `asr.transcribe` to the runner seam (`asr._load_default_model` + `BILI_ASR_DEVICE=cpu`) without weakening any existing assertion, and add an assertion that one invocation constructs the model once.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_cli_asr.py tests/test_cli_pilot.py -v`

### Task 3: README batch guidance and the reuse warning

**Files:**
- Modify: `bilibili-asr-archive/README.md`

**Interfaces:**
- Consumes: the documented coordinator path (`bili-asr run --scope pending`) and the printed line from Task 1.
- Produces: the batch section the acceptance check greps.

- [ ] Document the batch command, the printed `model constructions=` line, and the sentence carrying the literal `forfeits that reuse` for a per-item `bili-asr asr --bvid <bvid>` loop.
- [ ] Keep the existing batch/scope documentation intact; add, do not rewrite.

Run: `cd bilibili-asr-archive && grep -n 'model constructions=\|forfeits that reuse\|bili-asr asr --bvid <bvid>' README.md`

## Verification

- A test asserts `model_constructions == 1` for a ≥3-item run through the documented path,
  extending the existing counting fixture and the reuse oracle.
- The suite's existing reuse assertions stay green; the recorded-token fixture is untouched.
- `grep -n 'forfeits that reuse' README.md` succeeds.

## Evidence log

| Date | Evidence |
|------|----------|
| 2026-09-13 | T1 `0d8b7c5` + fix `3a08989` — counter + per-batch line; review Request Changes (stdout broke `campaign`'s JSON) → spec D2.6 amended to stderr → Approved with Minor. |
| 2026-09-13 | T2 `e6b1fd5`/`cb4d587` + fixes `82ba5e3`/`0a1d354` — one runner per invocation, five labels, campaign stdout guarded; Approved with Minor after a fix round and a pilot-half guard round. |
| 2026-09-13 | T3 `b2f9550` — README publishes the batch path, the stderr line and the three greppable literals; suite 1422 passed. |
| 2026-09-13 | Plan QC tri (N=3, one batch): **all three seats `Approve with residuals`**, 0 Critical; seats 1/2/3 independently found the same Important (paid-but-empty batch printed nothing). Consolidated at `{SDD_DIR}/review/qc-consolidated.md`. |
| 2026-09-13 | QC fix wave `8b5ac50` (I1, W1–W4, W2b, F-02, S1, S2) → re-review `Approve with residuals`; CLI-side F-02 guard was unpinned and the spec still had two stale `stdout` clauses. |
| 2026-09-13 | Spec amend: the table row and the "zero-ASR prints nothing" clause corrected; D2.6 now reads "prints when `asr_items > 0` **or** `model_constructions > 0`, on stderr". |
| 2026-09-13 | Guard patch `035125c` — CLI F-02 pin added; mutant now fails. **Suite at head: 1432 passed / 4 skipped.** A6 byte-intact. |

## Review Gate Summary

| Gate | Decision | Notes |
|------|----------|-------|
| Task reviews | Approved with Minor ×3 | 0 Critical / 0 open Important after two fix rounds and one guard round |
| Plan QC | **Approve with residuals** | tri-review N=3 (one batch), 0 Critical, one convergent Important closed by `8b5ac50` + `035125c`; final re-review `review/qc-fix-1-review.md` |
| QA gate | pending | residuals R1 (low), R2 (low) registered |

**Seat 3's honest framing (adopted):** the coordinator already reused one runner at the base commit, so this plan
by itself would not have saved the measured 5.6 minutes — a per-item `asr --bvid` loop still pays per process.
What it changes is that the in-process loops now honour the rule and the cost is **visible**
(`5 × asr --bvid` → five `constructions=1 for 1` lines vs `1 × asr --pending --limit 5` → one
`constructions=1 for 5`).
