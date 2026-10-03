---
plan_id: asr-run-id-uniqueness
project: _default
status: draft
created_at: 2026-10-03
execution_mode: inline
plan_parallelism: serial
---
# Plan asr-run-id-uniqueness — Make the ASR run id unique so a same-second collision cannot silence every write-back

**Main worktree branch**: `dev`（control root 驻留分支；本 plan 不切换。记录于 2026-10-03，Phase 1 lock 轮）

## Status
- **Priority**: P1
- **Effort**: S (upper edge — the D8 stderr observable is part of this same round: id + narrowed
  `except` + refusal-visibility in one module, one focused session)
- **Risk**: LOW
- **Confidence**: HIGH
- **Fingerprint**: audit-2026-10-02r2/03-ensure-asr-run-pk-collision
- **Depends on**: none
- **Category**: bug
- **Evidence**: `bilibili-asr-archive/src/bili_asr/services/queue_source.py:140-157` — `run_id = f"{command}-{int(_time.time())}"` then `start_acquisition_run` inside `try/except Exception` → `asr_run_id = None`
- **Planned at**: commit `1e756df`, 2026-10-02
- **Captured issue**: `I-000166`

## Problem

`QueueSource.ensure_asr_run` mints this invocation's run id from the command name and the current
wall-clock **second**:

```python
now = int(_time.time())
run_id = f"{command}-{now}"
```

`acquisition_runs.run_id` is a **`TEXT PRIMARY KEY`**, and `start_acquisition_run` is documented to
raise `sqlite3.IntegrityError` on a duplicate. That raise is caught by a deliberately broad
`except Exception:` which sets `self.asr_run_id = None`.

Every transcript write-back is keyed on that id — `coordinator.py:750` and `:782`
(`_record_subtitle_transcript` / `_record_asr_transcript`), `cli/asr.py:287-299`,
`cli/pilot.py:592-611` — and each of those returns early when the id is `None`. So a collision does
not fail loudly; it **silently disables the whole invocation's write-backs**, which is exactly the
R14 / `v_missing_transcript` gap (`I-000067`) that the write-back was landed to close, re-entered at
one-second granularity. The operator sees a successful archive.

### The collision is reachable in-process, not only across invocations

`RunCoordinator._close_writeback_source` (`coordinator.py:702-706`) sets `self._writeback_source =
None` at **every batch boundary** (called from the `finally` at `:1204`). The next batch re-opens the
source, so `asr_run_id` is `None` again and `ensure_asr_run` re-mints the id from the same wall-clock
second whenever a batch boundary falls inside one second — a normal shape for small batches,
fast-failing rows, or a bounded `--limit`.

Cross-process shapes hit the same path: two shells, a scripted retry loop, or `pilot` following `run`
within the same second.

**目标与非目标（一行）**：目标是「同一 wall-clock 秒内的两次同 command 调用各自拿到可用的 run id，
其 transcript 写回不被静默吞掉」——成功判据是 `acquisition_runs` 出现两行、每个 id 各自写得出
`transcripts` 行；非目标是**不改** `acquisition_runs.run_id` 的 `TEXT PRIMARY KEY`、不改 schema、
也不改行级 write-back 的静默 best-effort 契约。

**操作者可见性（D8，product-manager 裁定）**：run 被 store 拒绝时**不得静默**。该 `QueueSource`
实例必须向 stderr 打印**至多一行**（按实例限一次），指名 command、拒绝原因（异常类）与该 scope 的
transcript 写回被跳过。按**实例**而非按行或按次——拒绝发生在任何行被记录之前，被跳过的是整个
scope（指名一行会低估爆炸半径）；而 store 持续故障时每次调用都会重试并再次被拒，按次打印会退化成
每行一行噪声，按实例只留首条。fd 2 关闭（`sys.stderr is None`）时不打印、不回退 stdout、不抛错
（`coordinator._print_model_constructions` 已是本仓同一形态的先例）。行级 write-back 失败保持既有
静默契约——那一条已由行级证据（`archive: ok` / manifest 行）承载，run 级的 `asr_run_id = None`
没有任何行级证据可承载它。理由：stdout 仍把每一行报成 `archived`，运营者会读成一次干净的成功，
而 `v_missing_transcript` 只在另一个命令（`status`）里可见，不是 run-scoped 观测量。

## Current state (excerpt — verify against live code before editing)

`bilibili-asr-archive/src/bili_asr/services/queue_source.py:136-157`:

```python
        if self.asr_run_id is not None:
            return self.asr_run_id
        try:
            now = int(_time.time())
            run_id = f"{command}-{now}"
            TranscriptRepository(self.connection).start_acquisition_run(
                AcquisitionRunRecord(
                    run_id=run_id,
                    kind="asr",
                    selector_kind="pending",
                    selector_target=None,
                    requested_limit=None,
                    credential_present=False,
                    started_at=now,
                )
            )
            self.asr_run_id = run_id
        except Exception:
            self.asr_run_id = None
        return self.asr_run_id
```

The schema fact — `bilibili-asr-archive/src/bili_asr/storage/schema-transcripts.sql:50-51`:

```sql
CREATE TABLE IF NOT EXISTS acquisition_runs (
    run_id TEXT PRIMARY KEY,
```

The repository contract — `bilibili-asr-archive/src/bili_asr/storage/database.py:931-935`:

```python
    def start_acquisition_run(self, run: AcquisitionRunRecord) -> None:
        """...
        ``run_id`` is the primary key and is never reused: a duplicate raises
        ``sqlite3.IntegrityError``.  The run is committed on its own so a
```

## Invariant restored (target state, not the line moved)

**A run id is unique per invocation, so a store refusal means a real refusal.** The id generator must
be able to mint a fresh key on every call — including two calls inside one wall-clock second — because
the callers' contract (`asr_run_id is None` ⇒ this run's write-backs are skipped) treats `None` as
"the store refused". Uniqueness is bought in the generator; the primary key, its refusal behaviour and
the best-effort `None` all stay exactly as they are. D8 adds the missing observable only for the case
the contract still cannot express: a genuine refusal.

## Contracts to preserve (name these in the task report)

- **`acquisition_runs.run_id` is `TEXT PRIMARY KEY` and is never reused** —
  `schema-transcripts.sql:50-51`, `database.py:931-935` (`start_acquisition_run` documents the
  `sqlite3.IntegrityError`). This plan changes the **generation**, never the column, the constraint or
  the schema. The compass Non-Goal makes that a hard boundary of the iteration, not a preference.
- **The wide `except` is narrowed, not deleted.** The refusal path must still leave `asr_run_id` `None`
  and the call must still return normally — the retry-with-suffix candidate (option 2) must raise
  nothing to the caller.
- **The callers' guards stay.** `coordinator.py:750-751` / `:782-783`, `cli/asr.py:287-292`,
  `cli/pilot.py:592-603` all check `is None` and skip; that skip behaviour is the contract D8
  decorates with a stderr line. Do not move the guard.
- **The `run_id` namespace is shared with two other producers.** `subtitle_ingest.py:340` and
  `metadata_ingest.py:294` also write `acquisition_runs` rows, minting `uuid.uuid4().hex` (and
  `run_ledger.generate_run_id` uses `run-{ts}-{rand}`). No shape collision is possible with a
  `{command}-{...}` id, but the uniqueness argument must be made **within** the ASR generator, not by
  appealing to the store's refusal — the store refusing is the correct behaviour this plan keeps.
- **D8's stderr line is per-instance, fd-2-only, and not a log.** Exactly one line per `QueueSource`
  instance, nothing on stdout, silent no-op when fd 2 is closed.
  `coordinator._print_model_constructions` is the in-repo precedent for the shape.

## Conventions to follow

- The module's own docstring says the run is best-effort and a store that refuses the run must leave
  `asr_run_id` `None` — that contract stays. What changes is the id, so a **legitimate** retry no
  longer looks like a refusal.
- Match the repo's error-handling pattern in `queue_source.py`: bounded `except` clauses naming the
  concrete classes, not a blanket `Exception` (the neighbouring `record_local_transcript` /
  `record_caption_transcript` both name `(_sqlite3.Error, OSError, ValueError, TypeError, KeyError)`).
- Ids are opaque to every consumer but the store. The one consumer that touches the string at all is
  a **sort key**, not a parser: `cli/status_cmd.py:463` / `:477-480` orders same-second runs by
  `run_id` descending. Both candidate ids keep that deterministic and opaque — but the chosen id must
  remain **newline-free, ASCII-safe and unique within the second**, because ordering (not parsing) is
  what that reader depends on.
- Match `run_ledger.generate_run_id` (`run_ledger.py:79-82`, `run-{ts}-{rand}` via
  `secrets.token_hex(4)`) as the repo's existing precedent for an opaque run id if a random suffix is
  preferred over a monotonic one — do not invent a third style without saying why.

## Tasks

### Task 1 — Make the id unique (Effort: S)

**Files**
- Modify: `bilibili-asr-archive/src/bili_asr/services/queue_source.py` (`ensure_asr_run`, ~`:121-158`)

**Change (pick one, prefer the first):**

1. **Monotonic suffix** — `run_id = f"{command}-{time.time_ns()}"` (keeps the readable
   `command-timestamp` shape, removes the one-second window), or
2. **Suffix bump on collision** — attempt `f"{command}-{now}"`, and on `sqlite3.IntegrityError`
   retry with a disambiguating suffix (e.g. `-{n}` for n in 2..N) before giving up.

Whichever is chosen, narrow the `except Exception:` to the classes the store actually raises
(`sqlite3.Error`, `OSError`, `ValueError`), so a programming error no longer masquerades as
"store refused the run". On a genuine refusal, implement the D8 observable in the same edit: exactly
one stderr line **per `QueueSource` instance** naming the command, the exception class and the fact
that this scope's transcript write-backs are skipped; fd 2 closed ⇒ silent no-op (see
§操作者可见性 and the Done criteria). Keep `started_at=now` (a Unix second is the schema's
granularity).

**Interfaces (verbatim, unchanged):**

```python
def ensure_asr_run(self, command: str) -> str | None: ...
```

**In scope**: `bilibili-asr-archive/src/bili_asr/services/queue_source.py`,
`bilibili-asr-archive/tests/test_storage_queue_writes.py` (or the file already covering
`ensure_asr_run`; confirm before editing).

**Out of scope**: `start_acquisition_run` and the schema (`run_id` stays `TEXT PRIMARY KEY`), the
callers' guards, `finish_acquisition_run` (the separate "runs never finished" lead — not this plan).

### Task 2 — Pin the collision (Effort: S, same round)

Add a test that proves the defect class is closed:

1. Open two sources over the same seeded store (or call `ensure_asr_run` twice on two instances)
   **inside the same wall-clock second** — freeze/inject the clock if the module allows, otherwise
   assert the two ids differ rather than relying on timing.
2. Assert both calls return a non-`None` id and that the two ids differ.
3. Assert a `record_local_transcript` through each run id lands its `transcripts` row (the
   end-to-end half matters here — the id being non-`None` is not the observable the operator cares
   about).

Record the red/green pair: pre-fix the second call returns `None` (or both calls return the same id
and the second `start_acquisition_run` raises).

## STOP conditions

- If `ensure_asr_run` no longer matches the excerpt (a merge changed the id scheme), STOP and report.
- If some reader **does** parse the run-id format (grep `run_id` across `src/` and the tests before
  editing — the audit found none), STOP: the id shape would then be a contract, not an implementation
  detail.
- If the clock cannot be controlled in the test harness and the assertion would be timing-dependent,
  STOP and prefer the deterministic assertion (two ids differ) over a flaky one — never add a
  `sleep`.
- **Contract-breaking (irreversible) — STOP, do not implement around it:**
  - If the fix requires a **sequence table, a counter table, a new column, a schema edit, or a
    migration** to mint unique ids, **STOP and report to PM**. The compass Non-Goal forbids schema
    change and migration outright (`archive.db` is rebuildable-by-policy, no in-place migration);
    uniqueness must come from the generator alone. This is the single most likely way to "solve" the
    symptom by leaving the iteration's boundary.
  - If the fix changes `acquisition_runs.run_id`'s `TEXT PRIMARY KEY`, or widens/narrows any column,
    STOP for the same reason — the collision is a *generation* defect, and the store's refusal of a
    duplicate is correct behaviour to keep.
  - If a consumer is found that **parses** the id (split on `-`, `int(...)`, `startswith("run-")`
    outside `status_cmd`'s sort), STOP and report: the id shape would then be a contract, and the
    chosen candidate must be re-decided against that consumer rather than around it.
  - If making the refusal visible requires touching a **line-level** write-back failure path (e.g.
    `coordinator._record_subtitle_transcript` / `_record_asr_transcript` or
    `queue_source.record_local_transcript` / `record_caption_transcript`), STOP — D8 explicitly keeps
    line-level failures silent; only the run-level refusal is in scope.

## Drift check

```
git diff --stat 1e756df..HEAD -- bilibili-asr-archive/src/bili_asr/services/queue_source.py bilibili-asr-archive/src/bili_asr/storage/schema-transcripts.sql
git log --oneline 1e756df..HEAD -- bilibili-asr-archive/src/bili_asr/services/queue_source.py
grep -rn "run_id" bilibili-asr-archive/src/ --include=*.py
```

Re-read before editing when any of these is non-empty:

1. `queue_source.py` changed — re-read `ensure_asr_run` against the excerpt; the id scheme may have
   already moved.
2. `schema-transcripts.sql` changed — the `TEXT PRIMARY KEY` fact this plan rests on must be re-read;
   if the column moved, the whole repair boundary moves with it (STOP per the STOP conditions).
3. The `run_id` grep shows a **new** consumer that parses rather than sorts the id — the plan's
   "ids are opaque" premise is then false; reconcile the candidate choice before editing.
4. The `run_id` grep no longer shows `status_cmd.py:463` / `:477-480` — the only ordering consumer this
   plan names is gone; re-derive whether anything else depends on the id's *shape*.

**Cross-plan note:** this plan's only shared file with the iteration's other three is none — it owns
`queue_source.py` (and possibly its test file) alone. `coordinator.py:750` / `:782` are **read-only
references** to the caller contract; if the repair appears to need a caller change, STOP rather than
editing a file that `caption-writeback-guard` is concurrently changing.

## Done criteria

- [ ] `ensure_asr_run` cannot collide within one second (monotonic id or retry-with-suffix)
- [ ] The `except` names concrete classes rather than bare `Exception`
- [ ] **Observable** — a run refused by the store prints **at most one line per source instance** to
      **stderr** naming the command, the refusal's exception class, and that the scope's transcript
      write-backs are skipped; a subsequent refusal on the same instance prints **no** second line;
      nothing is written to stdout; with fd 2 closed the call still returns `None` without raising
      (capsys/capfd assertion, no sleeps)
- [ ] New test fails before and passes after; record the red/green pair and the assertion used
- [ ] `cd bilibili-asr-archive && PYTHONPATH=$PWD/src python -m pytest -q tests/test_storage_queue_writes.py` passes; record the command and result
- [ ] `git diff --check -- bilibili-asr-archive/src/bili_asr/services/queue_source.py` exits 0
- [ ] No files outside the in-scope list are modified (`git status --short`)

## Verification notes

Run from the package root with the absolute source path pinned. Do not run the full suite. The
write-back's own end-to-end witness is **audit plan 015** (not in this iteration) — land this one first and let 015 assert the store-route row; do not duplicate the assertion here.

## QA Gate Summary

**`accepted with open issues` — 2026-10-03** (`qa-engineer`, `QA gate: mandatory` / `QA mode: acceptance-only`;
report `{SDD_DIR}/asr-run-id-uniqueness/qa-acceptance.md`, range `1dc720b..a23b44c`).

All 7 Done criteria hold at the reviewed head, each mapped to evidence the gate re-read, re-hashed or
re-derived (source blob identity pinned by sha256; worktree clean before and after). The gate re-ran the plan's
own affected unit file and independently re-derived the two acceptance questions: the D8 observable holds in its
final (twice-widened) form, and the collision half is evidenced by two same-second calls returning distinct
non-`None` ids **with** a transcript row landing through each — clock injected, no `sleep`. The gate confirms no
Done criterion overclaims the narrowed `except` boundary.
Open items: the plan's own issue (`I-000166`, high) — its acceptance is now evidenced and its **closure is
PM-owned**; `I-000197` and `I-000198` correctly out of this plan's criteria and correctly dispositioned;
`I-000192` named as the owner of the boundary repair.

### Plan QC (tri-review, N=3, plus a revalidation round)

Round 1 `Approve` / `Approve` / `Request Changes`; round 2 (targeted revalidation of the fix delta)
**`Approve` / `Approve` / `Approve`**, each seat re-probing the fix independently. Three seats converged on one
defect — the `except OSError` guard in the diagnostic was narrower than the failure set of a present-but-unusable
`stderr` (`ValueError` for a closed/detached wrapper, `TypeError` for a binary stream), so the diagnostic could
raise out of `ensure_asr_run`'s documented no-raise contract. **Fixed** in `a23b44c` (guard widened to
`(OSError, ValueError, TypeError)`, four-shape test), not deferred, because it was a regression this task
introduced. All remaining findings are dispositioned into named issues or recorded in the plan's Post-QC ruling.
Consolidated in `{SDD_DIR}/asr-run-id-uniqueness/review/qc-consolidated.md` (seat reports `qc1.md`–`qc3.md`, all
passing `mstar qc validate-report`).

### A new observable this iteration introduced, captured rather than waived

The QA gate isolated an adjacent consequence no seat or fix round addressed: with fd 2 dying **mid-flight**, the
swallowed failed write still dirties the interpreter's `stderr` buffer, whose **shutdown flush** raises — so the
process **exits 120** where the base exited 0 (measured at `d67f84c` and `a23b44c`, absent at `1dc720b`; control
`os.close(2)` alone → 0, `os._exit(0)` after the call → 0). Reachability is nil in-product (no `src/` code closes
or replaces fd 2) and the PM ruled it **not a criterion failure** — but an exit-code change is observable to any
caller checking `$?`, and the same print-to-stderr shape exists at two precedent sites (`coordinator.py:1260`,
`cli/asr.py:102`) that were never probed, so it is captured as **`I-000199`** rather than waived.

### L2 task review

`Approved` with one Minor (R1) — the diagnostic could raise when stderr dies after startup; fixed in `0d7c84a`
and re-verified. `{SDD_DIR}/asr-run-id-uniqueness/task-1-review.md`.

## Engine lifecycle ownership

Source-only repair, no lifecycle claim. Advanced by PM through the normal per-plan flow; no delivery
tail promised.

**Post-QC PM ruling (2026-10-03).** The plan-QC tri-review returned `Approve` / `Approve` /
`Request Changes`. Two warnings were raised and both are decided here rather than left implicit:

1. **The narrowed `except` lets a connection-contract `TypeError` escape the write-back** (qc3 F-001;
   qc1 judged it unreachable on the live path because `QueueSource.__init__` already validates the
   connection, so the trigger is a prerequisite violation — a contract lost *after* construction).
   Ruling: **accepted as a known, bounded consequence of narrowing the tuple, recorded as **`I-000198`**
   (filed separately from `I-000192`, which is the caption call site's missing swallow boundary; this one is the narrowed tuple's consequence)** — a genuinely unreachable-in-product shape whose fix belongs at the call boundary
   (that issue's surface), not in this plan. The narrowing itself is the plan's own instruction and the
   escape requires an object that violates its constructor's contract.
2. **The refusal diagnostic is emitted on `campaign`**, whose stdout is a single machine-read JSON
   document (qc3 F-002). Ruling: **not a defect for this plan.** The line goes to stderr only; stdout
   stays clean, which is the property the JSON consumer depends on, and the new test asserts
   `captured.out == ""`. A wrapper that *merges* stderr into stdout is a wrapper bug; the precedent
   `coordinator._print_model_constructions` reasons about stdout for this same command. Recorded here so
   the decision is explicit rather than unaddressed.

A third finding — the per-instance latch being per-batch in practice (qc3 F-003 / qc1 S-3) — is latent,
not live: all three `run_batch` callers are single-batch, so per-instance equals per-invocation today,
and qc1's census refines the trigger accordingly. Captured as `I-000197`.

4. **qc3 F-004** (the `time_ns` rationale overstates the mechanism): accepted as a wording nit; the code is correct and the docstring's claim is not load-bearing, so no edit is made in this round.

5. **qc1 S-1** (a transient refusal is announced with persistent-refusal wording) and **qc2 F-001** (the `except OSError` guard is narrower than the failure set of a present-but-unusable `stderr`): S-1 is accepted as wording — the latch is faithful to the per-instance Done criterion and the transient case self-heals; **F-001 is fixed** in the same round (the guard widens to `(OSError, ValueError, TypeError)` plus a closed/detached test), because two seats proved `ValueError`/`TypeError` escape the method's own absolute no-raise claim.

