# AGENTS.md — `.mstar/` harness

## Path symbols

| Symbol | Path |
|--------|------|
| `{HARNESS_DIR}` | `.mstar/` |
| `{PLAN_DIR}` | `.mstar/plans/` |
| `{SDD_DIR}` | `.mstar/sdd/<plan-id>/` |
| `{ITERATION_DIR}` | `.mstar/iterations/` |
| `{KNOWLEDGE_DIR}` | `.mstar/knowledge/` |
| `{SPECS_DIR}` | `.mstar/specs/` |

## Content boundaries

- `docs/` — human docs (install, contribute)
- `{SPECS_DIR}` — frozen specs / ADRs
- `{ITERATION_DIR}` — iteration packages
- `{KNOWLEDGE_DIR}` — reusable implementation SSOT
- `{PLAN_DIR}` — main plans + durable gate summaries

## What travels with Git

`.mstar/**` is tracked, so `git worktree add` gives a fresh checkout the same harness the primary
checkout has — plans, SDD records, workflow snapshots, project registers, the root register,
iteration packages, knowledge and specs. Only genuinely **volatile** state stays local: state that
is true on one machine or for one run, and that would churn the repository on every command.

| Excluded (stays local) | Why |
|------------------------|-----|
| `{SDD_DIR}` | engine-owned runtime scratch: `mstar sdd workspace` writes its own `.gitignore` holding `*` into every `<plan-id>/`, and a nested ignore file outranks the repository's rules |
| `.mstar/snapshots/` | a live engine/status cache, rewritten continuously while sessions run |
| `.mstar/sess-probe.log` | a session log of this host |
| `.mstar/**/*.bak*`, `.mstar/**/*.bak-*` | operator backups of register files |
| `.mstar/.execution-maintenance/` | machine-local execution scratch |

Everything else under `.mstar/` is expected to be tracked, including `{PLAN_DIR}`,
`{ITERATION_DIR}` package READMEs and `delivery-compass.md`, `.mstar/workflows/` and
`.mstar/projects/`. `bilibili-asr-archive/scripts/validate_harness_state.py` holds this boundary
as one of its legs: a **volatile** path that is tracked fails the run, and every other tracked
path under the harness dir is tolerated.

### Supersedes: the process-local published set (compass D11)

Until 2026-09-29 the opposite rule applied. `.mstar/**` was ignored by default with four
exceptions — this file, `{SPECS_DIR}`, `{KNOWLEDGE_DIR}`, `{ITERATION_DIR}/<id>/specs/**` — and
everything else was "process face" that stayed on the operator's machine. That boundary is now
**repealed**, deliberately and by operator decision, because it made a worktree unable to carry
the harness it was supposed to work against.

What the old rule got right, kept here as a warning rather than as a rule: a **process face** —
a compass, a package README, an iteration index — is superseded by `mstar-compound`'s promotion
into `{KNOWLEDGE_DIR}` at iteration close, so tracking it means carrying a document that competes
with its own successor. Tracked is not the same as current; read the compass as the record of a
plan at the time it was written, not as the description of `HEAD`.

Two consequences of the repeal worth stating plainly, because the old page argued the reverse:

- **Citations that cross the harness/product line now resolve in a clone.** A knowledge note
  naming the SDD record it came from, or a spec naming the plan that produced it, used to be a
  known local-scope exception. Those paths are tracked now, so such a citation is a normal
  reference.
- **The frozen-debt list is gone.** The six paths that used to be tolerated as frozen debt are
  simply tracked. There is no debt table on this page to update, and no re-add attribution to
  maintain; `20260928-harness-state-contract`'s checker no longer reads one.

### Re-derive the split

There is no hand-maintained count on this page. The two commands that own the answer:

```bash
# what the ignore rules say about a path (the verdict, per path)
git check-ignore -q --no-index <path> && echo local || echo trackable

# every tracked harness path the boundary leg would judge
git ls-files .mstar | wc -l
```

`bilibili-asr-archive/scripts/validate_harness_state.py` prints the boundary verdict for the whole
directory, and `bilibili-asr-archive/tests/test_harness_state.py` holds both halves of it: a
force-added volatile path goes red, and a force-added plan / SDD / workflow / register /
iteration-README path stays green.

## Product root

Application code lives under `bilibili-asr-archive/`.
