# Compound report — iter-2026-10-ledger-integrity

Architect (leaf), compound round run per `mstar-compound`. Scope: knowledge promotion + index registration
only; no product source, compass, plan, or SDD report was edited. Delivery head of the iteration:
`ec9d3d2` (integration branch `iteration/iter-2026-10-ledger-integrity`; four plans merged).

## Result

| # | Deliverable | Path | Action |
|---|-------------|------|--------|
| 1 | Reachability is measured, not argued | `.mstar/knowledge/best-practices/reachability-delta-not-asserted.md` | **new** |
| 2 | Cross-plan premise collision | `.mstar/knowledge/testing-patterns/cross-plan-premise-collision.md` | **new** |
| 3 | Journal ledger & projection replay | `.mstar/knowledge/architecture-patterns/journal-ledger-and-projection-replay.md` | updated (3 sections) |
| 4 | Operational sidecars | `.mstar/knowledge/architecture-patterns/operational-sidecars.md` | updated (1 section) |
| 5 | Absence assertion & negative control | `.mstar/knowledge/testing-patterns/absence-assertion-negative-control.md` | updated (1 section) |
| 6 | Claim-scope discipline | `.mstar/knowledge/best-practices/claim-scope-discipline.md` | updated (1 section) |
| 7 | venv editable `.pth` hides the tree under test | `.mstar/knowledge/testing-patterns/venv-editable-pth-hides-tree-under-test.md` | updated (container notes) |

- New documents: **2**. Updated documents: **5**.
- CONCEPTS.md entries added: **1** (`manifest journal` — journal, fold, torn fragment, stranded record).
- Catalog (Phase 6): both new docs registered `kind=document` / `document_kind=knowledge` / `lifecycle=active`
  and linked to the iteration (`documents`); completeness check returns 0 knowledge files without a catalog row.
- `compound-refresh` triggered: **no** (live knowledge; one corrected residual clause inside the refreshed doc).
- Phase 4 discoverability: root `AGENTS.md` and `.mstar/AGENTS.md` already surface `{KNOWLEDGE_DIR}` — no edit.

## Overlap decisions (Phase 2)

| Candidate | Extraction decision | Why |
|---|---|---|
| Reachability delta + finding-attribution refutation | **new `best-practices/` doc** | No owner: `pairing-rule-travels-with-behaviour.md` covers "re-check in newly enabled configurations" but not frequency/actor/depth or a falsified attribution |
| Cross-plan test-premise collision | **new `testing-patterns/` doc** | `absence-assertion-negative-control.md` is about one fixture's reachability; this is the between-iteration dimension. Cross-linked |
| Torn fragment / strand settlement + file-based fold trigger | **update** `journal-ledger-and-projection-replay.md` | High overlap (module, mechanism, residual list); a new doc would duplicate it |
| Fold discard invariant owned by one helper | **folded into the same update** (`_remove_journal` is that file's own method) | Reviewer-detectable code structure, not a standalone pattern |
| Loud scope-wide write-back skip + unusable-stderr failure set | **update** `operational-sidecars.md` | Adjacent to its stderr diagnostics contract and the attempt-ledger boundary |
| Recoverability vs artifact existence; fixture-fitted bound | **update** `absence-assertion-negative-control.md` | Exactly its class |
| Two-halves honest contract; amendment beside a falsified sentence | **update** `claim-scope-discipline.md` | Exactly its class |
| Repo/environment specifics (nested package root, `python3`, scratch pytest, `"\n"` split rule) | **splits**: `"\n"` rule → journal pattern; container notes → `venv-editable-pth…` | Environment facts are rediscoverable; the non-obvious half was placed with its mechanism |

## Candidates skipped, with reason

- **`migrate_legacy_rows` durable-deletion (I-000195) as a bug-track doc.** The *fix* is a normal base-view
  correction; the durable lesson is the refuted attribution + the retroactive reachability of a pre-existing
  defect, both captured in doc 1. A second document would duplicate it.
- **`time.time_ns()` vs `int(time.time())` as a standalone lesson.** Rediscoverable from code and slightly
  mis-stated when generalised (`time_ns()` is not a uniqueness guarantee; zero equal reads in 200 k is a
  measurement, not a proof). The one durable claim — the diagnostic's no-raise contract and the failure set of a
  present-but-unusable `stderr` — went into `operational-sidecars.md` instead.
- **Per-plan status, issue ids as narrative, commit-by-commit history.** Progress, not knowledge; the compass and
  plans carry them.
- **`_JOURNAL_MIN_COMPACT_BYTES` sizing rationale.** The floor's *existence* is captured with the trigger; the
  measured 9032 B / 34-row derivation is a one-off measurement.
- **Iteration package promotion:** the package holds only `delivery-compass.md` (default-excluded) and
  `direction-lock.md`; no `guides/`, `specs/` or README. Triage = **keep snapshot** for `direction-lock.md`
  (lock-time record, no cross-iteration reuse); no file needed promotion.

## Compound Round Summary (draft for the compass — PM to apply)

```
- 结晶文档数：2 new（另 5 篇既有文档更新）
- 新增 CONCEPTS.md 条目：1（manifest journal）
- 触发 compound-refresh：否
```

## Iteration Retrospective (minimal) — review input for the PM

- **做得好的**：跨 plan 集成核查（D12）在收口前捞出 1 个新失败并顺带修好 2 个既有失败，是本次成本最低的
  一次证据动作；拒绝型守卫（`_remove_journal`）把不变量收进一个所有者，四个调用点无需各自记得。
- **可改进的**：`manifest.py` 三个 plan 同文件 → 测试前提互相失效（`I-000206`）；三个实现轮/审查轮上下文耗尽，
  PM 不得不亲自做复现与修复提交，说明单文件高密度计划需要把复现预算事前写进计划；守卫引入的"不可读"半边
  一开始没有被写成契约句，直到 review 座位补上。
- **下迭代建议**：把 D12 的失败集合差集作为迭代收口的固定步骤（不只在本迭代临时采用）；HANDOFF 里已知的两条
  门禁绕过（危险访问、审批关闭）与本次无关，但 `I-000205`（strand 修复路径）值得先于新的 `manifest.py` 计划处理。

## Verification performed

- `mstar compound validate <doc>` on all 7 touched documents → `ok: true, violations: []`.
- Catalog completeness: 33 knowledge catalog rows vs 32 knowledge files → 0 unregistered.
- Every factual claim in the new/updated docs was re-read against the iteration branch head `ec9d3d2`
  (`manifest.py`, `queue_source.py`, `coordinator.py`, `tests/test_manifest.py`, `tests/test_coordinator.py`).
