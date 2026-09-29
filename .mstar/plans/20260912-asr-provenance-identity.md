# Declared model identity, VAD capture, and low-confidence locations

> Iteration `iter-2026-09-asr-ops-hardening`, spec points 4–5 → acceptance **A4**, **A5**.
> Primary spec: `.mstar/iterations/iter-2026-09-asr-ops-hardening/specs/04-provenance-observability.md`.
> Execution mode: `sdd` (3 tasks).

## Status

- Priority: P1
- Task category: `logic` / provenance + observability
- Status: Done
- Depends on: nothing; P3 reads the low-confidence locations this plan records
- Owner: fullstack-dev · QA gate: mandatory (provenance contract + redaction invariant)
- Findings cleanup: zero-residual
- Evidence: audit guide §3, §4.4; `{KNOWLEDGE_DIR}/architecture-patterns/run-scoped-asr-provenance.md`

## Goal

An archived transcript says which model produced it, how much audio the VAD actually
captured, and where the doubtful passages are — without ever serializing a path.

## Specify (measured defects)

- **P1.** All ten archived files of the 2026-09-12 run record
  `asr_model_name: "[redacted]"`: the operator loaded the checkpoint from a local
  directory, which by design is not a redaction-safe identifier, and no declared
  hub-level identity existed to fall back on. Redaction itself is correct and stays.
- **P2.** Gaps longer than 3 s between cues occur 1–15 times per video; nothing records how
  much audio the VAD captured, so a speaker pause and a VAD miss are indistinguishable.
- **P3.** `asr_low_confidence_cues` names a count; the per-cue confidence exists only in
  `raw.json`, so the archive cannot say *where* the doubt is.

## Clarify (decisions — spec 04 owns the detail)

1. **Declared identity**: `BILI_ASR_MODEL_ID` → `ASRConfig.model_id` (appended last so
   positional construction stays safe), folded into the existing `model_name` provenance
   slot and never emitted as a separate key, so the nine-key provenance contract stays
   intact. Precedence: declared id → a redaction-safe configured id → `[redacted]`. An
   unsafe declaration is a loud `ValueError`; a declaration contradicting a safe
   `model_name` also fails. Revision uses the existing `BILI_ASR_MODEL_REVISION`.
2. **VAD facts**: `asr_vad_segments`, `asr_vad_captured_s`, `asr_vad_captured_ratio`
   (clamped to `[0, 1]`, seconds unclamped), computed in `archive.py` next to
   `_confidence_summary`, gated on `source == "asr"`.
3. **Low-confidence locations**: `asr_low_confidence_at` — ascending start seconds with
   3 decimals, emitted by the same function that emits `asr_low_confidence_cues` so
   count and list agree by construction.

## Non-goals

- Re-transcribing anything; changing the confidence threshold's role in scoring; changing
  cue shaping; making the model id a required configuration.

## Architecture

| Surface | Change |
|---|---|
| `src/bili_asr/asr.py` | `ASRConfig.model_id`, declared-identity precedence + validation, provenance folding |
| `src/bili_asr/archive.py` | VAD capture summary + `asr_low_confidence_at` beside `_confidence_summary` |
| `src/bili_asr/cli.py`, `coordinator.py` | Pass the declared identity through (no new keys) |
| `tests/test_asr_reproducibility.py`, `tests/test_archive_md.py` | Declared-identity, precedence, and new-field assertions |

## Tasks

### Task 1: Declared producer identity

**PM decision carried in (inherited residual R1 from `20260912-batch-model-reuse`):** a *failed* model load is
currently retried once per row, and `model_constructions` reports 0 for those attempts because `_model` was never
assigned — so a batch that fails every load prints `0` and cannot distinguish N retries from one construction.
Settle it here, on the provenance/counting surface this plan owns: either count attempts separately (e.g. a
documented `model_load_attempts` alongside `model_constructions`) or state explicitly in the code and the README
that the counter counts *successful* constructions only and that a failed load is retried per row. Whichever you
choose, make it observable and pinned by a test — and record the choice in the report.

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/asr.py`
- Test: `bilibili-asr-archive/tests/test_asr_reproducibility.py`

**Interfaces:**
- Consumes: the existing `ASRConfig` dataclass field order and `ASRRunner.provenance()` redaction rules.
- Produces: `ASRConfig.model_id` (appended last), `BILI_ASR_MODEL_ID`; the declared identity folded into the existing `model_name` provenance slot.

- [x] Add `model_id` (default empty) as the **last** `ASRConfig` field so positional construction stays safe, plus the `BILI_ASR_MODEL_ID` env knob in `default_config()`.
- [x] Implement the precedence in `provenance()`: declared id → a redaction-safe configured `model_name` → `[redacted]`; never emit `model_id` as its own key, so the nine-key contract holds.
- [x] Reject an unsafe declaration with a loud `ValueError`, and reject a declaration that contradicts an already-safe `model_name`.
- [x] Keep the path/URL/credential redaction untouched; the declared value must itself pass the identifier test.
- [x] Test: declared identity recorded; `[redacted]` without it; both failure modes; the nine provenance keys unchanged; the two existing redaction tests stay green.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_asr_reproducibility.py -v`

### Task 2: VAD capture facts in the archive

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/archive.py`
- Test: `bilibili-asr-archive/tests/test_archive_md.py`

**Interfaces:**
- Consumes: the merged cue spans and the entry duration already available to `write_archive`.
- Produces: `asr_vad_segments`, `asr_vad_captured_s`, `asr_vad_captured_ratio` beside `_confidence_summary`, gated on `source == "asr"`.

- [x] Compute the captured span as the union of cue spans merged across gaps at or below the local constant (1.0 s) — a local constant, because `archive.py` may not import `asr.py`.
- [x] Emit the three keys only for ASR sources; the ratio is clamped to `[0, 1]` while the seconds stay unclamped.
- [x] Test: key presence and absence by source; ratio bound; recomputation from `raw.json`; a single-cue and an empty-segment edge case.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_archive_md.py -v`

### Task 3: Low-confidence locations and target-host verification

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/archive.py`
- Test: `bilibili-asr-archive/tests/test_archive_md.py`
- Verify on target: WSL2 host via the operator's checkout

**Interfaces:**
- Consumes: Task 2's summary function and the per-cue confidence in `raw.json`.
- Produces: `asr_low_confidence_at` — ascending start seconds with 3 decimals, emitted by the same function that emits `asr_low_confidence_cues`.

- [x] Emit the location list from the same code path as the count so the two agree by construction.
- [x] Test: count-vs-list consistency on a crafted artefact (including zero low-confidence cues → key absent or empty list, matching the count key's behaviour).
- [x] Verify on the target host that a declared revision does not break a local-directory load (`BILI_ASR_MODEL_ID` + `BILI_ASR_MODEL_REVISION` with `BILI_ASR_MODEL=<local dir>`); record an amendment request in spec 04 if it does.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_archive_md.py tests/test_asr_reproducibility.py -v`

## Verification

- An archive produced from a local checkpoint with the declaration records the hub id and
  revision; without it, `[redacted]`; a forbidden-token scan over frontmatter + `raw.json`
  finds no path, URL, or credential-like value.
- The frontmatter carries the three VAD keys and the location list; both recompute from
  `raw.json`.
- The provenance tests (`::test_provenance_preserves_safe_slash_qualified_model_identifier`,
  `::test_provenance_redacts_path_url_and_credential_like_model_values`) stay green.
- `tests/test_asr_cues.py` unmodified (A6 guard).

## Durable Roadmap and Dependencies

- **Inherited residual R1 (low, from `20260912-batch-model-reuse`)**: a *failed* model load is retried once
  per row (`factory_attempts == N` for an N-row batch) and `model_constructions` reports 0 because `_model`
  was never assigned, so the printed count cannot distinguish N load retries from one construction. This plan
  owns the provenance/counting surface: decide whether a failed attempt counts and whether retries are
  bounded. Owner: `@project-manager`; trigger: this plan's Task 1 (provenance identity).


- **New residual R1 (low, opened by this plan's review at Task 1)**: the model-load attempt count is recorded
  (`ASRRunner.model_load_attempts`) but printed nowhere an operator can see, so a batch whose every load fails
  still shows no reuse line — the operator-surface half of the inherited residual. Fixing it needs an A2-aware
  amendment to spec 02 D2.6 (the line's shape is frozen and asserted verbatim in four test files) plus
  `coordinator.py`'s print site. Owner: `@project-manager`; trigger: the next iteration (carried at iteration-close as a roadmap item for the plan that owns spec 02 D2.6 + coordinator.py's print site).
- **New residual R2 (low)**: model-load retries stay unbounded per row (pre-existing; deliberately unchanged).

## Evidence log

| Date | Evidence |
|------|----------|
| 2026-09-13 | T1 `a5b65ca`/`b087fd6` + fix `4f509ff` — declared identity via `BILI_ASR_MODEL_ID`; review Request Changes (README promised an unprinted behaviour) → option (b) → Approved with Minor. |
| 2026-09-13 | T2 `a3ad89c` + fix `08cfbfd` — VAD capture facts (spans/seconds/ratio, ASR-only, zero-length skip); Approved with Minor after a fix round. |
| 2026-09-13 | T3 `0666310` + fix `26817c9` — `asr_low_confidence_at`; review Request Changes (the recorded host remedy used a no-load call) → option (a) real load probe on the host → **Approve**; spec 04 D4.5 verified. |
| 2026-09-13 | Plan QC tri (N=3, one batch): seat 1 `Approve with residuals` (8 Suggestion), seats 2 and 3 `Request Changes` (1 Important + 2 Warning + 5 Suggestion), 0 Critical. Consolidated at `{SDD_DIR}/review/qc-consolidated.md`. |
| 2026-09-13 | Fix wave `48690b7` — separator-aware redaction (F-001), the D4.3 hub-level-and-not-a-local-directory predicate (F-002, spec amended twice), the `asr`-path failure code + one-shot entry validation (QC3-F1), F-003 and S-1…S-7 → re-review `Approve with residuals`; suite `1565 passed / 4 skipped`. |
| 2026-09-13 | PM-side: spec 04 D4.3 amended to the implemented intent, D4.10 (zero-length skip) recorded, capture-key scope documented. |

## Review Gate Summary

| Gate | Decision | Notes |
|------|----------|-------|
| Task reviews | Approved ×1, Approved with Minor ×2 | One Important closed per fix round; no open Critical/Important at any task close |
| Plan QC | **Approve with residuals** | tri-review N=3 (one batch), 0 Critical; 1 Important + 2 Warning + 8 Suggestion closed by `48690b7`, or recorded as residuals |
| QA gate | pending | residuals to be adjudicated at the L4 gate |
