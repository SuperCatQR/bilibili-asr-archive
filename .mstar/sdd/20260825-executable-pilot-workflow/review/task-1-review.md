# Task 1 L2 review — Execute a bounded mixed pilot

Review range: `559dfcb54816a8e275e5d162ab27f86cde187476..8de38460fc58294e12fc97c2ef318965d7875b67`
Diff: `review/task-1.diff`

### Spec Compliance

- ✅ Spec compliant
- ⚠️ Cannot verify from diff:
  - PM pytest 173 passed on `8de3846` (Assignment claim; not re-run).
  - Live harvest/download/ASR behavior beyond fakes (Task 2 owns ASR-missing + rerun).

### Strengths

- Composition stays in `cli`: live seams (`harvest_subtitle` status string, `download_audio` + `artifact_stem` out path, lazy `asr.transcribe`, keyword-only `write_archive`) unchanged.
- `_pilot_select` now takes `meta_ok` plus resume statuses; duration sort is deterministic; `_expand_selected_pages` pulls sibling `work_id`s so `--n 1` cannot succeed on page 0 only.
- Mixed fake-HTTP test asserts both archives, ASR called once on the no-sub row, SESSDATA as cookie value and absent from stdout/stderr/ledger.
- Missing-branch exit names `subtitle` / `audio-asr`; per-item API/stream errors continue; `ASRDependencyError` does not mark `archived`.

### Issues

#### Critical

None.

#### Important

None.

#### Minor

- `cli.py` `_cmd_pilot`: `ASRDependencyError` and `RiskBudgetExhausted` return before the `pilot branches:` / `pilot terminal:` summary, so operator-visible counts can be missing on those paths. Task 2 already owns ASR-missing coverage.
- `cli.py` `_cmd_pilot`: `print(f"pilot: selected {len(selected)}/{args.n} videos")` runs after expand, so `len(selected)` can exceed `--n` on multi-part bvids (behavior is correct; the fraction is easy to misread).
- `cli.py` `_cmd_pilot`: bare `except Exception` plus a `ValueError` filter that prints `unexpected error` without the message; failures increment `failed` but several paths (`NoAudioStreamError`, generic Exception) do not persist a terminal status. Matches “continue on failure” more than “persist every failure.”

### Assessment

**Task quality:** Approved
