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

## Published vs local

`.mstar/**` is local process by default. The ignore rules carry three exceptions, and those
exceptions are the published set: **this file, `{SPECS_DIR}`, `{KNOWLEDGE_DIR}`**. Everything else —
`{PLAN_DIR}`, `{SDD_DIR}`, `{ITERATION_DIR}`, `.mstar/workflows/`, `.mstar/projects/` — stays on the
operator's machine.

So a citation that crosses that line (a knowledge note naming the SDD record it came from, a spec
naming the plan that produced it) resolves **locally, not in a clone**. Fourteen kept files do
exactly that; the reference is not broken, it is scoped. Made true on 2026-09-25: 527 process files
had been force-added over time against these rules and were removed from the index, not from disk.

## Product root

Application code lives under `bilibili-asr-archive/`.
