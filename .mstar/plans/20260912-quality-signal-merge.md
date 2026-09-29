# Content-quality reasons folded into the existing quality surface

> Iteration `iter-2026-09-asr-ops-hardening`, spec point 3 → acceptance **A3**.
> Primary spec: `.mstar/iterations/iter-2026-09-asr-ops-hardening/specs/03-quality-surface.md`.
> Execution mode: `sdd` (3 tasks).

## Status

- Priority: P1
- Task category: `logic` / quality reporting
- Status: Done
- Depends on: nothing (P4's low-confidence locations are read by the same surface but do not block it)
- Owner: fullstack-dev · QA gate: mandatory (existing command's output contract)
- Findings cleanup: zero-residual
- Evidence: audit guide §4.3

## Goal

One command answers "is this archive's transcript content sound": the content signals that
today live in a parallel script are reasons in the existing quality vocabulary, and the
parallel script is gone.

## Specify (measured defects)

- **Q1.** `src/bili_asr/quality.py` owns the shape layer with seven reason codes
  (`empty`, `malformed`, `non_monotonic`, `overlap`, `out_of_range`, `identity_mismatch`,
  `artifact_missing`) and is reached through `bili-asr coverage --quality`.
- **Q2.** The content layer added on 2026-09-12 — per-cue confidence, fragment/over-long
  cues, duplicate cues, repeated n-grams, and cross-system agreement — lives in
  `bilibili-asr-archive/scripts/asr_quality.py`, which the coverage surface does not know
  about. Two entry points for one question.
- **Q3.** The recorded cue fixture shows what a naive port would cost: the content code
  `low_confidence` fires once and `overlong_cue` twice on a healthy transcript, so content
  reasons must not flip a good archive to a failure exit.

## Clarify (decisions — spec 03 owns the detail)

1. **Additive vocabulary**: seven content codes appended to `REASON_CODES`
   (`low_confidence`, `leading_mark`, `fragment_cue`, `overlong_cue`, `duplicate_cue`,
   `repeated_ngram`, `reference_disagreement`).
2. **Two classes**: `REASON_CODES` splits into `DEFECT_REASON_CODES` (today's seven) and
   `CONTENT_REASON_CODES` (new); only defects drive `valid_work_items` and the exit code —
   content reasons are advisory.
3. **One parser**: `_read_cues` returns cue records (start, end, text) once; confidence is
   read from the already-present `transcripts/raw/<stem>.json`; no model re-run.
4. **Reference agreement** arrives as `--reference <path>`, requires exactly one selected
   row, emits the `reference_disagreement` reason plus a JSON `reference` block carrying the
   basename only (never a path).
5. **Retirement**: `scripts/asr_quality.py` and `tests/test_asr_quality_script.py` are
   deleted; every output of the script has a named replacement in the coverage surface
   (the spec's retirement map). `--fail-under` is deliberately not ported.

## Non-goals

- Changing the seven existing reason codes, their semantics, or the coverage output shape.
- Any automatic repair, re-transcription, or text editing driven by content reasons.
- The `{SPECS_DIR}`/knowledge amendment requests recorded by the architect (iteration-close).

## Architecture

| Surface | Change |
|---|---|
| `src/bili_asr/quality.py` | Content codes, two-class split, cue-record parser, `--reference` input |
| `src/bili_asr/cli.py` | `coverage --quality --reference <path>` plumbing |
| `scripts/asr_quality.py`, `tests/test_asr_quality_script.py` | Deleted |
| `tests/test_quality.py`, `tests/test_coverage_report.py`, `tests/test_cli_help.py` | New content-reason coverage; existing assertions unmodified |

## Tasks

### Task 1: Two-class reason vocabulary and the cue-record parser

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/quality.py`
- Test: `bilibili-asr-archive/tests/test_quality.py`

**Interfaces:**
- Consumes: `transcripts/raw/<stem>.json` (per-cue `confidence`), the SRT cue text, `artifacts` already resolved by the analyzer.
- Produces: `DEFECT_REASON_CODES` (today's seven) + `CONTENT_REASON_CODES` (seven new); `_read_cues` returning cue records `(start, end, text)`.

- [x] Split `REASON_CODES` into `DEFECT_REASON_CODES` and `CONTENT_REASON_CODES`, keeping `REASON_CODES` as the ordered union so existing output stays comparable.
- [x] Add the content codes: `low_confidence`, `leading_mark`, `fragment_cue`, `overlong_cue`, `duplicate_cue`, `repeated_ngram`, `reference_disagreement`.
- [x] Change `_read_cues` to return cue records once; compute `low_confidence` from the raw sidecar (no model re-run), and the text reasons locally.
- [x] Ensure only defect reasons affect `valid_work_items` and the exit code; content reasons are advisory.
- [x] Test: each content reason fires on a crafted artefact; the recorded cue fixture yields `low_confidence` ×1 and `overlong_cue` ×2 with no defect reason, and the process still exits 0.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_quality.py -v`

### Task 2: Reference agreement and CLI plumbing

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/quality.py`
- Modify: `bilibili-asr-archive/src/bili_asr/cli.py`
- Test: `bilibili-asr-archive/tests/test_cli_help.py`

**Interfaces:**
- Consumes: Task 1's vocabulary; the coverage command's existing scope selectors.
- Produces: `coverage --quality --reference <path>`; a `reference` block in the JSON output carrying the basename only.

- [x] Project `QualityResult.content_reasons` into the coverage output — per-row reasons and the summary's reason counts — while `valid_work_items` and the exit status keep reading the defect codes alone (spec 03's Task-1-review amendment).
- [x] Add `--reference` to the coverage-quality command; require exactly one selected row when it is supplied, otherwise a diagnostic (not a traceback).
- [x] Emit `reference_disagreement` when the two transcripts' agreement falls below the threshold the spec names, with the JSON `reference` block carrying the basename and the compared character counts.
- [x] Never serialize a path, URL, or credential-like value in the block.
- [x] Test: agreement above/below threshold; the single-row requirement; the basename-only rule; `--fail-under` is not ported.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_cli_help.py -v`

### Task 3: Retire the parallel script

**Files:**
- Delete: `bilibili-asr-archive/scripts/asr_quality.py`
- Delete: `bilibili-asr-archive/tests/test_asr_quality_script.py`
- Test: `bilibili-asr-archive/tests/test_coverage_report.py`

**Interfaces:**
- Consumes: the retirement map in spec 03 (every script output → its coverage replacement).
- Produces: one quality entry point; no orphaned references.

- [x] Delete the script and its test; remove every reference (docs, README, comments) that names them.
- [x] Verify the retirement map is complete by running the coverage command on an archive that holds ASR transcripts and comparing the reported signals against `git show <iteration-base>:scripts/asr_quality.py`.
- [x] Keep `tests/test_quality.py` and `tests/test_coverage_report.py` assertions unmodified; add coverage for the new codes only where a gap exists.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_quality.py tests/test_coverage_report.py tests/test_cli_help.py -v`

## Verification

- `bili-asr coverage --quality --archive-root <root>` on an archive holding ASR transcripts
  reports the content reasons; the signal list matches the retired script's outputs.
- `git ls-files scripts/asr_quality.py tests/test_asr_quality_script.py` is empty.
- `tests/test_quality.py` + `tests/test_coverage_report.py` pass with unmodified assertions;
  `tests/test_cli_help.py` gains the content-reason cases.
- `tests/test_asr_cues.py` unmodified (A6 guard).

## Durable Roadmap and Dependencies

- **Inherited residual R1 (medium, from `20260912-gpu-enablement-truth`)**: `scripts/verify_baseline.py`'s
  `staged_test_tree()` stages `tests/test_check_asr_env.py` but a `scripts/` holding only
  `verify_baseline.py`, so the module's `from scripts.check_asr_env import …` cannot resolve and the
  documented baseline gate aborts with zero tests collected (`rc=2`). This plan deleted the *other* instance of
  the class (`tests/test_asr_quality_script.py`) but does **not** own `scripts/verify_baseline.py`, so the fix did
  not land here (plan-QC seats 1/2, I1/I4 — verified live at head). **Re-targeted at plan-QC (2026-09-13): the next
  iteration that owns the verification baseline**, trigger = its start; recorded in this iteration's compass
  `## Roadmap Position` as a Next-iteration item. **Register cross-reference:** `{PROJECT_DIR}/_default/residuals.json` → `entries["20260912-gpu-enablement-truth"][id=R1]` (`target` re-pointed to that next iteration, `tracking` names this plan's QC).
- **Inherited residual N-3 (low, from the L4 QA gate)**: `guides/hygiene-report.md:15,30` carries a third live
  bare `python3.12 scripts/check_asr_env.py` form, outside R2's registered scope. Fold into this plan's
  documentation pass or into iteration-close's spec refresh.

## Evidence log

| Date | Evidence |
|------|----------|
| 2026-09-13 | T1 `fc13614` — two-class vocabulary + one cue-record parser; PM resolved the brief/D3.2 conflict as two fields (spec 03 amendment); **Approved with Minor**. |
| 2026-09-13 | T2 `9575d6b` + fix `c06e56a` — content projection + `--reference`; review Request Changes (the `.md` bundle could become the comparison source) → artefact rank + frontmatter strip → **Approved with Minor**. |
| 2026-09-13 | T3 `faebe2d` — retired `scripts/asr_quality.py` + its test, retirement map verified signal-by-signal on a real root; **Approved with Minor**. |
| 2026-09-13 | Plan QC tri (N=3, one batch): **all three `Approve with residuals`**, 0 Critical, 6 Important across seats (2 security/correctness: unbounded comparison time, underscore-adjacent credential leak; 1 truthfulness: plain-text rows lose all content reasons; 1 residual ownership; 1 map gap; 1 operability). Consolidated at `{SDD_DIR}/review/qc-consolidated.md`. |
| 2026-09-13 | Fix wave `5b39333` — separator-aware redaction, `_MAX_COMPARE_CHARS` time bound, no-comparable-text rule documented, ngram boundary + mixed-row order pinned, two doc corrections → re-review **Approve with residuals**, no regression. |
| 2026-09-13 | PM-side: R1 re-targeted (register + compass Next-iteration item), plan-3 R1/R2 registered, hygiene-report claim corrected, spec 03 retirement map corrected (title, explicitly-dropped outputs, per-shape parity, bounds follow-up). |
| 2026-09-13 | L4 QA gate (`review/qa-gate.md`): **Approve with residuals**; A3 checks 1–6 PASS; suite at head **1491 passed / 4 skipped**. |

## Review Gate Summary

| Gate | Decision | Notes |
|------|----------|-------|
| Task reviews | Approved with Minor ×3 | One Important closed per fix round in T2; no open Critical/Important at any task close |
| Plan QC | **Approve with residuals** | tri-review N=3 (one batch), 0 Critical, 6 Important closed by `5b39333`; final re-review `review/qc-fix-1-review.md` |
| QA gate | **Approve with residuals** | residuals R1 (low), R2 (low); production-root reproduction still unproven from this host |
