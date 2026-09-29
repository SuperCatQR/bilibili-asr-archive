# Post-Merge Regression Test Plan

> Date: 2026-09-04.
> Target: `main` after completed iteration integration.
> Merge validation commit: `095870f`.
> Status: Executed with prerequisite blocker.
> Execution mode: verification.
> Findings cleanup: zero-residual.

## Goal

Establish a repeatable release gate for the merged Bilibili ASR archive CLI. The gate must prove that the completed scheduler, campaign, coverage, integrity, persistence, ASR reproducibility, search/export, and installed-entrypoint contracts coexist on `main` without live Bilibili traffic, model downloads, credential exposure, or accidental enablement of concurrency.

## Success Criteria

- The full Python 3.12 fixture suite passes from the product root and collects the merged test set without import-path ambiguity.
- The real installed `bili-asr` console script and the supplemental `python -m bili_asr` entrypoint both behave as documented.
- Offline baseline installation is reproducible from a reviewed local wheel closure and the advisory snapshot is evaluated locally.
- Persistence, archive publication, sidecar projection, path confinement, and reclaim tests pass under malformed input, failure injection, symlink, and multi-process fixtures.
- Scheduler and campaign tests preserve bounded, sequential, resumable, mixed-outcome semantics.
- ASR tests prove lazy run-scoped model reuse, deterministic normalization, and redacted provenance without loading real model weights.
- Coverage, quality, search, export, verify, recover, and concurrency-gate surfaces are deterministic and read-only where specified.
- No automated test opens a live Bilibili socket, downloads media, or downloads a model.
- The only live operation is an explicitly authorized single-item WSL long-live acceptance, recorded separately and redacted.

## Non-Goals

- This plan does not claim full-corpus archival or semantic transcript correctness.
- This plan does not enable concurrent workers, a daemon, service startup, or automatic scheduling.
- This plan does not acquire or persist `SESSDATA`, signed URLs, model weights, media, or real archive data.
- Dependency upgrades and security remediation remain separate change requests.

## Global Constraints

- Run from `bilibili-asr-archive/` with Python 3.12.
- Prefer `python -m pytest` over the pytest console wrapper so the product root is on `sys.path` for the repository `scripts` namespace.
- Use temporary archive roots for all CLI fixtures. Never point tests at an operator archive.
- Clear `BILI_SESSDATA`, proxy variables, and model-download configuration for automated runs.
- Use fake HTTP transports and fake ASR runners only. A test that needs live HTTP or real model weights is out of scope and must stop.
- Treat `manifest.jsonl` as the state source of truth. Treat cursor, scheduler, campaign, ledger, attempts, and audit files as validated sidecars.
- Delete generated `build`, `dist`, egg-info, temporary wheel fixtures, SQLite indexes, and verification environments after each verification wave unless the result is an explicitly redacted artifact.

## Test Matrix

| Wave | Scope | Command or evidence | Pass condition |
|---|---|---|---|
| A | Environment and entrypoints | `python --version`; `python -m bili_asr --version`; `python -m bili_asr --help`; `python -m pytest --collect-only -q` | Python is 3.12; CLI exposes all merged verbs; collection succeeds with no errors |
| B | Full fixture regression | `python -m pytest -q` | Every collected test passes; no live network/model activity |
| C | Operations contracts | `python -m pytest -q tests/test_scheduler.py tests/test_campaign.py tests/test_long_live.py tests/test_mixed_outcome_contract.py tests/test_cli_pilot.py` | Bounded selection, risk resume, long-live opt-in, reclaim, and exit precedence pass |
| D | Persistence and archive safety | `python -m pytest -q tests/test_persistence_scale.py tests/test_manifest.py tests/test_run_ledger.py tests/test_coordinator.py tests/test_archive_md.py tests/test_audio_reclaim.py tests/test_integrity.py` | Atomicity, locks, streaming projections, bundle markers, path confinement, and fail-closed recovery pass |
| E | Transcript and read projections | `python -m pytest -q tests/test_quality.py tests/test_coverage_report.py tests/test_search_index.py tests/test_export.py` | Quality signals, denominator boundaries, FTS5, deterministic export, and read-only guarantees pass |
| F | ASR reproducibility | `python -m pytest -q tests/test_asr_reproducibility.py tests/test_asr_format.py` | Fake model construction/reuse, normalization, lifecycle release, and provenance redaction pass |
| G | Installed package baseline | `python -m pytest -q tests/test_cli_help.py tests/test_verify_baseline.py` | Isolated console-script checks pass; missing prerequisites fail explicitly; no recursive verifier execution |
| H | Offline package verification | `python scripts/prepare_offline_baseline_fixture.py --wheel-source "$REVIEWED_WHEELS" --output .offline-baseline --run` | Reviewed wheel closure installs with no index/network; isolated CLI and product tests pass; advisory snapshot is clean |
| I | Authorized live acceptance | WSL-native archive root, one long-live `work_id`, `schedule --scope WORK_ID --limit 1 --allow-long-live --max-audio-gb 10` | Only after operator approval; peak disk stays under cap; archive/reclaim and redaction evidence pass |

## Execution Notes

- `main` was fast-forwarded to remote `e0c1cb0` and then merged with the completed persistence-scale-safety iteration. The final local merge commit is recorded by the `main` worktree.
- Wave A passed: merged CLI help exposed the full command surface and collection succeeded with `690 tests collected` when the merged source path was supplied to the validation interpreter.
- Waves C through F passed after updating two stale test adapters to the existing `ASRRunner` injection boundary: `45 passed in 1.10s` focused, and `685 passed, 5 deselected in 38.43s` for the full non-install fixture suite.
- An initial full invocation exposed three stale coordinator test adapters; they were fixed on `plan/20260904-post-merge-test-adapter` and merged as the test-only commit `d6a6547`.
- Wave G isolated console-script checks are currently blocked by the local prerequisite: the available developer environment has no pip, and uv offline installation cannot find a complete local build/runtime/dev wheel closure. The checks fail explicitly with the named prerequisite rather than skipping.
- Wave H remains pending until a reviewed local wheel directory is supplied. No live Bilibili traffic, model download, or real media transfer was used in the automated waves.


### Task 1: Mainline smoke and collection

- [ ] Verify `main` is at the merge commit and has no tracked or untracked product changes.
- [ ] Run Wave A from the product root.
- [ ] Record the exact collected test count and Python version in the verification result.
- [ ] Confirm all merged CLI verbs are present: `fetch-meta`, `status`, `runs`, `asr`, `pilot`, `probe-subs`, `harvest-subs`, `download-audio`, `run`, `schedule`, `campaign`, `search`, `coverage`, `verify`, `recover`, `evaluate-concurrency`, and `export`.

### Task 2: Full and focused fixture regression

- [ ] Run Wave B once as the primary gate.
- [ ] Run Waves C through F when Wave B fails, or when a release report needs per-domain evidence.
- [ ] Confirm failures are classified as code failures, missing prerequisites, or test-startup failures; do not convert a failure into a skip to obtain a green result.
- [ ] Confirm tests do not create files outside their temporary roots.

### Task 3: Installed CLI and offline baseline

- [ ] Run Wave G in the supported Python 3.12 environment.
- [ ] Prepare a local wheel directory containing exactly one compatible wheel per declared build, runtime, and `dev` distribution.
- [ ] Set `REVIEWED_WHEELS` to that local directory and run Wave H with `tests/fixtures/advisories-empty.json`.
- [ ] Inspect `verification-results/baseline.json` for the schema, command return codes, advisory status, and redaction. Do not commit generated result data unless it is explicitly bounded and intended.
- [ ] Remove `.offline-baseline`, disposable virtual environments, and build artifacts after the wave.

### Task 4: Read-only and security boundary checks

- [ ] Verify `coverage`, `verify`, `search`, `export`, and `evaluate-concurrency` do not mutate manifest or source sidecars.
- [ ] Verify `recover` only writes bounded redacted audit evidence and never requeues work.
- [ ] Scan captured output and generated sidecars for cookies, signed URLs, raw tracebacks, media paths outside the archive root, and model payloads.
- [ ] Confirm the concurrency gate remains an evidence-only `go` or `no-go` report and runtime mode remains `sequential-no-daemon`.

### Task 5: Authorized WSL long-live acceptance

- [ ] Keep the archive root on a WSL-native filesystem and outside the git checkout.
- [ ] Supply the cookie value only in the current shell when login is required; never echo, persist, or include it in evidence.
- [ ] Choose exactly one metadata row with `duration_s` greater than 45 minutes.
- [ ] Measure `audio/` before and after the bounded scheduler call.
- [ ] Require `--allow-long-live` and a positive `--max-audio-gb`; never use an unlimited audio cap for this acceptance.
- [ ] Confirm `archived`, bounded peak usage, reclaimed audio, honest cursor state, and no-secret output.
- [ ] Store only redacted stdout/stderr, disk measurements, status, and runs summaries in the evidence record.

## STOP Conditions

- Test collection fails because the supported invocation cannot import repository verification helpers.
- Any automated test opens live Bilibili traffic, downloads a model, or transfers real media.
- The merged CLI changes manifest status taxonomy, risk taxonomy, or sequential-no-daemon behavior without a new approved plan.
- A fixture or report contains credentials, signed URLs, raw exception text, model weights, or uncontrolled archive data.
- Persistence, archive, or sidecar tests pass only when symlink/failure-injection cases are disabled.
- Offline verification lacks a complete reviewed wheel closure or advisory snapshot and would otherwise be reported as green.
- Live acceptance requires a cookie file, unbounded disk, a multi-item batch, or a long-live policy bypass.

## Acceptance / Done Criteria

- [ ] Wave A collection and CLI smoke pass.
- [ ] Wave B full suite passes under Python 3.12.
- [ ] Waves C through G pass or have an explicit, reproducible prerequisite failure recorded.
- [ ] Wave H passes when the reviewed local wheel closure is available.
- [ ] No live network or model activity occurs in automated verification.
- [ ] Any live WSL evidence is separately authorized, redacted, and bounded to one item.
- [ ] No sensitive values or generated runtime data are committed.
- [ ] `git status --short` is clean on `main` after cleanup.

## Expected Deliverables

- One redacted verification summary containing commit, Python version, collection count, full-suite result, focused-wave results, and prerequisite status.
- One optional offline baseline JSON result under the documented ignored result path.
- One separate redacted WSL evidence record only when the operator authorizes live acceptance.
- No product-code change as part of this test plan unless a reproducible defect is first reduced to a failing test and assigned to a separate fix plan.
