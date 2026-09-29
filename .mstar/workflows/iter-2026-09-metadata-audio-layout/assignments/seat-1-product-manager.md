# Assignment — Phase 1 Review & Edit chain, seat 1 of 3

**Execute as**: product-manager
**Delegation**: forbidden
**Task category**: docs
**Task budget (implement / ops rounds)**: one editing round over the four files named below, plus the Q1/Q2 rulings. No product-code writes.
**Working branch**: current (no branch switch — Phase 1 chain edits uncommitted docs in the control root; PM commits later on the integration checkout)

---

## Identity / anti-recursion — read first

You are a **leaf executor** (`product-manager`), dispatched by `project-manager`. Load, in this order:

1. `mstar-roles` (hub) → `mstar-roles/references/product-manager.md` → `mstar-roles/references/_shared/leaf-executor-core.md`
2. Skill presets this round: `mstar-phase-gates` (Prepare), `mstar-artifacts` (specs/knowledge)

**NEVER**: invoke `project-manager`; invoke any sibling role (architect, writing-specialist) or any other subagent; delegate any part of this work; use `subagent` / `workflow` tools. You are not `project-manager` and must not self-upgrade to orchestration. Do the work in this session; return a Completion Report. If something is genuinely unanswerable, return `Blocked` with the reason — never invent delegation.

## Context (you cannot see the PM session)

Iteration `iter-2026-09-metadata-audio-layout` — **Phase 1 Review & Edit chain, seat 1 of 3** (product-manager → architect → writing-specialist, sequential; you are first). It answers three operator complaints from 2026-09-26 about a Bilibili ASR transcript-archival CLI (product root `bilibili-asr-archive/`). Registered today; compass is now `status: active`.

### Files you own this round — edit in place

A comments-only report is **not** an acceptable substitute for editing.

- `.mstar/iterations/iter-2026-09-metadata-audio-layout/delivery-compass.md` — read all of it: `## Scope`, `## Decisions` (D1–D10), `## Open Questions` (Q1–Q6), `## Acceptance Criteria`, `## Non-Goals`, `## Milestones`, `## Delivery Branch Policy`.
- `.mstar/plans/20260926-video-metadata-enrichment.md` — video-metadata plan (4 SDD tasks).
- `.mstar/plans/20260926-audio-inventory.md` — audio-inventory plan (3 SDD tasks).
- `.mstar/iterations/iter-2026-09-metadata-audio-layout/specs/` — three specs: `metadata-coverage-contract.md`, `audio-retention-contract.md`, `output-layout-options.md`. Read as needed; `output-layout-options.md` §4–5 is the layout decision material.

### Direction decisions already made — do not relitigate

Full D1–D10 live in compass `## Decisions`; the ones binding your product calls:

- **D2** — metadata scope is the **high-value set** (video title onto the artifact, uploader name, tags, category, cover), *not* the whole 45-key `view` response.
- **D5** — frontmatter `title` keeps meaning the *part* title; the video title is a new sibling key `video_title` (additive, never a redefinition).
- **D6** — audio retention is **already** the shipped default (`KEEP_AUDIO_DEFAULT = True`) and **already tested** (`tests/test_audio_retention_policy.py`, 4 cases). The real gaps are a missing inventory plus two narrow coverage holes. No doc in this package may claim the iteration "adds persistence" or "adds retention tests" — both would be false.
- **D8** — the layout target shape is **deliberately undecided**; the survey is the deliverable.
- **D3/D7** — new video facts go in **child tables** (`video_tags`, `video_details`), never widened columns (measured: `CREATE ... IF NOT EXISTS` means a new column is silently absent on existing DBs); the audio inventory uses the already-declared `audio_objects` / `part_audio_objects`.

### Open questions — Q1 and Q2 are YOURS to disposition

- **Q1** (owner: you, `Blocking? No`) — should the archive freeze video metadata as a **point-in-time snapshot**, or is refresh-on-recollect acceptable? This decides whether a future `stat` addition needs a timestamped child table. Today's plans sidestep it by storing only slowly-changing fields.
- **Q2** (owner: you, `Blocking? No`) — should a stored cover URL survive `export`? `export.py:175-177` replaces any value starting `http(s)://` with `[redacted]`; `:63` drops keys ending `_url`; `:48` lists `cover_url` exactly — so a stored cover is invisible in an export **by design**. The column was named `pic` to work within that existing rule. Changing the rule is a policy call, not a code fact.

Disposition each by **either** converging it into a `## Decisions` row (D11, D12 — needs `decision` + `rationale` + `source`; cite the user's 2026-09-26 instruction where one applies, otherwise state it as your product ruling and mark the source as such), **or** re-owning it to `PM` explicitly with the reason written into the row. Both are non-blocking, so neither may block `status: locked` — but neither may be silently deleted.

### Your markers — clearance duty

Two markers in the compass (around lines 238 and 240) are owned by you:

```
<!-- TODO(owner: product-manager): decide and record Q1 (point-in-time metadata snapshot vs refresh-on-recollect) and Q2 (whether a stored cover URL should survive export); both change what the metadata plan may promise, and neither is answerable from code alone. -->
<!-- TODO(owner: product-manager): confirm the metadata scope in D2 is the priority order the operator wants if the two plans cannot both fit the iteration's capacity — the audio inventory is the smaller change but the metadata plan is the one the operator named first. -->
```

You **must** clear every marker whose owner is `product-manager`. A marker you cannot clear must be **re-owned to `PM`** before you finish, with the reason written into it. Report both counts: **cleared N / re-owned M**.

## What to produce

1. Your rulings on Q1 and Q2, landed as compass `## Decisions` rows (or explicit PM re-ownership), **with the consequence written where it actually bites** — e.g. if Q1 rules that refresh-on-recollect is acceptable, say so in the plan's scope so a later reader cannot infer a snapshot guarantee from the stored grain.
2. Priority-order confirmation for D2 (marker 2): state the order explicitly in the compass, and if capacity can fit only one plan, name which gives way. The operator named metadata first; the audio inventory is the smaller change. Make the call and write it down.
3. Product-facing edits to both plans: their acceptance criteria must be checkable by a reader who did not watch the investigation, and nothing may promise behaviour the code does not have (see D6).
4. **Do not add anything to `{KNOWLEDGE_DIR}`** — forbidden in the start chain. Compass / plans / specs / iteration package only.

Stay inside `.mstar/iterations/iter-2026-09-metadata-audio-layout/` and `.mstar/plans/20260926-*.md`. Do not touch product code under `bilibili-asr-archive/`, do not commit, do not switch branches.

## Return shape

A compact Completion Report, not a narrative. Emit these fields **after** the `## Report` heading below so they are not parsed as Assignment header fields:

- **Verdict**: `Done` | `Blocked`
- **Files edited**: path → what changed (one line each)
- **Marker clearance**: cleared N / re-owned M, with ids
- **Q1 / Q2 disposition**: converged (as D__) or re-owned to PM — one line each, stating the ruling itself
- **D2 priority order**: the order you recorded
- **Blocked on** (if any): the exact missing input

**Budget**: one editing round over the four files above; stop once the marker list is empty for your role and Q1/Q2 are dispositioned. Do not re-sweep the wider repository — the reconnaissance this package rests on is already recorded inside it.

## Report
