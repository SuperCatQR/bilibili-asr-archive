# Plan 017 — Revalidate the published contract against the shipped mechanism

## Status
- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Confidence**: HIGH
- **Fingerprint**: audit-2026-10-02r2/07-contract-drift-docs
- **Depends on**: none
- **Category**: docs
- **Evidence**: `bilibili-asr-archive/README.md:1000`, `:566-570`, `:1309-1312`, `:490-492`; `bilibili-asr-archive/docs/metadata-storage.md:72-77`; `bilibili-asr-archive/src/bili_asr/cli/run.py:49,66`
- **Planned at**: commit `1e756df`, 2026-10-02
- **Captured issues**: `I-000169`, `I-000179`, `I-000181`

## Problem

The `ff39fd0..1e756df` delta moved durable facts and left the published contract describing the prior
mechanism. `git log --name-only ff39fd0..1e756df -- docs README.md` is **empty** — no doc change rode
with the code.

| # | Published claim | What the code now does |
|---|---|---|
| A | `README.md:1000` — "The JSONL manifest (`{archive-root}/manifest/manifest.jsonl`) remains the single source of truth" | The ledger is a **pair**: the deterministic snapshot plus `manifest.journal.jsonl`, which is where `upsert` appends (one O(1) write per row). The journal is not named anywhere in the README's ledger or archive-root inventory (`:566-570`). |
| B | `README.md:1309-1312` — "each appended row is one locked re-read of the whole ledger plus two `fsync` calls … `N·L + N(N−1)/2` line parses — at `N = L = 2,000` roughly 6M parses" | Plan 003 replaced this with a journal append: one replay per process, then O(1) per row. The paragraph is now an analytic bound for a mechanism that no longer exists. |
| C | `docs/metadata-storage.md:72-77` — "`audio_objects`, `part_audio_objects`, and `asr_models` are still empty: no audio bytes and no ASR model rows are written by any command here" | The R14 write-back writes all three: `database.py:1198` (`asr_models`), `:1816` (`audio_objects`), `:1862` (`part_audio_objects`), reached from `cli/asr.py:290`, `cli/pilot.py:364/601`, `coordinator.py:794`, `cli/queue.py:193/397`. |
| D | `README.md:490-492` — "The ASR/pilot chain (`download-audio`, `asr`, `pilot`, `run`, `schedule`, `campaign`) is still driven from `manifest/manifest.jsonl`" | The store route and the transcript write-back have landed (`11374d1`, `aee6f2e` are ancestors of `main`); `--queue-source store` is a shipping flag and `queue_source.py:300/329` are the write-back entry points. |
| E | `cli/run.py:49,66` — `{"archived", "gone"}` spelled inline | `manifest.TERMINAL_STATUSES` is the same fact, imported by `coverage_report.py:13`, `scheduler.py:17`, `coordinator.py:30`, `campaign.py:20`. A third terminal status would be honoured everywhere except `run`'s scopes, silently re-queuing terminal rows. |

Rows A–D are the same failure mode the repo's own
`{KNOWLEDGE_DIR}/best-practices/claim-scope-discipline.md` names: a published claim wider than the
code. Row E is a live drift hazard, not a doc.

## Current state (excerpts — verify against live code before editing)

`bilibili-asr-archive/README.md:1309-1312`:

```
- **Append cost, bounded analytically (not measured)**: each appended row is one
  locked re-read of the whole ledger plus two `fsync` calls, and the whole
  derivation runs under the archive-writer lock, so appending `N` rows to an
  `L`-line ledger costs about `N·L + N(N−1)/2` line parses — at `N = L = 2,000`
  roughly 6M parses and 4,000 fsyncs. That is an analytic bound only: no runtime
  measurement was taken on a real archive, so a first full-queue derivation
  should be treated as holding the writer lock for a duration this iteration
  does not state.
```

`bilibili-asr-archive/docs/metadata-storage.md:72-77`:

```
`audio_objects`, `part_audio_objects`, and `asr_models` are still empty: no
audio bytes and no ASR model rows are written by any command here. The legacy
audio/ASR chain (`download-audio`, `asr`, `pilot`, `run`) still records its work
in the JSONL manifest, not in these tables, so nothing on this path fills them
yet.
```

`bilibili-asr-archive/src/bili_asr/cli/run.py:45-50`:

```python
        return (
            [
                (key, e)
                for key, e in sorted(entries.items())
                if e.get("status") in VALID_STATUSES - {"archived", "gone"}
                and not _is_excluded(e)
            ],
            None,
        )
```

## Conventions to follow

- The README is the operator's contract surface; write the *mechanism* (what happens, at what cost,
  with which bound), not an assurance. The repo's claim-scope discipline requires the bound to travel
  with the claim: "one replay per process, then one O(1) journal append per row" — and if a number is
  published, it must be a measured one or explicitly labelled analytic.
- Match the existing README voice for the ledger: name the pair (snapshot + journal), name the
  compaction rule as it now reads in code after plan 014 — if 014 has not landed, describe the
  mechanism as it exists (journal appended, snapshot rewritten on `save()`/`compact()`) and do not
  promise the trigger that 014 will add.
- `{KNOWLEDGE_DIR}/architecture-patterns/journal-ledger-and-projection-replay.md` is the crystallized
  record of the new mechanism — align the README with it rather than inventing new prose.

## Tasks

### Task 1 — Correct the ledger claims (Effort: XS)

**Files**
- Modify: `bilibili-asr-archive/README.md` (the SSOT sentence ~`:1000`; the archive-root inventory
  ~`:566-570`; the append-cost bullet ~`:1309-1312`)

**Change.**
- Name `manifest/manifest.journal.jsonl` beside `manifest.jsonl` and state the pair's roles: the
  snapshot is the compacted projection, the journal holds rows appended since it (so an operator who
  copies only the snapshot sees a stale projection between compactions — say this, since it is
  actionable).
- Replace the append-cost paragraph with the journal mechanism and a true bound. If plan 014 has
  landed, describe the compaction trigger; if not, describe the current behaviour without promising
  one.
- Correct the chain-sentence if Row D is in scope for this pass (Task 3).

### Task 2 — Correct the store-table claim (Effort: XS, same round)

**Files**
- Modify: `bilibili-asr-archive/docs/metadata-storage.md` (~`:72-77`)

**Change.** State which command writes which table, naming the entry points
(`record_local_transcript` / `mark_audio_acquired`), and keep the *boundary* that is still true (the
legacy manifest path records its own work in the manifest; the store rows are the store-side evidence
for the same work). Do not over-claim: if a table has only one writer path, say so.

### Task 3 — Fix the surviving literal and the chain sentence (Effort: XS, same round)

**Files**
- Modify: `bilibili-asr-archive/src/bili_asr/cli/run.py` (`:49`, `:66`)
- Modify: `bilibili-asr-archive/README.md` (~`:490-492`)
- Modify: `bilibili-asr-archive/tests/` — one pin for the literal (see below)

**Change.**
- `run.py`: use `TERMINAL_STATUSES` in both predicates (`VALID_STATUSES - TERMINAL_STATUSES` and
  `not in TERMINAL_STATUSES`). Add a one-line test asserting the two forms are the same object (or a
  behavioural pin: a synthetic third terminal status is excluded by the scope filter) so a future
  status cannot diverge.
- README chain sentence: describe the store route as the chain's queue input and the manifest route
  as the explicit fallback, per what `--queue-source` actually does today — **read `cli/_shared.py`
  and the `--queue-source` help text before writing**, and do not describe the route as default if the
  flag's default says otherwise.

## STOP conditions

- If README `:1309-1312` has already been rewritten (a merge landed the doc half), STOP and re-scope
  to the remaining rows rather than re-editing.
- If `--queue-source`'s default is **manifest** (not store), STOP on Row D: the sentence would then be
  right and only the tension with the landed write-back needs a note. Report which it is.
- If the product decision is that the manifest remains the chain input by design, STOP and record that
  as the ruling rather than "correcting" the README against it — the finding is the drift, not a
  preference.
- Do not restate numbers you have not measured: if a cost figure is needed, either measure it in plan
  019's run or label it analytic, exactly as the current text does.

## Drift check

```
git diff --stat 1e756df..HEAD -- bilibili-asr-archive/README.md bilibili-asr-archive/docs/metadata-storage.md bilibili-asr-archive/src/bili_asr/cli/run.py
```

If any changed, re-read each cited line before editing.

## Done criteria

- [ ] The README names the snapshot **and** the journal where it describes the ledger, and the
      archive-root inventory lists the journal
- [ ] The append-cost paragraph describes the journal mechanism; every number in it is either measured
      (with the measurement cited) or explicitly labelled analytic
- [ ] `docs/metadata-storage.md` no longer says the three tables are unwritten; the replacement names
      the writer path
- [ ] `rg -n 'archived", "gone' bilibili-asr-archive/src` matches only `manifest.py`'s definition site
- [ ] The new pin for `run.py`'s scope literal fails if the literal is reintroduced (record how)
- [ ] `cd bilibili-asr-archive && PYTHONPATH=$PWD/src python -m pytest -q tests/test_cli_help.py -k run` (or the file owning the scope test) passes; record the command and result
- [ ] `rg -n 'new-target' ...` — scoped check: `rg -n "manifest.journal.jsonl" bilibili-asr-archive/README.md` returns the inventory and the ledger passage; record the actual output
- [ ] `git diff --check` exits 0; `git status --short` shows no out-of-scope file

## Verification notes

Docs-only changes use scoped `rg` evidence with the actual output recorded — not a test file. The one
executable change (`run.py`) carries its own unit pin. Do not run the full suite.

Because this plan edits the README, keep the diff to the cited passages; do not reformat the
document. Re-read the surrounding paragraphs before editing so the corrections read as part of the
existing narrative.

## Engine lifecycle ownership

Mixed docs + one source literal, no lifecycle claim. Advanced by PM through the normal per-plan flow;
no delivery tail promised.
