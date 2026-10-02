# E2E Verification Report

## Scope

- **Workflow / plan**: `e2e-23191782-store-writeback-chain` (type `plan`, `delivery_kind: verification/report-only`)
- **Plan document**: `.mstar/plans/e2e-23191782-store-writeback-chain.md` (status `authorized`)
- **User authorization and permitted side effects**: operator authorized 2026-10-03 —
  Q1 授权 A4（检出同步 `d41c257` → `1e756df`）；Q2 启用 S11（人工抽检腿）；Q3 确认写根
  `/root/e2e-asr/store-writeback-chain`（不写 `/mnt/e`）；Q4 允许持久化 `HSA_ENABLE_DXG_DETECTION=1`；
  Q5 候选集沿用页 5–6；「过程中的问题登记，若是硬阻塞就尝试修复」。
  Permitted: real Bilibili API calls for pages 5–6, real GPU ASR on the named host, writes confined to the
  run root, one profile edit for Q4. Not permitted and not done: dependency installs, lock regeneration,
  full pytest suite, writes outside the run root, credential rotation.
- **Target build / ref**: repo `1e756df8d76618195dd68aae9a1129ab6ce33ada` (subject
  `chore(harness): land the iteration plan + workflow artifacts in git`) — synced from the host's
  pre-run `d41c2572e27c116fb422f4be93927f0e71b422e3` under authorization A4.
- **Actual environment / device / session**:
  - Compute host `chosenecho@192.168.3.21` = WSL2 distro on `DESKTOP-HHFROLO`, Ubuntu 24.04.1,
    kernel `6.18.33.2-microsoft-standard-WSL2`, 24 GB RAM, `/dev/sdd` 674 GB free.
  - GPU **AMD Radeon RX 7800 XT**, `arch=gfx1101`, `vram_gb=15.8`, ROCm `/opt/rocm-7.2.1`,
    `hip=7.2.26015-fc0010cf6a`, `torch 2.9.1+rocm7.2.0.git7e1940d4`.
  - Interpreter for every scenario: `$P/.venv/bin/bili-asr` / `.venv/bin/python` (3.12.3) with
    `transformers 5.16.1`, `accelerate 1.15.0`, `soundfile 0.14.0`, `soxr 1.1.0`, `numpy 1.26.4`.
    (`/root/gpu-venv` lacks `accelerate`; it was never used.)
  - Checkpoints: `models/Qwen3-ASR-1.7B-hf` + `models/Qwen3-ForcedAligner-0.6B-hf`, loaded fully offline
    (`HF_HUB_OFFLINE=1`; no network model fetch observed).
  - Run root (the only write root): `/root/e2e-asr/store-writeback-chain/` with `archive/`, `artifacts/`,
    `evidence/`. Credential referenced by path only, never printed.
- **Assigned scenario IDs**: S0–S12 (13 scenarios; S11 and S12 added to the draft's S0–S10 list by the
  operator's Q2/Q4 authorization).

## Results

| Scenario | Expected | Actual | Outcome | Evidence |
|---|---|---|---|---|
| **S0** checkout sync | `HEAD == 1e756df`; `--queue-source` present; gap views present; dirty patch preserved | `HEAD = 1e756df8`; `cli/` package present (single-module `cli.py` gone); `asr --help` has `--queue-source`; 24 subcommands; `v_missing_audio`/`v_missing_transcript` present; `DEFAULT_HOTWORDS = ()`; pre-sync tree saved as patch (73 lines) + branch `pre-e2e-sync-d41c257` | **passed** | `evidence/s0-identity.txt`, `evidence/s0-dirty-tree.patch`, `evidence/s0-pre-status.txt` |
| **S1** env capability gate (both arms asserted) | bare → exit 1 with `dxg-detection FAIL` + `device-probe FAIL`; with DXG → exit 0, `arch=gfx1101 vram_gb=15.8` | Exactly that. bare exit **1** (`2 failed`); DXG exit **0** (`device ok name=AMD Radeon RX 7800 XT arch=gfx1101 vram_gb=15.8`) | **passed** | `evidence/s1-bare.txt`, `evidence/s1-dxg.txt` |
| **S2** fresh store bootstrap + metadata ingest | `archive.db` created; ≥57 parts; page-6 retry allowed once | attempt 1: `rate_limited`, `risk_interrupted`, RC=2, cursor unchanged at page 6 (30 parts landed); attempt 2 after 20 s: page 6 collected, RC=0. Final **videos=60, parts=60**, `ingestion_runs=2` | **passed** | `evidence/s2-fetch.txt`, `evidence/s2-counts.txt`, `evidence/s2-candidates.txt` |
| **S3** caption-arm admission | `harvest-subs` writes `source_kind='subtitle-ai'`; part leaves all three gap views | `harvest BV1acKfzEEWS:p0 stored subtitle-ai ai-zh v1`; 1 transcript row, 195 segments, sha 64-hex; in `v_missing_subtitle`=0, `v_missing_audio`=0, `v_missing_transcript`=0; `pipeline_state=transcribed` | **passed** | `evidence/s3-probe.txt`, `evidence/s3-harvest.txt`, `evidence/s3-store.txt` |
| **S4** audio-branch admission (two-state) | before any attempt: `v_missing_audio` for the part = 0; after `harvest-subs` records `no-subtitle`: = 1; no transcript, no audio object | **before = 0**; `harvest BV1aAhLzsENb:p0 no-subtitle`; attempt row `kind=subtitle outcome=no-subtitle error_code=None selector_kind=bvid`; **after = 1**; transcripts=0; audio_objects=0. Rollup after: missing_subtitle 59, missing_audio 1, missing_transcript 0 | **passed** | `evidence/s4-pre.txt`, `evidence/s4-harvest.txt`, `evidence/s4-post.txt`, `evidence/s4-rollup.txt` |
| **S5** audio download | `part_audio_objects` row `acquisition_source='download'`; bytes on disk >0; leaves `v_missing_audio`; enters `v_missing_transcript` | `audio_ok (audio/BV1aAhLzsENb.p0.m4a)`; pao row `video_part_id=12 audio_id=1 acquisition_source=download`; **3,064,353 bytes**; missing_audio 0; missing_transcript 1 | **passed** | `evidence/s5-download.txt`, `evidence/s5-pao.txt`, `evidence/s5-bytes.txt` |
| **S6** **ASR → archive + store write-back convergence (headline)** | see per-assertion detail below | **all 7 assertion groups hold** | **passed** | `evidence/s6-asr.txt`, `evidence/s6-store.txt`, `evidence/s6-bundle.txt`, `evidence/s6-pre.txt` |
| **S7** re-run spends nothing | `asr: queue empty …`, exit 0, no new run, no model load | `asr: queue empty (no parts need transcription)` RC=0; `kind='asr'` run count **1 → 1**; wall **0 s** (a real run is ~51 s) | **passed** | `evidence/s7-rerun.txt`, `evidence/s7-norun.txt` |
| **S8** reader exits | status counts the part; search finds freshly written ASR text; `verify`/`coverage` exits recorded | `search-index: indexed 250 block(s)`; `search 大智者` → **`BV1aAhLzsENb P0 … [00:00:08,480 → 00:00:11,840] 因为[大智者]，有[大智者]`** (asr-local content IS indexed/searchable); `search 职业革命家` → 5 caption-arm blocks; `status` RC=0; `verify` RC=**1** (`defect_count 0, backlog_count 0, diagnostics: structural_input_error ×2`); `coverage --strict` RC=**1** (`cumulative complete 1/1`, 4 × `evidence_missing` diagnostics) | **passed** (with two characterized non-zero exits) | `evidence/s8-status.txt`, `evidence/s8-search.txt`, `evidence/s8-verify.txt`, `evidence/s8-coverage.txt` |
| **S9** publish idempotence | first run publishes or reports state; second reports `already_published` and replaces nothing | `already_published` on both runs; `bundle.md` sha256 **identical** before/after (`cc87d231…ebce0`); `published=0 already_published=1 failed=0` | **passed** | `evidence/s9-first.txt`, `evidence/s9-second.txt`, `evidence/s9-hash.txt`, `evidence/s9-tree.txt` |
| **S10** hotword as-shipped state | `DEFAULT_HOTWORDS == ()`; measured candidates shipped; path inert unset | `DEFAULT_HOTWORDS: tuple[str, ...] = ()`; `MEASURED_HOTWORD_CANDIDATES` present; `BILI_ASR_HOTWORDS` unset | **passed** | `evidence/s10-hotwords.txt` |
| **S11** human inspection leg (closes `I-000102`) | force the caption-bearing part's audio route, then `proofread`; hand-inspect ≥5 blocks | forcing row written via the product's own `ManifestStore`; `download-audio` (manifest route) `audio_ok`; `asr` (manifest route) `archived (asr)` 84 s, raw sidecar written; `proofread` RC=0 → side-by-side + alignment (29 blocks, 83 ASR segments, 195/195 subtitle entries assigned, **0 unassigned**); machine verdicts 24 agree / 3 minor / 2 review; **8 blocks hand-inspected**, 5 agree / 2 minor-despite-passing / 1 review | **passed** | `evidence/s11-force.txt`, `s11-download.txt`, `s11-asr.txt`, `s11-proofread.txt`, `s11-sidebyside.md`, `s11-alignment.jsonl`, **`evidence/s11-inspection.md`** |
| **S12** DXG persistence (host side of `I-000118`) | persist the var so a bare `check-asr-env` exits 0 | Placed in `/etc/profile.d/bili-asr-gpu.sh` (+ `/etc/environment`); `bash -lc '<venv>/bin/bili-asr check-asr-env'` bare → **exit 0**, `device ok … arch=gfx1101 vram_gb=15.8`, `asr-env: verified`. **Not achieved** in `wsl -e bash -s` (exit 1) — that invocation reads no startup file at all | **passed** (documented limits) | `evidence/s12-persist.txt`, `evidence/s12-placement.txt`, `evidence/s12-login-after.txt`, `evidence/s12-bare-after.txt` |

### S6 per-assertion detail (the headline)

Invocation: `asr --bvid BV1aAhLzsENb:p0 --archive-root … --artifact-root … --no-keep-audio`
→ `asr: model constructions=1 for 1 asr item(s)`, `BV1aAhLzsENb:p0: archived (asr)`, RC=0, **wall 51 s**
for 374 s of audio (shortest caption-less candidate, chosen to bound cost).

| # | Assertion | Observed |
|---|---|---|
| 1 | exactly one new `transcripts` row, `source_kind='asr-local'`, `version=1`, sha 64-hex | `transcript_id=2 source_kind=asr-local version=1 model_id=1 sha_len=64 language=und` — **holds** (language is `und`, see F4) |
| 2 | `transcript_segments` > 0, ordinals contiguous, `end_ms > start_ms` | `n=55 min_ord=0 max_ord=54 well_ordered=55` — **holds** |
| 3 | `asr_models` row for the checkpoint | `model_id=1 model_name=…/models/Qwen3-ASR-1.7B-hf revision=""` — **holds** |
| 4 | new `acquisition_runs` row `kind='asr'` | `run_id=asr-1790983612 kind=asr selector_kind=pending selector_target=None outcome=running` — **holds** (with F1/F2 caveats) |
| 5 | attempt row `outcome='stored'`, `transcript_id` set, same run | `run_id=asr-1790983612 outcome=stored error_code=None transcript_id=2` — **holds** |
| 6 | **convergence**: leaves `v_missing_transcript`; `pipeline_state='transcribed'` | `v_missing_transcript` for the part **1 → 0**; `pipeline_state=transcribed` — **holds** |
| 7 | four-family artifact bundle + `.bundle-ready` | `bundle.srt`, `bundle.txt`, `bundle.md`, `bundle.raw.json`, `.bundle-ready` all present — **holds** |

Content sanity (not a threshold echo): first three stored segments read
`我们今天要讲的就是说，` / `有大的智慧，必然会有大的勇敢，` / `因为大智者，有大智者` — coherent transcript of
`BV1aAhLzsENb:p0` 【实事求是】大勇者必有大怯.

## Evidence

All evidence is new for this run, recorded on the compute host under
`/root/e2e-asr/store-writeback-chain/evidence/`; nothing was reused from the prior
`e2e-23191782-love-items-dual-route` run (its route stores were inspected read-only to confirm they
could not be reused — both artifact trees had been cleaned, 0 bytes of audio survived).

Distinctive evidence:

- `s0-identity.txt` — sync identity, capability verdict, and the 11-file content diff showing the host's
  `d41c257` was the same change as upstream `0a95035` (which IS an ancestor of `1e756df`).
- `s6-store.txt` — every S6 assertion query with its output, including the convergence flip.
- `s8-search.txt` — the live proof that asr-local text is indexed and searchable with block timings.
- `s11-inspection.md` — the human reading of 8 blocks, with the two "agree-but-really-defective" cases.
- `i166-repro.txt` — the mechanism reproduction for F1 below (isolated store copy, not the run store).

No secret value appears in any evidence file. Credentials are referenced by path only; `s12-*` files
record placement file *names* and a `=<redacted>` rendering.

## Findings and handoff

| id | severity | finding | status |
|---|---|---|---|
| **F1** | high | **`I-000166` reproduced live, not merely inferred.** With `asr-<next-second>` pre-occupied in `acquisition_runs`, `ensure_asr_run` returned `None` and `cli/asr.py`'s write-back guard evaluated to `False` — a **silent, invocation-wide write-back skip**. Evidence `i166-repro.txt`. | registered; owner = the active `iter-2026-10-ledger-integrity` plan `asr-run-id-uniqueness` |
| **F2** | medium | **`kind='asr'` acquisition runs are never finished.** `finish_acquisition_run` is called only from `services/subtitle_ingest.py`; nothing closes an ASR run. Observed: every `kind='asr'` row sits at `outcome='running'`, `finished_at=NULL` (including the successful S6 run). Any consumer reasoning "has this ASR run completed?" gets the wrong answer forever. | new issue registered |
| **F3** | low | **ASR run selector mislabels a scoped call.** `asr --bvid X:p0` produced `selector_kind='pending', selector_target=NULL` (`asr.py:151` calls `_ensure_asr_run(queue_source, "asr")` with no selector), so the run ledger claims a whole-queue scope for a single-part invocation. | new issue registered |
| **F4** | low | **`language='und'` documented as provenance-derived.** The plan asserted the language comes from provenance; the observed value is `und` for a Chinese transcript, because `provenance["language"]` is absent. Cosmetic today (the uniqueness key tolerates it) but it de-identifies every default-path ASR row. | new issue registered |
| **F5** | low | **`coverage`/`verify` read evidence sidecars the plain CLI never writes.** `coverage --strict` RC=1 with `evidence_missing` for `attempts`, `cursor`, `run_ledger`, `scheduler`; `verify` RC=1 with `structural_input_error` ×2. Consistent with the CLI paths leaving no ledger sidecars, but the operator-facing read is "1/1 complete yet exit 1". | new issue registered |
| **F6** | low | **Plan/doc drift found while executing (my plan's own errors, corrected in-flight).** `fetch-meta --resume` is mutually exclusive with `--start-page`; `probe-subs` requires exactly one of `--bvid`/`--limit-parts`. Both were wrong in the draft and cost two corrective rounds. | recorded here; documentation follow-up only |
| **F7** | — | Pre-existing, unchanged: `I-000067` and `I-000149` are **stale** at `1e756df`. S6 is now the independent live confirmation for the `I-000067` family (the write-back does happen, and it converges the views). | no new issue; note for the audit trail |

Reproduction for F1 is a 12-line script (`/tmp/i166-repro.py` on the host) against a store copy; F2/F3 are
read from `s6-store.txt` + `s6-anomaly-runs.txt`; F4 from `s6-store.txt`; F5 from `s8-verify.txt`/`s8-coverage.txt`.

## Not verified

- **`verify`/`coverage` green path.** Not attempted: those readers consult ledger sidecars that the plain
  CLI paths do not write (F5), so a green run was out of scope for this scenario list. Both exits are
  recorded verbatim rather than asserted as pass.
- **Corpus-scale behaviour.** One caption-bearing part and one caption-less part, from pages 5–6 only
  (S2 collected 60 of ~1739 videos). No claim is made about rate-limit behaviour beyond the two pages
  observed, nor about multi-part videos (`:pN` beyond p0).
- **`wsl -e bash -s` DXG form.** S12 fixed the login-shell/profile case; the bare non-interactive form
  still exits 1 by construction (no startup file is read). Left as a documented limitation.
- **`--queue-source manifest` as a product path.** Used only as the *authorized forcing device* for S11;
  it is deprecated by its own banner and was not otherwise exercised.
- **Human inspection depth.** 8 blocks of one part (`I-000102`'s "≥5 blocks" is met for one part); a
  corpus-wide editorial claim would need more parts.
- **FS: rate limiting.** Page 6 needed exactly one retry, as the plan allowed. No deeper throttle
  probing was attempted (deliberately: the STOP rule forbids hammering).

## Completion recommendation

- **Assigned scenarios: 13 (S0–S12). Completed: 13. Blocked: 0. Not-run: 0. Failed: 0.**
- **Product verdict: the headline capability is confirmed on real hardware.** ASR → archive → store
  write-back → gap-view convergence → searchable text all hold at `1e756df` on the RX 7800 XT. The
  store-driven chain's central claim is no longer analytic.
- **Five findings** (1 high already-owned, 4 new small ones) are registered for bounded follow-up; none
  blocks this run's acceptance, and F1's fix already has a home in the active iteration.
- **Workflow lifecycle**: recommend `completed` for this verification workflow — all assigned scenarios
  reached a determinate result, which is independent of the product verdict. I (PM) own the final state.
- **Operator-facing one-liner**: the chain works end-to-end on the GPU host; the remaining defects are
  bookkeeping-class (run lifecycle/selector/language labels), plus one live-reproduced silent-skip
  hazard (`I-000166`) that the active iteration is already scheduled to fix.
