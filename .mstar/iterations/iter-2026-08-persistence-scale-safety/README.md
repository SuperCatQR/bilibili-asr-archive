# iter-2026-08-persistence-scale-safety

Iteration package for the autonomous `M` iteration that hardens sequential archive persistence/read scale and makes local SenseVoice execution reproducible.

## Documents

| Document | Kind | Description | Status |
|---|---|---|---|
| [delivery-compass.md](delivery-compass.md) | compass | Autonomous direction lock, two-plan budget, gates, and branch policy | completed |
| [specs/persistence-scale-safety.md](specs/persistence-scale-safety.md) | spec | Durable JSONL persistence, streaming projection, publication, and path contract | locked |
| [specs/asr-reproducibility.md](specs/asr-reproducibility.md) | spec | Local ASR model lifecycle, provenance, and fixture reproducibility contract | locked |

## Plans

Exactly two business plans are in the `M` budget; review/edit, SDD task review, QC/QA, close, compound, and PR gates are process gates, not additional plans.

| Plan | Role | Status |
|---|---|---|
| `20260831-persistence-scale-safety` | First serial business plan: persistence/read-scale and archive safety | Done |
| `20260831-asr-reproducibility` | Second serial business plan: local ASR lifecycle and provenance | Done |

The second plan started after the first plan's coordinator/persistence seam was integrated and its focused checks passed. Both plans completed QC/QA and serial integration. Plan files are process artifacts under `.mstar/plans/` and are not present in this checkout, so the two plan ids above are recorded as names rather than links; iteration-only specs remain under this package.

## Promotion log

| Source | Promoted to | Date | Notes |
|---|---|---|---|
| `specs/persistence-scale-safety.md` | `knowledge/architecture-patterns/operational-sidecars.md` | 2026-09-03 | Updated existing high-overlap guidance; retained iteration spec as historical contract. |
| `specs/asr-reproducibility.md` | `knowledge/architecture-patterns/run-scoped-asr-provenance.md` | 2026-09-03 | Structured promotion of the run-scoped lifecycle and redacted provenance pattern. |
