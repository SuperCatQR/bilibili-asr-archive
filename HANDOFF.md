# HANDOFF — bilibili-asr-archive

**Parked 2026-09-24; the parked iteration's harness package was deleted 2026-09-25.** The active
iteration stopped by operator decision: no plan is being advanced. On 2026-09-25 the operator also
had that iteration's harness package, its workflow snapshot and its two un-started plans deleted,
along with the registry rows that pointed at them — **§9** is the authoritative list of what went
and what remains. Nothing in this file is in progress. Read it first when picking the project up.

Orientation for a reader with no session context: this repository is a personal archival CLI
for the Bilibili UP 未明子 (UID 23191782) — enumerate videos, harvest AI/CC subtitles first,
download audio only when a part has none, transcribe locally, and archive `srt`/`txt`/`md`/`raw`
with a resumable manifest. `AGENTS.md` holds the boundary; `CONCEPTS.md` holds the vocabulary.

---

## 1. Where everything is

| Ref | Tip | What it carries |
|---|---|---|
| `main` | `f326398` | The last released product state (`37b0acc`, 2026-09-21) plus the Qwen3-ASR boundary rebuild, the repo-level `.mstar` publication fix, one harness-registration commit, and the 2026-09-25 structure tidy-up. **The editorial commands are not here.** |
| `iteration/iter-2026-09-transcript-editorial-stages` | `aa86ea1` | The merged Plan 1 (merge commit of PR #17) plus the Phase-1 package as it stood at the lock — the pre-deletion snapshot of the files §9 removed from disk. |
| `feat/20260923-transcript-proofread` | `55f846c` | The Plan-1 branch, merged via PR #17 and **kept** — this is where a fix rider commits. |

All three are pushed through the tips above.

Tips are **observations, not a live view**: each is the last commit that ref was at when this
table was last written (2026-09-25). A commit made afterwards does not make the rest of this
page wrong. `git rev-parse --short <ref>` is authoritative. `main`'s row names `f326398` — the
structure tidy-up that rewrote this table — and `0c47504` revised this page again; §9 below was
written on the same date. Read each row as the date it was written, not as the current tip.

Subcommand count: **20 on `main`, 22 at the integration tip** — the two new commands are
`align-transcripts` and `verify-proofread`.

**The integration branch does not contain the ASR rebuild.** `main` and the integration branch
forked at `37b0acc` and both moved: 9 commits on the integration side, 18 on `main`. The boundary
commit `2548ca9` is *not* an ancestor of the integration tip, so that tip still carries
`DEFAULT_MODEL = "FunAudioLLM/Fun-ASR-Nano-2512"` while `main` carries `Qwen/Qwen3-ASR-1.7B-hf`
plus `Qwen/Qwen3-ForcedAligner-0.6B-hf`. At the 2026-09-25 reading,
`git diff --stat main iteration/…` reported 586 files and `src/bili_asr/asr.py` alone at
653+/638− — the counts move with every commit on either side, so read them as a magnitude
rather than a contract. **Merging the iteration into `main` as-is would revert the engine
boundary**; the close PR needs the rebuild merged back in first (or the iteration rebased onto
the current `main`).

## 2. The iteration that is parked

`iter-2026-09-transcript-editorial-stages` — make 校对 (proofread) and 精校 (reading edition)
**repeatable, verifiable pipeline stages**: the mechanical checks as commands, the editorial
judgement as a written protocol plus loadable agent skills (compass **D2**). Package:
`.mstar/iterations/iter-2026-09-transcript-editorial-stages/` (compass, direction lock, the
stage contract under `specs/`) — **deleted from disk 2026-09-25** (§9). Three plans, nine tasks,
`M` scale.

| Plan | State | Evidence |
|---|---|---|
| `20260923-transcript-proofread` (3 tasks) | **Code complete and merged into the integration branch — with the plan's gates open** | T1 `ebbbac6` + rider `360098c` (reviewed, approved with minor); T2 `a9f411e` → `45222e9` → `e366c35`; T3 `55f846c`. PR [#17](https://github.com/SuperCatQR/bilibili-asr-archive/pull/17), merge `aa86ea1`: 6 commits, 8 files, +4034/−0. |
| `20260923-reading-edition` (4 tasks) | **Deleted 2026-09-25** — never started, never committed | — (existed on disk only; preserved in the deletion archive, §9) |
| `20260923-editorial-skills` (2 tasks) | **Deleted 2026-09-25** — never started, never committed | — (existed on disk only; preserved in the deletion archive, §9) |

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

Registered under `.mstar/projects/_default/residuals.json` →
`entries["iter-2026-09-transcript-editorial-stages"]`. That group was **removed on 2026-09-25**
(§9) — its full text is preserved in the deletion archive. As registered at the park:

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
- Plans 2 and 3 untouched by this park; both were deleted, still unstarted, on 2026-09-25 (§9).
- No `{KNOWLEDGE_DIR}` promotion (the iteration's compound round never ran).
- No file deletion or rewrite anywhere *as part of this park*: the merged history, the kept
  branch, the SDD records and the scratch evidence all stayed as they were. (A separate operator
  decision on 2026-09-25 did delete harness records — see §9.)

## 8. What this park does and does not preserve

- **Preserved in git (travels with a clone):** this file, the product code on the three refs
  above, `.mstar/AGENTS.md`, `.mstar/knowledge/**`, `.mstar/specs/**` — the harness's declared
  clone-handoff surface.
- **Machine-local (does not travel):** the rest of `.mstar/**` — the SDD records, the sealed
  plans, the register and its target directory. (Some of what this bullet described — the parked
  iteration's package and workflow snapshot, and the two un-started plans — was deleted on
  2026-09-25; §9 is authoritative.)
  `.mstar/status.json` was the one file in this set that had been force-added to the index against
  the `.mstar/**` ignore rule, which made a checkout able to hold a live registry row whose
  `workflows/` document never arrived (`20260922-target-host-reconciliation · R1`). It was removed
  from the index on 2026-09-25, so the registry is now entirely local and that contradiction is
  gone; the register row itself still awaits its own closure.
- **Offline copy:** every ref can be packed into one file with
  `git bundle create <file> --all` (run from the repository root).

## 9. The 2026-09-25 deletion — what went, what stayed, what is only in the archive

On **2026-09-25**, after this park was written, the operator had the parked iteration's harness
records deleted. This section is the authority for that; the earlier sections describe the state
*before* it, and every claim above that conflicts with this one is superseded. **No product code,
no git ref and no branch changed** — every removed path was a harness record tree (`.mstar/**`, plus
the same layout inside two gitignored scratch fixtures) and nothing else.

**Deleted from disk (8 roots, 24 files, 433 316 bytes):**

| Root | Files |
|---|---|
| `.mstar/iterations/iter-2026-09-transcript-editorial-stages/` | 4 (compass, direction lock, package README, `specs/editorial-stage-contract.md`) |
| `.mstar/workflows/iter-2026-09-transcript-editorial-stages/` | 2 (`snapshot.json`, `agent-flow.jsonl`) |
| `.mstar/plans/20260923-reading-edition.md` | 1 |
| `.mstar/plans/20260923-editorial-skills.md` | 1 |
| both worktrees' `.mstar/iterations/<id>/` (2 copies) | 4 each |
| both `.test-tmp/t2review/{base,onlytest}/` fixtures' `.mstar/iterations/<id>/` (2 copies) | 4 each |

Also removed, so nothing points at a file that is gone: the workflow registry row in all three
live `status.json` copies (`.mstar/status.json` and both worktrees'), and the four residual entries
`entries["iter-2026-09-transcript-editorial-stages"]` (R1 high, R2, R3, R4). `20260923-transcript-proofread`
— the one plan whose code is merged — **was not deleted and is not in scope**; its file, its SDD
records and its open gates (§3) all still stand.
(Two gitignored T2-review scratch fixtures —
`.worktrees/20260923-transcript-proofread/bilibili-asr-archive/.test-tmp/t2review/{base,onlytest}/.mstar/status.json`
— still carry that registry row. They are gitignored scratch fixtures frozen at the review-time
state, left standing deliberately rather than rewritten; the `.tmp/**` dispatch records and the
gitignored `.mstar/plans/**` and `.mstar/sdd/**` pages keep their own historical references for
the same reason.)

Two **tracked** documents on the kept branches cite the package path as well —
`bilibili-asr-archive/docs/editorial-stages.md:7` and `.mstar/specs/asr-archive-cli.md:58`. Those
citations are left unrewritten for the same reason as the fixture above: they are what the branch
said when it was written, and the caller resolves them through git rather than through the
checkout — `git show <tip>:.mstar/iterations/<id>/specs/editorial-stage-contract.md` works at either
tip even though the same path is absent from those working trees (see the working-tree note above).

**Archive — the only complete copy.** Written to the 123pan delivery side under
`bili-asr-e2e/deletion-records/` (the convention that directory already used):

- `pre-delete-report-20260925-harness-editorial-stages.txt` — 71 489 B,
  sha256 `9d394651b4adb62e3e06648e154093b4de7a8c669007c7f0581f7a3f40dec413`. Carries the
  per-root listing, a sha256 for every file, the deletion-set vs kept-set comparison, and the full
  text of the removed residual entries. (Its own deletion-set line first read 292 641 B, which
  contradicted the 433 316 B overview; the corrected copy was re-uploaded and read back.)
- `harness-editorial-stages-deleted-20260925.tar.gz` — 147 218 B, 24 files, sha256
  `d212a8b712fd25a7b17b9f6710720cec119bf4ed72934812221ec02ba196394e`. A byte-exact copy of every
  deleted file. Verify with `sha256sum` against the hashes in the report.

Both files were re-read from the remote after upload and their hashes matched the local copies.

**Recovery, by kind:**

- **Iteration package (4 files)** — also in git: `f33ee02` (first lock), `89a9ebb` (re-lock after
  D18) and both kept branches. `git show 89a9ebb:.mstar/iterations/<id>/delivery-compass.md` works.
  **But the deleted `delivery-compass.md` was 55 232 B while every committed version is 47 394 B** —
  the on-disk file carried a delta that was never committed, and that delta exists **only** in the
  archive above.
- **`20260923-reading-edition.md` and `20260923-editorial-skills.md`** — *not* in git at all: no
  ref ever committed either file (checked with `git log --all` / `git cat-file -e` across every
  ref). The archive is their only copy.
- **`workflows/<id>/` (2 files)** — likewise not in git: the workflow snapshot and the agent-flow
  log were machine-local by design. Archive only.

**Working-tree state in the two kept worktrees — do not "clean" it.** Each worktree checkout shows
the package as four **unstaged** deletions plus a modified `.mstar/status.json`, because the files
were removed from disk without a commit. That is deliberate: the two branch tips must keep carrying
the package (§Recovery above). So in those worktrees do **not** `git add -A && git commit` (it would
drop the package off the branch that is the recovery path) and do **not** `git checkout -- .` or
`git stash` expecting a tidy tree (it would put the files back and make this section false). If you
want a clean `git status` there, the honest move is to leave the branch alone and accept the
working-tree delta, or to re-lock the iteration deliberately.

**What this deletion does *not* mean:** the branch `iteration/iter-2026-09-transcript-editorial-stages`
and the kept feature branch still exist locally and on `origin`, and the merged Plan-1 code is
unaffected. Deleting the *harness records* does not un-park, un-merge or abandon the iteration —
it removes the local paper trail. The five open gates in §3 are still the honest next work, and
the substance of residual `R2`'s blocked-on-Finding-1 note is still true — but the entry itself is
no longer registered: it was one of the four removed from `residuals.json`, and its full text now
lives only in the archive report's final section, which keeps all four entries verbatim for
re-registration if wanted; every one of them carries `source_plan: 20260923-transcript-proofread`,
a plan that is still on disk and out of this deletion's scope. What is gone is the local
registry rows that once made those records discoverable from the machine.
