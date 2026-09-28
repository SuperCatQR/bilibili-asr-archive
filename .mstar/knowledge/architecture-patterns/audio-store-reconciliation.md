---
module: bili-asr audio store (archive.db: audio_objects / part_audio_objects)
date: "2026-09-28"
problem_type: architecture_pattern
category: architecture-patterns
severity: medium
plan_id: 20260926-audio-inventory
applies_when:
  - reconciling a store against files on disk
  - defining the counters a reconciliation or inventory command reports
  - deciding whether a reconciliation is allowed to write or delete
  - building a candidate set — manifest rows versus a directory scan
  - choosing the identity a stored object is deduplicated on
tags:
  - reconciliation
  - inventory-counters
  - manifest-as-candidate-set
  - read-only-promise
  - storage-key-identity
  - streaming-digest
  - absent-versus-unreadable
---

# Reconcile from the declared record, not the directory: four counters and a read-only promise

## Context

The audio store could *record* what it downloaded (`MediaQueueRepository.mark_audio_acquired` writes
`audio_objects` and `part_audio_objects`) and nothing could *read it back* as an inventory. The gap was the
second half of the operator's own request — "a queryable audio inventory in the DB" — and the command that
closes it (`derive-audio-inventory`) had been specified in a contract and a plan while never existing in any
commit.

Building it forced four decisions that are easy to get subtly wrong, because each has a plausible alternative
that also compiles and also passes a naive test.

## Guidance

1. **The manifest is the candidate set; the filesystem answers one question only.** A reconciliation walks the
   rows the archive *declared* (`work_id` → `audio_path`) and consults disk for "is the file this row names
   actually there?". A directory scan as the source of truth invents candidates the archive never held, which
   is precisely what the `missing` counter is defined to forbid. The distinction also decides the two modes of
   the shared resolver: `resolve_audio_path(..., require_exists=True)` hits a base only when it holds the
   **file** (the probe you want), while `require_exists=False` can return a **non-existent** path.

2. **Four counters, defined before they are implemented.** They are product rulings, so name them in the
   contract first and implement them as written rather than re-deriving them from the counter names:

   | Counter | Counts | Never |
   |---|---|---|
   | `recorded` | a candidate that had **no** object row and now has one | invented when the file was absent |
   | `already` | a candidate whose row was already present and matched — a re-run converges, it does not accumulate | a second row for one object |
   | `missing` | a manifest row that **names** an `audio_path` and the file is **not there** | deleted, re-created, or silently skipped |
   | `unlinked` | an observed object that **no** `part_audio_objects` row attributes to a part | used to delete anything |

   Note what `missing` is *not*: it is absence, not unreadability, and not "a row we chose to skip". A
   present-but-unreadable file fits **none** of the four; the shipped command counts it as neither and names it
   on stderr with its reason, and the question of whether the vocabulary needs a fifth counter is an open
   product ruling rather than a local redefinition.

   `unlinked` is a **store** observation, not a manifest one: it is the object-id set minus the linked-id set,
   which is how an operator sees that the store holds audio it cannot tie to any archived part.

3. **A row that names nothing is not a candidate.** A manifest row without an `audio_path` is neither recorded
   nor missing — it never declared audio. Counting it as `missing` would invent a candidate, and counting it as
   `already` would claim a match that was never tested.

4. **The identity is `storage_key`, not `sha256`, and that is deliberate.** Location is the identity of an
   archived object: the CLI derives a deterministic per-part path, so a re-download or a repaired decode
   produces a *new* hash for the *same* location and must not become a second object. `audio_objects` carries
   **two** UNIQUE constraints, so both paths exist — reuse by path first, and when no row matches the path but
   another row already holds that `sha256`, reuse that row and repoint its `storage_key` (the "same content, new
   path" branch). A silent third row is never written.

5. **Digesting is not optional, and `--deep` means re-verify.** `audio_objects.sha256` is `NOT NULL UNIQUE`, so
   a row without one cannot be deduplicated and the writer refuses a bare hash. A single **streamed** pass gives
   hash and size together, which is the same read the size probe would pay for anyway. `--deep` is therefore
   not a "hash or don't" switch: it re-verifies the digest of an object whose row is **already present**.

6. **Publish the cost model, then honour it.** "One streamed read per newly recorded file; zero file reads for
   a candidate whose `storage_key` already has a row and is not passed to `--deep`" is a testable promise about
   I/O. Honouring it means the row check comes **before** the digest — the natural order (digest, then ask) is
   wrong and costs a read per known row on every re-run. Pin it by counting reads, not by reasoning:
   monkeypatching the digest helper and asserting `(recorded, reads) == (1, 1)`, then `(already, reads) ==
   (1, 0)`, then `(1, 1)` under `--deep`.

7. **A read-only promise is proven by a byte-snapshot, not by reading the code.** "The command never deletes,
   re-creates or moves a file" is checkable: hash every file under the root (including a deliberately stray one
   no manifest row names), run the command, hash again, and require the two maps to be identical. The absence
   of a write call is an argument; the unchanged tree is evidence.

## Why This Matters

A reconciliation that writes the wrong thing is worse than one that does nothing, because the store is the
archive's record of truth — a `missing` counter that deletes, or an `unlinked` counter that "tidies up", would
destroy the very evidence an operator is trying to read. And a reconciliation whose counters are defined
loosely produces numbers nobody can act on: the operator cannot tell "the file is gone" from "I could not read
it" from "I did not look", which are three different repairs.

## When to Apply

- Any command whose job is to reconcile a declared record against the filesystem.
- Before implementing counters named in a contract: implement as written, and if one cannot be computed as
  defined, **stop and report** rather than redefining it locally.
- When the candidate set could plausibly come from either a record or a scan — the record is the source of
  truth, and the filesystem is the probe.
- Whenever a command's I/O behaviour is part of its contract, including "it reads nothing for the common
  case".
- When a read-only or additive promise needs to be defended: prove it over the whole tree, byte for byte.

## Examples

### Before — counters derived from their names, and a scan for candidates

```python
for path in audio_dir.iterdir():        # invents candidates the archive never declared
    if path.name not in stored:         # and cannot tell "absent" from "unreadable"
        missing += 1
```

This "works" on a tidy fixture and reports nonsense on a real root: a stray file becomes a candidate, a
permission error becomes a deletion, and a row whose file moved looks identical to one that never had audio.

### After — declared candidates, four defined counters, and the read counted

```python
for work_id, entry in sorted(entries.items()):
    declared = entry.get("audio_path")
    if not declared:
        continue                        # not a candidate at all
    resolved = _resolve_existing(roots, entry)   # require_exists=True: the file must be there
    if resolved is None:
        missing += 1                    # named-but-absent: reported, never invented, never deleted
        continue
    if str(declared) in keys and not deep:
        already += 1                    # the row check is BEFORE the digest: zero reads
        continue
    sha256, byte_size = _digest_and_size(resolved)   # one streamed pass, and only when needed
```

## Evidence

- `.mstar/iterations/iter-2026-09-metadata-audio-layout/specs/audio-retention-contract.md` §3 (field
  semantics), §3.1 (the four counters as product rulings, with the one-summary-line and exit taxonomy), §4
  (what a reclaim may and may not delete), §5 (bounds on a future change).
- The command: `feat/20260928-audio-inventory` `678b376` + `bda9465`
  (`src/bili_asr/services/audio_inventory.py`, `tests/test_audio_inventory.py`, 8 tests).
- The cost model, measured by counting digest calls: 1 read for a new file, **1** where the plan requires
  **0** in the first cut, then **0** after the row check was moved ahead of the digest; `--deep` re-verifies at
  1.
- The read-only promise, measured: a byte-snapshot of every file under the root before and after a run is
  identical; no file created, none removed, and a deliberately stray `audio/stray.m4a` still present.
- `unlinked` proven load-bearing: an orphan object row gives `unlinked=1`; adding its
  `part_audio_objects` link gives `unlinked=0`.
- The identity rule and its "same content, new path" branch: `mark_audio_acquired`'s own docstring, and
  `architecture-patterns/audio-evidence-queue-contract.md` on the two UNIQUE constraints.

## See also

- `architecture-patterns/audio-evidence-queue-contract.md` — the **write** side: which table is the sole
  positive audio-evidence probe, and why the three gap groups must never be summed. This document is the
  **read** side of the same two tables.
- `architecture-patterns/artifact-root-split.md` — the base-resolution rules `resolve_audio_path` follows, and
  why write-side re-confinement must use one base instead of the read loop.
- `best-practices/degradation-vs-observation-third-state.md` — the general form of the "absent vs unreadable"
  problem this vocabulary deliberately does *not* fold into one counter.
