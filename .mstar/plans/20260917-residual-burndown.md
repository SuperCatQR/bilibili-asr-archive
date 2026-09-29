# Residual burn-down: bounded retries, bounded n-gram work, reachable doubt locations, narrowed import surface

> Post-iteration residual work on `main` @ `bc425f6`, following `iter-2026-09-asr-ops-hardening` (terminal).
> Primary specs: `.mstar/iterations/iter-2026-09-asr-ops-hardening/specs/02-batch-reuse.md` (D2.6, frozen line shape),
> `specs/03-quality-surface.md` (frozen `to_dict` keys / CSV columns / `schema_version`), `specs/04-provenance-observability.md` (D4.8).
> Execution mode: `inline` — 4 independent single-seam changes + one test-drift repair; no new module, no new CLI command.

## Status

- Priority: P3 (residual burn-down; nothing here blocks a corpus run)
- Task category: `logic` / residual closure
- Status: Done
- Owner: fullstack-dev · QA gate: pm-acceptance (no mandatory E2E; operator instruction: "不针对这个改动进行 e2e，后续常规测试时候留意一下")
- Findings cleanup: zero-residual
- Depends on: nothing. `bc425f6` (the P1+P2 pass) is the base and is the reason T5 exists.

## Goal

Close the four open code-side residuals of `iter-2026-09-asr-ops-hardening` that were deferred to "the
next plan touching this code", and repair the test drift `bc425f6` left behind — without changing any
frozen output contract, and without inventing a new surface.

## Specify (measured defects, verified at `bc425f6`)

- **S1 (provenance R2).** `ASRRunner._get_model` retries a failed factory call **once per row with no cap**:
  an N-row batch whose load always fails pays N attempts. Measured: `tests/test_asr_reproducibility.py:1068`
  asserts `len(attempts) == 3` for three rows — the retry is per-row, unbounded.
- **S2 (quality R2).** `_check_content`'s repeated-ngram pass builds a `Counter` over **every** 8-char window
  of the joined transcript: `quality.py:648-653`, bounded only by `_MAX_BYTES` (8 MiB → ~8 M windows).
- **S3 (quality R1).** The retirement map's `asr_low_confidence_at` row ("where the doubt is") has **no live
  surface**: `quality.py:629-633` reports `low_confidence` as a bare reason with no count and no location, and
  `Cue.confidence` never reaches the report even though the raw sidecar carries per-cue scores.
- **S4 (subtitle-gateway R1).** `bilibili_api_gateway.py:26` binds the whole `user` module
  (`from bilibili_api import Credential, request_settings, user`), so `user.get_api` reaches **every**
  endpoint description in the package without a forbidden-token hit; the import-surface test's own docstring
  names this as a known hole.
- **S5 (test drift, introduced by `bc425f6` — found during this plan's recon).** `bc425f6` flipped the
  all-loads-failed behaviour from *silent* to *printing a diagnostic* (`coordinator.py:813-820`) and rewrote
  the README paragraph accordingly, but touched **no test** (`git show --stat bc425f6`): three assertions now
  pin the retired behaviour and `main` is **red** — measured `1557 passed / 3 failed / 4 skipped / 5 errors`
  (the 5 errors are `test_cli_help.py`'s installed-wheel fixtures, an environment gap unrelated to this plan).

## Clarify (decisions)

1. **Retry cap semantics.** A *failed* load is retried per row today; the cap bounds the **attempts**, not the
   rows. Cap = `MAX_MODEL_LOAD_ATTEMPTS` in `asr.py`; once spent, `_get_model` raises the existing
   `ASRModelError` **without calling the factory again**, so the counter never exceeds the cap. `model_load_attempts`
   keeps its documented meaning ("every factory invocation") — deliberately **not** extended to "suppressed
   attempts", because the run-scoped provenance knowledge doc pins `model_load_attempts >= model_constructions`
   and the README derives `attempts - constructions == failed loads` from it.
2. **Bounded n-gram work.** Keep the pinned window and threshold (`_NGRAM_CHARS = 8`, `_NGRAM_MIN_REPEATS = 3` —
   `test_ngram_window_is_the_pinned_eight_characters` pins both from both sides) and keep the **exact** answer for
   every text up to a new `_NGRAM_MAX_CHARS` bound; above it, scan a bounded window count instead of all of them.
   The scan is a *counter*, so a bounded prefix scan can only under-report a repeat that begins beyond the bound —
   acceptable for an advisory code, and it must be documented as such.
3. **Reachable doubt locations without changing the contract.** `specs/03` freezes `QualityResult.to_dict()` keys,
   the CSV column tuple and `schema_version`, but it already ships a precedent for extra information on **stderr**
   (the reference-agreement ratio). So: carry the locations on `QualityResult` as a new **keyword-only dataclass
   field with a default** (positional construction is impossible — the single construction site is keyword-only,
   and the field is appended after `reference`), project them **only** into the human-facing CSV path as an extra
   stderr line, and leave `to_dict()`, the CSV columns and the JSON document byte-identical.
4. **Narrowed import surface.** Replace the module-wide `user` binding with the three names the adapter actually
   uses (`API`, `User`, `VideoOrder`, all verified importable from `bilibili_api.user`), so its reach is exactly
   those three attributes and `user.get_api` is no longer reachable. `ALLOWED_PACKAGE_IMPORTS` gains a
   `bilibili_api.user` row and **loses the `user` name** from the package-root row; the exact-equality assertion
   (`imports == ALLOWED_PACKAGE_IMPORTS`) keeps it honest.
5. **N-4 stays open by operator decision.** The six Latin-script hotwords remain unverified ("待下次有音频时验证"):
   the only video that speaks them (`BV1eGJ46mEHQ`) lost its audio when `e2e-asr/batch10-gpu` was deleted on
   2026-09-17, so no A/B is possible without re-downloading. Its register row is **edited, not closed** — target and
   tracking are re-stated to name the deletion and the re-download requirement.
   *(Correction 2026-09-25: the audio was not lost — that deletion removed an empty `audio/`; the `.m4a` survives at
   `.tmp/batch10/archive/audio/BV1eGJ46mEHQ.p0.m4a`. This paragraph is left as written; see the register row for the
   full correction.)*

## Tasks

### Task 1: Cap the model-load retries

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/asr.py`
- Test: `bilibili-asr-archive/tests/test_asr_reproducibility.py`

**Interfaces:**
- Consumes: `ASRRunner._get_model`'s failure path and `model_load_attempts` (unchanged meaning).
- Produces: `MAX_MODEL_LOAD_ATTEMPTS` (module constant, in `asr.py`).

- [x] Add `MAX_MODEL_LOAD_ATTEMPTS` and refuse further factory calls once `model_load_attempts` reaches it,
      raising the existing `ASRModelError` (never `ASRModelError`-wrapping a suppressed call).
- [x] Keep `model_load_attempts >= model_constructions` and `attempts - constructions == failed loads` intact.
- [x] Test: an N-row batch with N above the cap pays exactly the cap in attempts; a load that fails then succeeds
      still succeeds inside the cap; the cap is not reachable in a healthy run.
- [x] Test: the existing per-row retry test still holds below the cap.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_asr_reproducibility.py -q`

### Task 2: Bound the repeated-ngram scan

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/quality.py`
- Test: `bilibili-asr-archive/tests/test_quality.py`

**Interfaces:**
- Consumes: the joined cue text and the pinned `_NGRAM_CHARS` / `_NGRAM_MIN_REPEATS`.
- Produces: `_NGRAM_MAX_CHARS` (bounded window count); the `repeated_ngram` content code keeps its spelling.

- [x] Extract the scan into one helper that takes the text and returns whether a window repeats, so the bound
      lives in exactly one place.
- [x] Keep the exact answer at and below the bound; above it, scan a bounded number of windows.
- [x] Keep `_NGRAM_CHARS == 8` and `_NGRAM_MIN_REPEATS == 3` (the both-sides pinning test must stay green).
- [x] Test: the pinned window fixture still fires; a repeat that begins past the bound is allowed to be missed
      (documented, asserted as the bound's own contract); a body at exactly the bound is still exact.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_quality.py -q`

### Task 3: Make the low-confidence locations reachable, without touching the frozen contract

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/quality.py`
- Modify: `bilibili-asr-archive/src/bili_asr/cli.py`
- Test: `bilibili-asr-archive/tests/test_cli_help.py`

**Interfaces:**
- Consumes: `Cue.confidence` (already parsed from the raw sidecar) and the published `LOW_CONFIDENCE` threshold.
- Produces: a new keyword-only `QualityResult` field carrying the low-confidence cue starts; a stderr line on the
  CSV path only.

- [x] Collect the low-confidence cues' start seconds (ascending, 3 decimals — the archive's own rendering) beside
      the existing `low_confidence` reason, from the same filtered list so count and locations cannot disagree.
- [x] Add the field to `QualityResult` **after** `reference`, keyword-only with a default, so the single
      keyword-only construction site and every consumer keep working.
- [x] Leave `to_dict()`, the CSV column tuple, `schema_version` and the JSON document byte-identical; print the
      locations on **stderr** for the human CSV path only (the `coverage --quality` precedent), and never on the
      JSON path.
- [x] Test: the JSON payload is unchanged; the CSV path emits the line; a row with no recorded scores emits
      nothing (not computed rather than fabricated).

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_cli_help.py -q`

### Task 4: Narrow the gateway's `user` import surface

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py`
- Test: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`

**Interfaces:**
- Consumes: the three `bilibili_api.user` names the adapter uses.
- Produces: a per-module import row in `ALLOWED_PACKAGE_IMPORTS`; the package-root row loses `user`.

- [x] Import `API`, `User`, `VideoOrder` from `bilibili_api.user` and drop the module-wide `user` binding.
- [x] Update the three call sites (`user.API[...]`, `user.VideoOrder.PUBDATE`, `user.User(...)`) and the comment
      that documented the module-wide binding as residual R1.
- [x] Update `ALLOWED_PACKAGE_IMPORTS` (add the `bilibili_api.user` row, remove `user` from the root row) and the
      surface test's docstring so it no longer describes the hole as open.
- [x] Test: the exact-equality import check passes; `get_api` is no longer reachable through the adapter's names.
- [x] Keep `FORBIDDEN_SEAM_METHOD_TOKENS` and the positive controls untouched.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_bilibili_api_gateway.py -q`

### Task 5: Repair the test drift `bc425f6` left behind

**Files:**
- Modify: `bilibili-asr-archive/tests/test_asr_reproducibility.py`
- Modify: `bilibili-asr-archive/README.md` (only if an assertion needs a phrase the README does not carry)

**Interfaces:**
- Consumes: the shipped behaviour of `bc425f6` (diagnostic on all-loads-failed, `RunSummary.model_load_attempts`).
- Produces: three tests that pin the **current** contract instead of the retired one.

- [x] `test_a_batch_whose_every_load_fails_is_silent_and_pays_n_attempts` → assert the diagnostic **is** printed
      (its name and docstring must state the new contract, not silently invert).
- [x] `test_the_attempt_count_survives_on_the_runner_the_batch_no_longer_holds` → drop the
      `hasattr(summary, "model_load_attempts")` negation; assert the summary carries the count.
- [x] `test_readme_states_the_attempts_are_recorded_rather_than_printed` → assert the README's **current** phrases
      (the diagnostic is named; the "recorded, not printed" claims that no longer exist are gone).
- [x] Test: the three pass, and the whole file is green.

Run: `cd bilibili-asr-archive && .venv/bin/python -m pytest tests/test_asr_reproducibility.py -q`

### Task 6: Register bookkeeping

**Files:**
- Modify: `.mstar/projects/_default/residuals.json`

- [x] Close the five rows `bc425f6` already fixed (in place: `lifecycle`, `closed_at`, `closure_note`,
      `closure_evidence` naming the commit and the measured evidence).
- [x] Close the four rows this plan fixes, pointing `closure_evidence` at this plan's tasks and tests.
- [x] Close `20260912-batch-model-reuse · R1` — its `decision` is already `verified-closed` but its lifecycle
      still reads open.
- [x] **Edit, do not close**, `20260912-gpu-enablement-truth · N-4` (operator decision): restate the target as
      "the next transcription of a video that speaks ITEM/AITEM/tribunal, which now requires re-downloading the
      audio (the 2026-09-17 `e2e-asr/batch10-gpu` deletion removed the only copy)".
      *(Correction 2026-09-25: no re-download is required — the copy survived at
      `.tmp/batch10/archive/audio/BV1eGJ46mEHQ.p0.m4a`; the quoted re-statement is left as written. See the
      register row.)*
- [x] Validate the register against the schema (9 required fields; `lifecycle` ≠ open implies `closed_at` +
      `closure_note`; `source_plan` equals its entries key).

## Verification

- Targeted: the five test files named above, each run in its own task.
- Baseline: `cd bilibili-asr-archive && .venv/bin/python -m pytest -q` — expect **3 failed → 0 failed**, with only
  the 5 pre-existing `test_cli_help.py` installed-wheel errors remaining (an environment gap, recorded in Scope).
- No E2E: per operator instruction this change carries no browser/device/installed-deployment run; the operator
  will watch it during routine testing instead.
- Preview: the four changes are readable in one sitting; no change touches a frozen contract, so the diff is the
  evidence.

## Scope

- **In:** `asr.py`, `quality.py`, `cli.py` (one stderr line), `sources/bilibili_api_gateway.py`, the two test files,
  `README.md` (only if Task 5 needs it), the register.
- **Out of scope, recorded:** the 5 `test_cli_help.py` installed-wheel errors (no wheel installed on this host;
  they are not a code defect); `N-4` (stays open by operator decision); every non-residual improvement raised
  in review (CLI flags for hotwords/device/keep-audio, the `_materialize_input` copy, long-audio chunking) —
  those are new features, not residual closure.

## Evidence log

| Date | Evidence |
|------|----------|
| 2026-09-17 | Recon at `bc425f6`: 5 of the 11 registered rows are already fixed in code but still `open` in the register; `main` is red with 3 failures caused by `bc425f6` touching behaviour + README without touching tests (`1557 passed / 3 failed / 4 skipped / 5 errors`). |

## Review Gate Summary

| Gate | Decision | Notes |
|------|----------|-------|
| Task reviews | — | single-plan inline execution; no task reviewers dispatched |
| Plan QC | — | not required for `Execution mode: inline` residual closure |
| QA gate | pm-acceptance | targeted tests + a green non-E2E baseline; operator watches it in routine testing |

## Completion Report (2026-09-17)

**Result.** All 4 code changes landed, the 3 drifted tests were re-pinned to the shipped contract, and the register
now reads **1 open item (N-4, by operator decision)** where it read 11.

**Files changed (10):** `src/bili_asr/asr.py` (cap), `src/bili_asr/quality.py` (bounded n-gram + `low_confidence_at`),
`src/bili_asr/cli.py` (one stderr line), `src/bili_asr/sources/bilibili_api_gateway.py` (narrowed import),
`README.md` (cap + diagnostic), 4 test files, `.mstar/projects/_default/residuals.json`.

**Verification.** `cd bilibili-asr-archive && .venv/bin/python -m pytest -q` → **1568 passed / 0 failed / 4 skipped /
5 errors** (was 1557 passed / 3 failed). The 5 errors are the pre-existing `test_cli_help.py` installed-wheel fixtures
(`uv pip install -e ".[dev]"`), an environment gap untouched by this plan. Per-task runs: quality 62 passed, gateway
327 passed / 1 skipped, asr-reproducibility 98 passed, cli-help 96 passed / 5 errors.

**No E2E**, per operator instruction; the operator will watch these paths during routine testing.

**Schema.** The register validates clean (9 required fields, enum-checked `severity`/`decision`/`lifecycle`,
`closed_at` + `closure_note` on every closed row, `source_plan == entries key`), and the engine's own rollup now
prints `residuals: low 1`, matching the register.

**Latent defect found and corrected:** `20260912-batch-model-reuse · R1` carried `decision: "verified-closed"`, which
is outside the engine's `defer | accept | risk-accepted` enum — that one value made the **whole register unwritable**
by the engine. Corrected to `defer` while closing the row.
