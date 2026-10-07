# Repository Structure Flattening Plan

## Decision

The Python product currently lives below `bilibili-asr-archive/`, while the
repository root also carries a tracked `.mstar/` process harness and old
workspace documents. The target layout is a single product root: the contents
of `bilibili-asr-archive/` move to the repository root, and the mstar harness
is removed from the active repository contract.

The former control-root `README.md`, `AGENTS.md`, `CONCEPTS.md`, and
`HANDOFF.md`, together with `pytest-of-ChosenEcho/` and
`verification-results/`, are deprecated workspace artifacts. The product
README from the nested package is now the root `README.md`; the other control
artifacts are ignored at the control-root level. Existing tracked files are
not silently deleted by `.gitignore`; cleanup is an explicit migration step
below.

## Target layout

```text
.
├── pyproject.toml
├── uv.lock
├── src/bili_asr/
├── tests/
├── scripts/
├── docs/
├── references/
├── notes/
├── archive/                 # ignored operator data
├── models/                  # ignored checkpoints
└── .github/workflows/ci.yml
```

The product `README.md` moves to the repository root after the deprecated
workspace README is removed. Its installation examples and all code, test,
CI, and documentation references must then use root-relative paths.

## Migration phases

1. **Freeze the boundary.** Keep the anchored ignore rules in `.gitignore` and
   record the pre-migration status. Do not stage or overwrite unrelated local
   changes already present in the checkout.
2. **Remove the old process surface.** Delete the tracked `.mstar/` tree and
   remove the mstar-only CI job, validator scripts, harness tests, and active
   documentation links. Historical reports may remain only when they are
   clearly marked as archived evidence and no active command or test reads
   them.
3. **Move the product one level up.** Use Git-aware renames for the contents
   of `bilibili-asr-archive/` (`src`, `tests`, `scripts`, `docs`, `references`,
   `notes`, `pyproject.toml`, `uv.lock`, `PLAN.md`, and the product README).
   Do not move ignored runtime data such as `archive/`, `models/`, virtual
   environments, caches, or temporary directories.
4. **Rewrite path contracts.** Update packaging, pytest discovery, CLI install
   hints, archive/model defaults, CI working directories, shell examples, and
   tests so they resolve from the repository root. Remove obsolete
   `bilibili-asr-archive/` prefixes and all `.mstar` assumptions.
5. **Rebuild ignore rules.** Convert data/cache rules to root-relative paths
   (`/archive/`, `/models/`, `/logs/`, test scratch, and generated reports).
   Retain only the explicit root rules that prevent deprecated control
   artifacts from returning; the replacement product README remains tracked.
6. **Validate and clean up.** Run the full offline test suite, package build and
   installed CLI smoke, compile checks, `git diff --check`, and a repository
   search for active `bilibili-asr-archive/`, `.mstar`, and mstar package/CLI
   references. Confirm that no ignored media, checkpoints, caches, or local
   reports enter the index.

## Acceptance checks

- `python -m pip install -e ".[dev]"` works from the repository root.
- `python -m pytest -q` discovers the same product tests from the root.
- `python -m build --sdist --wheel` produces a usable distribution.
- `bili-asr --help` works from an installed environment.
- CI has no mstar installation or harness validation job.
- Active source, tests, scripts, and docs contain no `.mstar` or `mstar`
  dependency; retained historical evidence is isolated and non-executable.
- `git status --short --ignored` shows only expected local runtime artifacts.

## Risks and order constraints

- Move files before changing import paths so Git can preserve rename history.
- Update CI and package metadata in the same change as the move; otherwise a
  fresh checkout will install or test from a path that no longer exists.
- Remove harness tests together with the harness validator. Keeping them after
  `.mstar/` is removed would make the default suite depend on a deprecated
  external CLI.
- Do not delete archived evidence until active references have been removed and
  the replacement root-relative documentation has passed the validation checks.
