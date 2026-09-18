# Verification-surface truth: one definition of manifest well-formedness, and the intermittent suite red

> **For agentic workers:** REQUIRED SUB-SKILL: Use `mstar-sdd` (recommended) or inline execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the project's own verification surfaces tell the truth — a normally-produced manifest (append-only state history) stops being reported as malformed by `verify` **and** `coverage`, both adopting the judgement the `coverage --quality` branch already gets right, and the intermittent full-suite red is either traced to a named root cause or, when it cannot be reproduced on demand, made diagnosable at its next occurrence — never left a shrug. Nothing here loosens the gate: the change is bidirectional by construction (healthy history passes, real damage still fails closed).

**Closes:** `e2e-23191782-season-7686105 · R2` (criteria 1–4) and `20260917-hotword-acronym-precision · R1` (criterion 5) — iteration compass `{ITERATION_DIR}/iter-2026-09-residual-closeout/delivery-compass.md` `## Acceptance Criteria`.

**Architecture:** The manifest is append-only by design (`operational-sidecars.md` #10: durable sidecars stay append-oriented and projection-based), so one work_id legitimately yields several rows (`needs_audio` → `audio_ok` → `archived`). `sidecar_projection.project_manifest_records` emits `manifest_duplicate_work_id` for exactly that history and takes the latest row — correct, and it stays (criterion 1 retains the emitter). What is wrong is that **three readers each decide what the code means**: `integrity.py` has no entry for the string in its recognised-diagnostic vocabulary (L211–229), so the else-branch (L228-229) maps it to `structural_input_error` and `cli.py`'s `0 if not defects and not diagnostics` (L2800) turns a healthy archive into exit 1; `coverage_report.py` both forces `manifest_state = "malformed"` (L76-77) — which makes `denominator_available` False (L198) and blanks every ratio (L223-224) — and carries the code in the report's `diagnostics` set (L68-75), so `_cmd_coverage`'s `1 if report.data["diagnostics"] else 0` (L1497) exits 1; and the `coverage --quality` branch keeps its own copy of that projection (cli.py L1267-1274) with the same any-diagnostic exit rule (L1478), so it **also exits 1 on a healthy archive** — its denominator is the only part that is right today. The fix is therefore one named judgement, subtracted in the three readers, rather than three separate repairs (spec §2), and it is one-directional only in appearance: every other unrecognised code still fails closed.

Measured on a scratch root with real history (`/tmp/arch-probe/root2`, 3 rows / 2 work_ids, all four sidecars valid): baseline `verify` exit 1 (`defects 0`, `diagnostic structural_input_error`), `coverage` `count None` exit 1, `coverage --quality` `count 2 available` **exit 1**. With the recognition branch added and the code subtracted in both coverage projections: `verify` `diagnostics []` exit 0, `coverage` `count 2 / available / cumulative complete / diagnostics []` exit 0, `coverage --quality` exit 0 — with `defects` and `recover`'s `authoritative` identical before and after.

**Tech Stack:** Python 3.12, pytest, the repo's own sidecar projection / integrity / coverage modules.

**Execution:** mstar-sdd

**Main worktree branch**: `main`

## Global Constraints

- **Every command in this plan names its working directory.** Two roots are in play and neither is a
  superset of the other: the **repository root** `/root/workspace/bilibili-asr-archive` (holds `.mstar/`,
  `.git`, and the package directory `bilibili-asr-archive/`) and the **package root**
  `/root/workspace/bilibili-asr-archive/bilibili-asr-archive` (holds `.venv/`, `src/`, `tests/`).
  Python and pytest always run from the **package root** as
  `cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && .venv/bin/python -m pytest …`;
  the form `bilibili-asr-archive/.venv/bin/python -m pytest tests/…` is runnable from neither root
  (no `tests/` at the repository root, no `bilibili-asr-archive/.venv` under the package root).
- Python 3.12; the only interpreter used is the repo venv at
  `bilibili-asr-archive/.venv/bin/python` (i.e. `.venv/bin/python` from the package root).
- **Do not change the frozen contracts**: `coverage`'s CSV column tuple, `coverage-quality-v1` / `coverage-report-v1` `schema_version`, the two-class quality vocabulary (defect codes decide validity, content codes are advisory), and `REASON_CODES` order all stay byte-identical.
- Append-only + projection stays the storage model; **no** manifest compaction, in-place rewrite, or migration is introduced, and the emitter in `sidecar_projection.py` (L216) stays.
- The fix is **bidirectional**: healthy history must reach exit 0 / `available`, and genuinely malformed input must still fail closed. A one-directional change that merely stops complaining is not acceptable. Concretely: subtracting the one ordinary-history code is allowed at the readers; silencing the else-branch, or making any *other* unrecognised code benign, is not.
- **One judgement, not three.** The ordinary-history code must be named once (`ORDINARY_HISTORY_DIAGNOSTICS` in `sidecar_projection.py`, beside the projection that emits it) and subtracted at the three reader sites named in Task 1. A reader that filters it by quoting the literal string a fourth time, or a coverage reader that keeps reporting it while only the denominator is repaired, is a regression against this constraint.
- `recover`'s `authoritative` semantics are unchanged (it is computed from the projection's diagnostic sets at integrity.py L233-236, never from `report.diagnostics`; manifest-side history must not change it either way).
- Verification scope follows `mstar-harness-core` § 定向执行与验证边界: only changed behaviour and direct contracts. **Local full-suite runs are authorized for Task 3 only** — the operator selected the "bounded diagnosis" option on 2026-09-18, which requires repeated full-suite runs to reproduce an intermittent failure; that permission does not extend to other tasks and is cited in each Task 3 Assignment `Constraints`.
- Never assign real-browser/device/installed-deployment E2E evidence as a task or gate of this plan; each layer proves itself with its own unit/integration tests.

## Engine lifecycle

Who advances this plan row's engine state, and what records each transition:

- **Scoped sequence** — one engine verb per transition; never a hand-edited snapshot: `bind --coordinator` → `prepare` → `bind` → `progress` → `handoff` → `accept` → `integration-start` → Git merge → `integration-accept` → `complete`.
- **Evidence order** — `compound` disposition, PR identity and merge evidence are recorded **after** the row is `Done`; the engine refuses those writes while any plan row is not `Done`. The delivery tail runs on a completed row, never ahead of it.
- **Snapshot declares no integration anchors** → the row cannot reach `Done` today: stop at a submitted/accepted handoff, report the blockage to the coordinator, and never fabricate a terminal state (`Done`, `completed`, PR identity, merge record).

Semantics and failure behavior → `mstar-artifacts/references/plan-workflow-lifecycle-contract.md`; PM step sequence → `mstar-roles/references/project-manager/plan-management.md`.

---

### Task 1: Recognise append-only history in the manifest readers

**Effort (agent-oriented):** S

**Split point:** If the change to `integrity.py` and the change to the two coverage projections cannot both be landed and tested in one round, split by reader: Task 1a `integrity.py` (recognition + exit contract), Task 1b the coverage readers (subtract the code in `coverage_report.build` and in `cli._cmd_coverage_quality`, drop the malformed override) — each closes its own file and its own assertion.

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/sidecar_projection.py` — **add one module-level name only**: `ORDINARY_HISTORY_DIAGNOSTICS = frozenset({"manifest_duplicate_work_id"})` beside the projection that emits the code. The emitter at L216 is untouched (criterion 1 retains it).
- Modify: `bilibili-asr-archive/src/bili_asr/integrity.py` (the recognised-diagnostic loop L211–229: one branch that maps the ordinary-history code to nothing, placed before the else-branch at L228-229)
- Modify: `bilibili-asr-archive/src/bili_asr/coverage_report.py` (delete the `manifest_duplicate_work_id` → `"malformed"` override at L76-77, and subtract `ORDINARY_HISTORY_DIAGNOSTICS` from the codes projected into `diagnostics` at L68-75)
- Modify: `bilibili-asr-archive/src/bili_asr/cli.py` (`_cmd_coverage_quality`'s copy of the same projection, L1267-1274 — subtract the same set). **This one line is what makes the iteration's claim true**: without it the `--quality` branch keeps exiting 1 on a healthy archive, which is measured, not inferred (spec §1). The exit *rule* at L1478 is not touched, and neither is `_cmd_coverage`'s at L1497.
- Test: `bilibili-asr-archive/tests/test_integrity.py` + the three contract-pinning cases named in Task 2 (they live in `test_coverage_report.py` / `test_cli_help.py` and are Task 2's edits)
- Out of scope: `sidecar_projection.py`'s emitter (it stays — the projection is allowed to say what it saw: `project_manifest_records` still returns the code in its `diagnostics` to every caller, and that return value is where the fact remains visible), `coverage_report.py::_read_manifest` (L288-329, a helper with **no call site** anywhere in src/ or tests/ — its L325 duplicate branch is unreachable and is neither the reason the emitter stays nor a second judgement to keep in sync), `cli.py`'s exit rules (L1478, L1497) and the `verify` exit rule (L2800).

**Interfaces:**
- Consumes: `sidecar_projection.project_manifest_records(path, *, policy)` → `(entries, state, diagnostics)`; `ManifestStore` rows; the new `ORDINARY_HISTORY_DIAGNOSTICS` set.
- Produces: an `integrity.py` whose `diagnostics` list no longer contains `structural_input_error` for ordinary history, a `coverage_report.py` and a `cli._cmd_coverage_quality` whose projected `diagnostics` no longer contain the ordinary-history code (so their exit rules see nothing to fail on) and a `coverage_report.py` whose `manifest_state` stays `"available"` for it — all consumed by Task 2's assertions. `manifest_state`, `report.defects` and `report.authoritative` are unchanged by the recognition branch (measured: `authoritative` `true` → `true`, `defects` identical).

- [ ] **Step 1: Write the failing unit test**

```python
def test_append_only_history_is_not_a_structural_error(tmp_path: Path) -> None:
    """One work_id with a real state history is ordinary, not malformed."""
    row = {"work_id": "BV1x:p0", "bvid": "BV1x", "cid": 7, "page_index": 0,
           "pubdate_str": "20260828", "title": "A", "status": "needs_audio"}
    paths = write_archive(tmp_path, {**row, "status": "archived"},
                          [{"start": 0, "end": 1, "text": "ok"}], source="cc")
    _manifest(tmp_path, [row, {**row, "status": "audio_ok"},
                         {**row, "status": "archived", **paths}])
    # The attempts sidecar must exist: without it integrity.py L238-241 files
    # `missing_attempts_sidecar` and the exit stays 1 for an unrelated reason.
    attempts = tmp_path / "coordinator" / "attempts.jsonl"
    attempts.parent.mkdir()
    attempts.write_text(json.dumps(_attempt("BV1x:p0", "ok")) + "\n", encoding="utf-8")
    report = IntegrityVerifier().verify(tmp_path)
    assert report.defects == []
    assert report.diagnostics == []          # -> cli.py L2800 then returns 0
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && .venv/bin/python -m pytest tests/test_integrity.py -k append_only_history -v`

- [ ] **Step 3: Minimal implementation**

In `sidecar_projection.py`, add the one name (`ORDINARY_HISTORY_DIAGNOSTICS`, beside the projection that emits the code — the emitter line itself is unchanged). In `integrity.py`, add one branch in the mapping loop, before the final `else`:

```python
elif diagnostic in ORDINARY_HISTORY_DIAGNOSTICS:
    continue
```

Treating it as expected append-only history is what the definition requires; the alternative — mapping it to a *benign diagnostic* — is **rejected**: `cli.py`'s exit rule counts *any* diagnostic, so a benign entry still forces exit 1.

In `coverage_report.py`, delete the `if "manifest_duplicate_work_id" in manifest_diagnostics: manifest_state = "malformed"` override **and** subtract the same set where the codes are projected into `diagnostics` (L68-75): `for code in manifest_diagnostics - ORDINARY_HISTORY_DIAGNOSTICS`. Deleting the override alone restores the denominator but leaves the report red, because `_cmd_coverage` exits non-zero on any diagnostic — measured, see the Architecture note. Apply the same subtraction to `cli._cmd_coverage_quality`'s copy of the projection (L1267-1274); nothing else in that branch changes.

- [ ] **Step 4: Run the same affected test — expect PASS**

Run: `cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && .venv/bin/python -m pytest tests/test_integrity.py -k append_only_history -v`

Reuse unaffected evidence with its original range and applicability; do not repeat checks merely because HEAD changed.

- [ ] **Step 5: Commit**

### Task 2: Pin the exit contract and the denominator with a real state history

**Effort (agent-oriented):** S

**Split point:** Split by surface if needed — integrity/exit assertions vs coverage/denominator assertions — each a self-contained test file change.

**Files:**
- Test: `bilibili-asr-archive/tests/test_integrity.py` (state-history fixture + two-way exit assertions)
- Test: `bilibili-asr-archive/tests/test_coverage_report.py` (denominator `available` + `count`, and **invert** the two cases that pin the old contract: `test_duplicate_manifest_makes_denominator_unavailable` L129-133 asserts `count is None` + the code present, and `test_cli_returns_diagnostic_exit` L248-251 asserts a doubled manifest makes `coverage` non-zero — the second keeps its purpose with a genuinely malformed row as its trigger)
- Test: `bilibili-asr-archive/tests/test_cli_help.py` (`test_module_coverage_formats_and_diagnostic_exit` L227-246: the duplicated-manifest half at L242-245 asserts `returncode == 1` and the code in stdout — it must assert the code is **absent** and the denominator available; the non-zero half moves to real damage. A CLI-level `verify` exit-0 case fits this file's conventions and is welcome)
- `tests/installed_cli.py` is the spawn helper those CLI cases already use (`run_module`), not a test file.
- Out of scope: production source (Task 1 owns it), `tests/test_verify_baseline.py` (Task 3's territory).

**Interfaces:**
- Consumes: Task 1's behaviour.
- Produces: the pinned contract the register closure for `R2` cites, **in both directions** — healthy state history → `verify` `defects: []`, `diagnostics: []`, exit 0; genuinely malformed input → still non-zero; `coverage --archive-root <root> --format json` → `denominator.state == "available"` with `count` equal to the work_id count **and exit 0**; `coverage --quality` → the same archive no longer fails on the history code (compass criteria 2–4).

- [ ] **Step 1: Write the failing tests**

Two-way assertions, all with a fixture that writes **two or more rows per work_id**:
1. healthy state history → `verify` `defects: []`, `diagnostics: []`, exit 0 (fixture must include `coordinator/attempts.jsonl`, else `missing_attempts_sidecar` keeps the exit at 1);
2. a genuinely malformed row (e.g. an invalid status, per `VALID_STATUSES`) → still non-zero and still reported;
3. `coverage --format json` on the healthy archive → `denominator.state == "available"`, `count == <number of work_ids>`, `manifest_duplicate_work_id` absent from `diagnostics`, exit 0 — the archive needs all four sidecars valid for the exit-0 half (an absent cursor/scheduler/run-ledger reports `evidence_missing` and keeps the exit at 1), while the code-absent half holds on any fixture;
4. the three inverted cases named in **Files** above, each with a one-line comment saying it used to pin the defect. Do not "fix" them by deleting the assertion — the point of the pair is that the same input now reaches the opposite verdict.

```python
# negative control — a real defect must still fail closed
assert cli_main(["verify", "--archive-root", str(root), "--format", "json"]) == 1
```

- [ ] **Step 2: Run tests — expect FAIL** (both halves fail until Task 1 lands: the healthy-history half because the reader still calls ordinary history a structural error, the inverted cases because they now assert the opposite of what the implementation does. Note what `-k "history or denominator"` selects today — verified by `--collect-only` on 2026-09-18, exactly one test, `tests/test_coverage_report.py::test_duplicate_manifest_makes_denominator_unavailable`, i.e. the case that pins the old contract.)

Run: `cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && .venv/bin/python -m pytest tests/test_integrity.py tests/test_coverage_report.py -k "history or denominator" -v`

- [ ] **Step 3: Adjust only test fixtures/assertions**

No production change is expected here; if one proves necessary, it belongs to Task 1 and this task goes back to the PM.

- [ ] **Step 4: Run the same tests — expect PASS**, with the negative control still failing closed.

- [ ] **Step 5: Commit**

### Task 3: Diagnose the intermittent full-suite red to a root cause

**Effort (agent-oriented):** M

**Split point:** The bounded diagnosis is one round; a fix that proves larger than one round splits into Task 3a (root cause + minimal fix) and Task 3b (bounds/regression test), with the diagnosis recorded either way.

**Files:**
- Modify (only if the root cause implicates it): the single source or test file the diagnosis names — candidates on current evidence are `tests/conftest.py`, `tests/test_verify_baseline.py`, or `scripts/verify_baseline.py` (it stages a tree and shells out to `pip`), but the diagnosis, not this list, decides.
- Create (only if the cause is outside this repo and cannot be reproduced on demand): a conftest-level hook that persists the setup-failure traceback to a stable path, so the next red is diagnosable — the deliverable then is the mechanism, not a guess.
- Test: the affected test file(s) once identified.
- Out of scope: repairing the environment; changing unrelated tests to hide the red.

**Interfaces:**
- Consumes: the recorded symptom — four consecutive full runs of one working tree produced **261 / 0 / 196 / 0** setup errors, cross-file, while `tests/test_verify_baseline.py` is 100 % green standalone (23 passed); `/tmp` space is already **ruled out** (a full green run moved the 3.7 GiB tmpfs by +31.4 MiB against ~1.7 GiB free).
- Produces: a root cause (with the captured ERRORS section as evidence) and either a fix or a documented boundary — or, when the red cannot be reproduced on demand, the diagnosability mechanism in place of a guess. All three branches are consumed by the register closure for `20260917-hotword-acronym-precision · R1`, and that closure must name **which branch** it took, the evidence file, and where the next red is read from; a note reading only "not reproduced" is not a closure (compass criterion 5).

- [ ] **Step 1: Reproduce with a captured traceback**

Run the full suite until red, capturing the body — **not** the summary:

Run: `cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && .venv/bin/python -m pytest -q --tb=long > /tmp/suite-red.log 2>&1; echo "exit=$?"` then read the `ERRORS` section of that file (grepping the summary is what failed last time: the summary counted 261 errors while a grep for the error text matched nothing).

- [ ] **Step 2: Read the traceback and name the failing fixture**

Record the fixture, its scope, and the exception type in the Completion Report. If the failing fixture is `tmp_path` or another builtin, say so explicitly — that points at the environment, not at repo code.

- [ ] **Step 3: Minimal fix, or the diagnosability hook**

If the cause is in this repo: fix it and pin it. If it is environmental/external: land the traceback-persistence hook, then record the boundary (what triggers it, what to do when it fires) in the file the diagnosis implicates. If the red cannot be reproduced on demand inside the bounded budget: the deliverable is the **mechanism** (that same hook) plus the verbatim run record — and the register closure must say so (compass criterion 5); "not reproduced" on its own is not an acceptable closure note.

- [ ] **Step 4: Verify**

Run the full suite at least twice after the change and record both outcomes verbatim (`<n> passed, <m> errors`) — an intermittent failure cannot be proven fixed by one green run, and the record must say so honestly rather than claiming a fix. These verbatim outcomes are the evidence the register closure cites.

Run: `cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && .venv/bin/python -m pytest -q 2>&1 | tail -3` (repeat; keep both tails verbatim)

- [ ] **Step 5: Commit**

## Plan self-review (PM before locked)

1. **Spec coverage:** `R2` → Tasks 1–2; `20260917-hotword-acronym-precision · R1` → Task 3. Both register entries have a closure path.
2. **Placeholder check:** every task names its files and a runnable command (each command names its working directory, per Global Constraints); Task 3's conditional target list is explicitly "the diagnosis decides", with the allowed file set named and the alternative deliverable (the hook) concrete.
3. **Type consistency:** `manifest_state` / `denominator_available` / `diagnostics` names match the source; line references were re-checked against the tree on 2026-09-18 (integrity L211–229, coverage L68-75 / L76-77 / L198 / L223-224, cli L1267-1274 / L1478 / L1497 / L2800); the fixture helper names (`write_archive`, `_manifest`, `_attempt`, `IntegrityVerifier`) are the ones already in `tests/test_integrity.py`, and the CLI spawn helper is `tests/installed_cli.py::run_module`.
4. **Capacity (task shape / session fit):** Tasks 1–2 are S and each closes its files and its assertions in one round; Task 3 declares an M band with a named split point, and its budget pressure never shortens the two-run verification in Step 4.
5. **One-definition check:** Task 1 edits four files for one named rule (`ORDINARY_HISTORY_DIAGNOSTICS`) and three subtraction sites; any implementation that repairs only `coverage`'s denominator fails spec §3.3's exit-0 half, and any implementation that also filters *other* codes fails the bidirectional constraint.

## SDD runtime (ephemeral)

When using `mstar-sdd`, artifacts live under `{SDD_DIR}` (see `mstar-conventions`). Do not duplicate briefs/reports in this file.
