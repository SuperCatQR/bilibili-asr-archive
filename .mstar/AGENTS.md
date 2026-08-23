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
- `{PLAN_DIR}` — main plans + durable gate summaries (local process; gitignored)

## Product root

Application code lives under `bilibili-asr-archive/`.
