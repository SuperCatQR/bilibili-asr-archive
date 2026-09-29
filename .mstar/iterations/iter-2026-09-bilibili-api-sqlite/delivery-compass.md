---
iteration_id: iter-2026-09-bilibili-api-sqlite
title: "Replace metadata acquisition with bilibili-api and normalized SQLite storage"
start_date: 2026-09-09
status: completed
end_date: 2026-09-10
iteration_base_branch: main
spec_integration_branch: iteration/iter-2026-09-bilibili-api-sqlite
target_branch: main
plans:
  - 20260909-structured-metadata-schema
  - 20260909-bilibili-api-ingestion
  - 20260909-metadata-cli-smoke
effort_scale: M
---

# iter-2026-09-bilibili-api-sqlite Delivery Compass

## Direction Lock

The iteration replaces the metadata acquisition path in place. It does not migrate
existing JSONL archives and does not introduce a parallel `v2` runtime. The new
metadata path uses the documented `bilibili-api-python` package behind a local
gateway and writes normalized records to SQLite.

## Product Problem and User Value

The current package describes metadata acquisition as a JSONL manifest plus cursor
and run sidecars. That shape makes the new metadata path harder to reason about:
identity, multipart structure, resumability, and run outcomes are not one
queryable contract, and an operator cannot distinguish a bounded collection from
an actually complete one using the new database path.

This iteration gives the personal archive operator one fresh, inspectable metadata
store and one stable application boundary. A normalized SQLite database makes
users, videos, parts, runs, page outcomes, and cursors queryable; a typed gateway
contains upstream-library churn; and bounded page evidence makes retries and
partial collection honest. The value is a safe foundation for later transcript
work, not a claim that media or ASR coverage is complete.

### Target users and outcome

- **Primary user:** the owner/operator of the personal archive running `bili-asr`
  against a selected Bilibili user and archive root.
- **Maintainer:** the developer extending the archive with subtitle, audio, and ASR
  slices after this iteration's contracts are accepted.
- **Successful outcome:** a new operator can start from a fresh archive root,
  collect bounded metadata, resume from the SQLite cursor, inspect status and run
  evidence, and understand exactly what was or was not collected without reading
  legacy sidecars or exposing credentials.

### Locked decisions

1. **Replacement boundary**: Replace the existing metadata path in place. No JSONL
   compatibility mode; the new CLI writes only to SQLite.
2. **Iteration scope**: Metadata acquisition (user/video/parts) and structured
   storage only. Subtitle download, audio, ASR execution, transcript writes, and
   export are explicitly out of scope for this iteration.
3. **Storage boundary**: SQLite owns normalized metadata, ingestion state, cursors,
   and future media/transcript foreign keys. Audio files remain external immutable
   objects. Raw API response JSON is never stored.
4. **Normalization**: Schema satisfies 3NF. No duplicate derived values (part counts,
   `work_id`, run aggregates). Views and application code compute derived facts.
   Duration conversion uses `floor(seconds * 1000)`. Page-index normalization uses
   `page - 1` from one-based API values. Ingestion evidence tracks one-based
   `page_number` (API request) separately from zero-based `page_index` (entity key).
5. **Metadata retention**: Store stable identifiers (BVIDs, AIDs, CIDs, MIDs) and
   the current display labels (titles, names) needed to operate the archive. Do not
   store historical snapshots of mutable fields like view counts, descriptions, or
   old titles. Upserts overwrite display labels; this is operational state, not a
   historical metadata warehouse.
6. **Ingestion reliability**: Cursors, run outcomes, and page results live in SQLite.
   No metadata sidecars (`meta-cursor.json`, `run-ledger.jsonl`) for the new path.
7. **API boundary**: Pin `bilibili-api-python==17.4.2` with `uv.lock`. Only the
   gateway module imports `bilibili_api`; services consume typed DTOs.
8. **Credential boundary**: Accept optional `BILI_SESSDATA` from environment or CLI
   flag. Never persist, log, or display credentials, signed URLs, or raw stack traces.
9. **Verification**: Offline fake-gateway tests prove schema/idempotency contracts.
   One opt-in live smoke run collects at most one public metadata page for UID
   23191782 into a temporary database. No subtitle/playback/audio/ASR calls.
10. **Delivery branches**: Base `main`, integration
    `iteration/iter-2026-09-bilibili-api-sqlite`, PR target `main`.

## Scope

### In scope

- A new 3NF SQLite schema for Bilibili users, videos, video parts, ingestion runs,
  cursors, page outcomes, and future media/transcript references.
- A database repository with explicit transactions, foreign keys, constraints,
  idempotent upserts, cursor persistence, and query methods for metadata work.
- A `BilibiliGateway` adapter around the documented `bilibili-api-python` APIs:
  `user.User.get_videos`, `video.Video.get_info`, and `video.Video.get_pages`.
- Normalization from gateway DTOs into database records without storing raw API JSON.
- In-place replacement of the metadata behavior behind the existing `bili-asr`
  executable with the SQLite-backed `fetch-meta`, `status`, and `runs` commands;
  no second executable or compatibility `v2` path.
- Fake-gateway tests and an opt-in, one-page live API smoke test.
- Dependency pinning, configuration documentation, and removal/disconnection of
  metadata-sidecar runtime behavior from the new entry path.

### Out of scope

- Migration or import of existing `archive/manifest/manifest.jsonl` data.
- Subtitle probing/downloading and subtitle segment persistence implementation.
- Audio download, audio blob publication, retention policy, or media reprocessing.
- ASR execution (FunASR-Nano or SenseVoice), transcript segment persistence, or
  model versioning implementation; the schema may reserve these boundaries for the
  next iteration.
- Web UI, vector search, cloud object storage, and multi-user authentication.
- Automatic installation of ROCm, PyTorch, or third-party system dependencies.
- Corpus-wide completeness, transcript quality, and media availability claims.

## User-facing CLI Contract

The replacement keeps the existing `bili-asr` executable but narrows this
iteration's supported metadata surface to three commands:

- **`bili-asr fetch-meta`**: Collects video metadata from Bilibili and writes to
  `{archive_root}/archive.db`. Operators supply `--mid` (user ID, defaults to
  `23191782`), `--archive-root` (defaults to `archive`), optional `--start-page`
  (explicit one-based page to start from), optional `--limit-pages` (stop after
  this many pages), and optional `--sessdata` (never persisted). The command
  resumes from the database cursor when no page override is given, or starts at
  page 1 for a fresh database. Pass `--resume` to explicitly require cursor
  presence; it fails if no cursor exists. Never reads or writes legacy JSONL
  sidecars.

- **`bili-asr status`**: Reads the database and reports how many videos/parts
  are discovered, how many need further processing, and what ingestion work is
  pending. Fails clearly if the database does not exist.

- **`bili-asr runs`**: Shows ingestion run history from the database with start
  times, page counts, and outcome codes (no raw errors or credentials). Optional
  `--limit` shows only the N most recent runs.

**Exit codes** (observable, three-value taxonomy):
- **0**: Successful metadata collection (reached end or explicit page limit) or
  successful read command. Does not claim subtitle, audio, ASR, or transcript
  coverage.
- **1**: Usage error (bad arguments, missing database for read commands).
- **2**: Metadata gateway failed after bounded retry; cursor remains unchanged.

A failed page never advances the cursor, ensuring safe resume.

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| 20260909-structured-metadata-schema | 3NF metadata schema and SQLite repository | Done | Foundational; blocks the gateway and CLI plans. 3 tasks + 2 QC fix waves (14590a3, 5f22fc6, bf602b8, ff81140, 6d76ea4, 2063a1a); QC tri N=3 converged Approve; QA gate Approve (33 focused / 726 full; wheel+sdist ship schema.sql); merged bf8892b |
| 20260909-bilibili-api-ingestion | bilibili-api gateway and normalized ingestion | Done | Sequential; blocked by schema/repository (Done). 3 tasks + QC fix wave (dfb66ba, 0c2c379, 6359e7d, 783986a, 3dcc51b); QC tri N=3 converged; QA gate Approve (131 focused +1 skip / 857 full +1 skip; uv lock --check no-op; live smoke executed — bounded response_error under anonymous access, happy path via Batch 3 SESSDATA CLI); merged 5ccc9c8 |
| 20260909-metadata-cli-smoke | SQLite-backed metadata CLI and verification | Done | Sequential; blocked by gateway/ingestion (Done). 3 tasks + docs fix wave (849c046, cf490ff, c86daa7, 1a99751; PM-edited spec exit-code section); QC tri N=3 converged; QA gate Approve (861+2 / 38+1 fresh; isolated-install verified; anonymous live bounded-failure executed live; credential happy path = explicit blocker, BILI_SESSDATA unset); merged 1307f92 |

Status values: `Todo` | `InProgress` | `InReview` | `Done` | `Blocked`

### Plan handoff contract

- **Plan 1 → Plan 2:** the schema plan freezes the 3NF tables, repository
  transactions, cursor/page semantics, and typed internal records. Plan 2 may not
  add an API adapter before that repository evidence passes its task review, QC,
  and mandatory QA gate.
- **Plan 2 → Plan 3:** the gateway plan freezes DTO normalization, bounded error
  codes, one-page ingestion, and cursor advancement. It owns offline package-seam
  evidence; Plan 3 owns the CLI E2E and the sole opt-in live smoke.
- **Plan 3 → iteration close:** the CLI plan proves the user-facing replacement
  (`fetch-meta`, `status`, `runs`), fake-gateway E2E, and bounded live evidence or a
  documented live-network blocker. No plan may claim subtitle, audio, ASR,
  transcript, export, or corpus-coverage completion.

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Spec freeze | 2026-09-09 | pending |
| Dev complete | 2026-09-10 | pending |
| QC complete | 2026-09-10 | pending |
| Iteration close | 2026-09-10 | pending |

## Acceptance Criteria

- The fresh schema has the declared tables, foreign keys with `ON DELETE RESTRICT`,
  uniqueness/check constraints, and views; contract checks show no duplicated
  canonical or derived facts such as `work_id`, part counts, or run counts in base
  tables. Reserved media/transcript tables remain empty schema boundaries with
  explicit FK relationships to `video_parts`, `audio_objects`, and `asr_models`.
- A fresh archive database can insert one user, one video, and all of its parts
  using the explicit transaction ordering (user → video → parts → discoveries →
  cursor → page outcome → commit); replaying the same run/page is idempotent for
  entities (via `INSERT ... ON CONFLICT DO UPDATE`) and discovery relations (via
  primary key uniqueness), while a deliberate new run retains its own run/page
  evidence.
- A failed page records only a bounded error code, leaves the prior cursor intact,
  and does not store cookies, signed URLs, raw responses, or raw exception text.
- The gateway is the only application boundary that imports `bilibili_api`, and
  service/repository tests run without network access.
- `bilibili-api-python==17.4.2` and its lockfile are declared; the tested API calls
  return normalized DTOs for the selected user/video/page fields.
- The existing `bili-asr fetch-meta` command writes to SQLite, not the old JSONL
  metadata manifest; `status` and `runs` read that same database; `--resume` uses
  only the DB cursor; and a missing fresh database fails clearly for read commands.
- Fake-gateway E2E tests pass. When opted in, the live smoke requests no more than
  one public metadata page for UID 23191782 into a temporary database; it calls no
  subtitle, playback, audio, or ASR path. If risk controls block the attempt, a
  bounded blocker is recorded without unbounded retries.
- Exit code `0` is limited to successful bounded collection/read commands, `1` to
  usage/configuration errors, and `2` to terminal or risk-interrupted gateway
  failure; no result claims corpus-wide or transcript completion.
- Existing old archive data is untouched; no migration, import, or compatibility
  reader is introduced.

## Non-Goals

This iteration explicitly excludes:

- **No migration**: No import, transformation, or compatibility reader for existing
  `manifest.jsonl`, `meta-cursor.json`, or `run-ledger.jsonl` files. The new
  database cursor replaces their metadata-path role. Existing archives are left
  untouched.
- **No subtitle/media/ASR pipeline**: Subtitle probing/downloading, audio
  downloading, audio retention policy, ASR execution (FunASR-Nano or SenseVoice),
  transcript segment writes, and SRT/TXT/MD export remain out of scope. Schema
  reserves foreign-key boundaries for future iterations.
- **No parallel runtime**: No second `bili-asr-v2` executable or compatibility mode.
  The existing `bili-asr` executable uses SQLite exclusively for metadata commands.
- **No raw response storage**: Third-party API responses, signed URLs, cookies, and
  raw stack traces are never persisted in the database or logged to disk.
- **No historical metadata warehouse**: Current display labels (titles, names) are
  operational values that may be overwritten on re-ingestion. No snapshot history
  of mutable upstream fields like view counts, descriptions, or old titles.
- **No completeness claims**: Successful metadata collection does not claim subtitle
  availability, audio availability, ASR coverage, transcript quality, or corpus-wide
  completeness. Exit code `0` means bounded metadata collection succeeded, not that
  every video has usable media or transcripts.

## Roadmap Position

- **Current iteration (iter-2026-09-bilibili-api-sqlite)**: **delivered** (2026-09-10).
  All three plans Done and merged into the integration branch (`bf8892b`, `5ccc9c8`,
  `1307f92`); offline fake-gateway evidence in place; the opt-in live smoke was
  executed live with the designed bounded failure under anonymous access, and the
  credential happy path is recorded as an explicit live-network blocker
  (`BILI_SESSDATA` unset on this machine) — the allowed close condition. Deferred
  operational notes ride the Batch-3 carry list (C1–C6) and the plan Durable
  Roadmaps.

- **Next iteration (subtitle/transcript)**: Add subtitle acquisition (AI/CC) and
  normalized transcript-segment storage using the reserved foreign-key boundaries.
  **Trigger**: MET — current iteration complete (all plans `Done`, acceptance
  evidence in place). **Owner**: `project-manager`. **Done when**: Subtitles and
  transcript segments are queryable through normalized tables without
  reintroducing sidecars. **Contract notes to decide explicitly in that plan**:
  the `ingestion_runs` table is metadata-scoped — the subtitle/transcript
  process-record schema decision must be explicit (plan-3 QC carry F-010), and the
  cursor state `risk_interrupted` has no producer yet (C3).

- **Subsequent iteration (audio/ASR)**: Add audio download (external objects) and
  local ASR execution (FunASR-Nano or SenseVoice). **Trigger**: Subtitle/transcript
  iteration complete. **Owner**: `project-manager`. **Done when**: Audio objects
  and ASR runs are tracked through normalized tables, and generated transcript
  segments are versioned per model/run.

- **Final vision**: A personal long-lived speech-to-text archive where all metadata,
  audio references, and transcript segments are queryable in SQLite. SRT/TXT/MD
  exports are rebuildable projections, not canonical state.

## Delivery Branch Policy

> Mirror of frontmatter; keep in sync with workflow snapshot branch anchors.

| Field | Value |
|-------|-------|
| `iteration_base_branch` | `main` |
| `spec_integration_branch` | `iteration/iter-2026-09-bilibili-api-sqlite` |
| `target_branch` | `main` |

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Third-party API response shape changes | Med | High | Pin 17.4.2, isolate it behind typed gateway DTOs, and keep fake-gateway contract tests |
| `get_videos` page semantics differ from the old manual cursor | Med | High | Persist explicit page parameters/results and verify one-page live behavior before full runs |
| SQLite schema accidentally duplicates derived facts | Low | High | Require schema review against declared functional dependencies and constraint tests |
| Existing uncommitted exploratory files contaminate the replacement | Med | Med | Review product diff before implementation; stage only planned files and remove dead prototypes deliberately |
| Live Bilibili risk control blocks smoke test | Med | Med | Bound to one page, use public metadata only, preserve no credentials, and treat blocked live smoke as an explicit evidence gap |

## Iteration package

> Sibling paths under `{ITERATION_DIR}/<iteration-id>/` — not in `{SPECS_DIR}/`
> or `{KNOWLEDGE_DIR}/`. Promoted at iteration-close via compound.

| Path | Purpose |
|------|---------|
| `guides/` | API research and review-chain notes |
| `specs/` | Iteration-scoped schema and gateway contracts |
| `README.md` | Package document index |

## Quality Gate Summary

> Filled at iteration-close. Human summary only; per-plan gate details stay in
> each main plan, and open residual SSOT stays in the project register.

| plan_id | QC decision | QA gate | Residuals | Durable summary |
|---------|-------------|---------|-----------|-----------------|
| 20260909-structured-metadata-schema | Approve (tri N=3 converged after 2 fix waves) | Approve (33 focused / 726 full; wheel+sdist ship schema.sql) | none open | `.mstar/plans/20260909-structured-metadata-schema.md#review-gate-summary` |
| 20260909-bilibili-api-ingestion | Approve (tri N=3 converged after fix wave; targeted re-review) | Approve (131 focused +1 skip / 857 full +1 skip; uv lock --check no-op; live smoke executed — bounded response_error under anonymous access) | none open | `.mstar/plans/20260909-bilibili-api-ingestion.md#review-gate-summary` |
| 20260909-metadata-cli-smoke | Approve (tri N=3 converged after docs fix wave + PM spec edit) | Approve (861 full +2 skip / 38 focused +1 skip fresh; isolated-install verified; anonymous live bounded-failure executed; credential happy path = explicit blocker) | none open | `.mstar/plans/20260909-metadata-cli-smoke.md#review-gate-summary` |

## Compound Round Summary

> Filled at iteration-close.

- 结晶文档数：1（`architecture-patterns/normalized-metadata-stack.md`——三份迭代 spec 的结构化重写，含 supersedes 注记；已登记 `{KNOWLEDGE_DIR}/README.md`）
- 新增 CONCEPTS.md 条目：0 新增；1 处漂移修正（`meta-cursor.json` 行标注 metadata 路径已被 SQLite `ingestion_cursors` 取代，sidecar 保留于 archival flow）
- Package 盘点：`guides/` ×4 = Phase-1 process 历史（keep snapshot）；`specs/` ×3 = 提升源（结构化重写进 knowledge，specs 保留为冻结记录）；`delivery-compass.md` 默认排除
- 触发 compound-refresh：无强制项；flag——`operational-sidecars.md` 与 `bilibili-asr-archive-cli.md` 中 metadata 侧描述仍描述旧 JSONL 元数据路径（正确，但下次该领域触及时建议 refresh 对照新栈）

## Iteration Retrospective (minimal)

> Filled at iteration-close.

- **交付形态**：3 plans 串行 SDD，9 实现/测试提交 + 2 个 plan-QC 修波（3 个 merge commit），零迁移、零并行可写轨。
- **门禁有效性**：每轮 plan QC（N=3）都在 plan 级别抓到了 L2 task review 未升级为阻塞的契约缺口（6W/1W+8 携带/2W 文档债），全部当轮清零；zero-residual 保持——无 open R#。
- **文档契约债教训**：operator-facing 约束（默认页界、无码 exit-2 变体）在实现时已裁定，但未同步进 spec/README/docs——三席一致以 docs-accuracy Warnings 阻塞收口。后续 plan 的 Acceptance 应把「文档与行为一致」视为可验证项。
- **运行时证据分层**：QC（diff/logic）不可证的运行时声明（pass counts、wheel 内容、live smoke）显式路由到 mandatory QA gate 闭环，避免了评审席与 QA 职责坍缩。
- **live smoke 现状**：匿名访问受上游风控限制（有界 `rate_limited`/`response_error`；2026-09-11 更正：早期「反爬拒绝」结论实为缺失 HTTP 后端导致的进程内 `ArgsException`，见 plan `20260911-live-metadata-path-fix`），credential happy path 待操作者凭证；Plan-2/3 的 CLI/文档已如实记录，不构成 blocker。

- 做得好的：pending
- 可改进的：pending
- 下迭代建议：pending

## Prepare Gate Summary

- specify: complete — user goal and product boundary are recorded above.
- clarify: complete — replacement boundary, storage boundary, metadata retention,
  ingestion history, dependency isolation, live-smoke boundary, and branch policy
  were confirmed interactively.
- plan: complete — three sequential plans below define interfaces, dependencies,
  acceptance, and the next-iteration roadmap.
- primary specs: `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/`
- blocked-by dependencies: Plan 1 → Plan 2 → Plan 3.

## Review Chain Log

- product-manager: complete (2026-09-09)
- architect: complete (2026-09-09)
- writing-specialist: complete (2026-09-09)
- PM lock: complete (2026-09-09)
- Phase 1 status: locked — ready for integration branch and Phase 2 execution

## Direction Lock Evidence

- User-confirmed replacement boundary: in-place replacement, no old-data migration.
- User-confirmed first slice: metadata and schema only.
- User-confirmed storage boundary: audio external object, structured records in SQLite.
- User-confirmed ingestion reliability: run/page/cursor history in SQLite.
- User-confirmed dependency policy: fixed `bilibili-api-python==17.4.2` behind gateway.
- User-confirmed branch policy: `main` → `iteration/iter-2026-09-bilibili-api-sqlite` → `main`.
- User-confirmed verification: fake E2E plus one-page live smoke.

## Definition of Done

This iteration is complete when:

1. **All three business plans are `Done`** (schema/repository, gateway/ingestion,
   CLI/smoke) after passing implementation, task review, QC tri-review, and
   mandatory QA gates.

2. **Offline evidence is complete**: Fake-gateway E2E tests confirm schema
   constraints, 3NF compliance, transaction atomicity, cursor resume, idempotent
   upserts, and bounded error handling without network access.

3. **Live smoke has bounded evidence**: The opt-in one-page smoke test either
   succeeds (collects one public metadata page for UID 23191782 into a temporary
   DB) or an explicit live-network blocker is documented (rate limit, risk control).
   No unbounded retry attempts.

4. **Phase 3 compound/close artifacts are complete**: Knowledge crystallization,
   roadmap updates, and retrospective are recorded in this compass.

5. **PR is merge-ready**: PR to `main` is open, required CI is green, review
   findings are resolved or explicitly registered, and the branch is mergeable.

This definition does **not** claim subtitle availability, audio availability, ASR
execution, transcript quality, export functionality, or corpus-wide completeness.
It establishes a verified metadata foundation for future iterations.

## Status Notes

- The previous workflow register contains a stale completed FunASR iteration entry
  and an invalid duplicate listing; this iteration must create a valid new workflow
  snapshot rather than reuse that ID.
- The old archive remains untouched because this iteration intentionally does not
  migrate existing data.

## Notes

- External API reference: https://nemo2011.github.io/bilibili-api/#/modules/user
- PyPI package reference: https://pypi.org/project/bilibili-api-python/
- Raw review bundles belong under `{SDD_DIR}/review/` and are not pasted here.

## Iteration Package Index

See `README.md` for the package document index.

## Plan Index

| Plan | Primary spec | Depends on |
|------|--------------|------------|
| 20260909-structured-metadata-schema | `specs/structured-metadata-storage.md` | none |
| 20260909-bilibili-api-ingestion | `specs/bilibili-api-gateway.md` | 20260909-structured-metadata-schema |
| 20260909-metadata-cli-smoke | `specs/metadata-cli-contract.md` | 20260909-bilibili-api-ingestion |

## Close Placeholder

Phase 3 will replace the pending fields above with completed quality, compound,
retrospective, and delivery evidence after every plan is Done.

## Phase 1 Review Notes Placeholder

Specialist review edits must be applied to this compass, the plan files, or the
iteration package only. No start-chain reviewer may add new files under the
shared knowledge directory.

## Plan-Dependency Gate

- Plan 1 may start immediately after PM lock.
- Plan 2 may start only after Plan 1's implementation, task review, QC, and QA
  gate are complete.
- Plan 3 may start only after Plan 2's implementation, task review, QC, and QA
  gate are complete.

## Expected Evidence Paths

- Main plans: `.mstar/plans/20260909-*.md`
- Iteration specs: `.mstar/iterations/iter-2026-09-bilibili-api-sqlite/specs/`
- Workflow snapshot: `.mstar/workflows/iter-2026-09-bilibili-api-sqlite/snapshot.json`
- Root register: `.mstar/status.json`
- SDD review bundles: `.mstar/sdd/<plan-id>/review/`

## No-Migration Declaration

This iteration creates a fresh database schema and new metadata path. It does not
read, transform, or write old `manifest.jsonl` rows, and it does not attempt to
reconcile pre-existing archive files.

## API Boundary Declaration

Only `sources/bilibili_api_gateway.py` may import `bilibili_api`. The rest of the
application consumes typed DTOs and repository methods. This is a testable boundary
and a replacement seam if the upstream package changes.

## Database Boundary Declaration

The database is the source of truth for structured metadata and ingestion process
state. Blob files are not canonical metadata records in this iteration; future
media/transcript plans must link them through normalized object/reference tables.

## End-to-End Smoke Declaration

The live smoke test is intentionally opt-in (`BILI_LIVE_SMOKE=1`) and bounded to
one public metadata page for UID 23191782 in a temporary database root. It performs
no subtitle/playback URL retrieval, audio download, or ASR, and persists no
credential. A blocked live attempt is recorded as a bounded evidence gap rather
than retried or treated as success.

## PM Self-Review

- Each plan has a single owner, explicit dependencies, interfaces, tests, and
  acceptance evidence.
- The schema plan owns database invariants; the gateway plan owns external API
  normalization; the CLI plan owns user-facing wiring and smoke verification.
- No plan relies on a placeholder implementation or on old JSONL migration.

## Phase 1 Lock Placeholder

PM will change frontmatter `status` from `active` to `locked` only after the
sequential product-manager → architect → writing-specialist review/edit chain has
returned and all review edits are visible on disk.

## User Intent Summary

The user wants a fresh structured foundation for a personal long-term Bilibili
speech-to-text archive, starting with a normalized database and replacing the data
acquisition library with the documented bilibili-api package.

## Deferred Work

The following are deliberately deferred and must not be silently pulled into this
iteration: subtitle acquisition, audio downloading/retention, ASR execution,
transcript segment writes, exports, vector search, and cloud storage.

## Phase 1 Completion Checklist

- [x] Direction lock decisions recorded
- [x] Draft compass, plans, specs, status, and indexes registered
- [x] product-manager / architect / writing-specialist review edits completed
- [x] PM final lock sets compass `status: locked`
- [x] Branch policy mirrored in compass and workflow snapshot metadata
- [ ] Only after all above: commit and push integration branch

## Next Phase Placeholder

After Phase 1 lock and integration branch creation, Phase 2 runs the three plans
serially using SDD, task review, tri-QC, and mandatory QA gates.

## Phase 1 End

This compass remains `active` until the review chain and PM lock complete.

## End

The canonical iteration state is the frontmatter, plan table, and workflow
snapshot; prose above records the shared direction and constraints.

## Appendix: Terms

- **Gateway**: typed boundary around `bilibili-api-python`.
- **Canonical metadata**: normalized current values needed to identify and process
  a Bilibili video and its parts.
- **Observation**: a page result in an ingestion run, not a historical metadata
  snapshot.
- **Blob reference**: a database row pointing to an external immutable object.

## Appendix: Future Contract

Later transcript work should insert one transcript version per processing run and
one row per segment, keeping text/time fields queryable in SQLite while treating
SRT/TXT/MD as derived projections.

## Appendix: Review Scope

Reviewers must check that the plan does not reintroduce raw API JSON, duplicate
part counts/work IDs, or create a second metadata source of truth.

## Appendix: Branch Scope

No product implementation branch is created before Phase 1 review-chain completion.

## Appendix: Evidence Hygiene

Do not put cookies, signed URLs, full response bodies, or raw stack traces in any
compass, plan, report, fixture, or database row.

## Appendix: Iteration ID Uniqueness

This ID is intentionally distinct from `iter-2026-09-funasr-nano-7800xt`, whose
legacy status entry is stale and whose snapshot path is currently unreadable by the
engine selection envelope.

## Appendix: Completion Rule

Opening a PR is not iteration completion; Phase 5 merge-ready evidence is required.

## Appendix: Start-Chain Boundary

Product and architecture reviewers may edit this package and plan/spec documents,
but may not add shared knowledge during Phase 1.

## Appendix: Stable Source

The documentation URL supplied by the user is the reference for public API names;
implementation must verify installed signatures and use a fake gateway for tests.

## Appendix: Current Working Tree

The working tree contains uncommitted exploratory prototypes from an earlier
conversation. They are not part of this iteration until a plan explicitly includes
them; implementation must stage only intended files.

## Appendix: User Confirmation Sequence

Replacement boundary, storage boundary, metadata retention, ingestion history,
dependency strategy, branch policy, and acceptance boundary were confirmed one by
one before this draft was written.

## Appendix: Plan Order

The order is deliberately serial because the gateway DTOs depend on repository
contracts and the CLI depends on both.

## Appendix: No Silent Scope Expansion

Any newly discovered requirement must be written back to the affected plan before
implementation continues.

## Appendix: End of Compass

This is the draft before specialist review; PM lock is still pending.
