# Operational record coverage: the pilot's ledger boundary, and a run that records its own interruption

> **For agentic workers:** REQUIRED SUB-SKILL: Use `mstar-sdd` (recommended) or inline execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the operational record from silently under-reporting in the two places the season audit found — a pilot-archived row that leaves no attempt trail and is therefore invisible to `--scope failed`, settled by **writing the boundary where an operator reads it** (`pilot --help`, `README.md`) rather than by giving the pilot a ledger of its own; and an externally killed `run` that leaves no run-level record at all, settled by **writing one**, carrying partial counts, on the interruption path.

**Closes:** `e2e-23191782-season-7686105 · R4` (documentation — **no behaviour change**; compass criterion **2**) and `· R5` (behaviour change, test-anchored; compass criterion **3**) — **both closed 2026-09-18** (verified closes; `R4` as an operator-surface close with its knowledge half handed to `mstar-compound`, `R5` scoped to the `run` entry point) — iteration compass `{ITERATION_DIR}/iter-2026-09-text-and-ledger-precision/delivery-compass.md` `## Acceptance Criteria`. *(Criterion numbers re-pointed 2026-09-18: the retirement of the cue criterion shifted the live set from 1–4 to 1–3, so R4's is 2 and R5's is 3 — see the compass `### Scope changes`.)*

**Architecture:** Two entry points and one exit path. `AttemptLedger` is instantiated only in `coordinator.py`, so the `pilot` command's in-process loop archives without persisting stage attempts — the knowledge doc scopes the ledger to "`bili-asr run`", so the omission is within the letter of the contract, but it lands on the failure that same paragraph warns about ("otherwise `--scope failed` silently drops rows") for a path the doc never names. Separately, `_cmd_run` (L2280-2338) appends its run-ledger record on the normal exit path only (`cli.py` L2327-2334, inside the `try:`/`with archive_writer(...)` block whose writer is opened at L2308) and `src/` installs no signal handling at all (grep for `SIGTERM`/`SIGINT` finds two unrelated prose matches), so a `SIGTERM` — the operator's own stop button — is exactly the case with no record.

Three structural facts decide how the interruption path must be built, and each is checkable in the tree:

- `run` is in `_ARCHIVE_WRITER_COMMANDS` (cli.py L2892-2902), so `main()` already holds the archive lock around the whole command; `_cmd_run`'s own `with archive_writer(...)` (L2308) is a same-thread passthrough (`archive_writer`, coordinator.py L72-95, yields without re-locking when the root is already owned). The record write therefore happens **under the lock that is already held** and must not acquire, release or steal it — and when the interruption unwinds, `archive_writer`'s `except BaseException` releases the flock, so the next `run` re-enters normally.
- The per-stage code is wrapped in `except Exception` handlers that are explicitly written to keep the batch going (`coordinator.py` L457, L470, L530, L546, L559, L602, L673, L704, and the per-row handler at L880: "redacted; batch continues"). An interruption raised as an `Exception` would be **swallowed** and the batch would continue; it must be a `BaseException` subclass, which those handlers cannot catch.
- On the interruption path there is no `RunSummary` — `run_batch` never returns — so the partial counts cannot come from a summary object. They come from the durable truth that already exists: `AttemptLedger(root).load()` (each executed stage persists an attempt, `operational-sidecars.md` #3) filtered to the attempts recorded at or after this run's `started_at`, plus `compute_coverage_summary(store.load())` and `len(entries)` — read-only, no requeue, no manifest mutation.

**Tech Stack:** Python 3.12, pytest, `signal`, the repo's run-ledger module.

**Execution:** mstar-sdd

**Main worktree branch**: `main`

## Global Constraints

- **Every command in this plan names its working directory.** Python, the CLI and pytest run from the
  **package root** `/root/workspace/bilibili-asr-archive/bilibili-asr-archive` (holds `.venv/`,
  `src/`, `tests/`, `README.md`): `cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive && …`.
  `git` and repository-relative paths run from the **repository root**
  `/root/workspace/bilibili-asr-archive`. The form
  `bilibili-asr-archive/.venv/bin/python -m pytest tests/…` is runnable from neither root.
- **Test invocation on a feature worktree (binding)**: the worktree has no `.venv`, and the
  control-root venv's editable install resolves `bili_asr` to the control root. Every run must be
  `cd /root/workspace/bilibili-asr-archive/.worktrees/20260918-operational-record-coverage/bilibili-asr-archive && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest <selector> -v`,
  with `bili_asr.__file__` confirmed to resolve under the worktree first. Captured in
  `{KNOWLEDGE_DIR}/architecture-patterns/worktree-test-invocation.md`.
- Python 3.12; the only interpreter used is the repo venv (`.venv/bin/python` from the package root).
- **`{KNOWLEDGE_DIR}` is not written during start/execute** (`iteration-artifact-boundaries.md`). Task 1 therefore lands the operator-facing text in **product** surfaces (`pilot --help`, `README.md`) and puts the knowledge-destined wording in the iteration package (`{ITERATION_DIR}/iter-2026-09-text-and-ledger-precision/guides/`), for `mstar-compound` to promote at iteration-close. Do not edit `{KNOWLEDGE_DIR}/architecture-patterns/operational-sidecars.md` in this plan.
- Task 2 must not change the archive single-writer boundary: the interruption path **writes one ledger record and exits** — it never acquires, releases, or steals the archive lock, never requeues work, and never mutates the manifest. The record write sits inside the `archive_writer` block that `main()` already holds (`run` is an archive-writer command), so no lock state changes on the interruption path at all.
- **The interruption path is idempotent, and the guarantee is named:** exactly one record, because there is exactly one write site (the single `finally` in `_cmd_run`; the existing L2327-2334 call moves into it rather than being duplicated), and no partial line, because that write is one line appended by the existing `RunLedger.append` under `run-ledger.jsonl.lock` (`persistence.append_jsonl_record`: open-append + write + flush + fsync — a completed write is a whole line; readers already tolerate a corrupt tail, `RunLedger.load` prints "ignoring corrupt line"). "One record" comes from the single write site and the one-shot handler, **not** from the primitive.
- **The signal disposition is one-shot and raises `BaseException`:** the installed handler restores the previous disposition on delivery and then raises a `BaseException` subclass (so the coordinator's per-stage `except Exception` handlers cannot swallow it and the batch cannot continue past the interruption). During the record write the two dispositions are set to ignore, so a second `SIGTERM`/`SIGINT` cannot interrupt the write; a second signal therefore cannot produce a second record or a partial line. No new write mechanism is introduced.
- **What the process presents:** the run body's `finally` writes the record once and the process exits with the conventional interruption code — `128 + signum`, i.e. **143** for `SIGTERM` and **130** for `SIGINT` — returned/raised as `SystemExit`, never as an uncaught exception (a traceback would present exit 1 and put the interruption in the same bucket as a failed run). The record's `exit_code` carries the same value; `run_ledger._validate_record` only requires an `int` (L262-264), so no schema change is needed.
- Existing run-ledger semantics are unchanged for normal exits: `command` / `exit_code` / `work_ids` / `coverage_summary` / `started_at` / `finished_at` keep their meanings; an interrupted run is distinguishable by its exit code (143/130 vs 0/1/2) but is not a new schema version and adds no new field. The normal path's record must be byte-identical to today's for a normal exit.
- A failure to write the interruption record is **reported on stderr**, not silently swallowed: the existing `except Exception: pass` around the L2327-2334 write may not hide the interruption path's only deliverable (the process still exits with the interruption code).
- Verification scope follows `mstar-harness-core` § 定向执行与验证边界: only changed behaviour and direct contracts; no local full-suite runs without explicit permission.
- Never assign real-browser/device/installed-deployment E2E evidence as a task or gate of this plan.

## Engine lifecycle

Who advances this plan row's engine state, and what records each transition:

- **Scoped sequence** — one engine verb per transition; never a hand-edited snapshot: `bind --coordinator` → `prepare` → `bind` → `progress` → `handoff` → `accept` → `integration-start` → Git merge → `integration-accept` → `complete`.
- **Evidence order** — `compound` disposition, PR identity and merge evidence are recorded **after** the row is `Done`; the engine refuses those writes while any plan row is not `Done`. The delivery tail runs on a completed row, never ahead of it.
- **Snapshot declares no integration anchors** → the row cannot reach `Done` today: stop at a submitted/accepted handoff, report the blockage to the coordinator, and never fabricate a terminal state (`Done`, `completed`, PR identity, merge record).

Semantics and failure behavior → `mstar-artifacts/references/plan-workflow-lifecycle-contract.md`; PM step sequence → `mstar-roles/references/project-manager/plan-management.md`.

---

### Task 1: Write the pilot attempt-ledger boundary down (R4)

**Effort (agent-oriented):** XS

**Split point:** Not splittable — one boundary statement in two product surfaces plus the package note.

**Verification mode:** `scoped-check` (non-executable documentation/policy — no test file is created).

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/cli.py` — the `pilot` subparser registration at L102-105. **The boundary text goes in a new `description=` (or `epilog=`) argument, not in the existing `help=` string**: the `help=` string is only rendered in the top-level `bili-asr --help` command list, and `pilot --help` today prints usage + option help with no description at all (measured: `pilot --help | grep -n -- "--scope failed"` → no output, exit 1). Criterion 3's check reads `pilot --help`, so `help=` alone would leave the check failing while looking implemented.
- Modify: `bilibili-asr-archive/README.md` (the section that documents `--scope` / recovery, so an operator reading about `--scope failed` learns which entry points feed it)
- Create: `{ITERATION_DIR}/iter-2026-09-text-and-ledger-precision/guides/pilot-attempt-ledger-boundary.md` (the knowledge-destined text + the evidence for `R4`)
- Out of scope: `{KNOWLEDGE_DIR}/**` (see Global Constraints), `coordinator.py`, `pilot`'s execution logic — this task changes **no behaviour**.

**Interfaces:**
- Consumes: the measured evidence — `BV1RFoxBqEzo:p0` is `archived` in the season manifest and has `stages=[]` in `coordinator/attempts.jsonl`, while all 13 run-archived rows carry `download+asr+archive`; the contract text in `operational-sidecars.md` §3.
- Produces: the operator-facing statement cited by `R4`'s closure — visible in `pilot --help` output and in `README.md`'s recovery paragraph (README.md L1021-1024, the one that today reads "Retryable failures remain selectable by the same command or by `run --scope failed`", beside the exit-code table at L1012-1016) — plus the package text `mstar-compound` promotes at iteration-close. `{KNOWLEDGE_DIR}/**` stays untouched (compass criterion 3 and Non-Goals).

- [x] **Step 1: Read the changed text and its contract target**

Read `operational-sidecars.md` §3 and the `run` / `pilot` / `--scope` documentation already in `README.md`.

- [x] **Step 2: Apply only the assigned text change**

State, in both product surfaces: the stage-attempt ledger is written by `bili-asr run`; work archived through the `pilot` entry point leaves no attempt records and is therefore **not** reachable by `--scope failed`; the per-stage truth for pilot work does not exist, and `pilot` is a bounded probe, not a corpus path. Keep it to the fact and its consequence — no advice beyond where the recovery path does work. Name the recovery surface with the literal token `` `--scope failed` `` in both surfaces, so the Step 3 grep is the acceptance check itself rather than a proxy for it (compass criterion 2). In `cli.py`, that means the subparser's new `description=`/`epilog=`, i.e. the text `pilot --help` actually prints.

- [x] **Step 3: Run the named scoped checks**

```bash
# working directory: the package root /root/workspace/bilibili-asr-archive/bilibili-asr-archive
# (.venv, src/ and tests/ all live here; from the repository root the same venv is
# bilibili-asr-archive/.venv — the `cd` below is what makes either path resolve)
cd /root/workspace/bilibili-asr-archive/bilibili-asr-archive
.venv/bin/python -m bili_asr pilot --help | grep -n -- "--scope failed"
grep -n -- "--scope failed" README.md
.venv/bin/python -m pytest tests/test_cli_help.py -q
```

Baseline before the edit (recorded 2026-09-18, so the check is known to discriminate): the first
command exits 1 with no output — the literal is not in `pilot --help` today; the README grep finds the
pre-existing `run --scope failed` mentions, which are explicitly **not** the check.

Record expected and observed for all three: the help line present; the README recovery paragraph (the one beside the exit-code table, which already carries `run --scope failed`) now carrying the pilot boundary as well — the pre-existing mentions are not the check; and the help/CLI test file green (a help-text edit must not break its assertions). These three are the artifact-side check behind `R4`'s closure (compass criterion 2).

- [x] **Step 4: Record `Verification mode: scoped-check`** with the complete fields from `mstar-sdd/references/file-handoffs.md` § Verification evidence; no fabricated test files or outputs.

- [x] **Step 5: Commit only the assigned files**

### Task 2: Record the run when it is interrupted (R5)

**Effort (agent-oriented):** M

**Split point:** Split by **evidence class**, and the two parts are **order-free, not 2b-depends-on-2a**. Task 2a is the record-building helper plus its unit test; Task 2b is the signal wiring plus the subprocess test. The dependency the earlier draft claimed ("2b depends on 2a's helper signature") does not exist, because the seam's signature is pinned **in this plan** — `_partial_run_state(root, started_at)` returning `(work_ids, records_existing, coverage_summary)` — and Step 1's test code is written against it verbatim. Both parts therefore code against a frozen interface rather than against each other's output: 2a can land and prove the partial-count logic from durable state alone (verified at plan review: Step 1's test executes green against the real `AttemptLedger` with no signal wiring present), and 2b can be written first and merely fail at runtime until 2a's helper exists. Either order is safe; what is *not* optional is that **both** roads converge on the same one-helper/one-`finally` shape, so the two must not be merged from different rounds with different seam names. Each part closes its own file and gate; if only one lands in a round, land 2a first (its test is the cheaper, self-contained evidence), and never present the subprocess test alone as the measurement.

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/cli.py` (`_cmd_run`, L2280-2338: move the existing record write into the single `finally` of the run body, add the one-shot signal disposition above it, and drop the `except Exception: pass` that would swallow the interruption path's write failure)
- Modify (only if the helper needs it): `bilibili-asr-archive/src/bili_asr/run_ledger.py` — `build_run_record` (L171-206) already takes `command` / `started_at` / `exit_code` / `work_ids` / `records_existing` / `coverage_summary`, which is the whole interruption record, so **no second builder is written**; this file changes only if reading the attempts needs a helper.
- Test: `bilibili-asr-archive/tests/test_run_ledger.py` (helper-level: the partial counts and the record shape for an interruption)
- Test: `bilibili-asr-archive/tests/test_coordinator.py` (subprocess-level: spawn the CLI against a fixture archive, send `SIGTERM`, assert the record appears once). The spawn pattern exists at `tests/test_persistence_scale.py:64` (`subprocess.Popen` children with ready/release files); the CLI spawn helper used by the existing CLI cases is `tests/installed_cli.py::run_module` (blocking `subprocess.run`) — the new test needs `Popen` plus a stdout read, and `test_coordinator.py`'s existing `test_cli_run_appends_run_ledger_record` (L695) is in-process, so it is a shape reference only.
- Out of scope: the archive lock implementation, `AttemptLedger` (Task 1's subject, unchanged behaviourally), `recover`, the normal-exit record's field values.

**Interfaces:**
- Consumes: `RunLedger` / `build_run_record` (existing, `run_ledger.py` L171-206 / L335-348); the `run` summary object **only on the normal path**; on the interruption path the durable truth instead — `AttemptLedger(root).load()` filtered to attempts with `started_at >= <this run's started_at>`, `compute_coverage_summary(store.load())`, and `len(entries)`; `SIGTERM` and `KeyboardInterrupt` as the two interruption sources.
- Produces: a run-ledger row for an interrupted run built by the existing builder, carrying the same fields as a normal one plus partial counts, consumed by `R5`'s closure assertions — **exactly one** row, `command: "run"`, `exit_code: 143`, the partial `work_ids`, and a next `run` over the same root that starts cleanly (compass criterion 3). The normal path's record keeps today's values byte for byte.

- [x] **Step 1: Write the failing unit test**

The new logic is the *partial counts*, not the record assembly — `build_run_record` already assembles. Test that logic, at the seam the interruption path uses (attempts recorded at or after `started_at`, the run's own rows):

```python
def test_partial_counts_come_from_the_attempts_this_run_persisted(tmp_path: Path) -> None:
    """A killed run still says what it managed to do."""
    from bili_asr.coordinator import AttemptLedger

    started_at = "2026-09-18T00:00:00Z"
    ledger = AttemptLedger(tmp_path)
    ledger.append({"stage": "download", "work_id": "BVold:p0", "attempt": 1,
                   "outcome": "ok", "error_code": None, "artifact_paths": [],
                   "started_at": "2026-09-17T23:00:00Z",
                   "finished_at": "2026-09-17T23:00:01Z"})          # before this run
    for stage in ("download", "asr"):
        ledger.append({"stage": stage, "work_id": "BV1x:p0", "attempt": 1,
                       "outcome": "ok", "error_code": None, "artifact_paths": [],
                       "started_at": started_at, "finished_at": started_at})

    work_ids, records_existing, coverage = _partial_run_state(tmp_path, started_at)
    record = build_run_record(command="run", started_at=started_at, exit_code=143,
                              work_ids=work_ids, records_existing=records_existing,
                              coverage_summary=coverage)
    assert record["command"] == "run"
    assert record["work_ids"] == ["BV1x:p0"]      # BVold:p0 belongs to an earlier run
    assert record["exit_code"] == 143
```

Name the seam `_partial_run_state(root, started_at)` as above — what is pinned is its inputs (an archive root and this run's `started_at`) and that it reads durable state rather than a summary object that does not exist on this path.

**Pin the third return value too, because the name invites a mistake:** `records_existing` is the **manifest** row count, exactly as the normal path passes it today (`records_existing=len(entries)` at cli.py L2332, where `entries = store.load()`), **not** the attempts-ledger length. A helper that returns `len(AttemptLedger(root).load())` here would silently change a field the plan's Global Constraints require to stay byte-identical on the normal exit path, and would also make the interruption record disagree with every other run record in the ledger. The helper's third value is `compute_coverage_summary(store.load())` and the run body passes `records_existing=len(entries)` itself; the helper therefore takes the archive root and does **not** re-read the manifest for this field. Keep `_partial_run_state` only if it stays a read-only derivation of the *record inputs*; if the implementer finds it clearer, a name that says what it returns (`_interrupted_record_inputs`) is preferred, and either way the unit test above is the contract.

- [x] **Step 2: Run test — expect FAIL**

Run: `cd /root/workspace/bilibili-asr-archive/.worktrees/20260918-operational-record-coverage/bilibili-asr-archive && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_run_ledger.py -k partial -v`

- [x] **Step 3: Minimal implementation**

Extract the record write into one helper and call it from the run body's single `finally`, so both the normal exit and the interruption path go through it exactly once. Install a one-shot `SIGTERM` disposition that raises a `BaseException` subclass (an `Exception` would be swallowed by the coordinator's per-stage handlers — see Architecture), let `SIGINT` keep raising `KeyboardInterrupt` through the same `finally`, set both dispositions to ignore around the record write, and exit with the conventional code (143 `SIGTERM` / 130 `SIGINT`) as a `SystemExit` — never an uncaught traceback. No lock acquisition, no requeue, no manifest mutation, no second write path.

- [x] **Step 4: Write and run the subprocess test**

Spawn `cd /root/workspace/bilibili-asr-archive/.worktrees/20260918-operational-record-coverage/bilibili-asr-archive && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m bili_asr run --scope pending --archive-root <fixture>` over a fixture archive, `SIGTERM` it mid-run, then assert `run-ledger.jsonl` contains exactly one `command: "run"` row with `exit_code: 143` and partial `work_ids`, that the process exited 143, and that no `.lock` file was left in a state the next run cannot re-enter (a subsequent run over the same root starts cleanly).

The interruption must be **deterministic, not a sleep**: the child prints `run: scope=… selected N row(s)` (cli.py L2304) before the batch starts, so the test reads that line from the child's stdout and only then signals — and the fixture must hold enough rows that the batch is provably still in flight at that point (per-row output is printed only after the whole batch returns, so stdout gives no later anchor). A run that finished before the signal landed must fail the assertion loudly (rc 0 ≠ 143): sizing the fixture until that cannot happen is the test's job, not a tolerance to add.

- [x] **Step 5: Run both affected tests — expect PASS**

Run: `cd /root/workspace/bilibili-asr-archive/.worktrees/20260918-operational-record-coverage/bilibili-asr-archive && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_run_ledger.py tests/test_coordinator.py -k "interrupted or partial or ledger" -v`

Also confirm the normal path is untouched: `cd /root/workspace/bilibili-asr-archive/.worktrees/20260918-operational-record-coverage/bilibili-asr-archive && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_coordinator.py -k run_appends_run_ledger -v`

- [x] **Step 6: Commit**

## Plan self-review (PM before locked)

1. **Spec coverage:** `R4` → Task 1 (documentation, scoped-check verification); `R5` → Task 2 (behaviour change, unit + subprocess tests). Both register entries have a closure path.
2. **Placeholder check:** Task 1 names both product files and the package file plus three runnable checks with their working directory and their pre-edit baseline; Task 2 names the exact functions and line ranges, both test files, the existing spawn precedent with its line number, the durable source of the partial counts, the deterministic interruption anchor, and a concrete record contract. No `TBD`/`etc.` remains.
3. **Type consistency:** `RunLedger` / `build_run_record` / `AttemptLedger` / `_cmd_run` / `archive_writer` / `_ARCHIVE_WRITER_COMMANDS` are the real names, and `build_run_record`'s keywords are the real ones (run_ledger.py L171-186); the fixture key names match `tests/test_run_ledger.py`; `exit_code` accepts any `int` (L262-264), so 143/130 need no schema change.
4. **Capacity (task shape / session fit):** Task 1 is XS and closes in one round; Task 2 declares an M band with a two-part split point, and the split keeps the subprocess evidence in its own round rather than trimming it under budget pressure.
5. **Signal-path check:** the handler raises a `BaseException` (an `Exception` is swallowed by the coordinator's per-stage handlers), writes once from the single `finally` while the archive lock the command already holds is still held, ignores further signals for the duration of that write, and exits with 128+signum instead of a traceback — the four ways this path can silently fail to deliver its one record are each named in Global Constraints.

## SDD runtime (ephemeral)

When using `mstar-sdd`, artifacts live under `{SDD_DIR}` (see `mstar-conventions`). Do not duplicate briefs/reports in this file.

## Review Gate Summary

Durable decision surface — sufficient for handoff once `{SDD_DIR}` is gone.

- **Decision:** `Approve` (plan QC tri-review → two targeted re-review waves → QA gate `Approve with residuals`)
- **Review range / Diff basis:** `0fc963d271e8497b473b2b08ff6ea653085a0ebd..6fb114a1957a9696bfb1a5458bd69e8d2e75e25a` — 4 product files, +640/−33 (`README.md`, `src/bili_asr/cli.py`, `tests/test_coordinator.py`, `tests/test_run_ledger.py`); `run_ledger.py` untouched (no schema change).
- **Review bundle:** `{SDD_DIR}/review/` — `qc-consolidated.md`, `qc1.md` / `qc2.md` / `qc3.md`, `branch.diff`, `qc-fix-1.diff`, `qc-fix-2.diff`, `task-1.diff`, `task-2.diff` (ephemeral; gitignored).
- **QC inputs:** `qc1.md` (`qc-specialist`), `qc2.md` (`qc-specialist-2`), `qc3.md` (`qc-specialist-3`). Wave 1: `Request Changes` (3 distinct Warnings, 13 distinct Suggestions) → fix wave 1 (`36a642d`) → targeted re-review (qc3 `Approve`; qc2 kept F-001 open as `partially fixed` because the SIGINT half was untouched) → fix wave 2 (`6fb114a`) → targeted re-review (qc2 `Approve`) + qc3 confirmation → **`Approve`**.
- **Task reviews:**
  - Task 1 — review range `0fc963d..5bcf0bf`, earned **`Task quality: Approved`**, report `task-1-review.md` → `{SDD_DIR}/task-1-review.md` (2 Minor: an imprecise reflow comment, and the writer-naming narrowing that became W2).
  - Task 2 — review range `5bcf0bf..4bc9a56`, earned **`Task quality: Approved`**, report `task-2-review.md` → `{SDD_DIR}/task-2-review.md` (4 Minor, incl. the pre-guard window and the unbounded banner read). **Its test-file anchors are stale (~490 lines off) — the corrected numbers are in `qc-consolidated.md` §Materialized correction; the code anchors resolve.**
- **Blocking result:** **fixed** — all 3 Warnings closed in two fix waves, each verified by a fresh seat dispatch over the delta. No blocking item was deferred; the deferred items are Suggestions/limitations with register rows.
- **Residual findings:** `entries["20260918-operational-record-coverage"]` — `R1` (`schedule`/`campaign` keep the silent swallow and write no interruption record), `R2` (a `run` killed between process entry and the guard writes nothing), `R3` (attempt membership by lexicographic timestamp comparison), `R4` (a second `SIGINT` inside the `except KeyboardInterrupt` clause before the guard writes nothing; carries the C-level-handler accepted-limitation too) — **all `low`, all `decision: defer`, all owner `@project-manager`**, none a blocker-defer.

## QA Gate Summary

- **QA gate:** `mandatory` · **QA mode:** `targeted` · **Verdict:** `Approve with residuals` (9/9 ACs pass, `findings: []`)
- **QA gate reason:** an open `R#` on this `plan_id` **and** a behaviour change (signal handling in `_cmd_run`).
- **Acceptance trace:** `{SDD_DIR}/review/qa.md` (sha256 `3ed45c759e54f93b05501aac47395cc042d8b81c1bc3f7d7962288f8345f9c8a`) — with the coverage/gap disclosure.
- **Evidence reused vs newly run:** the gate **executed** its evidence. Newly run: `pilot --help | grep -- "--scope failed"` (line 10, exit 0); `grep -n -- "--scope failed" README.md` (357/1023/1027); `pytest tests/test_cli_help.py -v` → **43 passed, 0 errors** (with `UV_CACHE_DIR` pointed at a writable cache — with the sandbox's read-only default cache the five `test_installed_*` errors appear; the PM reproduced them on the unmodified control tree, so they are environmental); `pytest tests/test_coordinator.py -k "sigterm or sigint" -v` → **5 passed**; `pytest tests/test_run_ledger.py -k partial -v` → **1 passed**; `pytest tests/test_coordinator.py -k run_appends_run_ledger -v` → **1 passed**; negative control (no signal) → rc 1, so `assert rc == 143` raises (the check is real); write-failure probe → rc **143** with `run: run-ledger write failed (PersistenceError)` on stderr and no traceback. Reused as review input only: the QC bundle and the iteration guide. **No full suite, no build, no network, no archive-host access.**
- **R# closure recommendations (both applied by the PM):** `R5` → **closed `verified`**, scoped to the `run` entry point and pointing at `R1`/`R2`/`R4` as the boundary; `R4` → **closed as an operator-surface close**, its closure note naming the guide as the carrier and handing the knowledge half to `mstar-compound` at iteration-close.

## Done note — how this row reached `Done` (2026-09-18)

Same environment limitation as plan 1, recorded rather than papered over: this host has **no `mstar` CLI and no importable engine package**, so the plan's own scoped engine sequence (`bind`/`prepare`/`progress`/`handoff`/`accept`/`integration-*`/`complete`) could not run. The row's `Done` was written through the CLI-less legacy route with the workflow snapshot, this plan's compass row and this file as carriers.

- **Executed:** per-task L2 reviews (both `Approved`), plan QC tri-review ⇒ two fix waves ⇒ targeted re-reviews (`Approve`), and the mandatory QA gate (`Approve with residuals`, 9/9 ACs, executed evidence).
- **Deliberately NOT claimed:** no PR identity, no merge to the target branch and no per-row integration *anchor field* is fabricated for this row. `Done` here is the plan-row state (execute + review/acceptance complete), not a delivery claim — the iteration's tail (`iteration-close` → PR delivery → verify merge) owns delivery, and the integration-merge reconciliation recorded in the compass §Delivery Branch Policy still has to happen at close.
- **Integration (recorded after the fact, 2026-09-18):** the plan's branch was merged into `iteration/iter-2026-09-text-and-ledger-precision` as `34249dc` (`merge(20260918-operational-record-coverage): plan 2 integration`), and the merged tree is **byte-identical to the reviewed branch tip `6fb114a`** (`git diff --stat 6fb114a HEAD` empty). That is a real, verifiable fact about this row's integration; it is not a PR identity, and it is not a merge to `main`, which the iteration's tail still owns.
- **Carried to the coordinator:** the same CLI-less limitation applies to the iteration's `phase-3-close` and everything after it.
