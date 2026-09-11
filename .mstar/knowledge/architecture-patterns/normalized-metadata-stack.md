---
module: bili-asr metadata acquisition stack
date: 2026-09-10
last_updated: 2026-09-11
problem_type: architecture_pattern
category: architecture-patterns
severity: medium
plan_id: iter-2026-09-bilibili-api-sqlite
applies_when:
  - adding or changing metadata acquisition, storage, or its CLI surface
  - wiring a third-party SDK into the package without leaking its response shapes
  - deciding where normalized facts, cursors, or run evidence live
  - extending ingestion (subtitles, media, transcripts) onto the schema reservations
  - bounding or documenting operator-facing collection commands
tags:
  - sqlite-metadata
  - gateway-boundary
  - ingestor
  - normalized-schema
  - exit-taxonomy
  - live-smoke
---

# Normalized metadata stack (gateway → ingestor → SQLite repository)

## Context

Through iter-2026-09 the package replaced its JSONL metadata path (manifest +
meta-cursor + run-ledger sidecars) with a normalized SQLite stack built in three
reviewed layers. No migration was performed: a fresh `{archive_root}/archive.db`
is the metadata source of truth, and the old sidecars keep their role only in
the archival flow.

## Guidance

**Layering and boundaries (top to bottom):**

- **Gateway boundary (`src/bili_asr/sources/`)**: exactly one module
  (`sources/bilibili_api_gateway.py`) imports the third-party package — enforced
  durably by an AST import-boundary test, not by convention. The adapter
  converts package responses into application-owned frozen DTOs with
  post-init validation and normalizes at the boundary (one-based `page` →
  zero-based `page_index`; seconds → `floor(seconds * 1000)` ms). Upstream
  failures map onto a five-class bounded exception taxonomy
  (`rate_limited` / `not_found` / `response_error` / `transport_error` /
  `shape_error`), each carrying a persistable scalar code validated by the
  repository's own `validate_error_code`. Raw upstream text, URLs, cookies, and
  response bodies stay process-local — they may ride the exception chain in
  memory but never enter a DTO, message, log line, or row. Credentials are
  constructed at the boundary and never serialized anywhere downstream.
- **Ingestion service (`src/bili_asr/services/metadata_ingest.py`)**: owns
  pagination, cursor semantics, and the one-page transaction; consumes the
  application-owned protocol (never the concrete adapter). Transitive part
  ownership is enforced here (parts requested only for summaries already
  validated against the requested `mid`). Outcomes are honest by construction:
  `complete` only on an empty page, `limited` never claims complete, gateway
  rate-limits map to `risk_interrupted`, other bounded errors to `failed`, and
  a failed page preserves the prior cursor byte-for-byte.
- **Repository (`src/bili_asr/storage/`)**: 3NF SQLite schema
  (`archive.db` from a checked-in `schema.sql`; all FKs `ON DELETE RESTRICT`;
  reserved audio/transcript tables as empty FK boundaries). Derived values
  (`work_id`, part counts, run aggregates) live in views or computed
  properties, never base-table columns. Public APIs are canonical single-form
  (one form per method; speculative compatibility forms were removed in
  review), and every method's commit behavior is documented in an explicit
  commit matrix. The failure path is a separate no-payload transaction that
  persists only bounded scalar evidence; terminal run outcomes cannot be
  regressed and page clocks are validated against the run's stored
  `started_at`.

**Operator surface:** the existing `bili-asr` executable is the composition
root — it constructs config → database → gateway → ingestor and never parses
third-party dictionaries. The exit taxonomy is bounded and documented
(`0` bounded success/read, `1` usage/config/missing-DB, `2` terminal failure —
gateway variant with scalar code + unchanged cursor, unexpected variant with a
fixed message, no code, cursor possibly at the last committed page and the run
possibly `running`). Full collection is bounded by default
(`--limit-pages` defaults to 10); the credential comes from `BILI_SESSDATA` or
`--sessdata`, is redacted to presence-only in every display path, and an
explicitly blank value means anonymous.

**Why this shape:** each review/QA wave found contract gaps at layer
boundaries rather than inside modules — canonical forms, commit boundaries,
and the bounded-failure protocol had to be made explicit before the next plan
built on them. Freezing the vocabulary (bounded scalar codes, single-form
APIs, transaction ordering) is what made the three plans compose without a
second metadata SSOT.

## Why this matters

- Later iterations (media objects, ASR provenance) must keep extending this stack through the
  reserved schema boundaries and the repository contract — not by reintroducing sidecars.
  Subtitle acquisition and transcript segments did exactly that at
  `iter-2026-09-subtitle-transcript-sqlite`: see `subtitle-acquisition-contract.md` and
  `normalized-transcript-storage.md` (the caption path no longer uses the JSONL sidecars; the
  ASR/pilot commands still do).
- The single-import gateway boundary is what makes package upgrades
  (`bilibili-api-python==17.4.2`) reviewable: the fake-gateway seam mirrors the
  pinned wheel's surface, so offline tests falsify quickly and the opt-in live
  smoke validates the real package.
- The record-level validation is the secret-prevention SSOT: the schema
  enforces only the 64-char length bound; charset and forbidden-class checks
  live at the record boundary and must be inherited by every new consumer.

## When to apply

- Extending ingestion to subtitles/media/transcripts: populate the reserved
  tables through the repository, reusing the locked ordering and bounded-code
  vocabulary.
- Changing the CLI metadata surface: keep the exit taxonomy and documented
  bounds; operators read `status`/`runs` for derived state.
- Reviewing new gateway methods: they must appear on the application-owned
  protocol (services never import the adapter module path except at the
  composition root).

## Examples

- `tests/test_metadata_e2e.py` — full-stack offline evidence: CLI → adapter →
  ingestor → repository over the fake seam, with idempotent replay, failed-page
  cursor preservation, and legacy-sidecar absence.
- `tests/fixtures/fake_bilibili_gateway.py` — the single deterministic fake
  package seam with scripted calls, documented-call allowlist, and no-leak
  sentinels.
- `docs/metadata-storage.md` — operator-facing fresh-start workflow, exit
  tables, and the bounded live-smoke command.

## Supersedes (metadata path only)

Transcript storage and the caption acquisition boundary are documented in
`normalized-transcript-storage.md` and `subtitle-acquisition-contract.md` (promoted at
`iter-2026-09-subtitle-transcript-sqlite` close).

The metadata-path roles of `manifest.jsonl` (item state), `meta-cursor.json`
(resume cursor), and `run-ledger.jsonl` (run history) are replaced by
`archive.db` (`videos` / `video_parts` entities, `ingestion_cursors`,
`ingestion_runs`/`ingestion_pages`). Those sidecars remain the archival-flow
state machine for subtitle/audio/ASR processing — see
[operational-sidecars.md](operational-sidecars.md). No migration reader was
introduced and none is planned.

## Known limits (as shipped)

- Full-collection runs are bounded (`--limit-pages` default 10); a
  `page_limit=None` ingestor run terminates only on an upstream empty page —
  operator surfaces must keep the bound.
- Cursor state `risk_interrupted` has no producer yet (rate-limit interruption
  leaves the cursor untouched); CLI resume logic must not depend on it.
- Anonymous (no-credential) access is subject to upstream risk control at this
  egress: the corrected call shape returns `code=0` with a credential, while
  anonymous or over-large requests can be answered with HTTP 412 or JSON `-400`
  (bounded `rate_limited` / `response_error`). Happy-path collection therefore
  requires an operator credential.
- The transport itself needs two things the pinned package does not provide on
  its own (fix plan `20260911-live-metadata-path-fix`): a declared HTTP backend
  (`curl_cffi`, no transitive requirement and no extras in 17.4.2) and an
  explicit proxy on proxied hosts — the package's client builds
  `AsyncSession(proxies={"all": ""})`, which defeats `trust_env`, so
  `HTTPS_PROXY`/`ALL_PROXY` alone are ignored until the gateway applies
  `BILI_HTTP_PROXY` (or a resolved fallback) via `request_settings.set_proxy`.
- The one-page user-video call must be issued as the WBI-signed
  `GET x/space/wbi/arc/search` with `dm` disabled and `w_webid` always present
  (a non-empty `access_id` when the package can supply one, otherwise the empty
  string — the package's `User.get_videos` passes `None` and is rejected), and
  the page size is bounded to 30: `ps=30`/`ps=50` return `code=0`, `ps=100` is
  rejected (`-400`/412).
- An earlier recorded note ("anonymous access is rejected by anti-bot controls")
  was invalidated on 2026-09-11: those failures were the missing HTTP backend
  raising `ArgsException` in-process, not an upstream response.
