---
report_kind: qc
reviewer: qc-specialist-3
reviewer_index: 3
plan_id: "20260911-subtitle-cli-cutover"
verdict: "Approve"
generated_at: "2026-09-11"
---

# Code Review Report

## Reviewer Metadata

- Reviewer: @qc-specialist-3
- Runtime Agent ID: qc-specialist-3
- Runtime Model: cn-sekirocloud/deepseek-v4.1-flash (host default in `/root/.dsh/settings.yaml`; the leaf session does not expose its own route — tier `standard` per Assignment)
- Review Perspective: QC seat 3 of 3 — performance/reliability lens **plus** this Assignment's lens emphasis: evidence honesty (the plan carries the iteration's acceptance evidence), operator readiness, and the iteration's closure obligations
- Report Timestamp: 2026-09-11T17:30+08:00

## Scope

- plan_id: `20260911-subtitle-cli-cutover`
- Review range / Diff basis: `c5a9b82..8373817` (4 commits) — copied verbatim from the Assignment
- Working branch (verified): `feature/20260911-subtitle-cli-cutover` (`git branch --show-current`)
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260911-subtitle-cli-cutover` (`git rev-parse --show-toplevel`), package root `bilibili-asr-archive/`
- HEAD verified: `8373817c4c25c5edae9446b48396fc5c8800565f`; `git log c5a9b82..8373817` → exactly the 4 disclosed commits (`8ec992b`, `c501d9a`, `d5c0f9e`, `8373817`); `git status --porcelain` empty
- Files reviewed: 13 (`git diff --numstat c5a9b82..8373817` recomputed by this seat: 13 files, +4597 / −574 — matches the Assignment)
- Commit range: identical to the Review range (`c5a9b82..8373817`)
- Analysis methods: `git diff --stat/--numstat/--check/--name-only`, `git log`, `read`, `grep` over the review package (`review/branch-diff.md`, `task-1/2/3-review.md`, `progress.md`) and over the shipped sources/tests/docs — **not** test/build/lint runs, not `git` mutations, no network
- Deep review: **triggered** (S1: 4597 changed lines / 13 files ≥ 200 lines and ≥ 8 files; S6: diff spans `src/bili_asr/`, `src/bili_asr/services/`, `tests/`, `tests/fixtures/`, `docs/`, repo-root `README.md` — ≥ 3 module boundaries). S2/S4/S5 not triggered (no auth/payment/migration paths, no production DDL in this diff, no high-risk marker in the plan metadata); S3 partially (new module, but the domain is already in `{KNOWLEDGE_DIR}`).
- Lenses applied: **Performance Lens**, **Reliability Lens**, **Enforcement-Path Lens**, **Ownership / Derived-State Lens** (QC3 defaults) + **Bounds / Real-Entry-Path** checks where the live-evidence question required them. Findings that came from a lens carry `Source Type: deep-lens: <name>`.
- Independent verification this seat performed: `git diff --check c5a9b82..8373817` → **clean** (Done criterion "`git diff --check` clean" confirmed, not taken from the report); the branch touches **no** production file that another plan owns (`git diff --name-only` = README + docs + `cli.py` + new `services/subtitle_ingest.py` + tests/fixture); `TranscriptRepository.__init__`'s `require_subtitle_schema` guard was already present **at base** `c5a9b82` (`git show c5a9b82:…/storage/database.py`, introduced by `4dcbf5d`) — so the plan's carried "fix wave 2" item is already cashed and is not an open obligation of this branch.

## Findings

### 🔴 Critical

None.

### 🟡 Warning

None.

### 🟢 Suggestion

- **[Q3-01] The default selection tie-break across two *different* non-default language families is not what the operator-facing prose says, and no test pins that corner.** `_family_rank` returns the same rank (`len(("zh","en")) == 2`) for every family outside `zh`/`en`, so the minimum key `(family_rank, is_ai, upstream_index)` lets the CC-before-AI preference decide *across* distinct rest-families: for tracks `(ai-ja @0, fr-CC @1)` the French uploader track wins although it appears later upstream. The docs state "every remaining family in upstream order — and prefers an uploader caption … over a machine one **inside the same family**" (`docs/metadata-storage.md:198-202`), and the README repeats "the rest in upstream order" (`README.md:621-626`); the plan's Global Constraints say "then the rest in upstream order, with CC before AI inside a family". The shipped key is exactly what the locked spec §3 prescribes (`specs/subtitle-cli-contract.md:193-198`), so **code == spec** and the prose is the imprecise artifact; the existing preference test pins only `zh>en>rest` with equal kinds (`tests/test_subtitle_cli.py:386-404`), never a cross-family CC/AI pair.
  - Source Type: deep-lens: Enforcement-Path Lens
  - Verification: diff/read/grep anchor — `src/bili_asr/services/subtitle_ingest.py:119-125,160-167` vs `docs/metadata-storage.md:198-213`, `README.md:621-632`, plan `## Global Constraints` (selection bullet), `specs/subtitle-cli-contract.md:193-198`, `tests/test_subtitle_cli.py:386-409`
  - Expected vs observed: expected the documented family rule to describe the shipped tie-break verbatim vs observed the docs' "inside the same family" qualifier is false for two distinct non-default families (CC wins over upstream order). Impact on a Chinese archive: nil today (the mismatch needs two visible non-`zh`/`en` families of different kinds, and the selection is printed and `--language`-overridable). Fix (PM's choice): one docs clause reworded to "the CC-before-AI preference applies across the remaining families; upstream order settles same-kind ties", **or** a test pinning `(ai-ja @0, fr-CC @1) → fr-CC` so the behaviour is explicit.
  - Confidence: High

- **[Q3-02] The probe's stdout is the one operator surface that prints an upstream free-text field, and it is never marker-scanned; the docs sentence next to it over-claims.** `probe … track <lan> <ai|cc> <lan_doc>` (`src/bili_asr/cli.py:812`, documented at `docs/metadata-storage.md:117` and by locked spec §2.1) renders upstream `lan_doc`; the gateway only requires it to be a non-empty string and trims it (`sources/bilibili_api_gateway.py:295-301`, `sources/models.py` `_text`: non-empty only — no length cap, no control-character rule). Yet the sentinel scan runs on the harvest output only (`tests/test_live_subtitle_cli_smoke.py:795`, rehearsals `:1037/:1083/:1118`); the probe's stdout is credential-scanned (`:777`) but never run through `assert_leaks_no_markers`, and no rehearsal scripts a marker-bearing label, so the scan *could not* fire. The docs sentence "No output carries a credential, a signed URL, a raw body, or **upstream message text**" (`docs/metadata-storage.md:153`) therefore contradicts the line shape documented four lines above it. Live, the sentinel scan is vacuous anyway (the fake seam is not installed), so the meaningful live check is the credential one — which does cover the probe.
  - Source Type: deep-lens: Enforcement-Path Lens
  - Verification: diff/read/grep anchor — `tests/test_live_subtitle_cli_smoke.py:795` vs `:777` vs `:1037/:1083/:1118`; `fixtures/fake_bilibili_gateway.py:150-192,828-841` (NO_LEAK_MARKERS + scanner); `src/bili_asr/cli.py:812`; `docs/metadata-storage.md:117,153`
  - Expected vs observed: expected every output path that can render an upstream value to be scanned (and the docs' no-upstream-text sentence to be scoped) vs observed the one such path is unscanned and unscoped. Non-blocking (the gateway never reads `subtitle_url`, so a signed URL cannot reach the DTO; a raw body cannot appear). Fix (this is Task-3 Minor 2, independently re-judged): scope the docs sentence to the error/evidence paths and, cheaply, script a marker-bearing `lan_doc` in the probe rehearsal plus `assert_leaks_no_markers(probe_out + probe_err, …)`; optionally bound the printed label (length/control characters) since it is the only unbounded upstream string on an operator surface.
  - Confidence: High

- **[Q3-03] Three fields of the acceptance evidence line are printed but tied to nothing, and a forgotten credential reads as a legitimate skip.** `with_tracks`, `stored` and the printed `run_id` are parsed by the readers (`tests/test_live_subtitle_cli_smoke.py:340-455`) and re-emitted on the one count-only evidence line (`:832-847`) but never asserted live (the printed `run_id`↔row pairing *is* pinned offline, `tests/test_subtitle_e2e.py:623-631`); and because the smoke derives its expectation from the same environment the command reads, an operator who forgot to source the credential gets `sessdata=absent` + `tracks=0` and pytest reports **skip**, not "you forgot the credential" (`:711-725,845-847`).
  - Source Type: deep-lens: Ownership / Derived-State Lens
  - Verification: diff/read/grep anchor — `tests/test_live_subtitle_cli_smoke.py:349,383,412,804-805,832-847` (no assertion on `with_tracks`/`stored`/printed `run_id`) vs `tests/test_subtitle_e2e.py:623-631` (the run_id pairing is pinned offline)
  - Expected vs observed: expected every fact printed on the acceptance line to be tied to its authoritative source (or the fact's absence to be visible) vs observed three printed facts are only observed. Impact: a reader of the recorded line relies on the smoke's own parse; the arithmetic covers `stored` and `with_tracks` only indirectly. Fix (folded by PM as Task-3 Minors 4+5): `assert harvest.stored == 1`, assert the printed `run_id` against the persisted run row, and make an opted-in run with `sessdata=absent` fail loudly (or at minimum add the one-sentence operator reading to `docs/metadata-storage.md:501-509`).
  - Confidence: High

- **[Q3-04] The docs' recorded live observation drops `run_id=`, which the committed code prints.** `docs/metadata-storage.md:510-519` quotes `… tracks=ai-zh:ai harvest_exit=0 attempted=1 stored=1 …`; `tests/test_live_subtitle_cli_smoke.py:838` prints `harvest_exit={harvest_exit} run_id={harvest.run_id} attempted=…`. Every other field is byte-identical to the implementer report's copy of the line (`implementer-task-3-report.md:93`). Cosmetic, but the same docs promise the run id is always printed, so the abridged quote reads as inconsistent with the contract it documents. (Task-3 Minor 3.)
  - Source Type: read
  - Verification: diff/read/grep anchor — `docs/metadata-storage.md:510-519` vs `tests/test_live_subtitle_cli_smoke.py:836-843` vs `implementer-task-3-report.md:93`
  - Expected vs observed: expected the quoted evidence line to be the committed code's output verbatim vs observed `run_id=…` elided. Fix: paste the line with `run_id=` (or mark it abridged).
  - Confidence: High

- **[Q3-05] Documentation/spec completeness on the *failure* and *rebuild* paths (four clauses, all one-line fixes).** (a) `harvest-subs` is a writer command, so `main()` takes the lock **before** the handler runs the database check (`cli.py:2492-2501` → `coordinator.py:70-94` → `persistence.py:55-56` `os.makedirs` + `open(lock_path,"a+b")`): a harvest pointed at a missing/mistyped `--archive-root` still leaves `<root>/coordinator/archive-writer.lock` and exits 1 with "no archive database" — nothing in the docs warns that the failed invocation creates the root; the docs' lock section only says what a *completed* harvest leaves (`docs/metadata-storage.md:184-188`, `README.md:655-659`). (b) Consequently `specs/subtitle-cli-contract.md:304-306` ("neither command creates a file under the archive root except `harvest-subs`'s database writes") is literally false — already dispositioned by Task-1 ⚠️2 → Task-3 ⚠️4, and this seat agrees no fix round is needed; a spec errata line at iteration close is the honest closure. (c) The rebuild instruction "delete `archive.db` and re-run `fetch-meta`" (`docs/metadata-storage.md:247-250`, `README.md:639-646`) does not mention that a bare `fetch-meta` stops at the default 10-page bound (`config.py:32`; documented separately at `docs/metadata-storage.md:383-385`), so rebuilding a corpus collected beyond page 10 silently re-collects a subset. (d) The canonical Workflow block (`README.md:100-125`) now places `probe-subs`/`harvest-subs` directly above `download-audio --missing-subs` with no caveat, although the ⚠️6 boundary (stated three times elsewhere: `docs/metadata-storage.md:252-268`, `README.md:647-654`, `README.md:345-352`) means the audio feeder gains nothing from the preceding step.
  - Source Type: deep-lens: Reliability Lens
  - Verification: diff/read/grep anchor — `cli.py:2435-2445,2486-2501`; `coordinator.py:57,70-94`; `persistence.py:33-56`; `docs/metadata-storage.md:184-188,247-250,383-385`; `README.md:100-125,639-646,655-659`; `src/bili_asr/config.py:27-32`; `specs/subtitle-cli-contract.md:300-306`
  - Expected vs observed: expected the operator docs to describe the shipped failure/rebuild paths as precisely as the success path vs observed four under-specified spots. None changes shipped behaviour. Fix: one clause each — "the lock is taken before the database check, so even a failed harvest creates `<root>/coordinator/`"; a spec errata line; "re-run `fetch-meta` with the `--limit-pages` bound you need (or repeat with `--resume`)"; and a pointer in the Workflow block to the SQLite↔manifest boundary.
  - Confidence: High

- **[Q3-06] Two deferral statements do not carry the owner + trigger the harness Durable Roadmap Gate requires.** The plan's Durable Roadmap block names owner/trigger for the projection/audio-queue/contract items (plan `## Durable Roadmap and Dependencies`, bullet "Deferred with a named owner (`project-manager`, trigger "this iteration delivered")"), but two neighbouring statements are open-ended: "Deferred: retiring `bili_client`'s subtitle methods and migrating the ASR/pilot path" (no owner, no trigger) and the recorded nit **M2** — `finish_acquisition_run` sits outside the interrupted-run guard, "the next owner of the run lifecycle decides whether to close it" (`src/bili_asr/services/subtitle_ingest.py:351-358,374-387` — verified: the finish call is outside the `except BaseException` block, so on an abrupt terminate the run row can stay `running`, exactly as the shipped metadata run discipline behaves). In substance M2 defers a lifecycle invariant to an unnamed future owner.
  - Source Type: manual-reasoning (harness rule: `mstar-harness-core` → Durable Roadmap Gate)
  - Verification: diff/read/grep anchor — plan `## Durable Roadmap and Dependencies` (bullets 2 and the "Recorded (nits …)" block) vs `src/bili_asr/services/subtitle_ingest.py:351-358,374-387`; register `.mstar/projects/_default/residuals.json` currently holds only R1 (`20260911-subtitle-gateway`)
  - Expected vs observed: expected every "deferred / next owner" statement to name owner + trigger + done-definition (or be registered) vs observed two statements leave it implicit. Fix: one plan-text edit naming `project-manager` + trigger "next plan that touches the acquisition run lifecycle (expected: the audio/ASR iteration)" for M2, and an owner/trigger for the legacy retirement item; alternatively register M2 as a `low` residual. **Not blocking**: M2 mirrors shipped metadata behaviour, and M4 / the Task-1–2 nits are already recorded acceptances.
  - Confidence: Medium (the Gate reading of M2 is a judgement call; the code anchor and the missing owner/trigger are factual)

### ⚪ Unconfirmed

None. Every finding above has an intact diff/read/grep evidence channel. The runtime-proof gaps (live run reproducibility, offline suite counts) are **not** findings — they are hand-offs to L4/QA, listed under ⚠️ below per `reviewer-workflow.md` § "Evidence gaps (hand to QA — do not self-execute)".

---

## Focus 1 — Evidence honesty: the recorded live run and the three-invocation ledger

### 1.1 What the recorded line actually is

`live subtitle CLI smoke evidence: … part_source=fixed-sample work_id=BV1S8hA6MEvy:p0 sessdata=present probe_exit=0 probed=1 with_tracks=1 without_tracks=0 probe_failed=0 track_count=1 tracks=ai-zh:ai harvest_exit=0 run_id=1de9b7cb7cd141bfa7114112212188db attempted=1 stored=1 unchanged=0 no_subtitle=0 failed=0 remaining_without_transcript=0 source_kind=subtitle-ai language=ai-zh version=1 segments=2913 transcripts=1 attempts=1 pending_after=0` (SDD `progress.md:71-75`, `implementer-task-3-report.md:93`, `docs/metadata-storage.md:510-519`).

The line is **test-composed** (the house pattern — `tests/test_live_metadata_smoke.py:353` does the same), which is honest only if every field is derived and checked. This seat independently confirmed the derivation for each field group in the committed code:

| Field group | Where it comes from | Assertion that would fail if it were absent |
|---|---|---|
| `part_source`, `work_id` | constant provenance + the seeded row (`:131-143,259-287`) | the string identity is asserted against *both* readers' parse of the shipped CLI output (`:383`, `:432`) and against the seeded pending row (`:479-499`) |
| `sessdata=present` | `_credential_label(_credential_expectation())`, from the same env the command reads (`:223-232,323-337`) | the CLI's own first line must equal that token (`:329-337`), and the persisted run row must carry `credential_present == int(expect)` (`:557-573`) |
| `probe_exit`, `harvest_exit` | `main()` return values | `:788`, `:803` |
| `probed/with_tracks/without_tracks/probe_failed/track_count/tracks` | full-match regexes over the CLI's stdout (`:173-194,340-395`) | `probed == 1` (`:349`), one track line per listed track (`:378`), the zero-track marker (`:369`) |
| `attempted/stored/unchanged/no_subtitle/failed/remaining_without_transcript` | the same harvest summary regex (`:398-452`) | `attempted == 1` (`:412`), `(failed, no_subtitle) == (0,0)` and `remaining == 0` (`:804-805`) — `stored` only indirectly (Q3-03) |
| `source_kind/language/version/segments/transcripts/attempts/pending_after` | the rows the CLI wrote (`:501-592`) | enum membership, non-empty language, `version == 1`, 64-char hash, ordinal-ordered non-empty segments, exactly one terminal run row + one linked attempt, `v_pending_subtitles` empty |
| root file set | `_archive_files` walk | exact set == `[archive.db, coordinator/archive-writer.lock]` (`:675-689`) — proves no sidecar, no `subtitles/raw/`, no `transcripts/srt/` |

Two structural facts that make "this was really live" more than a claim: the live test requests **no** seam fixture and the suite has **no** autouse seam (`tests/conftest.py` has only the `torch` mock; `fake_gateway_seam` is requested explicitly by rehearsal tests), and the smoke's own loud-fail guard requires the pinned distribution (`:203-220`). Its documented bounded outcomes (stored / `tracks=0` / `not_found` / `rate_limited`) each assert their shape and print before skipping (`:711-725,845-847`), so a run that stored nothing cannot read green — verified, not merely quoted.

### 1.2 What the evidence **proves** for the iteration

Assuming the recorded line is genuine, it proves that the *shipped* CLI + real adapter over the pinned distribution + real SQLite repository completed one bounded probe and one bounded harvest of one real public part (`BV1S8hA6MEvy:p0`), with the operator credential in effect, inside a temporary root, and that: one visible track `ai-zh`/`ai` was listed (probe exit 0); the harvest stored version 1 as `subtitle-ai`/`ai-zh` with 2913 ordered segments and a hash (A2's row shape, live); exactly one terminal run row (`kind=subtitle`, selector `pending`/limit 1, `credential_present=1`) and one linked attempt row (`stored`) exist; the part left the pending enumeration; and the root held only `archive.db` + the writer lock (A7, live). It also proves the acceptance evidence was taken **through a credential** (the run row's `credential_present=1` is inside the asserted set) and that no credential value reached stdout, stderr or any persisted row. That is exactly the "real normalized rows" branch of A11's live clause, for the one bounded part the plan budgeted.

### 1.3 What it does **not** prove

- Nothing about the corpus, caption coverage, or caption quality — and no output claims any (A9/A12 verified).
- Nothing beyond **one** part: no live evidence for re-acquisition (`unchanged`), version 2, captionless parts, the `failed` mapping, or enumeration rotation (A3/A4/A5/A6/A10 rest on offline/P1/P2 evidence only, by design).
- That the endpoint keeps answering that way — the sample is dated and replaceable in one line (`:126-133`).
- That the printed `run_id` equals the persisted row *live* (the pairing is only pinned offline, `tests/test_subtitle_e2e.py:623-631`). `segments=2913` is an observation, not a contract: the live assertion sweeps the segment timeline and non-empty intervals, deliberately not the count.
- **Its own existence.** No artifact of the run survives (temporary root removed; the range holds a single test commit, `d5c0f9e` @ 17:16:27, i.e. after all three invocations — `git log --date=iso`). The line is the operator's record, and it cannot be re-derived from this seat (live network forbidden by the dispatch). This is the standard L3→L4 hand-off, not a defect.

### 1.4 Is the three-invocation ledger complete and honest?

**Complete and honest as far as a read-only seat can judge; accept it, and record the deviation rather than normalize it.** The ledger (`implementer-task-3-report.md:96-117`, PM summary in `progress.md:87-92`) states all three invocations, the cause of each, that **no evidence is claimed from attempt 1** (its anonymous `sessdata=absent tracks=0` observation is described as the documented "nothing visible now" reading), and that attempts 2 and 3 produced the same bounded facts with only a presentation change between them. This seat's independent checks:

- The claimed attempt-1 causes leave **visible structural traces**: the credential fixture is explicitly **not** autouse with a docstring naming exactly that trap (`tests/test_live_subtitle_cli_smoke.py:861-871`), and `_flush_output` exists solely to drop the smoke's own preamble before the readers see command output (`:873-881`, called once at `:764`, matching "the second `capsys` flush was removed so a future stray print fails loudly" — with one flush, the harvest reader sees only the harvest's output, `:766,791`).
- Internal consistency: the folding of probe counts into the line and the removal of the second flush are exactly what distinguish attempt 2's description from attempt 3's, and the committed line does carry the probe counts.
- **Not verifiable**: the "presentation-only" and "no assertion changed" claims are structural inferences, because the range contains a single test commit written after all three runs; attempt 1/2 file states are unrecoverable from git. The cost is bounded (2–3 fail-fast calls per invocation, no retry, no call-shape change, no run discarded because of an upstream answer), so this is not a discipline violation of the "no unbounded probing" rule — but the plan budgeted one live run, and the extra invocation was avoidable in principle (a smoke that asserts the credential expectation *before* spending a call would have failed attempt 1 faster — see Q3-03).

**Where to record it — durable note or register entry? Largely the durable note; not a register entry.** The register (`{PROJECT_DIR}/_default/residuals.json`) is the **finding/severity SSOT with owner + closure lifecycle**; the deviation is a process record with no defect and no fix, so an entry there would be an unclosable `low` finding that misrepresents a disclosure as a defect and pollutes the register the iteration-close reads. The right homes are (a) the plan's durable summary / `## Durable Roadmap and Dependencies` (already done — `progress.md:92`), carried into the plan's Review Gate Summary, and (b) the iteration's Quality Gate Summary at close, plus a compound/knowledge note if the iteration close promotes live-smoke discipline. The **actionable** residue is not the deviation but the slow-fail behaviour of the smoke's credential check (Q3-03) — if PM wants machine-tracking at all, that is the item worth a `low` register entry with a named owner, not the invocation count.

---

## Focus 2 — Iteration acceptance mapping (compass `## Acceptance Criteria`, A1–A12)

Owner keys: P1 = `20260911-subtitle-gateway` (Done), P2 = `20260911-transcript-storage` (Done), P3 = this plan.
Status legend: **S** = satisfied by evidence in the tree; **(o)** = satisfied but the specific assertion is offline-only by design; **(p)** = satisfied by a previously closed plan's evidence, not re-pinned here.

| # | Status | This branch's evidence (plus earlier plans) | Flags / residual notes |
|---|---|---|---|
| A1 | **S** | `cli.py:802-812` prints `sessdata:`, one `probe <work_id> tracks=<n>` line per part in order, the explicit `(no subtitles visible)` marker (`:807-809`), `track <lan> <ai\|cc> <label>` lines and the `probe-subs: probed=… with_tracks=… without_tracks=… failed=…` summary; shapes pinned offline (`tests/test_subtitle_cli.py:430+`, `tests/test_subtitle_e2e.py:638-691`, smoke readers `:173-194,340-395`); live: `probe BV1S8hA6MEvy:p0 tracks=1` + `tracks=ai-zh:ai`. | **(o)** zero-track and multi-track shapes are offline-only (the live sample exposed one track); a live `tracks=0`/`not_found` reading is a documented skip, not a failure. |
| A2 | **S** (p) | Live rows: `source_kind` in `ALLOWED_CAPTION_SOURCE_KINDS`, non-empty `language`, `version == 1`, 64-char hash, ordered non-empty segments (`test_live_subtitle_cli_smoke.py:515-552`); offline row assertions `tests/test_subtitle_e2e.py:273-374`; FK/`video_parts` linkage via the join assertion (`:518-525`). `floor(seconds*1000)` is pinned in P1 (`tests/test_bilibili_api_gateway.py:2686`), code at `sources/bilibili_api_gateway.py:455-469`. | **(p)** the ms conversion rule is not re-pinned in this branch (P1 evidence, unchanged by this diff). |
| A3 | **S** (o) | `tests/test_subtitle_e2e.py:375-438` (same body → `unchanged`, no new version, no duplicate segments) and `:439-497` (changed body → `stored … v2`, v1 still readable through `TranscriptRepository.read_transcript`, both hashes and both segment sets compared). | **(o)** offline only; the single live run stored v1 (`unchanged`/v2 are not live-proven). |
| A4 | **S** (o) | `tests/test_subtitle_e2e.py:501-546` (captionless + failing part: bounded attempt rows, run `partial`, printed counts, exit 0), `:548-598` (a captionless part stores later, never-attempted first); service mapping `subtitle_ingest.py:457-468,528-557`; the live smoke's non-storing path asserts the same evidence shape (`test_live_subtitle_cli_smoke.py:595-650`). | **(o)** the `no-subtitle` path is live-pinned only as a rehearsed/recorded alternative, not exercised by the recorded run. |
| A5 | **S** (p/o) | Mapping in the service (`:455-479`), per-part attempt rows carrying the scalar code (`tests/test_subtitle_e2e.py:534-543`), never-claims-success (`:538-545`), the smoke's refusal ladder (`test_live_subtitle_cli_smoke.py:151-158,653-672`); the upstream→code taxonomy itself is P1's. | **(p)** the recorded live run had no failure code, so `rate_limited`/`transport_error`/`shape_error`/`-101 → not_found` rest on P1 + offline evidence. No fallback reading was needed for A5 in this branch. |
| A6 | **S** (p) | Live run asserts one `acquisition_runs` row = `kind=subtitle`, selector `pending`/NULL, `requested_limit=1`, `credential_present=1`, terminal `complete`, plus one linked attempt (`test_live_subtitle_cli_smoke.py:554-581`); E2E asserts `ingestion_runs` is untouched by construction (no metadata repository is constructed, `cli.py:751-756,835-840`). Schema/repository pinning is P2's. | none |
| A7 | **S — strongest live evidence** | Live root file set exactly `[archive.db, coordinator/archive-writer.lock]` (`:675-689`); E2E no-sidecar/no-projection over the temp root (`tests/test_subtitle_e2e.py:692-716`) and probe-leaves-only-the-DB (`tests/test_subtitle_cli.py:1031-1035`); "no read" is structural: neither handler imports a manifest module. | none. (The lock file is *expected* here and documented — `docs/metadata-storage.md:182-194`.) |
| A8 | **S** | Live credential scan over stdout+stderr and every persisted row, with the assertion-introspection trap defused (`:692-708,777,796-798,829`); E2E sentinel scans with a non-vacuous positive control (`tests/test_subtitle_e2e.py:717-751`); the adapter never reads `subtitle_url` (`bilibili_api_gateway.py:281-304`). | **Q3-02**: the probe's stdout is credential-scanned but not sentinel-scanned, and the docs' "no upstream message text" sentence is unscoped next to a documented `lan_doc` line. Structural A8 still holds (no signed URL/body can reach the DTO). |
| A9 | **S** | `cli.py:898-914` prints all four counts including zeros, the run id, presence and `remaining_without_transcript`; exact printed-line equality incl. the `attempted=0` run (`tests/test_subtitle_e2e.py:601-633`), all four counts + presence in the live line; no coverage claim anywhere (grep of the docs' subtitle sections). | **(o)** `with_tracks`/`stored`/printed `run_id` are printed but not asserted live — Q3-03. |
| A10 | **S** (o) | `tests/test_subtitle_e2e.py:548-598` drives three successive bounded runs (FIFO rotation; never-attempted first; a captionless part stores later) and asserts the exact listing order; the ordering contract lives in the view (`schema-transcripts.sql:100-141` — newest attempt via `ROW_NUMBER … ORDER BY finished_at DESC, run_id DESC`, `attempted` flag, transcript/gone exclusion) and in `database.py:1091-1123` (SQL `LIMIT` applied — bounded query, no full-table materialisation). | **(o)** offline only (the live run had a single part, `pending_after=0`). |
| A11 | **S — primary branch taken, no fallback needed** | Offline E2E exists and is offline by construction (shared protocol double, no seam autouse, no network); live run yields **real normalized rows** (`stored=1`, 2913 segments, v1, run+attempt rows, `pending_after=0`) and asserts its own honesty rules including "a run that stored nothing skips rather than reads green". | ⚠️ hand-off: the live observation and the offline suite counts (1279 passed / 4 skipped vs baseline 1261/3, arithmetic consistent) are implementer-reported and were not re-run by any QC seat; the live line cannot be re-derived here. QA should either re-take the bounded smoke or record explicit acceptance of the recorded line — and, if re-taken, must require `sessdata=present` in the evidence/skip. |
| A12 | **S with 3 precision items** | Verified against code by this seat: commands/bounds (`cli.py:758-769,842-865`, `docs:88-107`, `README:594-600`), exit taxonomy (`cli.py:820-822,915-917`, `docs:156-168`), output shapes (`cli.py:801-819,898-914`), the composed rebuild line proven by exact-equality including the absolute DB path (`tests/test_subtitle_cli.py:1047-1074`), the guard/rebuild (`docs:236-250`), the writer lock + probe lock-freedom (`docs:182-194`, `README:655-659`, `cli.py:2435-2445`), the legacy boundary/`needs_audio` (`docs:252-268`, `README:345-352,647-654`), the two schema resources (`README:644-646`), proxy + credential knob reuse (`docs:281-292,338-372`). | **Q3-01** (preference prose vs tie-break), **Q3-04** (abridged live quote), **Q3-05** (failure/rebuild-path clauses). None falsifies the criterion's substance: the two commands, bounds, exits, output shapes, SQLite-only projection boundary and untouched legacy path all match. |

**Falsified criteria: none.** Unproven-in-live (offline-only by design): A3, A4, A5's mapping, A10, plus A1's zero/multi-track shapes. Satisfied only by a fallback reading: **none** — A11's primary branch (real rows) was taken; the fallback (recorded bounded blocker) was not needed.

---

## Focus 3 — Operator readiness (README + `docs/metadata-storage.md` against this host)

Host facts assumed: **no `archive.db` exists here**, and the **proxy is required** (direct route to Bilibili is blocked). Walked end to end:

1. **Install/backend** — `uv sync` / `pip install -e ".[dev]"` provides `curl_cffi`; without it every call fails in-process as `response_error` (`docs:294-309`). Clear.
2. **Credential** — `--sessdata` or `BILI_SESSDATA` (flag wins; blank = anonymous); presence-only display (`docs:281-292`, `README:633-638`). Clear, and the shipped `resolve_sessdata`/`redact_sessdata` are reused rather than reinvented.
3. **Proxy** — the required knob is `BILI_HTTP_PROXY` with the documented precedence and the explicit warning that `HTTPS_PROXY`/`ALL_PROXY` alone are ignored by the pinned client (`README:547-556`, `docs:338-372`), plus a copy-paste example with `fetch-meta` (`docs:369-372`). Adequate for this host.
4. **Create the database** — `fetch-meta --mid 23191782 --archive-root archive` (`README:102,511`). The default page bound and `--limit-pages`/`--resume` semantics are documented (`docs:383-385`), but the **rebuild** instruction (step 6) omits the bound → Q3-05(c).
5. **Probe** — `probe-subs --limit-parts 5 --archive-root archive` (or `--bvid BV…:p0`): prints `sessdata: …`, per-part lines, summary; exits 0/1/2 as documented; creates nothing and never creates the database (verified: not in `_ARCHIVE_WRITER_COMMANDS`, and the missing-DB check precedes `open_database`, whose `initialize_schema` would otherwise create the file). On this host with no `archive.db` the operator gets the shipped read-command line and exit 1 — no surprise, no stray file.
6. **Harvest** — `harvest-subs --limit-parts 5`: requires the bound (or a single `bvid:pN`), takes the writer lock, prints per-part lines + the complete summary. On a missing root the operator gets exit 1 + the fetch-meta pointer, **plus a silently created `<root>/coordinator/` directory** (Q3-05(a)) — the one rough edge in an otherwise clean path.
7. **Pre-iteration database** — both commands print the fixed rebuild line and exit 1 while `status`/`runs` keep working; the fix is executable (delete `archive.db`, `fetch-meta`, harvest again) modulo the bound caveat (Q3-05(c)).
8. **Boundary with the legacy path** — stated in the docs section, in a README bullet, and in the `run` four-stage paragraph (⚠️6 discharged); the Workflow block itself lacks the pointer (Q3-05(d)).
9. **Live smoke** — documented command with `.env`, `BILI_HTTP_PROXY`, `BILI_LIVE_SMOKE=1`, `-s -v` (the `-s` rationale is documented), and the worktree-vs-control-checkout trap named (`docs:469-491`, `README:661-690`, module docstring `:64-73`). Adequate; the credential-forgotten skip remains a reading hazard (Q3-03).

**Watch item (no action required):** output is printed only after the whole bounded run returns (`cli.py:788-792` then the print block), so a large `--limit-parts N` harvest gives no per-part feedback while holding the writer lock. The docs' examples keep bounds small and the run is bounded per part, so this is a design choice, not a defect — worth one sentence ("output appears when the bounded run finishes") if the docs are touched for Q3-05.

**Verdict on readiness:** a fresh operator can follow README + `docs/metadata-storage.md` to create the archive, probe, harvest, read the exits/output shapes, handle a pre-iteration database, and understand what the SQLite path does and does not feed. The four under-specified spots in Q3-05 are the only places a careful operator would be misled.

---

## Focus 4 — Closure obligations

| Obligation | Status | Evidence |
|---|---|---|
| **F3** — shared `FakeGateway` double gains the two subtitle methods | **Discharged here (Task 2)** | `tests/fixtures/fake_bilibili_gateway.py:364-403` (scripting + `get_subtitle_tracks`/`fetch_subtitle_segments`, both recording `listing_cids`/`body_cids`); `test_subtitle_cli.py` scripted through it with zero assertion lines changed (Task-2 review) |
| **R1** (whole-`user`-module import) | **Correctly left open, correctly retargeted** | `git diff --name-only c5a9b82..8373817` includes **no** `sources/bilibili_api_gateway.py`; register `residuals.json` R1 target = "the next plan whose file list includes …(the CLI plan does not; expected: the audio/ASR iteration)" — matches reality. The register still shows exactly one open entry (`residuals: low 1` in the engine status), i.e. this branch registered nothing new and closed nothing |
| **QC3-003** (`docs/metadata-storage.md` "no … transcripts are written yet") | **Discharged here** | `docs/metadata-storage.md:58-69` — the §"Media and transcript tables" text now describes `harvest-subs` writing transcripts; the old "Reserved media boundary / written yet" wording is gone (grep: no `written yet`, no `Reserved media boundary`) |
| **QC3-005** (the composed rebuild line must carry prefix **and** root) | **Discharged here** | `cli.py:545-556` composes the line; `tests/test_subtitle_cli.py:1047-1071` asserts the exact full stderr line for both commands including the absolute `database_path` |
| **QC3-002** (repository `__init__` should fail fast) | **Already cashed at base — not an open obligation** | `git show c5a9b82:…/storage/database.py` → `TranscriptRepository.__init__` calls `require_subtitle_schema` (introduced by `4dcbf5d`, an ancestor of the base). This branch additionally guards in the CLI (`_open_subtitle_connection:559-581`) and services guard first, so the promise is doubly met |
| **M3** (env-sourced credential assertion lost with the legacy tests) | **Discharged here (Task 2)** | `tests/test_subtitle_e2e.py:756-812` — env credential present and absent: value reaches the adapter, `credential_present` 1/0 in the run row, printed line, value nowhere |
| **M1** (probe-vs-harvest `not_found` asymmetry) | **Discharged here (docs)** | `docs/metadata-storage.md:170-180` states both readings and both exit codes; the asymmetry is also rehearsed on both sides (`tests/test_live_subtitle_cli_smoke.py:1169-1188`) and pinned in code (probe `failed` → `failed=` and exit 2 when all parts fail, `cli.py:803-804,820-822`; harvest `not_found` → `no-subtitle`, exit 0, `subtitle_ingest.py:457-460,473-476`) |
| **⚠️2** (writer lock must be documented) | **Discharged here** | `docs/metadata-storage.md:182-194` + `README.md:655-659`; `README.md:186-195` no longer lists `probe-subs` as a writer; pinned by the exact-file-set assertions |
| **⚠️6** (`download-audio --missing-subs` gains nothing) | **Discharged here** | `docs/metadata-storage.md:252-268`, `README.md:647-654`, `README.md:345-352`; code anchor: `cli.py:944-948` still selects `status == "needs_audio"` from the manifest, which the new harvest never writes — statement is true |
| **Task-3 Minors (6) recorded for the plan-QC fix round** | **Recorded; this seat's independent severity re-judgement below** | `progress.md:93-99` disposition |
| **Task-1 M2 / M4, Task-2 Minors** | **Recorded acceptances; M2 needs an owner/trigger (Q3-06)** | plan `## Durable Roadmap and Dependencies` "Recorded (nits …)" block |
| **Durable Roadmap items** (projections, audio queue, contract promotion, legacy retirement) | **Present**; the legacy-retirement bullet lacks owner/trigger (Q3-06) | plan `## Durable Roadmap and Dependencies`; compass Roadmap Position |
| **Nothing here invalidates a previously closed plan's claims** | **Confirmed** | P1's claims (typed boundary, bounded codes, credential never persisted, `subtitle_url` never crosses the boundary) are untouched — no `sources/` file is in the diff, and the probe output is expressed in the DTO's own terms. P2's one falsified sentence (QC3-003) is fixed above. Deletions of legacy CLI-surface tests (11 in `test_subtitles.py`, 2 in `test_mixed_outcome_contract.py`, 2 in `test_page_pipeline.py`, 2 in `test_cli_asr.py`) all target the *replaced* manifest semantics; every one maps to a named, stronger replacement, and the surviving legacy producer `subtitles.harvest_subtitle` is still exercised from four modules (`test_subtitles.py:220,243`; `test_page_pipeline.py:127-128,241`; `test_cli_asr.py:112`; risk ceiling via `test_cli_pilot.py:449-457` and `test_run_ledger.py:399`) — independently confirmed, no coverage regression |

**Discharged / owned:** F3 ✓, QC3-002 ✓ (pre-base), QC3-003 ✓, QC3-005 ✓, M1 ✓, M3 ✓, ⚠️2 ✓, ⚠️6 ✓, R1 ✓ (retarget valid), Task-2 ⚠️4/⚠️6 ✓. **Needs a PM decision, not a code change:** M2's owner/trigger and the legacy-retirement bullet (Q3-06).

---

## L2 severity re-judgement (independent)

| L2 finding | This seat's independent severity | Rationale / anchors |
|---|---|---|
| Task-3 Minor 1 — report claims a README M1 bullet that does not exist | **Suggestion (report-prose only)** | Verified: the M1 statement lives in `docs/metadata-storage.md:170-180`; `README.md:611` only lists the line shape. Obligation met where the plan named it; must not be propagated into the QC/knowledge record. Agree with L2. |
| Task-3 Minor 2 — probe output never sentinel-scanned; docs' "no upstream message text" | **Suggestion** (non-blocking), now **Q3-02** | Confirmed by this seat at the anchor level; structural A8 still holds. |
| Task-3 Minor 3 — docs' live line drops `run_id` | **Suggestion**, now **Q3-04** | Confirmed byte-level difference against `tests/test_live_subtitle_cli_smoke.py:838`. |
| Task-3 Minor 4 — `with_tracks`/`stored`/printed `run_id` unasserted live | **Suggestion**, now **Q3-03** | Confirmed; the `run_id`↔row pairing is pinned offline (`test_subtitle_e2e.py:623-631`), so the live gap is narrow. |
| Task-3 Minor 5 — live body never runs offline; missing credential reads as a skip | **Suggestion**, now **Q3-03**; plus a **QA instruction** | The live-only composition (`summary` assembly, skip branch) is covered by the recorded run; the credential reading hazard is real for a gate-run and is the one place a skip could be mistaken for upstream evidence. |
| Task-3 Minor 6 — module organisation interleaving | **Cosmetic (no action)** | Agree with L2. |
| Task-1 M1 (probe `not_found` asymmetry) | **Closed by documentation** | Both readings documented and rehearsed; no rework. |
| Task-1 M2 (finish outside the interrupted-run guard) | **Suggestion (process, now Q3-06)** — the code nit itself is acceptable because it mirrors the shipped metadata discipline (`cli.py`'s metadata path leaves a `running` row on an unexpected abort, documented at `docs:537-541`); what is missing is the owner/trigger for the deferred decision | `subtitle_ingest.py:351-358,374-387`; plan "Recorded (nits …)" |
| Task-1 M4 (cross-test private helper import) | **Cosmetic (no action)** | Agree with L2; promote to a fixture only if a third consumer appears. |
| Task-2 Minor 1 (report's metadata clock claim is wrong) | **Suggestion (report-prose only)** | Reproduced the reasoning: `SubtitleIngestor.__init__` binds `_now` as a default argument (`subtitle_ingest.py:309`) while `MetadataIngestor` calls the module-global `_now()` — the correction must not be lost when the QC bundle is consolidated. |
| Task-2 Minor 2 (`_archive_files` blind to empty directories) | **Suggestion (assertion strength)** | Verified `_archive_files` walks file names only (`test_live_subtitle_cli_smoke.py:467-476`, `test_subtitle_e2e.py:166-173`); matches the spec's literal "no file" wording, and the one directory a shipped path could create (`coordinator/`) always contains the lock — see Q3-05(a). |
| Task-2 Minor 3 (M3 branch pinned across two tests) | **Cosmetic (no action)** | Informational. |
| Task-1/2/3 ⚠️ "wider counts are implementer-reported" | **Not a finding — QA hand-off** | QC does not re-run suites (`qc-specialist-shared.md` NEVER). |

**Escalation check:** no L2 item is a plan-level blocker; nothing in this branch warrants a fix round *before* Done, but the six Suggestion items should be disposed of (fixed or explicitly accepted) under the plan's `Findings cleanup: zero-residual`.

---

## Source Trace

- Finding ID: Q3-01 → Source Type: deep-lens: Enforcement-Path Lens → Source Reference: `src/bili_asr/services/subtitle_ingest.py:119-125,160-167`; `docs/metadata-storage.md:198-213`; `README.md:621-632`; `specs/subtitle-cli-contract.md:193-198`; `tests/test_subtitle_cli.py:386-409` → Confidence: High
- Finding ID: Q3-02 → Source Type: deep-lens: Enforcement-Path Lens → Source Reference: `src/bili_asr/cli.py:812`; `tests/test_live_subtitle_cli_smoke.py:777,795,1037,1083,1118`; `tests/fixtures/fake_bilibili_gateway.py:150-192,828-841`; `docs/metadata-storage.md:117,153` → Confidence: High
- Finding ID: Q3-03 → Source Type: deep-lens: Ownership / Derived-State Lens → Source Reference: `tests/test_live_subtitle_cli_smoke.py:340-455,804-805,832-847,861-881`; `tests/test_subtitle_e2e.py:623-631`; `docs/metadata-storage.md:501-509` → Confidence: High
- Finding ID: Q3-04 → Source Type: read → Source Reference: `docs/metadata-storage.md:510-519`; `tests/test_live_subtitle_cli_smoke.py:836-843`; `implementer-task-3-report.md:93` → Confidence: High
- Finding ID: Q3-05 → Source Type: deep-lens: Reliability Lens → Source Reference: `src/bili_asr/cli.py:2435-2445,2486-2501`; `src/bili_asr/coordinator.py:57,70-94`; `src/bili_asr/persistence.py:33-56`; `src/bili_asr/config.py:27-32`; `docs/metadata-storage.md:184-188,247-250,383-385`; `README.md:100-125,639-646,655-659`; `specs/subtitle-cli-contract.md:300-306` → Confidence: High
- Finding ID: Q3-06 → Source Type: manual-reasoning (harness Durable Roadmap Gate) → Source Reference: plan `## Durable Roadmap and Dependencies` (bullets + "Recorded (nits …)"); `src/bili_asr/services/subtitle_ingest.py:351-358,374-387`; `.mstar/projects/_default/residuals.json` → Confidence: Medium
- Cross-check anchors used for the focus sections: `review/branch-diff.md` (whole-range diff), `review/task-1-review.md`, `review/task-2-review.md`, `review/task-3-review.md`, `progress.md:1-99`, `implementer-task-3-report.md:70-139`, `delivery-compass.md:100-119`, `specs/subtitle-cli-contract.md`, `residuals.json`, and the shipped sources/tests/docs listed above. No credential file was read or sourced; no test/build/lint run; no git mutation; no network call.

## Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 0 |
| 🟢 Suggestion | 6 |
| ⚪ Unconfirmed | 0 |

**Verdict**: **Approve**

The branch delivers the iteration's operator surface faithfully: a genuinely read-only `probe-subs` (structurally outside the writer set), a bounded `harvest-subs` whose per-part evidence, outcome mapping, run lifecycle, summary completeness and SQLite-only projection boundary are pinned by offline E2E cases that this seat read rather than trusted (`tests/test_subtitle_e2e.py`, `tests/test_subtitle_cli.py`), and documentation that matches the shipped code on every claim I spot-checked (the composed rebuild line, the writer lock, the `not_found` asymmetry, the `needs_audio` boundary, the missing-DB/exit taxonomy). The acceptance-carrying live run's evidence line is derived from the shipped CLI's own stdout and from the rows it wrote, each with an assertion that would fail if the fact were absent; its one honest weakness (a handful of printed-but-unasserted fields, and a credential-forgotten skip that reads like upstream evidence) is logged as Q3-03 for the fix round and as a QA instruction. The five remaining Suggestions are documentation-precision, assertion-strength or process-recording items with no shipped-behaviour impact, and the three-invocation deviation is judged properly disclosed, bounded, and best recorded as a durable note rather than a register entry. All closure obligations are discharged or correctly owned (F3, QC3-002/003/005, M1, M3, ⚠️2, ⚠️6, R1 retarget), and nothing in the range invalidates a previously closed plan's claims.

### ⚠️ Items for PM / L4 (QA) — cannot be verified from this seat

1. **The recorded live observation is not reproducible here** (live network forbidden by the Assignment; no artifact survives; one test commit written after all three invocations). QA should either **re-take** the bounded smoke (`BILI_LIVE_SMOKE=1`, `--limit-parts 1`, temporary root, credential + proxy from the documented environment) or **explicitly accept** the recorded line at the gate. If re-taken and it does **not** store, require the evidence/skip to carry `sessdata=present` before treating it as a bounded upstream observation — a `sessdata=absent` skip says nothing about upstream (Q3-03).
2. **The offline suite counts are implementer-reported only** (`test_subtitle_cli/e2e/live_*` focused group 116 passed/3 skipped; full suite 1279 passed/4 skipped vs baseline 1261/3; arithmetic internally consistent). No QC seat re-ran them; the plan's Done criterion "offline suites green" rests on that evidence. I independently confirmed only the read-only items: `git diff --check` clean and the 13-file `+4597/−574` shape.
3. **The three-invocation ledger's attempt-1/2 states are unrecoverable from the range.** I verified the corroborating structure (non-autouse credential fixture with the trap named; a single `_flush_output` call; the evidence line carrying the probe counts) and found no internal inconsistency. PM: keep the deviation in the plan's durable summary + the iteration's Quality Gate Summary, and do not silently normalize the one-run live budget for later plans.
4. **Five PM decisions are pending under the fix round** (no code risk): Q3-01 (reword the preference prose or pin the corner), Q3-02 (docs scoping + optional probe sentinel rehearsal), Q3-04 (paste `run_id=`), Q3-05 (lock-before-guard clause, spec errata line, rebuild bound, Workflow pointer), Q3-06 (owner/trigger for M2 and the legacy-retirement bullet). Disposition each as fixed or explicitly accepted so `zero-residual` holds; none changes shipped behaviour.

---

## Revalidation

**Lens**: targeted L3 re-review of the plan-QC fix wave for this seat's six Suggestions (Q3-01…Q3-06),
the A1–A12 mapping re-check, and a regression lens over the 92 deleted lines. Read-only; no subagent,
no git mutation, no live network, no credential read.

**Checkout / artifact identity (read-only probes)**: worktree HEAD `7e57eb62d35d33b8effee6b21bac8b0b8f4d70c1`, branch
`feature/20260911-subtitle-cli-cutover`, `git status --porcelain` empty. One read-only `git log -1 --name-only 7e57eb6`
was run to confirm the review artifact is complete: the commit holds **exactly the 9 files** the fix diff lists
(README, `docs/metadata-storage.md`, `cli.py`, `services/subtitle_ingest.py`, `sources/bilibili_api_gateway.py`,
`sources/models.py`, `tests/test_bilibili_api_gateway.py`, `tests/test_live_subtitle_cli_smoke.py`,
`tests/test_subtitle_cli.py`) — no hidden tenth file. Line arithmetic re-derived from the artifact: 908 `+` lines
minus 9 `+++` headers = **+899**; 101 `−` lines minus 9 `---` headers = **−92** → matches the Assignment exactly.

**Focused offline run (the Assignment's one sanctioned command, nothing else)**: `BILI_LIVE_SMOKE` and `BILI_SESSDATA`
explicitly unset, no `.env` sourced, `pytest tests/test_live_subtitle_cli_smoke.py -q` →
**`20 passed, 1 skipped`** in 0.98 s (the skipped case is the opt-in live body, so the module stayed offline). This is
the only execution this seat performed; the full suite, `test_subtitle_cli.py`, lint and the live gate were **not**
re-run (they remain the L4/QA obligation already recorded in the consolidation).

### Per-item verification

- **Q3-01 — CLOSED.** Both operator-facing documents now state the family-blind term:
  `docs/metadata-storage.md:210-219` ("The CC-before-AI term is deliberately **family-blind**: the remaining families
  share one rank … upstream order settles only a tie between tracks of the same family and the same kind. That ranking
  order is the locked key") and `README.md:631-637` (same reading, `**different** non-default families`). The old
  qualifier is gone from both files (grep `inside the same family` / `inside a family` → 0 hits). The new pinning test
  `tests/test_subtitle_cli.py:506-538` (`test_the_cc_before_ai_preference_decides_across_two_rest_families`) is
  **genuinely discriminating**: `_family_rank` maps every family outside `("zh","en")` (`subtitle_ingest.py:71,123-129`)
  onto the same rank, and the shipped key is `(_family_rank(...), is_ai, upstream_index)` (`:164-171`), so the *old*
  prose's reading — CC/AI only inside one family, therefore upstream order across families — would select `ai-ja@0`
  and fail `is french_cc`; the test also pins order-independence (`(french_cc, japanese_ai)` → still `french_cc`) and
  the same-family/same-kind tie (upstream order). Cosmetic only: the docstring's "the family rank and the upstream index
  each disagree with the outcome on their own" is loose for the family rank (both rest-families *tie* there rather than
  disagree); the conclusion it argues for is correct and independently verified.
- **Q3-02 — CLOSED.** (i) The live surface is scanned: `tests/test_live_subtitle_cli_smoke.py:871`
  `assert_leaks_no_markers(probe_out + probe_err, context="live probe output")`. (ii) The scan is proven non-vacuous on
  that exact surface by an offline rehearsal — `:1139-1183` scripts a track whose `label` **is** the signed-URL sentinel,
  asserts the marker really is on stdout (`the label is printed as metadata, which is why it is scanned`), asserts the
  scan raises there, and adds a negative control on the benign surface. (iii) The docs sentence is scoped and the
  printed field named: `docs/metadata-storage.md:153-159` now reads "The error and evidence paths carry no credential, a
  signed URL, a raw body, or raw upstream message text: a bounded scalar code stands in for whatever upstream said. The
  one upstream **metadata** value any output prints is the track label (`lan_doc`) on the `track` lines above — printed
  as metadata, trimmed, and rejected by the gateway as a bounded `shape_error` if it carries a control character, so it
  cannot split the locked one-line-per-track shape." The mechanism claim is verified end-to-end: `sources/models.py:25-38`
  (`_text` rejects `\x00`/`\r`/`\n`) → `bilibili_api_gateway.py:288-313` (adapter strips and wraps `TypeError/ValueError`
  into `GatewayShapeError`) → pinned by `tests/test_bilibili_api_gateway.py:2496-2527` (`shape_error`, one call) and the
  DTO-level cases added at `:1594-1613`. Two wording observations only (below), no shipped impact.
- **Q3-03 — CLOSED, both halves.** (a) *Printed fields tied to their source*: `_read_probe_output` now derives and
  asserts `with_tracks`/`without_tracks`/`failed` against the part line it summarizes and requires the three brackets to
  partition `probed` (`tests/test_live_subtitle_cli_smoke.py:437-448`) — the `track_count: int | None = None` sentinel for
  a failed listing is what keeps that partition exact (a refused listing prints `failed=1, without_tracks=0`, and
  `None == 0` is False), which I re-derived against the CLI's own arithmetic (`cli.py:900-906`); `_read_harvest_output`
  ties the four outcome counts to the part line's outcome (`:508-520`, `outcome` is total by construction from the
  `stored|unchanged` regex plus the two explicit branches, so the mapping cannot `KeyError`) and requires a non-empty
  `run_id`; `_assert_stored_rows` / `_assert_no_transcript_rows` now take the printed `run_id` and assert it **is** the
  persisted run row's id (`:647-650`, `:735-737`); the live path ties `stored`/`unchanged` to the outcome
  (`:908-910`). All seven call sites pass the new keyword (the sanctioned module run is green). (b) *Forgotten credential
  fails loudly*: `_require_live_credential` (`:236-257`) is applied inside `_live_preconditions` (`:260-276`), called
  first in the live body (`:846`) — before any `main()` call, so no upstream call is spent — and it `pytest.fail`s with
  source-the-`.env` guidance when `BILI_SESSDATA` is unset **or blank**; the order (opt-in skip → pin assert → credential
  fail) is itself rehearsed offline by `:1052-1091` (default skips without credential *or* pinned distribution; opted-in
  without a credential fails and the message names the variable and "benign skip"; a blank value fails too; a resolvable
  value passes). `docs/metadata-storage.md:519-526` documents exactly that rule, including "A default (not opted-in)
  pytest run still skips, credential or not."
- **Q3-04 — CLOSED.** `docs/metadata-storage.md:544-553` now quotes `… harvest_exit=0
  run_id=1de9b7cb7cd141bfa7114112212188db attempted=1 stored=1 …`, byte-identical to the recorded ledger
  (`implementer-task-3-report.md:93`) and to the field order the committed code prints (`cli.py` summary line; smoke
  evidence line `:946`). No other elision remains in that quote.
- **Q3-05 — CLOSED (all four sub-items).** (a) The lock-before-DB-check ordering and its filesystem consequence are
  stated in both documents: `docs/metadata-storage.md:195-200` and `README.md:676-679` ("The lock is taken **before** the
  command's database check, so even a failed or mistyped harvest — a missing `--archive-root`, say — creates
  `<root>/coordinator/` and leaves the lock file there while exiting `1`; nothing reaches the database"). Structurally
  re-verified: `harvest-subs` ∈ `_ARCHIVE_WRITER_COMMANDS` (`cli.py:2528-2538`) and `main()` wraps `_dispatch_command`
  in `archive_writer(args.archive_root)` (`:2585-2591`), while the database check lives inside the handler
  (`_archive_database_exists`, `:502-515`) — so the claim is true, and the offline F-001 case pins the lock file for an
  exits-1 harvest (`tests/test_subtitle_cli.py:1185-1187`). (b) The spec's literally-false clause is corrected by the
  PM's dated note under §6: `…/specs/subtitle-cli-contract.md` now carries "> Dated PM note (2026-09-11 …): read this
  together with the shipped writer lock — `harvest-subs` is an archive-writer command and additionally takes
  `coordinator/archive-writer.lock` …; `probe-subs` takes none. The database remains the only content file either
  command writes." That discharges the item; bookkeeping nit: `implementer-fix-1-report.md:325-327` still lists "the
  spec errata line at iteration close" as an open follow-up although the note is already in place — the PM should simply
  mark it closed. (c) The rebuild's implicit bound is documented in both: `docs/metadata-storage.md:268-271` and
  `README.md:658-661` name `DEFAULT_PAGE_LIMIT = 10` and give `--limit-pages <n>` / repeated `--resume` as the
  remedies; verified `config.py:32` (value 10, applied when the flag is omitted) and that `--resume` really continues
  from the stored cursor (`services/metadata_ingest.py:197-200`: stored cursor's `next_page`, else page 1), so the
  "repeated runs" advice is sound. (d) The Workflow pointer exists: `README.md:102-110` places the ⚠️ block above the
  command list and links `#subtitle-acquisition-on-sqlite-probe-subs--harvest-subs`, which is the correct GitHub slug of
  the `#### Subtitle acquisition on SQLite (`probe-subs` / `harvest-subs`)` heading at `README.md:587`; the block's
  claims (`harvest-subs` writes `archive.db` not the manifest; `download-audio --missing-subs` gains nothing;
  `asr --pending` does not see the stored transcripts) match `cli.py`'s `asr --pending` help and the legacy-boundary
  section (`docs:280-289`, `README:664-671`).
- **Q3-06 — PARTIALLY CLOSED (1 of 2 statements).** M2 is fixed: the plan now reads "**M2** — (owner
  `project-manager`; trigger: the next plan that owns the run lifecycle) `finish_acquisition_run` sits outside the
  interrupted-run guard …" (`{PLAN_DIR}/20260911-subtitle-cli-cutover.md:326-329`), i.e. owner + trigger present. The
  **legacy-retirement bullet still carries neither**: `:289` is still "- Deferred: retiring `bili_client`'s subtitle
  methods and migrating the ASR/pilot path." with no owner/trigger/done-definition, and the neighbouring named-owner
  bullet (`:290-297`) enumerates only projections, the audio queue and contract promotion — the retirement item is not
  in that list (grep over the whole plan: `bili_client`/`retiring` occur once, on `:289`). The implementer's own fix
  report classifies Q3-06 as a PM-owned plan edit it did not perform (`implementer-fix-1-report.md:325-327`). So the
  Assignment's claim holds for M2 only. **This is not blocking** (no shipped behaviour, and the deferral's substance is
  recorded in the same section), but under the Durable Roadmap Gate it needs one plan-text line — owner
  (`project-manager`), trigger (the audio/ASR iteration, which is also the next owner of `bili_client`'s subtitle
  methods), done-definition — or an explicit PM acceptance; until then `zero-residual` cannot be declared for this item.

### A1–A12 re-check (compass acceptance criteria)

| # | Status after the wave | What changed / why it still holds |
|---|---|---|
| A1 | **S** (unchanged) | No change to the probe output contract; zero/multi-track shapes remain offline-only `(o)`. |
| A2 | **S (p)** (unchanged) | No storage/DTO field change; the ms rule is still P1's evidence. |
| A3 | **S (o)** (unchanged) | Same-store/`unchanged`/v2 cases untouched; the new pathological-timeline case is an additional bounded-failure case, not an A3 claim. |
| A4 | **S (o)** (unchanged) | `no-subtitle` mapping untouched; QC2-001's reordered partial-failure case (`tests/test_subtitle_cli.py:1063-1126`) strengthens the adjacent "one failure does not end the run" evidence. |
| A5 | **S (p/o)** (unchanged) | Error taxonomy untouched; QC2-002 adds the storage-ceiling `ValueError` → `failed`/`shape_error` per-part path (`:1128-1174`) and the service now converts it (`subtitle_ingest.py:497-541`). |
| A6 | **S** (unchanged) | Run/attempt rows unchanged; the readers now assert the printed `run_id` against the run row, so the live A6 evidence is tied tighter. |
| A7 | **S — holds and is strengthened** | The probe now opens `sqlite3.connect("<file-uri>?mode=ro", uri=True)` with `row_factory`/`foreign_keys` set and the first read inside the bounded handler (`cli.py:542-601`), and `_open_subtitle_connection(read_only=True)` is used only by `probe-subs` (`:857-859`); `harvest-subs`/`status`/`runs` keep the write-capable path (`read_only` defaults `False`). The file-set claims (`probe → [archive.db]`, `harvest → [archive.db, coordinator/archive-writer.lock]`) are unchanged in the tests and are now **structural** rather than conventional: no schema script runs and no commit happens on the probe path, so no `-journal`/`-wal` can be created by it (no WAL anywhere in `src/`; `sqlite3` default 5 s busy timeout preserved). The repository contract is satisfied by the read-only connection exactly as the new comment claims — `_validate_connection` requires only `row_factory is sqlite3.Row` and `PRAGMA foreign_keys == 1` (`storage/database.py:208-220`), both connection-local. Two bounded edges examined, neither a defect (below). |
| A8 | **S — holds and is strengthened** | The sentinel scan now covers the probe's stdout+stderr live (`smoke:871`) and its non-vacuity is pinned offline with a positive *and* negative control (`:1139-1183`); the credential scan over output and every persisted row, the assertion-introspection trap defusal, and "`subtitle_url` is never read" are untouched. The one A8 caveat recorded in the first pass is closed. |
| A9 | **S — precision flag lifted** | `with_tracks`, `stored`/`unchanged` and the printed `run_id` are now asserted against the part line and the persisted run row, in the live readers and in the rehearsals (`smoke:437-448,508-520,647-650,735-737,908-910`). The remaining "(o)" is only that the live *sample* exposed one track. |
| A10 | **S (o)** (unchanged) | Ordering/view evidence untouched. |
| A11 | **S** (unchanged) | Primary branch (real rows) still taken; the hand-off stands — the live line and the suite counts remain implementer-reported and were not re-derived here. |
| A12 | **S — clean** | All three precision items are closed (Q3-01 docs+test, Q3-04 `run_id=`, Q3-05a/c/d docs and the spec note), and the two commands' bounds, exits, output shapes and the SQLite-only projection boundary still match the code. |

**Falsified criteria: none. Fallback readings needed: none** (A11's primary branch). A3, A4, A5's mapping, A10 and
A1's zero/multi-track shapes remain offline-only by design.

### Regression lens — the 92 deleted lines

- **Deleted doc sentences lose no shipped guarantee.** (i) The preference clause's "inside the same family" became the
  family-blind clause; the rest of the rule (families `zh` → `en` → rest, CC preferred over AI, `--language` overrides)
  survives verbatim in both files. (ii) "No output carries a credential, a signed URL, a raw body, or upstream message
  text" is *narrowed* to the error/evidence paths and the printed-label carve-out, and its second half ("no count here is
  presented as coverage of the corpus") is retained. (iii) The two-line rebuild quote became one line plus the explicit
  **stderr** fact (qc1's F-002) and gained the page bound. (iv) The lock sentence and the smoke-assertion bullet were
  extended, not replaced. I explicitly checked the neighbouring "**Without a credential** … reported as a reasoned skip"
  bullets (`docs:441-463`) — they belong to the **metadata** live smoke section (`docs:408-474`,
  `tests/test_live_metadata_smoke.py`), not to the subtitle smoke, so the new credential rule introduces no
  self-contradiction in either document.
- **Deleted code changes nothing outside the wave's items.** `_archive_database_exists` (`cli.py:502-515`) is a pure
  extraction — the missing-database line is byte-identical to the deleted inline print and both read paths call it;
  `_open_read_connection` keeps its behaviour and gains a bounded `(OSError, sqlite3.Error)` handler that reuses the same
  message shape; `_open_subtitle_connection`'s new `read_only` keyword defaults to the previous path; the write call in
  `subtitle_ingest.py` is unchanged inside a new `except ValueError` that converts the storage boundary's bounded
  rejection into this part's `failed`/`shape_error`. All four are inside the consolidated wave (F-001, QC2-002,
  QC2-003), as are the DTO text rule (F-003) and the docs edits.
- **F-003's stricter `sources/models._text` is bounded at every construction site**, which was the main regression risk
  of the wave: `_normalize_video_summary_item` (`bilibili_api_gateway.py:179-191`), `_normalize_user_video_page`
  (`:204-211`), `_normalize_video_part_item` (`:236-244`) and `_normalize_subtitle_track` (`:306-313`) each wrap
  `TypeError/ValueError` into a bounded `GatewayShapeError`; `_complete_summary_from_detail` (`:507-513`) re-uses fields
  already validated by the summary it was handed, so it cannot newly raise; `SubtitleSegment.text` moved to
  `_caption_text` (`models.py:176`), whose semantics are unchanged and which deliberately keeps interior control
  characters — the WIP regression the implementer's audit caught and fixed, verified here as
  `test_caption_text_keeps_interior_control_characters_as_one_row`
  (`tests/test_bilibili_api_gateway.py:2730-2765`) over a two-line cue. No production DTO construction exists outside the
  gateway. The metadata path's `VideoSummary.title` tightening is pinned by
  `test_get_user_video_page_rejects_a_title_with_control_characters` (`:540-560`).
- **The F-001 guard mirrors the storage rule exactly**, so it does not merely narrow the symptom: storage's identifier
  rule (`storage/models.py:65-72`, used for `bvid` at `:154/:186/:293`) rejects precisely "empty after stripping" and
  `\x00`/`\r`/`\n`, which is the predicate in `cli.py:665-675`; a padded-but-storable value is deliberately *not*
  rejected (`tests/test_subtitle_cli.py:310-328`), keeping the two exits honest.
- **Test-side deletions**: the rewritten partial-failure case replaced an `in captured.out` substring check and a
  single line-index assertion with full-stdout equality, both attempts in part order, the stored row's joined
  `cid`/`page_index`, the exact `run["outcome"] == "partial"` and row counts (`:1063-1126`) — strictly stronger than what
  it replaced; the reader/assert signature changes are covered by the sanctioned green run.

### New observations (non-findings — no action required, recorded for honesty)

1. `docs/metadata-storage.md:157-158` says a label is "rejected by the gateway as a bounded `shape_error` if it carries a
   control character", while the rule (mirroring storage) rejects the three line-affecting ones (`\x00`, `\r`, `\n`); an
   interior tab or ESC would still be printed. The sentence's operative claim (the locked one-line shape cannot be split,
   and the track line parse is unaffected) holds. If the docs are touched again, "a line-breaking control character"
   would be exact.
2. The same sentence says the label is "the one upstream **metadata** value any output prints"; the probe also prints the
   upstream `lan` code (`cli.py:899`), which is metadata too (though a validated code, not free text, and the selector
   vocabulary). Substantively correct, literally slightly broad.
3. Q3-01's loose phrasing survives in two **non-shipped, PM-owned** artifacts: plan `:63` ("with CC before AI inside a
   family") and `:109` ("CC before AI for the same language family"), and the spec's §3 prose ("inside one family prefer
   `is_ai = False` (CC) over AI") — in the spec the authoritative key sentence
   (`(family_rank, is_ai, upstream_index)`) sits immediately above it, and the shipped docs are now precise. Recommend a
   one-line alignment at iteration close; not a reopened finding.
4. Two bounded consequences of the probe's `mode=ro` connection that I examined and accept (both unreachable-or-bounded,
   both reported through the shipped `unreadable archive database …` line + exit 1 rather than a traceback or exit 2):
   (i) on a database with **no `transcripts` table at all**, `initialize_schema` would previously have applied
   `schema-transcripts.sql` — by design, `_accepts_transcript_script` treats "absent" as fresh
   (`storage/database.py:131-138,148-166`) — so the pre-fix probe could proceed after an in-place migration; the probe now
   reports the rebuild line while `harvest-subs` still migrates. That state is unreachable for archives created on/after
   iteration `20260909-structured-metadata-schema` (their pre-contract `transcripts` table makes the tested legacy shape,
   `tests/test_subtitle_storage…`/`test_storage_schema.py:525-562`, the real one, and both commands still answer it
   identically — `test_subtitle_cli.py:1355-1382` unchanged and green), and the new refusal matches the documented "no
   in-place migration" policy. (ii) A hot journal left by a crashed writer can no longer be rolled back by the read-only
   connection, so the probe would answer with its bounded unreadable-database line instead of silently recovering; the
   normal concurrent-writer case is unaffected (default 5 s busy timeout). Not reproduced at runtime here (needs a
   crashed writer); QA may pin it if it wants the belt and braces.

### Updated counts and verdict

| Severity | Count (first pass → revalidated) | Detail |
|----------|----------------------------------|--------|
| 🔴 Critical | 0 → **0** | — |
| 🟡 Warning | 0 → **0** | F-001 (qc1's Warning) is fixed and verified by reading + the new parametrization; its runtime re-check belongs to the QA gate. |
| 🟢 Suggestion | 6 → **1 open** | Q3-01, Q3-02, Q3-03, Q3-04, Q3-05 **closed and verified**; Q3-06 **partially closed** — M2 owns an owner/trigger, the legacy-retirement bullet (plan `:289`) still does not. |
| ⚪ Unconfirmed | 0 → **0** | — |

**Updated Verdict: Approve** (unchanged, now with one explicitly open residual). The fix wave does what it claimed: the
five closed items are implemented at the anchored lines, the new tests are discriminating rather than decorative (the
Q3-01 pin would fail under the old prose's reading; the Q3-02 rehearsal proves the probe scan can fire; the Q3-03
rehearsal proves an opted-in run without a credential fails instead of skipping), the deleted prose lost no shipped
guarantee, no code changed behaviour outside the wave's items, and A7/A8 are stronger while A9/A12 are now clean. The one
remaining item — the legacy-retirement deferral's owner/trigger in the plan text — is a PM-owned, non-blocking plan edit
(or an explicit acceptance) that must be settled before `zero-residual` is declared for this plan.

### Hand-off (unchanged plus one)

1. **L4/QA**: re-verify F-001 at runtime (`probe-subs --bvid ""` → `probe-subs: unknown --bvid ` + exit 1, both with and
   without an existing `archive.db`), reproduce the offline suite at HEAD (implementer-reported `1311 passed, 4 skipped`),
   and re-take the bounded live smoke requiring `sessdata=present` in the evidence or skip.
2. **PM**: close Q3-06's second half (plan `:289`) and mark the spec errata item closed in
   `implementer-fix-1-report.md`'s follow-up list; keep the three-invocation live deviation as a durable note, not a
   register entry.
3. This seat changed nothing in the checkout; the only execution was the sanctioned offline smoke-module run.
