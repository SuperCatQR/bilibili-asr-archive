---
report_kind: qc
reviewer: qc-specialist-2
reviewer_index: 2
plan_id: "20260824-cursor-based-resume"
verdict: "Request Changes"
generated_at: "2026-08-24"
---

# Code Review Report

## Reviewer Metadata
- Reviewer: @qc-specialist-2
- Runtime Agent ID: qc-specialist-2
- Runtime Model: grok-4.6
- Review Perspective: Security and correctness risk
- Report Timestamp: 2026-08-24T23:45:00Z

## Scope
- plan_id: `20260824-cursor-based-resume`
- Review range / Diff basis: `361530d0a4da34de93bb86c778d1efbe061500c4..ef21ddeb4f8bc65d01c7c0827b219873fc661e6a` / merge-base vs plan HEAD (plan 002 start `361530d` → HEAD `ef21dde`)
- Working branch (verified): `plan/20260824-cursor-based-resume`
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260824-cursor-based-resume`
- Files reviewed: 5 (README.md, bili_client.py, cli.py, meta_cursor.py, test_meta_cursor.py)
- Commit range: `361530d0a4da34de93bb86c778d1efbe061500c4..ef21ddeb4f8bc65d01c7c0827b219873fc661e6a` (HEAD `ef21dde`)
- Analysis methods: git-diff, read, grep; deep-lens: Security Lens, Correctness Lens, Bounds Lens, Real-Entry-Path Lens
- Deep review: triggered (S1: 634 insertions / 5 files, S6: cli + bili_client + meta_cursor)
- Lenses applied: Security Lens, Correctness Lens, Bounds Lens, Real-Entry-Path Lens
- PM pytest note (not re-run): 162 passed on `ef21dde`

## Findings
### 🔴 Critical
- None

### 🟡 Warning
- [F-001] `--resume` never persists JSONL or cursor after a successful page; only the exception path and the terminal success path write. Spec (`meta-cursor.md` writers / advance rule) and README claim a write after each successful archive-list page merge. A crash mid-resume leaves `state=risk_interrupted` at the old `next_page` and drops in-memory pages (re-fetchable, but the documented crash-safety contract is not met).
  - Source Type: deep-lens: Correctness Lens
  - Verification: diff/read/grep anchor (`cli.py` `_after_successful_page`: `if args.resume or not client.pages_fetched: return`; `on_page` wiring in `fetch_pages`; README “after each successful archive-list page merge”)
  - Expected vs observed: expected `--resume` to merge JSONL and advance/keep cursor after each successful `pn` vs observed early-return that skips persist until exit 0 or exit 2
  - Confidence: High
  - Fix: Persist partial JSONL on every successful page for both resume and non-resume; advance `next_page` only after that merge (keep `risk_interrupted` until a true terminal `complete`/`limited`).

- [F-002] `max_pages` is still compared to absolute `pn` (`if max_pages is not None and pn > max_pages`) after `start_page` was added. CLI help and README describe `--limit-pages` as “stop after N pages”. Combined with `--resume` this is wrong: `--resume` from `next_page=5` plus `--limit-pages 2` fetches page 5 then stops (`6 > 2`), not two pages. A start `pn` already greater than N still performs one request, then stops.
  - Source Type: deep-lens: Correctness Lens
  - Verification: diff/read/grep anchor (`bili_client.py` `fetch_pages` loop; `cli.py` `max_pages=args.limit_pages`; parser help “Stop after N pages”)
  - Expected vs observed: expected a per-run page budget (or documented last-`pn` semantics) vs observed leftover start-at-1 comparison
  - Confidence: High
  - Fix: Count pages fetched this call (`fetched >= max_pages`) or document and test `--limit-pages` as max `pn`, including resume.

### 🟢 Suggestion
- [F-003] Without `--resume`, the first successful page persists `state=limited` (or `complete`) so leftover `risk_interrupted` is not auto-consumed. That matches the spec’s “never persist `running`” constraint, but a SIGKILL after page 1 of an uncapped crawl leaves a `limited` sidecar that `--resume` will not continue. Acceptable if intentional; worth a README sentence that only exit-2 `risk_interrupted` is auto-resumable after a crash.
  - Source Type: deep-lens: Correctness Lens
  - Verification: diff/read/grep anchor (`cli.py` `_after_successful_page` `_persist_cursor(..., state="complete" if client.enumeration_complete else "limited")`; spec `--resume` table)
  - Expected vs observed: expected in-progress crash not to look like an intentional limit vs observed first-page `limited` write
  - Confidence: Medium

### ⚪ Unconfirmed
- None

## Source Trace
- Finding ID: F-001
- Source Type: deep-lens: Correctness Lens
- Source Reference: `bilibili-asr-archive/src/bili_asr/cli.py` `_after_successful_page` resume early-return; spec `meta-cursor.md` advance rule
- Confidence: High
- Note: F-002 same files `fetch_pages` / `--limit-pages`; F-003 first-page `limited` replace

## Checklist (diff/read)
- Inputs / resume mid match / `next_page >= 1`: covered in `MetaCursorStore._validate` and `resume_start_page`
- No cookie / SESSDATA / URL / Traceback in sidecar: extra keys stripped; `_FORBIDDEN_MARKERS` + length cap on string codes; CLI persist only schema scalars
- `BiliClient` does not import `meta_cursor`: confirmed in source + test
- Atomic replace: same-dir `.tmp` + `os.replace`
- `state=running` cannot be flushed: `_validate` raises
- Real entry path: CLI tests call `main(["fetch-meta", ...])` rather than a hand-mounted store only
- Unexpected `Exception` path stays exit 1 with redacted “unexpected error” (no traceback)

## Summary
| Severity | Count |
|----------|-------|
| 🔴 Critical | 0 |
| 🟡 Warning | 2 |
| 🟢 Suggestion | 1 |
| ⚪ Unconfirmed | 0 |

**Verdict**: Request Changes

Needs L4/QA verification: full pytest already cited by PM on `ef21dde` (do not re-run here). After fix, targeted tests for (1) `--resume` per-page JSONL/cursor persist under a mid-run abort, and (2) `--resume --limit-pages N` page count vs absolute `pn`.
