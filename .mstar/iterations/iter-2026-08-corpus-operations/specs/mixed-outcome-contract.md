# Mixed outcome and exit contract delta

The iteration standardizes observable partial-batch outcomes while preserving the frozen manifest status values and risk taxonomy.

This document is the aggregation SSOT for `harvest-subs`, `download-audio`, `asr`, `pilot`, and `run`. It does not change `VALID_STATUSES`, `classify_risk`, or the JSONL manifest shape. `pilot` remains the frozen two-branch proof command; `run` remains complementary. No limited batch claims full-corpus completion.

## Frozen exit taxonomy

- Exit `0` means the requested work is processed or explicitly already terminal (`archived` / `gone` selected as already terminal).
- Exit `1` means usage/configuration error, missing optional ASR, per-item failure, or an incomplete scope caused by non-risk skips (`offline`, `audio_budget`, `missing_audio`, `missing_subtitle_raw`).
- Exit `2` remains reserved for risk/API terminal interruption; cursor and successful manifest progress remain durable.

## Aggregation algorithm (locked)

Apply in this order after a batch starts (usage/config errors still exit 1 before any row runs):

1. If any row raised `RiskBudgetExhausted`, stop the remaining live work and exit `2`. Earlier successful rows, artifacts, `last_api_error_code` on failed rows, and sidecars stay as written.
2. Else if any selected row failed, or skipped for a reason other than `already_terminal`, exit `1`.
3. Else exit `0` (every selected row succeeded, or was skipped as already terminal).

`RunSummary.fully_processed` is the coordinator encoding of steps 2–3: true iff not `risk_interrupted` and every row is `ok` or `skip_reason == "already_terminal"`. `run` maps `risk_interrupted` → 2, else not `fully_processed` → 1, else 0.

## Per-command observables

| Command | Mixed success + per-item failure | Risk after a success | Already-terminal selector | Sidecars |
|---------|----------------------------------|----------------------|---------------------------|----------|
| `harvest-subs` | Continue; success stays `subtitle_done` / `needs_audio`; fail stays last stable status; exit 1 | Exit 2; success kept | N/A (todo is `meta_ok` only) | No run-ledger / attempts |
| `download-audio` | Continue; success stays `audio_ok`; fail stays `needs_audio`; exit 1 | Exit 2; success kept | N/A (todo is `needs_audio`) | No run-ledger / attempts |
| `asr` | Continue; success stays `archived`; fail stays `subtitle_done` / `audio_ok`; missing optional ASR is a per-item incomplete outcome (continue remaining selected rows, then exit 1); `subtitle_done` without on-disk raw is `missing_subtitle_raw` (no ASR); **locked exit 1** | N/A (no HTTP) | `--pending` ignores `archived`/`gone` | No run-ledger / attempts |
| `pilot` | Continue; success may `archived`; fail retryable; missing branch coverage or `failed>0` → exit 1; ledger records that exit | Exit 2; ledger `exit_code=2`; success kept | All-archived leftover → skip, exit 0 | `run-ledger.jsonl` (`command=pilot`) |
| `run` | Continue; failure summary + `scope not fully processed`; exit 1; attempts JSONL records failed stages | Exit 2; coverage snapshot includes archived successes | Explicit `archived`/`gone` work_ids skip `already_terminal`, exit 0 | `run-ledger.jsonl` + `coordinator/attempts.jsonl` |

Retry:

- `harvest-subs` re-selects leftover `meta_ok`.
- `download-audio --missing-subs` re-selects leftover `needs_audio`.
- `asr --pending` re-selects leftover `subtitle_done` / `audio_ok`.
- `pilot` re-selects `_PILOT_PROCESSABLE` non-archived rows.
- `run --scope failed` re-selects non-terminal rows with a recorded failed stage attempt.
- Successful `archived` rows are never duplicated on those reruns.

Newly marked `gone` is terminal and not retryable. Harvest / download / run currently count a newly marked gone row as a per-item failure (exit 1). That is compatible with this aggregation (step 2) and with existing tests; it is not a `run --scope failed` candidate.

## Observed mismatches (Task 1 characterization)

| Surface | Scenario | Task 1 observed | Locked contract | Task 2 |
|---------|----------|-----------------|-----------------|--------|
| `asr --pending` | One row archives, one per-item ASR/archive failure | Exit `0` (`return 1 if failed and not ok else 0`) | Exit `1` | Corrected: `_cmd_asr` now `return 1 if failed else 0` |
| `pilot` `audio_budget` | Skip named on stderr, counter still increments `failed` | Exit 1 (correct); wording mixes skip + failed | Exit 1 remains; skip reason must stay visible | Unchanged |
| `harvest-subs` / `download-audio` / `asr` | Mixed batch | No `run-ledger.jsonl` row | Unchanged: ledger is `fetch-meta` / `pilot` / `run` only | Unchanged |

Task 2 corrected the `asr` mixed-exit root cause. QC fix wave: `_cmd_asr` treats `ASRDependencyError` as a per-item incomplete outcome (continue remaining selected rows, then exit 1); only `RiskBudgetExhausted` stops remaining live work. Do not invent a new exit code, status, or risk class.

## Secrets and traces

Stdout, stderr, manifest rows, `run-ledger.jsonl`, `coordinator/attempts.jsonl`, and `meta-cursor.json` may carry redacted scalar codes/reasons only. Never credentials, `SESSDATA`, cookies, signed URLs, raw exception text, or tracebacks.
