# Assignment — Phase 1 Review & Edit (architect)

**IDENTITY**

- Execute as: `architect`
- Delegation: forbidden (leaf executor; complete this yourself; no subagents)
- Who runs this turn: architect

**Scope**

Iteration `iter-2026-08-live-pc-pilot` Phase 1 review chain, seat 2/3 (architecture). Seat 1 (product-manager) has already returned; its edits are on disk — build on them, do not revert.

**Working branch / Branch policy**: control worktree `/root/workspace/bilibili-asr-archive` (docs-only; harness artifacts gitignored; no business-repo branch).

**Task category**: docs

**Inputs (read-only)**

- `.mstar/iterations/iter-2026-08-live-pc-pilot/delivery-compass.md`
- `.mstar/plans/20260826-audio-reclaim-on-archive.md`
- `.mstar/plans/20260826-bounded-live-pc-pilot.md`
- `.mstar/specs/asr-archive-cli.md` (frozen MVP)
- `.mstar/knowledge/architecture-patterns/bilibili-asr-archive-cli.md`
- Source (read-only reference): `bilibili-asr-archive/src/bili_asr/cli.py`, `coordinator.py`, `archive.py`, `subtitles.py`, `audio.py`

**Edit targets (direct file edits)**

- Plans: lock Interfaces sections (helper signatures, wiring points at the `archived` write in pilot/asr/coordinator), module placement, error/skip semantics.
- Iteration spec deltas: create/update `.mstar/iterations/iter-2026-08-live-pc-pilot/specs/` if contract-level decisions need capture (reclaim + budget). Do NOT touch `.mstar/specs/asr-archive-cli.md` frozen spec or add under `.mstar/knowledge/`.
- Compass: Risk Register / architecture wording fixes only.

**Architecture questions to resolve (edit in place)**

1. Reclaim helper placement: new `audio_reclaim.py` vs a function in existing filesystem module — pick one, name it, lock signature.
2. Budget gate: pre-download size estimate source (`duration_s` × 64kbps ceiling?) and skip semantics (per-item skip vs batch stop) — lock one.
3. Whether coordinator `--offline` archive stage also reclaims (recommend: yes, same helper).
4. Verify no plan breaks: HTTP ownership (`bili_client` only), no live HTTP in tests, no schema migration, credential redaction.

**NEVER**

- Do not modify `bilibili-asr-archive/src/**` or tests (docs/seats only).
- Do not add under `.mstar/knowledge/`.
- No git commands; no commits.
- No subagent dispatch.

**Completion Report**

Reply with: files edited (paths + one-line summaries), locked interface decisions, contract risks for seat 3, verdict Approve/Revise.
