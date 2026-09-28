# Spec: Bilibili ASR Archive CLI (MVP)

**Status:** frozen (Phase 1 direction locked, autonomous mode; iteration `iter-2026-08-wmz-asr-mvp`)  
**Primary consumers:** plans `001-cli-scaffold-meta`, `002-subtitle-audio`, `003-asr-archive`  
**UP mid default:** `23191782`  
**Change policy:** requirement changes require a new spec revision + PM sign-off; plans must not add scope beyond this spec.

> **Revision note, 2026-09-24 — the ASR engine only.** The body below is the frozen bootstrap text and
> is kept as written: it names SenseVoice-Small, `funasr` and the ModelScope cache, which were the
> facts when this spec was locked. The engine has since changed twice (SenseVoice → FunASR-Nano →
> **Qwen3-ASR + Qwen3-ForcedAligner on transformers**), so the ASR-specific statements in *Goals* 4,
> the module map's `asr.py` line, and the whole `[asr]` dependency boundary are **superseded by**
> `bilibili-asr-archive/README.md` ("Where the ASR checkpoints live", "Naming the producer") and by the
> migration plan `.mstar/plans/20260924-qwen3-asr-transformers.md`. Everything else here — the CLI
> surface, the risk-control contract, the layering rules and the exit taxonomy — still holds, and the
> layering rule that matters for the engine change is the one that did not move: `asr.py` imports its
> engine lazily, so the module imports and `status`/`--help` run without the extra.

**Placement:** this file is warehouse-level MVP. Intended page-aware ledger (`work_id` = `bvid:p<zero-based-page-index>`), `artifact_stem`, unresolved legacy rows, and `meta-cursor.json` are **not** frozen here. They live in `.mstar/iterations/iter-2026-08-archive-foundations/` until iteration-close.

## Problem

Need a durable, resumable local tool to turn a Bilibili UP's public videos into searchable text. Manual download+ASR does not scale; B站 AI subtitles cover part of the corpus for free.

## MVP proof bar (DoD)

Tool completeness on a **~20-video pilot** — not full-corpus coverage. Pilot must exercise both pipeline branches (subtitle-hit and audio→ASR) and leave a resumable manifest in terminal states. Full corpus is next-iteration ops.

## Goals

1. Enumerate all visible archives for a mid into a local manifest (JSONL).
2. Prefer existing AI/CC subtitles before any ASR (subtitle-first).
3. Download audio-only streams when subtitles are missing.
4. Transcribe with local SenseVoice-Small (CPU-capable, optional extra).
5. Emit `srt` / `txt` / `md` with metadata frontmatter; resume-safe.

## Non-goals (MVP)

Full-corpus finish, diarization, LLM polish, search UI, redistribution, GUI. External downloader (yutto/BBDown) is a documented fallback only — the pure-API path is the deliverable.

## CLI surface (MVP, frozen)

```text
bili-asr fetch-meta --mid <mid> [--resume]
bili-asr probe-subs [--limit N] [--sessdata ...]
bili-asr harvest-subs [--limit N]
bili-asr download-audio --bvid <bvid>|--missing-subs [--limit N]
bili-asr asr --bvid <bvid>|--pending [--limit N]
bili-asr pilot --n 20
bili-asr status
```

> **Revision 2026-09-19 (iteration `iter-2026-09-artifact-root`).** The frozen list above predates the commands added
> since (`derive-manifest`, `coverage`, `coverage --quality`, `verify`, `recover`, `export`, `search`, `schedule`,
> `campaign`, `runs`, `reconcile`, `publish-transcripts`). Two operator-facing flags landed with that iteration and are part of the shipped
> surface: **`--artifact-root`** (also `BILI_ARTIFACT_ROOT`; flag wins; unset = the archive root) on the **11** commands
> that then wrote or read artifact paths, and **`--keep-audio` / `--no-keep-audio`** on the **5** commands that reach the
> reclaim path. A configured root is validated before the writer lock and refused with one of four named lines
> (`artifact root does not exist | is not a directory | is a symlink | cannot be opened`, exit 1). Contract:
> `{ITERATION_DIR}/iter-2026-09-artifact-root/specs/artifact-root-contract.md`.
>
> **Revision 2026-09-20 (iteration `iter-2026-09-transcript-projections`; sign-off for this file's change policy is
> recorded in that iteration's `delivery-compass.md` **D15**).** Two mechanical facts move, and nothing else does. The
> added-command enumeration above gains `publish-transcripts`, the iteration's product-writing command. With it,
> **`--artifact-root`** is on the **12** commands that write or read artifact paths — the eleven of the 2026-09-19
> revision plus `publish-transcripts`; `derive-manifest` is not among them, because it carries no artifact flag. No
> requirement, no exit-taxonomy line and no behaviour changes with this revision.

- Entrypoint: **`bili-asr`** (frozen; no longer "or `wmz-asr`").
- `pilot` selects a mix: short videos preferred, ≥1 without subtitles (audio→ASR branch), ≥1 with subtitles (zero-ASR branch); `--n` may be lowered for smoke runs.
- All commands print a summary of manifest state changes; all are idempotent/resumable.

## Module boundaries (architecture contract)

Layering is strictly one-directional; lower layers never import higher ones.

```text
cli.py            # argparse commands only; no HTTP/ASR logic
  ├─ manifest.py  # ManifestStore: JSONL ledger, status SSOT. No network, no I/O beyond manifest dir.
  ├─ bili_client.py  # ALL Bilibili HTTP: search, view, player/wbi/v2, playurl, subtitle JSON, audio GET.
  │                 # Owns buvid bootstrap, WBI signing, SESSDATA injection, risk backoff.
  ├─ subtitles.py # Pure transforms + orchestration over bili_client: probe/harvest, json→srt.
  ├─ audio.py     # playurl parse + stream download + ffmpeg remux (calls bili_client for HTTP).
  ├─ asr.py       # SenseVoice wrapper + segment→srt/txt. Import-guarded; no Bilibili knowledge.
  └─ archive.py   # File writers: transcripts/{srt,txt,md,raw} + frontmatter. Pure formatting, no network.
  └─ artifact_root.py  # Policy leaf: resolves/validates the artifact root and carries the read/write bases.
                    # stdlib only; imported by cli, the readers and the writers. No I/O beyond probing the root.
```

- Cross-layer rule: `subtitles`/`audio`/`asr`/`archive` never import each other; only `cli` (and `pilot` orchestration in `cli`) composes them.
- HTTP ownership: exactly one module (`bili_client`) opens sockets. Everything else receives data or paths. This is the primary test seam.
- `asr.py` boundary: imports `funasr` lazily inside `transcribe()`; module import must succeed without the `[asr]` extra so `status`/`--help` never require torch.

## `[asr]` dependency boundary

- Base install (`pip install -e bilibili-asr-archive/`): pure-Python + requests/httpx; full CLI surface parses; `asr`/`pilot`(ASR branch) invoked without the extra exit non-zero with one actionable message: install hint `pip install -e "bilibili-asr-archive/[asr]"`.
- Optional extra `[asr]` adds `funasr` (+ `torch` CPU). No alternate engine, no silent skip.
- SenseVoice-Small model weights are downloaded by FunASR on first `transcribe()` to its own cache (`~/.cache/modelscope`); the CLI documents `BILI_ASR_MODEL` env (default `iic/SenseVoiceSmall`) and a documented offline story: pre-populate the cache or set a local model dir — no vendored weights in the repo.

## HTTP / WBI / risk-control contract

All requests carry browser UA; JSON API calls carry `Referer: https://www.bilibili.com/` and buvid3/4 cookie from `x/frontend/finger/spi` (one bootstrap per process, cached).

| Endpoint | Auth/WBI | Notes |
|----------|----------|-------|
| `x/space/wbi/arc/search` (fetch-meta) | WBI-signed (`wbi_img` keys), buvid cookie | preferred when WBI available |
| `x/series/recArchivesByKeywords` (fetch-meta alt) | buvid cookie; no WBI | acceptable MVP fallback; proven under 412 backoff |
| `x/web-interface/view` (bvid→cid) | none | plain GET ok |
| `x/player/wbi/v2` (subtitle list) | WBI-signed; **AI subtitles realistically need SESSDATA** — Path A expects empty AI list here | this is the known login/WBI interaction hot spot; spike in plan 002 Task 0 |
| subtitle JSON (`subtitle_url`) | none (signed URL) | short-lived; download immediately after probe |
| `x/player/playurl` (dash audio) | WBI-signed; quality capped without login | prefer `dash.audio` id 30216→30232; stream GET needs Referer+UA |

**WBI signing:** `GetKey` (`wbi_img` from nav) → mixin-key reorder → MD5-signed query params. Key rotation is real; cache keys per process, re-derive on signature-rejected responses (code -403) once before failing.

**Risk-control taxonomy (terminal vs retryable):**

| Signal | Class | Action |
|--------|-------|--------|
| HTTP 412, code -412, -352 | retryable | exponential backoff (base 2s, cap 60s, max 5 attempts), jitter; refresh buvid once mid-sequence |
| code -799 | retryable | backoff; counts toward same budget |
| code -403 (WBI) | retryable-once | re-derive mixin key, retry once |
| HTTP 5xx / network | retryable | same backoff budget |
| 404 / video gone (code -404, -62002…) | terminal | manifest status `gone`, skip permanently |
| Backoff budget exhausted | **terminal** | command exits non-zero with a summary of failed bvids + last error code; `fetch-meta` documents the risk-control ceiling reached (count of un-enumerated pages) in its summary. A ceiling is an acceptable, documented outcome for the pilot — not a silent failure. |

## Error taxonomy (process exit + manifest)

- Exit 0: command succeeded (individual `gone` videos are fine).
- Exit 1: usage/config error (missing ffmpeg, bad args, `[asr]` extra missing).
- Exit 2: terminal API failure — risk-control ceiling or exhausted retries; summary printed listing bvids + codes; manifest entries stay in their last state for resume.

## Test seams (architecture contract)

- `bili_client` is the only seam needing HTTP mocks: all tests inject a fake transport / `responses`/`respx` layer; no live network in unit tests (live smoke optional, opt-in flag).
- `ManifestStore` operates on a temp-dir manifest root (`--archive-root` or fixture); no test touches the real `archive/`.
- `subtitles`/`archive`/`asr` formatters are pure functions over dicts/segments — tested with synthetic fixtures, zero mocks.
- Every risk code in the taxonomy above has one unit test asserting its retry/terminal classification.
- WBI signing is a pure function `(params, img_key, sub_key) → signed query` with a golden-vector test against the bilibili-API-collect reference vectors.

## Auth / risk (two documented paths)

- **Path A — no login (default, must work end-to-end):** AI subtitle list returns empty without SESSDATA; this is expected — mark `needs_audio`, proceed via audio download + local ASR.
- **Path B — with SESSDATA (optional):** env `BILI_SESSDATA` or `--sessdata`; unlocks AI subtitles and higher playurl quality. Secrets never committed, logged, or echoed.
- Obtain `buvid3`/`buvid4` via `x/frontend/finger/spi`.
- Backoff on HTTP 412 / code -412 / -352 / -799; document retry limits rather than silently failing.

## Manifest state machine

`pending → meta_ok → sub_checked → {subtitle_done | needs_audio → audio_ok} → asr_done → archived`

Idempotent: re-runs skip completed states. Status names are the SSOT shared by all three plans.

## Outputs

```text
archive/
  manifest/manifest.jsonl
  meta/{bvid}.json
  subtitles/raw/{bvid}.json
  transcripts/{srt,txt,md,raw}/
  audio/{bvid}.m4a   # retained by default since iter-2026-09-artifact-root (--keep-audio /
                     # --no-keep-audio, BILI_KEEP_AUDIO=1/0); reclaimed audio is expected absence
```

## Revision note — hotword provenance (2026-09-28)

> Revision for iteration `iter-2026-09-ops-readiness`, plan
> `20260928-hotword-injection-governance`. It supersedes only the meaning of the
> `hotwords` provenance value; the model / revision / device / language
> provenance contract is unchanged.

The `hotwords` provenance value is the **effective** prompt vocabulary — the terms
that actually reached the decoder prompt — not merely the configured list. A term
may enter the prompt only by evidence-based seeding: it must occur in the run's own
first-pass transcript or in the paired AI-subtitle text
(`bili_asr.asr.evidence_guard_hotwords`; pure string logic, no model calls). A run
transcribes once unguarded and then re-seeds the prompt with only the tokens that
first pass produced; the second pass runs only when that kept list is non-empty.
The shipped default (`DEFAULT_HOTWORDS`) is **empty** while the per-token keep/drop
measurement is pending an operator re-run — no speculative seeding. Tokens with no
evidence occurrence are dropped from the prompt and recorded in provenance as the
`hotword_dropped_no_evidence` key (comma-separated, present only when at least one
configured token was dropped). A run that configured no hotwords is unchanged: no
prompt-vocabulary line and no `hotword_dropped_no_evidence` key.

## Verification (DoD)

- Unit: state transitions, subtitle JSON→SRT conversion, SRT/md formatting, import-guard for ASR extra
- Integration: fetch ≥1 page meta (mocked HTTP acceptable; live smoke optional); probe 5 videos; end-to-end pilot ≤20 videos (short videos preferentially)
- Acceptance: README commands succeed on a clean install with ffmpeg + Python 3.12; both auth paths (no-login and SESSDATA) documented with expected behavior

## References

- `bilibili-asr-archive/PLAN.md`
- `bilibili-asr-archive/references/bilibili-API-collect/player.md`
- `bilibili-asr-archive/references/bilibili-API-collect/risk-and-stream.md`
- ADR: `.mstar/iterations/iter-2026-08-wmz-asr-mvp/specs/adr-001-architecture.md`
