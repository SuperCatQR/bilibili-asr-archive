# Architect task — decide 3 things

You are the architect seat for iteration `iter-2026-10-asr-success-attestable`. Decide three technical questions and write two short specs. **Do not read any other file. Do not open anything under `bilibili-asr-archive/`.** All facts you need are below.

## Defect 1 (`I-000188`)
Part `BV1YFEUzpEsT:p0`: decoded audio **73.561 s**, archived transcript only **13 segments spanning 0.0–59.0 s** — 20% of speech never reached — yet recorded `outcome=stored`, bundle `archived`, no `error_code`. Measured: fresh download is full length; a **4× token budget gave byte-identical output**; the skipped span is speech-level energy (−27 dB mean vs −26 dB covered); at **+20 dB the model does emit text** there while a verified-silent control emits nothing at any gain. So it is *hard audio*, not a gain bug. **Nothing compares the produced span against the decoded duration.**

## Defect 2 (`I-000187`)
`probe-subs` reported `tracks=0` / `(no subtitles visible)` / `failed=0` for two parts; **minutes later `harvest-subs` stored `subtitle-ai` for both**; a re-probe showed `tracks=1`. Same part, same command, only time differs. `no-subtitle` is what admits a part into the paid branch (download + GPU ASR). A control part reported `tracks=0` on all three probes and is genuinely caption-less — one probe cannot tell "absent" from "unseen".

## Source facts (verbatim, authoritative)

`_split_audio` docstring: *"Returns `(chunk_samples, offset_seconds)` pairs in order whose lengths **tile the input exactly**: no overlap, no gap, nothing dropped and nothing added."*

The chunk loop (`asr.py`):
```python
chunks = _split_audio(samples, SAMPLE_RATE, self.config.chunk_seconds)
for chunk, offset in chunks:
    ...
    text, language = self._transcribe_chunk(models, scratch, bust_cache=bust_cache)
    if not text:
        continue                      # empty chunk silently dropped, nothing recorded
    units = [ ... + offset ... ]
    pieces.extend(_thread_text(text, units))
cues = _aligned_cues(pieces)
```
`ASRRunner.transcribe` already keeps `self._last_characters` and `self._last_transcribed_segments` (existing per-run state precedent).

`AudioDecodeError` docstring already admits: *"Nothing here compares the decoded duration with the row's `duration_s`, so a short read is not detected."*

`v_missing_audio` predicate (the paid-branch admission):
```sql
-- subtitle_attempts CTE: newest attempt per video_part_id (finished_at DESC, run_id DESC), kind='subtitle'
JOIN subtitle_attempts AS latest ON latest.video_part_id = vp.video_part_id AND latest.recency = 1
WHERE vp.processing_status <> 'gone'
  AND NOT EXISTS (SELECT 1 FROM transcripts AS t WHERE t.video_part_id = vp.video_part_id)
  AND latest.outcome IN ('no-subtitle', 'failed')
  AND NOT EXISTS (SELECT 1 FROM part_audio_objects AS pao WHERE pao.video_part_id = vp.video_part_id);
```
The view also exposes `latest.outcome AS newest_outcome, latest.error_code AS newest_error_code`.

`subtitle_ingest.py` — both causes funnel to the same outcome:
```python
except GatewayNotFound:
    return self._record_captionless_part(run_id, item, "not_found", started_at)
...
track = select_subtitle_track(tracks, languages)
if track is None:
    # Either nothing was visible or nothing matched the requested languages
    return self._record_captionless_part(run_id, item, None, started_at)
```
Gateway contract: *"An inventory the credential in effect could not see is an empty tuple — never a `not_found` failure and never a placeholder track."*

## Constraints from the product-manager seat (binding)
- Stock data is **not** rescanned/reconciled/rewritten this iteration; but the operator must be able to **detect** existing short-coverage records **read-only**, from the archive itself.
- A re-run may not "launder" a previously-successful short-coverage record: only two self-consistent end states (coverage improves and evidence updates; or coverage stays short and the archive no longer shows unqualified success).
- **The store persists no decoded-audio duration.** So read-only detectability of *pre-existing* records can only mark them "not evaluable" unless coverage evidence lands somewhere decodable from the archive. Resolve this explicitly.

---

# Your output: write exactly ONE file

Path: `/root/workspace/bilibili-asr-archive/.mstar/iterations/iter-2026-10-asr-success-attestable/specs/architect-decisions.md`

Contents, in this order, concise (target ~150 lines total):

## D8 — shortfall: block or mark?
Decide. Justify in 2–3 sentences. State the consequence for existing archives and for re-runs, and reconcile with the "no third state" constraint above.

## D9 — coverage evidence: quantity and threshold
The granularity (per-part single span vs per-chunk) and **the exact quantity compared**. Give the comparison rule, and derive the threshold from the measured basis (73.561 s decoded / 0–59.0 s produced) — do not pick a round number. State whether `_split_audio`'s tiling promise is a usable assertion base and why. Name exactly **where** the evidence is recorded (field/table/sidecar) and list its **consumers**.

## D10 — caption exhaustion: the shape
Choose: (a) empty inventory no longer counts as exhaustion, (b) recorded distinguishably so `v_missing_audio` separates it, or (c) both. Give **the exact predicate change as concrete SQL**. Show that a genuinely caption-less part still reaches the paid branch.

## How read-only detection works for pre-existing records
Answer the product-manager's constraint directly: for records already archived before the fix, what can the operator see, and what can they not? Be plain about the limit.

## Migration verdict
One line: does any of this need a schema migration? This repo's standing decision is "schema rebuildable, no in-place migration". If a migration is needed, say so loudly.

## Spec 1 — asr-coverage-attestation (normative, ~40 lines)
The contract: the quantity, where it is recorded, what "shortfall" means, the comparison rule, both directions of assertion (shortfall detected; full coverage NOT flagged). Testable — a reader must be able to write the witness from it without asking you anything.

## Spec 2 — caption-exhaustion-attestation (normative, ~40 lines)
The contract: what distinguishes "unseen" from "absent" in the record, the predicate change, the preservation case. Same testability bar.
