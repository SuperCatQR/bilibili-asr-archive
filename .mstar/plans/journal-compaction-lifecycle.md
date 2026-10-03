---
plan_id: journal-compaction-lifecycle
project: _default
status: draft
created_at: 2026-10-03
execution_mode: inline
plan_parallelism: serial
---
# Plan journal-compaction-lifecycle — Make journal compaction reachable and order `save()` like its siblings

**Main worktree branch**: `main`（control root 驻留分支；本 plan 不切换。Phase 1 lock 轮记录为 `dev`，2026-10-03 于派发前**重记**为 `main`：一个 peer 会话在迭代进行中把 control root 从 `dev` 移到了 `main`（合并 `01d762a`，仅 `docs/`，`git diff --stat main..dev -- bilibili-asr-archive/src bilibili-asr-archive/tests` 为空即无产品分叉），故 `dev` 的驻留记录已失效。重记而非改用 `--main-branch dev` 传参：后者等于让门禁检查一个不存在的观测。）

## Status
- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Confidence**: HIGH
- **Fingerprint**: audit-2026-10-02r2/04-manifest-journal-compaction
- **Depends on**: plans/journal-replay-integrity.md
- **Category**: bug
- **Evidence**: `bilibili-asr-archive/src/bili_asr/manifest.py:295-315` — the compaction gate; `:380-392` — `save()`'s unlink-before-write order; thresholds at `:51-54`
- **Planned at**: commit `1e756df`, 2026-10-02
- **Captured issues**: `I-000167` (compaction), `I-000170` (`save()` ordering)
- **Ruling**: compass **D9** — trigger form = file-based bytes; Task 3 (maintenance subcommand) ruled
  **out**. See `## Approach` below.

## Problem

Two defects in the manifest journal ledger, one structural and one an ordering window.

### 1. The journal never compacts on any in-repo path

`_maybe_compact_locked` requires **both** clauses to hold:

```python
        if not (
            self._appends_since_compact >= _JOURNAL_COMPACT_THRESHOLD
            and journal_bytes >= max(1, _JOURNAL_WRAP_BYTES_FACTOR * snapshot_bytes)
        ):
            return
```

`_JOURNAL_COMPACT_THRESHOLD = 256` counts appends **by this process instance**
(`self._appends_since_compact += 1` per append, reset to `0` at construction). Normal invocation
shapes — `run --limit N`, `asr`, `pilot`, or any bounded batch — append far fewer than 256 rows in
one process, so the counter resets before the byte clause can even be evaluated. And a whole-tree
grep shows **no `src/` caller invokes `save()` or `compact()`** (only tests do).

Net effect: the journal is never folded. Every fresh process and every projection pays
`O(snapshot bytes + journal bytes)` of parse-and-validate, and the cost grows with the number of
transitions ever recorded — not with corpus size. The deterministic snapshot, whose whole purpose is
to bound the read, is never refreshed.

Readers paying the full replay:
- `ManifestStore.load()` → `_replay_latest()` (`:222-266`);
- `sidecar_projection.replay_journal_records` (`sidecar_projection.py:193-218`) → used by
  `project_manifest_records`, i.e. `integrity`, `coverage_report`, `cli/status_cmd`;
- `SearchIndex.is_stale` (`search_index.py:527-533`) — on **every `search`** (audit plan 019's sibling finding `I-000172`).

**目标与非目标（一行）**：目标是「日志有可达的收口路径，且 crash 窗口与两个兄弟方法一致」——
journal 经正常 append 路径可被折叠（journal 缩小、snapshot 持有全部行），`save()` 先写 snapshot 后
unlink journal；非目标是**不改** journal 磁盘格式、不削弱 `_append_record` 的 durability
（write + fsync + 目录 fsync）、不在本 plan 里重复 `journal-replay-integrity` 的 split 规则、
也不动 `search_index.py`。

**代价限定**：用户可见的收益是「读成本随语料规模而非转移次数增长」——一个账本读得越久越贵的归档
最终会让 `load()`/`status`/`search` 慢到不可用；本 plan 只承诺折叠路径可达与 crash 窗口归位，
不承诺任何具体性能数字（实测属审计 plan 019，本迭代 Non-Goal）。

### 2. `save()` unlinks the journal before rewriting the snapshot

`save()` is the only one of the three rewrite paths with the inverted order:

| method | order |
|---|---|
| `save()` `:380-392` | `_replay_latest()` → **`_remove_journal()`** → `if not current: return` → `_replace_snapshot(current)` |
| `compact()` `:396-407` | `_replace_snapshot(current)` → `_remove_journal()` |
| `migrate_legacy_rows()` `:597-603` | `_replace_snapshot(next_entries)` → `_remove_journal()` |

A crash, `SIGKILL`, or a raised `OSError` (e.g. ENOSPC on the temp write) between the unlink and the
`os.replace` loses every row that lived only in the journal — they were in `current`, an in-memory
dict that dies with the process — while the stale snapshot stays in place. Combined with defect 1
(the journal is where new rows actually live), that window is wider than the code implies.

**Interaction with `I-000138`**: that registered row covers `compact()` deleting the journal when the
snapshot is absent. The fix here must **preserve** the invariant it established: never unlink a
journal whose rows were not successfully folded into a snapshot.

## Approach (architect ruling — Q1 settled)

**This plan restores an invariant, it does not move lines.** The invariant is: *the deterministic
snapshot's whole purpose is to bound the read cost, so the fold path must be reachable from the
append path alone, and no rewrite path may discard a row it has not already durably published.*
Defect 1 breaks "reachable"; defect 2 breaks "durably published first". The file's stored bytes stay
the SSOT after the change — only *when* the fold happens and *in which order* the two artifacts move.

**Q1 ruling — the trigger form is the long-term contract; Task 3 is OUT (YAGNI).** Recorded as
compass `## Decisions` **D9**. Evidence from the code, not from intent:

| Call site | What it shows |
|---|---|
| `manifest.py:270-271` (`_append_record` opens the journal `O_WRONLY` + `O_APPEND` + `O_CREAT`) | the journal's **only** writer in all of `src/` (grep `O_APPEND` / `JOURNAL_NAME`: writer at `manifest.py:48,271`; the other hits are readers — `sidecar_projection.py:204`, `search_index.py:460`) |
| `manifest.py:454` → `manifest.py:462` (`upsert` calls `_append_record` then, immediately, `_maybe_compact_locked(self._entries, journal_bytes=self._journal_bytes)`) | `_append_record` has exactly **one** caller and it is always followed by the trigger check — no append can bypass it |
| `manifest.py:291-292` (`_appends_since_compact += 1` / `_journal_bytes += len(payload)`) | the per-instance counter is the thing that makes the reachable path unreachable; the on-disk byte count is what a file-based trigger must read |
| `manifest.py:252` (`journal_bytes = len(raw)` inside `_replay_latest`) | the on-disk journal size is already computed and already returned — **no new plumbing** is needed for a file-based trigger |
| whole-`src/` grep for `.save()` / `.compact()` | **zero callers**: the maintenance surface Task 3 proposes would be the *first* observable way to run a method nothing currently runs |

So a bytes-only relative trigger folds a long-lived archive from the append path alone: every append
that grows the journal is followed by the check, and when appends stop the residue is bounded by the
threshold (≤ `2 × snapshot_bytes` — or, with the floor, ≤ `max(floor, 2 × snapshot_bytes)`), so read
cost stays bounded without an operator ever running a command.

**Amendment (2026-10-03, after the plan-QC tri-review — the sentence above is false under a strand).**
The residue bound holds only while a fold can actually complete. Once a torn fragment strands complete
rows behind itself, `_remove_journal` refuses to unlink (by design), so no fold completes and the
journal grows **unbounded** instead: measured after 40 post-fragment appends, journal 4120 B against a
43 B pinned snapshot, with a fresh reader seeing **1 of 41 rows**. Read cost therefore grows with the
journal, not with the threshold, in that state. This is recorded rather than fixed here: the repair
(or the report) a stranded tail needs is its own surface, filed with the measurement as **`I-000205`**
(high). The plan's Done criteria are unaffected — they are about *deletion*, and nothing is deleted —
but no reader of this section should carry away the residue bound as an unqualified property. **Ablation:** delete Task 3's subcommand
and no confirmed requirement fails — there is no requirement (issue, acceptance criterion or operator
prompt) naming an on-demand fold, and none can be observed today because no call site exists.

**Reopen condition** (write it into the plan, not into a comment): reopen Task 3 only if a future
journal-append path bypasses `upsert`, **or** audit plan 019's measured run shows the residue
persistently above the floor on a real root. Until then the trigger *is* the contract.

**Ablation lines for the components this plan keeps:** the floor (`_JOURNAL_MIN_COMPACT_BYTES`) — removal
would lose "a small snapshot does not rewrite per row"; kept for the measured live root. The journal
format — removal would lose cross-process replay for readers that are already correct
(`sidecar_projection.replay_journal_records`, `search_index`); kept unchanged.

## Current state (excerpts — verify against live code before editing)

`bilibili-asr-archive/src/bili_asr/manifest.py:51-54`:

```python
#: Rewrite the snapshot once an appending store holds this many journal rows.
_JOURNAL_COMPACT_THRESHOLD = 256

#: Wrap the journal when its byte size exceeds the snapshot's by this factor.
_JOURNAL_WRAP_BYTES_FACTOR = 2
```

`bilibili-asr-archive/src/bili_asr/manifest.py:295-315`:

```python
    def _maybe_compact_locked(
        self, entries: dict[str, dict[str, Any]], *, journal_bytes: int
    ) -> None:
        """Fold the journal into the snapshot once append history is dominant.
        ...
        """
        snapshot_bytes = os.path.getsize(self.path) if os.path.exists(self.path) else 0
        if not (
            self._appends_since_compact >= _JOURNAL_COMPACT_THRESHOLD
            and journal_bytes >= max(1, _JOURNAL_WRAP_BYTES_FACTOR * snapshot_bytes)
        ):
            return
        self._replace_snapshot(entries)
        self._remove_journal()
        self._appends_since_compact = 0
        self._journal_bytes = 0
```

`bilibili-asr-archive/src/bili_asr/manifest.py:380-393`:

```python
        requested = dict(entries) if entries is not None else None
        with self._manifest_lock(create=True):
            current, _journal_bytes = self._replay_latest()
            if requested is not None:
                current.update(requested)
            self._remove_journal()
            self._appends_since_compact = 0
            self._journal_bytes = 0
            self._journal_signature = self._journal_stat_signature()
            if not current:
                self._entries = {}
                self._loaded = True
                return
            self._replace_snapshot(current)
```

Note the `journal_bytes` passed into `_maybe_compact_locked` is `self._journal_bytes`, which counts
only what **this instance** appended — a second process appending to the same journal never advances
it. That is a second reason the trigger is per-instance rather than per-file.

**Line-citation re-anchor (2026-10-03 — superseded twice; re-anchor by method name).** This plan was
written against `manifest.py` at `1e756df`. Every citation below that falls after `:252` has since drifted, and
**by a different amount per method**, so no single offset is correct: measured at the final HEAD `06845c7` the
offsets are `_read_latest` +2, `_append_record` +9, `_maybe_compact_locked` +8, `save` +12, `compact` +16, and
the Task 4 anchors `:521/:528/:536-543/:596-598` are now `:542/:550/:536-549/:606` (QC seat 1's measurement,
recorded rather than re-derived). Two earlier notes here claimed a uniform +7 after `fbe2087`; that was true only
of the state before this plan's own three commits landed. **Treat every `:NNN` as historical and re-anchor by
method name** — which is what this note asked for from the start, and now the only thing it can honestly ask.

## Contracts to preserve (name these in the task report)

- **Journal append format + durability.** `_append_record` (`manifest.py:266-292`) is
  `write + fsync(fd) + fsync(directory_fd)` with the record serialised by `_json_line`
  (`ensure_ascii=False`). Do not weaken any of the three; a fold must not be reached by relaxing this.
  The follow-up `os.fstat` (`:277-285`) that records `own_signature` is **part of the contract** —
  removing it makes an instance mistake its own append for a foreign one and re-replay per upsert.
- **The snapshot-absent invariant (`I-000138`).** Never unlink a journal whose rows were not
  successfully folded into a snapshot. This plan must hold it in `save()`'s form as well as
  `compact()`'s (`manifest.py:396-407`) form.
- **Do NOT copy `migrate_legacy_rows()`'s ordering as a model (amended 2026-10-03).** Its
  `_replace_snapshot` → `_remove_journal` order (`:597-598`) is the correct *sequence*, but during this
  iteration's plan-QC it was found to unlink a journal whose rows the snapshot does **not** contain: its
  rewrite base is `dict(current)` from the snapshot-only `_read_latest()` (`:521`, `:528`), and journaled
  rows are overlaid only for absent keys (`:541-543`) or bare-legacy snapshot rows (`:536-540`), so a
  journaled *supersede* of an existing page-qualified row is discarded and then deleted — captured as
  **`I-000195`** (high, with a public-API repro). Read that issue before treating any sibling as the
  reference shape; here "match the siblings" means match `compact()`'s publish-before-discard order, and
  additionally satisfy `save()`'s own base — which, unlike `migrate_legacy_rows`, already replays into
  `current`. If closing this plan's Task 2 tempts you to also "fix" `migrate_legacy_rows`, **STOP** — that
  is `I-000195`'s surface, not this plan's.
- **`_replay_latest`'s split rule.** The journal replay is split on `"\n"` — `manifest.py:253` is the
  pre-fix `splitlines()` line and is owned by `plans/journal-replay-integrity.md`. **Do not touch it
  here**: this plan runs second (see the file's `Depends on`), so by the time Task 1 lands that line is
  already `"\n"`; re-editing it would either duplicate the sibling's fix or regress it.
- **All three rewrite methods hold `self._manifest_lock`** (`manifest.py:295-315` caller contract,
  `:371-394`, `:396-407`, `:500+`). Any new trigger must too.

## Conventions to follow

- The module's own docstrings already state the intended shape: compaction "rewrites the deterministic
  snapshot (byte-stable by construction, since it sorts keys and serializes with fixed separators) and
  atomically resets the journal". Match that; do not invent a new format.
- All three rewrite methods hold `self._manifest_lock`; any new trigger must too.
- `_replace_snapshot` writes a temp file + `os.replace` + directory `fsync`; reuse it, do not
  hand-roll persistence.

## Tasks

### Task 1 — Make the trigger file-based (Effort: S)

**Files**
- Modify: `bilibili-asr-archive/src/bili_asr/manifest.py` (`_maybe_compact_locked` ~`:295-315`,
  constants ~`:51-54`)

**Change.** Replace the per-instance clause with a per-file one: compact when the journal has grown
past the snapshot, e.g.

```python
        if journal_bytes < max(_JOURNAL_MIN_COMPACT_BYTES, _JOURNAL_WRAP_BYTES_FACTOR * snapshot_bytes):
            return
```

where `journal_bytes` is the size **read from the file**. Two ways to get it, prefer the second:

- the parameter already passed by `upsert` (`manifest.py:462`) — it is the replayed on-disk size plus
  this instance's own appends (`:252`, `:292`), so it **undercounts** whenever another process
  appended since this instance's last replay;
- **stat the journal inside `_maybe_compact_locked`** the same way the snapshot size is already taken
  one line above (`os.path.getsize(self.path)`) — symmetric, and immune to the staleness above. This
  is the shape Q1/D9 records as the contract: **both** sizes come from the file, so the trigger is a
  function of the ledger on disk and not of who happens to be running it.

Keep a floor so a tiny ledger does not rewrite constantly (a snapshot of a few hundred bytes would
otherwise compact on every row).

Preserve: the snapshot-absent case must not delete a journal it did not fold (`I-000138`). The
per-instance counter and its constant are removed under this ruling — delete `_appends_since_compact`
and `_JOURNAL_COMPACT_THRESHOLD` together rather than leaving either unused; keep `_journal_bytes`
(it is the on-disk byte carrier `_replay_latest` returns and `load()`/`upsert()`/`migrate_legacy_rows()`
maintain).

**In scope**: `bilibili-asr-archive/src/bili_asr/manifest.py`,
`bilibili-asr-archive/tests/test_manifest.py`. **No CLI file is in scope** — Q1/D9 ruled the
maintenance subcommand out (see Task 3).

**Out of scope**: the journal's format, `_append_record`'s durability (write + `fsync` + directory
`fsync` — do not weaken), `_replay_latest`'s split rule (that is plans/journal-replay-integrity.md's fix;
if it has not landed, do not duplicate it here), `search_index.py`.

### Task 2 — Order `save()` like its siblings (Effort: XS, same round)

**Change.** In `save()`, move `_remove_journal()` to **after** the successful `_replace_snapshot(...)`,
and leave both artifacts untouched when `current` is empty:

```python
        with self._manifest_lock(create=True):
            current, _journal_bytes = self._replay_latest()
            if requested is not None:
                current.update(requested)
            if not current:
                self._entries = {}
                self._loaded = True
                return
            self._replace_snapshot(current)
            self._remove_journal()
            self._appends_since_compact = 0
            self._journal_bytes = 0
            self._journal_signature = self._journal_stat_signature()
```

This also fixes the empty-`current` early return that currently unlinks first — the `I-000138`
hazard in its `save()` form. Keep the in-memory bookkeeping (`_appends_since_compact` /
`_journal_bytes` as applicable, `_journal_signature = self._journal_stat_signature()`) consistent on
**every** exit including the early return, so the next `upsert`'s staleness check (`:216-220`) does
not do a needless re-replay; the early return must touch neither artifact on disk.

### Task 3 — **OUT of scope** (ruled out by Q1/D9; not "deferred")

The candidate was a `bili-asr` maintenance subcommand calling `compact()`. It is **cut for this
plan**, with the evidence in `## Approach` above. Its stated premise does not hold: the journal is
never written by readers — `_append_record` (`manifest.py:266`) has exactly one caller, `upsert`
(`manifest.py:454`), and that caller always evaluates the trigger immediately afterwards
(`:462`). There is no process in which the journal grows without the fold being evaluated in the
same call.

**Do not add a CLI surface in this plan.** The plan's in-scope list is correspondingly narrowed to
`manifest.py` + `tests/test_manifest.py` — the `cli/*.py` allowance that used to sit in the in-scope
line is withdrawn. If the trigger proves insufficient on a real root, the reopening route is the
reopen condition in `## Approach`, not an implementation-time improvisation.

**Split point.** Task 1+2 are one round and the whole of this plan's implementation surface.

**Ablation:** removed component — the maintenance subcommand. Nothing fails without it: no acceptance
criterion, no captured issue (`I-000167` / `I-000170`) and no compass Non-Goal names an on-demand
fold, and `save()`/`compact()` have zero `src/` callers today.

Should the reopen condition fire, the candidate shape is already known, so no redesign round is
needed: owner module `bili_asr/cli/queue.py` (the module that already owns manifest-producing verbs
`derive-manifest` / `derive-audio-inventory`), verb `compact-manifest`, contract = open `ManifestStore`
on `--archive-root`, call `compact()` (which takes `self._manifest_lock` itself, `manifest.py:396-407`),
print before/after byte sizes for both artifacts, exit 0/1. **Do not build it in this plan.**


### Task 4 — Fix `migrate_legacy_rows`' rewrite base (routed from `I-000195`, Effort: S)

**Why this plan owns it.** `I-000195` (high, captured 2026-10-03 during plan-QC) is the same durable-deletion
invariant this plan exists to enforce (`I-000138`: never unlink a journal whose rows were not folded), in the
same file, with the same fix shape as Task 2 — and this plan's `## Contracts to preserve` already argues about
`migrate_legacy_rows`. Plan `journal-replay-integrity` closed only the split-rule cause; this one closes the
base cause. Public-API repro is in the issue; the PM verified the anchors by reading `manifest.py:521`, `:528`,
`:536-543`, `:596-598` directly.

**Change.** Make the rewrite base the **effective replay view** rather than the snapshot-only view, so a
journaled *supersede* of an existing page-qualified row survives the rewrite — mirroring what `save()` already
does (it replays into `current`). The overlay at `:536-543` exists precisely because the base is the snapshot;
widening the base to the replay view makes that overlay redundant for kept keys while keeping the bare-legacy
coalesce merge (`:536-540`) intact, since the migration's own source rows are bare-legacy. Preserve the
migration's report semantics (`LegacyMigrationReport` counters), the bare-legacy identity/re-key logic, and the
`next_entries != current` guard at `:596`.

**Verify.** The issue's repro must go green: `save({BV1:p0: meta_ok, BV9: bare legacy})` →
`upsert(BV1, status="archived")` → fresh `ManifestStore(root).migrate_legacy_rows(lambda b: [page(b,0,1)])` ⇒
snapshot's `BV1:p0` reads `archived`, and a fresh `load()` agrees. Add that as a regression test in
`tests/test_manifest.py` (red on the pre-fix base — verify it is red before changing the source).

**STOP.** If widening the base changes the migration's *report* semantics (a row that would have been counted
as re-keyed/updated is no longer counted, or vice versa), STOP and report — the counters are consumed by
`subtitles.harvest_subtitle` and the CLI. If the fix requires changing `_read_latest` (as opposed to which view
the base is built from), STOP — that is the sibling plan's surface.

**PM ruling on Task 4's flagged concern (2026-10-03).** The implementer kept one `_read_latest()` call,
now used **only** to select `bare_keys` — the set of rows the `LegacyMigrationReport` counts — and flagged that
widening it to the replay view would newly count journal-only bare rows (reachable through `upsert`'s freeze path
for `unresolved` / `excluded_from_page_processing` rows), which is this task's STOP condition.

**Ruling: the deviation is accepted and becomes the recorded contract.** Three reasons, in order of weight:

1. **The comment states a real distinction.** The migration's *source* rows are bare-legacy rows **of the
   snapshot**. A row journaled bare since the last snapshot is not a legacy row awaiting migration — it is a row
   a newer writer deliberately froze, and counting it as a migration source would relabel a live state as
   migrated/unresolved. The pre-existing behaviour is correct here; what was wrong was the *base*, not the
   source selection.
2. **The operator surface is unchanged.** The reason the counters are a STOP condition is that
   `subtitles.harvest_subtitle` and the CLI read them. Preserving them is the conservative choice, and a
   counter change is a separate, reviewable decision rather than a side effect of a data-loss fix.
3. **It is not a residual risk.** `_replay_latest()` begins with `entries = self._read_latest()` and overlays
   the journal onto it, so the effective view is a *superset* of the snapshot view — every `bare_keys` entry is
   present in `next_entries`, and the `next_entries[key]` lookups are unconditionally safe. Verified by the PM
   by reading `_replay_latest`'s body.

So `next_entries` is built from the effective view while `bare_keys` is selected from the snapshot: upstream
frames resolve newer, and the migration's *own* source selection stays exactly as it was. If a future iteration
wants journal-only bare rows migrated, that is a new issue about the **source set**, not a reopening of this
one — do not re-file it under `I-000195`.

**PM refutation of the L2 review's ⚠️#2 (2026-10-03, recorded so it is not carried forward as if true).** The
review reported that the widened base "makes a journal-only destination row visible to `dest_occupied` →
`manifest.py:573-584` now raises `ManifestMigrationCollision` **where the old base silently discarded it**", and
asked whether `subtitles.py:109` (which calls without `coalesce_existing_page`) needs handling.

**PM probe says the refusal is not introduced by this change — it fires identically at the pre-fix base.** Method:
byte-identical source twins (`4357617`'s `manifest.py` vs HEAD, sha `aeff2130…` / `5b3de752…`), the same ledger
built through the public API (`save` a bare-legacy row → `upsert` the page-qualified destination row, which lands
in the journal), then `migrate_legacy_rows(..., only_bvid=…)`:

| tag | journal-only DEST row | outcome | snapshot after |
|-----|-----------------------|---------|----------------|
| pre `4357617` | seeded | **RAISED** `ManifestMigrationCollision: migration would overwrite existing work_id BV1xx411c7mD:p0` | unchanged |
| post `91e74ad` | seeded | **RAISED** `ManifestMigrationCollision: …` (identical) | unchanged |
| pre | not seeded | NO RAISE, `migrated=[BV1xx411c7mD:p0]` | row migrated |
| post | not seeded | NO RAISE, `migrated=[BV1xx411c7mD:p0]` (identical) | row migrated |

The explanation is in the pre-fix code itself: the old base was `dict(current)` **and then** every
snapshot-absent `effective` key was added (`for key, entry in effective.items(): if key not in next_entries:
next_entries[key] = entry`). A journal-only destination key is snapshot-absent, so it was in the old base too —
`dest_occupied` saw it and raised then as well. The change alters which row **wins** for keys present in **both**
views (that is `I-000195`'s fix); it does not alter the **key set** `dest_occupied` examines.

**Consequence for the review's question:** the `ManifestMigrationCollision` path at `subtitles.py:109` is
pre-existing behaviour that this plan neither introduces nor widens. It is therefore **out of scope**, and it is
not recorded as a residual of this plan. If the collision-vs-discard policy for a journal-only destination row is
unwanted, that is a separate issue about `migrate_legacy_rows`' collision policy (and possibly about whether
`subtitles.harvest_subtitle` should pass `coalesce_existing_page=True`) — open it on its own merits, not as a
consequence of this change.

## STOP conditions

- If `_maybe_compact_locked` or `save()` no longer matches the excerpts, STOP and re-read.
- If making compaction file-based would compact on **every** append for a small archive (snapshot
  absent or tiny), STOP and pick the floor with the measured sizes from the live root
  (`/srv/bili-asr-archive/manifest/manifest.jsonl` is 9032 bytes over 34 rows) rather than guessing —
  the cost of a wrong floor is a snapshot rewrite per row.
- If a test asserts the journal survives a specific `save()` sequence, STOP and read it: the ordering
  change is exactly what such a test would pin.
- If the journal is absent on the target root (the live root has none today), do not fabricate a
  trigger from it — the byte arithmetic must hold for the snapshot-only case too.
- **Contract-breaking (irreversible) — STOP, do not implement around it:**
  - If a file-based trigger cannot be expressed without changing the **journal disk format**, the
    **snapshot format**, or `_append_record`'s durability sequence (`write` → `fsync(fd)` →
    `fsync(directory_fd)`, `manifest.py:275-288`), STOP and report. Those are the contracts other
    processes and readers rely on; a fold that needs a format change is a different plan.
  - If the ordering fix in Task 2 would be achieved by deleting the journal **before** the snapshot in
    any branch — including the empty-`current` early return — STOP: that re-opens the exact data-loss
    window this plan exists to close, and it re-breaks `I-000138`.
  - If the only way to make the trigger reachable on a real root is to add the Task 3 maintenance
    command (or any new CLI surface), **STOP and report to PM** rather than implementing it. Q1/D9
    ruled that surface out with evidence; a real counter-example is a finding, not a licence to add it.
  - If a caller outside `manifest.py` starts appending to `manifest.journal.jsonl` (grep `O_APPEND` /
    `JOURNAL_NAME` under `src/`), STOP — the "append path alone is sufficient" premise of D9 is then
    false and the trigger form must be re-decided before this plan continues.

## Drift check

```
git diff --stat 1e756df..HEAD -- bilibili-asr-archive/src/bili_asr/manifest.py bilibili-asr-archive/src/bili_asr/sidecar_projection.py
git log --oneline 1e756df..HEAD -- bilibili-asr-archive/src/bili_asr/manifest.py
git diff 1e756df..HEAD -- bilibili-asr-archive/tests/test_manifest.py | grep -n "compact\|save\|journal"
```

Re-read before editing when any of these is non-empty:

1. `manifest.py` changed — re-read **both** methods against the excerpts above.
2. `sidecar_projection.py` changed — it is a journal reader (`replay_journal_records`,
   `sidecar_projection.py:193-218`); a format assumption moving there changes what a fold may do.
3. `test_manifest.py` gained a `compact()` / `save()` / journal case — the sibling plan
   (`journal-replay-integrity`) and this plan both add cases there, and a pin written by the first
   landing is what a second landing must not contradict.
4. **`journal-replay-integrity` has not landed yet** (check `git log --oneline 1e756df..HEAD` for its
   commit): this plan's `Depends on` says it lands first. If it has not, that is a sequencing error,
   not a merge conflict — report it; do not fold its change into this one.

## Done criteria

- [ ] A normal append path (not just tests) can fold the journal: a test drives N cross-process
      appends and asserts the journal shrank and the snapshot holds every row
- [ ] **Observable, outside the process that implements it** — record the on-disk byte sizes of
      `{root}/manifest/manifest.journal.jsonl` and `{root}/manifest/manifest.jsonl` before and after
      the folding append; after folding, the journal's size is **lower** and a reader that opens only
      `manifest.jsonl` finds every row that was journaled. Sizes are the observable; no timing
- [ ] `save()` writes the snapshot before unlinking the journal; the empty-`current` case touches
      neither artifact (pinned by content, not by mtime granularity)
- [ ] The `I-000138` invariant holds: with no snapshot and journal rows present, no path deletes the
      journal
- [ ] A failure injected between the snapshot write and the journal unlink leaves the journal
      recoverable (record the injected failure and the observable)
- [ ] `cd bilibili-asr-archive && PYTHONPATH=$PWD/src python -m pytest -q tests/test_manifest.py` passes; record the command and result
- [ ] `git diff --check` exits 0; `git status --short` shows no out-of-scope file
- [ ] Record the on-disk before/after sizes for snapshot and journal in the task report

## Verification notes

Run from the package root with the absolute source path pinned. Do not run the full suite. Any
timing/ordering assertion must be deterministic — no sleeps. If the compaction test needs a journal
larger than a floor, construct it by appending rows through `upsert`, not by writing the file by hand
(the point is to exercise the real path).

## Engine lifecycle ownership

Source-only repair, no lifecycle claim. Advanced by PM through the normal per-plan flow; no delivery
tail promised. **No CLI surface is added** (Task 3 ruled out by Q1/D9), so this stays a plan-local
change with no workflow registration.
