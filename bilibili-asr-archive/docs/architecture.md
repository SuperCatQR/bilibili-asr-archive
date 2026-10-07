# Current Architecture

The package is organized around four runtime boundaries and one composition
root:

```text
CLI composition root
  -> services (metadata, subtitles, queue derivation, adoption)
  -> storage repositories (metadata, transcripts, media queue)
  -> pipeline stages (attempts, locks, ASR/archive writeback)
  -> products (archive bundles, manifest, search indexes)
```

`bili_asr.cli.main` owns argument parsing, artifact-root resolution, writer
locking, and command dispatch. Command modules contain one concern each. The
package-level `bili_asr.cli` surface exposes the dispatcher and parser only;
private command handlers are imported from their owning module.

The ASR package keeps model ownership in `asr.runner`, audio decoding and
chunking in `asr.audio`, cue alignment in `asr.alignment`, configuration and
hotword policy in `asr.config` / `asr.hotwords`, and evidence projection in
`asr.coverage` / `asr.provenance`. The runner is lazy and run-scoped: callers
can reuse one model set across parts without moving storage or publication
logic into the model boundary.

SQLite access is split by write responsibility. `storage.database` owns
connection/bootstrap/schema contracts; `storage.metadata` owns normalized
video discovery and ingestion state; `storage.transcripts` owns transcript
versions and segments; `storage.media_queue` owns audio queue predicates.
Transactions stay inside the repository methods documented as committing; the
other methods remain composable inside a caller transaction.

The coordinator is a thin state machine. `pipeline.stages` performs subtitle,
audio, ASR, and archive stages; `pipeline.attempts` redacts failure evidence;
`pipeline.writeback` applies manifest/store updates; `pipeline.locks` owns the
archive writer lock; and `pipeline.models` holds stage result records. This
keeps resumability and atomic bundle publication visible without making the
CLI or repositories depend on model details.

Search has two explicit implementations. `search_index.manifest` serves the
legacy manifest index, while `search_index.store` serves the transcript FTS5
index. Shared query models, readers, constants, and error classes live in the
remaining submodules. Neither read path creates a missing index.

Tests follow the same ownership map. Reusable fakes, archive seeds, CLI
builders, and transport fixtures live in `tests/support/`; test modules contain
scenario assertions. `scripts/project_staging.py` is the single bounded
staging helper used by offline fixture and installed-entrypoint verification,
so verifier output cannot recursively copy the checkout into itself.
