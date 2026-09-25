# HANDOFF — bilibili-asr-archive

**Parked 2026-09-24.** The active iteration stopped by operator decision: no plan is being
advanced. Nothing in this file is in progress. Read it first when picking the project up.

Orientation for a reader with no session context: this repository is a personal archival CLI
for the Bilibili UP 未明子 (UID 23191782) — enumerate videos, harvest AI/CC subtitles first,
download audio only when a part has none, transcribe locally, and archive `srt`/`txt`/`md`/`raw`
with a resumable manifest. `AGENTS.md` holds the boundary; `CONCEPTS.md` holds the vocabulary.

---

## 1. Where everything is

| Ref | Tip | What it carries |
|---|---|---|
| `main` | `3b561ea` | The last released product state (`37b0acc`, 2026-09-21) plus the Qwen3-ASR boundary rebuild, the repo-level `.mstar` publication fix, and one harness-registration commit. **The editorial commands are not here.** |
| `iteration/iter-2026-09-transcript-editorial-stages` | `aa86ea1` | Phase-1 package + the merged Plan 1 (merge commit of PR #17). |
| `feat/20260923-transcript-proofread` | `55f846c` | The Plan-1 branch, merged via PR #17 and **kept** — this is where a fix rider commits. |

All three are pushed; the working tree is clean.

Subcommand count: **20 on `main`, 22 at the integration tip** — the two new commands are
`align-transcripts` and `verify-proofread`.

**The integration branch does not contain the ASR rebuild.** `main` and the integration branch
forked at `37b0acc` and both moved: 9 commits on the integration side, 17 on `main`. The boundary
commit `2548ca9` is *not* an ancestor of the integration tip, so that tip still carries
`DEFAULT_MODEL = "FunAudioLLM/Fun-ASR-Nano-2512"` while `main` carries `Qwen/Qwen3-ASR-1.7B-hf`
plus `Qwen/Qwen3-ForcedAligner-0.6B-hf`. `git diff --stat main iteration/…` reports 579 files and
`src/bili_asr/asr.py` alone at 653+/638−. **Merging the iteration into `main` as-is would revert
the engine boundary**; the close PR needs the rebuild merged back in first (or the iteration
rebased onto the current `main`).

## 2. The iteration that is parked

`iter-2026-09-transcript-editorial-stages` — make 校对 (proofread) and 精校 (reading edition)
**repeatable, verifiable pipeline stages**: the mechanical checks as commands, the editorial
judgement as a written protocol plus loadable agent skills (compass **D2**). Package:
`.mstar/iterations/iter-2026-09-transcript-editorial-stages/` (compass, direction lock, the
stage contract under `specs/`). Three plans, nine tasks, `M` scale.

| Plan | State | Evidence |
|---|---|---|
| `20260923-transcript-proofread` (3 tasks) | **Code complete and merged into the integration branch — with the plan's gates open** | T1 `ebbbac6` + rider `360098c` (reviewed, approved with minor); T2 `a9f411e` → `45222e9` → `e366c35`; T3 `55f846c`. PR [#17](https://github.com/SuperCatQR/bilibili-asr-archive/pull/17), merge `aa86ea1`: 6 commits, 8 files, +4034/−0. |
| `20260923-reading-edition` (4 tasks) | **Not started** (`Todo`) | — |
| `20260923-editorial-skills` (2 tasks) | **Not started** (`Todo`) | — |

## 3. Open gates — close these, or waive them on the record, before the iteration can close

PR #17 was merged **with the gates open**, disclosed in the PR comment and the merge-commit
body. None of the following has been done.

1. **Task 2's SDD review returned `Changes requested`** (artifact:
   `.mstar/sdd/20260923-transcript-proofread/task-2-review.md`). Its **Major Finding 1**:
   `check_marker_record_parity` (`bilibili-asr-archive/src/bili_asr/services/editorial_verify.py`,
   the function body around `:497-517`) compares mark **occurrences** against marked **rows** and
   locates the surplus as a **tail slice**, so the line it prints names the document's *last* body
   mark — on both real corpus firings a correctly paired site — and deleting one mark makes the
   refusal go silent while real mispairings stay live. The requested fix is to pair by the
   `[hh:mm:ss]` **stamp**, not by count and tail index, plus one test that pairs a site with its
   stamp. Minimal repro: three body marks at `00:00:01/00:00:03/00:00:05` with marked rows at
   `00:00:03/00:00:05` reports `:3`, while the unpaired site is body index 1.
2. **Four minors ride the same rider**: the demanded purity test was never written; a
   `CandidateFacts` off-by-one; two stale claims about an unreachable 20 000-char cap; a
   one-route-only token that silently disables the vacuity advisory.
3. **Task 3's SDD review has not run.**
4. **Plan QC tri-review and the QA gate (`mandatory` / `targeted`) have not run.**
5. **Residual `R2` stays blocked on Finding 1**: do not use `verify-proofread` to adjudicate the
   two marker-parity candidates until the fix lands.

## 4. Resume — the first four steps

```bash
# 1. read the state, then work where the code is
git -C <repo> fetch origin
git -C <repo> log --oneline -3 origin/iteration/iter-2026-09-transcript-editorial-stages

# 2. the fix rider commits on the kept feature branch (worktree .worktrees/20260923-transcript-proofread)
git -C <repo> worktree list

# 3. from that worktree: the invocation matters — the repo venv is an editable install of the
#    PRIMARY checkout, so pin PYTHONPATH or the suite grades the wrong tree
PYTHONPATH=$PWD/src <repo>/bilibili-asr-archive/.venv/bin/python -m pytest -q

# 4. the corpus-gated half needs the measurement corpus mounted (see §5)
```

Then: fix Finding 1 and the four minors → re-run the Task 2 review → review Task 3 → run the plan
QC tri-review and the QA gate → only then does the iteration-close PR
(`iteration/iter-2026-09-transcript-editorial-stages` → `main`) become the honest next artifact.

## 5. Evidence you do not have to re-measure

| Measurement | Result |
|---|---|
| Full suite at `55f846c` (this machine, 2026-09-24) | **1875 passed / 5 skipped / 5 errors** in 107 s |
| The 5 errors | `tests/test_cli_help.py` `installed_*` — they need `uv` to provision an isolated venv, and `uv` is absent here. Pre-existing, not product failures |
| Editorial suites with the corpus mounted | **94 passed / 0 skipped** — the six-item replay really runs against `/mnt/123pan/bili-asr-e2e` (sha256-pinned; the corpus is path-referenced by design and never copied into the repo) |
| The merged integration tip, smoke-tested | 22 subcommands; the three editorial suites **94 passed** |
| Fails-before, recorded per task | T2c `11 failed, 45 passed` (all `invalid choice: 'verify-proofread'`); T3 `17 failed, 7 passed` (`invalid choice: 'align-transcripts'` + the missing document) |

Without the corpus mounted the editorial cases **skip** rather than fail — that is the accepted
non-hermeticity of compass **D12**, and it means CI cannot exercise criterion 4.

## 6. Residuals registered by the parked iteration

In `.mstar/projects/_default/residuals.json` → `entries["iter-2026-09-transcript-editorial-stages"]`:

| id | severity | decision | what it is |
|---|---|---|---|
| `R1` | high | defer | three corpus sites where the two routes contest a hotword token and the record does not cover the disagreement — corpus-side adjudication |
| `R2` | medium | defer | two candidates carry more body marks than mark-bearing rows; **blocked on Finding 1** |
| `R3` | low | defer | the alignment's midpoint-comparison left endpoint is unpinned, so a mutation survives the suite |
| `R4` | medium | accepted | the cross-seat basename contract — closed by its test |

Next iteration's first row (already registered, high): `20260922-proofread-wave · R1` — the ASR
hotword list is itself an insertion source (target: `src/bili_asr/asr.py` and the hotword
measurement family).

## 7. What was deliberately not done

- No fix rider, no Task 3 review, no QC tri-review, no QA gate, no iteration close.
- **No `iteration/* → main` PR.** `main` therefore does not carry the two new commands.
- Plans 2 and 3 untouched.
- No `{KNOWLEDGE_DIR}` promotion (the iteration's compound round never ran).
- No file deletion or rewrite anywhere: the merged history, the kept branch, the SDD records and
  the scratch evidence all stay as they were.

## 8. What this park does and does not preserve

- **Preserved in git (travels with a clone):** this file, the product code on the three refs
  above, `.mstar/AGENTS.md`, `.mstar/knowledge/**`, `.mstar/specs/**` — the harness's declared
  clone-handoff surface.
- **Machine-local (does not travel):** the rest of `.mstar/**` — the iteration package, the
  sealed plans, the SDD records, the workflow snapshot, the register and its target directory.
  `.mstar/status.json` was the one file in this set that had been force-added to the index against
  the `.mstar/**` ignore rule, which made a checkout able to hold a live registry row whose
  `workflows/` document never arrived (`20260922-target-host-reconciliation · R1`). It was removed
  from the index on 2026-09-25, so the registry is now entirely local and that contradiction is
  gone; the register row itself still awaits its own closure.
- **Offline copy:** every ref can be packed into one file with
  `git bundle create <file> --all` (run from the repository root).
