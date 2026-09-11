# Full State-Machine and Installed Entrypoint Integration Tests

> Candidate source: `.mstar/plans/audit-2026-08-24/004-state-machine-entrypoint-tests.md`.
> Iteration: `iter-2026-08-pilot-ops`.
> Execution mode: `sdd`.

## Status

- Priority: P2
- Category: tests
- Status: Done
- Depends on: `20260825-executable-pilot-workflow` (pins settled pilot interfaces)
- Findings cleanup: zero-residual

## Goal

Pin the frozen MVP command surface under tests: every shipped-command manifest transition plus subprocess invocation of the installed `bili-asr` console script (not `PYTHONPATH` as install proof). Product bar is “the operator can trust `bili-asr` as installed”; this plan does not change CLI contracts except where plan A already settled them.

## Global Constraints

- Tests use fake HTTP and ASR seams; no live network, model downloads, or ffmpeg process execution.
- Use temporary archive roots; assert externally visible outcomes (exit code, stdout/stderr, manifest records, artifact files).
- Do not patch the behavior under test; monkeypatch only `build_default_transport`, `default_sleeper`, `asr.transcribe`.
- Console-script testing must not mutate the repo or global environment during normal runs; installed-entrypoint assertions run when package is available, else clear environment prerequisite.
- No risk-taxonomy or `VALID_STATUSES` change; JSONL field is `status` (not `state`). `state` is reserved for `meta-cursor.json`.
- `bili_client` remains the only HTTP owner; tests must not add a second transport.

## Interfaces

- Console script: `bili-asr --help`, `bili-asr status --archive-root <root>`
- Module entrypoint: `python -m bili_asr --help`
- `cli.main(argv: list[str] | None = None) -> int`
- `ManifestStore` JSONL at `{archive_root}/manifest/manifest.jsonl`; last-write-wins per `work_id`; `get` / `get_compatible` / `upsert` unchanged.
- Frozen transitions used by shipped commands (live harvest skips unused `sub_checked` / `asr_done` labels): `meta_ok -> needs_audio -> audio_ok -> archived` and `meta_ok -> subtitle_done -> archived`. Do not invent a new intermediate status.
- Exit codes: 0 success; 1 usage/config/`ASRDependencyError`; 2 `RiskBudgetExhausted` / terminal gone-class API. Mixed per-video exit-code (README vs CLI) is **out of contract**.

## Tasks

### Task 1: Cover command-level state transitions

- [x] `meta_ok -> needs_audio -> audio_ok -> archived` with fake audio stream + stubbed ASR.
- [x] `meta_ok -> subtitle_done -> archived`; ASR not called.
- [x] Risk exhaustion → exit 2, last stable manifest `status` preserved, resumable summary.
- [x] Missing optional ASR → exit 1, record non-archived.
- [x] Reruns idempotent; no duplicate JSONL lines; unrelated rows untouched.

Run: `python -m pytest bilibili-asr-archive/tests/test_cli_asr.py bilibili-asr-archive/tests/test_cli_pilot.py bilibili-asr-archive/tests/test_manifest.py -q` exits 0.

### Task 2: Exercise the installed entrypoint

- [x] Packaging/integration fixture invokes `bili-asr --help` and `bili-asr status --archive-root <temp>` from an installed environment.
- [x] Module-entrypoint tests separate; `PYTHONPATH` execution not proof of installation.
- [x] Document the exact environment-prep command in the plan execution handoff.

Run: `python -m pytest bilibili-asr-archive/tests/test_cli_help.py -q` exits 0 (or clear env prerequisite).

## Acceptance Criteria

- Both subtitle and audio-ASR terminal paths covered through `cli.main` (frozen transitions used by shipped commands).
- Risk exhaustion → exit 2 with last stable manifest `status` preserved; missing ASR extra → exit 1 and non-archived; rerun idempotent.
- `bili-asr --help` and `bili-asr status --archive-root <temp>` exercised as installed-console-script subprocesses in the supported environment; `python -m` is separate and is not install proof.
- Mixed per-video exit-code (README vs CLI) is **not** changed here; do not “fix” it without a product contract. Characterization may be noted, not shipped as a new DoD.
- `python -m pytest bilibili-asr-archive/tests -q` exits 0; no live HTTP or model downloads.
- `git status --short` shows only in-scope files.

## STOP Conditions

- Console-script testing requires mutating repo/global env during normal test execution → STOP, move installation to CI/setup.
- ASR path cannot be stubbed without violating lazy import → STOP, adjust seam in plan A first.
- Existing test conflicts with frozen status machine → STOP, document discrepancy rather than weaken assertion.

## Prepare → Execute Handoff

Installed-entrypoint coverage is local pytest when the package is installed, else a documented environment prerequisite (CI matrix is a later slice). Add transition tests after plan A settles interfaces; then run the full declared test command.

Environment preparation command for installed entrypoint testing:
```bash
pip install -e ".[asr,dev]"
# or minimal:
pip install -e .
```
When running pytest in an environment without the console script installed, `test_cli_help.py` skips installed-script assertions with a clear prerequisite message without failing or mutating the environment.

## Durable Review Summary

- Feature HEAD / merge: `79652889e7e7b7a6c8419a4bf30badf6f73ee757` (FF into `iteration/iter-2026-08-pilot-ops`).
- L2: Task 1 Approved (`10ebd02`); Task 2 Approved (`7965288`).
- QC tri: Approve (all three seats, 0 Critical/0 Warning; cosmetic suggestions only: subprocess timeout, tmp_path annotation, unused import).
- QA mandatory/full: Approve. `PYTHONPATH=src .venv-pm/bin/python -m pytest -q` → 189 passed (focused state-machine + entrypoint suite 41 passed).
- Notable decisions: frozen transitions `meta_ok→needs_audio→audio_ok→archived` / `meta_ok→subtitle_done→archived` covered through `cli.main`; installed console script tested as subprocess with PYTHONPATH stripped (genuine packaging proof), `python -m` kept separate; skip-guard fixture with documented `pip install -e ".[asr,dev]"` prep; mixed per-video exit-code left out of contract.
