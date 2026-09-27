# Spec addendum — `.mstar/specs/asr-archive-cli.md` provenance section

**For the coordinator.** The worktree for plan `20260928-hotword-injection-governance`
has no `.mstar/` (the published set is control-root-relative), so this in-place
spec addition is staged here verbatim for you to land into the tracked spec at
`/root/workspace/bilibili-asr-archive/.mstar/specs/asr-archive-cli.md`, per the
plan's Global Constraints (contract home: the spec's own revision-note pattern,
dated addendum, superseding only the lines it names).

---

Insert immediately after the spec's provenance paragraph (the one recording the
ASR runner configuration — model, revision, device, language, hotwords — in the
raw sidecar and `asr_*` frontmatter):

> **Revision note, 2026-09-28 — hotword provenance (iteration
> `iter-2026-09-ops-readiness`; plan `20260928-hotword-injection-governance`).**
> The `hotwords` provenance value is henceforth the **effective** prompt
> vocabulary — the terms that actually reached the decoder prompt — not merely
> the configured list. A term may enter the prompt only by evidence-based
> seeding: it must occur in the run's own first-pass transcript or the paired
> AI-subtitle text (`bili_asr.asr.evidence_guard_hotwords`, pure string logic,
> no model calls). The run transcribes once unguarded, then re-seeds the prompt
> with only the tokens that first pass produced. The shipped default
> (`DEFAULT_HOTWORDS`) is empty while the per-token keep/drop measurement is
> pending operator re-run — no speculative seeding. Tokens with no evidence
> occurrence are dropped from the prompt and recorded in the provenance as the
> `hotword_dropped_no_evidence` key (a comma-separated list, present only when
> at least one configured token was dropped). A run that never configured
> hotwords is unchanged: no prompt vocabulary line and no
> `hotword_dropped_no_evidence` key. This note supersedes only the sentence
> describing `hotwords` as the configured list; the model / revision / device /
> language provenance contract is unchanged.

---
