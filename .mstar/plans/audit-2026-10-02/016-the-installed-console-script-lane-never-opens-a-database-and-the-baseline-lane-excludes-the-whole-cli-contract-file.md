# Plan 016 — Make the installed lane open a database, and give the baseline lane its contract file back

## Status
- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Confidence**: HIGH
- **Fingerprint**: audit-2026-10-02r2/06-installed-lane-baseline-scope
- **Depends on**: none
- **Category**: tests
- **Evidence**: `bilibili-asr-archive/tests/test_cli_help.py:27-42` — the only `run_installed` calls; `bilibili-asr-archive/scripts/verify_baseline.py:271-279` — the staged-tree exclusion; `bilibili-asr-archive/pyproject.toml:84-92` — the registered markers
- **Planned at**: commit `1e756df`, 2026-10-02
- **Captured issues**: `I-000174` (installed lane), `I-000175` (baseline scope); rider covers the DX-02 lead

## Problem

Two independent verification-surface gaps.

### 1. The installed console-script lane never opens a database

`tests/test_cli_help.py`'s isolated-install lane calls `run_installed(...)` four times — `--help` at
`:31` and `:69`, and `status` at `:41` and `:97` — and the `status` calls fail with "no archive
database" **before** any database open. The lane's own docstring (`tests/installed_cli.py:3-10`)
claims it is the installation-delivery proof.

Meanwhile `src/bili_asr/storage/database.py:55-57` loads the schemas via `resources.files(__package__)`
and they are declared only in `pyproject.toml:81-82` (`[tool.setuptools.package-data]`). A one-line
packaging regression that drops `schema.sql` / `schema-transcripts.sql` from the wheel — or a missing
runtime dependency in `[project.dependencies]` — leaves **every** installed-lane test green while the
shipped `bili-asr` is unusable. The 44+ in-process CLI tests that do open databases all run against
the sys.path source tree (`tests/conftest.py:21`), not the artifact.

### 2. The baseline lane excludes a file holding ~44 in-process contract tests

`scripts/verify_baseline.py`'s staged tree uses a file-level ignore set:

```python
            if name in {"test_verify_baseline.py", "test_installed_cli.py", "test_cli_help.py"}
```

`tests/test_cli_help.py` holds **49** `def test_` definitions, of which only **5** take the
`isolated_cli` fixture (`:30`, `:39`, `:67`, `:90`, `:927`). The other ~44 are pure in-process
`main()` / `capsys` contract tests (the `coverage --reference` family, redaction, CSV column
freeze) — so the repository's declared "complete product pytest suite" (`README.md:443`) never
exercises a whole subsystem's CLI surface.

The name the ignore set already references — `test_installed_cli.py` — **does not exist**; the lane's
own helper documents that command at `tests/installed_cli.py:65`.

## Current state (excerpts — verify against live code before editing)

`bilibili-asr-archive/tests/test_cli_help.py:25-42`:

```python
def isolated_cli(tmp_path_factory: pytest.TempPathFactory):
    ...
    return provision_isolated_cli(str(tmp_path_factory.mktemp("isolated-cli") / "venv"))


def test_installed_console_script_help(isolated_cli) -> None:
    proc = run_installed(isolated_cli, ["--help"])


def test_installed_console_script_status_fails_without_database(isolated_cli, tmp_path: Path) -> None:
    ...
    proc = run_installed(isolated_cli, ["status", "--archive-root", str(archive_root)])
```

`bilibili-asr-archive/scripts/verify_baseline.py:269-279`:

```python
    staged = destination / "tests"
    shutil.copytree(
        ROOT / "tests",
        staged,
        ignore=lambda directory, names: {
            name
            for name in names
            if name in {"test_verify_baseline.py", "test_installed_cli.py", "test_cli_help.py"}
            or name == "__pycache__"
            or name.endswith(".pyc")
        },
    )
```

`bilibili-asr-archive/tests/installed_cli.py:65` (the intended name):

```python
        f"python -m pytest tests/test_installed_cli.py -q",
```

## Conventions to follow

- The lane's fixture (`tests/conftest.py`'s `isolated_cli` / `tests/installed_cli.py`'s
  `provision_isolated_cli`) already pays the install cost module-wide — reuse it, do not provision a
  second venv.
- `scripts/verify_baseline.py` runs the staged suite with a **network-deny guard** and `safe_env()`
  (`:290-306`); any new test must stay offline (the isolated lane is offline by construction — the
  schema is a package resource).
- Read the launcher's exit-code contract before asserting one: `bili-asr status` on a seeded root is
  the natural probe, but confirm which exit code a healthy store produces in-process first, and assert
  that.

## Tasks

### Task 1 — Give the installed lane a database (Effort: S)

**Files**
- Create: `bilibili-asr-archive/tests/test_installed_cli.py`
- Modify: `bilibili-asr-archive/tests/test_cli_help.py` (move the five `isolated_cli` tests out; leave
  the in-process family where it is)

**Rider (from the same audit seat, effort XS).** Document the marker lanes landed by plan 008 while
you are in the test surface: `README.md:1334,1352,1369` documents only the per-file
`BILI_LIVE_SMOKE=1 … pytest tests/test_<file>` idiom, and `rg -n '\-m live_smoke|\-m scale' README.md
docs/*.md` returns no hits although `pyproject.toml:84-92` registers the three markers. Add one
paragraph next to the existing live commands naming `-m live_smoke` / `-m scale` / `-m slow`, and
either remove the registered-but-unused `slow` marker or annotate it as reserved
(`rg -n 'mark.slow' tests/` returns no users). Do not expand this into a broader test-docs rewrite.

**Change.** Move the installer tests into `tests/test_installed_cli.py` — the name
`scripts/verify_baseline.py` already excludes and `tests/installed_cli.py:65` already documents — and
add one new case there:

- provision the isolated CLI (existing fixture),
- create an archive root and run an installed command that **opens or materializes** the database
  (e.g. `status --archive-root <root>` on a root seeded by the fixture, or a command that creates the
  DB),
- assert exit 0 and an output line that could only come from a schema-backed read.

Keep the existing "not path or checkout source" test (`:67-69`) in the same file so the artifact
identity assertion travels with the lane.

**In scope**: `bilibili-asr-archive/tests/test_installed_cli.py` (new),
`bilibili-asr-archive/tests/test_cli_help.py`, `bilibili-asr-archive/scripts/verify_baseline.py`
(only if the ignore set needs its comment updated — the name already matches).

**Out of scope**: the build backend / `pyproject.toml` packaging declarations (they are the thing
being verified, not changed), `tests/installed_cli.py`'s provisioning logic, the offline wheel
fixture story (that is plan 017's sibling `I-000177`).

### Task 2 — Prove the new case can fail (Effort: XS, same round)

Add the mutation control the repo's own testing knowledge requires: the new installed-lane case must
be shown to go red when the schema resource is absent. Cheapest faithful control: temporarily remove
one entry from `[tool.setuptools.package-data]` in a scratch copy (or build the wheel with the entry
dropped) and observe the failure — **record the observation, then restore**. Do not commit a modified
`pyproject.toml`.

## STOP conditions

- If `tests/test_cli_help.py` no longer holds 49 definitions / 5 fixture users, STOP and re-count
  before splitting — the split shape depends on it.
- If no installed command can reach a database without a network call or a non-packaged resource,
  STOP and report: that is a packaging finding in its own right, and this plan must not paper over it
  by asserting something weaker.
- If `scripts/verify_baseline.py`'s exclusion has already been narrowed, STOP — only the missing test
  remains.
- Do **not** run the offline wheel baseline to validate this plan (it needs a per-host fixture that
  does not exist here); validate with the direct `pytest` invocation below.

## Drift check

```
git diff --stat 1e756df..HEAD -- bilibili-asr-archive/tests/test_cli_help.py bilibili-asr-archive/scripts/verify_baseline.py bilibili-asr-archive/pyproject.toml
```

If any changed, re-read the lane and the exclusion before proceeding.

## Done criteria

- [ ] `bilibili-asr-archive/tests/test_installed_cli.py` exists and carries the installer tests plus
      the new database-opening case
- [ ] `tests/test_cli_help.py` retains the in-process contract family; no test is lost in the move
      (record the before/after definition counts)
- [ ] The new case fails with the schema package-data entry removed and passes with it restored
      (record both observations)
- [ ] `cd bilibili-asr-archive && PYTHONPATH=$PWD/src python -m pytest -q tests/test_installed_cli.py tests/test_cli_help.py` passes; record the command and result
- [ ] `rg -n "test_installed_cli.py" bilibili-asr-archive` resolves to a file that now exists
- [ ] `git diff --check` exits 0; `git status --short` shows no out-of-scope file

## Verification notes

The installed lane provisions its own venv; expect it to be the slowest test in the file. Run only
these two files, not the suite. `pyproject.toml` must be byte-identical to its committed state at the
end (`git diff -- pyproject.toml` empty).

## Engine lifecycle ownership

Source-only test-infrastructure change, no lifecycle claim. Advanced by PM through the normal per-plan
flow; no delivery tail promised.
