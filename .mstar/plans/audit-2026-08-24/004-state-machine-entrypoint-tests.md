# Full State-Machine and Installed Entrypoint Integration Tests

> **For agentic workers:** REQUIRED SUB-SKILL: Use `mstar-sdd` (recommended) or inline execution. This audit plan is a candidate for the normal Prepare -> Execute flow; it does not register or execute itself.

**Goal:** Add deterministic integration coverage for the shipped command surface and every frozen manifest transition, including subprocess invocation through the installed `bili-asr` entrypoint.

**Architecture:** Tests should exercise the CLI composition layer with fake HTTP and ASR seams, while keeping formatters and manifest tests focused. Use temporary archive roots and assert externally visible outcomes: exit code, stdout/stderr, manifest records, and artifact files. The test suite must not make live network calls or download model weights.

## Status
- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/003-executable-pilot-workflow.md
- **Category**: tests
- **Planned at**: commit `ab3cd97`, 2026-08-24
- **State**: TODO
- **Note**: plan 003 is the immediate dependency because this test plan pins its settled command interfaces. Plans 001, 002, and 005 are additional behavioral prerequisites where the integration fixture covers all-part media, metadata resume, or API-contract integrity; they are listed in the index and prose rather than duplicated in this single-path Status field.

## Finding and current state

- The suite has broad helper coverage but no dedicated tests for `cli.py:403-445` (`asr` command), the complete pilot path (`cli.py:448-461`), or multi-stage manifest transitions.
- Existing CLI help tests invoke `python -m bili_asr` with a manually injected `PYTHONPATH` (`bilibili-asr-archive/tests/test_cli_help.py:7-17`), not the declared console script `bili-asr = "bili_asr.cli:main"` (`pyproject.toml:16-17`).
- The frozen spec requires tests for transitions, formatters, risk-code classifications, mocked integration, pilot, and clean-install behavior (`.mstar/specs/asr-archive-cli.md:101-107,133-137`).

## Interfaces

Test the existing public surfaces:

- Console script: `bili-asr --help`, `bili-asr status --archive-root <root>`
- Module entrypoint: `python -m bili_asr --help`
- `cli.main(argv: list[str] | None) -> int`
- `ManifestStore` JSONL persistence and status values in `manifest.py:13-28`

Use `monkeypatch` to replace `bili_asr.bili_client.build_default_transport`, `default_sleeper`, and `bili_asr.asr.transcribe` where the command needs a fake external boundary. Do not patch the behavior under test.

## In scope

- `bilibili-asr-archive/tests/test_cli_asr.py` (create)
- `bilibili-asr-archive/tests/test_cli_pilot.py` (create or extend after plan 003)
- `bilibili-asr-archive/tests/test_cli_help.py`
- `bilibili-asr-archive/tests/test_manifest.py`
- `bilibili-asr-archive/tests/test_fetch_meta.py` for cursor/entrypoint integration additions
- `bilibili-asr-archive/pyproject.toml` only if a test script or package test configuration is needed

## Out of scope

- Product source changes except minimal test hooks explicitly required by plans 001-003.
- Live API, FunASR model loading, ffmpeg process execution, performance benchmarking, or coverage percentage targets.
- Replacing pytest or introducing a test framework.

## Conventions and exemplars

- Use workspace-local temporary directories from `tests/conftest.py:12-30` so tests remain compatible with the repository's stated sandbox constraints.
- Assert artifacts and manifest contents, as `tests/test_subtitles.py:220-240` and `tests/test_audio.py:242-257` do, rather than merely asserting helper return values.
- Use fake transports modeled on `tests/test_fetch_meta.py:20-42`, `tests/test_subtitles.py:24-49`, and `tests/test_audio.py:25-59`.

## Tasks

### Task 1: Cover command-level state transitions

**Files:** Create/modify `bilibili-asr-archive/tests/test_cli_asr.py`, `tests/test_cli_pilot.py`, `tests/test_manifest.py`.

- [ ] Assert `meta_ok -> needs_audio -> audio_ok -> archived` with a fake audio stream and stubbed ASR.
- [ ] Assert `meta_ok -> subtitle_done -> archived` and that ASR is not called.
- [ ] Assert risk exhaustion returns exit 2, preserves the last stable state, and prints a resumable summary.
- [ ] Assert missing optional ASR returns exit 1 and leaves the record non-archived.
- [ ] Assert reruns are idempotent and do not duplicate JSONL lines or overwrite unrelated rows.

Run: `python -m pytest bilibili-asr-archive/tests/test_cli_asr.py bilibili-asr-archive/tests/test_cli_pilot.py bilibili-asr-archive/tests/test_manifest.py -q` -> exit 0 with all transition assertions passing.

### Task 2: Exercise the installed entrypoint

- [ ] Add a packaging/integration fixture that invokes `bili-asr --help` and `bili-asr status --archive-root <temp>` from an environment where the package is installed.
- [ ] Keep module-entrypoint tests as a separate check; do not treat `PYTHONPATH` execution as proof of installation.
- [ ] Document the exact command used to prepare the test environment in the plan's execution handoff; the audit itself must not install dependencies.

Run: `python -m pytest bilibili-asr-archive/tests/test_cli_help.py -q` -> exit 0; installed-console-script assertions run when the package is available, otherwise the test reports a clear environment prerequisite rather than silently skipping.

## STOP conditions

- If console-script testing would require mutating the repository or global environment during normal test execution, STOP and move installation to CI/setup while retaining a subprocess test.
- If the ASR path cannot be stubbed without violating lazy import, STOP and adjust the source seam in plan 003 before writing acceptance tests.
- If an existing test relies on a specific manifest status that conflicts with the frozen state machine, STOP and document the discrepancy rather than weakening the assertion.

## Drift check

Before execution run:

`git diff --stat ab3cd97..HEAD -- bilibili-asr-archive/tests bilibili-asr-archive/pyproject.toml`

If earlier plans changed command names or state fields, compare all interfaces above with live code and update this plan only through Prepare clarification.

## Done criteria

- [ ] Both subtitle and audio-ASR terminal paths are covered through `cli.main`.
- [ ] Risk exit 2, ASR dependency exit 1, and idempotent rerun behavior are asserted.
- [ ] `bili-asr --help` and `bili-asr status` are exercised as installed-console-script subprocesses in the supported environment.
- [ ] `python -m pytest bilibili-asr-archive/tests -q` exits 0.
- [ ] No test makes live HTTP or downloads model weights.
- [ ] `git status --short` shows only in-scope files changed.

## Prepare -> Execute handoff

During Prepare, decide whether installed-entrypoint coverage belongs in local tests, CI, or both, and define the supported clean-install matrix. During Execute, add transition tests after plans 001-003 settle their interfaces, then run the full declared test command.
