# Plan 008 — Register pytest markers + centralize the live/scale opt-in gates

## Status
- **Priority**: P3
- **Effort**: XS
- **Risk**: LOW
- **Depends on**: plans/007-*.md (land 007 first — it edits the same conftest block)
- **Category**: tests
- **Confidence**: HIGH
- **Evidence**: `tests/test_live_subtitle_smoke.py:137`, `tests/test_live_subtitle_cli_smoke.py:125`, `tests/test_live_metadata_smoke.py:73`, `tests/test_persistence_scale.py:38`; `pyproject.toml:78-80`
- **Planned at**: commit `ff39fd0`, 2026-10-02

## Problem

The live/smoke/scale opt-in gates are hand-rolled per file: each of the four files re-declares its own
env-var constant (`BILI_LIVE_SMOKE` / `BILI_SCALE`), its own skip helper, and its own reason text.
`pyproject.toml`'s `[tool.pytest.ini_options]` declares only `testpaths` — no `markers`, no `addopts`.

So ~35 live/smoke/scale tests are **invisible to pytest's collection metadata**: an operator cannot run
`-m live`, CI cannot gate them, and the env-var names can drift apart silently (a fifth opt-in class would
copy-paste a fourth idiom).

## Current state

- `tests/test_live_metadata_smoke.py:73`, `tests/test_live_subtitle_smoke.py:137`,
  `tests/test_live_subtitle_cli_smoke.py:125` — each gates on `BILI_LIVE_SMOKE` with a local skip helper.
- `tests/test_persistence_scale.py:38` — gates on `BILI_SCALE`.
- `pyproject.toml:78-80`:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
```
No `markers` registered.

## Approach

1. Register three markers in `pyproject.toml [tool.pytest.ini_options]`:
   `markers = ["live_smoke", "scale", "slow"]`.
2. Mark the four files' classes/functions with the matching marker (`live_smoke` for the three live smokes,
   `scale` for the persistence-scale file).
3. Replace the per-file env-var skip helpers with a **single shared conftest fixture** that reads one
   mapping (env var → marker) and skips centrally, preserving the exact skip reason text so existing
   behaviour is unchanged.
4. Keep the env-var names (`BILI_LIVE_SMOKE`, `BILI_SCALE`) — this plan adds metadata, it does not rename
   the operator-facing knobs.

## Files

- **Modify**: `pyproject.toml` — add `markers` under `[tool.pytest.ini_options]`.
- **Modify**: `tests/conftest.py` — add the shared opt-in-gate fixture (land after 007 edits conftest).
- **Modify**: the four smoke/scale test files — add the marker and use the shared gate (delete the local
  skip helpers).

## Out of scope

- Changing the env-var names or the opt-in semantics (tests still skip by default).
- The tests' bodies/assertions.
- The conftest `tmp_root`/sys.path work (that is plan 007).

## Verification gates

- **Collection metadata**: `python3.12 -m pytest --collect-only -m live_smoke -q` lists the live-smoke
  tests (they are now selectable by marker).
- **Default run still skips**: `python3.12 -m pytest tests/test_live_metadata_smoke.py tests/test_persistence_scale.py -q` →
  the live/scale tests report as skipped (by the central gate, not a per-file `skip()`), with the same
  reason text as before.
- No marker warnings:
  - Run: `python3.12 -m pytest tests/test_live_metadata_smoke.py -q -W error::pytest.PytestUnknownMarkWarning` →
    no unknown-mark warning (the marker is registered).

## STOP conditions

- If centralizing the gate changes the skip reason text that an operator or doc references, STOP — keep the
  reason strings byte-identical; only the mechanism moves.
- If a fifth opt-in class exists that the four files do not represent, STOP and list it before registering
  only three markers.

## Done criteria

- [ ] `python3.12 -m pytest --collect-only -m live_smoke -q` lists the live-smoke tests.
- [ ] `python3.12 -m pytest tests/test_live_metadata_smoke.py tests/test_persistence_scale.py -q` skips by
      default with the same reason text.
- [ ] `python3.12 -m pytest tests/test_live_metadata_smoke.py -q -W error::pytest.PytestUnknownMarkWarning` → no warning.
- [ ] `git diff --check -- pyproject.toml tests/conftest.py tests/test_live_metadata_smoke.py tests/test_live_subtitle_smoke.py tests/test_live_subtitle_cli_smoke.py tests/test_persistence_scale.py` exits 0.
- [ ] No files outside the Files list are modified.

## Drift check

`git diff --stat ff39fd0..HEAD -- pyproject.toml tests/conftest.py tests/test_live_metadata_smoke.py tests/test_live_subtitle_smoke.py tests/test_live_subtitle_cli_smoke.py tests/test_persistence_scale.py` — if any changed, confirm the per-file gate helpers are still present before centralizing.
