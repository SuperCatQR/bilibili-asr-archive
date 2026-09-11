# Task 1 Report: Stage-attempt ledger + coordinator core

- **Status: DONE**
- Plan: `20260825-run-coordinator-offline` (Task 1 of 2)
- Branch: `plan/20260825-run-coordinator-offline` (worktree, base 5b392cc)

## Implemented

1. **`bili_asr/coordinator.py`** (new, 547 lines)
   - `AttemptLedger`: append-only JSONL sidecar at
     `{archive_root}/coordinator/attempts.jsonl`. Atomic appends via
     tmp file + fsync + `os.replace` (readers see whole lines only; a
     crash leaves no partial record — tmp is removed on failure).
     Fields per plan §Interfaces: `stage`, `work_id`, `attempt` (int,
     monotonically increasing per (work_id, stage) across runs),
     `outcome` (`ok|failed|skipped`), `error_code` (int | short str |
     null — redacted scalars only; forbidden-marker scan rejects
     cookies/URLs/tracebacks), `artifact_paths` (relative paths),
     `started_at`/`finished_at`.
   - `RunCoordinator`: composes the existing seams exactly as locked —
     harvest → `harvest_subtitle(client, identity, store, root)`;
     download → `download_audio(client, identity, out_path, store=store)`
     with `out_path` from `artifact_stem`; asr → `transcribe(audio_path,
     model_name=None)`; archive → `write_archive(root, entry, segments,
     *, source, raw)`. No second HTTP client; no signature forks.
   - Stage execution by manifest status: `pending/meta_ok/sub_checked` →
     harvest; `subtitle_done` → archive-from-subtitle-raw;
     `needs_audio` → download → asr → archive; `audio_ok` → asr →
     archive. Terminal rows (`archived`/`gone`) are skipped on rerun
     (idempotent manifest + attempts ledger). `gone` API responses mark
     the row `gone`; `RiskBudgetExhausted` stops the batch with
     `risk_interrupted` (exit 2); all other per-item failures are
     recorded and the batch continues.
   - `--offline` (client=None/offline=True): harvest/download are
     `skipped` with reason `offline` and are **never invoked** — full
     offline semantics belong to Task 2 per the brief.

2. **`bili_asr/cli.py`**: new `bili-asr run --scope pending|failed|<work_id>...
   [--offline] [--limit N] [--archive-root] [--sessdata]`. Scope
   resolution reuses `_todo_for_bvid` for selectors; `pending` selects
   all non-terminal processable rows; `failed` selects rows with a
   recorded failed stage attempt. Bounded `--limit`. Exit codes: 0 all
   processed, 1 per-item failures, 2 risk ceiling. A compatible
   `RunLedger` record (`command="run"`) is appended per run
   (best-effort, mirrors `_cmd_pilot` pattern).

3. **`tests/test_coordinator.py`** (new, 11 tests, fake transport +
   stubbed `transcribe`, no live HTTP):
   atomic append (no partial lines; non-redacted payload rejected);
   attempt counter across instantiations; live pending run records
   per-stage attempts with correct stage sequences and relative
   artifact paths; rerun skips terminal rows (manifest, attempts, HTTP
   calls, transcribe all unchanged); `--limit 1` bounds the batch
   (single probe); per-item ASR failure → row not archived, sibling
   archived, `failed` attempt with `error_code="ASRModelError"`, no raw
   exception text persisted; specific work_id scope; gone → terminal +
   batch continues; `--offline` issues zero HTTP and records
   `harvest/skipped/offline`; `RunLedger` record appended.

## Tests

```
PYTHONPATH=src:tests …/.venv-pm/bin/python -m pytest tests/test_coordinator.py -q
→ 11 passed
PYTHONPATH=src:tests …/.venv-pm/bin/python -m pytest -q
→ 266 passed (255 at merge-base + 11 new), 0 failed
```

(Test venv from the sibling worktree `20260824-multipart-page-aware-pipeline`
as instructed; `tests` on PYTHONPATH because test modules import helpers
from each other — same pattern as existing `test_cli_pilot.py`.)

## Files changed

- `bilibili-asr-archive/src/bili_asr/coordinator.py` (new)
- `bilibili-asr-archive/src/bili_asr/cli.py` (+161)
- `bilibili-asr-archive/tests/test_coordinator.py` (new)

## Commits

- `6827180` feat(coordinator): stage-attempt ledger + run coordinator core (Task 1)

## Self-review notes

- Frozen surfaces untouched: `VALID_STATUSES`, `classify_risk`,
  manifest schema (sidecar only), existing seam signatures, `pilot`.
- Redaction enforced in two layers: `_safe_error_code` extracts only
  scalar codes / exception class names; `_validate_attempt` rejects
  forbidden markers (SESSDATA/cookie/http/https/Traceback) and
  absolute artifact paths.
- One real bug found and fixed during testing: `_stage_asr_archive`
  previously re-upserted a stale entry after `_mark_archived`,
  reverting the manifest status to `audio_ok`; fixed by mutating
  `audio_path` before the single archived upsert.
- Tests use a `CidRouterTransport` subclass that routes
  `player/wbi/v2` by the `cid` param (row order is sorted by work_id,
  which does not match response-queue order for arbitrary bvids) and
  serves `playurl` from an explicit queue because the base transport's
  substring routing would otherwise match `player/wbi/v2` against the
  playurl URL.
- Known Task-2 follow-ups (intentionally out of scope): offline
  reprocessing of on-disk artifacts, per-run failure summary surface,
  README documentation, nonzero exit when scope not fully processed
  (current: nonzero only on per-item failure / risk ceiling).
