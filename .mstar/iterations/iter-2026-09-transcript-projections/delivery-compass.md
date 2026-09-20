---
iteration_id: iter-2026-09-transcript-projections
start_date: 2026-09-20
status: locked
iteration_base_branch: main
target_branch: main
plans: [20260920-transcript-projections]
---

# iter-2026-09-transcript-projections Delivery Compass

> **For agentic workers:** this compass is the context carrier for the Phase-1 review-and-edit chain.
> Dispatched roles cannot see the PM's session; they read this file, the plan files and this package.
> Every gap that is deliberately left coarse carries a marker with an explicit owner; the marker syntax is
> defined in `mstar-iteration/references/phase-1-prepare.md` §1.3(iii) and nowhere else — it is not
> restated here. The three-role chain has closed with **no chain-owned marker left**; the only open items
> are the two non-blocking questions whose owner is `PM` (`## Open Questions`).

## Scope

Close the **remaining piece of the medium charter row `e2e-23191782-season-7686105 · R1`**: the
**SRT/TXT/MD projection rebuild**. Today the caption path stores a transcript in `archive.db` and
**produces no products at all** — `harvest-subs` writes segments to the store and nothing else, and
no shipped command can turn a stored transcript into an archive bundle. The consequence was measured
on a live host on 2026-09-20: with AI captions available for both E2E items, the chain took its
documented "subtitles first" branch, the audio queue correctly excluded them, and **not one row could
reach `archived`** (`e2e-23191782-longform-pair-webdav` report §R2-A3/A4/A5/A6/A8). The product can
collect text it cannot publish.

In scope — each entry is a promise about what an operator can do after this iteration that they
cannot do now:

1. **One command turns a stored transcript into a complete archive bundle** — for a part whose
   transcript is already in `archive.db`, an operator runs `bili-asr publish-transcripts` and gets the
   four artifact families (`srt`, `txt`, `md`, `raw`) plus the bundle marker under the archive's
   configured artifact root, with the row recorded in the manifest so the archive's own readers agree
   it is done. Command name, selector surface, printed summary and exit stance are **D10**; the identity,
   frontmatter and raw-sidecar contract are **D11** (contract §3–§4); the recorded state is **D12**
   (contract §5).
   Check: `## Acceptance Criteria` 1–3.
2. **Projection is idempotent and never disturbs what the chain already published** — a second run
   changes nothing; a row whose bundle the chain completed is left alone; nothing is written back into
   the store. **Range** (D3, said out loud because the sentence is otherwise wider than the mechanism):
   "left alone" ranges over a bundle the archive's own completeness reader (`archive_bundle_complete`)
   counts complete; a bundle that reader does not count — a publication interrupted before the marker,
   or a marker whose hashes disagree with the files — is published again, which is how such a row heals
   (D10d, criterion 2). Nothing in this promise reacts to the store gaining a newer transcript version
   after a bundle was published: the next-version drift non-goal holds that line and criterion 6 checks
   that it is disclosed.
   Check: `## Acceptance Criteria` 2.
3. **The published GPU self-check works from any working directory** (folded in from the E2E's
   finding F4 / register row `e2e-23191782-longform-pair-webdav · R1`): `check-asr-env` currently
   anchors its helper at `parents[3]` (the repository root, which has no `scripts/`) instead of the
   package root, so it exits 1 with `no check script found` from anywhere but the product root.
   Check: `## Acceptance Criteria` 5.

**Evidence of the gap, at file:line, from the 2026-09-20 E2E run:** `coordinator.py`'s archive stage
reads segments from the file system and skips with `missing_subtitle_raw` when they are absent; the
SQLite caption path writes no projection (`services/subtitle_ingest.py`); `write_archive()`
(`archive.py:452`) needs an `entry` dict plus a `segments` list and publishes the four families
through `_publish_bundle`; the store's `transcript_segments` holds `start_ms`/`end_ms`/`text` and
**no `confidence` column**, and the `transcripts` row carries `source_kind`
(`subtitle-ai`/`subtitle-cc`/`asr-local`), `language`, `version` and `content_sha256`. Nothing
bridges those two shapes today.

Chosen shape (user-locked, see `## Decisions` D1/D2): **a new command that projects stored
transcripts into archive bundles and records the resulting state**; the ASR/audio chain and its
manifest contract are not restructured.

**The iteration-level contract is [`specs/transcript-projection-contract.md`](specs/transcript-projection-contract.md)** — the plan's declared `primary_spec`, written and sealed by the architect round. Every claim in this compass cites it by section:

| Contract section | What a compass claim rests on it for |
|---|---|
| §2 candidates | D10b's membership rule (every stored part holding a transcript, whatever its `processing_status`), the locked candidate order, the selector and what "unknown `--bvid`" means |
| §3 identity + winner rule | the stem (`{bvid}.p{page_index}`), which stored transcript wins when a part has several, the ms→s conversion, `duration_s`/`pubdate_str` |
| §4 frontmatter + sidecar | the exact nine frontmatter keys, the deliberate omissions (criterion 4), the `raw` sidecar shape |
| §5 recorded state | the `archived` row and its key set, the `already_published` predicate, the half-written-bundle path, the readers' agreement (criterion 3) |
| §6 `asr-local` | D13's "in range, provenance deferred" answer |
| §7 operator surface | D10 restated where a mechanism is needed (printed lines, exit stance, `--help` content, the writer lock) |
| §8 modules / interfaces / readers | which module composes what, and the blast radius on the readers |
| §9 risks + rollback · §10 validation plan | the fixture shape (Fixture F, its five states and its `attempts.jsonl`), the pinned invocation, the named cases per task |
| §11 disclosures · §12 F4 · §13 frozen spec | what the published surfaces must carry, the `check-asr-env` anchor fix (criterion 5), and the revision `{SPECS_DIR}/asr-archive-cli.md` owes (PM-owned) |
| §14 deferrals | the non-goals that are tracked rather than assumed |

## Decisions

| # | Decision | Rationale | Source |
|---|----------|-----------|--------|
| D1 | **Scope = the projection rebuild (charter piece 2) + the folded-in F4 fix.** Nothing else enters this iteration. | The register names this as the next iteration's first item with trigger "the previous iteration's close"; the 2026-09-20 E2E then measured the consequence directly — captions are now served upstream (both items), so the caption path is the path reality takes, and without a projection it publishes nothing. | user instruction (2026-09-20) |
| D2 | **Route = a new command that projects stored transcripts into the archive bundle; the chain and its manifest contract are not restructured.** `coordinator.py`, `audio.py`, `asr.py` keep reading the manifest; the projection composes in `cli.py` like every other command (the repo's cross-layer rule), reads the store, publishes through the existing archive writer. | Same shape as the bridge that closed piece 1 (`derive-manifest`), which the register's own text calls the cheapest unblocking slice; it keeps the "which store is SSOT" question outside a projection, and it makes a later deletion (not rewrite) the way to change that answer. | user instruction (2026-09-20); queue-bridge compass D2 (continuity) |
| D3 | **Projection is additive and idempotent; the store is read-only for it.** Re-running changes nothing; a bundle the chain published is never rewritten; no manifest state is written back into `archive.db`. | Mirrors the bridge's conflict policy (`queue-derivation-bridge`) so the two halves of the boundary behave the same way, and keeps the "no back-write of an inferred truth" rule (`operational-sidecars.md`) structurally true rather than conventional. | PM (continuity with D2/queue-bridge D4/D8); mechanism fixed by the `architect` round in D11/D12 |
| D4 | **Branch policy: `iteration_base_branch` = `main`, `spec_integration_branch` = `iteration/iter-2026-09-transcript-projections`, `target_branch` = `main`.** | Repo `AGENTS.md`: "Default integration / PR target: `main`; Feature work: plan branches merging into `iteration/<iteration-id>`". Identical to the four preceding iterations — a written project convention, not a silent default. | project convention (AGENTS.md) |
| D5 | **Verification is fixture-based inside this iteration; the real-device re-run is a separate E2E workflow.** No scenario of this iteration depends on the GPU host, and no acceptance criterion is satisfied by a real-device run. | `mstar-harness-core` § 定向执行与验证边界: real-device/E2E verification is never a development plan's task or gate. The user authorised the live re-run as a **separate** workflow after delivery (2026-09-20). | user instruction (2026-09-20); skill contract |
| D6 | **The F4 fix is in scope as a small work item of this iteration's plan** (one anchor plus a test that runs the command from a cwd other than the product root). | The plan already touches `cli.py`, which is exactly the trigger register row `e2e-23191782-longform-pair-webdav · R1` records; leaving it for "the next plan that touches `cli.py`" would be the same plan. | user instruction (2026-09-20); register row R1's `target` |
| D7 | **Phase 1 writes no `{KNOWLEDGE_DIR}`.** Iteration-level specs and guides land in this package; promotion happens at iteration-close via `mstar-compound`. | `mstar-iteration` §1.5.5 and §1.6 (the start chain must not add knowledge). | skill contract |
| D8 | **The store's caption kinds are the first-class input; `asr-local` is decided, not assumed.** No command writes an `asr-local` transcript today, so the iteration must state explicitly whether the projection handles that kind now or defers it. | `transcripts.source_kind` already allows `asr-local` and the content-uniqueness index hands its identity rule to a later iteration; deciding it here avoids a third iteration discovering the hole again. | PM (carried from queue-bridge D5); resolution owner `architect` round (D13) |
| D9 | **Engine lifecycle writes are hand-written to the frozen contract's schema and validated with the engine's own validator before being treated as landed** (`validateWorkflowSnapshot` / `validateWorkflowEntry` / `validateResidual`), because no `mstar` CLI is installed on the control host. A transition is never claimed from prose alone. | The CLI is the engine's authorised producer; without it the alternative is either a prose-only claim (unacceptable — it is how the two 2026-09-19 closes wrote terminal snapshots the engine then refused, register row `iter-2026-09-artifact-root · R4`) or a schema-checked hand write. Installing `@mstar-harness/cli` (npm, 3.11.2 available) would remove the substitution; that is an operator decision and is not required for correctness, only for provenance. | PM (environment constraint, 2026-09-20); engine validator evidence recorded per transition |
| D10 | **Q1 converged — the projection's operator surface is one new command and it adds no exit value: `bili-asr publish-transcripts [--bvid <bvid[:pN]>] [--limit-parts N] [--archive-root <root>] [--artifact-root <root>]`.** **(a) Name** `publish-transcripts`. **(b) Range** — with no selector, **every stored part that holds a transcript, whatever its `processing_status`** (a `gone` part still holds local text; `gone` describes upstream availability, not the store's contents); `--bvid <bvid[:pN]>` follows the shipped `_subtitle_selector` rule (bare `bvid` = every stored part of that video, `bvid:pN` = exactly that part) and an unknown selector is the configuration error `publish-transcripts: unknown --bvid <value>`, exit 1; `--limit-parts N` bounds the run in **parts** (a non-positive value is exit 1, as in `probe-subs`). **(c) Prints** — one line per candidate in a deterministic order: `<work_id>: published (source=<kind> lang=<language> version=<v> cues=<n>) <md path>`, `<work_id>: already_published`, or `<work_id>: failed (<reason>)`; then `publish-transcripts: candidates=<n> published=<n> already_published=<n> failed=<n>`, every count including the zeros. **(d) Exit stance** — `0` when every candidate is published or already published, **including the case of no candidate at all**; `1` when the command cannot keep its promise (a usage/configuration error, a refused archive state, or a candidate whose bundle could not be published — that part is named and the summary line still prints); **`2` is not produced by this command.** The command carries `--artifact-root` like the other product-writing commands (flag wins over `BILI_ARTIFACT_ROOT`; unset = the archive root), opens no socket, and its printed paths are the root-relative form the archive already records. | **(a) Naming** (via the `naming-analyzer` skill, against the shipped family `fetch-meta` / `probe-subs` / `harvest-subs` / `derive-manifest` / `download-audio`): *publish* is already this repository's word for exactly this act — the archive writer publishes a bundle and `README.md:541` says the marker is "published last" — and *transcripts* is the noun the store itself uses, so `harvest-subs` stores a transcript and `publish-transcripts` takes it out. **Rejected**: `project-transcripts` / `rebuild-projections` — in this repo *projection* is the established word for a **read-only derived view** (`sidecar_projection.py`'s own docstring, `coverage` called "an inspection projection"), so a *writing* command named with it would read as an inspection command, and "rebuild" is false of the additive behaviour D3 fixes (the command never rebuilds a completed bundle); `emit-transcripts` names no destination, `publish-bundles` names the writer's internal unit rather than the object the operator has. **(b) The rejected default** was "all pending parts": *pending* is the store's own word for "holds no transcript" (`v_pending_subtitles`, which is exactly `derive-manifest`'s queue), so reusing it for "holds a transcript and no bundle" would promise the 61 captionless parts of the 2026-09-20 store a product this command can never make — their route is the audio chain (the captionless-remainder non-goal). `gone` stays in the range because excluding it would withhold products the store already holds; the recorded *state* for such a row is D12's, not this decision's. `--limit-parts` rather than `--limit` is unit honesty: the two store-side part-ranged commands use `--limit-parts`, while `--limit` in this family counts manifest rows/videos (`download-audio`, `asr`). **(c)** The per-row identity is what criterion 4 needs (the source must be named truthfully, and criterion 1 needs the operator to see the four families' paths); the `md` path is printed because it is the one product name the store cannot derive — it carries the date and the title — and the closing counts line follows `derive-manifest`'s shipped form, which prints every count including the zeros. **(d)** "Empty is success" follows the bridge's own precedent (`cli.py:1098-1100`); exit 1 already carries "the promise was not kept" in the shipped readers (`verify --trusted-local` exits 1 on defects, `coverage` exits 1 with `artifact_missing`), so no fourth meaning is invented; exit 2 stays reserved for terminal API failure (risk-control ceiling or exhausted retries), it is unreachable for a command that opens no socket, and usage errors are already mapped to 1 by `_UsageErrorArgumentParser`. **Consequence the plan carries**: the "publish the boundary" task publishes this surface (name, range, limits) in the command's `--help` and the README boundary bullet, and criterion 6 checks it there. | product-manager (Q1 convergence, this round; naming analysed with the `naming-analyzer` skill over the shipped command family; `_subtitle_selector` rule `cli.py:805-821`; `derive-manifest` summary and append-failure form `cli.py:1223-1246`; empty-queue-as-success `cli.py:1098-1100`; exit taxonomy `{SPECS_DIR}/asr-archive-cli.md:108-112`; usage-error mapping `cli.py:83-90`; `--artifact-root` convention `{SPECS_DIR}/asr-archive-cli.md:42-49`; root-relative recorded paths `{KNOWLEDGE_DIR}/architecture-patterns/artifact-root-split.md`) |
| D11 | **Q2 converged — the content contract is fixed by the iteration contract §3–§4.** One bundle per stored **part** (stem `{bvid}.p{page_index}`, the writer's own `archive_stem` rule, `archive.py:34-38`); the winning transcript is the minimum over *(source-kind rank: `subtitle-cc` → `subtitle-ai` → `asr-local`, language family rank `zh` → `en` → other, language code, `version` DESC)* — the harvester's own caption preference (`subtitle_ingest.py:140-143`, `:162`, `:164-171`) read off stored columns, total by the store's `UNIQUE (video_part_id, source_kind, language, version)` (`schema-transcripts.sql:25`); `start_ms`/`end_ms` are divided by 1000 once into the writer's `segments` shape (`/1000` exactly, so the SRT round-trips the stored milliseconds); the `raw` sidecar is the writer's own synthesis `{"segments", "source"}` because the store has no `lan`/`lan_doc` (`archive.py:481-484`); the frontmatter carries **exactly nine keys** (`bvid`, `title`, `date`, `duration_s`, `source`, `url`, `work_id`, `page_index`, `cid`) and **deliberately omits** every `asr_*`/`confidence` key — the omission is structural (no `confidence` column, the VAD/capture summary is emitted only when `source == "asr"`, `asr_provenance` is not passed), never zero-filled or guessed. | The mapping must fit the tables as they are (compass `## Non-Goals`: no schema change), so every key the bundle carries is a store fact or a rendering of one; criterion 4 checks the omission by inversion. | architect round 2026-09-20; contract §3–§4 |
| D12 | **Q3 converged — the projection records `status: archived` plus the four root-relative `*_path` keys and the winner's `source`/`language`, through `ManifestStore.upsert`; the store is untouched (`mode=ro`).** `archived` is the state the chain itself writes after `write_archive` + a successful `archive_bundle_complete` (`coordinator.py:501-518`, `:520-527`); `subtitle_done` is **structurally excluded** (the reader demands `subtitles/raw/{stem}.json` and would report `missing_raw_subtitle`, `integrity.py:370-380`); `asr_done` would assert ASR work that was not done. Idempotency **is** the record: a candidate is `already_published` iff its effective row declares all four paths and `archive_bundle_complete` confirms them at the **write base** — then nothing at all is written; a bundle that reader does not count complete (a missing or disagreeing marker, an interrupted publication, or products with no row) is published again, which is how such a row heals, and a stale `.archive-bundle-stage` makes that candidate `failed` with exit 1 (D10d). A later stored version changes nothing: the next-version drift non-goal. | It is the only status both true of a published bundle and accepted as *done* by the readers (`integrity.py:385` excludes it from `retryable_incomplete`; `coordinator.py:45` makes it terminal, so the chain never re-processes the row), and it makes D3's "never rewrites" structural instead of conventional. | architect round 2026-09-20; contract §5 |
| D13 | **Q4 converged — `asr-local` is in range, and its identity/provenance rule is explicitly deferred.** The candidate relation is **not** filtered by `source_kind` (D10b's membership rule is "holds a transcript", and filtering would silently narrow it); the mapping is kind-agnostic because the writer's `source` is the stored `source_kind` verbatim. No shipped command can write such a row: the one transcript writer validates against `ALLOWED_CAPTION_SOURCE_KINDS = ALLOWED_SOURCE_KINDS - {"asr-local"}` (`storage/models.py:471-476`, used at `database.py:885-889`). The deferred half is **named**: the per-model/run identity rule (`schema-transcripts.sql:30-35`, already handed to the audio/ASR iteration by the queue-bridge contract §6) and the `model_id` → `asr_*` provenance mapping — the writer's `asr_provenance` seam exists (`archive.py:452`, `:476-477`), so carrying provenance later is passing an argument, not changing the bundle layout. Until then an `asr-local` bundle would carry `source: "asr-local"` and no `asr_*` keys; that gap is disclosed. | D8 requires an explicit answer; this one keeps D10's range literally true without half-building a provenance mapping for rows no producer exists to create. | architect round 2026-09-20; contract §6 |
| D14 | **Q5 converged — the documents that move are the two T6 files, and two claims outside that bound are reassigned to `PM`.** In `bilibili-asr-archive/README.md`: `:341-342` ("no SRT/TXT/MD projection is rebuilt from them"), `:1010` ("Rebuilding the SRT/TXT/MD projections from the stored transcripts is still deferred work for a later iteration"), `:1049` ("or rebuild the SRT/TXT/MD projections from the stored transcripts"), `:1090-1096` ("the SRT/TXT/MD projection rebuild stays out of this iteration"), and — a count T6 does not name — `:374`'s "**eleven** commands that resolve an artifact path", which is twelve once this command carries `--artifact-root` (the block above it, `:348-371`, is the list that sentence counts). In `bilibili-asr-archive/docs/metadata-storage.md`: `:318-321` ("still deferred: rebuilding the SRT/TXT/MD projections from the stored transcripts") and `:331` ("Neither subtitle command writes an on-disk projection of the transcript: no `subtitles/raw/*.json` and no `transcripts/srt/*.srt`" — true of the two subtitle commands, and it must not be left reading as a global absence claim). **Outside the T6 bound, reassigned to `PM`:** `bilibili-asr-archive/docs/artifact-root.md:89-103` (the same count, `十一个`, and the same eleven-command list that D10 makes twelve — its "six commands without the flag" line stays true) and `{SPECS_DIR}/asr-archive-cli.md:42-45` (the added-command enumeration and the "**11** commands" count, contract §13). **Not in the set:** the `asr --pending` clause in `README.md:341-342` (D2 leaves the chain untouched, so it stays true) and the new command's own surface (§7's `--help`, T4's). | The three files are the surfaces an operator reads — the README entry point, the metadata-storage boundary section, and the flag's own guide — and every sentence listed is a claim the shipped command falsifies; a documentation task bounded to two files cannot leave the third false, so that claim and the frozen spec's are the PM's to bound and to sign (Q6/Q7, both non-blocking). The knowledge doc carrying the same deferral (`{KNOWLEDGE_DIR}/architecture-patterns/bilibili-asr-archive-cli.md:243-255`) is outside this chain's write scope (D7) and is compound's at iteration-close. | writing-specialist round 2026-09-20 — claim search over the published surfaces at HEAD; the two-file bound is T6 / contract §11; Q5 |
| D15 | **Q6/Q7 resolved by the PM — the published surface moves as one set, and the frozen spec's owed revision is authorised now.** T6's bound widens from two files to four: `bilibili-asr-archive/README.md` and `bilibili-asr-archive/docs/metadata-storage.md` (already in), **plus** `bilibili-asr-archive/docs/artifact-root.md` and **`{SPECS_DIR}/asr-archive-cli.md`**. The frozen spec's change policy requires a revision plus PM sign-off for a requirement change; the sign-off is given here, scoped to exactly two mechanical facts its own text now contradicts: the added-command enumeration (`:42-44`) and the `--artifact-root` command count (`:45`, `eleven` → `twelve`, with `derive-manifest` and `publish-transcripts` both named). No exit-taxonomy line, no requirement text and no behaviour is touched. | Three of the four files carry the *same* stale claim (the count and the eleven-command list) and the fourth omits a command that ships; the previous iteration left the same debt owed, and a frozen document that contradicts the shipped CLI is precisely the defect class this repository keeps a best practice about. Fixing one copy and leaving the others is how the class survives a review round. | PM sign-off (frozen spec change policy) + D14's own finding that the count appears in three copies |

## Open Questions

| # | Question | Owner | Blocking? |
|---|----------|-------|-----------|
| — | **None.** Q6 and Q7 were the residue this table was allowed to carry past the lock; the PM resolved both by **D15** before locking (widened documentation bound + authorised frozen-spec revision), so no open row crosses the lock. | — | — |

**Q1–Q5 are closed, and none is left behind as a marker.** Q1 was converged by the product-manager round into
**D10**; Q2/Q3/Q4 by the architect round into **D11/D12/D13**; **Q5 by this round into D14** — all five are
withdrawn from this table, disclosed rather than silently deleted: the operator surface is D10's and is carried
as the plan's `## Operator surface (product)`; the content contract is D11 + contract §3–§4; the recorded state
is D12 + contract §5; `asr-local` is D13 + contract §6; the documents that move are D14. The two rows the writing round left (Q6/Q7) were §1.3(v)'s permitted residue — non-blocking, owner `PM` — and the PM
resolved both into **D15** at the lock rather than carrying them forward. With rows 1–2 of `## Phase 1 review chain` no longer quoting marker text, **no chain-owned
marker remains in this compass, the plan, the contract or the package index**: the marker count at this point is
zero active, two `PM`-owned open rows.

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| `20260920-transcript-projections` | Project stored transcripts into archive bundles (and fix the `check-asr-env` anchor) | Todo | The iteration's single business plan: `{PLAN_DIR}/20260920-transcript-projections.md` — `Execution: mstar-sdd`, `QA gate: mandatory`/`targeted`. Contract: `specs/transcript-projection-contract.md` (written by the `architect` in this chain). |

**Plan split confirmed, and the contract it points at is declared.** The plan is **one** plan with **one**
business deliverable (the projection) and the folded-in F4 fix as its own small task; the
`architect` round authored the decomposition in `{PLAN_DIR}/20260920-transcript-projections.md` `## Tasks` —
**T1** `archive.bundle_paths` (the bundle-name rule's one home), **T2** the repository read, **T3** the pure
projection service, **T4** the `publish-transcripts` command, **T5** the readers' agreement fixture (criteria
1–4), **T6** publishing the boundary in `README.md` + `docs/metadata-storage.md` (the files D14 leaves to T6;
the third claim set D14 names, `docs/artifact-root.md`, is outside the bound and PM-owned — Q7),
**T7** the F4 anchor fix (criterion 5). Its `primary_spec` is
`{ITERATION_DIR}/iter-2026-09-transcript-projections/specs/transcript-projection-contract.md`. No task or gate
depends on a real-device run (D5); the dependency waves, exact file lists and verification selectors live in the
plan.

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Spec freeze (Phase 1 lock) | 2026-09-20 | chain closed — round 3 (`writing-specialist`) landed; `status: locked` is the PM's, on the two `PM`-owned rows above |
| Dev complete (plan Done) | 2026-09-20 | pending |
| QC + QA gate | 2026-09-20 | pending |
| Iteration close (compound + index + roadmap) | 2026-09-20 | pending |
| PR delivery → merge-ready | 2026-09-20 | pending |
| Separate E2E workflow re-running the live pair (user-authorised, not part of this iteration) | after delivery | pending |

## Acceptance Criteria

Each criterion is third-party checkable: it names the command an operator runs, the exit code, and the
line or state that proves it — none rests on the code looking right. Where a criterion needs a value the
contract fixes (identity/stem, frontmatter keys, the recorded status), it says so: the expected value is
the contract's (D11/D12), never invented here.

**Fixture F** (criteria 1–4): a disposable archive root (a temp dir — never a real `archive/`) built
through the shipping commands or from a checked-in fixture, whose `archive.db` and artifact tree hold the
five states the criteria discriminate: **(i)** a part holding a `subtitle-ai` transcript and no bundle;
**(ii)** a part whose bundle the chain archived normally (the idempotency control); **(iii)** a part whose
bundle was published and whose store then gained a **second transcript version** (the drift case);
**(iv)** a part whose publication was interrupted before the marker (a half-written bundle); **(v)** a part
whose `processing_status` is `gone` and which nonetheless holds a transcript. Checks run offline against F;
criterion 5's check is separate (the `check-asr-env` cwd sweep). **F's `manifest.jsonl` holds at most one
row per `work_id`** — the append-only-history shape belongs to the readers' own open defect
(`e2e-23191782-season-7686105 · R2`, high), which criterion 3 deliberately stays outside (see the
readers' append-only-history non-goal). **Two further properties of F are what make criteria 1 and 3
satisfiable at all**, both fixed by the contract (§5.3, §10): F holds an **empty
`F/coordinator/attempts.jsonl`** (`verify` exits `0` only when `defects` *and* `diagnostics` are empty, and a
manifest without that sidecar raises `missing_attempts_sidecar`, `integrity.py:314-328`, `cli.py:3328` — the
projection writes no attempts record, that ledger is chain stage evidence), and its caption body carries **no
advisory content code**, so criterion 3's literal `reasons: []` holds (`coverage --quality`'s JSON `reasons`
is the defect ∪ advisory union, `cli.py:1564-1567`; validity reads the defect list alone, `cli.py:1578`).

1. **A stored transcript becomes a complete bundle.** Operator runs
   `bili-asr publish-transcripts --archive-root <F> --bvid <part>` → exit `0`. Observable: the line
   `<work_id>: published (source=<kind> lang=<language> version=<v> cues=<n>) <md path>`, the closing line
   `publish-transcripts: candidates=1 published=1 already_published=0 failed=0`, the four families present
   under the write base (`--artifact-root` when given, else the archive root) at the
   `transcripts/{srt,txt,md,raw}/` paths for that part, and the `.bundle-ready` marker beside the `srt`.
   The archive's own reader then counts them, not a bespoke probe:
   `bili-asr verify --trusted-local --archive-root <F>` exits `0` with `defect_count: 0` and that `work_id`
   absent from `defects` (run in full under criterion 3). The exact stem/title forms, and which stored
   identity wins when a part holds more than one, are the contract's (D11) — this criterion checks that the
   four families plus the marker exist for the selected part and that the shipped reader reads them.
2. **Projection is idempotent and never rewrites a completed bundle.** Operator runs the same command
   twice against F and compares `sha256sum` of the four families and the marker after each run, plus the
   store's `transcripts` / `transcript_segments` row counts and `content_sha256` values. Run 1: exit `0`
   with `published=<n>`. Run 2: exit `0` with `published=0 already_published=<n> failed=0`, every hash
   identical, and the store counts and hashes unchanged (the connection the command opens is read-only).
   On **(ii)** nothing moves at all — the row prints `already_published` and its four files and marker stay
   byte-identical. **Range of "never rewrites"** (D3): a bundle the archive's completeness reader counts
   complete; **(iv)** is published instead, which is how such a row heals (the writer invalidates the
   marker before replacing and writes it last) — or, when the writer's own staging guard refuses (a stale
   `.archive-bundle-stage` left by the interrupted attempt, `archive.py:228-230`), that part prints
   `failed` and the run exits `1` (D10d). On **(iii)** the run still prints `already_published` and the
   published bytes stay identical: a store that gained a newer version after publication is the
   next-version drift non-goal, and criterion 6 checks that its limit is disclosed.
3. **The archive's own readers agree the row is done.** After criterion 1's run:
   `bili-asr verify --trusted-local --archive-root <F>` → exit `0` with `defect_count: 0` and the projected
   `work_id` absent from `defects` (this is the reader that recomputes the marker's per-family `sha256`
   through `archive_bundle_complete`, `integrity.py:357` — so integrity, not a bespoke four-way probe, is
   what the operator's check runs); `bili-asr coverage --archive-root <F> --quality --format json` → the
   projected row's entry carries `reasons: []` (not `artifact_missing`), `artifact_count: 4` and a non-zero
   `cue_count`, and `summary.valid_work_items` includes it; and `bili-asr derive-manifest --archive-root <F>`
   prints the same `queue=<n>` as before the projection and exits `0` — the derived queue is the no-transcript
   relation, so this check proves the projection appended nothing the derivation reads as its own. The
   recorded manifest status the row carries is the contract's (D12). The two readers' own exit codes are
   unchanged by this iteration (the no-new-exit-code non-goal) and are not part of this criterion beyond
   `verify`'s `0` above —
   `coverage`'s exit code is its own, and on a manifest with more than one row per `work_id` that reader is
   already broken for reasons this iteration does not touch (the readers' append-only-history non-goal), which
   is why F is built with one row per `work_id`.
4. **The published bundle claims no more than the store knows.** Operator reads the two files the run wrote
   — the `md` frontmatter block and the `raw` sidecar in F's `transcripts/md|raw/` — and compares them
   against the contract's key list (D11). Observable: `rg -n '^\s*(asr_|confidence)' <published md>` (and the
   corresponding read of the sidecar's keys) returns **no match** — the check inverts the code deliberately,
   because `rg` exits `1` when nothing matches and the pass is the absence of a match — and the frontmatter's
   `source:` value equals the row's stored `source_kind` verbatim, the same identity the summary line prints.
   Keys a caption cannot support (ASR model/revision/VAD/capture keys, per-segment confidence) are
   **absent**, never zero-filled or guessed. The expected key set is the contract's; what is checked here is
   that nothing outside it appears and that the source is named truthfully.
5. **`check-asr-env` is cwd-independent (F4).** Operator runs `bili-asr check-asr-env` from three cwds —
   the package root, the repository root, and a neutral temporary directory. Observable: the same outcome
   from all three, with the failing stage named when a stage fails (exit `0` with `check: device ok …` +
   `asr-env: verified` on a host that carries the GPU stack; exit `1` naming the failing stage on a host
   that does not) and **never** the pre-fix `no check script found` failure that today comes from the two
   cwds that are not the product root. The command's own exit contract is unchanged — D6 fixes this item to
   the anchor plus one test, and the no-new-exit-code non-goal forbids widening it. Evidence: a test runs it from a cwd other
   than the package root and fails on the pre-fix anchor.
6. **The bound is stated where an operator reads it.** Three checks, each with its own observable:
   (a) `bili-asr publish-transcripts --help` exits `0`, and its text names the command's range — it
   publishes stored transcripts and fetches nothing — together with the two limits this iteration discloses
   (a published product is never replaced by a newer stored version; a row that already carries an earlier
   manifest state is outside what the archive's readers currently agree on, the readers'
   append-only-history non-goal);
   (b) `rg -n 'publish-transcripts' bilibili-asr-archive/README.md bilibili-asr-archive/docs/metadata-storage.md`
   exits `0`, and the matched lines are the boundary text the plan's documentation task owns (D14 assigns
   which sentences move): they no longer state that no SRT/TXT/MD projection exists, and they say what stays
   unpublishable;
   (c) this compass's `## Roadmap Position` still names the separate live E2E re-run as its first next item
   (owner `project-manager`, trigger: this iteration merges) and the register's other medium rows with their
   owners — a read of that section, so no iteration-close claim can quietly drop the bound.

## Non-Goals

- **No real-device / GPU E2E in this iteration** — D5. The live re-run on the target host is a
  separate, user-authorised E2E workflow after delivery; no task, criterion or gate here depends on it.
- **No change to the ASR/audio chain's code or to the manifest's state vocabulary** — D2. `coordinator.py`,
  `audio.py`, `asr.py` keep reading the manifest; this iteration adds a publication, not a second chain.
  The exclusion is stated precisely because the projection *does* record the published row's state in the
  manifest (Scope 1): it writes only a status the chain's existing vocabulary already accepts (D12 names
  which), and no reader's meaning of an existing status changes.
- **No "force the audio branch for a captioned part"** — register row `e2e-23191782-longform-pair-webdav · R2`.
  That is a product decision about an override surface, not part of publishing what the store has; the
  row keeps its trigger.
- **No schema change and no migration** — the projection reads the existing tables; widening a
  constraint only ever applies to fresh databases (the frozen policy), so the contract must fit the
  tables as they are.
- **No back-write into the store** — D3. Nothing about the projection's outcome is recorded in
  `archive.db` beyond what already exists; the manifest stays the chain's state machine.
- **No fix for the artifact-root measurement hardening** — register row `iter-2026-09-artifact-root · R2`
  (fail-open usage measurement; the missing write/fsync probe; the per-row walk) stays open with the
  A7 verdict recorded. This iteration writes *products*, not audio budgets, and touching that guard
  would widen the review surface the row's own `target` does not ask for.
- **No manifest-reader cleanup** — `20260918-verification-surface-truth · R1`/`R2` (a dead
  `_read_manifest` helper, a duplicated projection) keep their own trigger.
- **No writes to `{KNOWLEDGE_DIR}`** — D7.
- **No new exit code for existing commands, and no change to an existing command's exit behaviour** —
  operators and CI wrappers script the frozen `0/1/2` taxonomy; D10 answers Q1 inside it (`0`/`1` only,
  `2` unreachable for a command that opens no socket), so the new command needs no revision of the frozen
  spec's exit table.
- **No replacement of a published product when the store gains a newer transcript version (the next-version drift non-goal)** — the projection
  is additive (D3) and this iteration publishes what has no product yet; deciding that an archive bundle is
  *replaceable* is a revision-history question, and today's marker records nothing to compare a version
  against (`archive-bundle-v1` holds `schema` plus one `path`/`sha256` pair per artifact family). The
  operator-visible consequence is a disclosure, not a repair: the part prints `already_published` and the
  older products stay, and criterion 6 checks that the limit is stated on the command's own surface.
- **No product for a part the store holds no transcript for (the captionless-remainder non-goal)** — the captionless remainder (61 parts in the
  2026-09-20 live store) is the *derived audio queue's* subject, not this command's: `derive-manifest`
  appends them as `needs_audio` (`queue=<n>`), `download-audio` / `asr` / `run` produce their products, and
  `harvest-subs` already prints `remaining_without_transcript=<n>`. The projection's summary counts only its
  own candidates and is not an archive-completeness report; the operator's completeness surfaces stay
  `coverage` and `verify`.
- **No reader repair for the append-only-history disagreement (the readers' append-only-history non-goal)** — register row
  `e2e-23191782-season-7686105 · R2` (high) stays open: `verify` maps `manifest_duplicate_work_id` — raised
  by the reader module `sidecar_projection.py` for ordinary append-only state history — to
  `structural_input_error`, and plain `coverage` blanks its denominator for the same input. The projection
  inherits that limit on a real corpus — a part queued `needs_audio` while it was captionless, which later
  gains an upstream caption and is harvested, then holds both a transcript and an earlier manifest row — so
  this iteration claims nothing about that shape: Fixture F is built with one row per `work_id`, criterion 3
  stays outside it, and the row keeps its own trigger (the next plan touching `integrity.py` or
  `coverage_report.py`).

## Roadmap Position

- **Current iteration — in progress**: close the projection half of `e2e-23191782-season-7686105 · R1`
  (a supported way to publish a stored transcript as an archive bundle, so the caption path can
  produce products at all) and the folded-in `check-asr-env` anchor fix
  (`e2e-23191782-longform-pair-webdav · R1`).
- **Next (each item names owner and trigger so a reader with no access to this session can act):**
  1. **Separate E2E workflow re-running the live pair** (`BV1vVDKBvEqL:p0`, `BV1iMGL6KE9J:p0`) through
     the projection path on the target GPU host, now that the store already holds both transcripts —
     user-authorised 2026-09-20 (D5, choice "fixture now, live E2E after delivery"). Owner:
     `project-manager` opens it after this iteration merges. This is also where the WebDAV artifact
     placement finally gets a real archived row.
  2. **`e2e-23191782-longform-pair-webdav · R2`** — no override exists to route a caption-bearing part
     through the audio branch, so the audio path of the two most recent iterations is still unverified
     on live data; the row carries the decision options (opt-in override vs. an E2E over captionless
     items). Owner: `project-manager` at the next planning round.
  3. **`iter-2026-09-artifact-root · R2`** — re-scoped by measurement on 2026-09-20 (keep the fail-open
     defect; downgrade the per-row walk; prefer declaring fsync-hostile mounts out of contract over
     adding a probe). Owner: the next plan that owns `audio_budget.py`'s call sites or the operator's
     network-mount configuration.
  4. **`iter-2026-09-artifact-root · R3`** (medium) — the path-to-base pairing is re-implemented in
     five modules. Trigger: the next plan that adds an artifact family or a second configured root.
  5. **Low rows that fold into plans touching the same files**: `20260918-transcript-text-precision · R1`
     (five unexercised hotwords), `20260918-operational-record-coverage · R1`/`R2`/`R4`
     (interruption-contract windows), `e2e-23191782-longform-pair-webdav · R3` (`fetch-meta`'s blocked-page
     recovery), `20260918-verification-surface-truth · R1`/`R2`, `iter-2026-09-text-and-ledger-precision · R1`
     (knowledge docs failing the compound validator).
- **Standing discipline**: the low rows are not iteration material on their own — they fold into plans
  that touch the same files (their `target` fields say which), and the register is their SSOT.

## Delivery Branch Policy

| Field | Value |
|-------|-------|
| iteration_base_branch | `main` |
| spec_integration_branch | `iteration/iter-2026-09-transcript-projections` |
| target_branch | `main` |

Source: repo `AGENTS.md` (default integration / PR target `main`; feature work merges into
`iteration/<iteration-id>`), identical to the four preceding iterations. Not a silent default.

**Main worktree branch**: `main` (the control root stays on `main`; the iteration's reviewed documents are committed on the integration branch in its own worktree, per `mstar-iteration` §2.3 step 7).

## Phase 1 review chain (§1.6)

One row per round, written from that round's own report as it lands: `product-manager` → `architect` →
`writing-specialist`, in that order, each editing these artifacts in place. `status: locked` only after
the writing-specialist's hygiene pass and after every non-`PM` marker is cleared.

| # | Role | Findings | Cleared markers | Reassigned to PM |
|---|------|----------|-----------------|------------------|
| 1 | `product-manager` | **Q1 converged into D10 and the row withdrawn from `## Open Questions`**: name `publish-transcripts` (chosen with the `naming-analyzer` skill against the shipped verb-noun family; `project-transcripts` rejected because *projection* is this repo's word for a read-only derived view), range = every stored part that holds a transcript (the "all pending parts" default rejected — *pending* is the store's word for "no transcript" and would promise the 61 captionless parts), `--bvid <bvid[:pN]>` reusing `_subtitle_selector`, `--limit-parts N`, a per-candidate line plus a `derive-manifest`-form counts line, and an exit stance of `0`/`1` inside the frozen taxonomy with `2` unreachable. All six criteria rewritten as operator-visible checks (command, exit code, observable line/state); criterion 3 no longer cites the unshipped "four-way consistency" probe and instead runs `verify` (which recomputes the marker) and `coverage --quality`; criterion 6 became a three-part disclosure check. Nine non-goals validated against the charter: one narrowed (D2's "no manifest contract change" now says *vocabulary*, because the projection does record state in the manifest), eight upheld; **three added** — next-version drift, the captionless remainder, and the readers' append-only-history defect (`e2e-23191782-season-7686105 · R2`, high) the projection inherits. Fixture F extended to the five states the criteria discriminate. Plan: `## Operator surface (product)` added and the Prepare/self-review rows synced. | 2 — the two draft markers, in criteria 1 and 3 (both cleared in place) | 0 |
| 2 | `architect` | **Q2/Q3 converged into D11/D12 and Q4 into D13; all three withdrawn from `## Open Questions`** (one row left: Q5, `writing-specialist`). Wrote and sealed `specs/transcript-projection-contract.md` (§1–§14, every claim at `file:line`, pinned to `013a507`): the candidate relation is every stored part that holds a transcript, whatever its `processing_status`, read through **one new** repository call with the locked order in the repository; the winner is the minimum over *(cc → ai → `asr-local`, family `zh` → `en` → other, language code, `version` DESC)* — the harvester's own preference read off stored columns, total by the store's `UNIQUE` key; `start_ms / 1000` exactly into the writer's `segments`; the `raw` sidecar is the writer's own synthesis because the store has no `lan`/`lan_doc`; **nine** frontmatter keys, with every `asr_*`/`confidence` key **structurally** absent (no `confidence` column; the VAD summary runs only for `source == "asr"`; `asr_provenance` is not passed) and nothing zero-filled; the recorded row is `status: archived` + four root-relative paths + `source`/`language` (fifteen keys) — `subtitle_done` rejected because the reader demands `subtitles/raw/` (`integrity.py:370-380`), `asr_done` rejected as a claim about ASR work that was not done; idempotency is the record, not a file probe (`already_published` iff the row declares the bundle **and** `archive_bundle_complete` confirms it at the write base, else publish — which is how an interrupted bundle heals; a stale `.archive-bundle-stage` is that candidate's `failed`, exit 1); `asr-local` stays in range with its per-model/run identity rule and the `model_id` → `asr_*` provenance mapping **explicitly deferred** to the audio/ASR iteration. Plan `## Tasks` authored: **T1** `archive.bundle_paths` (name rule's one home), **T2** the repository read, **T3** the pure service, **T4** the command, **T5** the readers' agreement fixture (criteria 1–4), **T6** the boundary docs (two named files), **T7** the F4 anchor + one cwd-independent test (criterion 5); `## Done criteria` filled and `## Prepare gates` `plan` → done. **Two findings the PM should see, neither reopening D10**: (a) criterion 3's literal `reasons: []` additionally requires Fixture F's caption body to carry no **advisory** content code, because the JSON `reasons` is the defect ∪ advisory union (`cli.py:1564-1567`) while validity reads the defect list (`cli.py:1578`) — recorded as a fixture requirement in the criteria paragraph and the contract; (b) a green `verify` exit additionally needs `F/coordinator/attempts.jsonl` (`missing_attempts_sidecar`, `integrity.py:314-328`, `cli.py:3328`), and the projection must not write that ledger (chain stage evidence) — recorded as a second fixture requirement. **Frozen spec**: `{SPECS_DIR}/asr-archive-cli.md:42-45` owes a revision (its added-command enumeration and its "**11** commands" `--artifact-root` count → twelve); the exit taxonomy (`:110-112`) needs none; conclusion recorded in contract §13, spec not edited (PM-owned). | 2 — the two draft markers, in `## Scope` (replaced by the contract pointer + the section map) and in `## Plans` (replaced by the confirmed split, task list and declared `primary_spec`); both cleared in place | 0 |
| 3 | `writing-specialist` | **Q5 converged into D14, and the chain closes with no chain-owned marker.** The move set was verified against the published claims by search, not taken from T6's list alone: four stale sentences in `README.md` (`:341-342`, `:1010`, `:1049`, `:1090-1096`) plus the `eleven` count at `:374` that D10 makes twelve, two in `docs/metadata-storage.md` (`:318-321`, `:331`), and — outside the two-file bound — `docs/artifact-root.md:89-103` and the frozen spec's enumeration and count, the latter two reassigned to `PM` as the non-blocking rows Q6/Q7. Corpus hygiene over the four artifacts and the iteration index: 13 stale question-id sites repaired (in `## Scope`, `## Plans`, `D3`/`D8`/`D10`, `## Acceptance Criteria` 1/3/4 and 6(b), `## Non-Goals`, both remaining risk rows — each pointed at a withdrawn `Q2`, `Q3` or `Q5` and now names `D11`, `D12` or `D14`); the risk register's reference to the unshipped "four-way consistency" probe replaced by the readers' agreement checks the criteria actually run; the contract's §5.5 state table completed to the **five** states the fixture holds (the `gone`-part state (v) added, with the plan's T4 honouring line moved to the same count); the `eleven` count aligned with its two other homes (`tests/test_cli_help.py:1112-1116`, `tests/test_cli_artifact_root.py:53-66`), which T4 now names so the new command also joins the two shipped help/flag matrices; the `## Scope` evidence citation corrected to the report's own `§R2-A3/A4/A5/A6/A8` labels; T6's regression claim corrected — only `README.md` is pinned by `test_check_asr_env.py:124-138` (the second pinned copy is `docs/wsl-rocm-gpu.md`, not `docs/metadata-storage.md`), so the metadata doc's evidence is the static `rg` alone; the iteration index's orphaned `iter-2026-09-artifact-root` row moved back into the table it belongs to; the package index pointed at D1–D14. **Marker audit:** 2 occurrences found, both quotations inside rows 1–2 of this table, both rephrased — **0 active markers** in the compass, plan, contract and package index (active = the form §1.3(iii) defines). **Registration check:** `plans:` matches the plan id in the plan frontmatter, the package `README.md`, the index row and the plan's `iteration:` field; the branch anchors match the workflow snapshot — nothing to escalate there. | 0 | 2 |

## Iteration package

| Path | Purpose |
|------|---------|
| [`specs/transcript-projection-contract.md`](specs/transcript-projection-contract.md) | the iteration-level contract the `architect` writes in this chain — identity/stem, version choice, ms→s conversion, raw-sidecar and frontmatter key list, recorded state, idempotency, exit stance alignment, validation plan (this iteration writes no `{SPECS_DIR}` file; D7) |
| `guides/` | operator-facing notes if the plan produces any — none yet |
| `README.md` | package index |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **A projection is read as "`archive.db` is now the archive SSOT".** The caption path stores text and the projection publishes it, so the store looks authoritative. | Med | High | D2/D3: the chain and its manifest contract are untouched, the store connection is read-only, and `## Non-Goals` states the SSOT question is still deferred and that answering it later is a deletion, not a rewrite. The `writing-specialist` round checked that no published sentence implies otherwise, and named the sentences that move (D14). |
| **The projected frontmatter/`raw` claims more than a caption can know** (a `md` that looks like an ASR run, or zero-filled confidence that reads as measured). | High | Med | Acceptance criterion 4 compares keys against the contract's explicit list and requires the unsupportable ones to be **absent**; the review chain's claim-scope discipline (a knowledge doc this repo already keeps) is the review lens. |
| **Idempotency collides with versioning**: a part gains a new transcript version after it was projected, and the rebuild either duplicates a bundle or silently keeps stale products. | Med | Med | D12 makes the rule explicit and the fixture is extended with a second version (F-iii); the contract states which way the command resolves it, and the drift-after-publication half is a stated limit rather than silence — the next-version drift non-goal plus criterion 6's disclosure check. |
| **A projected bundle fails the archive's own completeness readers** (a marker or raw-sidecar shape that `archive_bundle_complete`/`verify` rejects), producing archives that look published but are not counted. | Med | High | Acceptance criterion 1/3 runs the real readers (`archive_bundle_complete`, `verify --trusted-local`, `coverage`) rather than a bespoke check; those readers' agreement checks are part of the gate. |
| **The F4 fold-in is scoped to grow** (the anchor fix is a one-liner, but "while we are here" changes to the self-check or its taxonomy would widen the review surface). | Med | Low | D6 fixes the item: the anchor plus one cwd-independent test. Any further self-check change is a separate row. |
| **Fixture-only verification leaves the projection unproven on a real corpus** (which is exactly how this iteration started). | High | Med | Accepted by D5 deliberately: criterion 6 states the bound, and the follow-up live E2E is the first item of `## Roadmap Position` with the user's authorisation already recorded. |

## Quality Gate Summary

Human summary only; per-plan gate details stay in the main plan, and the residual SSOT stays in
`{PROJECT_DIR}/_default/residuals.json`. Filled at the plan's QC/QA gates.

| plan_id | QC decision | QA gate | Residuals | Durable summary |
|---------|-------------|---------|-----------|-----------------|
| `20260920-transcript-projections` | pending | pending | pending | pending |

## Compound Round Summary

Filled at iteration-close (`mstar-compound`).

## Iteration Retrospective (minimal)

Filled at iteration-close.
