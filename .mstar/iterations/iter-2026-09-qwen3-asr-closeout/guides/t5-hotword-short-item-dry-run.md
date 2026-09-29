# T5 — the short-item dry run (supplementary evidence)

**Status: supplementary, not the T5 verdict.** This is a seventh item outside the frozen six-part
corpus (compass C6), run on 2026-09-26 to prove the apparatus end-to-end before spending ~3 h of GPU
time on the corpus, and to answer a question the protocol raised: whether the two repairs of the same
day changed the measurement's own premises. It does **not** enter the P1–P9 verdict; the corpus figure
is computed from the six C6 items alone.

## Why this item

`BV1wLTP6NE9h:p0`, 448 s — chosen because it is short, it is real AAC `.m4a` (the container the
decoder could not read before `R1`'s repair), and its title names a shipped hotword:
**【对敌攻略】国际劳工仲裁庭，欢迎有识之士加入**. A list whose most conspicuous entry is
`国际劳工仲裁` is the natural place to look for an insertion.

Audio: `/root/e2e-asr/ab-short/audio/BV1wLTP6NE9h.p0.m4a`, sha256
`750124bc7fcf91fa9ce76aaea7418a59476a182f73e027943af24157c318df32`, 3 682 795 B, AAC 48 kHz stereo.
Source of the file: the control host's `e2e-23191782` archive; transferred byte-identically.

## The arms

Run with the driver `{ITERATION_DIR}/iter-2026-09-qwen3-asr-closeout/guides/assets/ab-hotwords-qwen3.sh`
(same script as the corpus run) plus a hand-run comparison arm:

| arm | `asr_hotwords` read back | what it is |
|---|---|---|
| **A** | **33** | the shipped configuration, after `R2`'s restoration |
| **B** | **0** | `DEFAULT_HOTWORDS` reduced to the empty tuple |
| **R** | **33** | same-config repeat of A |
| A-old | 26 | the pre-restoration list (`2548ca9`'s), kept as a comparison |

Arm B's edit was applied and reverted in one command group, and the restore proved twice — scoped
`git status --porcelain` empty **and** `git hash-object` equal to `git rev-parse HEAD:<path>`
(both `92da394e27209eea60bf04b9f0e7498f81c853ef` at the time). The arm identities above come from the
written artifacts' frontmatter, never from the invocation.

## Numbers

| | A (33) | B (0) | R (33) | A-old (26) |
|---|---|---|---|---|
| chars | 2 105 | 2 093 | 2 105 | 2 105 |
| cues | 60 | 57 | 60 | 60 |

- **P6 (global identity):** `ratio(A, B) = 0.987137` — **passes** the ≥ 0.95 bar. 41 shared cue
  buckets, 6 of them differing.
- **P7 (noise floor):** `ratio(A, R) = 1.000000`, and A and R are **byte-identical** (60 shared
  buckets, 0 differing) — passes the ≥ 0.995 bar with no headroom consumed. The engine is
  deterministic at this configuration on this item.
- **P8 (damage classes):** 0 empty cues; longest run of identical cues = 1. No degenerate class.

**Throughput (C4):** A 88.1 s, B 81.9 s, R 79.0 s for 448 s of audio → **0.196×, 0.183×, 0.176×**.
All far inside the ≤ 0.4× ceiling. The first run of the day included model load at 104 s (0.232×);
the steady state is ≈ 0.18×, matching the plan's §13.6 figure of 0.151× on the reference item.

## What it found

**1. `国际劳工仲裁` appears 4× in all three arms, identically.** The hotword did **not** insert on this
item: the speaker genuinely discusses registering `labor-labor-tribunal.org` and naming a body
"国际劳工仲裁". The spans read, in arm A:

> …引导他去这个啊这叫以这叫以彼之道还施彼身啊这**国际劳工仲裁**\啊这个是这个最典型的当然是美国了…
> …不好去处理，所以我们会做一个这么一个**国际劳工仲裁**的这个啊主要是对美啊啊…
> …**国际劳工仲裁**的话，它主要是对美啊对美对这个第一世界进行一个意识形态攻势啊…
> …什么国际劳工论坛啊，什么东西的国际劳工观察，然后我们搞一个就**国际劳工仲裁**，干他啊…

This is exactly the negative control `20260922-proofread-wave · R1` demands and the reason its own
finding is stated as "an unknown share of hits are insertions" rather than "hits are insertions" —
`R1` itself keeps the same kind of counter-evidence for 拉康/辩证法/此在/实存. A hotword hit is not
automatically an insertion, and this item is a case where it is not.

**2. On this item the 33-term list changed almost nothing.** `ratio(A33, A-old26) = 0.994774`; the
differing regions are `他`/`它` homophones, one `上`/`NG` fragment, and punctuation — none of them one
of the six restored terms. The item never speaks 扬弃/自在/变易/此在/感性/实存 (it is about a labour
tribunal), so a single item speaking none of them cannot test them. That is the protocol's P9
"interpretive floor" in miniature and the reason P9 exists.

## What it does **not** establish

Not a corpus-wide claim (one 448 s item, one channel, one engine). Not the T5 verdict — the P1–P9
bars are computed on the six C6 items. Not evidence about the six restored terms, which this item
never speaks. Not a per-term verdict on any term the corpus never utters.

It **does** establish that the apparatus works on the shipped configuration: real AAC `.m4a` decodes
through `R1`'s fallback, the 33-entry list is written and read back, the restore discipline holds, the
noise floor is measurable and zero, and the throughput gate is met with wide margin.
