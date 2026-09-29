---
iteration_id: iter-2026-09-text-and-ledger-precision
plan_id: 20260918-operational-record-coverage
guide: pilot-attempt-ledger-boundary
date: 2026-09-18
subject: Which entry point feeds `--scope failed` — the `pilot` boundary, written down
residual: "e2e-23191782-season-7686105 · R4"
decision: boundary written into both product surfaces; no behaviour change
---

# The pilot attempt-ledger boundary (2026-09-18)

**Question.** The stage-attempt ledger is the only source `--scope failed` reads. Which entry points
write attempts into it, and what does that mean for a row the `pilot` archived? The season audit
answered the second half by measurement and found the answer nowhere in the product: an
operator-reading surface never named the boundary, so the contract's own warning — "otherwise
`--scope failed` silently drops rows" — applied to a path the contract does not name.

**Answer (now stated in both operator surfaces).** The stage-attempt ledger is written by the run
coordinator behind `bili-asr run`, `bili-asr schedule` and `bili-asr campaign` — `RunCoordinator` is
the one appender, and all three entry points drive it. Work archived through the `pilot` entry point
leaves no attempt records, so no per-stage truth exists for pilot work and it is **not** reachable by
`--scope failed`. `pilot` is a bounded probe, not a corpus path. This guide is the knowledge-destined
copy for `mstar-compound` to promote at iteration-close; `{KNOWLEDGE_DIR}` was not written during
Execute (plan Global Constraints).

---

## 1. The boundary text as shipped

Both surfaces carry the same statement, and both carry the literal token `` `--scope failed` ``, so
the acceptance grep reads the boundary rather than a proxy for it.

### 1.1 `pilot --help` (`src/bili_asr/cli.py`, the `pilot` subparser's new `description=`)

```
Bounded mixed-branch probe (subtitle-hit and audio→ASR), not a corpus
path. The stage-attempt ledger is written by the run coordinator behind
`bili-asr run`, `bili-asr schedule` and `bili-asr campaign`: work archived
through this entry point leaves no attempt records, so no per-stage truth
exists for pilot work, and it is not reachable by `--scope failed`.
```

The text goes in `description=`, not in the pre-existing `help=` string: `help=` is rendered only in
the top-level `bili-asr --help` command list, while `pilot --help` printed usage plus option help and
**no description at all** before this change (measured — §4.1). The subparser also takes
`formatter_class=argparse.RawDescriptionHelpFormatter`: the default formatter re-wraps the paragraph
with `textwrap`'s hyphen breaking on, which can split the literal token at its own hyphen depending on
the terminal width. Raw description keeps the line breaks, so the token is intact at any width
(verified at `COLUMNS=50` as well as the 80-column pipe the check uses). No argument help line is
affected — `_split_lines` is unchanged.

### 1.2 `README.md`, the recovery paragraph beside the exit-code table (L1021-1029)

```markdown
Successful rows stay in their last stable status. Retryable failures remain
selectable by the same command or by `run --scope failed`. That recovery path
reads the stage-attempt ledger that the run coordinator behind `bili-asr run`,
`schedule` and `campaign` writes: work archived through the `pilot` entry point
leaves no attempt records, so no per-stage truth exists for pilot work and it is
not reachable by `--scope failed`. `pilot` is a bounded probe, not a corpus
path. Explicit `run --scope` work_id selectors of already-terminal rows skip
with `already_terminal` and exit 0; they are not duplicated.
```

Kept to the fact and its consequence: the places the recovery path does work are named
(`bili-asr run`, `schedule`, `campaign`), and nothing else is advised.

**Writer list widened (QC fix wave, 2026-09-18).** Both surfaces first said "`bili-asr run`"
alone, which reads as "work archived by `schedule`/`campaign` also leaves no attempt trail" — the
opposite of the truth, since all three drive the same `RunCoordinator`. The pilot half of the claim
is unchanged and still exact (`pilot` constructs no coordinator and writes no attempts), and the
literal token `` `--scope failed` `` is still in `pilot --help` (now line 10 of the 80-column
output, because the description gained a line).

## 2. Why the boundary is true (contract target, read-only)

- `{KNOWLEDGE_DIR}/architecture-patterns/operational-sidecars.md` §3 scopes the sidecar to the run
  coordinator: "**Run coordinator** (`bili-asr run`): stage-attempt ledger at
  `{archive_root}/coordinator/attempts.jsonl` with `harvest|download|asr|archive` ×
  `ok|failed|skipped`. … **Every executed stage must persist an attempt**, including
  download/archive failures — otherwise `--scope failed` silently drops rows." The pilot's omission is
  therefore inside the letter of that contract but outside what an operator could read.
- `AttemptLedger` has exactly one instantiation site in `src/`: `coordinator.py:344`
  (`self.ledger = AttemptLedger(self.root)`), i.e. inside `RunCoordinator`. The pilot runs its own
  in-process loop and constructs no coordinator-with-ledger, so it persists no attempts.
- `--scope failed` is defined next to the ledger: `cli.py`'s scope resolver calls
  `RunCoordinator(...).failed_work_ids()`, which returns the work ids with at least one recorded
  **failed attempt** in `coordinator/attempts.jsonl` (`coordinator.py:380-386`), intersected with
  manifest rows that are not `archived`/`gone`. No attempt records ⇒ nothing for the selector to see.

## 3. The measured evidence this closes (`R4`)

`{PROJECT_DIR}/_default/residuals.json` → `e2e-23191782-season-7686105 · R4` (severity `low`,
decision `defer`, registered 2026-09-17):

- **Source:** full artifact audit of the season run's archive root, 2026-09-17
  (`{WORKFLOW_DIR}/e2e-23191782-season-7686105/reports/e2e.md`, gap G1).
- **Measured:** the A2 probe item `BV1RFoxBqEzo:p0` is `archived` in the season manifest and has
  `stages=[]` in `coordinator/attempts.jsonl` — **zero records** — while all **13** run-archived rows
  carry `download+asr+archive`.
- **Consequence:** the pilot-archived row is invisible to `--scope failed`; and because the pilot does
  keep its own run-ledger row, `run-ledger.jsonl` shows one pilot row for an archive whose attempt
  ledger has no trace of that work.
- **Disposition in this plan:** the register's cheaper arm — state the boundary where an operator
  reads it — rather than give the pilot a ledger of its own. No behaviour change, no new sidecar.

The season archive root itself is not in this repository (the audit ran against the remote archive
host), so this section cites the register's recorded measurement; nothing here is a re-measurement and
nothing claims to be.

## 4. The three named checks, before and after

Working directory for all three (feature worktree, which has no `.venv`):
`/root/workspace/bilibili-asr-archive/.worktrees/20260918-operational-record-coverage/bilibili-asr-archive`,
with the control-root interpreter and `PYTHONPATH=$PWD/src` (the form pinned in
`{KNOWLEDGE_DIR}/architecture-patterns/worktree-test-invocation.md`).

Resolution probe, before any result was believed:

```
$ PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python \
    -c "import bili_asr, pathlib; print(pathlib.Path(bili_asr.__file__).resolve())"
/root/workspace/bilibili-asr-archive/.worktrees/20260918-operational-record-coverage/bilibili-asr-archive/src/bili_asr/__init__.py
```

### 4.1 Check 1 — `pilot --help` carries the boundary

```
$ PYTHONPATH=$PWD/src <control-venv>/bin/python -m bili_asr pilot --help | grep -n -- "--scope failed"
```

| State | Observed | Exit |
|-------|----------|------|
| Before (HEAD `0fc963d` blob, extracted to `/tmp/baseline-0fc963d`) | *no output* | `1` |
| Before (measured in-session on the unedited worktree, 2026-09-18) | *no output* | `1` |
| After (worktree, commit `5bcf0bf`, Task 1) | `9:exists for pilot work, and it is not reachable by \`--scope failed\`.` | `0` |
| After (worktree, commit `36a642d`, QC fix wave: writers named) | `10:exists for pilot work, and it is not reachable by \`--scope failed\`.` | `0` |

The pre-edit baseline is reproducible without touching the worktree:
`git -C <worktree> archive HEAD \| tar -x -C /tmp/baseline-0fc963d`, then run the CLI with
`PYTHONPATH=/tmp/baseline-0fc963d/bilibili-asr-archive/src` (module probe printed the baseline path, so
the run is known to be grading the pre-edit tree). The check discriminates.

### 4.2 Check 2 — the README recovery paragraph carries it too

```
$ grep -n -- "--scope failed" README.md
```

| State | Observed lines |
|-------|----------------|
| Before (README at HEAD `0fc963d`) | `357: bili-asr run --scope failed --limit 5 …`, `1022: selectable by the same command or by \`run --scope failed\`. Explicit \`run` |
| After (commit `5bcf0bf`, Task 1) | the same `357` and `1022`, **plus** `1025: truth exists for pilot work and it is not reachable by \`--scope failed\`.` |
| After (commit `36a642d`, QC fix wave) | `357`, `1023: selectable by the same command or by \`run --scope failed\`. That recovery path`, **plus** `1027: not reachable by \`--scope failed\`. \`pilot\` is a bounded probe, not a corpus` |

Line `1027` sits inside the recovery paragraph at `README.md` L1021-1029, directly below the exit-code
table (L1012-1017). The pre-existing `run --scope failed` mentions are not the check; the new line is.

### 4.3 Check 3 — `tests/test_cli_help.py` stays green

```
$ UV_CACHE_DIR=/root/workspace/bilibili-asr-archive/.tmp/uv-cache-full \
    PYTHONPATH=$PWD/src <control-venv>/bin/python -m pytest tests/test_cli_help.py -q
...........................................                              [100%]
43 passed in 2.57s          (exit 0)
```

Environment note, recorded because it changes what the raw command reports: the five
`isolated_cli`-fixture tests provision a throwaway virtualenv with `uv`, and `uv` needs a **writable**
cache. In this sandboxed worktree session the default `/root/.cache/uv` is read-only, so the bare
command ends `38 passed, 5 errors` — all five errors are fixture setup prerequisites
(`uv venv failed (Read-only file system … /root/.cache/uv/.tmpXXXX)`), unrelated to the help text and
present at the pre-edit baseline as well. Pointing `UV_CACHE_DIR` at a writable copy of that cache
(`cp -a /root/.cache/uv <writable dir>`, gitignored scratch, outside the worktree) restores the install
path and the file is fully green (`43 passed`, exit 0). No test, selector or assertion was changed; only
the cache location was redirected.

The help-text edit is what this check guards: the top-level `--help` assertions and the
`build_parser()`-level help assertions all remain satisfied.

## 5. What this changes, and what it does not

- **Changed:** two product files — `bilibili-asr-archive/src/bili_asr/cli.py` (the `pilot` subparser's
  new `description=` + `formatter_class=`) and `bilibili-asr-archive/README.md` (the recovery
  paragraph). Diff basis `0fc963d..5bcf0bf`, 2 files, `+17 / -3`.
- **Not changed:** `pilot`'s execution logic, `coordinator.py`, `_cmd_run`, the attempt ledger, the
  manifest, exit codes — no behaviour change of any kind. No test file was created; the verification
  mode for this task is `scoped-check` (non-executable documentation surface).
- `{KNOWLEDGE_DIR}/**` was **not** written: this guide is the promotion input for `mstar-compound` at
  iteration-close (plan Global Constraints; compass criterion 2).
- `R4`'s closure is the PM's register write, not a leaf action.

## 6. Artifacts

| Artifact | Location |
|----------|----------|
| Product change (commit `5bcf0bf44c6708a783650172051b84789586c53a`) | `bilibili-asr-archive/src/bili_asr/cli.py`, `bilibili-asr-archive/README.md` on `fix/20260918-operational-record-coverage` |
| Task brief | `{SDD_DIR}/task-1-brief.md` |
| Task report (implementer) | `{SDD_DIR}/task-1-report.md` |
