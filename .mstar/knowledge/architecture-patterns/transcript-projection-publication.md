---
module: bili-asr transcript projection (archive.db → published archive bundle)
date: 2026-09-20
problem_type: architecture_pattern
category: architecture-patterns
severity: medium
plan_id: 20260920-transcript-projections
applies_when:
  - publishing a stored transcript as on-disk products a chain's readers already judge
  - turning a database row into files whose names other code derives independently
  - deciding what a publication may claim about provenance it does not have
  - making a publish step idempotent against a store that versions its rows
tags:
  - projection
  - publication
  - manifest
  - idempotency
  - artifact-root
  - provenance
related_components:
  - cli.py
  - services/transcript_projection.py
  - archive.py
  - manifest.py
  - storage/database.py
---

# Publishing a stored transcript as an archive bundle

## Context

`archive.db` holds transcripts; the archive chain holds products (`transcripts/{srt,txt,md,raw}` +
a bundle marker) and a manifest whose rows carry the paths. For most of the project's life the
caption path stored text and published nothing, so a part with a caption could never reach
`archived` — measured live on 2026-09-20: both named items served AI captions, the chain took its
documented subtitles-first branch, the queue correctly excluded them, and **no row could be
produced**. This document records the contract that closed that gap (`iter-2026-09-transcript-projections`,
`20260920-transcript-projections`, delivery commit `71b858e`; full spec: the iteration package's
`.mstar/iterations/iter-2026-09-transcript-projections/specs/transcript-projection-contract.md`, recorded in the
index below as `iteration:iter-2026-09-transcript-projections/specs/...`).

## Guidance

1. **Split the decision from the write.** A pure service decides *which* stored row becomes a
   bundle and *what shape* it takes (`services/transcript_projection.py`); the command composes the
   store read, the decision, and the existing writer, and is the only place that touches I/O
   (`cli.py`). The service imports neither sqlite nor the filesystem, which is what makes the winner
   rule testable without a fixture tree.
2. **The winner rule is a total order with a declared, pinned mirror.** Pick a stored version by
   `(source_kind rank, language family rank, language code, version DESC)` — never "the newest row".
   The language-family ordering is *declared in the projection* and pinned against the harvester's
   own function by an **equivalence test**, because importing the harvester would drag a network
   stack into a pure module. Pin the pair, not the copy.
3. **Read the store read-only and write only the two surfaces you own.** The connection is
   `mode=ro`; the outputs are the bundle (through the existing writer, which owns staging, fsync
   order and the marker) and one manifest row. Nothing is written back into the store — the
   "no back-write of an inferred truth" rule keeps the manifest the chain's state machine.
4. **Merge the manifest row; never replace it.** `ManifestStore.upsert` appends the mapping it is
   given and `_read_latest` keeps the last record per key **whole** — there is no per-key merge. So
   the projection writes `{**existing_effective_row, **its own fifteen keys}`. See
   `row-merge-on-terminal-transition.md` for why this is load-bearing (a pre-existing `audio_path`
   is otherwise dropped and its file orphaned).
5. **`already_published` must mean "declared **and** complete at the write base".** The predicate is
   `declared is not None and archive_bundle_complete(write_base, declared)`: a row that declares the
   four paths but fails the completeness read (missing file, missing marker, any `sha256` mismatch)
   is **republished**, which is also how an interrupted publication heals. The reader returns False
   rather than raising, so an unreadable root means "republish", not "crash" — its cost and its risk
   are both registered (see below).
6. **A publication claims only what the store knows.** The md frontmatter and the raw sidecar carry
   the nine part keys plus the four product paths plus `source`/`language`; every ASR-only key
   (`asr_model_name`, the VAD capture trio, the confidence family) is **absent**, not zero-filled:
   a caption is not a capture and the store has no per-segment confidence column. An absence here is
   evidence only because a fixture can reach the falsifier — an ASR-shaped bundle produced by the
   same writer must make the inverted check match.
7. **Say what a hard kill does, not what you wish it did.** The writer stages under a fixed name and
   cleans up in a `finally`; an unwinding termination heals on the next pass, but a non-unwinding one
   (SIGKILL, default-disposition SIGTERM, OOM, or a failing `finally` itself) leaves the stage dir and
   the writer then refuses **every** later publication into that root, printed as a bare
   `failed (OSError)`. The docstring must state both halves.

## Why This Matters

- The projection is the difference between a store that accumulates text and an archive that
  produces products; without it the caption path is a dead end, which is exactly what a live E2E
  measured.
- Rules 4 and 6 are the two places where the shortcut *looks* right and loses or fabricates
  information: replacing the row silently drops keys, and zero-filling provenance silently invents
  measurement.
- The reader-agreement criterion (idempotent re-run leaves every byte and the effective row
  unchanged; `verify --trusted-local` → zero defects; `coverage --quality` → `reasons: []`) is what
  turns "the files exist" into "the archive agrees they are published".

## When to Apply

- Adding any second producer of archive bundles (a projection for another source kind, a repair
  command, an ASR-local writer).
- Changing what a publication records, or adding a reader that judges a bundle.
- Any command that writes an append-only row on a state transition the chain also performs
  (read `row-merge-on-terminal-transition.md` first).

## Known limits (registered, not hidden)

Two cost/robustness properties were measured and registered rather than fixed
(`entries["20260920-transcript-projections"]`): every completeness decision re-reads and SHA-256s the
four artifacts (so an idempotent re-run re-reads the published corpus, and `upsert` re-reads the
whole JSONL per candidate → O(N²) at corpus scale — `R7`), and a transient probe read error
(EIO/ESTALE) is indistinguishable from "not published", so a flake re-publishes over a good bundle
and invalidates its marker window (`R5`).
