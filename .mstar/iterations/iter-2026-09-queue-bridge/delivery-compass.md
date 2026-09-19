---
iteration_id: iter-2026-09-queue-bridge
start_date: 2026-09-19
status: locked
iteration_base_branch: main
target_branch: main
plans: [20260919-sqlite-queue-bridge]
---

# iter-2026-09-queue-bridge Delivery Compass

> **For agentic workers:** this compass is the context carrier for the Phase-1 review-and-edit chain.
> Dispatched roles cannot see the PM's session; they read this file, the plan files and this package.
> Every gap that is deliberately left coarse carries a marker with an explicit owner from the Phase-1
> chain; the marker syntax is defined in `mstar-iteration/references/phase-1-prepare.md` §1.3(iii) and
> nowhere else — it is not restated here.

## Scope

Close the medium residual `e2e-23191782-season-7686105 · R1` (the "SQLite feeds nothing below it" boundary):
**the ASR and audio chain must be able to take its work queue from `archive.db` instead of a hand-built
`manifest/manifest.jsonl`.** Two of the three pieces the boundary section names
(`docs/metadata-storage.md:302-305`) are in scope; the third is not.

In scope — each piece is a promise about what an operator can do after this iteration that they cannot do
now (boundary-section numbering in parentheses):

1. **Enumerate the audio work queue from SQLite** (boundary piece 1) — an operator runs **one command,
   `bili-asr derive-manifest --archive-root <archive-root>`** (D9), and every part the store records as still
   needing audio/ASR lands in `manifest/manifest.jsonl` as a page-qualified row carrying a converted
   duration; the queue is read out of `archive.db` instead of being assembled by hand. Which store facts
   count as "needing work" is the predicate Q3 raised, settled as **D12** (spec §2), not this sentence's.
   Check: `## Acceptance Criteria` 1.
2. **Give the legacy audio feeder a source again** (boundary piece 3) — `harvest-subs` stopped producing
   `needs_audio` (`docs/metadata-storage.md:295-297`), so nothing marked a captionless part for the audio
   path; after this iteration a captionless part that `harvest-subs` recorded in the store is selected by
   `bili-asr download-audio --missing-subs` and runs the chain with no hand editing.
   Check: `## Acceptance Criteria` 2 and 3.

Chosen shape (user-locked, see `## Decisions` D1/D2): **a new command that derives manifest rows from
`archive.db`**; the ASR/audio chain keeps reading the manifest and its code is not restructured. The command
name, its literal entry point, its exit stance and what it prints are **D9**; the selector surface and the
row mapping are the `architect`'s, settled as **D12** (Q3; spec §2–§3).

**Spec (architecture pass, 2026-09-19):** [`specs/sqlite-queue-bridge-contract.md`](specs/sqlite-queue-bridge-contract.md)
— the bridge contract: the queue predicate (§2), the row mapping and the additive conflict policy (§3), the
Q1/Q2/Q4/Q5 answers (§4–§7), the operator surface and its exit stance (§8), interfaces and affected readers
(§9), D8 restated next to the contract (§10), the deferred list (§11), risks/rollback (§12) and the validation
plan that makes criteria 1/2/3/6 checkable (§13). Every statement in it names the file:line it rests on.

## Decisions

| # | Decision | Rationale | Source |
|---|----------|-----------|--------|
| D1 | **Scope = pieces 1 + 3 only** (queue derivation + feeder restored). The SRT/TXT/MD projection rebuild (piece 2) is **out** of this iteration. | The register sizes pieces 1+3 as the corpus-unblocking slice (S) and the full three-piece closure as M; the projection half additionally needs a stem/version-identity decision that only matters once a queue exists. | user instruction (2026-09-19) |
| D2 | **Route = derive manifest rows from `archive.db` in a new command; the ASR/audio chain is not restructured.** `manifest.jsonl` remains the item state machine for this iteration. | Zero schema change, zero change to `coordinator.py`/`audio.py`/`asr.py` (they import no storage module today), reversible, and it avoids answering the "which store is SSOT" question inside a bridge. | user instruction (2026-09-19) |
| D3 | **Branch policy: `iteration_base_branch` = `main`, `spec_integration_branch` = `iteration/iter-2026-09-queue-bridge`, `target_branch` = `main`.** | Repo `AGENTS.md`: "Default integration / PR target: `main`; Feature work: plan branches merging into `iteration/<iteration-id>`". Same shape as the two preceding iterations — a written project convention, not a silent default. | project convention (AGENTS.md) |
| D4 | **No migration, no importer.** The bridge is a forward derivation SQLite→manifest. It never imports, transforms or reads `manifest.jsonl` back into the store, and it creates no compatibility reader. | Settled four times on the record (`docs/metadata-storage.md:283-286`, `:290`; the previous compass's No-Migration Declaration; two iteration specs). Schema widening would also apply to fresh databases only — `CREATE TABLE IF NOT EXISTS` cannot widen a constraint (`storage/schema-transcripts.sql:4-10`). | existing spec (frozen decision) |
| D5 | **The asr-local identity decision is in scope to *decide*, not to implement.** `transcripts.source_kind` already allows `asr-local` and the content-uniqueness index explicitly hands its per-model/run identity rule to "the audio/ASR iteration" (`storage/schema-transcripts.sql:30-35`). This iteration records the decision; writing ASR transcripts is a later iteration's work. | The schema authors wrote the hand-off; leaving it undecided again would keep a documented hole open for a third iteration. | knowledge/spec (schema comment) |
| D6 | **Phase 1 writes no `{KNOWLEDGE_DIR}`.** Iteration-level specs and guides land in this package; promotion happens at iteration-close via `mstar-compound`. | `mstar-iteration` §1.5.5 and §1.6 (start chain must not add knowledge). | skill contract |
| D7 | **The register row `e2e-23191782-season-7686105 · R1` is the charter and its corrected text is the input of record** (three registration errors were corrected on 2026-09-19, and a fourth — the `v_pending_subtitles` predicate — during this iteration's reconnaissance). | The row's `target` names the done-definition; its `tracking` now carries the recon facts (12 findings) that a plan needs. | PM (recon, 2026-09-19) |
| D8 | **Q7 converged — the "no back-write of an inferred truth" rule does not forbid an authoritative derivation: the bridge writes *recorded store facts* into the manifest and never copies manifest state back into the store; the rule forbids a *projection's inference* (a guess about an artifact that may not exist) from becoming manifest state.** | `operational-sidecars.md:234-236` constrains what may become manifest state, not whether the manifest may be derived from the store. D4 already fixes the opposite direction, so this row adds the remaining half of the line: a derived row states only what a store row supports (the part's identity, its duration, whether a transcript exists) — never a speculative `subtitle_done` or `archived`. Without this written down, a reviewer reads the rule against the bridge (Risk Register row 2). | product-manager (Q7 convergence; rule text `{KNOWLEDGE_DIR}/architecture-patterns/operational-sidecars.md:234-236`; direction fixed by D4; the boundary it closes is `docs/metadata-storage.md:288-293`) |
| D9 | **The bridge's operator surface is one new command: `bili-asr derive-manifest --archive-root <archive-root>`.** It reports a manifest-state summary like every other command and adds no exit-code value to the frozen taxonomy — exit `0` when the derivation completes, including "nothing to derive"; exit `1` only when the command cannot run (spec §8: a missing or unreadable `archive.db`, a database predating the transcript schema, `archive_busy`, a usage error). | D2 already fixed "a new command"; this row fixes the name, the literal entry point and the exit stance so the `architect` and the plan do not re-open them. `derive-manifest` names the direction the derivation actually runs (SQLite → manifest); "sync" would claim the back-write D4 forbids, and the register's alternative (`download-audio --from-sqlite`) is a flag on the chain's own command rather than the standalone surface D2 locks. The name stays inside the existing verb-noun family (`fetch-meta`, `harvest-subs`, `download-audio`). | product-manager (naming assigned to this role by the `## Scope` marker; boundary piece 1 = `docs/metadata-storage.md:302-304`; empty-queue-as-success precedent `cli.py:1098-1100`; exit taxonomy `{SPECS_DIR}/asr-archive-cli.md:97-101`) |
| D10 | **Q1 converged — the bridge materializes nothing and derives no `subtitle_done` row; it writes manifest rows and nothing else.** Every part in the queue is captionless by construction, so every derived row is `needs_audio`; the `missing_subtitle_raw` trap cannot fire for a derived row because no derived row can reach the state that skips. Materializing `subtitles/raw/{stem}.json` from stored segments is excluded: it is the projection rebuild D1 defers, the store holds neither the raw document's seconds-based timeline nor its `lan`/`lan_doc` fields, and it would let a store-derived file become the chain's evidence of an upstream caption. | The ASR/archive stage reads segments from the file system (`coordinator.py:396-413`) and skips with `missing_subtitle_raw` when they are absent (`coordinator.py:442-451`), while the SQLite caption path deliberately writes no projection (`services/subtitle_ingest.py`; `{KNOWLEDGE_DIR}/architecture-patterns/bilibili-asr-archive-cli.md:236-250`). `needs_audio` is the state the legacy probe already wrote for a captionless part (`subtitles.py:125-131`), and "no `transcripts` row" *is* the statement "this part still needs audio/ASR" (`schema-transcripts.sql:138-141`). | architect (Q1 convergence; full argument + evidence spec §4) |
| D11 | **Q2 converged — per-part audio/ASR evidence stays outside the store this iteration, and the first slice cannot preserve the store-side rotation contract; the loss is stated, not hidden.** The bridge is read-only on `archive.db` (`mode=ro`): it writes no run, no attempt, no transcript. Per-part audio/ASR evidence remains the manifest's forward transitions plus `coordinator/attempts.jsonl` (one row per attempted `(work_id, stage)`, `coordinator.py:34-58`, `:354-378`). Rotation is a repository-level `ORDER BY` over per-part attempt evidence that is caption-only (`database.py:1091-1123`; `schema-transcripts.sql:107-121`); a successful audio attempt produces no transcript and has no legal `acquisition_attempts` outcome shape (`schema-transcripts.sql:75-94`), and a widened CHECK would apply to fresh databases only (`schema-transcripts.sql:4-10`, D4). **Preserved:** the manifest's own forward state — a successful attempt leaves `needs_audio`, so criterion 6 holds for it. **Lost, and to be registered:** a failed attempt leaves no recency, so a bounded run may re-select the same head. | Registering a per-part audio outcome would need a schema change the policy forbids on a live archive, and the run-level slot (`acquisition_runs.kind ∈ {audio, asr}`, `schema-transcripts.sql:50-67`) cannot carry per-part recency. Claiming rotation without the evidence would be a false promise; stating it is the fallback criterion 6 already allows. | architect (Q2 convergence; registered consequence spec §5 decision 4 — PM registers the residual at close) |
| D12 | **Q3 converged — the queue is `v_pending_subtitles` read through the repository's locked order, the derived set is exactly that relation, and the bridge is additive, never authoritative.** The row is nine fields (`work_id` = `format_work_id`-computed `bvid:pN`, `bvid`, `page_index`, `cid`, `title` = the part's stored title, `duration_s` = `max(1, duration_ms // 1000)`, `pubdate`, `pubdate_str`, `status`) and `status` is always `needs_audio`; `pending`/`meta_ok`/`sub_checked`/`subtitle_done`/`audio_ok`/`asr_done`/`archived`/`gone` are never derived, each for the reason spec §3.3 gives. An existing **effective** row for the same `work_id` is never rewritten: `needs_audio` → nothing appended, any other status → left byte-for-byte as found. Legacy bare-`bvid` rows are neither migrated nor rewritten and the command never emits one. | Additive costs one read of a manifest the command opens anyway and buys the two invariants the alternative breaks: an archived part (the store keeps no transcript for chain-produced archives, so it stays in the queue forever) is not re-queued, and a live `subtitle_done` row whose raw document exists is not clobbered. The ms→s conversion is load-bearing: the audio budget fail-closes on a missing or zero duration (`audio_budget.py:48-56`, `:87-88`), and floor() inverts the gateway's own `floor(seconds × 1000)` (`sources/bilibili_api_gateway.py:250`). | architect (Q3 convergence; full mapping + policy spec §3) |
| D13 | **Q4 converged — for the audio queue an `asr-local` transcript does drain the relation, and that is the correct reading: the queue means "no text at all", and a stored ASR transcript means the text exists.** Re-queueing such a part would re-download and re-transcribe work already done. The conflation is on the **caption** side (`harvest-subs --pending`, `count_pending_subtitle_parts`, the "remaining without a transcript" line), where a source-kind-scoped view is the fix — and `CREATE VIEW IF NOT EXISTS` (`schema-transcripts.sql:106`) cannot replace a view on an existing database, so that repair belongs to the iteration that first writes `asr-local` transcripts (the owner D5 already names). This iteration modifies no view and adds no filter. | The view's `NOT EXISTS` carries no `source_kind` filter (`schema-transcripts.sql:139-141`); splitting the two meanings needs rows that do not exist yet, so it cannot be tested now and would be a fresh-database-only change (D4). The mitigation available today is the naming duty in D12's row shape. | architect (Q4 convergence; `{KNOWLEDGE_DIR}/architecture-patterns/normalized-transcript-storage.md:237-262`; spec §6) |
| D14 | **Q5 converged — the bridged audio path keeps the stack it already has (`bili_client`) and the bridge opens no socket at all: no second stack, no migration, no new flag.** The frozen spec's "exactly one module (`bili_client`) opens sockets" (`{SPECS_DIR}/asr-archive-cli.md:62`) is already false in substance — `sources/bilibili_api_gateway.py` is the only module allowed to import `bilibili_api` (its own docstring, lines 1-4) and opens sockets through it on the metadata/subtitle path, while `bili_client` owns the legacy transport the ASR/audio chain uses. **So the frozen spec does need a revision** — one sentence stating two named stacks with a per-path owner (plus a `derive-manifest` row in the frozen CLI surface). Per this round's constraints the architect records that conclusion and stops there: the revision and its sign-off are the PM's (Q6, `asr-archive-cli.md:6` change policy). The plan does **not** depend on the revision. | The audio path's stack is fixed by D2 (chain unchanged) and its call sites are `cli.py:1108`, `:2446`, `:2618` → `audio.py:156-200`; the bridge composes a read-only store connection and `ManifestStore` only, which is checkable by grep (spec §7). Leaving the false sentence in place while shipping a command that reuses that path would keep a published rule that contradicts the code. | architect (Q5 convergence; revision owed to PM as Q6 input; spec §7/§11) |

## Open Questions

| # | Question | Owner | Blocking? |
|---|----------|-------|-----------|
| Q6 | **Does the new command require a revision of the frozen spec `{SPECS_DIR}/asr-archive-cli.md`?** Its change policy requires a new revision + PM sign-off for any requirement change; the bridge adds a command and may add an exit-code line. | PM (with architect input) | No |

**Non-blocking rows may cross the lock only if their owner is `PM`** (§1.3(v)); every other row must be
converged into `## Decisions` or moved into a marker before `status: locked`. Q7 (the "no back-write of an
inferred truth" rule vs an authoritative derivation) was converged by the product-manager pass into **D8**
and is withdrawn from this table. **Q1–Q5 were converged by the architect pass into D10–D14 and are
withdrawn**; the only row left is Q6, whose owner is `PM` and which is non-blocking — its architect input is
the concrete revision named in D14 (a two-stack HTTP-ownership sentence, plus a `derive-manifest` row in the
frozen CLI surface), and the plan does not depend on it.

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| `20260919-sqlite-queue-bridge` | Derive the ASR/audio work queue from `archive.db` | Todo | The iteration's single business plan: `{PLAN_DIR}/20260919-sqlite-queue-bridge.md` — Task 1 pure derivation, Task 2 store read + CLI command, Task 3 chain acceptance over a fixture, Task 4 publish the boundary (README + `docs/metadata-storage.md`); `Execution: mstar-sdd`, `QA gate: mandatory`/`targeted`. Contract: `specs/sqlite-queue-bridge-contract.md`. |

Candidate fold-in, decided with the plan split: `20260918-operational-record-coverage · R3` is a two-line
fix in `cli.py` (parse rather than string-compare the run's `started_at`). **Decided (architect, 2026-09-19):
not folded in** — it touches the run-ledger timestamp comparison, not the command this plan adds, and folding
it would widen the review surface the register row's own `target` does not ask for. It keeps its existing
trigger (the next plan that touches `run_ledger.py` or the CLI's exit handling).

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Spec freeze (Phase 1 lock) | 2026-09-19 | pending |
| Dev complete (plan Done) | 2026-09-19 | pending |
| QC complete | 2026-09-19 | pending |
| Iteration close | 2026-09-19 | pending |

## Acceptance Criteria

Each criterion is third-party checkable: the command an operator runs, the expected exit code or output, and
the fixture state that must produce it. No blocking question is left: the `architect` converged Q1–Q3 into
D10–D12, and every criterion that depended on one carries the resolved expected value in the note that
closes it, so each is checkable as written.

**Fixture F** (criteria 1–3): one disposable archive root (`--archive-root <fixture>`, a temp dir — never the
real `archive/`), whose `archive.db` was built through the shipping commands (`fetch-meta`, then
`harvest-subs`) or from the plan's checked-in fixture, and whose parts cover every class the queue predicate
can discriminate: a part with no transcript row, a part with a stored subtitle transcript, a part whose
`processing_status` is `gone`, and a part that `harvest-subs` attempted with no caption. Building F may need
network; the checks below run offline against the built fixture.

1. **One command derives the audio queue from the store** (seed 1: no hand-built manifest).
   - `bili-asr derive-manifest --archive-root <fixture>` exits `0`; running it a second time exits `0` and
     leaves the *effective* state unchanged. The manifest is an append-only ledger, so rows may be appended
     again — what must not change is the last row per `work_id` (what `ManifestStore.load()` hands the chain):
     `python3 -c "import json;eff={};[eff.update({json.loads(l)['work_id']:json.loads(l)}) for l in open('<fixture>/manifest/manifest.jsonl')];print(json.dumps(eff,sort_keys=True))"`
     — identical before and after the second run (idempotent/resumable, `{SPECS_DIR}/asr-archive-cli.md:44`).
   - The derived set is the store's queue, not a subset the command chose. The store's one declared work queue
     today is `v_pending_subtitles`, and D12 (Q3; spec §2) fixes it as this command's queue, so the check
     compares the two sides:
     `python3 -c "import sqlite3;print('\n'.join(r[0] for r in sqlite3.connect('<fixture>/archive.db').execute('SELECT work_id FROM v_pending_subtitles ORDER BY 1')))"`
     vs
     `python3 -c "import json;print('\n'.join(sorted({json.loads(l)['work_id'] for l in open('<fixture>/manifest/manifest.jsonl')})))"`
     — equal, and non-empty on F. Both sides run with the stdlib only (no `sqlite3` CLI is required).
   - Every derived row is page-qualified and carries a usable duration: `work_id` matches `bvid:p<n>`
     (`upsert` refuses a new automatic row without one, `manifest.py:290`), and `duration_s` is a positive
     integer, because the audio budget fail-closes on a missing or zero duration (`audio_budget.py:48-56`,
     `:87-88`).
   - Deriving a row is not progress in the store: the `v_pending_subtitles` set is identical before and after
     the run — a bridged row must not drain the subtitle backlog the way a written `asr-local` transcript
     would.
   - `bili-asr derive-manifest --help` exits `0` and names the store set it derives; it does not reuse the
     bare label `pending:` that `status` already prints for the unrelated metadata backlog.

   **Resolved (architect, 2026-09-19 — D12; spec §2, §3):** the expected set is `v_pending_subtitles` read
   through `TranscriptRepository.list_pending_subtitle_parts()` (predicate `schema-transcripts.sql:138-141`,
   locked order `database.py:1091-1123`); the manifest-side expected set is the derived rows for exactly those
   parts, and on a fixture whose manifest was empty before the first run the two sets are equal by §3.4's
   additive policy. `status` is always `needs_audio`; `duration_s = max(1, duration_ms // 1000)`; an existing
   effective row for the same `work_id` is never rewritten.

2. **The captionless part is reachable by the audio path without hand editing** (seed 2).
   - On F, the captionless part `P`'s effective row — the last row for its `work_id`, the one
     `ManifestStore.load()` hands to the chain — has `status: needs_audio` and a `duration_s` equal to `P`'s
     stored `duration_ms` converted to seconds.
   - `bili-asr download-audio --missing-subs --archive-root <fixture> --limit 1` does **not** print
     `download-audio: no needs_audio entries in the manifest` (`cli.py:1098-1100`): the derived row is
     selected. With the HTTP seam stubbed (the frozen spec's test seam,
     `{SPECS_DIR}/asr-archive-cli.md:103-109`) the attempt targets exactly that `work_id` and no other row.

   **Resolved (architect, 2026-09-19 — D12; spec §3.1–§3.2):** expected `status` is `needs_audio` (the
   captionless → `needs_audio` rule: the part holds no `transcripts` row), and expected `duration_s` is
   `max(1, duration_ms // 1000)` of that part's stored `duration_ms` — floor, because the store was populated
   by `math.floor(seconds × 1000)` (`sources/bilibili_api_gateway.py:250`), clamped to 1 because the audio
   budget treats a zero duration as unknown and fail-closes (`audio_budget.py:48-56`).

3. **A run consumes the derived queue** (the residual's trigger: the first corpus run that must feed
   SQLite-collected metadata into the ASR chain — this is also the Risk Register row 1 mitigation).
   - Over F, with the HTTP seam stubbed and no live network, `bili-asr run --scope pending --archive-root
     <fixture>` — the fixture form may add the chain's own `--offline` flag, which plan Task 3 uses,
       since the promise here is the queue's reachability and not live HTTP — moves every derived row past the state the bridge gave it, and no derived `work_id` produces
     a `missing_subtitle_raw` skip — the ASR chain reads subtitle segments from `subtitles/raw/{stem}.json`,
     not from `transcript_segments`, which is the trap Q1 names.
   - Live confirmation (optional, opt-in, not this gate's evidence): on a real archive root with the `[asr]`
     extra installed, `bili-asr run --scope pending --archive-root <root> --limit 1` reaches
     `"status":"archived"` for the derived part; without the extra the run stops at the ASR stage's
     documented install-hint failure (`{SPECS_DIR}/asr-archive-cli.md:67`) and that step is reported
     untested, not passed.

   **Resolved (architect, 2026-09-19 — D10; spec §4):** the bridge does **not** synthesize rows for parts
   whose caption already lives in the store — such a part holds a transcript, so it is not in the queue at all
   — and it materializes no raw subtitle document. The invariant therefore ranges over exactly the rows the
   command writes (all `needs_audio`, all captionless) plus the chain-held rows §3.4 leaves untouched; no
   derived row can reach the archive-from-subtitle path that skips. A stored caption without an SRT/TXT/MD
   bundle is **not** re-queued — that is the projection rebuild (piece 2), out of scope by D1 and open in the
   register.

4. **No double write, no second SSOT claim** (seed 3).
   - The frozen spec is not back-edited: `git diff --stat <base>..<branch> -- .mstar/specs/asr-archive-cli.md`
     is empty, and the new command's contract lives in this package's `specs/` (D6) — the route the previous
     iteration's two CLI commands took (`{SPECS_DIR}/README.md:20-32`).
   - The two published boundary statements no longer contradict the shipped bridge:
     `grep -n "feeds nothing below it" bilibili-asr-archive/README.md` and
     `grep -n "the two paths do not feed each other yet" bilibili-asr-archive/docs/metadata-storage.md` return
     no match, and each file instead states what now flows (the audio/ASR queue) and what still does not (the
     SRT/TXT/MD projections).
   - The chain's code is untouched: `grep -rn "from \.storage\|import storage\|archive\.db"
     bilibili-asr-archive/src/bili_asr/coordinator.py bilibili-asr-archive/src/bili_asr/audio.py
     bilibili-asr-archive/src/bili_asr/asr.py` finds nothing (D2), and `asr --pending`, `run`, `schedule`,
     `campaign` keep selecting rows from the manifest.

5. **The bound is stated** (seed 4).
   - The register row `e2e-23191782-season-7686105 · R1` is updated by the PM at close to record what this
     iteration delivered and that the SRT/TXT/MD projection rebuild stays open — this iteration does not
     close it.
   - `## Non-Goals` and the two docs name the same omissions a reader would otherwise have to discover: the
     projection rebuild, no live-DB schema widening (Q2's fresh-database-only consequence), and the reader debt that remains *latent* after the previous iteration reconciled the three readers
     (`20260918-verification-surface-truth · R1`/`R2`, open) and which this iteration does not claim to fix.
   - `grep -n "derive-manifest" bilibili-asr-archive/README.md` finds the command in the documented operator
     sequence (`fetch-meta` → `harvest-subs` → `derive-manifest` → `download-audio --missing-subs` →
     `asr --pending`).

6. **Bounded runs still make progress** (new — the Risk Register's rotation row turned into a checkable
   promise).
   - On F extended with a second captionless part, after a first bounded run has attempted part A the next
     bounded selection (`bili-asr download-audio --missing-subs --archive-root <fixture> --limit 1`) attempts
     B, not A again: the queue has a recency source, not only a membership source.
   - Fallback if Q2 forgoes per-part audio/ASR evidence this iteration: the spec states the rotation loss and
     the register row keeps it open, so the criterion is satisfied by a recorded gap rather than silently
     dropped — the same fallback the Risk Register already commits to.

   **Resolved (architect, 2026-09-19 — D11; spec §5):** per-part audio/ASR evidence stays outside the store
   (the manifest's forward transitions plus `coordinator/attempts.jsonl`); the bridge writes nothing to
   `archive.db`. The criterion is satisfied in its **preserved** form — a successful attempt takes the row out
   of `needs_audio`, so the next bounded selection attempts the other part — while the **lost** half (a failed
   attempt leaves no store-side recency, so the same head can be re-selected) is stated in spec §5 decision 4
   for the PM to register as a residual at close: the recorded-gap branch this criterion's fallback allows.

## Non-Goals

- **The SRT/TXT/MD projection rebuild (piece 2)** — out by D1. It needs a stem/version-identity decision and
  a metadata source for the md name (`pubdate_str` + `title`), and its own correctness traps (a rebuild
  would emit an md without the live-run keys and a synthetic raw sidecar at the same paths). Reason for
  excluding now: it does not unblock a corpus run, which is what the residual's trigger is about.
- **No migration / importer** — D4. Includes: no reading `manifest.jsonl` back into SQLite, no backfill,
  no compatibility reader, no in-place schema widening of a live `archive.db`.
- **No change to the ASR/audio chain's code** — D2. `coordinator.py`, `audio.py`, `asr.py` keep reading the
  manifest; the bridge does not add storage imports to them.
- **No SSOT change** — the "does `archive.db` become the queue SSOT" question is explicitly deferred, and the
  bridge must be written so that answering it later is a deletion, not a rewrite.
- **No writes to `{KNOWLEDGE_DIR}`** — D6.
- **No real-browser/device/installed-deployment E2E** as a task or gate of this iteration.
- **No http-stack migration** — Q5 is a documentation decision, not a refactor of the audio download path.
- **No touching the closed iteration's records** — `iter-2026-09-bilibili-api-sqlite/**` is historical and
  is cited, never retro-edited (its own specs still say "draft" against a completed compass; that
  contradiction is recorded in the register row's tracking, not fixed here).
- **No new exit code, and no change to an existing command's exit behaviour** — operators and CI wrappers
  script the frozen 0/1/2 taxonomy (`{SPECS_DIR}/asr-archive-cli.md:97-101`). "Nothing to derive" is a
  success (`0`), exactly as `download-audio --missing-subs` already treats an empty queue
  (`cli.py:1098-1100`). Inventing a distinct code for the empty case is the expectation this entry excludes.
- **The bridge is not a runner** — deriving rows starts no download and no ASR. The operator still runs
  `download-audio` / `asr` / `run` / `schedule` / `campaign`, and the bridge itself opens no socket (Q5 fixes
  which stack the *audio path* may use; the bridge has no HTTP at all). Reading "close the boundary" as "one
  command now runs the whole pipeline" is the misreading this entry forecloses.
- **`status` keeps its current backlog line** — the bridge names its own set in its own help text and spec
  (Q3; Risk Register row 6), while `status`'s printed `pending:` count stays the metadata backlog it is today.
  Adding an audio-queue count to `status` is a second operator surface with its own consumers and is outside
  D1's slice, even though the recon's finding (h) shows that label is a standing trap.
- **No further work on the manifest readers.** The three-reader disagreement about append-only history
  (`e2e-23191782-season-7686105 · R2`) was **closed on 2026-09-18** by plan `20260918-verification-surface-truth`,
  which gave the three readers one named judgement; the register is the authority and reads `resolved`.
  What remains open is that plan's own latent debt (`20260918-verification-surface-truth · R1`/`R2`: a dead
  `_read_manifest` helper and a duplicated projection), which this iteration does not touch. The bridge adds
  rows those readers read, so it must not be read as promising anything new about `verify`/`coverage` exit codes.

## Roadmap Position

- **Current iteration**: close `e2e-23191782-season-7686105 · R1`'s queue half — a supported way to obtain
  the ASR/audio work queue from `archive.db`, and the feeder source that `harvest-subs` removed. This is the
  register's own "cheapest corpus-unblocking slice"; the projection rebuild stays open in the register.
- **Next iteration** (each item names owner and trigger so a reader with no access to this session can act):
  1. **`e2e-23191782-season-7686105 · R1`, remaining piece**: rebuild the SRT/TXT/MD projections from stored
     transcripts. Trigger: this iteration's close. Owner: `project-manager` opens Prepare; the stem/version
     identity and the md metadata source are the first decisions (see this compass's `## Decisions` D1 and
     the recon findings (a)–(l) in the register row's tracking).
  2. **`20260918-transcript-text-precision · R1`** (low): the five unexercised hotwords' benefit — needs a
     lecture that actually speaks them; plus the product-side wording sync (asr.py + README) that any plan
     touching those files can land.
  3. **`20260918-operational-record-coverage · R1`/`R2`/`R4`** (low): the interruption contract's remaining
     windows (`schedule`/`campaign` coverage, the pre-guard span, the SIGINT clause window). Trigger: the
     next plan that touches `cli.py`'s interruption surface; the three share one design.
  4. **`e2e-23191782-season-7686105 · R6`** (low): the intra-cue Latin gluing rule — first needs an XS
     retention change so the evidence exists at all.
  5. **`20260918-verification-surface-truth · R1`/`R2`** (low): delete the dead `_read_manifest` helper
     (spec-owner decision), dedupe the two projection copies. Trigger: any plan touching either coverage
     entry point.
  6. **`iter-2026-09-text-and-ledger-precision · R1`** (low): six knowledge docs fail the engine's own
     `compound validate`; the rule is now recovered and quoted in the row. Trigger: the next
     `mstar-compound-refresh` pass.
- **Standing discipline**: the low rows above are not iteration material on their own — they fold into plans
  that touch the same files (their `target` fields say which), and the register is their SSOT.

## Delivery Branch Policy

| Field | Value |
|-------|-------|
| iteration_base_branch | `main` |
| spec_integration_branch | `iteration/iter-2026-09-queue-bridge` |
| target_branch | `main` |

Source: repo `AGENTS.md` (default integration / PR target `main`; feature work merges into
`iteration/<iteration-id>`), identical to the two preceding iterations. Not a silent default.

**Main worktree branch**: `main`.

**Merge hazard to handle at close** (recorded now so it is not rediscovered): the previous iteration's
Phase-1 commit tracked a `{WORKFLOW_DIR}` snapshot on its branch while `main` keeps it untracked. Whoever
merges this iteration must decide deliberately what `{HARNESS_DIR}` paths travel on the integration branch.

## Phase 1 review chain (§1.6)

One row per round, written from that round's own report as it lands: `product-manager` → `architect` →
`writing-specialist`, in that order, each editing these artifacts in place. `status: locked` only after the
writing-specialist's hygiene pass and after every non-`PM` marker is cleared.

| # | Role | Findings | Cleared markers | Reassigned to PM |
|---|------|----------|-----------------|------------------|
| 1 | `product-manager` | Scope seeds turned into operator-promise requirements; six acceptance criteria with observables; Q7 converged into D8; D9 added (the literal `bili-asr derive-manifest --archive-root <archive-root>`, exit 0/1 only); four product-level non-goals | 2 | 0 |
| 2 | `architect` | The 13-section spec (`specs/sqlite-queue-bridge-contract.md`) and the four-task plan; D10–D14 added; Q1–Q5 withdrawn as decided; risk mitigations rewritten; recorded that the frozen `{SPECS_DIR}/asr-archive-cli.md` owes a PM-owned revision (D14/Q6) and that the rotation loss is the PM's residual to register | 6 | 0 |
| 3 | `writing-specialist` | 18 hygiene items fixed across the four documents — 1 engine-visible compass `plans` registration, 5 stale/dangling referents, 4 cross-document consistency, 4 package-index/placement, 3 wording/spelling/marker hygiene, 1 placeholder. 2 items escalated, not edited (criterion 3's evidence command form; the workflow snapshot's stale plan note) | 0 | 0 |

## Iteration package

| Path | Purpose |
|------|---------|
| [`specs/sqlite-queue-bridge-contract.md`](specs/sqlite-queue-bridge-contract.md) | the iteration-level bridge contract written by the `architect` — queue predicate, row mapping and conflict policy, the Q1/Q2/Q4/Q5 decisions, operator surface, interfaces, risks, validation plan (this iteration writes no `{SPECS_DIR}` file; D6) |
| `guides/` | operator-facing notes if the plan produces any — empty today |
| `README.md` | package index |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| A synthesized row satisfies the manifest's status vocabulary but not the archive stage's filesystem expectation (Q1) — the bridge "works" and the corpus run still skips | High | High | **Answered by D10** (spec §4): every derived row is `needs_audio` and the bridge writes no subtitle document, so the filesystem trap cannot fire for a derived row. The executable proof is plan Task 3 — a derived queue run with `run --scope pending --offline` reaches `archived` for the derived `work_id` with no `missing_subtitle_raw` attempt record — and Task 1's row shape is pinned field-for-field. |
| The bridge is read as a forbidden projection back-write (`operational-sidecars.md:234-236`) | Med | Med | Q7 converged as **D8** and is now discharged twice over: the spec restates the line next to the bridge's contract (spec §10), the status set the command may write is one item long (spec §3.3), and the store connection is `mode=ro` so the back-write direction fails inside SQLite rather than by convention (spec §9/§10). |
| A schema decision (Q2) that silently applies only to fresh databases | Med | High | **Answered by D11** (spec §5): no schema change is proposed at all. The fresh-database-only property is written down as the *reason* per-part audio evidence has no store home this iteration, so the plan relies on no widened CHECK (`schema-transcripts.sql:4-10`). |
| Rotation is lost: a naive "no audio row" queue re-attempts the same head every bounded run | Med | Med | **Answered by D11 + D12** (spec §3.4, §5): rotation is preserved for a successful attempt — the row leaves `needs_audio`, so the next bounded selection takes the other part (criterion 6's checkable branch, plan Task 3). The failed-attempt loss is stated in the spec, and the PM registers it as a residual at close (the recorded-gap branch criterion 6 permits). |
| The bridge's blast radius is understated: `coverage`, `coverage --quality`, `verify` and `export` also read manifest-shaped state | Med | Med | **Discharged:** the spec's §9 Interfaces lists all four with their `cli.py` lines as affected readers, alongside the chain's own selectors, and the compass `## Non-Goals` keeps further reader work out of this iteration (the three-reader reconciliation itself was closed on 2026-09-18; the open debt is `20260918-verification-surface-truth · R1`/`R2`) — the bridge must not be read as making `verify`/`coverage` exit 0 on a real archive. |
| The two "pending" notions (`v_pending_metadata` vs `v_pending_subtitles`) are bound to the wrong chain | Med | High | **Answered by D12** (spec §2, §8): the command's `--help` and its summary line name the set as *parts with no transcript and not `gone`*, `status`'s bare `pending:` label stays the metadata backlog (`cli.py:1232`, `schema.sql:156-166`), and plan Task 2 carries the help-text case as a gate. |

## Quality Gate Summary

> Filled at iteration-close. Human summary only; per-plan gate details stay in each main plan, and open
> residual SSOT stays in `{PROJECT_DIR}/_default/residuals.json`.

| plan_id | QC decision | QA gate | Residuals | Durable summary |
|---------|-------------|---------|-----------|-----------------|
| `20260919-sqlite-queue-bridge` | recorded at iteration-close | `mandatory` / `targeted` (plan frontmatter) | recorded at iteration-close | `{PLAN_DIR}/20260919-sqlite-queue-bridge.md` |

## Compound Round Summary

> Filled at iteration-close.

- 结晶文档数：<N>
- 新增 CONCEPTS.md 条目：<N>
- 触发 compound-refresh：<是/否>

## Iteration Retrospective (minimal)

> Filled at iteration-close.

- 做得好的：
- 可改进的：
- 下迭代建议：

## Quality Gate Summary

| Plan | QC (L3) | QA (L4) | Result |
|---|---|---|---|
| `20260919-sqlite-queue-bridge` | tri-review approve (qc1/qc2/qc3), 2 fix rounds + per-item confirmations | approve (`review/qa.md`) — criteria 1–6 pass, 110 passed / 1 skipped, live-ASR clause untested | **Done** — the derived queue reaches the ASR chain; the projection rebuild stays registered |
