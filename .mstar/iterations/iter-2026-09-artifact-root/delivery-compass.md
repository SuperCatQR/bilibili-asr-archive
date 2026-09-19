---
iteration_id: iter-2026-09-artifact-root
end_date: 2026-09-19
start_date: 2026-09-19
status: completed
iteration_base_branch: main
target_branch: main
plans: [20260919-artifact-root]
---

# Delivery Compass — iter-2026-09-artifact-root

**Feature (user request, 2026-09-19):** the location where the pipeline writes its **audio and products**
becomes configurable, so an operator can put them on `/mnt/123pan` while the repository, the working tree
and the project state stay where they are. Audio is to be **retained indefinitely**.

**Status: direction CONFIRMED by the user 2026-09-19 — the six decisions are recorded in §2 and the spec
is written against them. The compass locks at the end of Phase 1 (after the plan exists).**

## 1. What exists today (recon, read-only, 2026-09-19)

Everything lives under one `--archive-root` (`cli.py:28` `DEFAULT_ARCHIVE_ROOT = "archive"`), split into
two kinds of thing that this iteration must separate:

| Kind | Paths | Nature |
|---|---|---|
| **Products** | `{root}/audio/` (`audio.py:35`, `:202`), `{root}/transcripts/{srt,txt,md,raw}/` (`archive.py:466-471`), `{root}/subtitles/` | the outputs the user wants relocatable |
| **State** | `{root}/manifest/manifest.jsonl`, `{root}/archive.db` (`database.py:40`, opened below the root), `{root}/coordinator/` (attempts, locks) | a SQLite database, an fsync-per-append JSONL and lock files — see the placement hazard |

Three hard constraints make "just add a flag" wrong:

1. **`audio.py:187` asserts the audio directory IS `<archive_root>/audio`** — the location is pinned in code, not policy.
2. **Audio is confined to the archive root by an explicit safety invariant**: `path_policy.confined_audio_path`
   plus `coordinator.py:568` / `:617` raising `OSError("audio path outside archive")`, with descriptor-anchored
   opens (`path_policy.py:32-50`, `O_NOFOLLOW`) that deliberately refuse a symlinked `audio/`.
3. **Two subsystems assume the path shape**: `audio_budget.py:34` measures `root/audio`, and
   `audio_reclaim.py:16-36` builds its candidates as `audio/{stem}.{m4a,flac}`.

**Placement hazard the design must respect** (evidence from the closed plan's QC): `archive.db` is SQLite
opened `isolation_level="DEFERRED"` with no WAL, and the manifest appends with an fsync pair per row
(`manifest.py:186-220`). A FUSE/WebDAV mount cannot carry POSIX locks to the cloud, so **state must not be
relocated onto the network mount**; products may be.

## 2. Decision register (CONFIRMED by the user, 2026-09-19)

| # | Decision | **Decided** |
|---|---|---|
| **D1** | What becomes configurable | **One artifact root** covering audio + transcripts + subtitles. State (manifest, `archive.db`, coordinator) stays at the archive root. |
| **D2** | Mechanism and precedence | **CLI flag + environment variable, the flag wins.** Unset reproduces today's behaviour byte-for-byte. |
| **D3** | Naming | **`--artifact-root` / `BILI_ARTIFACT_ROOT`** (recommendation adopted by the PM; nothing is committed yet, so a rename is still free). Iteration slug `artifact-root`. |
| **D4** | The confinement invariant | **Re-base the guard onto the configured artifact root** — an artifact root outside the state root becomes legal, while the descriptor-anchored guarantees stay: each configured root opens with `O_NOFOLLOW`, no symlinked target directory is followed, and a path escaping its own root is still refused. |
| **D5** | Audio retention | **Promote to a first-class flag, retained by default.** `BILI_KEEP_AUDIO=1` stays honoured as the existing escape hatch. |
| **D6** | Migration | **None.** Unset = today's paths; an existing archive root keeps working, and legacy relative `audio_path` values in an existing manifest keep being honoured by every reader. |

## 3. Non-goals (proposed)

- No relocation of **state** (`manifest/`, `archive.db`, `coordinator/`) onto a network mount — the SQLite/lock
  hazard above.
- No change to the repository, the harness tree, worktrees or virtualenvs.
- No new storage schema, no second source of truth for audio state.
- No automatic cloud publication/sync: this iteration makes the **location** configurable; moving finished
  artifacts to the cloud is the operator's `rclone` step, not a pipeline responsibility.

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| `20260919-artifact-root` | Make the audio/product output location configurable (`--artifact-root`) | Done | `{PLAN_DIR}/20260919-artifact-root.md` — SDD, 4 tasks: T1 resolution core (S), T2 write path + retention (L), T3 readers (L), T4 CLI surface + docs (M); T1 → {T2, T3 parallel} → T4. Contract: `specs/artifact-root-contract.md` (15 sections, decisions D7–D19). `qa_gate: mandatory` / `targeted` — the confinement guard is the security surface. |

## Open Questions

**Q1 — RESOLVED by the user 2026-09-19: option (a).** Keep the cap semantics; the help text, the skip line and the docs must name `--max-audio-gb 0` for a retaining operator. No behaviour change; the cap stays fail-closed.

*(Original escalation, kept for the record.)* The confirmed decision D5 makes
audio retention the **default**, and the shipped default of `--max-audio-gb` is **10.0** on `pilot`/`run`/
`schedule`/`campaign` (`cli.py:124,247,281,329`). `would_exceed_budget` fail-closes (`audio_budget.py:72-90`),
so once retained audio passes 10 GiB the download stage skips **every** row (`coordinator.py:583-594`) and
`pilot` counts those as failed (`cli.py:2210-2222`) — i.e. the new default would brick a retaining operator's
downloads. Options: **(a)** keep the cap semantics and document that a retaining operator passes
`--max-audio-gb 0`, naming it in the help text and the skip line; **(b)** default the cap to 0 when retention is
on; **(c)** stop counting retained audio against the cap. Nothing else in the plan depends on Q1.

## 4. Verification sketch (to be firmed up in the spec)

- Unset root → byte-identical behaviour to today (the existing suites are the regression evidence).
- Configured root → audio and bundles land there; `coverage`, `verify`, `export`, `coverage --quality` and
  `status` report the same inventory as with the default layout.
- The confinement guard still refuses an out-of-root path **for the configured root** (the invariant is
  re-based, not dropped) and still refuses a symlinked target directory.
- Retention: with the retain policy, a row reaching `archived` leaves its audio in place.

---

## Naming note (naming rule applied)

The codebase already calls the outputs **artifacts** (`artifact_stem`, `coverage_report`'s
`artifact_present`), and calls the single current root the **archive root**. `artifact root` therefore reads
as "where the artifacts go, when that is not the archive root" — specific, consistent with existing
vocabulary, and it does not overload "output" (vague) or "cache" (wrong: these are durable products).
Alternatives considered: `--output-root` (vague about *what* output), `--products-root` (introduces a third
word for a concept that already has one), `--artifacts-dir` (dir implies single-level).

## 5. Why the split is the whole point (context the spec must carry)

The user's target is `/mnt/123pan` — a WebDAV FUSE mount. Products belong there; **state does not**:
`archive.db` is SQLite `isolation_level="DEFERRED"` with no WAL, and `manifest.py:186-220` fsyncs a pair per
append. FUSE cannot carry POSIX locks to the cloud, so relocating state would trade a correctness guarantee
for a path preference. D1's split is what makes the user's goal safe rather than merely possible.

The audio-retention decision (D5) also removes the usual reason to relocate state: nothing needs to be
pruned to reclaim space, because retained audio is a product the user wants kept.

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Direction confirmed by the user (D1–D6, Q1) | 2026-09-19 | done |
| Spec + plan written (544 + 690 lines; 15 sections, decisions D1–D19; 4 SDD tasks) | 2026-09-19 | done |
| Phase-1 lock published to the integration branch | 2026-09-19 | done (`cee0b94`) |
| Dev complete (all four tasks L2-clean; two needed a fix loop, one needed two) | 2026-09-19 | done (`60d8726`, `e048c91`, `5cbeb83`, `2ee3bb5`) |
| Plan QC tri-review + two fix waves | 2026-09-19 | done — 3/3 approve (`c72ce43`, `62a316d`) |
| QA gate (mandatory / targeted) | 2026-09-19 | done — approve with residuals; 600 passed / 0 failed, run by the seat |
| Iteration close | 2026-09-19 | this round |

## Roadmap Position

- **Current iteration — delivered 2026-09-19**: the products (audio, transcript bundles, raw subtitles) can be written
  outside the archive root via `--artifact-root`/`BILI_ARTIFACT_ROOT`, with the confinement guard re-based onto the
  configured root and audio retention promoted to a first-class flag that defaults to retain. State deliberately stays
  at the archive root. The user's goal — pointing the outputs at `/mnt/123pan` — is now reachable without moving the
  repository, the worktrees or the project state.
- **Next candidates** (each with owner and trigger so a reader with no access to this session can act):
  1. **`iter-2026-09-artifact-root · R2`** (medium): the artifact-root configuration's operational hardening — the cap/peak
     measure by walking the configured root once or twice per row (a network round trip on the intended mount), the
     measurement **fails open** when the mount is unavailable, the boundary never probes a write or a directory `fsync`,
     and no fixture covers any of it. Trigger: the first real corpus run with `--artifact-root` on the WebDAV mount.
  2. **`iter-2026-09-artifact-root · R3`** (medium): five hand-rolled path-to-base pairings (two identically named bundle
     helpers with different bodies) — the structural reason the same defect existed on two branches. Trigger: the next
     artifact family or the next time two helpers drift.
  3. **`iter-2026-09-artifact-root · R1`** (low): the write path's latent silent-no-upsert hazard; a future caller wiring
     the wrong base would turn a misconfiguration into an endless re-download. Trigger: the next plan touching
     `audio.py`'s record path or the coordinator's download wiring.
  4. **`e2e-23191782-season-7686105 · R1`** (medium, still open): the SRT/TXT/MD projection rebuild — unchanged by this
     iteration, which moved where artifacts live but not how they are built.
- **Standing discipline**: the low rows fold into plans that touch the same files (their `target` fields say which); the
  register is their SSOT.

## Compound Round Summary

Screened: the iteration package (`specs/artifact-root-contract.md`; no `guides/`), the plan's rulings and defect trail, and
the review material — each verified against the artifacts at the integration HEAD before promotion.

**Promoted — 2 new docs, 4 updated:**

| Doc | What it keeps |
|---|---|
| `{KNOWLEDGE_DIR}/architecture-patterns/artifact-root-split.md` (new) | The products/state split and why it is the design: products move, state (manifest, `archive.db`, sidecars, `search.db`) stays, because a FUSE mount cannot carry SQLite's locks or the manifest's per-append fsync pair. Plus the resolution/precedence rules, the two-base ordered read with its disclosed shadowing semantics, the **re-based** guard (`path_policy.py` unedited — only the root passed in changed), the four-refusal vocabulary and the reader map. |
| `{KNOWLEDGE_DIR}/best-practices/pairing-rule-travels-with-behaviour.md` (new) | The iteration's most expensive lesson: when a behaviour moves, the **pairing rule** must move with it. T3's fix for a one-base grading defect introduced a resolved-vs-lexical comparison that made `verify` and `coverage` disagree **inside one invocation**, and the tri-review then found the same family on a sibling branch. The tell is a reader and a writer disagreeing about one value — not a crash. |
| `{KNOWLEDGE_DIR}/best-practices/claim-scope-discipline.md` (updated) | **+4 instances** from this iteration, including operator-facing migration advice that was false in both halves and a docstring claiming an unshipped refusal, **+2 the PM itself wrote** (an inferred consequence two seats disproved by probe; an amendment applied twice because it patched a stale assumption), the author-side check, the "a message must be true of its input" rule, and the meta-observation that **review caught every instance, never the author**. |
| `{KNOWLEDGE_DIR}/testing-patterns/absence-assertion-negative-control.md` (updated) | Generalised to "the fixture must reach the falsifier", with the agreement-assertion-vs-fixture-gap case and the mutation control. |
| `{KNOWLEDGE_DIR}/testing-patterns/worktree-test-invocation.md` (updated) | The shared-stash-stack hazard (`git stash pop` with nothing pushed consumes another session's stash), stash-free RED capture, and the strict conflict-marker grep (Markdown `=======` false-positives). |
| `{KNOWLEDGE_DIR}/architecture-patterns/bilibili-asr-archive-cli.md` (updated) | The transient-audio section now states retain-by-default and per-base reclaim, and points at the new split doc. |

**Promoted to:** `{KNOWLEDGE_DIR}/architecture-patterns/artifact-root-split.md` (package spec §2–§10);
`{KNOWLEDGE_DIR}/best-practices/pairing-rule-travels-with-behaviour.md` (fix-wave defect trail + residual `R3`).

**Kept / skipped, with reasons:** the compass stays the package's own record (default-excluded); the D19 frozen-spec revision
had already landed in the repo, so it is not knowledge; residual rows `R1`/`R2`/`R3` stay register entries and are cited as
pointers; the `--max-audio-gb 0` ruling and per-command operator minutiae belong to the product docs; the review choreography
and finding ids stay in the ephemeral `{SDD_DIR}` bundles.

**Index and vocabulary:** `{KNOWLEDGE_DIR}/README.md` gained 2 rows and refreshed 4 (15 docs indexed); `CONCEPTS.md` gained the
term `artifact root`.

**Validator:** with `repo_root` at the integration checkout, the two best-practices docs **PASS**; the two new docs still fail on
the **registered false-positive class** (`iter-2026-09-text-and-ledger-precision · R1`: dotted `module.attr` tokens such as
`os.replace`, `cli.main`, `coordinator._declared_audio`), proven by neutralizing those tokens in `/tmp` copies. Two updated docs
failed identically before this round. The promotion did not edit prose to satisfy the heuristic.

- 结晶文档数：**2 新增 + 4 更新**（`{KNOWLEDGE_DIR}` 共 15 篇）
- 新增 CONCEPTS.md 条目：**1**（`artifact root`）
- 触发 compound-refresh：**否**（无文档因本次提升而过期；`bilibili-asr-archive-cli.md` 的 transient-audio 段已就地细化）

## Iteration Retrospective (minimal)

- **做得好的**：把"配置化输出位置"当成一次**架构切分**而不是加一个 flag —— 侦察先找出了三处硬约束（音频目录被写死、音频被限定在 archive root 内、预算与回收按路径形状拼），于是提案直接面向"产物/状态切分 + 守卫重锚定"，
  而不是等实现阶段撞墙。第二件做得好的事是"**守卫一行未改**"：`path_policy.py` 本来就是 root 参数化的，变的只是传进去的 root。
- **可改进的**：本迭代最贵的一课是**修复会引入同族新缺陷** —— T3 修好"整行只在一个基线上评级"（藏真缺陷、造假缺陷）之后，
  新写法又把"已 resolve 的候选"与"词法基线"比较，导致 `verify` 与 `coverage` **在同一次调用里互相矛盾**；随后三审又在**同一个函数的另一个分支**上找到同族缺陷。
  三次都指向同一个根因：**"路径↔基线"的配对规则被手写了五遍**。这类缺陷不会崩，只会让两个读者对同一个值给出不同答案 ——
  下一迭代若碰这块，先合并配对规则再改行为。
- **下迭代建议**：①**"这条断言能失败吗"与"这个读者和那个读者会不会给出不同答案"应当前移成作者动作**（本迭代四次"论断宽于代码"全由复审抓到，作者一次都没自查到，其中两次还是 PM 自己写的）；
  ②新增输出位置意味着**新的失败面**（网络挂载的延迟、抖动、fsync 支持），下一个配置化动作应连带一件探测与夹具，而不是留给运维；
  ③收口时把"论断纪律"的实例继续累积进同一篇知识文档，它已被两迭代连续喂养。

## Quality Gate Summary

| Plan | QC (L3) | QA (L4) | Result |
|---|---|---|---|
| `20260919-artifact-root` | tri-review approve after 2 fix waves (1 Critical + 2 Warning fixed; 2 rows registered) | approve with residuals - 7/7 criteria, 600 passed / 0 failed run by the seat | **Done** - products are relocatable, legacy archives keep working, retention defaults to retain |

**Open residuals disclosed (id · severity · decision · tracking):** `iter-2026-09-artifact-root · R1` (low, `defer`, the write path's latent silent-no-upsert) · `· R2` (medium, `defer`, the measurement hardening + fixtures + the two unreached `fail-closed` doc lines; must not be closed by documentation alone) · `· R3` (medium, `defer`, five pairing sites + the validity-vs-existence divergence). No `blocker-defer`; no unresolved `critical`. The plan's D19 frozen-spec revision landed with the close.
