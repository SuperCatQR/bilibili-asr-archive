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

`.mstar/**` is local process by default. The ignore rules carry four exceptions, and those
exceptions are the published set: **this file, `{SPECS_DIR}`, `{KNOWLEDGE_DIR}`, and
`{ITERATION_DIR}/<id>/specs/**`**. Everything else — `{PLAN_DIR}`, `{SDD_DIR}`, the rest of
`{ITERATION_DIR}` (package READMEs, `delivery-compass.md`, `guides/`), `.mstar/workflows/`,
`.mstar/projects/` — stays on the operator's machine.

**Amendment 2026-09-28 (architect ruling, compass D11).** The fourth exception is new. Iteration
*contract drafts* are published because the published set cites them: tracked files —
`{KNOWLEDGE_DIR}/architecture-patterns/audio-store-reconciliation.md`,
`{KNOWLEDGE_DIR}/architecture-patterns/metadata-delivery-hops-and-schema-evolution.md`,
`{KNOWLEDGE_DIR}/best-practices/completion-claims-need-live-evidence.md`,
`{KNOWLEDGE_DIR}/best-practices/premise-freshness-before-lock.md`, and others — name
`{ITERATION_DIR}/<id>/specs/*.md` and `{ITERATION_DIR}/<id>/guides/*.md` by exact path, so a clone
that dropped those drafts would carry dangling citations. Re-derive the exact set with
`grep -rhoE '\.mstar/iterations/[^ )`"]+\.md' $(git ls-files .mstar/specs .mstar/knowledge) | sort -u`.

**The amendment is deliberately *not* justified by "no tracked file cites the process face"** —
that claim is false and was checked rather than assumed:
`{KNOWLEDGE_DIR}/best-practices/completion-claims-need-live-evidence.md:137` cites
`{ITERATION_DIR}/iter-2026-09-metadata-audio-layout/delivery-compass.md` as its evidence, and
`premise-freshness-before-lock.md:98` cites a closeout `README.md`. **Those citations are
explicitly left as local-scope and are not a reason to publish the process face.** The rule the
set is built on is *kind*, not *citation count*: a **contract draft** (spec or guide) is the
durable artifact a knowledge note builds on and is published; the **process face** (compass,
package README, `{ITERATION_DIR}/README.md`) is superseded by `mstar-compound`'s promotion into
`{KNOWLEDGE_DIR}` at iteration close, so publishing it would compete with its own successor. The
two process-face citations above therefore resolve locally, exactly as the cross-line paragraph
below describes — and they are the **known, counted** exceptions, not an oversight.

So a citation that crosses that line (a knowledge note naming the SDD record it came from, a spec
naming the plan that produced it) resolves **locally, not in a clone**. **Five** kept files do
exactly that today — `{KNOWLEDGE_DIR}/architecture-patterns/operational-sidecars.md`,
`{KNOWLEDGE_DIR}/best-practices/claim-scope-discipline.md`,
`{KNOWLEDGE_DIR}/best-practices/completion-claims-need-live-evidence.md`,
`{KNOWLEDGE_DIR}/testing-patterns/hotword-list-measurement.md`, and `{SPECS_DIR}/asr-archive-cli.md`.
Re-derive with
`git grep -lE '\.mstar/(plans|sdd)/' <commit> -- .mstar/specs .mstar/knowledge` — **6 references
across 5 files at `371693b`**. The pair moved as knowledge landed: `18e8119` measured 3 files / 4
refs, `2696711` 4 / 5, and `d1c9600` onward 5 / 6. An earlier revision of this page said five files
and 166 references; the 166 was never reproducible, and the corrected pair is the one the command
returns **at the commit named**, which is why every count here is given per commit.

The published set, exactly as `.gitignore` decides it:

| Prefix | Tracked at `371693b` | Published? |
|--------|----------------------|------------|
| `.mstar/AGENTS.md` | 1 | yes (this file) |
| `.mstar/knowledge/**` | 26 | yes |
| `.mstar/specs/**` | 3 | yes |
| `{ITERATION_DIR}/**` | 9 | **only `<id>/specs/**`** (5 of the 9 — see Amendment above) |
| `{PLAN_DIR}/**` | 2 | no |
| **total** | **41** | **35 conform under this rule, 6 are frozen debt** |

**The 11 non-conforming paths are named, because "11 process files" is not actionable.**
Under the Amendment **five** of them are rule-consistent and need no action (they are iteration
`specs/` drafts, which the Amendment publishes); the remaining **six** are the frozen debt list
the plan A checker reads — they are delivery records of two *closed* iterations, so removing
them from the index is the operator's call, not a hygiene side effect:

| Path | Re-add commit | Verdict under the Amendment |
|------|---------------|-----------------------------|
| `{PLAN_DIR}/20260927-archive-db-queue-cutover.md` | `2696711` | **debt** — local; removal needs operator sign-off |
| `{PLAN_DIR}/20260927-evidence-dashboard.md` | `2696711` | **debt** — local; removal needs operator sign-off |
| `{ITERATION_DIR}/iter-2026-09-coverage-truth/README.md` | `2696711` | **debt** — local, package README |
| `{ITERATION_DIR}/iter-2026-09-coverage-truth/delivery-compass.md` | `2696711` | **debt** — local, process face |
| `{ITERATION_DIR}/iter-2026-09-metadata-audio-layout/delivery-compass.md` | `d1c9600` | **debt** — local, process face |
| `{ITERATION_DIR}/README.md` | `2696711` | **debt** — local, the index of a local tree |
| `{ITERATION_DIR}/iter-2026-09-coverage-truth/specs/exit-code-contract.md` | `2696711` | **published** — keep |
| `{ITERATION_DIR}/iter-2026-09-coverage-truth/specs/queue-cutover-contract.md` | `2696711` | **published** — keep, cited by `audio-evidence-queue-contract.md` |
| `{ITERATION_DIR}/iter-2026-09-metadata-audio-layout/specs/audio-retention-contract.md` | `cefed49` | **published** — keep, cited |
| `{ITERATION_DIR}/iter-2026-09-metadata-audio-layout/specs/metadata-coverage-contract.md` | `cefed49` | **published** — keep, cited |
| `{ITERATION_DIR}/iter-2026-09-metadata-audio-layout/specs/output-layout-options.md` | `d1c9600` | **published** — keep, uncited but a contract draft |

Re-derive the split and the attribution with the two commands that own it — there is no
hand-maintained count on this page any more:

```bash
git ls-files .mstar | grep -vE '^\.mstar/(AGENTS\.md|specs/|knowledge/|iterations/[^/]+/specs/)'
git log --diff-filter=A --format='%h %ad %s' --date=short -- <path>
```

A future plan that force-adds a process file is a **finding**, not a style preference: the
checker plan `20260928-harness-state-contract` asserts this split (compass **D11**), so the next
violation fails a repo test instead of waiting for the next hygiene pass.

Made true on 2026-09-25 (`18e8119`, `chore(repo): make .mstar local-only, as its own ignore rules
always said`): **527** process files had been force-added over time against these rules and were
removed from the index, not from disk. Re-derive with
`git show --name-status --format='' 18e8119 | grep -c '^D'`.

## Product root

Application code lives under `bilibili-asr-archive/`.
