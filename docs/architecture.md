# Current Architecture

Interactive component map: [architecture.html](architecture.html) (source:
[architecture.json](architecture.json)). It covers the CLI, SQLite workflow,
metadata acquisition, transcript production, editorial processing,
publication, and read projections.

The product has one execution core: the SQLite-backed workflow. A worker
claims one job, runs a handler against fixed inputs, and records the attempt
and result. The database is the operational source for metadata, immutable
transcript versions, workflow attempts, and publications. Files below the
archive root are byte artifacts and are published only through the archive
writer.

Long-running handlers keep the exact attempt alive through a daemon heartbeat
that uses a separate SQLite connection. CUDA/ROCm ASR runs cross a killable
child-process boundary; an expired inference is terminated and recorded as the
retryable `inference_timeout` outcome, so a stuck forced aligner cannot hold a
workflow lease indefinitely.

```text
CLI / composition
        |
        v
Workflow planner -> SQLite jobs, dependencies, leases, attempts
        |
        +--> Acquire: metadata, captions, audio
        |
        +--> Process: ASR, editorial proofread, deterministic rendering
        |
        +--> Publish: transcript bundles and documents
                         |
                         v
               Query projections: status, coverage, export, verify, search, dedup
```

The reading site is a separate static projection. `reading-export` opens the
archive database read-only, verifies each selected `reading.md` and `review.md`
against their recorded SHA-256 values, and generates the site's content
snapshot. Review decisions
and accepted human editions return through explicit CLI commands and append-only
review events; the original AI revision stays immutable.

The `dedup report` projection is read-only. It measures exact audio reuse and
cross-part transcript content hashes before any future alias or merge decision;
it does not choose a canonical record or rewrite provenance.

## Boundaries

`bili_asr.cli` parses arguments and constructs a run context. It owns command
configuration and should not implement stage state transitions.

`bili_asr.storage.workflow` owns job planning, dependency eligibility, leases,
attempt records, retries, immutable ASR profiles, and terminal outcomes. The
executor renews an exact attempt from an independent file-backed SQLite
connection while a handler runs; stale workers are fenced by job ID, owner, and
attempt count. A
profile is versioned by its configuration digest; registering a changed
configuration never mutates a profile referenced by an existing job.

`bili_asr.storage.metadata`, `storage.transcripts`, and the acquisition
services own external observations and durable transcript facts. A transcript
version is append-only. The ASR job records its reference transcript at plan
time and consumes the exact successful audio prerequisite result.

`bili_asr.asr` owns model lifetime, decoding, alignment, coverage evidence,
provenance, and the bounded CUDA/ROCm inference child process. A forced
alignment hang is killed at the configured deadline and returned to the
workflow as a retryable failure. It does not write workflow state or publish files. Editorial
handlers follow the same rule and persist input snapshots, model-call
envelopes, chunk results, revisions, and rendered document records through
their repositories.

`bili_asr.archive` is the object publication boundary. It writes the complete
bundle under a confined archive root and accepts a lease fence callback before
each irreversible replacement. The workflow handler checks the lease before
and after publication and before recording the publication fact.

`bili_asr.services.workflow_projection` is the read projection for the
workflow. `coverage`, `export`, and `verify` read video parts, transcript
versions, publication facts, and bundle layout from SQLite and published files.
They do not maintain a second execution status machine.

## State ownership

| Fact | Owner | Derived readers |
|---|---|---|
| Video and part observations | `storage.metadata` | planner, status, export |
| Transcript versions and segments | `storage.transcripts` | publisher, search, editorial |
| Job, dependency, lease, attempt | `storage.workflow` | worker, status, retry |
| Published bundle identity | `workflow_publications` plus bundle marker | coverage, export, verify |
| Search index | `search_index.store` | search |

The coordinator and JSONL manifest state machine have been removed from the
execution path. SQLite workflow jobs and attempts now own scheduling and
outcomes.
