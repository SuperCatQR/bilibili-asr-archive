# QC Consolidated — 20260909-bilibili-api-ingestion

- Iteration: `iter-2026-09-bilibili-api-sqlite` · Plan: `20260909-bilibili-api-ingestion` (SDD, Batch 2)
- Review range / Diff basis: `e62280a..783986a` (4 commits: dfb66ba, 0c2c379, 6359e7d, 783986a)
- Working branch (verified by all seats): `feature/20260909-bilibili-api-ingestion`, HEAD `783986a`, worktree clean
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260909-bilibili-api-ingestion`
- Seats: `qc-specialist` (qc1.md), `qc-specialist-2` (qc2.md), `qc-specialist-3` (qc3.md) — initial tri wave, N=3, same assignment scope
- Findings cleanup: `zero-residual`

## Seat verdicts (initial wave)

| Seat | Verdict | 🔴 Critical | 🟡 Warning | 🟢 Suggestion | ⚪ Unconfirmed |
|------|---------|-------------|------------|----------------|-----------------|
| qc-specialist (qc1) | Unconfirmed | 0 | 0 | 3 | 3 |
| qc-specialist-2 (qc2) | Request Changes | 0 | 1 | 6 | 4 |
| qc-specialist-3 (qc3) | Approve | 0 | 0 | 10 | 3 |

## Gate decision: **Request Changes** (fix wave required)

Zero Critical across all seats. One distinct Warning after cross-seat dedup (seat-2 W-001 =
seat-1 F-002: the bvid boundary asymmetry). Seat-1's Unconfirmed verdict is a template-rule
effect: its own diff-review evidence channels were fully intact and its three ⚪ items are the
PM-pre-dispositioned runtime-evidence routings owned by the immediate mandatory QA gate (not
defects) — the gate cannot be Approve until the fix wave closes the Warning AND the QA gate
closes the routed evidence. All three seats independently verified the branch clean on the
whole-branch constraints (import boundary, locked-order composition of Plan-1 canonical forms
with storage zero-diff, D1/D2/D3 invariants incl. D3 end-to-end, honest outcome taxonomy incl.
the empty-page-at-limit edge, byte-for-byte cursor preservation, no STOP condition triggered).

## Consolidated Warning (deduped; traceable to qcN findings)

| ID | Finding (trigger → impact) | Sources | Fix |
|----|----------------------------|---------|-----|
| W1 | bvid boundary asymmetry: summary normalization accepts any non-empty `bvid` (`bilibili_api_gateway.py:123-125`, no BV pattern), but `get_video_parts` raises raw `ValueError` BEFORE `_await_upstream` (`:272-273`); ingestor catches only `GatewayError` (`metadata_ingest.py:241`) → an upstream shape defect on an aid-carrying summary escapes unbounded: run stuck `outcome='running'`, zero page/run-failure evidence, no `IngestionRunResult`; classification asymmetric (same malformed bvid on an aid-less summary is bounded via `get_info`) | qc2 W-001 (W) · qc1 F-002 (S) | Enforce `_BVID_PATTERN` at `_normalize_video_summary_item` → `GatewayShapeError` (one-line fix) + tests: malformed-bvid summary page bounded on BOTH aid paths; downstream all-bounded |

## Suggestions (disposition — zero-residual)

**Fix now (this wave; seat-3 guidance: fold into the round that opens):**
- S-fix-1: dead/unused imports sweep across the branch — `tests/test_metadata_ingest.py` (`sqlite3`, pre-existing dead `GatewayShapeError`), `tests/test_bilibili_api_gateway.py` (`FakeApiException`), `services/metadata_ingest.py` (`UserVideoPage`); plus the recurring dead params/locals flagged by L2 (test `_page` helper `owner_mid` param + misleading docstring, unused `first` locals).
- S-fix-2: unreachable `except GatewayError: raise` in `_await_upstream` (`bilibili_api_gateway.py:335`).
- S-fix-3: duplicate aid-less summaries trigger duplicate `get_completed_video_summary` calls (qc2 S-001) — dedup completions the way parts fetches are deduped + test.
- S-fix-4: `_complete_summary_from_detail` checks detail owner-mid but never `detail.bvid == summary.bvid` (qc2 S-005) — identity anchor + test.
- S-fix-5: pin within-page duplicate-discovery behavior (keeps LAST `source_position`, qc2 S-002) with a test (document current flavor).
- S-fix-6: make the installed-vs-pinned `get_package_version` test distinguishable (mock the installed distribution with a DIFFERENT version string and assert precedence; qc1/qc3 recurring note).
- S-fix-7: add one ingestor-level test for a parts-stage failure (qc3 F-002; fixture already supports scripting it).
- S-fix-8: close the unclosed `:memory:` test connections (qc3).

**Accepted with rationale (no code):** prefix-based `assert_only_documented_metadata_calls` (seam constructs the call strings — negligible exposure, qc1/qc3); `bilivideo.com` hygiene-token false-positive edge (qc3); Task-1 error-mapping discretion rows (sound decisions, qc1); Task-2 Minor 2/3 cosmetics (qc1).

**Accepted as bounded design limits (both requesters recommend accept):** dangling-`running`-run windows (non-gateway exception after `start_run`; two-transaction finish shapes) — resumability and cursor integrity hold; no plan criterion requires terminal rows under abnormal termination; a storage-side fix would breach the verified storage-unmodified property → carried to Batch 3 (qc1 F-001 adjudication · qc2 S-006).

**Carried to Batch 3 (durable roadmap, not this plan's code):**
- C1: `page_limit=None` full-collection runs terminate only on an upstream empty page (qc3 F-001) → Plan-3 CLI must bound full-collection runs by default (or an `observed_total` defensive stop).
- C2: Plan-3 CLI must surface stale `running` runs in `runs` output and sweep non-terminal rows (qc1 F-001 carry · qc2 S-006).
- C3: cursor state `risk_interrupted` has NO producer in this branch — cursor stays byte-for-byte untouched on rate-limit interruption (spec-compliant); Plan-3 CLI resume logic must not depend on `risk_interrupted` cursor state; accept-vs-flip decided there (qc2 S-003).
- C4: `display_name = str(mid)` — a real label requires a future gateway capability decision (qc1 contract note).
- C5: non-gateway-exception → exit-taxonomy mapping unspecified — Batch-3 Task 1 specifies it (qc1 F-001 carry-forward).
- C6: adapter wiring notes for Batch 3: import from `bili_asr.sources.bilibili_api_gateway` (deliberately NOT package-re-exported); `--sessdata`/`BILI_SESSDATA` → `BilibiliApiGateway(sessdata=...)` (qc3 handoff).

## ⚪ Unconfirmed (→ mandatory QA gate; pre-dispositioned routings, consistent across seats)

- U1: full-suite pass counts implementer-reported (122 focused +1 skipped; 848 full +1 skipped) → QA re-runs both.
- U2: `uv.lock` reproducibility → QA re-runs `uv lock --check` (static lock consistency already diff-verified: new lock pins 17.4.2 from PyPI, no path deps, pyproject adds exactly one line).
- U3: live smoke NOT executed (opt-in; `BILI_LIVE_SMOKE=1`, one page, tmp SQLite DB, UID 23191782, no credential; skip path + `783986a` loud-fail guard verified statically) → Plan 3 / QA owns the run; the pinned dist is not installed in the control interpreter (`uv sync` first).
- U4: real-wheel response-shape claims (inner arc/search `data` shape; `get_pages` makes no internal `get_info`; exception hierarchy) mirrored from implementer wheel inspection → one-shot wheel inspection or the live smoke falsifies quickly.

## Verdict math

Gate = Request Changes: Approve requires every seat's unresolved Critical=0 AND Warning=0
AND no Unconfirmed verdict; seat 2 carries unresolved W1 and seat 1 is Unconfirmed. No
channel failures in any seat's own review scope. Fix wave next: one dispatch carrying W1 +
S-fix-1…8; targeted re-review by the seats that raised blocking/routed findings
(`qc-specialist`, `qc-specialist-2` — N=2, in-place `## Revalidation` in qc1.md / qc2.md);
then the mandatory QA gate closes U1–U4 before the gate can be Approve.

## Revalidation round (targeted, N=2: qc-specialist + qc-specialist-2)

Fix wave landed as commit `3dcc51b` (`783986a..3dcc51b`, 4 files, +278/−30; storage /
pyproject / uv.lock untouched; live smoke still opt-in-skipped; TDD red 7 failed →
focused 131 passed +1 skipped, full 857 +1 skipped — implementer-reported). Both
re-reviewing seats re-derived their evidence from the diff and post-fix source:

- qc-specialist (qc1.md `## Revalidation`): **W1 (= its F-002) RESOLVED** — same
  `_BVID_PATTERN` object at both boundaries, both aid paths symmetric, ingestor e2e pins
  run `failed`/`shape_error` + terminal run row + byte-for-byte cursor + malformed id never
  reaching parts/detail; all eight fold-ins landed; regression lens clean (no
  storage/pyproject/uv.lock hunks; D1/D3 untouched; disclosed fixture adjustments sound).
  Verdict maintained **Unconfirmed** solely per the template rule on its three ⚪ routed
  items — with the explicit statement that once the QA gate closes U1–U4 the seat has no
  remaining objection to plan-level Approve.
- qc-specialist-2 (qc2.md `## Revalidation`): **W-001 RESOLVED** (re-derived, not trusted)
  — identical pattern expression at both boundaries; normalization now also covers
  whitespace-padded bvids the old check accepted; ingestor catches `GatewayError` →
  `failed`/`shape_error` with atomic run finish; e2e test pins every consolidated
  prescription item. All six suggestions dispositioned per table. Verdict flipped to
  **Approve** (0C/0W/0 open S; 4 ⚪ QA-routed; U4 surface extended by the
  `detail["bvid"]` real-wheel dependency from S-fix-4).

## Final gate decision: **QC converged — Approve conditional on the mandatory QA gate**

- Defect state after convergence: zero unresolved Critical/Warning/Suggestion across all
  seats (seat 2 Approve with W resolved; seat 1 no open defects — Unconfirmed solely on
  routed-evidence template rule with stated no-objection; seat 3 Approve initial, findings
  all dispositioned).
- Per the consolidated verdict math the plan-level gate Approve is issued **after** the
  mandatory QA gate closes the routed evidence with fresh L4 runs:
  U1 full-suite + focused re-run at the post-fix baseline (131 focused +1 skipped; 857
  full +1 skipped), U2 `uv lock --check` no-op, U3 live-smoke execution (`BILI_LIVE_SMOKE=1`,
  one page, tmp SQLite DB, UID 23191782; `uv sync` first to install the pinned dist), U4
  real-wheel shape inspection including `get_info`'s top-level `bvid` (extended by S-fix-4).
- Zero open residual R# (`zero-residual` satisfied); Batch-3 carries C1–C6 recorded in the
  plan's Durable Roadmap.
- Final reviewed head: `3dcc51b` on `feature/20260909-bilibili-api-ingestion`; cumulative
  plan branch `e62280a..3dcc51b` (5 commits).
