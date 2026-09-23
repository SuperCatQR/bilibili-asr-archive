---
iteration_id: iter-2026-09-transcript-editorial-stages
start_date: 2026-09-23
status: locked
iteration_base_branch: main
target_branch: main
plans: [20260923-transcript-proofread, 20260923-reading-edition]
---

# iter-2026-09-transcript-editorial-stages Delivery Compass

> **For agentic workers:** this compass is the context carrier for the Phase-1 review-and-edit chain.
> Dispatched roles cannot see the PM's session; they read this file, the plan files and this package.
> Every gap deliberately left coarse carries `TODO(owner: <role>)`; the marker syntax is defined in
> `mstar-iteration/references/phase-1-prepare.md` §1.3(iii) and is not restated here.

## Scope

After this iteration an operator can run both editorial stages from the shipped CLI. **`align-transcripts`**
builds the two-route alignment for a stored part and prints the accounting that proves every input cue and
segment landed in a bucket; **`verify-proofread`** checks a proofread candidate against the stage's own rules;
**`verify-reading-edition`** checks a reading edition — each refusing by name, with a location, when a rule
breaks (the surface is **D11**). One business plan per stage.

What that replaces is measured: the six items were proofread and polished by hand on 2026-09-22/23, and the
tools that built and checked them live in gitignored scratch (`.tmp/proofread-work/tools/`) or outside the
repo entirely (`/mnt/123pan/bili-asr-e2e/proofread-transcripts/`) — so no one but the session that made them
could run either stage again, or refuse a bad candidate.

1. **Proofread stage** — the mechanical half ships as two commands (`align-transcripts`, `verify-proofread`):
   (a) a **two-route alignment artifact** built from a stored part's ASR transcript and its caption
   transcript, in which **every input cue/segment is accounted for** (`count in == count out`, plus an
   explicit bucket for the unattached) — the rule register row `20260922-proofread-wave · R2` asks for;
   (b) a **proofread-candidate verifier** that checks a candidate against both routes and the stage's
   own record: marker vocabulary + parity, per-change record completeness, character-level containment,
   and a **hotword-table screen** (`20260922-proofread-wave · R1` made measurable).
2. **Polish stage (reading edition)** — its own verifier, `verify-reading-edition`: a **reading-edition
   verifier** checking timestamps-absent, character containment against the proofread base, **zero
   unexplained insertions**, every deletion **classified** (filler·noise / adjacent-repeat-with-retained
   twin / fragment) **with a term guard** (the `此在` blind spot of 2026-09-23), marker parity, and — for
   multi-part candidates — **seam checks** and concatenation fidelity.
3. **Replayable acceptance**: the 2026-09-23 six-item corpus replays through both verifiers **offline**
   and reproduces the wave's recorded numbers, or every difference is named.
4. **The judgement protocol is written down** as a stage contract (`{SPECS_DIR}`): what the agent half
   must do, what the mechanical half refuses, and what neither proves (no audio listening).

## Decisions

| # | Decision | Rationale | Source |
|---|----------|-----------|--------|
| D1 | The locked direction is **two stages as verifiable commands + a written protocol** | User instruction this round, and it closes a measured capability absence | user instruction |
| D2 | **Mechanical checks ship as commands; judgement stays with agents** | Repo precedent (`transcript-projection-publication`: split the pure decision from the write) and the wave's own rule; an LLM verdict inside a deterministic command is not auditable | autonomous ranking |
| D3 | Acceptance is a **replay of the six-item corpus** (offline, files only) | The wave's recorded numbers (`gap 0`, ratios, marker counts) are reproducible evidence that needs no new audio or network | autonomous ranking |
| D4 | The stage artifact is **two products**: a proofread base (`md/` shape) and a reading edition (`reading/` shape); the verifiers take the base as *source of truth* for the edition | The wave discovered that the **caption/ASR routes**, not the base, are the containment reference for the edition (the `此在` case: base adjudicated a term as retained, the edition deleted it, and only the routes showed it mattered) — **the verifier must therefore take both** | autonomous ranking |
| D5 | **No ASR hotword-configuration change** (`20260922-proofread-wave · R1` keeps its own trigger) | Different blast radius (`asr.py` + the measurement family); folding it in would mix directions | autonomous ranking |
| D6 | **No real-device / GPU / live E2E** in this iteration | The stages are file transforms; the corpus replay is offline. Live-corpus re-verification is a separate, user-authorised E2E workflow | repo convention + prior compass D5 |
| D7 | **No `{KNOWLEDGE_DIR}` writes in Phase 1/2** — stage knowledge is promoted at iteration-close via `mstar-compound` | `mstar-iteration` §1.5.5 hard rule | repo convention |
| D8 | **No new exit codes**; the new commands follow the frozen `0/1` taxonomy (no socket opened, so `2` stays unreachable) | `{SPECS_DIR}/asr-archive-cli.md` freeze + prior compass D10 precedent | repo convention |
| D9 | Environment note: **no `mstar` CLI on this host** | Every engine lifecycle write is hand-written to the frozen contract's schema and validated with the engine's own validator before it is treated as landed | repo convention (prior compass D9) |
| D10 | **Amended by D13** (2026-09-23, PM after the product-manager round measured D10's premise false): the route *sources* are the store where a route exists in it, and the bundle's `raw` sidecar for the ASR route; loose JSON is still not a source of record | The store is the shipped SSOT for transcript text (`normalized-transcript-storage.md`), but it holds **caption routes only** — the amendment names the ASR route's real home instead of pretending the store has one | autonomous ranking + measured (see D13) |
| D13 | **Ruling on the measured blocker** (product-manager round: no store can hold an ASR route). The ASR route is read from the **bundle's `raw` sidecar** (`transcripts/raw/<stem>.json` — `{segments, source, provenance}`), the caption route from the **store** (`subtitle-ai`/`subtitle-cc` rows, read-only) or, for an archive root with no database, from the same bundle family when `source` says caption. **No store-side ASR writer is shipped in this iteration.** | Verified by the PM, two independent ways: (a) the table's only writer validates `source_kind` against `ALLOWED_CAPTION_SOURCE_KINDS` (`storage/models.py:476` → `database.py:885`, sole `INSERT INTO transcripts` at `database.py:918`) and `read_transcript`'s own docstring says "the `asr-local` reservation simply has no rows yet" (`database.py:1038`); (b) the store schema has **no hotword surface at all**, while `write_archive` records the runner's provenance in the raw sidecar (`archive.py:476-500`) — measured on the host: 6 ASR raw files, each `{segments, source, provenance.hotwords}`. Reading the sidecar is therefore the *only* source that carries the very thing this iteration's hotword screen must check. Rejected alternative (ship a store-side ASR writer): it widens into the audio/ASR iteration's blast radius (D5's boundary) for a route this iteration does not need to *store*, only to *read*. | autonomous ranking + PM measurement |
| D11 | **Q1 converged — three new commands carry the two stages, and they add no exit value.**<br>`bili-asr align-transcripts [--bvid <bvid[:pN]>] [--archive-root <root>] [--artifact-root <root>]`<br>`bili-asr verify-proofread --candidate <path> --bvid <bvid[:pN]> [--archive-root <root>]`<br>`bili-asr verify-reading-edition --candidate <path> --bvid <bvid[:pN]> --base <path> [--part <path>]… [--archive-root <root>]`<br>**(a) Names** — verb + the object the operator holds: `align-transcripts` (the act produces the alignment), `verify-proofread` / `verify-reading-edition` (the act checks a *named candidate* against the stage's written rules; the subject is the candidate, never the editorial work). **(b) Selectors** — `--bvid <bvid[:pN]>` reuses the shipped `_subtitle_selector` rule verbatim (bare `bvid` = every stored part of that video, `bvid:pN` = exactly that part; `cli.py:838-857`); for the builder it is optional — with no selector the range is **every stored part whose store holds both routes** (criterion 1's own phrase) — for both verifiers it is **required**, because it names the part whose routes the candidate is checked against, and a candidate whose own frontmatter `work_id`/`bvid` disagrees with the selector is refused by name (the shipped `identity_mismatch` discipline, `coverage --quality`). `--candidate` / `--base` / `--part` name the operator's files; `--part` is repeatable and is required exactly when the candidate declares more than one part (the seam and concatenation checks need them), refused by name when it contradicts the declaration. An unknown `--bvid` is the shipped configuration error `<command>: unknown --bvid <value>` (each of the three commands naming itself, exactly as `probe-subs`/`harvest-subs`/`publish-transcripts` do), exit 1. **(c) Prints** — one line per candidate in the read's locked order, then a closing counts line carrying every count including the zeros (`derive-manifest`'s shipped form):<br>· builder — `<work_id>: aligned blocks=<n> segments_in=<n> segments_attached=<n> segments_unattached=<n> cues_in=<n> cues_attached=<n> cues_unattached=<n>`; `align-transcripts: candidates=<n> aligned=<n> refused=<n>`<br>· proofread verifier — `<work_id>: ok (body_chars=<n> marks=<n> record_rows=<n>)`; `verify-proofread: candidates=<n> ok=<n> refused=<n>`<br>· edition verifier — `<work_id>: ok (body_chars=<n> base_chars=<n> deletions=<n> classified=<n> marks=<n> parts=<n>)`; `verify-reading-edition: candidates=<n> ok=<n> refused=<n>`<br>Three line kinds are fixed, the vocabulary is Q2's: a **verdict** line, a **refusal** line `<work_id>: refused (<rule>) at <location>` (the rule named, the location a `<path>:<line>` or a `[hh:mm:ss]`/cue index — never a bare failure), and an **advisory** line `warning (<rule>) at <location>` which changes neither the per-candidate verdict nor the exit (the shipped defect-vs-advisory split of `coverage --quality`, where content codes never move `valid_work_items` or the exit). **(d) Exit stance** — `0` when every candidate is aligned/ok, **including zero candidates**; `1` for a usage/configuration error (unknown `--bvid`, missing/unreadable store, unreadable `--candidate`/`--base`/`--part`, `--part` contradicting the candidate) and for a candidate the command refused; **`2` is never produced** (no socket is opened; `_UsageErrorArgumentParser` maps argparse's own usage exit to 1) — D8's taxonomy, no new exit value. **(e) Route reading stays store-first** (D10); the flag set above is what the two stages need from the *store*, and the Q4 persistence residue is bounded rather than left open: if the architect rules the alignment artifact is persisted, it is written below the configured artifact root and `--artifact-root` joins the builder's flags under the existing 12-command convention — no new output flag, and the printed accounting line and exit stance above are unchanged. | **(a) Naming** (via the `naming-analyzer` skill against the shipped family `fetch-meta` / `probe-subs` / `harvest-subs` / `derive-manifest` / `publish-transcripts` / `verify` / `check-asr-env`): `align-transcripts` parallels `publish-transcripts` — same verb-noun shape, and *transcripts* is the store's own noun; **rejected**: `merge-proofread` (the wave's scratch tool's own name, but *merge* names the editorial act that produces the base — which these commands do **not** do), `compare-routes` (comparison is half the job; the accounting is the point), `build-alignment` (the family is verb-noun, and `alignment` is the artifact, not the act). For the verifiers: **rejected** `proofread` / `polish` (claim the command *does* the editorial work — the exact implication the direction forbids: these commands verify bytes, they do not proofread), `check-*` (`check-asr-env` is a host self-check, a different promise), and `lint-*` (imports a code-linter vocabulary the repo does not use). `verify` is the repo's established word for a deterministic read-only check and already names the shipped integrity command (`cli.py:3552-3570`, text output `checked:` / `defects:`), so the new names extend that verb rather than inventing one. **(b)** `--bvid` is the repo's shipped selector for store-side part selection (`probe-subs`, `harvest-subs`, `download-audio`, `asr`, `publish-transcripts`) and `_subtitle_selector` is its one home; the builder's no-selector default follows `publish-transcripts`' precedent (and the criteria's own conditional "for a stored part carrying both routes"), while a *named* selector that lacks a route is a refusal, not silence — a named selector is the operator's assertion that the part is ready. `--part` being conditional rather than always-optional is the README's own rule against an accepted-but-ignored flag ("an accepted-but-ignored flag would be a false statement in the interface", `README.md:373-381`). **(c)** The accounting line is criterion 1's arithmetic printed where an operator can read it — both `in == attached + unattached` statements appear as four numbers each, so the check is a subtraction, not an inference; the edition verifier prints `base_chars` beside `body_chars` because criterion 4's recorded numbers are *ratios* (`body_chars`/`base_chars`, per `README-reading-edition.md`'s table); `marks` / `record_rows` are printed because parity is a two-number identity the replay must reproduce. `warning` exists so that Q2's advisory class is expressible without either faking a refusal (which would contradict criterion 2/3's "violating any rule exits non-zero") or hiding the finding — it is the shipped `coverage --quality` split, not a new mechanism. **(d)** Empty-is-success follows the bridge precedent (`cli.py:1098-1100`) and the "zero candidates" case is the *normal* one today (see the criterion-4 marker); exit 2 stays reserved for terminal API failure and is unreachable without a socket. **(e)** D10 is the compass's own settled call and is not re-opened here: the surface takes the store as the route source, and the bound on Q4 keeps a persistence ruling from silently altering the interface. **Consequence the plans carry**: the surface above is the fixed contract in both plans' `## Operator surface`, the disclosures stay criterion 5's job (`--help` + README), and criterion 4's route-source residue was escalated to the PM as a marker and **ruled the same day — D13** (the ASR route is read from the bundle's `raw` sidecar; no store-side writer is shipped). | product-manager (Q1 convergence, this round; naming analysed with the `naming-analyzer` skill over the shipped family; `_subtitle_selector` `cli.py:838-857`; `unknown --bvid` lines `cli.py:1046`, `:1141`, `:1400`; counts-line form `publish-transcripts` / `derive-manifest`; empty-is-success `cli.py:1098-1100`; defect-vs-advisory split `README.md:672-679`; exit taxonomy `{SPECS_DIR}/asr-archive-cli.md:115-119`; usage-error mapping `cli.py:83-92`; no-artifact-flag rule `README.md:373-381`; identity discipline `coverage --quality`'s `identity_mismatch`) |
| D12 | **Q6 converged — the six-item corpus stays where it is: path-referenced, never copied into the repo.** The replay reads the delivered corpus at its two measured roots — the control host's `.tmp/proofread-work/` (`fixed/` = the six proofread bases, `reading/` + `reading-merged/` = the editions) and the delivered tree at `/mnt/123pan/bili-asr-e2e/proofread-transcripts/{md,reading}/`, with the two route sources at `/mnt/123pan/bili-asr-e2e/asr-vs-subtitle/transcripts/raw/` (ASR) and `/mnt/123pan/bili-asr-e2e/subtitle-publish/transcripts/raw/` (caption) — and the plans **pin the files by sha256**, a missing or differing digest being a named refusal, never a silent pass. Unit-level cases stay on crafted/synthetic fixtures, so nothing in the test suite depends on the corpus being present. | **Why not copy**: (1) the repo is public (`origin = github.com/SuperCatQR/bilibili-asr-archive`) and this project's own boundary is "no redistribution … personal archival only" (`AGENTS.md`) — **zero transcript text is tracked today** (`git ls-files` matches no `transcripts/`, no `.srt`), so committing ~0.9 MB of six lecture transcripts would be the first redistribution of transcript text the repo has ever carried, for a *test* dependency rather than a product one; (2) the delivered corpus **is** the acceptance evidence — criterion 4 replays *it* — and an in-repo copy would make the replay prove something about the copy, then drift from the real thing silently (the same silent-loss class as `20260922-proofread-wave · R2`); (3) the corpus is reachable from **two independent places**, both measured this round: the control host's `.tmp/proofread-work/` copy and the delivered tree on the `123pan:` rclone mount (`/mnt/123pan/bili-asr-e2e/proofread-transcripts/`), which the target host also sees at the same path. **All 12 products are byte-identical between the two** (six `md/` bases and six `reading/` editions, sha256), as are `REVIEW.md` and `README-reading-edition.md` — so the local copy is a real fallback rather than a hope. **Honest cost, accepted**: the replay is therefore not hermetic — CI cannot run it, and if both roots disappear the criterion fails closed by name instead of quietly passing. Size is *not* the deciding factor (~0.9 MB of products, ~1.8 MB of routes, beside a 31 MB `.git`) — (1) and (2) are. | product-manager (Q6 convergence, this round; measured this round: `.gitignore:2,25` cover `.mstar/**`/`.tmp/`; `git ls-files` tracks no transcript text; `tests/fixtures/` is 300 KB total; sha256 parity verified for **all 12 products** (six `md/` + six `reading/`), `REVIEW.md` and `README-reading-edition.md` between the `.tmp` copy and the delivered tree; the prior compass `## Risk Register` row 1 already assumes path-referenced replay + named refusal. **One file does *not* match and is recorded as a finding, not smoothed over**: the delivered `INDEX.md` differs from the local `.tmp` copy — the local one (4351 B, 2026-09-22) is the base table alone; the delivered one (7594 B, 2026-09-23 13:07) is that same base table (lines 1–60 byte-identical) **plus** an appended reading-edition section whose `BV1vNTqzFEve` row and totals are **stale** (`16173 / 16663 / 0.9706`, total `91188 / 95030 = 0.9596`) against the shipped file's own frontmatter and `README-reading-edition.md` (`16175 / 16655 / 0.9712`, total `91190 / 95022 = 0.9597`) — the same stale-prose-count class the wave's own close records for three other files, here in the delivered index. **Criterion 4 names it** so the replay treats it as a known difference to explain rather than a verifier defect, and D12 keeps the corpus path-referenced precisely so a stale *index* cannot silently redefine the acceptance numbers — the products' bytes are the evidence, the index is a report about them) |
| D14 | **Q2 converged — the refusal taxonomy is fixed at 16 rules, 14 error / 2 advisory**, in the contract `§E`. Errors: `accounting_invalid`, `marker_parity`, `evidence_missing`, `char_outside_routes`, `hotword_disagreement`, `timestamp_in_body`, `insertion_unexplained`, `deletion_unclassified`, `term_guard_tripped`, `twin_not_retained`, `seam_break`, `concat_mismatch`, `identity_mismatch`, `part_missing`. Advisories: `route_absent_for_part`, `hotword_screen_vacuous`. | The error/advisory split is the shipped defect-vs-advisory discipline (`coverage --quality`, `README.md:672-679`): an error is a rule whose violation makes the candidate an **untrue statement about its own inputs**; an advisory leaves every byte accounted for, so refusing on it would fake a defect and hide that the check was vacuous. Every rule is decidable from bytes + the record; configuration errors (`unknown --bvid`, unreadable `--candidate`) keep the shipped usage form and carry no rule id | architect round (chain 2/3) |
| D15 | **Q3 converged — the behaviour/protocol boundary is written down** in the contract `§F`: 11 tested behaviours (accounting identity, containment both stages, insert/delete classification + per-character insertion, term guard + twin locatability, marker vocabulary/parity, seam + byte-exact concat, timestamp absence, identity match, part presence, the mechanical half of the hotword screen, the print forms) vs 7 protocol items (route adjudication; polish-level judgement; the "only when the context forces exactly one reading" inference rule; never completing a hotword phrase; the boundary statement; what a record row's prose may claim; whether a site is undecidable). | Closing rule, which is what keeps D2 honest: **a command may refuse only what it can show from the bytes and the record; anything requiring a reading of the speech stays in the protocol** | architect round (chain 2/3) |
| D16 | **Q4 converged — the alignment builder persists.** JSONL, one file per selected part, at `<artifact-root>/alignments/<work_id>.jsonl`: line 1 a header record carrying all six counts, then one line per input unit `{kind, at, attached, evidence}`. **Never under `transcripts/{srt,txt,md,raw}`** (those four are the product families; the bundle marker proves them complete, so a fifth family would make `archive_bundle_complete` lie). Persistence being on is what makes D11(e)'s `--artifact-root` live on the builder — the only flag this ruling adds. | JSONL over one JSON document because the **unit of recovery is a line**: a truncated tail becomes a parse failure plus a header/line-count mismatch, i.e. a visible `accounting_invalid`, instead of a document that merely looks shorter (the 251/9607 lesson). A failed write is a usage-form configuration error (exit 1), never a candidate refusal | architect round (chain 2/3) |
| D17 | **The builder's surface carries the shipped `[--artifact-root <path>]` bracket** (amending D11's line, explicitly and on the record). The two verifiers keep `--bvid` + `--archive-root` only: they write nothing, and their `accounting_invalid` fires on counts a *candidate* carries, not on a persisted artifact. | D11(e) itself bounds this: a persistence ruling must not **silently** alter the interface — D16 (persistence on) needs a root, so the addition is recorded here rather than assumed. The bracket is the repo's own convention for a command that writes an artifact: eleven shipped commands declare exactly this optional bracket (`README.md:373-381`), and `asr` carries **both** roots at once (`cli.py:155-156`, `--archive-root` + `--artifact-root`), which is precisely this command's shape (a route read from the archive + a product written under the artifact root). The misattribution this corrects: a previous round cited "D11(e)'s `--artifact-root`" as already live on the builder — D11(e) never names that flag; its text is the bound quoted above. | PM reconciliation at lock preparation, forced by D16 + shipped evidence |

## Open Questions

| # | Question | Owner | Blocking? |
|---|----------|-------|-----------|

**Q1, Q2, Q3, Q4, Q5 and Q6 are all closed and their rows are withdrawn above — disclosed, not silently
deleted.** Q1 (operator surface) → **D11**; Q6 (corpus placement) → **D12**; Q2 (refusal taxonomy) →
**D14**; Q3 (behaviour/protocol boundary) → **D15**; Q4 (alignment persistence) → **D16**; Q5
(knowledge-surface placement) → the contract's **§G**, the attachment plan `mstar-compound` executes at
iteration-close (no `{KNOWLEDGE_DIR}` write in Phase 1/2, D7). **No blocking row remains and no row is
left open**: the Phase-1 review-and-edit chain's three seats have all landed (product-manager →
architect → writing-specialist).

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| 20260923-transcript-proofread | 校对 stage: two-route alignment builder + proofread-candidate verifier | Todo | Business plan 1/2 |
| 20260923-reading-edition | 精校 stage: reading-edition verifier + seam/concat checks | Todo | Business plan 2/2 |

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Spec freeze | 2026-09-23 | pending |
| Dev complete | 2026-09-23 | pending |
| QC complete | 2026-09-23 | pending |
| Iteration close | 2026-09-23 | pending |

## Acceptance Criteria

Each criterion is checkable by an operator running a command or reading a named file; where a criterion
cites the wave's numbers, the file to read is named.

1. **Alignment accounts for every input.** Run
   `bili-asr align-transcripts --bvid <bvid:pN> --archive-root <root>` on a part whose **two routes are
   reachable** — the ASR route from the bundle's `raw` sidecar (`transcripts/raw/<stem>.json`), the
   caption route from the store (`subtitle-ai`/`subtitle-cc`, read-only) — per **D13** (which amends D10;
   no store-side ASR writer ships this iteration). The command exits `0` and prints, per part,
   four numbers each side — `segments_in=<n> segments_attached=<n> segments_unattached=<n>` and
   `cues_in=<n> cues_attached=<n> cues_unattached=<n>` — so the two identities
   `segments_in == segments_attached + segments_unattached` and `cues_in == cues_attached + cues_unattached`
   are a subtraction the operator can perform on the printed line, non-zero-safe (the arithmetic is
   printed, not inferred) and the unattached bucket is never silently dropped. Closing line
   `align-transcripts: candidates=<n> aligned=<n> refused=<n>`, every count including the zeros.

   <!-- RESOLVED 2026-09-23 (D13): criterion 1's premise is measured-false against D10 and needs a PM ruling, not a product one. Measured 2026-09-23: **no archive store can hold an ASR route.** The store's only transcript writer validates `source_kind` against `ALLOWED_CAPTION_SOURCE_KINDS = ALLOWED_SOURCE_KINDS - {"asr-local"}` (`storage/models.py:476`, used at `storage/database.py:885-887`), it is the table's only `INSERT INTO transcripts` (`database.py:918`), and all seven stores reachable from here hold caption routes only (`subtitle-ai` 6/2/0/0/0/0/0 rows across `/root/e2e-asr/{asr-vs-subtitle,e2e50,longform-pair,subtitle-publish}/archive.db`, `/mnt/e/asr-archive-20/archive.db`, `.tmp/e2e-23191782/archive/archive.db`, `.tmp/qa-probe/F-A/archive.db`). Consequence: "a part the store holds both routes for" names no part that exists, so this criterion cannot be exercised as written, and criterion 4's replay cannot take either route from a store. D10 ("built from the store, not from loose JSON files") is a settled compass row and the route source also decides whether D11's builder needs route flags — so the ruling is the PM's. The two candidate rulings, both consistent with everything measured: (a) ship a store-side ASR-transcript writer first (widens this iteration into the audio/ASR iteration's blast radius — D5's own boundary), or (b) amend D10 so the builder takes its two routes from named operator files (`--asr-route <path> --caption-route <path>`, digest-pinnable) with the store read as the *preferred* source when both routes are present. The plans' Global Constraints and both criteria are written to survive either. -->
2. **Proofread verification refuses by name.** Run
   `bili-asr verify-proofread --candidate <path> --bvid <bvid:pN> --archive-root <root>`. A candidate
   obeying the stage's rules prints `<work_id>: ok (body_chars=<n> marks=<n> record_rows=<n>)` and exits
   `0`; a candidate violating any of — marker vocabulary normalised (`‹?›` vs `〔?〕`) with body-marker ↔
   record-row **parity** held, every recorded change carrying its evidence, character-level containment
   against **both** routes, hotword-table tokens screened — prints
   `<work_id>: refused (<rule>) at <location>` naming the rule and the location, and exits `1`. Never a
   bare failure. Closing line `verify-proofread: candidates=<n> ok=<n> refused=<n>`.
3. **Reading-edition verification refuses by name.** Run
   `bili-asr verify-reading-edition --candidate <path> --bvid <bvid:pN> --base <path> [--part <path>]…
   --archive-root <root>`. Exit `0` with `<work_id>: ok (body_chars=<n> base_chars=<n> deletions=<n>
   classified=<n> marks=<n> parts=<n>)`, or exit `1` with `<work_id>: refused (<rule>) at <location>` when:
   no `[hh:mm:ss]` appears in the body; body characters ⊆ base characters **and** routes; **zero
   unexplained insertions** (per character); every deletion classified into the three classes
   (filler·noise / adjacent-repeat-with-retained-twin / fragment) with the **term guard** — a deletion
   whose core is a hotword-table term the base uses is a refusal, not a repeat (the `此在` blind spot of
   2026-09-23: 「在此在」→「在」 must refuse); marker parity held; and, for a multi-part candidate, seam
   checks and byte-exact concatenation fidelity pass. Closing line
   `verify-reading-edition: candidates=<n> ok=<n> refused=<n>`.
4. **The six-item corpus replays offline and reproduces the recorded numbers.** Replaying the delivered
   corpus (D12's roots: `.tmp/proofread-work/{fixed,reading,reading-merged}/` locally, and
   `/mnt/123pan/bili-asr-e2e/proofread-transcripts/{md,reading}/` delivered) through both verifiers exits
   `0` per item with no refusal, and the printed counts equal the numbers the wave recorded in the two
   index files it left — `bilibili-asr-archive/.tmp/proofread-work/INDEX.md` (bases: per-item `body_chars`
   / ratio / `‹?›` / `校对记录` rows) and `…/.tmp/proofread-work/README-reading-edition.md` (editions:
   per-item `body_chars` / `base_chars` / ratio, the totals `91190 / 95022 = 0.9597`, `〔?〕` = 68, and
   `gap 0` for the `哎/唉` accounting). Any difference is named and explained in the task handoff; none is
   silently absorbed, and a missing or digest-mismatched corpus file is a **named refusal**, never a pass.
   No socket is opened and no audio is read. **One difference is already measured and must be treated as a
   known one, not a verifier defect**: the *delivered* `INDEX.md`'s appended reading-edition section
   carries stale figures for `BV1vNTqzFEve` and for the totals (`16173 / 16663 / 0.9706`; `91188 / 95030 =
   0.9596`) against the shipped file's own frontmatter and `README-reading-edition.md`
   (`16175 / 16655 / 0.9712`; `91190 / 95022 = 0.9597`) — record D12's finding. The six products' bytes,
   not the index, are the acceptance evidence.
5. **The surfaces carry the disclosures.** An operator can read them without the session: each new
   command's `--help` (`bili-asr align-transcripts --help`, `… verify-proofread --help`,
   `… verify-reading-edition --help`) and the written surfaces the plans name —
   `bilibili-asr-archive/docs/editorial-stages.md` and the README section for the two stages — each state
   what the stage does **not** prove: no audio was listened to; the judgement is the agent's, the commands
   verify bytes and the record; and both routes are machine transcripts, neither is ground truth.
6. **No new exit code, and no existing command's exit behaviour moves.** Observably: each new command's
   help path exits `0`, its usage/configuration path (an unknown `--bvid`, an unreadable `--candidate`)
   exits `1`, a refused candidate exits `1`, and no invocation of any of the three produces `2` (there is
   no socket to fail); the frozen exit taxonomy in `{SPECS_DIR}/asr-archive-cli.md` gains no row and its
   exit table is unchanged apart from the added-command enumeration; the shipped exit-behaviour suites
   stay green.

## Non-Goals

- **No re-proofreading or re-polishing of the six existing items** — they are acceptance evidence, not subject matter.
- **No ASR hotword-configuration change** — register row `20260922-proofread-wave · R1` keeps its trigger (next iteration).
- **No judgement inside deterministic commands** — D2. A verdict the command cannot defend from the bytes is not a verdict it may print.
- **No new exit codes; no change to the frozen `0/1/2` taxonomy** for existing commands.
- **No real-device/GPU/live E2E** — D6.
- **No `{KNOWLEDGE_DIR}` writes in Phase 1/2** — D7.
- **No migration or republication of existing products** — the stages add verification and recording, not a new layout for what is already published.
- **No fix for the pre-store archive-root reconciliation** (`20260922-target-host-reconciliation · R4`) — unrelated operator hygiene, keeps its row.

## Roadmap Position

- **Current iteration（iter-2026-09-transcript-editorial-stages）**：make 校对 and 精校 **supported stages** — the mechanical half as three commands (`align-transcripts`, `verify-proofread`, `verify-reading-edition`, surface fixed by D11), the judgement half as the stage contract — with the six-item corpus as replayable acceptance (path-referenced, sha256-pinned, D12).
- **Next iteration**：close `20260922-proofread-wave · R1` (high) — the ASR hotword list is an insertion source; its `target` is `src/bili_asr/asr.py` + the hotword measurement family, and the two stages shipped here are what make its corpus measurement repeatable. Owner: `project-manager` at the next planning round; trigger: this iteration merges.
- **Also next (fold into plans touching the same files)**: `20260922-proofread-wave · R2`'s count-guard rule is **closed by this iteration's alignment builder** (criterion 1) — its register close happens in place at iteration-close; `20260922-target-host-reconciliation · R3` (venv console-script drift) folds into the next plan touching `scripts/`; the low rows of the target-host reconciliation keep their triggers.
- **最终目标**：the pipeline's text products (proofread base + reading edition) are produced and **verified by shipped, repeatable stages** on any corpus slice, with the agent's judgement bound to a written protocol rather than a session.

## Delivery Branch Policy

| Field | Value |
|-------|-------|
| `iteration_base_branch` | `main` |
| `spec_integration_branch` | `iteration/iter-2026-09-transcript-editorial-stages` |
| `target_branch` | `main` |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| The six-item corpus lives outside the repo and could be unavailable to a verifier run | Med | Med | **Decided — D12**: replay is **path-referenced** with the files **pinned by sha256**; the plans read the local `.tmp/proofread-work/` copies (verified byte-identical to the delivered tree) or the `/mnt/123pan/` delivery, and a missing or digest-mismatched file is a refusal **naming that file**, never a silent pass. Accepted cost, stated: the replay is **not hermetic** (CI cannot run it) — the alternative was putting ~0.9 MB of lecture transcripts into a public repo, which is the first transcript redistribution this project would ever carry and would make the replay prove something about a copy |
| Verifier rules over-fit the six items and refuse legitimate future candidates | Med | Med | The refusal taxonomy is the architect's (Q2 → **D14**); rules are stated as **classes** with the offending location, an advisory line exists for findings that must not fail a candidate (D11(c)), and the contract names which are error vs advisory |
| "Judgement cannot be mechanised" collapses into shipping nothing | Low | High | The split is explicit (D2) and the mechanical half is enumerated by criterion (alignment accounting, containment, classification, term guard, parity, seams) |
| **A criterion's premise is measured-false**: no store can hold an ASR route, so D10's route source names no part that exists | High | High | **Ruled 2026-09-23 — D13** after being escalated rather than papered over: the escalation carried the measurement (`storage/models.py:476`, `storage/database.py:885-887`/`:918`, seven stores checked) and the two candidate rulings. Both plans' Global Constraints and both criteria are written to survive either ruling, so the fallback does not reopen the iteration's direction |
| The scratch tool's 40-char-window false positives get re-shipped | Med | Med | The wave recorded the fix (window size ±200 chars, core-character check); Q3 → **D15** makes the boundary explicit and the plan cites the measured false-positive episode |

## Iteration package

| Path | Purpose |
|------|---------|
| `direction-lock.md` | Autonomous lock record (kept after the draft) |
| `guides/` | Exploration, process notes |
| `specs/` | Iteration-scoped spec drafts (the editorial-stage contract) |
| `README.md` | Package document index |

## Phase-1 findings log (chain rounds)

| # | Finding | Disposition |
|---|---------|-------------|
| F1 | **D10's premise was measured false**: no archive store can hold an ASR route (only caption kinds are writable; the store has no hotword surface). | **Ruled — D13**: the ASR route is read from the bundle's `raw` sidecar; no store-side ASR writer in this iteration. Both plans already isolate the route source to the CLI task, so no rework. |
| F2 | Delivered `INDEX.md` carried stale reading-edition numbers (`BV1vNTqzFEve` 16173/16663/0.9706, totals 91188/95030/0.9596) — the same stale-prose class the wave's close recorded. | **Fixed by the PM on the host** (both rows now 16175/16655/0.9712 and 91190/95022/0.9597, matching the shipped files' frontmatter and `README-reading-edition.md`); the replay no longer needs to explain it as a difference. |
| F3 | Measured window false-positive class (±40-char window → 50 false "content loss" hits, **0 real losses** — `README-reading-edition.md:82`; the fix was ≥ ±200 chars + core-character check, `±200 字窗口检验` — `.tmp/proofread-work/reading/BV1vNTqzFEve.p0.p3.notes.md`). | Carried into the edition plan's Global Constraints as a **fixture requirement** (the shipped rule must accept what the narrow window refused). |
| F4 | The architect's first seat **exhausted its budget with zero writes** (broad reading, no slice discipline) — a process failure, not a design one. | **Recovered by the PM**: the round was re-scoped into two small seats with the citations inline and an explicit write-first rule; seat 2a landed the contract's `§E`/`§F`/`§F.1` in one heredoc. Recorded here because the same failure mode hit the wave's pilot seat earlier — the durable lesson is *hand a seat its citations, not a reading list*. |
| F5 | The plans still describe the pre-D13 route source and a conditional ("if the PM amends D10") that no longer applies. | Handed to architect seat 2b with the five exact replacement strings; the plans' `## Operator surface` gained the taxonomy vocabulary and the `<artifact-root>/alignments/` path (D14/D16). **Seat 2b landed the surface edits but four pre-D13 phrasings survived** (plan 1's clarify gate, Global Constraints and Task-3 verification; plan 2's clarify gate) — **closed by writing-specialist, chain round 3**: each now reads D13 as a ruling, and the removed sentence's mis-attribution of the proposed route flags to **D11(e)** (which is `--artifact-root`) is gone. |
| F6 | **The sealed contract carried an unsourced quantitative claim**: §C asserted a caption-route "5.6–10.9 % CER (caption-as-reference)". The PM's claim audit searched the register, the delivered corpus (`INDEX.md`/`REVIEW.md`/`README-reading-edition.md`), the local wave tree and the alignment JSONL — **no source on disk** (the `5.6`/`10.9` strings in the JSONL are per-block `similarity` values). | **Corrected by the writing-specialist round** into a categorical statement that cites the repo's real reference discipline (`REFERENCE_AGREEMENT_FLOOR = 0.95`, `quality.py:58`; the capped comparison at `_MAX_COMPARE_CHARS = 20 000`, `quality.py:104`/`:549`) and the wave's item-by-item adjudication — no number retained. Durable lesson attached at close to `claim-scope-discipline.md` (contract §G row 2a). |
| F7 | **The PM's own citation instruction was wrong**: the audit table said the "≥ ±200 chars + core-character check" fix was recorded in the wave README; it is not (`grep '200'` there = 0 hits) — it lives in the wave's per-piece notes (`±200 字窗口检验`, `.tmp/proofread-work/reading/BV1vNTqzFEve.p0.p3.notes.md`). | **Caught by the writing-specialist, verified by the PM**, and the attribution corrected in plan 2's Global Constraints, this log's F3 and the risk register. Lesson recorded here: an orchestrator's recollection of *where the evidence lives* is itself a claim that must be checked before it is handed to a seat as fact. |
| F8 | **D11's fixed surface could not carry D16** as written: the builder had `--bvid` + `--archive-root` only, while D16 (persistence **on**) needs an artifact root — and a round had cited "D11(e)'s `--artifact-root`" as if it were already there (D11(e) actually says a persistence ruling must not **silently** alter the interface, and names no flag). An implementer would have hit the plan's own "a new flag appears → STOP" rule. | **Reconciled — D17** (the shipped `[--artifact-root <path>]` bracket, explicitly on the record; evidence `README.md:373-381` + `cli.py:155-156` where `asr` carries both roots). Caught by the plan-1 sealing seat as an observation on its own edit, verified and ruled by the PM; recorded rather than left as a contradiction. |
| F9 | **The chain's closing writing-specialist re-verification seat failed mid-read** (its second round on this iteration; the failure mode is the same broad-reading burnout as F4). | **Recovered by the PM, disclosed rather than papered over**: the six closing checks (live markers, unsourced numbers, rule-id consistency, D-number consistency, command/flag surfaces, structure census) were run at the control root with raw output kept in `.tmp/dispatch/closing-verification.txt` — all six pass. The PM is a separate seat from the architect producers, so the producer/verifier separation the harness requires still holds; what it does *not* hold is a same-role second pair of eyes, and that is the gap this row records. |
