# Task 2 report — installed entrypoint integration tests

- Status: DONE
- Role: fullstack-dev (fresh SDD implementer)
- Working branch used: `plan/20260825-state-machine-entrypoint-tests`
- Worktree path used: `/root/workspace/bilibili-asr-archive/.worktrees/20260825-state-machine-entrypoint-tests`
- HEAD: `7965288a7b9ceea1eead8cb9e685f0ef7e8f54ef`
- BASE_SHA: `10ebd0238e73efe35e0d7a4adaaabfc58a37d470`

## Implemented

Enhanced `bilibili-asr-archive/tests/test_cli_help.py` with installed-console-script and module-entrypoint integration tests:

| Target | Test Case | Assertion |
|---|---|---|
| Installed console script | `test_installed_entrypoint_help_exits_zero` | `bili-asr --help` runs as installed executable without `PYTHONPATH`; exits 0; stdout lists subcommands (`fetch-meta`, `status`, `asr`, `pilot`). |
| Installed console script | `test_installed_entrypoint_status_empty_archive` | `bili-asr status --archive-root <temp>` exits 0; stdout displays `manifest: empty`. |
| Installed console script | `test_installed_entrypoint_status_with_manifest_records` | `bili-asr status --archive-root <temp>` with test manifest records exits 0; stdout displays per-status counts (`archived: 1`, `meta_ok: 1`). |
| Module entrypoint | `test_module_entrypoint_help_exits_zero` & `test_module_entrypoint_help_mentions_subcommands` | `python -m bili_asr --help` exits 0; separate from installed console script test. |
| Module entrypoint | `test_module_entrypoint_status_empty_archive` | `python -m bili_asr status --archive-root <temp>` exits 0; stdout `manifest: empty`. |
| Direct Python API | `test_cli_main_help_direct` & `test_cli_main_importable` | `cli.main(["--help"])` exits 0; `cli.main` directly importable. |

### Environment Prerequisite / Non-Mutation Guard

- The fixture `installed_bili_asr` discovers `bili-asr` in the current Python interpreter's `bin`/`Scripts` directory or `PATH`.
- If the console script is absent, the fixture calls `pytest.skip` with a clear message: `"Installed 'bili-asr' console script not found in environment. Prepare environment with: pip install -e '.[asr,dev]' or pip install ."`.
- Normal test execution never mutates the repo or global environment.

### Environment-Prep Command

To install the package and console script into the test venv:
```bash
pip install -e ".[asr,dev]"
# or minimal:
pip install -e .
```

## Tests

- Target test:
```text
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest tests/test_cli_help.py -v
```
Output: `8 passed in 0.40s`

- Full test suite:
```text
PYTHONPATH=src /root/workspace/bilibili-asr-archive/.worktrees/20260824-multipart-page-aware-pipeline/bilibili-asr-archive/.venv-pm/bin/python -m pytest tests -q
```
Output: `189 passed in 3.86s`

## Files changed

- `bilibili-asr-archive/tests/test_cli_help.py` (committed on `plan/20260825-state-machine-entrypoint-tests`)
- `.mstar/plans/20260825-state-machine-entrypoint-tests.md` (task completion & environment prep documentation)

## Self-review

- No product source code modified.
- Console script tests run without `PYTHONPATH` to exercise the installed package entrypoint.
- Module entrypoint tests kept separate (`python -m bili_asr`).
- Zero residual findings.
- No PR opened.
