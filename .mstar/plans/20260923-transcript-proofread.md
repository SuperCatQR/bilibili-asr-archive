---
# NOTE (2026-09-25): the iteration package this plan points at — `delivery-compass.md`, the
# `specs/editorial-stage-contract.md` below, the workflow snapshot — was deleted from disk by
# operator decision; the registry row and the residual group went with it. The keys keep their
# historical values. Package recoverable from `f33ee02` / `89a9ebb`, or byte-exact from the
# deletion archive; both documented in `HANDOFF.md` §9. This plan's own file, code and gates
# are untouched and still stand.
plan_id: 20260923-transcript-proofread
iteration: iter-2026-09-transcript-editorial-stages
iteration_compass: .mstar/iterations/iter-2026-09-transcript-editorial-stages/delivery-compass.md
iteration_refs:
  - .mstar/iterations/iter-2026-09-transcript-editorial-stages/specs/editorial-stage-contract.md
primary_spec: .mstar/iterations/iter-2026-09-transcript-editorial-stages/specs/editorial-stage-contract.md
blocked_by: []
qa_gate: mandatory
qa_mode: targeted
execution_mode: sdd
---

# 校对 stage: two-route alignment builder + proofread-candidate verifier

> **For agentic workers:** REQUIRED SUB-SKILL: Use `mstar-sdd`. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the **proofread stage** a shipped, repeatable capability: an operator can (a) build the
**two-route alignment** for a stored part — ASR transcript × caption transcript, with **every input cue
and segment accounted for** — and (b) run the **proofread-candidate verifier** against a candidate file,
which refuses with named reasons when the candidate violates the stage's own rules (marker parity,
record completeness, containment against both routes, hotword-table screen).

**Closes / advances:** closes nothing on its own; it is plan 1 of 2 for the iteration direction. It
**discharges** register row `20260922-proofread-wave · R2`'s durable lesson by construction (the counting
rule becomes command behaviour); `R1` (hotword insertion, high) keeps its own trigger.

**Architecture:** A new service module under `src/bili_asr/services/` holds the **pure** decision logic
(alignment assignment, verification rules) with no sqlite/filesystem imports, mirroring
`services/transcript_projection.py`; `cli.py` composes the reads — the caption route from the store
(read-only, `mode=ro`) and the ASR route from the bundle's `raw` sidecar — plus the service and the
filesystem output, per the repo's cross-layer rule (only `cli.py` composes layers). The store is the SSOT
for **caption** transcript text (`normalized-transcript-storage.md`); the ASR route lives in the bundle's
`raw` sidecar (`transcripts/raw/<stem>.json` → `{segments, source, provenance}`, written by
`archive.py:476-500`), the only surface carrying `provenance.hotwords` — the evidence the hotword screen
needs (**D13**). The verifier reads a candidate markdown + the two routes. **No judgement inside the
commands** — the commands check what the bytes can prove and refuse by name; the agent half is the
contract's subject.

> **Premise ruled (D13).** The route source first came from compass D10, and D10's premise was measured
> **false** by the product-manager round: no archive store can hold an ASR route — the store's only
> transcript writer validates `source_kind` against
> `ALLOWED_CAPTION_SOURCE_KINDS = ALLOWED_SOURCE_KINDS - {"asr-local"}` (`storage/models.py:476`, used at
> `storage/database.py:885-887`; the table's only `INSERT INTO transcripts` is `database.py:918`), and all
> seven stores reachable from this host hold caption routes only. **Ruled 2026-09-23 — D13**: the ASR route
> comes from the bundle's `raw` sidecar, the caption route from the store, and no store-side ASR writer
> ships this iteration. Task 1's service still consumes two *segment lists* and opens neither source; Task
> 3's CLI is the only place the route source is chosen.

**Tech Stack:** Python 3.12, stdlib only (difflib; sqlite3 for the caption-store read; json for the raw sidecar), pytest, the repo's own
`TranscriptRepository` / CLI composition patterns. No new dependency.

**Execution:** mstar-sdd

**Main worktree branch**: `main` (the control root stays on `main`; feature work happens on the plan's
worktree branch created in Phase 2).

## Global Constraints

- **Two roots.** Repository root `/root/workspace/bilibili-asr-archive`; package root `<repo>/bilibili-asr-archive`. Python/pytest always run from a package root; linked-worktree runs use the pinned invocation (`PYTHONPATH=$PWD/src <control>/.venv/bin/python -m pytest …`) — see `worktree-test-invocation.md`.
- **No local full-suite run** — the suites named in tasks are the whole local budget; CI owns the full suite.
- **Fixtures only, no live network.** The alignment builder and verifier must not open a socket; the corpus replay (criterion 4) reads **files** — the delivered `md/` + `reading/` trees, the candidate files, and the two route sources as raw JSON (`.json` under the `asr-vs-subtitle` / `subtitle-publish` `transcripts/raw/` trees). Under **D13** the replay's routes cannot come from a store, so the corpus path is the route path here; unit-level cases use crafted route pairs and never the corpus.
- **Do not edit:** `{KNOWLEDGE_DIR}/**`, `{HARNESS_DIR}/workflows/**`, `status.json`, the register, any other plan/compass. Documentation edits are limited to the files named by the tasks.
- **The frozen spec** `{SPECS_DIR}/asr-archive-cli.md` is edited only for the added-command enumeration — the exact edit is named in the plan, and a wider revision is the PM's to raise.
- **Corpus placement (compass D12): path-referenced, never copied into the repo.** The acceptance corpus is read where it is delivered — `.tmp/proofread-work/fixed/<bvid>.p0.md` (proofread bases; all six verified byte-identical to the delivered `md/` tree by sha256) and `/mnt/123pan/bili-asr-e2e/proofread-transcripts/{md,reading}/<bvid>.p0.md` (delivered corpus) — with the two route sources at `/mnt/123pan/bili-asr-e2e/asr-vs-subtitle/transcripts/raw/` (ASR) and `/mnt/123pan/bili-asr-e2e/subtitle-publish/transcripts/raw/` (caption). The plans **pin the files by sha256**; a missing or digest-mismatched file is a refusal **naming that file**, never a silent pass (the prior compass's risk-register row 1). **Unit-level cases use crafted/synthetic fixtures only**, so the test suite never depends on the corpus being present — the replay is the corpus's consumer, and it is not hermetic (CI cannot run it) — accepted cost, D12. **No transcript text is added to the repo**: no copy under `tests/fixtures/`, none tracked (`git ls-files` matches no transcript text today; the repo is public and `AGENTS.md` sets "no redistribution … personal archival only").
- **Exit taxonomy:** `0` ok, `1` refusal/usage — `2` stays unreachable (no socket). No new exit codes for existing commands.

## Prepare gates

| Gate | State | Evidence |
|------|-------|----------|
| **specify** | done | Direction locked 2026-09-23 (`direction-lock.md`); the capability absence and the wave's defect record are cited in the compass `## Scope` and `## Decisions` D1–D3. |
| **clarify** | done | Q1 (CLI surface) and Q6 (corpus placement) **resolved by the product-manager round** into compass **D11/D12** and withdrawn from `## Open Questions`; Q2 (refusal taxonomy), Q3 (contract vs behaviour boundary), Q4 (alignment persistence) → architect (rows carry owners in the compass). One residue went to the PM rather than being settled by the chain: compass criterion 1's measured-false route-source premise was ruled the same day (**D13**; the ASR route comes from the bundle's `raw` sidecar, since no store can hold one). Compass D11 (the surface above), D12 (corpus placement), and the criterion-1 marker; neither plan's `## Operator surface` carries a marker any more. |
| **plan** | done (sealed 2026-09-23) | This file. Architecture pass landed (the stage contract's §E/§F/§F.1); the three tasks are sealed with verbatim interfaces, named cases and STOP conditions. |
| **primary_spec** | done | `.mstar/iterations/iter-2026-09-transcript-editorial-stages/specs/editorial-stage-contract.md` — §A proofread, §B edition, §C shared surface. *(That path was deleted from disk on 2026-09-25 — `HANDOFF.md` §9.)* |
| **blocked_by / dependencies** | none | Reads the caption route from the store shape, the ASR route from the bundle `raw` sidecar (D13), and the delivered corpus. |

## Operator surface (product — compass D11)

Fixed so no task re-opens it; the full decision, its rationale and the rejected alternatives are compass
**D11**. Everything below is the operator-facing contract of the two new commands.

```text
bili-asr align-transcripts [--bvid <bvid[:pN]>] [--archive-root <root>] [--artifact-root <root>]
bili-asr verify-proofread --candidate <path> --bvid <bvid[:pN]> [--archive-root <root>]
```

- **Range** — `align-transcripts` with no selector covers **every stored part whose two routes are
  reachable** (a caption row in the store + an ASR `raw` sidecar in the bundle — D13); `--bvid <bvid[:pN]>` follows the shipped `_subtitle_selector` rule
  (`cli.py:838-857`): bare `bvid` = every stored part of that video, `bvid:pN` = exactly that part. A
  selector naming no stored part is the configuration error
  `align-transcripts: unknown --bvid <value>` (resp. `verify-proofread: …`), exit 1 — the shipped line
  form (`cli.py:1046`, `:1141`, `:1400`).
- **`verify-proofread`'s selector is required**, not optional: it names the part whose routes the candidate
  is checked against. A candidate whose own frontmatter `work_id`/`bvid` disagrees with the selector is
  refused by name (the shipped `identity_mismatch` discipline `coverage --quality` uses). `--candidate`
  names the operator's file; an unreadable one is exit 1 with the path named, never a traceback.
- **Prints** — one line per candidate in the read's locked order, then the closing counts line carrying
  every count including the zeros (`derive-manifest`'s shipped form):
  - builder — `<work_id>: aligned blocks=<n> segments_in=<n> segments_attached=<n>
    segments_unattached=<n> cues_in=<n> cues_attached=<n> cues_unattached=<n>`; then
    `align-transcripts: candidates=<n> aligned=<n> refused=<n>`. The two identities
    (`…_in == …_attached + …_unattached`) are a subtraction on the printed line — this is criterion 1's
    observable, and the unattached bucket is never silently dropped.
  - verifier — `<work_id>: ok (body_chars=<n> marks=<n> record_rows=<n>)`, or
    `<work_id>: refused (<rule>) at <location>`, or `warning (<rule>) at <location>`; then
    `verify-proofread: candidates=<n> ok=<n> refused=<n>`.
  - **Three line kinds are fixed; the rule vocabulary is not** — it is the architect's refusal taxonomy
    (compass Q2 → D14). A refusal always names the rule *and* the location (`<path>:<line>` or a `[hh:mm:ss]`/
    cue index), never a bare failure. An advisory line changes neither the verdict nor the exit — the
    shipped defect-vs-advisory split (`README.md:672-679`).
- **Exit** — `0` when every candidate is aligned/ok, **including zero candidates** (`cli.py:1098-1100`'s
  empty-is-success precedent); `1` for a usage/configuration error (an unknown `--bvid`, a missing or
  unreadable store, an unreadable `--candidate`) and for a candidate the command refused; **`2` is never
  produced** (no socket is opened; `_UsageErrorArgumentParser` maps argparse's own usage exit to 1).
  No new exit value — compass D8, and the frozen exit table needs no revision.
- **Disclosures the operator surface must carry** (criterion 5 checks them): the commands read bytes and
  the record — they **do not proofread**; no audio was listened to; both routes are machine transcripts
  and **neither is ground truth**; a `‹?›` site is proven *marked*, never resolved.
- **Route source (compass D13)**: the ASR route from the bundle's `raw` sidecar, the caption route from
  the store (read-only). The printed accounting line and exit stance above are unaffected by the source.
- **Rule vocabulary** — the `refused (<rule>)` / `warning (<rule>)` rule ids are the contract's `§E` table (16 rules: 14 error / 2 advisory; D14). **Alignment artifact** — when persistence is on, the builder writes `<artifact-root>/alignments/<work_id>.jsonl` (header line with the six counts, then one line per input unit; D16) and never writes under `transcripts/{srt,txt,md,raw}`.

## Tasks (sealed 2026-09-23)

### Task 1: Alignment service (pure) + accounting

**Effort (agent-oriented):** M

**Split point:** if the accounting contract and its cases do not close in one round, split the assignment
(`assign_blocks`) from the reporter (`accounting_line` + the JSONL renderer). Both halves are functions over the
same `Alignment` value, so nothing is re-derived at the split, and the accounting assertion is the gate.

**Files:**
- Create: `src/bili_asr/services/editorial_alignment.py` — pure: no `sqlite3` / `pathlib` / `os` / `subprocess`
  import and no `open()` call (the precedent is `services/transcript_projection.py`, `:92–:236`).
- Test: `tests/test_editorial_alignment.py` — the eleven cases below; crafted fixtures only, never the corpus
  (`## Global Constraints`: unit-level cases must not depend on the corpus being present).
- Out of scope: `cli.py` and every route read (Task 3) — this service opens **neither** source, because the ASR
  route is the bundle's `raw` sidecar and the caption route the store (**D13**), and choosing between them is
  `cli.py`'s job (`_cmd_publish_transcripts`, `cli.py:1339–1352`, is the composition pattern). The verifier
  (Task 2). The alignment root and its flag (Task 3).

**Interfaces:**
- Consumes: two **already-normalized** segment lists, `Sequence[tuple[int, int, str]]` — `(start_ms, end_ms,
  text)` in milliseconds, the store's own segment shape (the shape `writer_segments`,
  `services/transcript_projection.py:196–202`, converts). **No call**: the service never reads a route.
- Produces (verbatim, for Task 3):
  - `def align_transcripts(work_id: str, asr_segments: Sequence[tuple[int, int, str]], caption_cues: Sequence[tuple[int, int, str]]) -> Alignment`
  - `def normalize_segments(raw: Sequence[tuple[int, int, str]]) -> tuple[RouteUnit, ...]`
  - `def assign_blocks(asr_segments: Sequence[RouteUnit], caption_cues: Sequence[RouteUnit]) -> tuple[tuple[Block, ...], tuple[RouteUnit, ...], tuple[RouteUnit, ...]]`
  - `def accounting_line(work_id: str, accounting: AlignmentAccounting) -> str`
  - `def alignment_jsonl_lines(alignment: Alignment) -> list[str]`
  - `def render_alignment_jsonl(alignment: Alignment) -> str`
  with `class RouteUnit(NamedTuple)` (`index`, `start_ms`, `end_ms`, `text`), `class Block(NamedTuple)`
  (`start_ms`, `end_ms`, `asr_segments`, `caption_cues`), `class AlignmentAccounting(NamedTuple)` (`blocks`,
  `segments_in`, `segments_attached`, `segments_unattached`, `cues_in`, `cues_attached`, `cues_unattached`) and
  `class Alignment(NamedTuple)` (`work_id`, `blocks`, `unattached_segments`, `unattached_cues`, `accounting`).
- Honours — **the assignment rule:** an ASR segment is the spine; a caption cue attaches to the ASR segment whose
  `[start_ms, end_ms)` contains the cue's **midpoint**, and a cue whose midpoint falls in an ASR **gap** or
  outside the route is **unattached and counted** (register row `20260922-proofread-wave · R2`'s measured shape).
  `segments_attached` counts segments holding at least one cue, `segments_unattached` the rest, so
  `X_in == X_attached + X_unattached` holds per side **by construction** and no input unit is ever dropped.
- Honours — **the block rule:** one block is a maximal run of consecutive ASR segments joined only when
  `next.start_ms - prev.end_ms <= MAX_INTER_SEGMENT_GAP_MS` (**`2_000`**) **and** no unattached cue lies between
  them — an unattached cue must terminate a block, never be swallowed into one. A block's interval is its first
  segment's `start_ms` to its last segment's `end_ms`.
- Honours — **the artifact format (D16), owned here and written by Task 3:** header line first, then one line per
  input unit, in route order (the ASR units, then the caption units). The header carries `kind: "header"`,
  `work_id`, `blocks` and **the six counts** (`segments_in`, `segments_attached`, `segments_unattached`,
  `cues_in`, `cues_attached`, `cues_unattached`); D16's "six counts" is read as its six non-`blocks` fields, so
  the header and `accounting_line` carry the same seven numbers. A unit line carries `kind` (`"segment"` /
  `"cue"`), `index`, `start_ms`, `end_ms`, `block` (0-based block index, or `null` when unattached), `chars` and
  `text`. Rendering is `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))` per line,
  joined with `"\n"` and terminated by one, so a second run is byte-identical.

**Verification:** `tests/test_editorial_alignment.py`, run from the package root with
`PYTHONPATH=$PWD/src <control>/.venv/bin/python -m pytest tests/test_editorial_alignment.py -v`. The case carrying
the stage's own failure record is
`test_a_cue_whose_midpoint_falls_in_an_asr_gap_is_unattached_and_counted` (focused selector:
`… tests/test_editorial_alignment.py::test_a_cue_whose_midpoint_falls_in_an_asr_gap_is_unattached_and_counted -v`).
New cases: that gap case; `test_accounting_identity_holds_for_both_routes_on_a_crafted_pair`;
`test_every_input_unit_appears_exactly_once_attached_or_unattached`;
`test_adjacent_segments_merge_into_one_block_only_when_no_unattached_cue_lies_between`;
`test_a_gap_larger_than_max_inter_segment_gap_ms_breaks_the_block`;
`test_an_empty_route_on_either_side_yields_zero_blocks_and_a_full_unattached_bucket`;
`test_normalize_segments_orders_by_start_ms_and_rejects_a_non_positive_interval`;
`test_alignment_jsonl_header_carries_blocks_and_the_six_counts`;
`test_alignment_jsonl_has_one_line_per_input_unit_in_route_order`;
`test_render_alignment_jsonl_is_byte_identical_on_repeat_rendering`;
`test_the_service_imports_no_io_module_and_calls_no_open`.
**Fails before the change** with `ModuleNotFoundError: No module named 'bili_asr.services.editorial_alignment'` —
the module does not exist and no alignment code exists anywhere in the tree today.

**Dependency position:** wave A, ready alone; it imports nothing from Task 2 or Task 3 and can land first.
Task 3 consumes it (`align_transcripts`, `accounting_line`, `render_alignment_jsonl`); Task 2 does not.
Parallel-safe with Task 2 (different files).

- [ ] **Step 1:** add the failing cases (crafted pairs, the gap shape first); **Step 2:** run the selector (expect
      FAIL: `ModuleNotFoundError`); **Step 3:** implement `align_transcripts` and the accounting/JSONL renderers;
      **Step 4:** run the selector (expect PASS) and confirm both identities hold in every case;
      **Step 5:** commit (`feat(services): pure two-route alignment with total accounting`).
- **STOP conditions:** if the service needs any of `sqlite3` / `pathlib` / `os` / `subprocess` / `open()` to
  satisfy a case, STOP — the purity boundary is what keeps Task 3 the only place the route source is chosen
  (**D13**), and a service that reads its own inputs re-opens that decision. If a case can satisfy
  `X_in == X_attached + X_unattached` only by discarding an input unit, STOP — the identity is a **partition**,
  not a subtraction. No refusal rule id is named here: the builder's refusal vocabulary is the contract's §E
  (16 rules; **D14**), introduced by Task 2, and this task mints none.

### Task 2: Proofread-candidate verifier (pure rules + CLI)

**Effort (agent-oriented):** L

**Split point:** split by **evidence**, not by file. Round 1 closes the two checks that read the candidate text
alone (marker vocabulary, marker↔record parity) **plus** the CLI composition and its five cases; round 2 adds the
three that need the routes (change evidence, containment, hotword screen) and the remaining cases.

**Files:**
- Create: `src/bili_asr/services/editorial_verify.py` — pure, same discipline as Task 1 (no `sqlite3` /
  `pathlib` / `os` / `subprocess`, no `open()`), reusing the shipped normalizers instead of re-deriving them.
- Modify: `src/bili_asr/cli.py` — register `verify-proofread` in `build_parser()` (`:96`) and add
  `def _cmd_verify_proofread(args: argparse.Namespace) -> int` beside the composition precedent
  `_cmd_publish_transcripts` (`:1339–1352`), carrying the defect-vs-advisory and `identity_mismatch` discipline of
  `_cmd_coverage_quality` (`:1708`). The name, flags and printed lines are this plan's `## Operator surface`
  (compass **D11**) and are not re-decided here; the selector rule is the shipped `_subtitle_selector`
  (`:838–846`).
- Test: `tests/test_editorial_verify.py` — the sixteen cases below; crafted candidates and crafted route texts.
- Out of scope: `align-transcripts` and the alignment persistence (Task 3); the alignment service (Task 1);
  `storage/**` (the caption route is read through the shipped `read_transcript` — no new repository method);
  `archive.py` (the `raw` sidecar is located through the shipped `bundle_paths`); `quality.py` (reused, not
  edited).

**Interfaces:**
- Consumes (verbatim, shipped — do not re-derive):
  - `def read_transcript(self, video_part_id: int, source_kind: str, language: str, version: int | None = None) -> TranscriptRecord | None` — `storage/database.py:1023`; `version=None` reads the latest version, which is the caption route (**D13**).
  - `def bundle_paths(root: str | os.PathLike[str], entry: dict[str, Any]) -> dict[str, Path]` — `archive.py:452`; its `raw_path` is the ASR route's sidecar `{segments, source, provenance}` (**D13**), where `provenance.hotwords` is the hotword screen's only evidence.
  - `def _subtitle_selector(value: str | None) -> tuple[str | None, int | None]` — `cli.py:838`; the `bvid[:pN]` rule for the **required** `--bvid`.
  - `def flatten_reference(text: str) -> str` — `quality.py:439`; the punctuation/spacing flattening both route-dependent checks reuse.
  - `def comparable_text(text: str, cues: list[Cue]) -> str` — `quality.py:466`.
  - `class ReferenceAgreement(NamedTuple)` — `quality.py:152`; its basename-only discipline is the location rule below, and `REFERENCE_AGREEMENT_FLOOR = 0.95` (`quality.py:58`) plus `_MAX_COMPARE_CHARS = 20_000` (`quality.py:104`) are the reused floor and window cap.
- Produces (verbatim, for Task 3's shared refusal spelling):
  - `def parse_candidate(text: str) -> CandidateFacts`
  - `def check_marker_vocabulary(candidate: CandidateFacts) -> tuple[Violation, ...]`
  - `def check_marker_record_parity(candidate: CandidateFacts) -> tuple[Violation, ...]`
  - `def check_change_evidence(candidate: CandidateFacts) -> tuple[Violation, ...]`
  - `def check_containment(candidate: CandidateFacts, asr_text: str, caption_text: str) -> tuple[Violation, ...]`
  - `def check_hotword_screen(candidate: CandidateFacts, asr_text: str, caption_text: str, hotwords: Sequence[str]) -> tuple[Violation, ...]`
  - `def verify_candidate(candidate_text: str, *, work_id: str, bvid: str, reference: str, asr_text: str, caption_text: str, hotwords: Sequence[str]) -> Verdict`
  - `def verdict_line(work_id: str, verdict: Verdict) -> str`
  - `def closing_line(command: str, total: int, ok: int, refused: int) -> str` — **the command name is a parameter, not a literal** (the same function prints `verify-proofread: …` here and `verify-reading-edition: …` in plan 2; a literal would force a duplicate function, and D11 fixes the line shape as `<command>: candidates=N ok=N refused=N`)
  with `class Violation(NamedTuple)` (`rule`, `location`, `advisory`), `class Verdict(NamedTuple)` (`ok`,
  `violations`, `body_chars`, `marks`, `record_rows`) and `class CandidateFacts(NamedTuple)` (the body lines, the
  marker sites, the record rows, and the frontmatter's `work_id` / `bvid`).
- Honours — **the rule vocabulary is the contract's §E (16 rules: 14 error / 2 advisory; D14).** Step 1
  transcribes §E's ids **verbatim** into the module's `E_RULE_IDS` and the test's frozen tuple; no rule id is
  minted here or anywhere else in this plan, and every `(<rule>)` either command prints is one of those sixteen.
  Which rule is advisory is §E's to say, not this task's judgement.
- Honours — **D11's three line kinds and their locations:** a clean candidate prints
  `<work_id>: ok (body_chars=<n> marks=<n> record_rows=<n>)`; a refusal prints
  `<work_id>: refused (<rule>) at <location>`; an advisory prints `<work_id>: warning (<rule>) at <location>`.
  `location` is `<basename>:<line>` for path-shaped sites and `[hh:mm:ss]` / `cue #<i>` for route sites — the
  **basename only**, never the operator's parents, per `ReferenceAgreement`'s discipline (`quality.py:152`). An
  advisory changes neither the verdict nor the exit.
- Honours — **the five checks this task must make provable** (the architect's minimum, not a licence to invent
  ids): marker vocabulary normalised (`‹?›` vs `〔?〕`); body-marker ↔ record-row parity in **both** directions;
  every recorded change carrying its evidence; body containment — every candidate body line, flattened through
  `flatten_reference`, is found in the union of the two routes' flattened text, so a line found in **either**
  route is contained (containment is exact, therefore `REFERENCE_AGREEMENT_FLOOR` is **not** its threshold); the
  hotword screen — for each `provenance.hotwords` token occurring in the body, compare the candidate's window
  against each route's window (windows capped at `_MAX_COMPARE_CHARS`) and read
  `difflib.SequenceMatcher(None, a, b).ratio() < REFERENCE_AGREEMENT_FLOOR` as "the two routes disagree here",
  which is the R1 signature.
- Honours — the caption route is read **read-only** and the ASR route from the sidecar (both **D13**); a candidate
  whose frontmatter `work_id` / `bvid` disagrees with the selector is refused by name under the shipped
  `identity_mismatch` discipline (`cli.py:1708`); an unreadable `--candidate` is exit 1 with the path named and
  no traceback; **the command never exits 2** (**D8** — no socket is opened, and `_UsageErrorArgumentParser`,
  `cli.py:83`, maps argparse's own usage exit to 1).

**Verification:** `tests/test_editorial_verify.py`, run from the package root with
`PYTHONPATH=$PWD/src <control>/.venv/bin/python -m pytest tests/test_editorial_verify.py -v`. New cases:
`test_a_clean_candidate_verifies_ok_with_its_three_counts`;
`test_an_unlisted_marker_glyph_is_refused_by_its_e_rule_and_location`;
`test_a_body_marker_without_a_record_row_is_refused_by_parity`;
`test_a_record_row_without_a_body_marker_is_refused_by_parity`;
`test_a_recorded_change_without_its_evidence_is_refused`;
`test_a_body_line_absent_from_both_routes_is_refused_as_out_of_containment`;
`test_a_body_line_found_in_the_asr_route_alone_is_contained`;
`test_a_body_line_found_in_the_caption_route_alone_is_contained`;
`test_a_hotword_token_where_the_two_routes_disagree_is_refused`;
`test_a_hotword_token_where_the_routes_agree_is_not_a_violation`;
`test_an_advisory_rule_changes_neither_the_verdict_nor_the_exit`;
`test_every_emitted_rule_id_is_one_of_the_contracts_sixteen`;
`test_a_candidate_whose_frontmatter_work_id_disagrees_with_the_selector_is_refused_as_identity_mismatch`;
`test_refusal_locations_carry_the_basename_and_never_the_operators_parents`;
`test_an_unreadable_candidate_is_exit_1_naming_the_path_without_a_traceback`;
`test_no_path_through_the_command_produces_exit_2`.
**Fails before the change** with `ModuleNotFoundError: No module named 'bili_asr.services.editorial_verify'` and,
for the CLI cases, `exit 1` plus `invalid choice: 'verify-proofread'` — the subparser does not exist, and
`_UsageErrorArgumentParser` (`cli.py:83`) is what turns that argparse usage error into 1 rather than 2 (**D8**).

**Dependency position:** wave A for the pure module — nothing in it depends on Task 1 or Task 3 — but its
`cli.py` edit must be **serialized against Task 3's**, because both register a subparser and a handler in the same
file. Task 3 consumes this task's refusal spelling (the three line kinds and §E's ids), not its code.

- [ ] **Step 1:** transcribe §E's sixteen ids (error/advisory split checked) and write the failing cases with the
      marker-vocabulary and parity shapes first; **Step 2:** run the selector (expect FAIL: `ModuleNotFoundError`,
      and `invalid choice` for the CLI cases); **Step 3:** implement the two text-only checks and compose
      `_cmd_verify_proofread` in `cli.py`; **Step 4:** add the three route-dependent checks, then run the selector
      (expect PASS); **Step 5:** commit (`feat(cli,services): verify a proofread candidate by named rule`).
- **STOP conditions:** if §E does not hold 16 rule ids with 14 error and 2 advisory, STOP and raise it to the PM —
  the discrepancy is a contract defect, not an implementation choice, and minting an id silently re-opens
  **D14**. If any check needs a rule §E does not name, STOP rather than inventing one. If the verifier would need
  a store write or a socket, STOP — the caption route is a read-only read (**D13**) and `2` must stay unreachable
  (**D8**). If a change to `cli.py` would alter an existing command's printed lines or exit codes, STOP — this
  task adds a command, it does not revise one.

### Task 3: Alignment CLI (`align-transcripts`) + corpus replay harness

**Effort (agent-oriented):** L

**Split point:** round 1 closes the command and its crafted-fixture cases (`cli.py` + the spec enumeration +
`tests/test_editorial_cli.py`'s non-corpus cases); round 2 adds the corpus replay cases and
`docs/editorial-stages.md`. The corpus must not gate the command — the suite has to stay green with the corpus
absent.

**Files:**
- Modify: `src/bili_asr/cli.py` — register `align-transcripts` in `build_parser()` (`:96`) and add
  `def _cmd_align_transcripts(args: argparse.Namespace) -> int` beside `_cmd_publish_transcripts`
  (`:1339–1352`): that command is this one's composition precedent — the store opened **read-only**, a pure
  service called, the products written by the caller, nothing written back into `archive.db`. Selector via
  `_subtitle_selector` (`:838–846`); the unknown-selector line form from `:1046`, `:1141`, `:1400`.
- Modify: `{SPECS_DIR}/asr-archive-cli.md` — the added-command **enumeration only** (the two commands, their
  flags, the three line kinds, the exit stance). A wider revision is the PM's to raise.
- Test: `tests/test_editorial_cli.py` — the fourteen cases below, with the corpus pins as a module-level frozen
  tuple.
- Create (docs): `docs/editorial-stages.md` (package root; `bilibili-asr-archive/docs/editorial-stages.md` from
  the repo root) — the stage's operator document.
- Out of scope: `editorial_alignment.py` and `editorial_verify.py` (Tasks 1 and 2 — imported, not edited);
  `storage/**` and `archive.py` (consumed through shipped functions only); the verifier's command (Task 2).

**Interfaces:**
- Consumes (verbatim, shipped — do not re-derive):
  - `def align_transcripts(work_id: str, asr_segments: Sequence[tuple[int, int, str]], caption_cues: Sequence[tuple[int, int, str]]) -> Alignment` — Task 1.
  - `def accounting_line(work_id: str, accounting: AlignmentAccounting) -> str` — Task 1 (D11's builder line).
  - `def render_alignment_jsonl(alignment: Alignment) -> str` — Task 1 (the D16 artifact's bytes; this task owns the root and the flag, not the format).
  - `def verdict_line(work_id: str, verdict: Verdict) -> str` — Task 2 (the shared refusal spelling).
  - `def read_transcript(self, video_part_id: int, source_kind: str, language: str, version: int | None = None) -> TranscriptRecord | None` — `storage/database.py:1023` (the caption route, read-only, **D13**).
  - `def list_stored_transcripts(self, bvid: str | None = None, page_index: int | None = None) -> list[sqlite3.Row]` — `storage/database.py:1205` (the candidate range; `_require_video_part`, `database.py:1270`, is the part guard).
  - `def bundle_paths(root: str | os.PathLike[str], entry: dict[str, Any]) -> dict[str, Path]` — `archive.py:452` (whose `raw_path` is the ASR route's sidecar, **D13**); `archive_stem` (`archive.py:34`) and `_capture_summary` (`archive.py:412`) name the bundle.
  - `def _subtitle_selector(value: str | None) -> tuple[str | None, int | None]` — `cli.py:838`.
- Produces (verbatim):
  - `def _cmd_align_transcripts(args: argparse.Namespace) -> int` — in `cli.py`; returns the documented exit (`0` when every candidate is aligned, including zero candidates; `1` for a configuration error and for a candidate the command refused).
  - `class CorpusItem(NamedTuple)` and `CORPUS: tuple[CorpusItem, ...]` — the frozen six-item enumeration in `tests/test_editorial_cli.py`, each carrying its proofread base, its two route paths and their **sha256** pins.
  - `def replay_item(item: CorpusItem) -> tuple[str, str]` — the replay's per-item driver, returning the accounting line actually printed beside the recorded one.
- Honours — **D13's route choice, which lives here and nowhere else:** the ASR route is read from the bundle's
  `raw` sidecar (`transcripts/raw/<stem>.json` → `{segments, source, provenance}`, the file `write_archive`'s
  `asr_provenance` argument, `archive.py:473`, fills) and the caption route from the store read-only; both are
  normalized to the service's `(start_ms, end_ms, text)` before the call, and a sidecar recorded in seconds is
  converted **here** because the service's unit is milliseconds (Task 1).
- Honours — the accounting identities are printed as a **subtraction** on the line and never enforced by dropping
  a unit (D11's builder line; Task 1's partition is the SSOT). A part whose two routes are not both reachable is a
  refusal in Task 2's §E spelling, never a silently skipped or silently aligned candidate.
- Honours — **the artifact (D16):** the builder writes `<artifact-root>/alignments/<work_id>.jsonl` — the header
  line then one line per input unit in Task 1's format, byte-identical on a second run — where `<artifact-root>`
  is the **existing** artifact-root flag (D11(e), `--artifact-root`), the same configured root the archive
  products use. **No flag is added to D11's surface:** D16 already resolved the toggle, so persistence is
  **unconditional** and there is no directory switch and no opt-out to expose. **Nothing is ever written under
  `transcripts/{srt,txt,md,raw}`**, and the acceptance run's artifact root must be a path **outside the
  repository** (no transcript text in the repo — D12/D16).
- Honours — the exit taxonomy (**D8**): `0` / `1` only, `2` unreachable; an unknown selector is
  `align-transcripts: unknown --bvid <value>` on exit 1, in the shipped line form.
- Honours — corpus placement (**D12**): path-referenced, never copied into the repo. The pins are sha256 only; a
  missing or digest-mismatched file is a refusal **naming that file** and never a silent pass. The replay is not
  hermetic (CI cannot run it) — the accepted cost of D12 — so its cases `skipif` the corpus is absent and the
  suite stays green without it.

**Verification:** `tests/test_editorial_cli.py`, run from the package root with
`PYTHONPATH=$PWD/src <control>/.venv/bin/python -m pytest tests/test_editorial_cli.py -v`; the offline replay is
`… tests/test_editorial_cli.py::test_the_corpus_replays_offline_and_reproduces_the_recorded_accounting_line -v`
(skipped, not failed, without the corpus). The three artifact cases —
`test_align_transcripts_writes_the_header_then_one_line_per_input_unit`,
`test_align_transcripts_writes_nothing_under_the_transcript_families` and
`test_a_second_run_rewrites_the_jsonl_byte_identically` — drive the write through D11(e)'s existing
`--artifact-root`, pointed outside the repository; their names and the case count are unchanged. New cases:
`test_align_transcripts_prints_one_line_per_candidate_then_the_closing_counts_line`;
`test_align_transcripts_covers_every_stored_part_when_no_selector_is_given`;
`test_align_transcripts_bvid_pn_selects_exactly_that_part`;
`test_an_unknown_bvid_is_the_documented_configuration_error_on_exit_1`;
`test_align_transcripts_writes_the_header_then_one_line_per_input_unit`;
`test_align_transcripts_writes_nothing_under_the_transcript_families`;
`test_zero_candidates_is_exit_0`;
`test_a_second_run_rewrites_the_jsonl_byte_identically`;
`test_a_part_whose_asr_sidecar_is_missing_is_refused_by_name_never_aligned`;
`test_no_path_through_the_command_produces_exit_2`;
`test_the_corpus_frozen_six_carry_their_two_routes_and_their_sha256_pins`;
`test_the_corpus_replays_offline_and_reproduces_the_recorded_accounting_line`;
`test_a_corpus_file_missing_or_digest_mismatched_is_refused_naming_that_file`;
`test_the_stage_document_names_the_commands_routes_exits_artifact_and_disclosures`.
**Fails before the change** with `exit 1` plus `invalid choice: 'align-transcripts'` — the subparser is absent and
`_UsageErrorArgumentParser` (`cli.py:83`) maps that usage error to 1 rather than 2 (**D8**) — and with
`FileNotFoundError` for the document case.

**Dependency position:** wave B. It consumes Task 1 (`align_transcripts`, `accounting_line`,
`render_alignment_jsonl`) and Task 2's refusal spelling, and its `cli.py` edit is serialized **after** Task 2's.
Not parallel-safe with Task 2 on `cli.py`; parallel-safe with nothing else in this plan.

- [ ] **Step 1:** add the failing command cases (crafted store + crafted sidecar) and the spec enumeration;
      **Step 2:** run the selector (expect FAIL: `invalid choice`); **Step 3:** implement
      `_cmd_align_transcripts` and the JSONL write; **Step 4:** run the selector (expect PASS), then add the
      corpus pins, the replay cases and `docs/editorial-stages.md`; **Step 5:** commit
      (`feat(cli,docs): align-transcripts and the proofread stage document`).
- **STOP conditions:** if any byte lands under `transcripts/{srt,txt,md,raw}`, STOP — those four families belong
  to the archive writer (`bundle_paths`, `archive.py:452`) and the alignment artifact is
  `<artifact-root>/alignments/` only (**D16**). If a new flag appears on the builder's surface, STOP — **D11** is
  fixed and **D16** needs none. If the JSONL root can default inside the repository, STOP — no
  transcript text is added to the repo (`## Global Constraints`, `AGENTS.md`). If any path produces exit `2`, or a
  new exit value is introduced, STOP (**D8**). If a printed line departs from `## Operator surface`'s three fixed
  kinds, STOP — the surface is fixed by **D11** and is not this task's to revise. If a corpus file must be copied
  into the repo for a case to pass, STOP — **D12** is path-referenced by construction.

## Done criteria

1. Criterion 1 of the compass (alignment accounting) holds on crafted fixtures **and** the six-item corpus.
2. Compass criterion 2 (proofread verifier refuses by name) holds; refusal taxonomy landed per D14.
3. Compass criterion 4 (corpus replay offline) holds for this plan's half with recorded numbers reproduced or differences named.
4. Compass criterion 5 (help + README disclosures) holds for the new commands.
5. All tasks reviewed (SDD), QC tri + QA gate complete; residuals registered.

## Review / QA

| Field | Value |
|---|---|
| QA gate | `mandatory` / `targeted` (runtime/behaviour change: new commands) |
| QC mode | triple (SDD) |
