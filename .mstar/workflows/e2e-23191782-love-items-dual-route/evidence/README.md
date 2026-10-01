# Evidence — `e2e-23191782-love-items-dual-route`

Verbatim copies of the target-host evidence gathered during checkpoint round 1 (2026-09-30).
Source on the target: `/root/e2e-asr/love-dual-route/{logs/20260930T064056Z,pre-run}/`.
No file here was edited after collection; the report's section references point into this tree.

## `logs/20260930T064056Z/` — run logs and probes

| File | What it holds |
|---|---|
| `a0-host-facts.log` | `uname`, cores, RAM, ffmpeg, disk |
| `a0-check-env-bare.log` | `check-asr-env` with no env — **exit 1** (the R1 residual, re-measured) |
| `a0-check-env-dxg.log` | same with `HSA_ENABLE_DXG_DETECTION=1` — **exit 0**, gfx1101 named |
| `a0-entry-points.log` | both venvs **without** DXG (`cuda_avail False` — expected, kept for the pairing) |
| `a0-entry-points-with-dxg.log` | the correction: both venvs **with** DXG; the decisive `accelerate` column |
| `a0-import-pinning.log` | unpinned → primary checkout; pinned → the detached worktree |
| `a0-cli-surface.log` | `--version` and the parsed subcommand count (24) |
| `a0-checkpoints.log`, `a0-hf-cache.log`, `a0-worktree-models.log` | local weights vs the hub cache (**12 K, refs only**) |
| `a0-default-config.log` | `default_config()` resolves **hub ids** — the input to finding F2 |
| `a0-local-checkpoints.log` | both local checkpoints' file listings and `AutoConfig` parse |
| `a0-network.log` | includes the HuggingFace reset (`curl rc=35`) |
| `a2-fetch-meta.log` | the first ladder: page 5 ok, page 6 never |
| `a2b-widen.log` | widened ladder attempt 1 (broken loop shape, recorded as-is) |
| `a2c-widen.log` | corrected widened ladder: **12/12 exit 2** |
| `a2-store.log` | store contents: 30 videos, 0 transcripts, the four `work_id` verdicts |
| `a2-diag.log` | per-page ingestion outcomes — `shape_error` vs `rate_limited`, cursor, `observed_total` |
| `a2-position-probe.log` | **E-1**: page ground truth via `recArchivesByKeywords` |
| `a2-endpoint.log` | **E-2**: page 1 ok / page 6 `shape_error`; raw legacy endpoint `-799` |
| `a2-item-diagnosis.log` | **E-3**: item 27 `BV18b9DYeE3s`, 29/30 normalizable |
| `a2-item-field-level.log` | **E-3**: the field-by-field probe — `desc` is the rejected field |
| `a2-blast-radius.log` | **E-4**: pages 2–6 scanned; 4 affected items, all multi-line `description` |
| `a2-minimal-tail.log` | **E-5**: no `--bvid` metadata-ingest path exists |

## `pre-run/` — the preservation ledger (A1/B0)

| File | What it holds |
|---|---|
| `a1-pre-state.txt` | `main` = `d41c257…`, `porcelain`, `reflog` **before** |
| `uncommitted-asr-py.delta.patch` | the uncommitted `asr.py` delta, byte-exact (`sha256 7fcb056a…`) |
| `asr.py.working-copy` | a byte copy of the working file (`sha256 cf535810…`) |
| `a1-delta.sha256` | both hashes + the diffstat (+60/−1) |
| `a1-rescue-ref.txt` | `rescue/d41c257-librosa-m4a d41c257` |
| `b0-pre-state.txt` | `d41c257` identity and the `main`-only commit list |
| `a0-build-identity.txt` | worktree `ed291be`, `DETACHED`, `PORCELAIN_LINES=0`, worktree list |
| `a1-post-state.txt` | `main` still `d41c257…`, `porcelain` identical, `reflog` unchanged at top |
| `status.json.copy` | the harness root register as it stood before the round |

**The `rescue/` ref and this ledger exist so that the target host's pre-run state is recoverable
without touching `refs/heads/main`.** Nothing in this directory was produced by modifying the
target's tracked files.

## round2/ — checkpoint round 2 (2026-09-30)

29 files, pulled verbatim from `/root/e2e-asr/love-dual-route/logs/20260930T-R2/` on the target after
round 2 completed. Same discipline as round 1: nothing was edited after collection.

`r2-b5-asr.clean.txt` is the same log as `r2-b5-asr.txt` with the `Loading weights:` progress bars and
the ROCm SDPA `UserWarning` repaints stripped — those lines are ~95% of the byte count and carry no
evidence. The raw file is kept alongside it so the de-noising is auditable.

Round 2's own control experiments live in the files rather than in prose:
`r2-a6-negative-control.txt` (the hand-written `no-subtitle` row, with the before/after view read and a
fresh-connection durability re-read), `r2-b2-control.txt` (the credential isolation: same item, same
host, same store, only the credential differs), and `r2-d4.txt` (the four re-run probes, including the
byte-identical audio tree that proves no re-download).
