# Hotword keep/drop — Measurement results (plan 20260928-hotword-injection-governance)

> **Status: PENDING-OPERATOR.** The corpus audio does not exist on this machine.
> (The historical cause was the `/mnt/123pan` WebDAV mount failing — first
> `Input/output error`, then a hard `401 Unauthorized` once its credential expired.
> That mount has since been **retired**: unmounted, `rclone-123pan.service`
> disabled, and the archive root moved to `/srv/bili-asr-archive`. No local archive
> is staged there yet.) The guard and the
> measurement harness are landed and tested; the per-token numbers below are not
> yet measured. This is an honest outcome, not a failure — the harness is ready to
> score the run the moment the audio is staged.

## Rerun instructions

1. **Stage the corpus audio.** The pinned corpus is the six parts where the
   20260922 proofread wave logged the most hotword-adjacent corrections. Re-fetch
   to a local disk. Do **not** run against a network mount: a WebDAV/FUSE mount
   makes `rm -rf` a data-loss primitive (see the knowledge note's trap 4) — that
   is one of the reasons the 123pan mount was retired rather than remounted. The
   current local archive root is `/srv/bili-asr-archive`.
   The 2026-09-26 round staged them at `/mnt/e/asr-archive-c6/audio` on the target
   host; substitute the nearest long-form part with both routes if a part is
   absent, and record the substitution here.

2. **Run the two arms** (same audio, same decoder settings; only the prompt
   vocabulary differs). The with-arm admits tokens only via the landed evidence
   guard, so "with-evidence-hotwords" is what the guard actually let through:
   ```bash
   cd .
   PY=.venv/bin/python
   export BILI_ASR_MODEL=$PWD/models/Qwen3-ASR-1.7B-hf \
          BILI_ASR_ALIGNER_MODEL=$PWD/models/Qwen3-ForcedAligner-0.6B-hf \
          BILI_ASR_MODEL_ID=Qwen/Qwen3-ASR-1.7B-hf HF_HUB_OFFLINE=1
   # without arm: shipped config seeds nothing (DEFAULT_HOTWORDS is empty).
   "$PY" -m bili_asr asr --pending --archive-root /root/e2e-asr/hw-govern/without
   # with arm: the six homophone tokens + the three verified archive terms, admitted
   # by the guard (the run's own first pass + paired subtitles).
   export BILI_ASR_HOTWORDS="扬弃,自在,变易,此在,感性,实存,国际劳工仲裁,International Employment Matters Tribunal,定在"
   "$PY" -m bili_asr asr --pending --archive-root /root/e2e-asr/hw-govern/with
   ```
   Copy each arm's paired subtitle documents into `subtitle/` (the harness reads
   `subtitles/raw/<bvid>.p0.json` per item).

3. **Score** (the audio is not needed to score a completed run):
   ```bash
   .venv/bin/python scripts/measure_hotwords.py --ab-root /root/e2e-asr/hw-govern
   ```
   This writes `HOTWORD-CENSUS.md` + `hotword-census.json`: per-token R/I/U and
   the corpus ratio. The comparators are the 20260918 text-precision basis
   (`difflib`, `autojunk=False`), pinned in `tests/_hotword_census_comparators.py`.
   **Comparator revision that scored the A/B:** the guide census as of 2026-09-26
   (`iter-2026-09-qwen3-asr-closeout/guides/assets/census.py` →
   `tests/_hotword_census_comparators.py`), functions `ratio`, `read_cues`,
   `srt_seconds`, `arm_b_text_over`.

4. **Land the ruling here** — one row per token, measured delta filled in:
   keep ⇔ delta > 0 **and** I = 0 (no insertion instances); otherwise drop.

## Ruling table (all 9 tokens; the 6 homophone tokens are the unverified set)

| Token | Verified? | Measured R | Measured I | Delta (with − without) | Ruling |
|---|---|---|---|---|---|
| 扬弃 | no (homophone) | PENDING | PENDING | PENDING | PENDING |
| 自在 | no (homophone) | PENDING | PENDING | PENDING | PENDING |
| 变易 | no (homophone) | PENDING | PENDING | PENDING | PENDING |
| 此在 | no (homophone) | PENDING | PENDING | PENDING | PENDING |
| 感性 | no (homophone) | PENDING | PENDING | PENDING | PENDING |
| 实存 | no (homophone) | PENDING | PENDING | PENDING | PENDING |
| 国际劳工仲裁 | yes | PENDING | PENDING | PENDING | keep (verified) |
| International Employment Matters Tribunal | yes | PENDING | PENDING | PENDING | keep (verified) |
| 定在 | yes | PENDING | PENDING | PENDING | keep (verified) |

## The default-list decision, recorded explicitly (Task 3)

Because the measurement is **pending**, the default hotword list is
**empty-with-guard-on**: `DEFAULT_HOTWORDS == ()`. There is no speculative
seeding — a token can enter the prompt only through `evidence_guard_hotwords`
against the run's own first-pass transcript or its paired AI-subtitle text, and
dropped tokens are recorded as `hotword_dropped_no_evidence`. The
measured-candidate tokens are preserved under `MEASURED_HOTWORD_CANDIDATES` so
the ruling has subjects; when the numbers land, the kept tokens return to
`DEFAULT_HOTWORDS` and the rest are dropped from the default source entirely.

## Why a fresh measurement, not the 2026-09-26 numbers

The 2026-09-26 round (record: `iter-2026-09-qwen3-asr-closeout/guides/
t5-hotword-measurement-results.md`) scored the *committed* 33-entry list and
returned R = 0 / I = 0 on a corpus under its pre-declared interpretive floor
(E = 7 < 8). This plan's arm is the *guard-admitted* list on the pinned
proofread-wave corpus — a different question — so it is measured, not inferred.
