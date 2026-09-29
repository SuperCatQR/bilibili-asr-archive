---
plan_id: 20260928-transcript-search
iteration: iter-2026-09-ops-readiness
iteration_compass: .mstar/iterations/iter-2026-09-ops-readiness/delivery-compass.md
primary_spec: .mstar/specs/asr-archive-cli.md
blocked_by: []
qa_gate: mandatory
qa_mode: targeted
execution_mode: inline
execution_mode_reason: >-
  CORRECTED 2026-09-28. The original note claimed the host refused delegation on that session.
  That was wrong: `subagent` was available and four implementers DID run, each reporting DONE
  (they committed on their own worktrees; an early worktree check in the coordinating thread read
  "no commits yet" and wrongly concluded dispatch had failed, so the PM then re-implemented inline
  in parallel — the duplicate files later mistaken for phantom work came from those live
  implementers). The honest record: implementation was split between the dispatched implementers
  and the PM's parallel inline work on the same plans. `inline` is kept as the declared mode
  because the per-task SDD artifacts (brief/report/diff under {SDD_DIR}) are absent by
  construction — the implementer worktrees carry no `.mstar/` (gitignored) — so the SDD trail
  cannot be reconstructed from disk. The QC tri-review ran as a full N=3 read-only fan-out and is
  unaffected. For this new iteration, dispatch works and the Review chain is dispatched per spec.
status: registered
gate_decision: pass
gate_decision_reason: Prepare satisfied — retrieval is a roadmap-declared gap with no shipped code; the sealed 20260825-search-export-fts5 plan is re-scoped (compass D4), not re-opened
gate_decided_at: 2026-09-27
registered_at: 2026-09-27
planned_at_sha: main
agents:
  implementer: fullstack-dev
  task_reviewer: code-reviewer
  plan_qc: qc-specialist
  qa: qa-engineer
---

# `bili-asr search`: FTS5 retrieval over archived transcripts

> **For agentic workers:** REQUIRED SUB-SKILL: `mstar-sdd`. Checkbox syntax.
>
> **Reference.** Sealed plan `20260825-search-export-fts5` predates the SQLite cutover;
  read it for intent evidence only. This plan targets the current transcript store.
>
> **Live-code fact (architect, Phase 1 review 2026-09-28):** a first-cut FTS5 retrieval
> layer **already exists on `main`** — `src/bili_asr/search_index.py` (~890 lines;
> `check_fts5_available`, `SearchQuery`, `SearchResult`, `SearchIndex.build/search_query`,
  `search()` entrypoint) plus a wired `search` subcommand in `cli.py:3360` (`--limit`,
> `--rebuild`, `--status/--source/--language/--scope/--work-id` filters). It indexes the
> **manifest**, not the transcript store. This plan therefore re-scopes from "build FTS5
> retrieval" to **"migrate the FTS layer onto the transcript store + add pubdate
> filtering"**: extend `search_index.py` (naming-analyzer first), do not write a parallel
> `src/bili_asr/search.py`; the `search` subcommand's existing flag surface stays, and
> `--from/--to/--format` join it. DoD items below are against the migrated layer.

## Goal (intent gate)

**真实目标**：operator 能回答"他在哪期讲过 XX"——本机、可复现、带时间戳跳转。
**成功判据**：DoD。**非目标**：向量/语义检索、跨语言检索、Web UI。

## Task 1: Index builder

- [x] Migrate the existing `search_index.py` FTS5 layer (manifest-indexed today) onto the
  transcript store: `bili-asr search-index` (idempotent, incremental) builds the FTS table
  over archived transcript blocks (time-bounded segments read from the transcript store —
  prefer the store; fall back to parsing published md only if the store lacks text for older
  rows, and record which source served each row).
- [x] Tokenizer: the `simple` tokenizer plus an auxiliary CJK bigram column
  (`tokenize='simple'` + `content=` form); document the choice in the spec.
- [x] Index lives inside `archive.db` (new `transcript_fts` virtual table + a small
  bookkeeping table), rebuilt rows stamped.
- Files: `src/bili_asr/search_index.py` (extended) + migration shim (see risk resolution
  below) + tests.

## Task 2: Query command

- [x] `bili-asr search <query> [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--limit N]
  [--format {table,json}]`: returns matching blocks with bvid, part, time range, matched
  snippet (FTS5 `snippet()`), and pubdate.
- [x] Date filters join `videos.pubdate`; default limit 20; `--format json` for scripts.
- [x] Exit codes, following
  `.mstar/iterations/iter-2026-09-coverage-truth/specs/exit-code-contract.md` §1–§2
  (the two-class contract — `backlog`/`healthy` → exit 0, `defect` → exit 1, `--strict`
  promotes backlog-class to exit 1): `search` exits 0 on a healthy archive including an
  empty result set (explicit "no hits" line — pinned by test), exits 1 only on store/index
  corruption (the defect class), and uses exit 2 for usage errors. `search-index` follows
  the same shape: exit 1 only when the store is unreadable/corrupt, never merely because
  rows are missing or unindexed.
- Files: `cli.py` wiring + `tests/test_search.py`. Exit fixtures come from the canonical
  `tests/test_exit_contract.py` owned by `20260928-queue-cli-cutover` (see its Task 5 risk
  resolution) — import, do not re-define.

## Task 3: Spec + reproduction note

- [ ] The search section (index location, tokenizer rationale, rebuild semantics, exit  <!-- deferred 2026-09-28: see ## Deferred / roadmap P2.5 -->
  contract) lands in a **new** warehouse spec (see Global Constraints) — not in the frozen
  `asr-archive-cli.md`, whose README records it is never back-edited.
- [x] README one-liner + the coverage/headline note updated so the retrieval capability
  is discoverable.

### Risk resolution: FTS index on a mid-archive store, under the no-migration rule (architect, 2026-09-28)

The store's schema discipline is `CREATE … IF NOT EXISTS` + **no ALTER, no table
rebuilds** (`storage/database.py` enforces it; a predates-contract store is answered with
the fixed schema-rebuild line, not ALTERed). An FTS5 virtual table is schema-shaped, so
"new `transcript_fts` table" cannot go into `schema-transcripts.sql` — that script is
only guaranteed to run against the matching store vintage, and old stores must keep the
shape they have.

**Resolution — a gated FTS migration shim owned by `search_index.py`, invoked only from
the `search-index` command path (never from `open_database`):**

1. On `search-index`, after the normal schema contract check: `CREATE VIRTUAL TABLE IF
   NOT EXISTS transcript_fts …` (+ the bookkeeping table, same IF NOT EXISTS form).
2. Gate on `fts5` availability (`check_fts5_available`, already in the module) — a build
   without FTS5 skips the migration and `search` keeps its existing FTS5-unavailable
   exit path.
3. Baseline stores predate `user_version`; bumping it would be invented state — no
   version bump, the virtual table's own existence is the state, and idempotent
   re-`CREATE` is a no-op.
4. Read paths (`search` query) never auto-create: a missing `transcript_fts` is the
   backlog class (empty "no hits" + a one-line "index missing — run search-index" hint,
   exit 0), never a defect. This is exactly the §1–§2 exit contract applied to the index.
5. Table locks stay inside one transaction per batch; WAL already on — no exclusive
   lock is taken beyond it.

## Global Constraints

- Index build must be resumable and safe on a store mid-archive (no table locks beyond
  the transaction; WAL mode already on) — mechanics pinned by the risk resolution above.
- Query path is read-only against the store except the index table.
- New names via `naming-analyzer`.
- No network in any path.
- Contract home (architect, 2026-09-28): search index location + tokenizer rationale +
  rebuild semantics go into a **new** warehouse spec `{SPECS_DIR}/transcript-search.md`
  at implementation time (written by this plan's Task 3, via PM change-control —
  `.mstar/specs/README.md` records that `asr-archive-cli.md` is frozen and never
  back-edited). Exit-contract wording cites
  `iter-2026-09-coverage-truth/specs/exit-code-contract.md` §1–§2 verbatim, no local
  restatement beyond it.

## Definition of Done

1. `search-index` on a fixture archive with 3 parts yields a queryable FTS table;
   re-running changes nothing (idempotence pinned).
2. `search` finds a phrase known to exist in exactly one block, with correct bvid +
   time range; pubdate filters exclude out-of-window hits.
3. Exit contract pinned by tests (via the shared exit-contract fixtures); new spec
   `{SPECS_DIR}/transcript-search.md` + README updated.
4. Corpus-scale smoke: the operator's headline corpus query (a known phrase) returns the
   same bvid set as the manual grep audit recorded in the plan's `## Smoke evidence`.

## Verification

- Fixture tests (synthetic archive.db with 3 parts, known phrase placements incl. a
  CJK phrase crossing a block boundary).
- The smoke evidence section is filled from the real corpus before Task 3 lands.
