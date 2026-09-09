# iter-2026-09-bilibili-api-sqlite

Fresh metadata-ingestion redesign for the Bilibili ASR archive.

## Documents

| Document | Kind | Description | Status |
|---|---|---|---|
| [delivery-compass.md](delivery-compass.md) | compass | Direction, scope, branch policy, gates, and roadmap | active |
| [specs/structured-metadata-storage.md](specs/structured-metadata-storage.md) | spec | 3NF SQLite schema and repository contract | draft |
| [specs/bilibili-api-gateway.md](specs/bilibili-api-gateway.md) | spec | Typed gateway around bilibili-api-python | draft |
| [specs/metadata-cli-contract.md](specs/metadata-cli-contract.md) | spec | SQLite-backed metadata CLI and smoke boundary | draft |
| [guides/](guides/) | guide | Review-chain and implementation notes | pending |

## Plans

| Plan | Role | Status | Depends on |
|---|---|---|---|
| [20260909-structured-metadata-schema](../../plans/20260909-structured-metadata-schema.md) | fullstack-dev | Todo | none |
| [20260909-bilibili-api-ingestion](../../plans/20260909-bilibili-api-ingestion.md) | fullstack-dev | Todo | 20260909-structured-metadata-schema |
| [20260909-metadata-cli-smoke](../../plans/20260909-metadata-cli-smoke.md) | fullstack-dev | Todo | 20260909-bilibili-api-ingestion |

## Direction

The old archive is not migrated. The new metadata path is an in-place replacement
that stores normalized entities and resumable ingestion state in a fresh SQLite
database. Audio remains a future external immutable object; future transcript
segments have a relational boundary in the schema.

## Product Problem and User Value

The current package's metadata path is built around JSONL and sidecar state. The
operator needs one fresh, queryable source of truth for Bilibili identity,
multipart structure, page outcomes, and resume state, while the maintainer needs
the upstream client isolated behind a typed seam. This package delivers that
foundation without pretending that metadata collection is transcript or corpus
completion.

For the archive owner, the value is an honest bounded workflow: start from a new
archive root, collect metadata through one gateway, resume from SQLite, inspect
`status`/`runs`, and keep credentials, raw responses, and old files out of the new
path. For future implementation plans, the value is a stable 3NF contract that
can later receive subtitle, audio, and transcript rows without reintroducing
metadata sidecars.

## Plan Ownership and Handoff

- Plan 1 owns the normalized schema, repository transactions, and offline storage
  contract evidence.
- Plan 2 owns the `bilibili-api-python` gateway, DTO normalization, and one-page
  ingestion semantics; its tests stay offline and it does not own the live smoke.
- Plan 3 owns the SQLite-backed CLI, fake-gateway E2E, and the sole opt-in,
  one-page live metadata smoke.
- The plans are strictly serial: Plan 2 consumes Plan 1's accepted repository
  contract, and Plan 3 consumes Plan 2's accepted gateway/ingestor contract.

## External references

- API documentation supplied by the user:
  https://nemo2011.github.io/bilibili-api/#/modules/user
- Package index:
  https://pypi.org/project/bilibili-api-python/

## Phase 1 boundary

This package is an iteration-scoped draft until product-manager, architect, and
writing-specialist review/edit invokes return. No shared knowledge directory is
modified by the start-chain.

## Metadata command boundary

The iteration keeps the existing `bili-asr` executable but replaces its metadata
path in place. The exact command contract is defined in
[`specs/metadata-cli-contract.md`](specs/metadata-cli-contract.md):

- `bili-asr fetch-meta` creates or updates `{archive-root}/archive.db` using the
  typed gateway and normalized repository. It accepts `--mid`, `--archive-root`,
  `--start-page`, `--limit-pages`, optional `--resume`, and optional `--sessdata`.
- `--resume` is an explicit DB-cursor selection and is mutually exclusive with
  `--start-page`; omitting both uses the persisted DB cursor or starts at page 1.
  No command in this path reads or writes `manifest.jsonl`, `meta-cursor.json`, or
  `run-ledger.jsonl`.
- `bili-asr status` and `bili-asr runs` read that same database and do not read
  legacy sidecars. `runs` may take a positive display `--limit`.
- Successful bounded collection (`complete` or `limited`) and successful reads exit
  `0`; usage/configuration errors exit `1`; terminal or risk-interrupted gateway
  failures exit `2`.
- `--sessdata` and `BILI_SESSDATA` are optional credential inputs only; values are
  never echoed, logged, persisted, or included in fixtures or examples.
- There is no second executable and no compatibility `v2` metadata path. The new
  database cursor is the only resume state for this entry path.

## No-migration declaration

No plan in this package reads, transforms, deletes, or rewrites the old manifest,
cursor, ledger, audio, or transcript files. A new run starts from a fresh SQLite
archive root; existing archive data remains untouched.

## Verification boundary

Offline fake-gateway E2E tests are mandatory. The opt-in live test is limited to
one public metadata page for UID 23191782 and a temporary database, with no
subtitle, playback, audio, or ASR calls. If environment or Bilibili risk controls
block the live attempt, the run records a bounded blocker rather than retrying or
claiming success. Neither tests nor operator evidence may contain credentials,
signed URLs, raw API responses, or raw exception text.

## Status

Phase 1 draft; PM lock pending.

## End

The delivery compass and plan files are the canonical iteration preparation
surface; runtime review bundles will live under the corresponding SDD directories.
