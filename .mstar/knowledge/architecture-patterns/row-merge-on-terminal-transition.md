---
module: bili-asr manifest row writes (append-only ledger with whole-record reads)
date: 2026-09-20
problem_type: architecture_pattern
category: architecture-patterns
severity: medium
plan_id: 20260920-transcript-projections
applies_when:
  - writing a row on a state transition another component already performs
  - adding a writer to an append-only manifest whose readers take the last record per key
  - reviewing a command that "updates" a row it did not create
tags:
  - manifest
  - append-only
  - merge-semantics
  - data-loss
  - audit
related_components:
  - manifest.py
  - coordinator.py
  - cli.py
  - archive.py
---

# Merge a row on a transition another writer also performs

## Context

`manifest/manifest.jsonl` is an append-only ledger. Its readers do not reconstruct a row
field-by-field from history: `ManifestStore._read_latest` keeps the **last record per key whole**,
and `upsert` appends the mapping it is handed as one record. The shipped chain therefore updates a
row by *merging*: `_mark_archived` reads the current effective entry (`_current_entry()`), applies
`.update(paths)`, and upserts the union (`coordinator.py:520-527`).

The projection command first shipped the other shape — it upserted exactly the fifteen keys it
decides. On the live transition that shape **replaces** the row, and every key the chain had put
there earlier disappears: a part whose row carried `audio_path`/`status: audio_ok` (from
`download-audio`/`run`) loses `audio_path` and `artifact_paths`; because `archived` is terminal and
only the chain's own archive step reclaims transient audio, the `.m4a` is orphaned and
`coverage`/`export` read `None`. The plan-QC correctness seat found it; the fix is one expression —
`store.upsert({**existing, **own_keys})`.

## Guidance

- **On a transition the chain also performs, merge; do not replace.** Read the effective row
  (`store.get(work_id)` / `_current_entry()`), spread it, then spread your own keys so yours win.
- **Do not re-derive the whole row from your own knowledge.** Your command knows a subset; the row
  may legitimately carry keys from another subsystem (audio paths, attempt records, an earlier
  status). Treat the row as shared state, not as a record you own.
- **A single load-time snapshot is an acceptable base in this design, and exact-key addressing is
  required.** `store.load()` once per run is enough when a `work_id` maps 1:1 to a part and the
  archive-writer lock covers the whole dispatch; a bvid-keyed compatibility lookup
  (`get_compatible`) is *worse* — it can resolve a sibling page's row and copy that page's
  `audio_path`/`cid` into the wrong part.
- **When you write documentation about the keys you record, state the scope of the claim**: "these
  are the keys this command decides" is not "these are the row's keys". The original spec sentence
  ("no `audio_path` — no audio exists for a caption") was true of the decision and false of the row.

## Why This Matters

The failure is silent, additive-looking, and terminal: the write succeeds, the readers still parse
the row, and the only symptom is a key that is simply no longer there — one whose consumer may be a
reclaim pass that will now never run. It is the class of defect a per-task review of the *writer*
cannot see, because the writer's own contract is satisfied; only a reviewer comparing the writer
against the **other** writer of the same transition catches it.

## When to Apply

- Any new command that writes manifest rows for a state the chain also reaches.
- Any "repair"/"rebuild" command that re-records a row it did not create.
- Reviewing such a command: ask *who else writes this row, and what do they keep that I would drop?*

## Counter-evidence that makes the rule checkable

Pin it with a fixture whose effective row already carries a key your command does not emit (the
fix's case does: a pre-existing `audio_status: audio_ok` row with `audio_path`/`artifact_paths`, then
publish, then assert the carried keys survive **and** your own key wins). Without that fixture a
replacement implementation passes every test you would otherwise write.
