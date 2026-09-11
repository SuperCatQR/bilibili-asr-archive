### Task 2: Exercise the installed entrypoint

- [ ] Packaging/integration fixture invokes `bili-asr --help` and `bili-asr status --archive-root <temp>` from an installed environment.
- [ ] Module-entrypoint tests separate; `PYTHONPATH` execution not proof of installation.
- [ ] Document the exact environment-prep command in the plan execution handoff.

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

## Durable Review Summary

(Filled after QC/QA.)
