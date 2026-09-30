# HANDOFF — bilibili-asr-archive

**Rewritten 2026-09-29.** This page opened with "Parked 2026-09-24 … Nothing in this file is in
progress. Read it first when picking the project up." That was true when it was written and is
false now: **four iterations have shipped since the park, and a fifth is running.** The parked
lifecycle itself has *not* moved — it is still parked, with the same gates open — so the numbered
sections below remain authoritative **for that work**. What changed is that they are no longer a
description of the project.

| Position as of 2026-09-29 | |
|---|---|
| `main` | **`371693b`** (2026-09-28) — **30 commits and 7 landed changes (4 of them two-parent merges; the rest squash landings)** past the park's reading (`f326398`) |
| Active iteration | **`iter-2026-09-harness-hygiene`** — `running`, `phase-2-execute` |
| Parked lifecycle | **`iter-2026-09-transcript-editorial-stages`** — still parked, gates still open (§2, §3). Its branch refs were **retired 2026-09-30** — fetch `refs/pull/17/head` before resuming (*Ref retirement* in §1) |
| Where to start | the **How to resume** section directly below |

**Shipped since the park.** Each `ended_at` is read from that iteration's own
`{HARNESS_DIR}/workflows/<id>/snapshot.json`; PR links are
`https://github.com/SuperCatQR/bilibili-asr-archive/pull/<n>`:

| Iteration | Lifecycle | Landed on `main` |
|---|---|---|
| `iter-2026-09-qwen3-asr-closeout` | `completed`, ended 2026-09-26 | PR #18 `638fb2d`; close `84e9767` |
| `iter-2026-09-coverage-truth` | `completed`, ended 2026-09-27 | PR #21 `2696711` |
| `iter-2026-09-metadata-audio-layout` | `completed`, ended 2026-09-27 | PR #21 `2696711`, then PR #25 `cefed49` |
| `iter-2026-09-ops-readiness` | `completed`, ended 2026-09-28 | PR #24 `662d9ca` |

Two lifecycle dates disagree and are recorded rather than smoothed over:
`iter-2026-09-metadata-audio-layout`'s snapshot has top-level `ended_at` 2026-09-27 while its
`metadata.closed_at` and its `{ITERATION_DIR}/README.md` row both say 2026-09-28. And
`iter-2026-09-coverage-truth` still carries `phase: phase-2-execute` although `status` is
`completed`: its PR #21 merge was performed out-of-band by the operator on 2026-09-27 (its own
snapshot notes say so, and `close_reason` records the merge as verified MERGED
2026-09-27T13:12:17Z), and the close itself was only written into the register on 2026-09-28 by
`139d6f9` (`chore(iteration): close iter-2026-09-coverage-truth and index ops-readiness`), which
never advanced the phase to `phase-6-post-merge-close`.

**Why the parked sections are still here.** Three things on this page are live rather than
historical, and deleting the page would lose them:

- **The editorial-stages lifecycle is genuinely still parked.** Its ref is still `aa86ea1`, still
  not merged into `main` (`git merge-base --is-ancestor aa86ea1 main` fails), and the two editorial
  subcommands are still absent from `main`. §2 and §3 describe real open work, and
  `{ITERATION_DIR}/README.md:26` points a reader here for the deleted package's recovery path.
- **§9 is the authoritative record of the 2026-09-25 deletion** — the only description of paths
  that no longer exist. It is deliberately unchanged; a dated pointer to a second, tracked copy of
  its archive is in **How to resume**.
- **§4's recovery steps and §6's residual table** are still the operator's reference for the parked
  work.

Orientation for a reader with no session context: this repository is a personal archival CLI
for the Bilibili UP 未明子 (UID 23191782) — enumerate videos, harvest AI/CC subtitles first,
download audio only when a part has none, transcribe locally, and archive `srt`/`txt`/`md`/`raw`
with a resumable manifest. `AGENTS.md` holds the boundary; `CONCEPTS.md` holds the vocabulary.

---

## How to resume

*Added 2026-09-29. The parked work below is resumed through the harness, not by hand — the entry
points moved since this page was written.*

**Entry points.** The harness directory is the **control root**, `/root/workspace/bilibili-asr-archive/.mstar/`
— not the copy inside any worktree, whose `.mstar/` is a per-checkout snapshot and does not carry
the live registers.

- `/iteration-start` — start a new iteration
- `/iteration-drive` — drive the active one (no argument restores the current lifecycle)
- `/iteration-loop` — the autonomous Phase 1–6 form
- `.mstar/AGENTS.md` — path symbols and the published-vs-local boundary; read before writing
  anything under `.mstar/`

**Two `.tmp/` paths are protected evidence — do not "clean" them.** Both are gitignored, both look
like scratch, and neither is litter. Deleting either is unrecoverable:

| Path | Why it is kept |
|---|---|
| `.tmp/deletion-records/` | The working copy of the 2026-09-25 deletion archive (§9). **A second, tracked copy landed 2026-09-29 (`05df363`) at `bilibili-asr-archive/docs/archive/deletion-records-20260925/`** (verified: directory exists, 3 files tracked, both `cmp`-identical to these). `harness-editorial-stages-deleted-20260925.tar.gz` 147 218 B, sha256 `d212a8b712fd25a7b17b9f6710720cec119bf4ed72934812221ec02ba196394e`; `pre-delete-report-20260925-harness-editorial-stages.txt` 71 489 B, sha256 `9d394651b4adb62e3e06648e154093b4de7a8c669007c7f0581f7a3f40dec413` |
| `.tmp/live-snapshot-backup.json` | A pre-correction backup of `iter-2026-09-text-and-ledger-precision` — an input to the harness-state correction, not a leftover |

**The deletion archive gains a second, tracked home (compass D12, ruled 2026-09-28).** The ruling
is that both files are published into Git at
`bilibili-asr-archive/docs/archive/deletion-records-20260925/`, alongside a tracked `README.md`
recording their provenance, and that `.tmp/deletion-records/` is retained as the working original.
**§9 below remains the record of the deletion** and is deliberately unchanged; what the publication
changes is that the bytes no longer exist on one machine only. *As of 2026-09-29 that directory was
not yet on disk or on any ref* — the task that writes it is `20260928-workspace-reclamation` Task 2,
and it had not landed when this page was rewritten: `git log --all --oneline --
bilibili-asr-archive/docs/archive/deletion-records-20260925/` returned nothing and `.tmp/deletion-records/`  (this check was written before Task 2 landed; re-run it today and it reports the tracked copy as present)
was still the sole copy. So treat the publication as **landed (see the check below)**: check before relying on
it, and verify with:

```bash
ls bilibili-asr-archive/docs/archive/deletion-records-20260925/     # empty/absent → not landed yet
cmp .tmp/deletion-records/<f> bilibili-asr-archive/docs/archive/deletion-records-20260925/<f>
sha256sum bilibili-asr-archive/docs/archive/deletion-records-20260925/*
git ls-files bilibili-asr-archive/docs/archive/deletion-records-20260925/
```

**The 123pan mount §9 names is retired — noted here, not in §9.** Measured 2026-09-29:
`mountpoint /mnt/123pan` → *is not a mountpoint*; `systemctl is-enabled rclone-123pan` → `disabled`;
no `bili-asr-e2e` tree exists under `/srv` or under the former mount. The archive root moved to the
local `/srv/bili-asr-archive` in `ab391a2` (`chore(storage): retire the 123pan mount and move the
archive root to /srv`, 2026-09-28). §9's `bili-asr-e2e/deletion-records/` line is left exactly as
written because it records **where the archive was delivered**, which is a historical fact; the
correct treatment of the retired mount is this dated note.

**One open harness observation, recorded by plan A.** In
`.mstar/projects/_default/roadmap.md` § **P3.5** (registered 2026-09-28, owner PM): **the engine's
fallback lifecycle selection is mtime-sensitive when the root register is legitimately empty.**
`status.json`'s `workflows[]` is cleared at terminal state per contract, which is correct — but
selection then degrades to "the most recently modified snapshot", so the same session can resolve a
different historical lifecycle at different times and report a different workflow. It affects
session-start context, not documents. Until the engine exposes an explicit selection, **do not
treat the workflow name reported at session start as evidence of the current iteration.** (That
path is machine-local, not under git.)

---

## 1. Where everything is

| Ref | Tip | What it carries |
|---|---|---|
| `main` | `371693b` | The last released product state (`37b0acc`, 2026-09-21), the Qwen3-ASR boundary rebuild, the repo-level `.mstar` publication fix, one harness-registration commit, the 2026-09-25 structure tidy-up, and then **everything the four iterations below shipped**: the Qwen3-ASR closeout, the archive.db queue layer and evidence dashboard, metadata enrichment plus `derive-audio-inventory`, the queue-SSOT cutover at the CLI with `proofread`/`search`/`search-index`, and shape A's one-directory-per-work bundle layout. Note that **shape A is not one of the four iterations below**: it is a separate landing (`d743043`, PR #26) whose L1 decision post-dates the iteration it merged under, and its residual group `20260928-layout-shape-a` carries an **open `medium` residual (`L-R2`, no arm's-length L2 verdict)** — it has no row in the table below and is not covered by any lifecycle there (QA-C2). **The editorial commands are still not here.** |
| ~~`iteration/iter-2026-09-transcript-editorial-stages`~~ | ~~`aa86ea1`~~ | The merged Plan 1 (merge commit of PR #17) plus the Phase-1 package as it stood at the lock — the pre-deletion snapshot of the files §9 removed from disk. **Retired 2026-09-30** — see *Ref retirement* below. |
| ~~`feat/20260923-transcript-proofread`~~ | ~~`55f846c`~~ | The Plan-1 branch, merged via PR #17 and **kept** — this is where a fix rider commits. **Retired 2026-09-30** — see *Ref retirement* below. |

*Corrected 2026-09-30.* This paragraph read "All three are pushed through the tips above
(**corrected 2026-09-29**). Verify with `git branch -a` — all three have an `origin/<ref>`".
**Only `main` still has a live branch ref.** The two parked refs were retired on 2026-09-30 with
operator authorisation (*Ref retirement* below); their commits are still reachable through GitHub's
PR refs. Verify what remains with `git branch -a`, and read tips one ref at a time —
`git rev-parse --short origin/main` — `--short` with several revisions exits 128 on this host
(2026-09-29).

Tips are **observations, not a live view**: each is the last commit that ref was at when its row
was last written. A commit made afterwards does not make the rest of this page wrong.
`git rev-parse --short <ref>` is authoritative. `main`'s row read `f326398` — the structure tidy-up
that rewrote this table — from 2026-09-25 until it was corrected to `371693b` on 2026-09-29
(`git rev-parse --short main`); `0c47504` and `9d530cd` revised this page in between, and §9 below
was written on the first of those dates. The two parked rows are unchanged and still name
`aa86ea1` and `55f846c`. Read each row as the date it was written, not as the current tip.

Subcommand count: **24 on `main`, 22 at the integration tip.** *Corrected 2026-09-29* — this line
read "20 on `main`, 22 at the integration tip", which was right when written and is now wrong on
the `main` side only. The integration figure is still correct: `aa86ea1` really does carry 22.
The two commands the parked iteration adds are `align-transcripts` and `verify-proofread`; the four
`main` gained since are `derive-audio-inventory`, `proofread`, `proofread-merge` and `search-index`.
Re-derive both sides from the source, per ref:

```bash
git show main:bilibili-asr-archive/src/bili_asr/cli.py    | grep -c 'add_parser('   # 24
git show aa86ea1:bilibili-asr-archive/src/bili_asr/cli.py | grep -c 'add_parser('   # 22
```

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

*Counts refreshed 2026-09-29.* Still 9 commits on the integration side, but **48 on `main`** — the
"18" above was the 2026-09-25 reading (`git rev-list --count 37b0acc..aa86ea1` → 9,
`git rev-list --count 37b0acc..main` → 48). `git diff --stat main aa86ea1` now reports **678 files,
259 613 insertions(+), 34 688 deletions(−)**. The ratio is the point rather than either number: the
integration side has not moved at all while `main` took 30 more commits, so the rescue this
paragraph describes has grown, not shrunk.

### Ref retirement — 2026-09-30

Three refs were deleted on **2026-09-30** on explicit operator authorisation. **No content was
lost**: every commit they held is still reachable from GitHub's PR refs, which outlive the branch
refs (verified on this host: a branch deleted on 2026-09-30 left its `refs/pull/<n>/head` serving
the same OID, and a `fetch` of it succeeded from a clean clone).

| Ref retired | Was | Recover with |
|---|---|---|
| `iteration/iter-2026-09-metadata-audio-layout` (local + `origin`) | `d28825b` — PR #25's branch, squash-merged into `main` as `cefed49`; the 20 pre-squash commits were held only by this ref | `git fetch origin refs/pull/25/head:refs/heads/<any-name>` → `d28825b` (identical OID) |
| `feat/20260923-transcript-proofread` (local + `origin`) | `55f846c` — Plan 1's branch, merged via PR #17 | `git fetch origin refs/pull/17/head:refs/heads/<any-name>` → `55f846c` (identical OID) |
| `iteration/iter-2026-09-transcript-editorial-stages` (local + `origin`) | `aa86ea1` — PR #17's merge commit | Same `refs/pull/17/head` fetch; `aa86ea1` is `55f846c` plus one merge event and **carries no content of its own** (its tree is byte-identical to `55f846c`). Re-creatable from `89a9ebb` + `55f846c` if the object is ever needed. |

**What the retirement does *not* mean.** The parked iteration is **still parked and its gates are
still open** (§2, §3) — retiring the refs removes a branch name, not the work. The six editorial
source files (~3 400 lines: `services/editorial_alignment.py`, `services/editorial_verify.py`,
three test modules, `docs/editorial-stages.md`) exist on **no `main` commit and in no part of the
deletion archive**; `refs/pull/17/head` is now their only home. A resuming agent must fetch that
ref **before** reading any of them — the body of §2 and §3, and
`{PLAN_DIR}/20260928-proofread-pipeline.md` Step 1, all assume the branch is present.

**Why these refs and why this way.** The sanctioned planner
(`mstar worktree cleanup --all-workflows --remote`) **refuses** all three —
`cleanup.refuse.foreign-branch` on the editorial pair and
`cleanup.refuse.unmerged` on `origin/iteration/iter-2026-09-metadata-audio-layout`, because no
snapshot row claims ownership of them (a historical metadata gap, not evidence of abandonment) and
the squash landing is invisible to ancestor tests. The retirement is therefore an **operator
decision outside the engine's sanctioned path**, recorded as such here rather than presented as a
cleanup verdict. Deletion used expected-OID compare-and-delete
(`git push --force-with-lease=refs/heads/<b>:<observed-oid> origin :refs/heads/<b>`), never a bare
delete. **Three tracked records still say "Do not touch" / "operator-owned" about exactly these
refs** — `{PLAN_DIR}/20260928-workspace-reclamation.md` Task 1 ("`feat/20260923-transcript-proofread`
… `iteration/iter-2026-09-transcript-editorial-stages` … parked, operator-owned"),
`{PLAN_DIR}/20260925-repo-cleanup.md` ("留（3 条）… parked 迭代的续做入口"), and the
`iter-2026-09-harness-hygiene` compass Non-Goals ("Deleting the parked
`iter-2026-09-transcript-editorial-stages` refs (operator-owned; `HANDOFF.md` §9 governs them)").
Those are **dated records of the rulings that then applied** and are deliberately left
byte-unchanged — the reclamation plan is itself an argument for this treatment, since
`iter-2026-09-harness-hygiene` left §9 byte-identical and put its dated pointer outside it. This
section is that pointer.

## 2. The iteration that is parked

`iter-2026-09-transcript-editorial-stages` — make 校对 (proofread) and 精校 (reading edition)
**repeatable, verifiable pipeline stages**: the mechanical checks as commands, the editorial
judgement as a written protocol plus loadable agent skills (compass **D2**). Package:
`.mstar/iterations/iter-2026-09-transcript-editorial-stages/` (compass, direction lock, the
stage contract under `specs/`) — **deleted from disk 2026-09-25** (§9); the two branch refs that
carried it were **retired 2026-09-30** (*Ref retirement* in §1), so read it out of `refs/pull/17/head`
or the deletion archive rather than from a checked-out branch. Three plans, nine tasks,
`M` scale.

| Plan | State | Evidence |
|---|---|---|
| `20260923-transcript-proofread` (3 tasks) | **Code complete and merged into the integration branch — with the plan's gates open** | T1 `ebbbbac6` + rider `360098c` (reviewed, approved with minor); T2 `a9f411e` → `45222e9` → `e366c35`; T3 `55f846c`. PR [#17](https://github.com/SuperCatQR/bilibili-asr-archive/pull/17), merge `aa86ea1`: 6 commits, 8 files, +4034/−0. |
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
# 1. read the state, then work where the code is.
#    CORRECTED 2026-09-30 — the branch refs were retired: the old
#    `git log --oneline -3 origin/iteration/iter-2026-09-transcript-editorial-stages`
#    now fails with "unknown revision". Fetch the PR ref first; it is the only home
#    of the editorial code (see *Ref retirement* in §1).
git -C <repo> fetch origin
git -C <repo> fetch origin refs/pull/17/head:refs/heads/editorial-stages
git -C <repo> log --oneline -3 editorial-stages

# 2. the fix rider commits on that branch. The worktree named here
#    (.worktrees/20260923-transcript-proofread) was reclaimed before 2026-09-30 and no
#    longer exists, so re-create one from the fetched ref — Base for it is the fetched
#    branch, not `main`.
git -C <repo> worktree list
git -C <repo> worktree add -b fix/<name> .worktrees/<name> editorial-stages

# 3. from that worktree: the invocation matters — the repo venv is an editable install of the
#    PRIMARY checkout, so pin PYTHONPATH or the suite grades the wrong tree
PYTHONPATH=$PWD/src <repo>/bilibili-asr-archive/.venv/bin/python -m pytest -q

# 4. the corpus-gated half needs the measurement corpus mounted (see §5)
```

Then: fix Finding 1 and the four minors → re-run the Task 2 review → review Task 3 → run the plan
QC tri-review and the QA gate → only then does the iteration-close PR become the honest next
artifact. *Corrected 2026-09-30:* the PR target is still `main`, but its head is no longer the
retired `iteration/iter-2026-09-transcript-editorial-stages` branch — open it from whatever branch
step 1 fetched or re-created.

## 5. Evidence you do not have to re-measure

| Measurement | Result |
|---|---|
| Full suite at `55f846c` (this machine, 2026-09-24) | **1875 passed / 5 skipped / 5 errors** in 107 s |
| The 5 errors | `tests/test_cli_help.py` `installed_*` — they need `uv` to provision an isolated venv, and `uv` is absent here. Pre-existing, not product failures |
| Editorial suites with the corpus mounted | **94 passed / 0 skipped** — the six-item replay really ran against `/mnt/123pan/bili-asr-e2e` — **that path exists nowhere on the host as of 2026-09-29** (the 123pan mount is retired, see the note above); the measurement stands, the route to reproduce it does not (sha256-pinned; the corpus is path-referenced by design and never copied into the repo) |
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

*Superseded 2026-09-29.* That row is no longer the next one — **`20260922-proofread-wave · R1` was
closed on 2026-09-27** by `iter-2026-09-qwen3-asr-closeout`, whose two-arm measurement on the frozen
six-item corpus landed the evidence, plus the guard layer whose content reached `main` in `662d9ca` (its own commit `b6daab5` is reachable from no ref — the change landed by squash, so cite the squash; QA-C6). Read it in
`.mstar/projects/_default/residuals.json` → `entries["20260922-proofread-wave"][0]`
(`lifecycle: resolved`, `closed_at: 2026-09-27`, `closure_note` naming `b6daab5`; the guard half belongs to plan `20260928-hotword-injection-governance` under **`iter-2026-09-ops-readiness`**, not the closeout iteration — QA-C6). The paragraph is
left as written because it is the park's record of what was believed then; do not treat it as the
next action. `R2` in that group is the one still open.

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
  plans, and the workflow snapshots. **Caveat (QA-C5): 11 `.mstar/**` paths are still tracked at
  `main` — two `{PLAN_DIR}` plans and the iteration delivery records — so "does not travel" is the
  intended boundary, not the current one. Treat it as a debt list, not a fact.** The sealed
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
  **As of 2026-09-30 the two branches are retired** (see *Ref retirement* in §1): reach these
  commits through `refs/pull/17/head` (`55f846c`), which carries `89a9ebb` and `f33ee02` as
  ancestors, or through whatever local ref the §4 step 1 fetch created.
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

**What this deletion does *not* mean:** the merged Plan-1 code is unaffected. Deleting the
*harness records* does not un-park, un-merge or abandon the iteration — it removes the local paper
trail. The five open gates in §3 are still the honest next work, and the substance of residual
`R2`'s blocked-on-Finding-1 note is still true — but the entry itself is no longer registered: it
was one of the four removed from `residuals.json`, and its full text now lives only in the archive
report's final section, which keeps all four entries verbatim for re-registration if wanted; every
one of them carries `source_plan: 20260923-transcript-proofread`, a plan that is still on disk and
out of this deletion's scope. What is gone is the local registry rows that once made those records
discoverable from the machine.

*Corrected 2026-09-30.* This section's opening sentence read "the branch
`iteration/iter-2026-09-transcript-editorial-stages` and the kept feature branch still exist
locally and on `origin`". **They no longer do** — both were retired on 2026-09-30 (*Ref
retirement* in §1). Everything else in this section is a dated record of the 2026-09-25 deletion
and is left as written; the "Working-tree state in the two kept worktrees" note above is now
**moot**, because those worktrees were reclaimed before 2026-09-30.
