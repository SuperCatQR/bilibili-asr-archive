# Findings register — 2026-10-03 hardware E2E runs

> **Why this file exists.** The authoritative issue store is `.mstar/store.db`, which `.gitignore`
> excludes as process-local authority. That makes a registered finding invisible to anyone reading
> a PR. This is a read-only **snapshot** exported from the store (`mstar issue export`) so the runs'
> findings are reviewable. The store remains the authority: to re-read it live, run
> `mstar issue show --id <id> --project _default --actor project-manager`.

Runs: `.mstar/workflows/e2e-23191782-store-writeback-chain/reports/{e2e.md,proofread-chain-e2e.md}`.
All eight were registered on 2026-10-03 and all are `open` — see `I-000186` for why none can be closed.

| Issue | Severity | Disposition | Title |
|---|---|---|---|
| `I-000182` | medium | open | E2E-2026-10-03: a kind=asr acquisition run is never finished — every ASR run stays outcome=running with finished_at NULL |
| `I-000183` | low | open | E2E-2026-10-03: a bvid-scoped asr invocation records selector_kind=pending with selector_target NULL, claiming a whole-queue scope |
| `I-000184` | low | open | E2E-2026-10-03: the default asr path stores language='und' for a Chinese transcript, so every ASR row is de-identified |
| `I-000185` | low | open | E2E-2026-10-03: coverage/verify exit non-zero on a healthy archive because the plain CLI writes no evidence sidecars |
| `I-000186` | medium | open | The issue-close channel is unreachable in practice: every privileged issue mutation needs an engine-issued session envelope bound to a live workflow snapshot, and no workflow in this repo has ever recorded that binding |
| `I-000187` | high | open | An empty caption inventory is recorded as a durable no-subtitle even when the credential is live: probe-subs and harvest-subs disagree on the same part, minutes apart, and the emptiness is what admits the paid audio->GPU-ASR branch |
| `I-000188` | high | open | The ASR stage can store a transcript that silently covers only part of the audio's speech, and the archive records it as success: 13 segments spanning 0-59.0 s of a 73.56 s recording, 20% of the speech unreached, with no coverage signal anywhere |
| `I-000189` | medium | open | proofread-merge drops a block whose side-by-side row is missing, exits 0, and still counts it in the accounting — a marked-up 定稿 can lose text without any signal |

## Severity summary

- **high**: I-000187, I-000188
- **medium**: I-000182, I-000186, I-000189
- **low**: I-000183, I-000184, I-000185

## The two that matter most, in one line each

- **`I-000188`** — ASR stored a transcript spanning 0–59.0 s of a 73.56 s recording (20 % of speech unreached) as an unqualified success. Attributed by measurement: fresh download 73.561 s, 4× token budget byte-identical, skipped span at speech-level energy, `+20 dB` recovers text while a verified-silent control stays empty.
- **`I-000187`** — an empty caption inventory is recorded as a durable `no-subtitle`, even with a live credential; `no-subtitle` is what admits the paid audio→GPU-ASR branch. Same family as `I-000041` but strictly broader: `I-000041` blames an invalid credential, this was measured with a valid one, so fixing `I-000041` would not close it.

Both are the same failure class as `I-000166`: **the ledger reports success while the fact differs.**

