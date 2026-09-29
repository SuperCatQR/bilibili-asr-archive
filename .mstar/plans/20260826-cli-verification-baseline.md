# Installed CLI Verification Baseline

> Iteration: `iter-2026-08-corpus-operations`.
> Execution mode: `sdd`.
> Findings cleanup: `zero-residual`.

## Status

- Priority: P1
- Category: product delivery / verification
- Status: Done
- Depends on: none
- Primary spec: `.mstar/iterations/iter-2026-08-corpus-operations/specs/verification-baseline.md`

## Goal

Make the installed `bili-asr` console script and its supported Python 3.12 environment continuously verifiable. The project should distinguish a clean package/entrypoint failure from a source-checkout test, establish a repeatable dependency and security baseline, and preserve the rule that automated verification makes no live Bilibili requests and downloads no ASR model weights.

## Global Constraints

- The `bili-asr` console script declared by `pyproject.toml` remains the supported entrypoint; `python -m bili_asr` is useful supplemental coverage, not installation proof.
- Verification must run against the package as installed in an isolated supported environment, with Python 3.12 explicitly represented.
- Tests use fake transports, temporary archive roots, and stubbed ASR. No live HTTP, real media transfer, or model download is allowed.
- Dependency/security checks are repeatable and report actionable failures without copying credentials, signed URLs, or raw exception text into logs/artifacts.
- Do not silently weaken test assertions because a tool is unavailable. Environment prerequisites and a clear skip/failure policy must be documented.
- No product behavior change is permitted solely to make verification pass; any contract change belongs in the mixed-outcome or scheduler plan.

## Interfaces

- Package metadata remains in `bilibili-asr-archive/pyproject.toml`; `bili-asr` maps to `bili_asr.cli:main`.
- Test entrypoints include `bili-asr --help`, `bili-asr status --archive-root <temporary-root>`, and `python -m bili_asr --help`.
- CI or local verification exposes a stable command group for install, tests, dependency metadata inspection, and security audit; exact workflow name/tool choice is to be locked during Prepare.
- The baseline report records Python version, package version, test command/result, dependency-audit result, and known environment prerequisites, but no secret-bearing environment values.

## In scope

- Packaging metadata and installed-console-script subprocess tests.
- CI/local verification workflow for Python 3.12, including test isolation and no-network/model-download guardrails.
- A pinned or reproducible dependency/security audit baseline appropriate to the repository's supported dependency set.
- Documentation of supported installation, verification commands, prerequisite behavior, and failure interpretation.
- Tests that prove source-checkout/module invocation is not mistaken for an installed-entrypoint check.

## Out of scope

- Replacing pytest, changing the CLI's frozen verbs, or adding a GUI.
- Running a live Bilibili acceptance campaign or downloading SenseVoice weights in CI.
- Broad dependency upgrades unrelated to a verified baseline finding.
- Full corpus scheduling, mixed outcome semantics, manifest migration, risk-taxonomy changes, or public service deployment.
- Storing credentials, tokens, signed URLs, or model weights in CI artifacts.

## Durable Roadmap and Dependencies

- Batch 1 (this plan): establish the supported Python 3.12 install/test/audit baseline and console-script coverage.
- Batch 2 (next iteration, owner: project-manager + ops-engineer): expand the matrix only after the first baseline is stable, adding supported OS variants or dependency lock policy as evidence requires.
- Deferred: dependency upgrades and pip-audit remediation are separate findings-driven plans; this plan must not absorb arbitrary upgrades. Final Done definition is a repeatable clean-install signal that catches entrypoint and dependency regressions without network/media side effects.

## Tasks

### Task 1: Add installed-entrypoint verification

**Files:** packaging/test configuration, `tests/test_cli_help.py`, focused test helpers, documentation.

- [x] Exercise `bili-asr --help` and `bili-asr status --archive-root <temporary-root>` through a real installed console script in the supported environment.
- [x] Keep `python -m bili_asr --help` as a distinct module-entrypoint assertion and document the difference.
- [x] Define a clear environment prerequisite/failure policy; do not silently pass when an installation is absent.
- [x] Assert output remains free of credentials, signed URLs, and raw tracebacks.

Run: installed-entrypoint tests pass in the isolated Python 3.12 environment without live network access.

### Task 2: Establish dependency/security verification baseline

**Files:** CI workflow or repository verification script, docs, focused tests as needed.

- [x] Add a repeatable Python 3.12 verification command that installs the declared package/test extras in isolation and runs the full suite.
- [x] Add dependency/security inspection with a deterministic tool/version policy and explicit behavior when the audit tool or advisory database is unavailable.
- [x] Publish machine-readable or concise human-readable results while excluding secrets and model/media artifacts.
- [x] Keep the baseline scoped to evidence-backed issues; record any later remediation as a durable follow-up plan.

Run: the declared verification baseline exits successfully in the supported environment, or fails with a named actionable prerequisite rather than a false green.

## STOP Conditions

- Installed-entrypoint proof would mutate a developer/global environment or require live credentials.
- The selected audit cannot be made reproducible or would require arbitrary dependency upgrades in this plan.
- CI/test setup downloads model weights, calls Bilibili, or leaks environment variables.
- Packaging metadata and the actual console script disagree in a way that needs product scope beyond this plan.
- A security finding cannot be separated from a dependency upgrade decision; record it for a separate plan instead of silently changing versions.

## Drift Check

Before execution inspect `pyproject.toml`, `tests/test_cli_help.py`, the current CI directory (if any), dependency declarations, `README.md`, and the latest iteration package. Confirm `bili-asr` remains the declared entrypoint and that prior test commands do not rely solely on `PYTHONPATH`. If the supported matrix or tool availability differs, update this plan during Prepare before implementation.

## Acceptance / Done Criteria

- [x] Real installed `bili-asr --help` and `bili-asr status` checks are present and distinguishable from module-entrypoint checks.
- [x] Python 3.12 full-suite verification is repeatable and has no live HTTP/model-download side effects.
- [x] Dependency/security baseline is explicit, reproducible, and honest about unavailable advisory data or prerequisites.
- [x] Documentation explains install, verify, failure, and artifact-hygiene behavior.
- [x] No credentials, signed URLs, raw exceptions, or model/media artifacts enter committed or CI output.
- [x] All declared tests pass in the supported environment.
- [x] `git status --short` contains only in-scope changes.

## Prepare → Execute Handoff

Prepare must lock the isolated installation strategy, supported Python 3.12 matrix, audit tool/version and unavailable-tool policy, and artifact redaction rules. Execute Task 1 before Task 2; after all tasks, produce the branch review package, mandatory QC tri-review, and QA gate. Dependency remediation remains a separately tracked plan when evidence warrants it.
