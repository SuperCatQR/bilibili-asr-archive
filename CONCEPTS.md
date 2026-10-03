# CONCEPTS — bilibili-asr-archive

Project-specific domain vocabulary. General programming terms do not belong here.

| Term | Meaning |
|------|---------|
| `work_id` | Ledger key for an archive item: `bvid:p<zero-based-page-index>` for multi-part videos (bare `bvid` for single-part). Distinct from the filesystem `artifact_stem` `{bvid}.p{page_index}`, which never contains `:`. |
| `meta-cursor.json` | Archive-root sidecar persisting archival-flow enumeration state (`next_page`, `total`, `state`, `last_api_error_code`, `updated_at`); `state` ∈ `running` (never persisted) / `risk_interrupted` (the only `--resume`-consumed state) / `limited` / `complete`. Metadata-command enumeration state now lives in the SQLite `ingestion_cursors` table instead (iter-2026-09); this sidecar keeps its role only in the archival flow. |
| risk stop (exit 2) | Batch-stop on API risk-control exhaustion; persists a resumable cursor and exits 2, distinct from per-video failures and from deliberate `--limit-pages` caps. |
| evidence projection | Bounded derived report or sidecar (`campaign.json`, coverage/quality, search index, integrity report, recovery audit, gate result) that may describe manifest-owned work but never becomes a second item state machine or back-writes inferred state. |
| audit-only recovery | Explicit bounded selection of currently verified integrity defects that appends redacted recovery evidence; it does not requeue work, change manifest status, or edit transcript/audio artifacts. |
| `sequential-no-daemon` | The concurrency gate's permanent report mode in this iteration: evaluation can return `go` evidence, but no worker, daemon, service, autostart, or concurrent manifest writer is enabled without a separate approved plan. |
| `run-scoped ASR` | One lazily constructed local ASR model is owned and reused only within a sequential coordinator batch, then released according to creator ownership; it is not a global cache or a concurrency mechanism. |
| `acquisition attempt` | One append-only evidence row per attempted part inside one acquisition run: outcome (`stored` / `unchanged` / `no-subtitle` / `failed`), an optional bounded error code, and the transcript version it produced; never a per-part status. |
| `no-subtitle` | The attempt outcome meaning no usable caption track was visible for this part with the credentials in effect at that attempt — not a failure, not a success, and not a claim that the video has no captions. |
| subtitle track (with `label` and the `ai`/`cc` marker) | One inventory entry a part exposes at one moment: normalized upstream `lan`, printable `lan_doc` label, and an AI-vs-CC classification where a missing upstream marker reads as CC (an audio track or media stream is not a "track" here). |
| transcript version | An immutable revision of one `(part, source kind, language)` caption, appended when its content hash differs from every stored version and never rewritten or deleted; the source-kind vocabulary (`subtitle-ai` / `subtitle-cc` / `asr-local`) is part of its identity. |
| content identity (`content_sha256`) | The SHA-256 over the canonical JSON of the millisecond segment triples that decides whether the archive already holds this caption text, enforced by a partial unique index scoped to the caption kinds (deliberately excluding `asr-local`). |
| audio queue | The work the ASR/audio chain draws from the store: every stored part that holds no transcript and is not `gone`, in the repository's locked order. A part recorded `no-subtitle` is in it, and a part holding any transcript (an `asr-local` one included) is not. Not the same set as `status`'s `pending:` line, which is the metadata backlog. |
| audio object | One archived audio file, as distinct from the part it came from: a part has at most one audio object, and several parts may share one when their content is byte-identical. Its identity is **where it is stored**, not what it contains — re-downloading or re-decoding the same part produces a new content hash for the same location and must stay the same object, which is why a repaired file is an update rather than a duplicate. *Avoid:* audio file, audio record (both read as either side of the object/link split) |
| effective row | The row a projection hands a consumer for one ledger key: the last row in the append-only manifest for that key, keyed by `work_id` when the row carries one and by the bare `bvid` otherwise. An additive consumer must consult the ledger's own key function — writing one key form and looking up another silently misses the other bucket. |
| artifact root | The second, operator-configured root for **products only** (`bili-asr … --artifact-root <path>` / `BILI_ARTIFACT_ROOT`): audio, transcript bundles and harvested subtitle documents are written under it, while the manifest, `archive.db`, `coordinator/` and the sidecars stay at the archive root. Unconfigured it *is* the archive root (one base, the shipped layout); configured it must already exist and the value is kept lexical, so a symlinked root is refused. Recorded artifact paths stay root-relative, and reads probe the configured root then the archive root, first hit wins — which is why an archive needs no migration. |

## transcript projection

The act of publishing a transcript already stored in `archive.db` as an on-disk archive bundle (srt/txt/md/raw + marker) plus one manifest row. Distinct from *acquisition* (fetching a caption or running ASR): a projection decides which stored version wins and records the result so the archive's own readers accept it. Command: `bili-asr publish-transcripts`.

## already_published

The predicate a projection uses to skip work: the effective manifest row **declares** the four bundle paths **and** the completeness reader confirms them at the write base. A row that declares them but fails the read is republished — which is also how an interrupted publication heals.


## manifest journal

The manifest's append-only per-row update log (`manifest/manifest.journal.jsonl`), from which the deterministic
snapshot (`manifest.jsonl`) is rebuilt by a fold. The journal is what makes a per-row write O(1); the snapshot is
what every non-store reader projects.

A **torn fragment** is a journal line a writer never terminated (crash between `write` and its `\n`) — or one that
shared a physical line with a later append that landed on it. Replay stops at the fragment and exposes nothing
after it. The records a fragment leaves behind are **stranded**: fsynced and readable by no one, because replay
refuses to skip mid-stream. A journal may only be discarded once every record it holds is durably published, so a
strand suspends the discard; the fold **settles** it by publishing the stranded records first. *Avoid:* torn tail
(the tail is the usual shape, not the only one), corrupt line (the bytes are a record or a fragment, not garbage).

## Flagged ambiguities

- **audio object vs audio queue** — the *object* is stored content (identity: location); the *queue* is the work the chain still owes (parts with no transcript). A part can be in the queue with no object yet, and can hold an object while no longer being in the queue; the two are never synonyms.