# iter-2026-08-persistence-scale-safety

Iteration package for the autonomous `M` iteration that hardens sequential archive persistence/read scale and makes local SenseVoice execution reproducible.

## Documents

| Document | Kind | Description | Status |
|---|---|---|---|
| [delivery-compass.md](delivery-compass.md) | compass | Autonomous direction lock, two-plan budget, gates, and branch policy | locked |
| [specs/persistence-scale-safety.md](specs/persistence-scale-safety.md) | spec | Durable JSONL persistence, streaming projection, publication, and path contract | locked |
| [specs/asr-reproducibility.md](specs/asr-reproducibility.md) | spec | Local ASR model lifecycle, provenance, and fixture reproducibility contract | locked |

## Plans

Exactly two business plans are in the `M` budget; review/edit, SDD task review, QC/QA, close, compound, and PR gates are process gates, not additional plans.

| Plan | Role | Status |
|---|---|---|
| [20260831-persistence-scale-safety](../../plans/20260831-persistence-scale-safety.md) | First serial business plan: persistence/read-scale and archive safety | Todo |
| [20260831-asr-reproducibility](../../plans/20260831-asr-reproducibility.md) | Second serial business plan: local ASR lifecycle and provenance | Todo |

The second plan starts only after the first plan's coordinator/persistence seam is integrated and its focused checks pass. Plan files are process artifacts under `.mstar/plans/`; iteration-only specs remain under this package, and no knowledge document is added before iteration-close compound.## Promotion log

| Source | Promoted to | Date | Notes |
|---|---|---|---|
| | | | |
