---
module: bili-asr verification
date: 2026-09-18
last_updated: 2026-09-19
problem_type: testing_pattern
category: testing-patterns
severity: high
plan_id: 20260919-artifact-root
applies_when:
  - running any test, probe or measurement from a linked feature worktree
  - verifying a change made in a worktree before QC, QA or a merge
  - capturing RED evidence by stashing or checking out an older revision
  - a test result disagrees with the diff under review
tags:
  - linked-worktree
  - editable-install
  - false-evidence
  - git-stash
  - red-evidence
---

# Running the tests from a feature worktree: the invocation is part of the evidence

## Context

Iteration Phase 2 does its implementation work in **linked worktrees** under
`<repo-root>/.worktrees/<plan-id>`, one per plan, cut from the integration branch. The repo's virtualenv
lives in the **primary checkout** (`<repo-root>/bilibili-asr-archive/.venv`) and is an *editable* install:
its `.pth` hard-codes the **primary checkout's** `src` path. The venv is gitignored, so a new worktree has
no `.venv` of its own.

## Guidance

From a worktree, run tests with **both** the control-root interpreter and a pinned source path, and
confirm which tree you are actually testing before you believe any result:

```bash
cd <repo-root>/.worktrees/<plan-id>/bilibili-asr-archive
PYTHONPATH=$PWD/src <repo-root>/bilibili-asr-archive/.venv/bin/python -m pytest <selector> -v
# immediately before trusting anything:
PYTHONPATH=$PWD/src <repo-root>/bilibili-asr-archive/.venv/bin/python -c \
  "import bili_asr, pathlib; print(pathlib.Path(bili_asr.__file__).resolve())"
```

The printed path must be **under the worktree**. If it is not, the run says nothing about your diff.

## Why This Matters

Without the pinned `PYTHONPATH`, the editable install silently resolves `bili_asr` to the **primary
checkout** — the *unmodified* tree — so the suite grades the wrong code. The failure is quiet in both
directions and that is what makes it dangerous:

- a change that is genuinely broken can run **green**, because the old code is what executes;
- a probe run to capture a *baseline* failure can come back green, and the honest-looking conclusion
  ("I could not reproduce it") is false.

Either way the artefact is **false evidence**, which is worse than no evidence in a project whose gates
are built on recorded runs. It cost real time in `20260918-verification-surface-truth`: the first probe
returned a baseline failure from the wrong tree, and a later probe accidentally ran the full suite
against the primary checkout.

## When to Apply

Whenever a measurement is taken from a linked worktree: implementer self-checks, task reviewers reading
line numbers against a claim, QC/QA spot-runs, and any A/B or before/after comparison. The rule binds the
**citation**, not just the command: a report that records only "pytest … → N passed" without the pinned
interpreter and the resolved `bili_asr.__file__` has not recorded which code it tested.

## Examples

- **Wrong:** `cd .worktrees/<plan>/bilibili-asr-archive && .venv/bin/python -m pytest` → `No such file or
  directory` (no venv in the worktree) or, with the control-root interpreter, a green run of the old code.
- **Wrong:** `cd <repo-root>/bilibili-asr-archive && .venv/bin/python -m pytest tests/...` → correct
  interpreter, correct tree, but it is the **primary checkout**, not the worktree: it grades `main`.
- **Right:** the pinned form above, plus the resolved-path line quoted in the report.

A related trap lives at the other end of the same wire: a *full-suite red* whose cause is unknown may be
this same resolution problem rather than a real defect. Rule it out explicitly — with the resolved-path
probe — before blaming the suite, the environment or a competing process.

## The stash stack is shared with the primary checkout

A second, quieter way to corrupt evidence from a worktree: **`git stash push` followed by `git stash pop`
when the push saved nothing applies whatever is on top of the stack — and the stack is not per worktree.**
the stash ref lives in the common git directory, so a pop issued in a feature worktree takes the entry another
session left there.

Measured incident: a worktree session ran `git stash push -- <module>` to capture RED evidence after the
module was already committed, so the push created no entry; the `pop` that followed applied a pre-existing
stash belonging to a different session (`On main: iter close: local process artifacts …`). Four files of the
worktree's `.mstar/` copy came back unmerged and one untracked knowledge file appeared. The control root was
untouched — it is a different set of inodes (verified by distinct `st_dev:st_ino`), and neither tree carried
conflict markers after the repair. Repair: `git checkout HEAD -- <the affected paths>` plus removal of the
untracked file, which restores their pre-pop content exactly; then confirm `git stash list` still holds the
pre-existing entries and the fix commit contains only its in-scope files.

Two habits remove the hazard rather than repairing it:

```bash
git stash list                      # before popping: whose entry is on top?
git show <older-revision>:<path> > /tmp/red/<path>     # or: git archive <rev> | tar -x -C /tmp
```

Capturing RED evidence from a **committed** revision needs no stash at all: read the old file, or extract the
old tree with `git archive` and run the probe there. That is also what makes a dual-commit probe safe to run
in parallel with other sessions.

One verification note from the same incident: when checking a tree for conflict residue, use the strict
markers (`^<<<<<<< `, `^>>>>>>> `, `^||||||| `). A loose grep for `=======` reports Markdown heading
underlines as conflicts — the first pass over the repaired tree reported 9 hits for 0 real ones.

## Evidence

- The resolution trap: iteration `iter-2026-09-verification-surface-truth`, plan
  `20260918-verification-surface-truth` — the editable install in the primary checkout, the pinned invocation,
  and the resolved-path probe.
- The stash incident: `{SDD_DIR}/20260919-artifact-root/task-1-report.md:398-407` (the disclosure and the
  repair) and `{SDD_DIR}/20260919-artifact-root/task-1-review.md:175` (the independent verification: strict
  markers 0 in both trees, 14 knowledge files in both, `git ls-files -m -o --exclude-standard -- .mstar`
  empty in the worktree, both stash entries still present).
