---
spec: 02-batch-reuse
iteration: iter-2026-09-asr-ops-hardening
owner_plan: 20260912-batch-model-reuse
spec_point: 2 — Batch model reuse must be reachable and stated
serves: A2 (guard: A6)
status: draft — iteration-scoped, promoted or dropped at iteration-close
---

# Contract 02 — One run scope, one runner, one construction (with a count)

## Contract

Within one process, one run scope owns exactly one `ASRRunner`, therefore at most one model construction, and the run
prints how many constructions it paid. The documented batch path is the coordinator path (`bili-asr run`, with
`schedule`/`campaign` as bounded wrappers over the same coordinator); the two remaining in-process ASR loops (`asr`,
`pilot`) hold one runner per invocation; `README.md` states that a per-item `bili-asr asr --bvid …` loop forfeits
reuse.

## Decisions

- **D2.1 Documented path = `bili-asr run --scope pending [--offline]`.** `run` already reuses the runner
  (`coordinator.py` L494–495) and `schedule`/`campaign` call the same `run_batch` (`cli.py` L2215, `campaign.py`
  L327). `--offline` is the operator's already-downloaded case (operational-sidecars guidance 3 and the `--offline`
  rule, L99–103). *Rejected:* a new multi-item `asr` entry point — the coordinator path already answers the
  question, and the risk register prefers documentation plus the count over a new surface (compass L205).
- **D2.2 `_cmd_asr` holds one runner for its whole selection** (`cli.py` L1528–1606 currently calls the one-shot
  module wrapper `asr.transcribe` per item, L1584). One invocation of `asr --pending --limit N` is one run scope by
  the knowledge doc's own definition (run-scoped-asr-provenance L30), so it must not pay N constructions.
  *Rejected:* documenting the batch path and leaving `asr` per-item — README's per-item warning would then be false
  for `asr --pending --limit N`, the command the run actually used (guide L100–101).
- **D2.3 `_pilot_archive_asr` holds one runner threaded from `_cmd_pilot`** (today `cli.py` L1669 calls
  `asr.transcribe` per item). The frozen MVP proof command can transcribe up to `--n-1` items in one process, so the
  same rule applies. *Rejected:* leaving `pilot` out as "superseded" — it is still documented (`README.md` L118) and
  the defect class is identical.
- **D2.4 `asr.transcribe()` keeps its one-shot contract** (`asr.py` L595–600, docstring "one short-lived runner"):
  it is the single-item compatibility wrapper and its characterization test stays untouched
  (`test_current_transcribe_constructs_once_per_call_characterization`, L180–183). Only *loops* must hold a runner.
- **D2.5 Observable proof = a runner-level counter surfaced per batch.** `ASRRunner.model_constructions` (int,
  incremented in `_get_model()` only when a model is actually constructed; `release()` does not reset it) →
  `RunSummary.model_constructions` = constructions observed **within this batch** (`after - before`, so a
  caller-injected runner reused across batches reports per-batch truth) → one printed line. `RunSummary.asr_items`
  counts rows whose `asr` stage produced a transcript (the existing `asr: ok` attempt), so the line can state reuse
  rather than a bare number.
- **D2.6 Printed line, once per batch, when `asr_items > 0` or `model_constructions > 0`, on `stderr`:** `f"{command}: model
  constructions={n} for {m} asr item(s)"` with `command ∈ {run, schedule, campaign, asr, pilot}` matching the
  existing prefix convention (`cli.py` L2068). A batch with neither ASR items nor a paid construction (subtitle-only) prints nothing, so
  subtitle-only output is unchanged; a batch that **paid** a construction prints even when every row failed. **Amended at Task-1 review (2026-09-13):** the original draft said `stdout`; measurement showed
  that breaks `campaign`, whose stdout is a single JSON document (`cli.py`: `print(json.dumps(summary.to_dict(),
  ...))`) that downstream callers parse — the line landed inside the document and JSON parsing failed. `stderr`
  keeps A2's "the run's own output states that construction count" true while preserving every command's stdout
  contract. *Rejected:* printing per row (A2 asks for the batch's own count; per-row output is noise);
  command-specific streams (one rule is easier to state and test).
  **Amended again at plan-QC (2026-09-13):** the guard is "nothing was paid", not "no ASR items" — all three
  QC seats independently reproduced a batch that **constructed the model and failed every transcription**
  (`model_constructions == 1`, `asr_items == 0`) printing nothing, which hides precisely the first-decode
  failure the line exists to expose. The line therefore prints when `asr_items > 0` **or**
  `model_constructions > 0`; a subtitle-only batch (neither) still prints nothing. `README.md` publishes the
  same rule.
- **D2.7 README wording (A2's greppable statement).** The model paragraph near `README.md` L44–54 must contain:
  `model constructions=`, the phrase `forfeits that reuse`, and the literal loop form `bili-asr asr --bvid <bvid>` —
  meaning: one process per item pays one model construction per item. *Rejected:* prose without the printed-line
  form — "greppable" in A2 means the documented line and the shipped line are the same string.

## Exact names and shapes

| Surface | Name / value |
|---|---|
| runner counter | `ASRRunner.model_constructions` → `int` |
| batch fields | `RunSummary.model_constructions`, `RunSummary.asr_items` → `int` |
| printed line | `<command>: model constructions=<n> for <m> asr item(s)` |
| documented path | `bili-asr run --scope pending [--offline]`; `schedule`/`campaign` as wrappers |
| test seam | patch `bili_asr.asr._load_default_model` with the existing fixture factory and set `BILI_ASR_DEVICE=cpu` (the runner then still exercises the real `_get_model` path; test_asr_reproducibility.py's `fake_funasr` fixture is the counter) |
| new tests | (i) 3 ASR rows through `RunCoordinator.run_batch` with **no injected runner** → `fake.construction_count == 1`, `summary.model_constructions == 1`, `summary.asr_items == 3`; (ii) CLI `run --offline` on a ≥3-row fixture → **stderr** contains `model constructions=1 for 3 asr item(s)`; (iii) `asr --pending --limit 3` → 1 construction |
| kept tests | `::test_target_runner_reuse_oracle_is_target_facing` (L186), `::test_current_transcribe_constructs_once_per_call_characterization` (L180), `::test_fixture_benchmark_reports_only_construction_and_shape` (L313–330) |

## Boundaries — must not change

- Injected-runner ownership and release: `run_batch` re-installs the injected runner and releases only a
  coordinator-created one (`coordinator.py` L694–703) — run-scoped-asr-provenance L30. The count is read, never
  owned.
- No new subcommand; the frozen `bili-asr` surface is unchanged (`asr-archive-cli.md` L30–44). No
  `--limit`/`--scope` semantics change.
- Manifest, attempt ledger, campaign checkpoint, scheduler sidecar and exit precedence (`risk_interrupted` → 2,
  per-item failure → 1, all-terminal → 0; operational-sidecars L115–118) are untouched.
- Per-item failure must still continue the batch (`cli.py` L1599–1604, `coordinator.py` L497–505): a shared runner
  changes construction count only.
- Cue shaping and transcript text: `asr.py` L125–135 / L447–546, `tests/test_asr_cues.py` and
  `tests/fixtures/asr-cues/` are untouched — the recorded 2037-token fixture renders identically (A6).
- Existing CLI stubs that patch `bili_asr.asr.transcribe` in `tests/test_cli_asr.py` / `tests/test_cli_pilot.py`
  move to the D2.5 seam; their *assertions* (call targets, exit codes) are preserved, not loosened.

## Traceability

| Decision | Forced by |
|---|---|
| D2.1 | guide §4.2 L95–101 (`coordinator.py:494` reuse is the designed contract; run-scoped-asr-provenance L30) |
| D2.2, D2.3 | guide L100–101: "Invoking `bili-asr asr --bvid …` once per item — the form the run used — reconstructs the model every time"; 21.8 min = 16.3 decode + 5.6 overhead (26 %) at L28–30 |
| D2.5, D2.6 | A2: (stream amended to stderr at Task-1 review — `campaign`'s stdout is a JSON document) "the run's own output states that construction count"; design choice for the per-batch delta and the `asr_items` denominator |
| D2.7 | A2: "`README.md` states that a per-item `bili-asr asr --bvid …` loop forfeits the reuse" |
| D2.4 | design choice: one rule — loops hold a runner, the one-shot wrapper stays one-shot |

## Non-goals inherited

No throughput benchmark or speed-up claim (compass L121–124): the contract claims one construction, nothing about wall
clock. No manifest compaction, no concurrency enablement (operational-sidecars guidance 8/L105).

## Check the plan must run

The counter is only meaningful if the coordinator's construction site stays the one under test. P2 must confirm on the
fixture path that patching `bili_asr.asr._load_default_model` (not `ASRRunner`) makes `RunCoordinator.run_batch`
construct the fake once for ≥3 rows — i.e. that no second construction site hides in the ASR/archive stages. If a site
cannot hold one runner, the plan records a compass amendment request instead of shipping a half-rule.
