# T5 — the two-arm hotword measurement on the frozen six-item corpus

**Verdict: `PARTIAL`.** The measurement ran to completion on all six items of both arms, with thresholds
fixed in advance, and returns a **negative result on the list's effect**: across 7.3 hours of audio and 33
shipped terms, the prompt produced **no measurable recovery and no measurable insertion**, and the corpus's
P6 identity bar **failed** for a reason that hand-reading attributes to a decoder degeneration in the
*prompted* arm. `PARTIAL` rather than `CONFIRMS`/`REFUTES` because the protocol's own **P9** condition
(`E < 8`) makes P1/P2 uninformative here — `E = 7`.

Run 2026-09-26 on `chosenecho@192.168.3.21` (WSL, RX 7800 XT gfx1101), repo `d41c257` + the uncommitted
33-entry restoration, `transformers 5.16.1`, `torch 2.9.1+rocm7.2.0`, `check-asr-env` exit 0 with all five
invariants. Command `CORPUS=long ITEM_ORDER=longest-first ab-hotwords-qwen3.sh all`.

## 1. Provenance of the audio — read this before comparing with older figures

The six were **re-downloaded from Bilibili** for this run, because the originals were lost when the 123pan
mount failed auth (register `R3`). They live at `/mnt/e/asr-archive-c6/audio` — a local disk, so nothing
here depends on WebDAV. Identity was cross-checked **before** downloading: the six cids and durations were
diffed against the independent table in
`.mstar/workflows/e2e-23191782-subtitle-publish-webdav/reports/e2e.md`, and all six agree. Every duration
matches the frozen C6 record within 2 s, and all six are AAC `.m4a`:

| item | frozen | measured | Δ |
|---|---|---|---|
| `BV1iddQYQE7D` | 7682 | 7682 | 0 |
| `BV1BdtazGEBE` | 6395 | 6395 | 0 |
| `BV1vNTqzFEve` | 5112 | 5111 | −1 |
| `BV1Y7M4zNEfF` | 2598 | 2598 | 0 |
| `BV11p5qzAE6s` | 2408 | 2407 | −1 |
| `BV1zz5zzFENq` | 2087 | 2087 | 0 |

**These are a fresh fetch, not the bytes the 2026-09-22 measurements used.** A difference between this run
and those figures could come from the source file rather than the engine — which is why the durations were
checked first. The caption leg is likewise a fresh API fetch, not the proofread route: the route on 123pan
is unreadable, and the census labels every span with the basis it used (`caption-only` here), so the
substitution is visible rather than silent.

## 2. Arm identity and the restore

Read back from each arm's own frontmatter, never from the invocation:

| arm | items | `asr_hotwords` | configuration |
|---|---|---|---|
| **A** `with` | 6 | **33** on all six | shipped |
| **B** `without` | 6 | **0** on all six | `DEFAULT_HOTWORDS` reduced to `()` for the arm |
| **R** `repeat` | **1** | **33** | same as A — the single longest item, protocol §7 |

All carry `asr_model_name = Qwen/Qwen3-ASR-1.7B-hf`. Restore is **byte-anchored** and passed:

```
  expected sha256: cf5358107337690fb584bf812c07ec4c55654e305b5665b6b2d3eeb7f1f1a0f7
  actual   sha256: cf5358107337690fb584bf812c07ec4c55654e305b5665b6b2d3eeb7f1f1a0f7
  RESTORE PROVEN: bytes identical to the pre-edit snapshot
```

`verify` on arm A: **6 checked, 0 defects**. Artifact audit discipline as in `guides/t5-artifact-audit.md`.

## 3. The thresholds, and what this run says about each

| clause | bar | measured | verdict |
|---|---|---|---|
| **P1** recoveries | `R ≥ 33` | **R = 0** | **uninformative** — P9: `E < 8` |
| **P2** coverage | ≥ `0.6 × E` terms recover | 0 of 7 | **uninformative** — same P9 condition |
| **P3** insertions | `I ≤ 8` corpus-wide | **I = 0** | **PASS** |
| **P4** concentration | no term > 2 insertions | max = **0** | **PASS** |
| **P5** fabrications | `F = 0` | `F = 0` | **not settled** — `fabrications()` is a declared placeholder, not a measurement |
| **P6** global identity | corpus `ratio(A,B) ≥ 0.95` | **0.941523** | **FAIL** — one outlier, read by hand in §5 |
| **P7** noise floor | `ratio(A,R) ≥ 0.995` | **1.000000**, byte-identical | **PASS** |
| **P8** damage classes | no empty-where-B-has-4; no run of ≥3 identical cues; cue counts within 0.5×–2× | 0; max run 1 (one item 2); all within bounds | **PASS by the letter** — and it did **not** catch §5's defect; see §6 |
| **C4** throughput | ≤ 0.40× realtime | **0.1465× / 0.1379× / 0.1496×** | **PASS** with wide margin |

Verdict mapping applied: `CONFIRMS` needs all of P1–P8, and P6 does not hold. `REFUTES` needs one of
`I > 8` / a term > 2 insertions / any `F` / any P8 class / (`E ≥ 8` and < 0.6×`E` terms recover) — none
applies. **`PARTIAL`** is the third state and applies on its own listed ground, `E < 8`.

## 4. The result: the prompt changed nothing measurable about the terms

`E = 7` — the terms spoken anywhere in the six items: `感性` (7×), `辩证法` (8×), `扬弃` (3×), and
`拉康`/`此在`/`自在`/`齐泽克` (1× each). **Every one has an identical count in both arms:**

| term | A | B | Δ |
|---|---|---|---|
| `感性` | 7 | 7 | 0 |
| `辩证法` | 8 | 8 | 0 |
| `扬弃` | 3 | 3 | 0 |
| `拉康` / `此在` / `自在` / `齐泽克` | 1 each | 1 each | 0 |

So `R = 0` and `I = 0`: **not one term was recovered by the prompt, and not one was inserted by it**, on
7.3 h of the corpus the list was built for.

Four of the six `R2`-restored homophone terms occur here, and each is rendered **identically with and
without the prompt**. That bears directly on why those six were added: the 2026-09-18 measurement that
justified them was the **retired FunASR** engine's, where `扬弃` scored 4 correct vs 57 wrong. Under the
shipping engine, on the same corpus, `扬弃` appears 3 times **in both arms** — the homophone failure the
entries exist to prevent does not reproduce. That is a finding about the engine change, not a proof the
entries are useless: `E = 7` caps what this corpus can say, and `变易`/`实存` never occur at all.

`P3`'s comparison is the useful scale: the proofread wave counted **at least 25** insertion instances on
these same six items under the old engine (a floor, not a total). Under the shipping engine and with the
prompt on, this run counts **0**.

## 5. The P6 failure: one outlier, read by hand

P6 fails corpus-wide at 0.941523 against a 0.95 bar. Per-item ratios:

| item | ratio(A,B) |
|---|---|
| `BV1iddQYQE7D` | **0.857939** ← below 0.90, named as the outlier |
| `BV1BdtazGEBE` | 0.975131 |
| `BV11p5qzAE6s` | 0.978957 |
| `BV1vNTqzFEve` | 0.981977 |
| `BV1zz5zzFENq` | 0.984338 |
| `BV1Y7M4zNEfF` | 0.986208 |

The other five clear 0.97. **Hand-reading the outlier**, which the protocol requires:

In arm A, at `00:23:51,904–00:23:55,794`, is **one cue of 5,289 characters** — inside a 3.9-second window.
A second, at `00:25:38,994–00:25:41,234`, is 2,439 characters. Together 7,728 characters in two cues, out
of A's 39,624. The text is an **English degeneration loop**:

> `…It's impossible.Ah,so in this situation,you,you think,it's very difficult…That is,that is,that is,that is blowing t…`
> …`atisthatis thatisthatisblowingtheairoutThatisthatisthatisthatisblowingthe airoutThatis…`

`blowing` occurs **99** times, `thatis` **41** times, `is` **401** times, inside that single cue.

**This is not a hotword effect.** The caption — an independent transcript — shows the speaker saying a
**short** `It's impossible` at 1435.9 s and then continuing in Chinese; it contains the phrase
`that is`/`blowing the air` **zero** times anywhere, and its Latin-character share is 2.0 %. The English is
not something the list prompted and not something the speaker said at length.

**It is reproducible and arm-specific:** arm R (same configuration as A) reproduces it byte-for-byte —
A and R are byte-identical on this item — and arm B, running the identical audio with an empty list,
produces **zero** cues over 500 characters. Corpus-wide, exactly one item has any cue above 500 characters,
and only in A.

So the honest reading is: on this item, the 33-term prompt is associated with a **decoder degeneration**
that costs A ≈7 700 characters of looped English. Whether the prompt *caused* it or merely failed to
prevent it is not settled by one item — but the correlation is arm-specific, reproducible, and in the
direction that matters, so it is reported rather than filed away as noise.

A decode at 6.1 characters/second on that item against 5.0 for B is the tell that made this findable at
all; every other item sits at 4.9–5.3 for both arms, which is normal speech.

## 6. A defect this run found in the instrument: P8 cannot see a 5 289-character cue

P8's three conditions are "no cue in A that is empty where B has ≥4 characters", "no run of ≥3 consecutive
identical cues", and a cue-count ratio band. **All three pass here** — and one cue of 5,289 characters in a
3.9-second window, 99 repetitions of the same token, sailed through all of them.

The conditions are the engine's known failure modes *expressed as the shapes they usually take*. A single
giant cue is the same failure in a shape none of the three tests names, because "repetition" was written as
*consecutive identical cues* (a run across cues) rather than *repetition within a cue*. The gap is recorded
here rather than patched quietly: the thresholds are frozen for this measurement, and a fix belongs to a
protocol revision that states what it changes and why — exactly as Amendment 1 did for the entry count.

What caught it instead was the P6 outlier rule's requirement to **read the outlier by hand**, plus
characters-per-second as a sanity check. Both are worth keeping for that reason.

## 7. What this measurement establishes

- **The two-arm apparatus works end to end on the real corpus**, on re-fetched AAC audio, with the arm-B
  edit applied and byte-provenly reverted, and `verify` reporting 0 defects on all six items.
- **P3, P4, P7, P8 and C4 pass**; P7 passes with zero headroom consumed (A and R byte-identical on the
  noise item, so the engine is deterministic at this configuration).
- **On the frozen corpus, with `E = 7`, the hotword prompt recovered nothing and inserted nothing.** Every
  exercised term carries the same count with and without it.
- **`扬弃`, `自在`, `此在`, `感性` are rendered identically in both arms** — the FunASR-era homophone failure
  that justified restoring the six does not reproduce under the shipping engine on this corpus.
- **P6 fails, and the failure traces to a reproducible English degeneration loop in the prompted arm** on
  one item, not to hotword insertion.
- **`PARTIAL`**, on P9's `E < 8` ground.

## 8. What it does not establish

`E = 7` is below P9's floor, so this corpus **cannot** settle whether the list earns its place, and a
`PARTIAL` must not be read as a pass or a fail on the list's worth. `P5` is unsettled (`F = 0` is a
placeholder). The degeneration is one item; whether the prompt causes it is a hypothesis this measurement
raises, not one it closes.

The sharpest thing the numbers say is narrow and worth stating narrowly: **on 7.3 h of the corpus the list
was built for, the list changed nothing measurable about any term it contains, while one item shows a
prompted-arm degeneration the unprompted arm does not have.** That is a reason to look harder at the
prompt surface, not a verdict that the list is worthless — and it is exactly the kind of negative result
residual `20260922-proofread-wave · R1` was created to make recordable.

---

**Promoted to:** `.mstar/knowledge/testing-patterns/hotword-list-measurement.md` — this iteration's round
extended that doc with the 2026-09-26 findings (the negative result, the `E < 8` interpretive floor, the
prompted-arm degeneration), the byte-anchored restore correction, and five further traps. The doc is the
reusable method; this guide stays the measurement record with its own raw inputs.

**Promoted tooling:** `guides/assets/ab-hotwords-qwen3.sh` (arm driver) and `guides/assets/census.py`
(per-term R/I/U classifier) are referenced from that doc as reusable artifacts.
