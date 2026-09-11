# Task 2 L2 review — Exercise the installed entrypoint

Range: `10ebd0238e73efe35e0d7a4adaaabfc58a37d470..79652889e7e7b7a6c8419a4bf30badf6f73ee757`
Diff: `.mstar/sdd/20260825-state-machine-entrypoint-tests/review/task-2.diff`
Tests: not re-run (PM: 189 passed on `7965288`).

### Spec Compliance

- ✅ Spec compliant
- ⚠️ Cannot verify from diff:
  - PM pytest 189 passed on `7965288` (Assignment claim; not re-run).

### Strengths

- **True packaging isolation**: `_run_installed` explicitly filters out `PYTHONPATH` from `os.environ` before executing the `bili-asr` executable, ensuring the subprocess exercises the installed packaging entrypoint rather than falling back to local directory lookups.
- **Graceful skip fixture & zero environment mutation**: The `installed_bili_asr` fixture searches `sys.executable`'s directory and `PATH`, issuing a clear `pytest.skip` with exact installation commands when the binary is absent. This strictly respects the STOP condition prohibiting environment mutations during normal test execution.
- **Clear tier separation**: Maintains distinct test blocks for installed console scripts (`bili-asr`), Python module entrypoints (`python -m bili_asr`), and in-process direct API invocations (`cli.main`).
- **Installed status subcommand verification**: Covers both empty archives (`manifest: empty`) and populated archives with multiple record states (`archived: 1`, `meta_ok: 1`), validating argument parsing (`--archive-root`) and manifest aggregation through the installed binary.
- **Handoff documentation**: Plan handoff documentation in `.mstar/plans/20260825-state-machine-entrypoint-tests.md` cleanly specifies the exact environment-prep commands (`pip install -e ".[asr,dev]"` / `pip install -e .`) and skip behavior.
- **Zero product scope creep**: No production code was modified; all changes are confined to `test_cli_help.py` and the plan document.

### Issues

#### Critical

None.

#### Important

None.

#### Minor

- `bilibili-asr-archive/tests/test_cli_help.py:91, 101, 139`: `tmp_path` fixture parameters are annotated as `pytest.TempPathFactory` rather than `pathlib.Path` (`pytest.TempPathFactory` is the type for the session fixture `tmp_path_factory`, while `tmp_path` provides a `pathlib.Path`). This is a benign type-annotation cosmetic that does not affect runtime behavior.

### Assessment

**Task quality:** Approved
