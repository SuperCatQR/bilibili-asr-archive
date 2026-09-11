# QC fix report — 20260826-cli-verification-baseline

## Scope

Remediated all findings in control-review `qc1.md`, `qc2.md`, and `qc3.md` on branch `plan/20260826-cli-verification-baseline`.

## Fixes

- Staged `README.md` alongside `tests/` and retained the installed-package import boundary, making checkout-relative documentation/import fixtures resolvable during the isolated full suite.
- Added strict fixture consumer validation: every `.whl` in the fixture must be manifest-listed and hashed; wheel distribution identities are parsed canonically; `required_distributions` must exactly equal the artifact distribution closure.
- Added a process-level `sitecustomize.py` socket deny guard for the staged pytest process, while preserving proxy/environment sanitization.
- Added platform-correct console script resolution (`bili-asr.exe` on Windows, `bili-asr` on POSIX).
- Made fixture preflight exercise the same isolated project install (`.[dev]`, `--no-index`, `--find-links`, `--no-build-isolation`) and verify the installed console script exists.
- Repaired both README fixture commands to include the required reviewed `--wheel-source` argument and documented the full closure requirement and network guard.
- Added deterministic tests for extra wheels, required-distribution mismatch, staged inputs, and Windows script selection.

## Verification

- Focused: `.venv/bin/python -m pytest -q tests/test_verify_baseline.py` → `17 passed in 0.05s`
- Full suite: `.venv/bin/python -m pytest -q` → `337 passed in 6.09s`
- `git diff --check` → passed

## Commit

`9f36095 Harden offline baseline verification contract`
