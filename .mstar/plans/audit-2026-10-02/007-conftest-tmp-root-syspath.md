# Plan 007 — Fix conftest `sys.path` hacks + `tmp_root` PID-reuse flake

## Status
- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: tests
- **Confidence**: HIGH
- **Evidence**: `tests/conftest.py:15,20,125-138`; `tests/test_audio_budget.py:111`; forensics note `tests/conftest.py:25-36`
- **Planned at**: commit `ff39fd0`, 2026-10-02

## Problem

Two intertwined test-infrastructure problems:

1. **`sys.path` hacks** (`conftest.py:15,20`, and again ad hoc at `test_audio_budget.py:111`): the suite
   loads `src/` and the repo root onto `sys.path` because the package is not pip-installed into the test
   interpreter. The suite therefore silently tests a **sys.path-loaded source tree**, not the installed
   artifact — the same trap `tests/installed_cli.py:4-8` warns about for console-script verification, but
   applied suite-wide.
2. **`tmp_root` PID-reuse flake** (`conftest.py:124-138`): the fixture names dirs
   `manifest-test-{pid}-{counter}` under a shared `<repo>/.test-tmp/`. The comment at `:128-131` explains the
   sandbox denies `%TEMP%` creation from Python, so it hand-rolls a workspace-local temp dir. Because the
   name is PID+counter only, a leftover dir from a killed run collides on PID reuse → `FileExistsError` →
   a random setup red. This is a recorded source of the intermittent full-suite reds (the forensics hook at
   `conftest.py:25-36` exists to catch the `261 / 0 / 196 / 0` setup-error pattern).

## Current state (excerpts)

`tests/conftest.py:15-22`:
```python
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
```

`tests/conftest.py:124-138`:
```python
@pytest.fixture
def tmp_root():
    os.makedirs(_TEST_TMP_BASE, exist_ok=True)
    path = os.path.join(_TEST_TMP_BASE, f"manifest-test-{os.getpid()}-{next(_counter)}")
    os.makedirs(path)                       # raises FileExistsError on PID reuse + same counter
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
```

## Approach

1. **`sys.path`**: build the path once, in one place, with a comment block explaining the sandbox
   constraint. Keep the two `insert` lines but consolidate them into a single clearly-labelled block at the
   top of `conftest.py` (a tiny `sitecustomize`-style preamble), and delete the ad-hoc
   `sys.path.insert(0, "tests")` in `test_audio_budget.py:111` (conftest already puts the repo root on the
   path). Do **not** switch to a pip-installed test run — the current interpreter is intentionally not the
   installed artifact; the goal is to make the sys.path loading explicit and single-sourced, not to change
   what is tested.
2. **`tmp_root` PID-reuse**: make the fixture tolerate a leftover dir. Either:
   - add a unique suffix (e.g. a UUID or `time.time_ns()` component) so a leftover never collides; **or**
   - keep the deterministic name but on `FileExistsError`, refuse-and-recreate (rmtree the stale dir and
   recreate) — only safe if the dir is provably stale.
   The UUID-suffix option is simplest and safe. Also pin the reuse case with a test (below).

## Files

- **Modify**: `tests/conftest.py` — consolidate the sys.path preamble; harden `tmp_root` against PID reuse.
- **Modify**: `tests/test_audio_budget.py` — remove the ad-hoc `sys.path.insert(0, "tests")` at `:111`.
- **Test**: `tests/test_conftest_tmp_root.py` (new) — or add to an existing conftest-adjacent test — for the
  reuse-tolerance pin below.

## Out of scope

- Changing what the suite tests (it still tests the source tree via sys.path; this plan only makes that
  explicit and removes the flake).
- The broader "test the installed artifact" question — that is `tests/installed_cli.py`'s lane, not this plan.
- Mocking strategy (`mock_torch`) — by-design, do not touch.

## Verification gates

- **Reuse-tolerance test**: create a stale `manifest-test-<pid>-<n>` dir to simulate a killed run, then
  invoke `tmp_root` and assert it yields a usable, distinct directory (no `FileExistsError`).
  - Run: `python3.12 -m pytest tests/test_conftest_tmp_root.py -k tmp_root_reuse -v` → passes.
- **No-ad-hoc-sys.path**: `rg -n 'sys.path.insert' tests/test_audio_budget.py` → no match (the insert is
  removed).
- Existing suite still green on the touched paths:
  - Run: `python3.12 -m pytest tests/test_storage_schema.py tests/test_audio_budget.py -q` → passes (a
    tmp_root-heavy file + the file that lost its ad-hoc insert).
  - Run: `python3.12 -m pytest tests/test_manifest.py -q` → passes (the primary tmp_root consumer).

## STOP conditions

- If removing the `sys.path.insert(0, "tests")` in `test_audio_budget.py` breaks that file's imports (i.e.
  conftest does **not** already make `tests/` importable), STOP — report the actual import error; do not
  re-add the insert without understanding why the conftest path did not cover it.
- If hardening `tmp_root` changes its yield type or contract observed by existing tests, STOP and list the
  affected consumers.

## Done criteria

- [ ] `python3.12 -m pytest tests/test_conftest_tmp_root.py -k tmp_root_reuse -v` passes.
- [ ] `rg -n 'sys.path.insert' tests/test_audio_budget.py` → no match.
- [ ] `python3.12 -m pytest tests/test_storage_schema.py tests/test_audio_budget.py tests/test_manifest.py -q` passes.
- [ ] `git diff --check -- tests/conftest.py tests/test_audio_budget.py tests/test_conftest_tmp_root.py` exits 0.
- [ ] No files outside the Files list are modified.

## Drift check

`git diff --stat ff39fd0..HEAD -- tests/conftest.py tests/test_audio_budget.py` — if either changed, re-open the excerpts and confirm the sys.path block and tmp_root body still match before editing.
