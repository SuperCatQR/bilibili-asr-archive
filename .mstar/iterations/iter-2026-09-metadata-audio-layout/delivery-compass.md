---
iteration_id: iter-2026-09-metadata-audio-layout
start_date: 2026-09-26
end_date: 2026-09-28
status: completed
iteration_base_branch: main
spec_integration_branch: iteration/iter-2026-09-metadata-audio-layout
target_branch: main
plans:
  - 20260926-video-metadata-enrichment
  - 20260926-audio-inventory
---

# iter-2026-09-metadata-audio-layout — delivery compass

> **Status: `locked`** (2026-09-26). Registered the same day on explicit operator authorisation: `status.json`
> `workflows[]` carries this iteration's entry and `workflows/iter-2026-09-metadata-audio-layout/snapshot.json`
> is written. **`locked` authorises Phase 2 preparation; it does not authorise a write dispatch while the
> serial rule in `## Blocked By` stands.**
>
> **Phase-1 Review & Edit chain: complete.** All three seats ran, in order, one invoke each —
> `product-manager` (D11 refresh-on-recollect, D12 cover stays store-only, D13 capacity order) → `architect`
> (D14 root-relative `storage_key`, D15 `observed_at` advance condition; corrected four DDL defects and one
> cross-plan contradiction) → `writing-specialist` (corpus hygiene; verified the Q1/Q2 convergence holds on
> disk). Every `TODO(owner: …)` marker is **cleared**; none was re-owned to `PM`. The chain's documentation
> edits are uncommitted in the control root by design — the transfer/commit sequence is
> `phase-2-worktree-lease.md` §2.3 step 7.
>
  > **CLOSED 2026-09-28:** the layout shape decision landed after this iteration was already closed.
  > The operator chose **L1 = A** (per-work bundle directory), answered L2 as "revise the published
  > promise", and ruled that **no backward compatibility** is owed. The decision and its delivery are
  > recorded in `specs/output-layout-options.md` §5. Delivered on `feat/layout-shape-a`, merged as
  > PR #26 (`d743043`); see `## Roadmap Position` for the post-merge state.

## Blocked By

**Nothing. The iteration is registered as of 2026-09-26 and this section is now a concurrency record, not a
gate.** It is kept because the risk it names has not disappeared — it has been accepted, bounded and handed
to a scheduling rule (Phase-2 write dispatch stays **serial** behind that session).

Superseded blocking condition, evidence measured 2026-09-26 at 11:12 CST:

| Fact | Value |
|---|---|
| Active workflow | `iter-2026-09-qwen3-asr-closeout`, `phase: phase-2-execute`, `status: running` |
| Its plan row | `20260924-qwen3-asr-transformers` = `InProgress` |
| Its execution lease | `holder: project-manager/iteration-drive`, **not released** |
| Its feature worktree | `.worktrees/20260924-qwen3-asr-transformers` on `feat/20260924-qwen3-asr-transformers` |
| **Another live session** | session `03c3069a-…`, turn 10 at `11:08:45` CST; commits `0a95035` (10:38) and `83ba8d0` (**11:10:55** — one minute before this check) |
| Files it touched | `src/bili_asr/asr.py`, `tests/conftest.py`, `tests/test_asr_qwen.py` |

The operator's first decision (2026-09-26) was **write the plans now, register after that closeout finishes**.
The operator then **superseded it** on the same day: create the iteration worktrees and register now, since
Phase 1 produces no commits on shared product code.

**Correction to this section's original rationale — the overlap claim was wrong.** It said registering now
would put two lifecycles on one repository with overlapping write surfaces, "`asr.py` in particular". Measured
afterwards: the overlap is **zero product files**. That session's diff is `asr.py`, `tests/conftest.py`,
`tests/test_asr_qwen.py` (3 files); this iteration's two plans list 28 files and name `asr.py` only in *Out of
scope* lines. The real cost of concurrent registration is **ledger attribution**, not file collision: a
session with no stored binding and no lease resolves through the single-active-entry fallback, so a second
entry makes it unresolvable until it picks one. Both sessions now hold explicit bindings.

**Scheduling rule that replaces the gate** — ~~the two lifecycles must not run write dispatches at the same
time~~. **RELEASED by the operator, 2026-09-26** (after being asked directly: dispatch T1 now, or wait for
`iter-2026-09-qwen3-asr-closeout` to close — the answer was proceed).

**Correction to this rule's own rationale, recorded because it was over-strict.** The rule as first written
conflated "another lifecycle is live" with a dispatch prohibition. `phase-2-worktree-lease.md` §2.0 #5 defines
the actual cross-parallel gate, and it is about **plans within one iteration**, satisfied by (a) a same-host
exclusive write lock on the coordination path, held on every coordination change, or (b) `Plan parallelism:
serial`, or (c) the operator accepting the cross-host lease race. It is **not** a statement that a second
registered lifecycle bars a first one from working. Four measurements replaced the rule's premise:

| Fact | Measured 2026-09-26 |
|---|---|
| Product-file overlap between the two iterations | **Zero** — this iteration's plans name 22 product paths, the other's branch diff is 4 (`README.md`, `asr.py`, `tests/conftest.py`, `tests/test_asr_qwen.py`), intersection empty |
| Ledger attribution collision | **Gone** — the other session holds an explicit binding (`selectedWorkflowId=iter-2026-09-qwen3-asr-closeout`), so a second entry cannot strand it |
| Same-host exclusive write lock on the coordination path | **Available and used** — `.mstar/.execution-maintenance/.status-write.lockdir` (atomic mkdir), exercised for both this iteration's registration and its `phase-1-locked` snapshot update |
| Is the other iteration actively writing? | **No** — its feature worktree is clean, and its plan-row note records T5/T6 complete with §14 item 4 *deferred by the operator* (which is why its row is not `Done`) |

**What still binds, and is not waived by this release:** the worktree + lease gates (§2.0 #5 — `Plan
parallelism: serial` never waives them). A writable dispatch for a plan requires a **verified
`execution_lease`** naming its feature worktree and working branch; merges into `spec_integration_branch` stay
**serial** via the top-level `integration_merge_lease`. Read-only work was never affected.

**Update 2026-09-27 — the reason the rule existed is now gone.** `iter-2026-09-qwen3-asr-closeout` reached
`completed` / `phase-6-post-merge-close` (its row `20260924-qwen3-asr-transformers` is `Done`, lease released).
The concurrent session moved on to a **different standalone plan** (`20260927-aac-decode-contract`) whose diff
touches `asr.py`, `tests/conftest.py`, `tests/test_asr_qwen.py` and `README.md` — the same three product files
as before, and still **disjoint from this iteration's 22**. So the release above no longer rests on the
operator's say-so alone: there is no other lifecycle sharing this iteration's write surface. What remains is
the ordinary rule that two writable streams must not edit the same file at the same time.

**The mirror case was observed, and it is the registration mechanism's known cost — recorded so it is not
mistaken for a fresh fault.** On 2026-09-27 at 02:23–02:27 the *other* session resolved to **this** iteration,
the exact inverse of the 11:57 incident: `iter-2026-09-qwen3-asr-closeout` closed (`completed`,
`phase-6-post-merge-close`) and that session registered a new standalone plan (`20260927-aac-decode-contract`),
which made two entries active while it held no binding yet. Its 02:37 turn reported
`unbound-multi-active`; 18 seconds later it was `active` on its own plan. **No pollution resulted in either
direction** — this iteration has no `agent-flow.jsonl` at all, so nothing of theirs could land here, and the
seven rows appended to their ledger in that window are their own close-out events (23:58 verdict/run,
01:33 run-end), none of them ours. The lesson is structural, not personal: **any** lifecycle registered while
another active entry exists needs its own binding before its session can resolve, and the host provides that
only through the operator's panel pick or `/mstar-execution adopt`.

**Entry procedure used** (this host has no `mstar` CLI and no engine package, so the two writes were made by
hand): write `workflow snapshot` first (create-only), then append the root `status.json` entry inside the
engine's own `EXECUTION_MAINTENANCE_LOCKDIR` (`.mstar/.execution-maintenance/.status-write.lockdir`) as an
atomic mkdir, re-reading the register under the lock and asserting the pre-existing entry byte-identical
before release. Then follow `phase-2-worktree-lease.md` §2.3.

## Scope

Three operator complaints, investigated 2026-09-26 with three independent read-only reconnaissance seats.

In scope, in this order (**binding dispatch order — D13**):

1. **Persist the video metadata the pipeline already receives and discards.** The operator named video tags;
   the investigation found the gap is wider and the cost is smaller than a tag fetch alone — the uploader
   name is a placeholder (`"23191782"` instead of `未明子`), and the real video title never reaches an
   artifact (the md says `哲学课3`).
   `Check: ## Acceptance Criteria 1-3`. Plan: `20260926-video-metadata-enrichment`.
2. **Make the downloaded audio inventoried, and pin the retention/reclaim behaviour that already holds.**
   The operator asked for persistence; the investigation found retention is **already** the default **and
   already tested** (D6) — so this item adds **no** retention and **no** persistence, and its title's
   "un-silenceably retained" names a property the shipped code has, not a change this iteration makes. The
   real holes are that the store cannot answer "which audio do I have" (the inventory half, the larger and
   the whole of the feature) plus two narrow coverage gaps in that surface (flag precedence over the
   environment; the sibling-page reclaim case).
   `Check: ## Acceptance Criteria 4-6`. Plan: `20260926-audio-inventory`.
3. **The output layout complaint.** Investigated, decided **and delivered**. The survey of 2026-09-26
   (measured costs, four decision items) is in `specs/output-layout-options.md`; the operator's
   2026-09-28 ruling settled L1 = A with L2 revised and no backward compatibility, and the migration
   shipped as PR #26 (`d743043`, merged into `main`; full suite 1775 passed / 125 skipped). The layout is
   now `transcripts/{stem}/bundle.{srt,txt,md,raw.json}` + `.bundle-ready`.
   `Check: ## Acceptance Criteria 7`.
   **Owed, not delivered:** no migration plan was ever written as a `{PLAN_DIR}` plan -- the decision
   arrived after this iteration closed and the change shipped as a direct branch. Two gaps are registered
   as residuals: no live-corpus verification (the 123pan WebDAV mount returns 401) and no arm's-length
   L2 verdict.

Out of scope: everything under `## Non-Goals`. (The layout *migration* was listed here as out
of scope because it was blocked on decision L1; that decision has since landed and the
migration shipped as PR #26, outside this iteration's branch.)

## Decisions

| # | Decision | Rationale | Source |
|---|----------|-----------|--------|
| D1 | **Registered, `active`, on explicit operator authorisation.** The iteration is registered (`status.json` `workflows[]` carries a second entry; `workflows/iter-2026-09-metadata-audio-layout/snapshot.json` written) and this compass moves `draft` → `active`. | Originally held back because a live session held `iter-2026-09-qwen3-asr-closeout`'s lease and registration is a repository-wide write. The operator then directed worktree creation and registration while that session is still live. The residual risk is bounded and understood: the two lifecycles share **no** product file — the other session's diff is `asr.py`, `tests/conftest.py`, `tests/test_asr_qwen.py` (3 files), while this iteration's two plans list 28 files and name `asr.py` only in *Out of scope*. The real cost is **ledger attribution**, not file collision. Phase-2 write dispatch therefore stays **serial** behind that session (see `## Blocked By`). | user instruction 2026-09-26 (supersedes the same day's earlier decision) |
| D2 | Metadata scope = the **high-value set**: video title onto the artifact, uploader name, tags, category and cover. Not the whole 45-key `view` response. | The operator asked for tags specifically; the title and the uploader name are free (already in responses the pipeline fetches) and carry the highest reader value. A snapshot of the entire response would freeze time-varying `stat` counters on `videos`, which is a different decision. | user instruction 2026-09-26 |
| D3 | New video-level facts go into **child tables** (`video_tags`, `video_details`), never widened columns on `videos` / `video_parts`. | Measured: `initialize_schema` runs only `CREATE ... IF NOT EXISTS`, so a new column is **silently absent** on every existing `archive.db` and its first `INSERT` raises `OperationalError`; a new table is created on the next open. Verified by running the product's own `initialize_schema` on a scratch database. | architect finding, 2026-09-26 (recon seat `metadata`) |
| D4 | The 25th (or later) frontmatter key is a **deliberate, pinned format revision**, never a silent addition. | `test_write_archive_publishes_the_exact_asr_key_set` (`tests/test_archive_md.py:297-349`; the old `:296-333` anchor predates the revision) pinned the exact ordered 24-key list with `assert len(front) == 24`. A silent addition would fail that test; a silent *semantic* change to `title` would not — hence D5. | code fact, 2026-09-26 | **Delivered 2026-09-27:** the pin now reads **25** (`assert len(front) == 25` at `:343`, 15 `asr_*` at `:344`), so the numbers quoted above are the pre-revision baseline.
| D5 | The frontmatter `title` **keeps** meaning the part title; the video title is a new sibling key `video_title`. | Redefining an existing published key changes what an archived artifact says without changing its shape — undetectable by any existing test and confusing to a reader comparing two archives. A sibling key is additive and honest. | user instruction 2026-09-26 (naming discipline); `naming-analyzer` pass |
| D6 | Audio **retention stays the default**; this iteration does not change it. The gap closed is the missing inventory plus two narrow test-coverage holes. | Retention already is the shipped default (`KEEP_AUDIO_DEFAULT = True`, `artifact_root.py:87`), nothing hard-codes a reclaim, **and the behaviour is already tested** — `tests/test_audio_retention_policy.py` (113 lines, 4 cases) pins retain-on-unset, and `tests/test_audio_reclaim.py` (189 lines, 11 cases) pins the unlink paths. Claiming to "add persistence" or "add retention tests" would both be false. | user instruction 2026-09-26; measured 2026-09-26 |
| D7 | The audio inventory uses the **already-declared** `audio_objects` / `part_audio_objects` tables. No schema change. | They exist in `schema.sql:92-110`, are pinned by `BASE_TABLES`/`EXPECTED_TABLE_COLUMNS`, and have never had a writer. Using them needs no schema change, which by D3's own rule is the cheapest possible landing. | architect finding, 2026-09-26 (recon seat `audio`) |
| D8 | The layout target shape is **not decided** in this iteration. The survey is the deliverable; the migration plan waits. | The operator chose to hold it open after seeing that "scattered" has a measurable core (two naming rules for one work id, which orphans an md on a title change) and a structural shell (10 product + 10 state families). Deciding a shape before knowing whether "fewer directories" or "one naming rule" is the actual want would misprice the work by an order of magnitude. | user instruction 2026-09-26 |
| D9 | The `/tmp` copy made per ASR row (`asr.py:304-318`) is **out of scope** for this iteration; it is documented in `specs/audio-retention-contract.md` §6. | `asr.py` was under active edit by the other live session on 2026-09-26 (`0a95035`, `83ba8d0`). Editing it here would create a merge conflict on the very lines the audio plan cares about. The cost is real and recorded, not dismissed. | measured 2026-09-26; user decision on the concurrent session |
| D10 | Branch policy: base `main`, integration `iteration/iter-2026-09-metadata-audio-layout`, target `main`. Recorded, not defaulted. | The repository's `AGENTS.md` sets the default integration/PR target to `main` and feature work to `iteration/<iteration-id>`. Recorded here explicitly because this compass must not infer a branch from the existence of `main`; the branch is named in `## Delivery Branch Policy` and will be mirrored into the workflow snapshot at registration. | repo `AGENTS.md`; recorded 2026-09-26 |
| D11 | **Metadata is refreshed on recollect, not frozen as a point-in-time snapshot.** `video_tags` and `video_details` hold **one row per video**, and `video_details.observed_at` records the moment of the **last successful collection** — a later collection overwrites it. No table in this iteration is a dated series, and no reader may infer "what upstream said on date X" from one. | The archive's product is the transcript; the store is a working index of what upstream last said, not an evidence vault. A snapshot guarantee would need a timestamped append-only child table per field family and a reader that asks for a time, and nothing asks. The only time-varying fields worth freezing were the `stat` counters, which D2's scope already declines; the fields actually stored change slowly enough that refresh-on-recollect degrades honestly — a stale row states what was true at collection. **Consequence, written into the plan:** `20260926-video-metadata-enrichment` may not promise a historical record, and its `video_details` docstring must say the single row is refreshed. | product-manager ruling 2026-09-26 (seat 1), consistent with the operator's D2 scope instruction 2026-09-26 |
| D12 | **The cover stays store-only: `export` keeps redacting it.** A stored `pic` is readable from `archive.db` and **invisible in every export**, because `export.py`'s key rule and value redaction are **not** modified this iteration (`_SENSITIVE_KEY_SUFFIXES` `:66-73`, `_is_sensitive_key` `:85-98`, value redaction `:174-177`). Wanting a cover in a *shared* export is a **new** decision (an explicit allow-list entry), not a relaxation of the general rule. | Export is the shareable surface and its rule is total: no `http(s)://` value and no `*_url` key leaves it. Punching a hole for one field would weaken a shipped guarantee for every export row to gain a URL the local store already carries — and the operator's complaint is about **persistence**, which the store answers. Naming the column `pic` (not `cover_url`) already threads this rule deliberately; the ruling makes it a promise instead of an accident. Revisit trigger: a named reader that needs the cover outside the archive. | product-manager ruling 2026-09-26 (seat 1); no operator instruction covers export policy |
| D13 | **Priority order under capacity pressure: metadata first, audio second — the audio inventory gives way if only one plan fits the window.** D2's scope is unchanged and both plans stay in this iteration's list; what is binding is the **dispatch order**, and a single-slot window takes `20260926-video-metadata-enrichment`. | The operator named the metadata complaints first, and named the tag field itself; deferral costs are asymmetric. Deferring the metadata plan means every ingest in the meantime keeps writing the placeholder `display_name = str(mid)` and publishing md without `video_title` — facts that only a re-collect repairs. Deferring the audio inventory costs **queryability only**: retention is already the shipped default (D6), so no audio is lost while it waits. Reversible by PM if the metadata plan hits its own STOP condition (Task 3's `tid` source), in which case the audio plan takes the slot. | user instruction 2026-09-26 (complaint order); product-manager ruling 2026-09-26 (seat 1) on which plan gives way |
| D14 | **`audio_objects.storage_key` holds the root-relative declared string (`audio/<stem>.<ext>`); an absolute path is refused.** The key is the same value the manifest records, resolved through `artifact_root.resolve_audio_path`'s ordered base pair. With it: a row never carries a base, so a row stays valid across a root change (artifact-root **D7**/**D12**), no new resolution rule is invented (**D8**), and `path_policy._audio_parts` (`:16-29`) — which refuses an absolute path outright — can still validate it. `audio_objects.sha256` remains the identity; `storage_key` is `NOT NULL UNIQUE` and an absolute key would split one object into two rows under two roots. | architect ruling 2026-09-26 (seat 2), clearing compass marker `:276` and closing the audio plan's `AQ1` | architect ruling 2026-09-26 (seat 2) |
| D15 | **`video_details.observed_at` advances only on a collection that actually observed something — "last successful collection", not "last attempt".** A re-collect that carries none of `pic`/`desc`/`tid` leaves the existing row and its stamp **untouched** rather than blanking the values and advancing the time. One row per video, still refreshed, still not a series. **This narrows D11's phrasing; it does not reopen or override it** — D11's own sentence already reads "the moment of the **last successful collection**", so its "a later collection overwrites it" is read as "a later *successful* collection overwrites it", and D15 only makes the qualifier operational. A reader who takes the literal "overwrites" against an empty observation is reading a guarantee neither decision makes. | The DDL lets all three value columns be `NULL`, so an unconditional `DO UPDATE SET` — the plan's first draft — can overwrite a populated row with nothing and stamp it as fresh, in a column whose meaning D11 fixes as the *last successful* collection. That is a fiction the schema cannot detect and the D11 pin cannot see (it asserts a count). Landed in Task 3 Step 3, the Task 3 `## Interfaces` line, and `specs/metadata-coverage-contract.md`'s preamble. | architect ruling 2026-09-26 (seat 2), clearing compass marker `:274`; consistent with D11's own wording (product-manager, seat 1) |
| D16 | **A tag fetch that produced no observation must not clear the `video_tags` rows a previous run stored.** `get_video_tags` answers **`None`** for "could not read this time" (risk control `-352`/`412`, transport failure) and **`()`** for "read it, and there are none"; the ingestor maps `None` to **omitting the bvid key**, which `record_page` already treats as non-destructive (`(tag_sets or {}).items()`), so nothing is written for that video and its stored rows survive. The builder must stop synthesizing an empty list from a failed read. **This extends D15's principle to `video_tags` — it is not D15 applied as written:** D15's scope is `video_details`/`observed_at` only, and its mechanism (an advance condition on one column) has no counterpart in a table that replaces a whole set, so the mechanism here is the return protocol plus the absent-key rule. **D11 is not overridden:** a later *successful* collection still refreshes the video's tags, and a genuine empty observation — key present, empty iterable — still clears them, which is exactly what AC 3's "a second run of the same bvid replaces the set rather than appending" pins. Clearing on an observation stays correct; only a non-observation stops being destructive. | Same defect class as T1's `C1`, and the same fiction D15's own justification names: the store cannot tell "upstream no longer lists these tags" from "we failed to ask", because `DELETE` followed by zero inserts leaves no trace the way a wrong value does. The empty tuple was legal input to a clearing write only because the plan's `:483` instruction made it so, and the task's only degradation test (`test_degraded_tag_fetch_does_not_fail_the_run`) runs on a fresh database, so no test in the plan can see the loss — it exists only across two runs with a degradation in the second. Bounded, not benign: the tags are a side table, not the artifact, and the next successful collection re-observes the truth, which is why the L2 review graded it `Important` rather than `Critical` — but the erasure ships in the default path and a reader of the table cannot detect it afterwards. **Rejected: a conditional delete inside `upsert_video_tags` ("never delete on empty")** — it would invert the pinned `test_upsert_video_tags_with_no_records_clears_the_set` and destroy a genuine empty observation's clear; the distinction has to be made where the information still exists, which is the gateway's return, not after it has been flattened to a list. | product-manager ruling 2026-09-27 (Task 3 fix round — not the Phase-1 chain), extending **D15** (architect ruling 2026-09-26); companion plan amendment in `20260926-video-metadata-enrichment.md` Task 3 Step 3 + `## Interfaces`; evidence `.mstar/sdd/20260926-video-metadata-enrichment/task-3-review.md` §I1-§I2 |

## Open Questions

**Q1 and Q2 were the two `product-manager`-owned rows. Both are now converged into `## Decisions` — Q1 → D11,
Q2 → D12 — for cause: a question that changes what a plan may promise, and that no code measurement can
settle, is a product ruling, not an open item. Their plan-level restatements were withdrawn in the same
round, so neither row survives in the metadata plan's own `## Open questions`. The rows below are what
remains.**

| # | Question | Owner | Blocking? |
|---|----------|-------|-----------|
| Q3 | Is one extra unsigned GET per video acceptable for a full-corpus run? Measured 2026-09-26: `/x/space/wbi/arc/search` returned `code 0` twice and then **HTTP 412**; `/x/web-interface/wbi/view/detail` returned `-352 风控校验失败` after two successes. A rate limit or campaign cap may be owed. | PM | No |
| Q4 | Which output-layout shape? **A** (per-work bundle dir) / **B** (flat, kind-in-extension) / **C** (four dirs, md renamed) / a combination — e.g. C now, A later. Decision items L1-L4 and measured costs are in `specs/output-layout-options.md` §4-5. | PM (needs user) | **No** for this iteration's two plans — blocks only the *third, unwritten* plan |
| Q5 | Is the published four-family promise (`README.md:602-607`) negotiable? It pins three families to `<stem>` and leaves the md a wildcard. Targets A and B revise it; Target C does not. | PM (needs user) | **No** for this iteration's two plans — blocks only targets A/B of the *third, unwritten* plan |
| Q6 | Does the operator want **fewer directories**, or only the naming defect fixed? The complaint says "too scattered"; the measured defect is the two-rules problem (`specs/output-layout-options.md` §2). This answer selects C against A/B. | PM (needs user) | **No** for this iteration's two plans — blocks only the *third, unwritten* plan |

**Q4-Q6 are the layout decision, and they are scoped to the third plan only.** The scope correction is
deliberate and is what makes this compass lockable: `phase-1-prepare.md` §1.3(v) bars `status: locked` while a
`Blocking? Yes` row is unconverged, and Q4-Q6 cannot be converged by any agent — they need the operator. The
substance is unchanged and nothing was silently deleted: all three rows remain in this table with owner `PM
(needs user)`. What was wrong was the *scope* of the flag — it read as blocking the iteration when it in fact
blocks one unwritten plan that is already declared out of this iteration's scope (`## Non-Goals`). The two
written plans (metadata, audio) are independent of the shape and were each reviewed by the chain on that basis.

**Consequence, recorded so it cannot be mistaken for an oversight: the third plan stays unwritten and is not
part of this iteration's locked scope.** Answering Q4-Q6 re-opens planning (a new iteration or an approved
scope expansion); it does not unblock work queued behind this lock.

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| `20260926-video-metadata-enrichment` | Persist the video metadata the archive already receives | **Done** | All five tasks delivered. Tasks 1–3 via PR #21 `2696711` (merge `8c29c27`, incl. D16 rider `a8670a3`); **Task 4 (`video_tags`/`video_details` child tables, D11/D15 refresh-on-recollect, D16) landed by PR #25 `cefed49`** — SDD round `.mstar/sdd/20260926-video-metadata-enrichment/task-4-*` (brief/diff/report/review/2× PM verification). Residuals R1–R3, R5–R7 + M-R* stay open and registered. |
| `20260926-audio-inventory` | Make the downloaded audio inventoried and un-silenceably retained | **Done** (AC 4/5 via other lifecycles; **AC 6 delivered 2026-09-28**) | **AC 4** holds (`tests/test_storage_queue_writes.py:174-177`, 11 passed) and **AC 5** holds (`tests/test_audio_retention_policy.py` + `tests/test_audio_reclaim.py`, 13 passed / 2 skipped) — but both were earned by PR #21 `2696711` / PR #24 `662d9ca`, not by this plan. **AC 6 was recorded as met while the command did not exist in any commit** (`git log --all -S` matched plan/contract prose only; the CLI had 23 subcommands and none was `*inventory*`). It is now real: `feat/20260928-audio-inventory` `678b376` + `bda9465`, merged as `5048de6`, 8 tests, one summary line in §3.1's field order, exit 0 on an empty reconciliation, read-only over the audio tree. **Task 1 is SUPERSEDED, not owed** — its `record_audio_object`/`link_part_audio` API never shipped and `mark_audio_acquired` (keyed on `storage_key`, not `sha256`) is the real seam. **Task 3 is 0/5**: coverage-completeness over an AC 5 that already passes. **No independent L2 verdict on Task 2** — the reviewer died with a skeleton and the PM both wrote and adversarially re-read the diff, finding two real defects in it (residual A-R4). Open: A-R1 (a present-but-unreadable file fits no §3.1 counter — needs a ruling), A-R2, A-R3. Also corrected here: **AC 4**'s cited evidence file `tests/test_audio_inventory.py` had never existed (the real coverage is the queue-writes file above), and an earlier PM note in this file called **AC 7** unmet — that was a misreading: AC 7 asks for the *survey*, and `specs/output-layout-options.md` §4 gives the measured cost per candidate shape while §5 names the decision required (Q4–Q6, flagged user-owned and blocking). The open item is the SHAPE DECISION itself, which correctly blocks the unwritten layout-migration plan. |
| *(layout migration — plan not written)* | — | — | Waits on Q4-Q6. Survey: `specs/output-layout-options.md` |

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Investigation complete, three plans' worth of material measured | 2026-09-26 | **done** |
| Two plans written (metadata, audio) | 2026-09-26 | **done** |
| Layout survey written with measured costs + open decision | 2026-09-26 | **done** |
| `iter-2026-09-qwen3-asr-closeout` reaches Phase 6 | — | awaiting |
| Phase-1 review-and-edit chain runs against this package | — | waiting on the line above |
| Compass locked, iteration registered | — | waiting |

## Acceptance Criteria

Each criterion below is restated in checkable form — exact command, exact expected observation — inside the
owning plan's own `## Acceptance criteria` section, so a reader who never read the investigation can verify
item without reconstructing the evidence. The `Plan` column names the owning plan; the `Evidence` column
names what the check actually observes.

| # | Criterion | Plan | Evidence |
|---|-----------|------|----------|
| 1 | A fresh ingest writes the uploader's real display name into `bilibili_users.display_name`, not `str(mid)`; an item carrying no `author` still falls back to `str(mid)` | metadata | a test asserting the observed `author` reaches the record (live value `未明子`) **plus** the negative control for the absent-author case; no assertion of the placeholder may survive in `test_metadata_ingest.py` / `test_metadata_e2e.py` |
| 2 | A published transcript artifact carries the video title, and the existing `title` key still means the part title | metadata | the md frontmatter contains `video_title` beside an unchanged `title`; the pinned key-set assertion is updated deliberately at its new exact length and named in the commit body — never loosened to a subset check |
| 3 | A video's tags are stored keyed by `(bvid, tag_id)` and are fetched **once per video**, not once per part | metadata | a multi-part test asserting exactly one tag call (`gateway.tag_calls == ["BV1MULTI"]`); `video_tags` rows queryable by `bvid`; a second run replaces the set rather than accumulating |
| 4 | `SELECT COUNT(*) FROM audio_objects` is non-zero after a download, and `part_audio_objects` links each object to its part | audio | an inventory test over one downloaded row, plus a direct `sqlite3` read of both counts on that root |
| 5 | The flag's precedence over `BILI_KEEP_AUDIO` is pinned, and a reclaim of one page leaves a sibling page's file present | audio | two characterisation tests in the existing suites, **expected to pass on first run**; a red result is a reported finding (data-loss defect → PM), never a weakened test |
| 6 | `derive-audio-inventory` reports `recorded` / `already` / `missing` / `unlinked` — counting what `specs/audio-retention-contract.md` §3.1 defines — and exits 0 on a zero-row reconciliation | audio | **DELIVERED 2026-09-28** on `feat/20260928-audio-inventory` (`678b376` + `bda9465`): `tests/test_audio_inventory.py` — 8 tests over a populated root, an empty root, and a re-run; one summary line in §3.1's field order; four counters each independently pinned; exit 0 on empty. Delivered after the PM found this row was **false** — the command had never existed in any commit, only in plan/contract prose. Two defects in the first implementation were found by the PM's own adversarial re-read and fixed in `bda9465`: the plan's explicit cost model was violated (a known row cost a file read where Task 2 requires zero) and a present-but-unreadable file was counted under `missing`, which §3.1 excludes. **Caveat: no independent L2 verdict exists** — the reviewer died with a 330-byte skeleton, and the PM authored the task (residual A-R4). |
| 7 | The output-layout survey states the measured cost of each candidate shape and names the decision needed | layout | `specs/output-layout-options.md` §3-5 (written; decision open) |

## Corrections recorded during authoring (2026-09-26)

Two claims in this package's first draft were **false** and were withdrawn after verification. They are
recorded rather than quietly fixed, because both are instances of the `claim-scope-discipline` class
(`{KNOWLEDGE_DIR}/best-practices/claim-scope-discipline.md`): a claim about what the code does or lacks must
be read off the code, not inferred from a symbol's absence in one grep.

| # | Withdrawn claim | What verification showed | Where it landed |
|---|---|---|---|
| 1 | "The audio retention default is untested, so a future edit can invert it silently." | Retention **is** tested: `tests/test_audio_retention_policy.py` (113 lines) pins retain-on-unset, `BILI_KEEP_AUDIO=1` retains, `=0` deletes, and the coordinator honours the value. Two genuine gaps survived checking: flag **precedence** is unpinned, and no reclaim case places a sibling page's file beside the reclaimed row's. | `specs/audio-retention-contract.md` §2.2; plan Task 3 rewritten as an XS coverage task |
| 2 | `VideoSummary.author` should be a **required** non-empty `str`, with a missing `author` a `GatewayShapeError`. | A required field would break every one of the **46** `make_vlist_item` call sites (the builder emits five keys; recounted 2026-09-26 — the earlier "47" counted the definition line), plus `_complete_summary_from_detail` (`bilibili_api_gateway.py:516-522`), which rebuilds the DTO without it, plus the two test `_summary` factories. `author` is therefore `str | None`, and the `str(mid)` fallback lives in the ingestor. | metadata plan Task 1 `## Design note` |

A third premise was **downgraded, not withdrawn**: Task 3's `tid`/`pic`/`desc` fields rest on a **live
probe** (2 of 3 attempts succeeded; the third returned HTTP 412), not on a recorded fixture, and
`make_vlist_item` carries none of them. The plan now says so explicitly and requires the implementer to
distinguish fixture-verified from probe-verified in its Completion Report.

## Non-Goals

- **No layout migration in this iteration.** The survey is the deliverable (D8); the migration plan waits on
  Q4-Q6.
- **No move of the 10 state families.** `README.md:470-475` explains why they cannot move: the manifest's
  per-append `fsync` pair and SQLite's locking are exactly what a FUSE/WebDAV mount cannot carry. This is
  permanent, not deferred.
- **No migration of existing archives on disk.** The shipped non-goal
  (`.mstar/iterations/iter-2026-09-artifact-root/specs/artifact-root-contract.md:443`). Recorded paths stay
  root-relative; a physical `mv` is the operator's.
- **No `stat` counters, no `rights`, no `dimension`.** Time-varying or reader-less; see
  `specs/metadata-coverage-contract.md` §3.2.
- **No credential on the tag call.** It answers anonymously today and must keep doing so.
- **No `asr.py` change** (D9), including the `/tmp` materialize copy.
- **No `KEEP_AUDIO_DEFAULT` change** (D6).
- **No backfill of `audio_objects` for audio already on disk** in this iteration — the plan's Task 2
  *records* what it finds, which is a forward-looking reconciliation, not a historical backfill with
  re-derived hashes.
- **No real-machine CLI E2E.** That lives only in a separately requested `mstar-e2e` workflow.

## Roadmap Position

- Current iteration: **delivered** (2026-09-28) — metadata enrichment (uploader name, `video_title`, tags,
  category/cover; 6 tasks incl. the R3 doc repair) and the audio inventory (`derive-audio-inventory`, AC 6) both
  complete; integration `iteration/iter-2026-09-metadata-audio-layout` @ `5048de6`, full suite 1699 passed / 123
  skipped. **Merged to `main` as `cefed49` (PR #25 squash-merge, 2026-09-28); full suite on merged main 1774 passed / 125 skipped.** See `## Quality Gate Summary` for the open residuals and the corrections this close made.
- Next iteration: the **layout migration** — the one plan still unwritten. It cannot start until the operator
  answers **Q4–Q6** (`specs/output-layout-options.md` §5, four candidate shapes with measured cost; the survey
  recommends C now and a re-decision on A/B with the L3 answer). Owner: PM, blocked on the operator.
- Parallel: `iter-2026-09-ops-readiness` (queue CLI cutover, hotword governance, proofread pipeline, search) —
  reported complete by another session; `20260928-*-ops-*` plans all `Done`.
- Deferred behind the layout decision: nothing in this iteration. The metadata and audio surfaces are closed.

## TODO markers owed to the Phase-1 chain

This compass is a **draft written by PM after an investigation**, not a locked Phase-1 artifact. The
review-and-edit chain has not finished. The work owed to it:

**Cleared by seat 1 (`product-manager`), 2026-09-26 — two of two, none re-owned:**

1. *"decide and record Q1 … and Q2 …"* → **cleared.** Q1 became **D11** (metadata is refreshed on
   recollect; `video_details` keeps one row per video and `observed_at` means "last collected", so no reader
   may read a snapshot guarantee out of the grain) and Q2 became **D12** (the cover stays store-only;
   `export`'s redaction rule is unchanged this iteration). Both questions left `## Open Questions` in the
   same round, and both of their restatements inside `20260926-video-metadata-enrichment.md` were withdrawn
   so the plan cannot promise either behaviour. Reason both converged rather than staying open: each changes
   what a plan may promise and neither is answerable by measuring code.
2. *"confirm the metadata scope in D2 is the priority order …"* → **cleared.** **D13** records the order:
   metadata first, audio second; if the window fits only one plan, `20260926-audio-inventory` gives way,
   because the metadata promises repair facts that a re-collect cannot recover once the meantime has passed,
   while the audio inventory defers queryability only — retention is already the default (D6), so no audio is
   at risk while it waits.

**Cleared by seat 2 (`architect`), 2026-09-26 — two of two, none re-owned:**

1. *"review D3's child-table design against the storage contract … confirm `video_tags`/`video_details` are the right grain"* → **cleared.** The grain is confirmed correct and D11 is **not** reopened; the DDL underneath it carried four defects, all now landed (schema-pin breadth, a needless index, an unconditional `observed_at` advance, and a D11 pin that could not observe its own stamp). Ruling recorded as **D15**.
2. *"should `audio_objects.storage_key` hold the root-relative declared string or an absolute path?"* → **cleared.** Root-relative, ruled against artifact-root **D7**/**D12**/**D8** and `path_policy`'s own refusal of absolute audio paths; recorded as **D14**. The same ruling exposed a writer defect in the audio plan's `ON CONFLICT(sha256)` shape, landed with it.

The markers below are owed to the remaining seats:

<!-- CLEARED(architect, 2026-09-26). **D3's child-table grain confirmed; the DDL as first written carried four defects, all corrected in `20260926-video-metadata-enrichment` Tasks 2-3 and `specs/metadata-coverage-contract.md` §2/preamble.**

**Ruling — grain: correct, not reopened.** `video_tags(bvid, tag_id, tag_name, tag_type)` and `video_details(bvid PRIMARY KEY, pic, "desc", tid, observed_at)` are the right grain: one row per video, keyed by `bvid`, both created with `CREATE TABLE IF NOT EXISTS`, so §2's "new table ⇒ created on the next open ⇒ **additive — preferred**" verdict holds and no operator owes an `archive.db` rebuild. The "one row per video, or a timestamped series?" question stays answered by D11 (one row, refreshed) and is **not** reopened — the fixed grain is a decision, not a defect found here.

**What the D3/§2 review found, and where each finding landed:**

1. **The schema pin is four maps, not two.** `test_schema_inspection_matches_the_declared_contract` (`tests/test_storage_schema.py:856-942`) asserts, per table in `BASE_TABLES`: `EXPECTED_TABLE_COLUMNS` (`:69`), `EXPECTED_FOREIGN_KEYS` (`:173`), `EXPECTED_PRIMARY_KEY_INDEXES` (`:205`), and — for a declared `CREATE INDEX` — `EXPECTED_INDEXES` (`:215`), while `EXPECTED_UNIQUE_CONSTRAINTS` (`:198`) defaults to `()`. **Measured** against this plan's own DDL: the two foreign-key entries and the two primary-key-index entries are **required** (each assertion reads `.get(table, ())`, whose default is empty, so it fails without an entry); the unique-constraint and index maps need none. Task 2's instruction named only `BASE_TABLES` + `EXPECTED_TABLE_COLUMNS` → corrected to name all four, and the same correction is written into `specs/metadata-coverage-contract.md` §2 for the next reader.
2. **The index is unnecessary and would break the pin.** Measured with `EXPLAIN QUERY PLAN`: the `video_tags` primary key `(bvid, tag_id)` already serves the plan's only declared query — `SEARCH video_tags USING INDEX sqlite_autoindex_video_tags_1 (bvid=?)`. §2 *permits* a new index (it is additive), but it must be registered in `EXPECTED_INDEXES` for zero query benefit, so Task 2's "`video_tags` table + its index" is dropped.
3. **`observed_at` now says what it means — and "successful" is now a condition, not an adjective.** The grain was right, but the DDL carried no annotation for the column and the plan's implementation rule was **always overwrite**. Since the DDL lets all three value columns be `NULL`, that rule lets a later observation carrying none of `pic`/`desc`/`tid` **blank a good row and advance the stamp** — writing "nothing was true at T" where the collection established no such thing, in a column whose meaning D11 fixes as *last successful* collection. Ruled as **D15** and landed as an explicit advance condition in Task 3 Step 3, in the Task 3 Interfaces line, and in the contract preamble. One row per video, refreshed, either way — D15 narrows D11's wording to the qualifier D11 already uses; it neither reopens nor overrides it.
4. **The D11 pin could not have observed the stamp it claimed to pin.** Task 3's `test_video_details_are_refreshed_not_appended` is specified (correctly) to assert `COUNT(*) == 1` — the assertion that actually distinguishes refresh from append, since a timestamped series would also show the newest value. But `tests/test_metadata_ingest.py` has **no clock fixture** (measured: zero occurrences of `monkeypatch`), unlike `test_metadata_cli.py:76-85` and `test_metadata_e2e.py:85`, so two collections inside one second leave `observed_at` **unchanged** and the "with `observed_at` advanced" Done criterion was unsatisfiable. Task 3 now names the fixture to install and adds the all-`NULL` observation as a third case.

`desc` is a SQL keyword: it stays as upstream's field name (naming discipline), quoted `"desc"` in the DDL and in the plan's SELECT templates. Measured: quoting does **not** change `PRAGMA table_info` (the column still reports as `desc`), so the map entry is unaffected; the reason for quoting is forward-safety, not a repaired failure — SQLite resolves the bare keyword correctly in every shape probed here, including `ORDER BY tid, desc`. No test in the plan is weakened and no assertion is relaxed. -->

<!-- CLEARED(architect, 2026-09-26). **Ruled: `audio_objects.storage_key` holds the root-relative declared string (`audio/<stem>.<ext>`), never an absolute path.** The plan's choice was right and is now argued rather than asserted; recorded as **D14**. Verified against the artifact-root contract (`iter-2026-09-artifact-root/specs/artifact-root-contract.md`):

- **D7** (register `:45`, argued §5) keeps every recorded artifact path — `audio_path`, `srt_path`, `txt_path`, `md_path`, `raw_path` — **artifact-root-relative** "with its shipped shape", and **D12** records the root "**nowhere durable** (no sidecar, no manifest field)". An absolute `storage_key` would write a root into the store durably: the second source of truth D12 exists to forbid, going stale the moment the operator moves `audio/` — and `## Non-Goals` says that `mv` is the operator's own.
- **D8** resolves a recorded path over the ordered base pair, each candidate validated at its own base. An absolute key needs either a **new** resolution rule or one baked-in base — the "cross-root path computation" D8 rejects. Root-relative invents no rule: the value already resolves through `artifact_root.resolve_audio_path`.
- **Hard rejection, not a style preference:** `path_policy._audio_parts` (`:16-29`) refuses an absolute path outright (as it does `..`, a first component other than `audio`, or a length other than 2), so an absolute `storage_key` could not be handed to `confined_audio_path` / `unlink_confined_audio` / `resolve_audio_path` at all.
- **An absolute key would also corrupt the identity half.** `storage_key` is `NOT NULL UNIQUE` (`schema.sql:98`; pinned at `tests/test_storage_schema.py:201`) while `sha256` is the intended identity — so absolute keys split one logical object into two rows the day it is observed under a second root.

**One defect surfaced with the ruling and is landed alongside it.** The plan's stated writer (`INSERT ... ON CONFLICT(sha256) DO NOTHING` followed by `SELECT audio_id ... WHERE sha256 = ?`) cannot satisfy **both** unique constraints. Measured: re-observing the same declared key with changed bytes raises `IntegrityError: UNIQUE constraint failed: audio_objects.storage_key` — which the plan's own "make the call non-fatal to the download" rule would then **swallow**, silently leaving a stale `sha256`/`byte_size` for a file whose bytes changed (and it is precisely the stale-digest case Task 2's `--deep` exists to detect). Measured remedy: an in-place `UPDATE ... WHERE storage_key = ?`, **never** delete-and-reinsert — the `part_audio_objects` foreign key is `RESTRICT` and blocks the delete. Landed in the audio plan (Task 1 Step 1/Step 3, Done criteria) and in `specs/audio-retention-contract.md` §3; plan `AQ1` is closed. This row was **not** Q1's consequence — Q1 is settled as D11 and concerns video metadata, not audio storage keys. -->

<!-- CLEARED(writing-specialist, 2026-09-26). **Both duties discharged.**

**Duty 1 — corpus hygiene on `specs/output-layout-options.md`, plus the §1.3/§3.3 contradiction check.** Reader-facing fixes only, in place; no section added or removed and no measured number touched (268 lines before, 277 after): the abstract now names §2 as the defect the scatter hides and resolves its own `§5 / Decision required` pointer; §1.2's `artifact-root-contract.md` **D13** is disambiguated from this iteration's own D13; the two header-less table families (§2's rule comparison and §4's three target tables) got header rows; §5 gained the **L1↔Q4 / L2↔Q5 / L3↔Q6** label map — the compass names the same slate differently — with L4 marked as having no compass question row; §5 item 4's bare "the compass roadmap" now cites `delivery-compass.md` `## Roadmap Position` item 3; and the method note states which tree each anchor family is relative to (`src/bili_asr/`, package, or repo root). The shape remains **undecided** — D8 leaves it open, Q4-Q6 stay PM/operator-owned.

**Evidence, duty 1.** §1.3's two quotations are verbatim-correct, and §2's defect finding is corroborated by the published source: `README.md:97` leaves `*.md` unquoted, so the shipped prose pins three families to `<stem>` and leaves the md a wildcard — exactly as §1.3 states (PM-verified). No contradiction found between §4/§5 and the promises quoted in §1.3/§3.3: Target C keeps the four-family shape, which is what makes its "no completeness migration" claim hold against `README.md:602-607`, and all three targets stay consistent with the state-stays-at-root promise at `README.md:470-475`. `README.md` and `docs/` prose is **not** contradicted by anything written here — `docs/artifact-root.md` (`:15` family list, `:125` root-relative recorded paths, `:62` accepting the four kind dirs) and `docs/audio-retention-policy.md` (`BILI_KEEP_AUDIO` table) both agree with §1.1/§1.2/§3.1 (PM-checked; `docs/metadata-storage.md:327-342` spot-checked here and also agrees).

**Duty 2 — convergence (added by seat 1): already verified, deliberately not redone.** No document in the package still restates Q1/Q2 as open; `specs/metadata-coverage-contract.md` §3.2/§4 cites **D11**/**D12** (and **D15**) rather than the withdrawn question numbers; and D6's prohibition holds — no "adds persistence" / "adds retention tests" wording in any of the three specs. The only surviving `Q1`/`Q2` mentions are the compass's own convergence record (`:116-117`, `:261-264`), which states them as *converged*, not open.

Nothing re-owned to PM. -->

<!-- PM clearance (registration time, 2026-09-26): re-verified — the control root is on `main` @ `9d530cd` and `git worktree list` shows no non-terminal workflow owning it (`iter-2026-09-qwen3-asr-closeout`'s lease holds `.worktrees/20260924-qwen3-asr-transformers`; this iteration holds none). Both plans' `Main worktree branch: main` fields are correct as written; no backfill needed. -->


## Quality Gate Summary

Corrected at this close: the two rows below previously recorded states that were **not earned** (an external
session had closed both plans). Every claim here was re-verified against the tree.

| plan_id | Review | Delivered | Open residuals (id + severity + tracking) |
|---------|--------|-----------|-------------------------------------------|
| `20260926-video-metadata-enrichment` | L2 Approved per task (T1–T5; T4 twice, two seats) + plan QC tri Approve (0C/0I/2W/6I) | Tasks 1–5 all merged: T1–T3 in `main` via PR #21 `2696711`; T4 `318c0ed`+`9110798`+`2241575`; T5 `b098906`; R3 `7a5c358`; integration `5048de6`, 1699 passed / 123 skipped | **15 open**: R1 (medium — `video_title` unreachable for CSV consumers until the manifest half), R2 (medium — `CREATE VIEW IF NOT EXISTS` silent no-op), R3 (low — **partially closed**; its transcript-projection half is R5), R4 (medium — unattributed external commit+merge on this plan's branch), R5 (low — a third contract, another iteration), R6 (medium — a multi-line `description` costs the whole page), R7 (low — the dead T4 review seat), M-R1/M-R2 (medium — unpaced tag GETs; `GatewayShapeError` fails the page), M-R6–M-R11 (low) |
| `20260926-audio-inventory` | **No independent L2 verdict** (the seat died; the PM authored Task 2 and re-read it adversarially — residual A-R4) | AC 4 + AC 5 hold (`test_storage_queue_writes.py:174-177` 11 passed; `test_audio_retention_policy.py`+`test_audio_reclaim.py` 13 passed / 2 skipped) but were earned by PR #21 `2696711` / PR #24 `662d9ca`, **not** this plan. **AC 6 delivered 2026-09-28**: `678b376`+`bda9465`, 8 tests, end-to-end `recorded=1 already=0 missing=0 unlinked=0` exit 0 | **4 open**: A-R1 (medium — a present-but-unreadable file fits no §3.1 counter; needs a product ruling), A-R2 (low — Task 1's plan text describes an API that never shipped), A-R3 (medium — AC 6 was recorded as met while the command did not exist), A-R4 (medium — the L2 seat is owed). Task 3 remains 0/5, coverage-completeness only |

**Unresolved critical: none.** Blocker-defer: none — no open residual blocks a delivery. **Acceptance
criteria**: AC 1–7 all met; AC 6 and AC 4's evidence pointer were corrected at this close, and an earlier PM
note calling AC 7 unmet was a misreading (AC 7 asks for the *survey*, which exists; the SHAPE DECISION is a
documented operator-owned open item that blocks the unwritten layout plan, not the criterion).

**Honesty notes carried forward**: (a) no arm's-length review of the audio Task 2 exists (A-R4); (b) three L2
review seats across this iteration died silently leaving skeletons, so some verdicts rest on PM reproduction
rather than a reviewer's word — each such case is named in its residual; (c) the unreadable-file branch of the
audio reconciliation was never genuinely exercised (the probe ran as root, which bypasses mode bits), so it is
reasoned and disclosed rather than demonstrated (A-R1).
## Compound Round Summary

Package inventoried per §3.2 step 1 (`{ITERATION_DIR}/iter-2026-09-metadata-audio-layout/**`, compass excluded):
4 `.md` files — `README.md`, `specs/audio-retention-contract.md`, `specs/metadata-coverage-contract.md`,
`specs/output-layout-options.md`.

**Promoted: 3 docs** (each through Phase 2 overlap → Phase 3 Write → Phase 6 index row):

| New doc | Source | Why it cleared Q1–Q8 |
|---|---|---|
| `best-practices/completion-claims-need-live-evidence.md` | This close's own finding (compass AC 6 + the plan row) | Q1,2,3,7,8 — no existing doc covers externally written completion states; the detection method (`git log -S --all` vs the CLI's own subcommand list) is reusable and was decisive twice |
| `architecture-patterns/metadata-delivery-hops-and-schema-evolution.md` | `specs/metadata-coverage-contract.md` §1–§3 | Q2,3,7,8 — `normalized-metadata-stack.md` describes the *layers*; this is the *delivery checklist* across them, plus the measured "a new column is silently absent" rule and the map-by-map pin obligations |
| `architecture-patterns/audio-store-reconciliation.md` | `specs/audio-retention-contract.md` §3–§5 | Q3,4,7,8 — `audio-evidence-queue-contract.md` owns the **write** side; this is the **read** side: the four counters, the identity rule, the measured cost model, the read-only promise |

**Kept as snapshot: 1 doc** — `specs/output-layout-options.md`. Deliberately not promoted: it is a *decision
input* whose decision is still open (Q4–Q6, operator-owned), and `architecture-patterns/artifact-root-split.md`
already owns the root-vs-shape rule it depends on. Promote it once the shape is chosen and the layout plan runs.

**Skipped: 0.** Two candidates were considered and rejected against existing coverage rather than written:
the worktree restore trap (`git checkout HEAD --` vs the index) is already in
`testing-patterns/worktree-test-invocation.md:93`, and the endpoint-spelling lesson is folded into the
metadata delivery doc rather than given its own file (it is one hop's rule, not a standalone pattern).

**CONCEPTS.md**: 1 entry added — **audio object** (identity is *location*, not content), plus a
`Flagged ambiguities` note separating *audio object* from *audio queue*. Table and column names
(`video_details`, `storage_key`) were deliberately **not** added: the vocabulary rules exclude implementation
specifics.

**Catalog**: `mstar catalog register` was **not** run — `{HARNESS_DIR}/store.db` does not exist on this host
(`store.not-initialized`), so there is no catalog to write. The engine here (3.11.2) still enforces the
`{KNOWLEDGE_DIR}/README.md` index row, which is satisfied for all three new docs and verified for all 24 docs in
the directory. Recorded so a later reader does not read the missing catalog row as an omission.

**Trigger compound-refresh**: no.
## Iteration Retrospective (minimal)

- **The dominant failure mode was a claim outliving its evidence.** Twice a completion state was written by a
  session that had not produced the work (compass AC 6 met for a command that did not exist; the audio plan
  `Done` at 0/15). Neither was a lie about the code — each was a pointer nobody resolved. The close gate is what
  asked, and resolving pointers is now the first act of this phase. Captured as
  `best-practices/completion-claims-need-live-evidence.md`.
- **Subagent capacity, not task difficulty, was the binding constraint.** Three L2 review seats died silently
  mid-round (T4's first, T4's re-dispatch, T2's) leaving 330–887-byte skeletons, and one implementer ran out of
  context having written nothing. In every case the PM either re-dispatched with pre-supplied evidence or did
  the adversarial read itself. The mitigations that worked: **write the report skeleton first** (so a death
  leaves a locatable artifact), **pre-supply reconnaissance** in the dispatch (the T4b/Task-2 evidence files),
  and **segregate worktrees per round** — after the PM mis-dispatched a second fix round into the first round's
  worktree, the R4 hazard recurred by PM error, not by any implementer's.
- **A reviewer's stated failure mode can be wrong while its conclusion is right.** The T4 fixture-provenance
  finding claimed deletion would stay green; measured, it went red via a sibling `KeyError`. The implementer
  pushed back with evidence and was right to; the finding was still valid for a different reason (the *value*
  was unasserted). Two T4 seats also produced **different** Importants, so a single-seat review would have
  missed half. Recorded rather than smoothed over.
- **Self-found defects are evidence the review is owed, not that it is unnecessary.** The PM's own adversarial
  re-read of Task 2 found two real defects (a violated cost model; `missing` counting an unreadable file). Both
  are fixed and pinned — and the fact that the author found them is exactly why A-R4 asks for an arm's-length
  read instead of closing on them.
- **Smooth**: the D16 third-state fix, the WIP-interrupted resume, and the serial integration merges (four, no
  conflicts) all closed in one round each. The per-track collision matrix computed before dispatch (T4 ∩ T5 = ∅)
  held exactly.