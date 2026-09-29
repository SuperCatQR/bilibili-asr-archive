# T5 — the short-corpus result (supplementary, not the verdict)

**Status: a real measurement, with a narrower reading than the corpus verdict.** Run 2026-09-26 over the
three-item ≤10 min corpus admitted by the protocol's **Amendment 3**. It reports what that instrument can
settle and, in §4, what it cannot. The P1–P9 verdict remains the six-item corpus's job.

## 1. What ran

Item set = **every** local item with `duration_s ≤ 600 s`, taken whole:

| item | duration | title |
|---|---|---|
| `BV1aRTA6mEGF:p0` | 571 s | 【项目预告】150元在线装配电工培训和电工论坛 |
| `BV132XgBjER4:p0` | 500 s | 【实事求是】对某特定行为的披露和定性 |
| `BV1wLTP6NE9h:p0` | 449 s | 【对敌攻略】国际劳工仲裁庭，欢迎有识之士加入 |

Total 1 520 s = 25.3 min. Fifteen .m4a's exist locally under 1 200 s; only these three are ≤ 600 s.

Command: `CORPUS=short /root/e2e-asr/tools/ab-hotwords-qwen3.sh all` — one driver for both corpora, so the
arm-B source edit and its restore proof exist once. Host `chosenecho@192.168.3.21` (WSL, RX 7800 XT
gfx1101), `transformers 5.16.1`, `torch 2.9.1+rocm7.2.0`, repo at `d41c257` + the uncommitted 33-entry
restoration, `check-asr-env` exit 0 with all five invariants.

## 2. Arm identity — read back, never assumed

From each arm's own frontmatter (`asr_hotwords`), one row per item:

| arm | entries | what it is |
|---|---|---|
| **A** `with` | **33** on all 3 items | the shipped configuration |
| **B** `without` | **0** on all 3 items | `DEFAULT_HOTWORDS` reduced to `()` for the arm |
| **R** `repeat` | **33** on all 3 items | same configuration as A |

All three carry `asr_model_name = Qwen/Qwen3-ASR-1.7B-hf`, `asr_chunk_seconds = 180`, `source = asr`.

**Restore proof (protocol §4 as amended by 3a).** `asr.py` sha256 before the edit
`cf5358107337690f…a0f7`; after the B arm the driver requires that same digest and logs:

```
=== restore proof (byte-anchored)
  expected sha256: cf5358107337690fb584bf812c07ec4c55654e305b5665b6b2d3eeb7f1f1a0f7
  actual   sha256: cf5358107337690fb584bf812c07ec4c55654e305b5665b6b2d3eeb7f1f1a0f7
  (context) working blob 35074ba7… / HEAD blob 92da394e…
  (context) working tree differs from HEAD — expected when the fix is uncommitted
  RESTORE PROVEN: bytes identical to the pre-edit snapshot
```

That last line is the whole point of Amendment 3a: this host's fix is **uncommitted**, so a git-anchored
restore would have reverted it to the 26-entry list and its git-shaped proof would have **passed**. The
byte-anchored proof reports the divergence instead of acting on it.

## 3. The clauses this corpus can settle

| clause | bar | measured | verdict |
|---|---|---|---|
| **P6** global identity | corpus `ratio(A,B) ≥ 0.95` | **0.98107** | **PASS** |
| **P7** noise floor | `ratio(A,R) ≥ 0.995` on every item | **1.000000**, all three **byte-identical** | **PASS** |
| **P8** damage classes | no degenerate class | 0 empty cues; longest identical run = 1; cues 63/63, 75/82, 60/57 | **PASS** |
| **C4** throughput | ≤ 0.40× realtime | **0.1803× / 0.1434× / 0.1467×** (A/B/R) | **PASS** |

Per item, `ratio(A,B)`: `BV132XgBjER4` 0.996608 (7 of 63 shared buckets differ), `BV1aRTA6mEGF` 0.966848
(11 of 58), `BV1wLTP6NE9h` 0.987137 (6 of 41).

The throughput ceiling is met with wide margin, and A is the slowest arm — the prompt lengthens the
decode slightly (0.1803× vs 0.1434×), which is the expected direction and still 2.2× inside the gate.

## 4. The clauses this corpus **cannot** settle — stated before the run

| clause | bar | measured | why it does not count |
|---|---|---|---|
| **P1** recoveries | `R ≥ 33` | **R = 0** | **Uninformative**: P9 says an `E < 8` corpus leaves P1 uninformative, and `E = 6`. |
| **P2** coverage | ≥ `0.6 × E` terms recover | 0 of 6 | Same P9 condition. |

`E = 6`, the terms the census counted as exercised on **these three items**: `国际劳工仲裁` (4×),
`国际劳联`, `攻势`, `智利`, `亚美利坚` — all five rendered by both arms — plus `马恩牌`, which arm A rendered
and arm B did not. The other **27 of 33 terms are never spoken** by these three items.

(An earlier draft of this section named the wrong set: it listed `拟态论` and omitted `马恩牌`. `拟态论` is
real but occurs on `BV1eGJ46mEHQ`, an item **outside** this corpus — that hit belongs to the eleven-item
survey, not to `E`. Corrected against `census.json`'s own per-term rows, which is what `E` is computed from.)

**The six `R2`-restored terms are untestable here in the strongest sense:** 扬弃, 自在, 变易, 此在, 感性,
实存 have **zero** occurrences across all eleven short items on disk — not merely across the three. A corpus
that never speaks a term cannot measure that term, and a null must not be read as a negative.

`F` (fabrications) reads 0, and that 0 is a **placeholder, not a measurement**: `census.py`'s
`fabrications()` returns 0 by construction and says so, because a fabrication needs a span-level reading the
tool does not perform. P5 is therefore **not settled** by this run either. Reported so that nobody reads the
zero as evidence.

## 5. The one finding that is a measurement

**`R` = 0 on this corpus: no term was recovered by the prompt on these three items.** Five of the six
exercised terms (`国际劳工仲裁`, `国际劳联`, `攻势`, `智利`, `亚美利坚`) are rendered **identically by
both arms** — they are *inherited*, not recoveries, which is exactly the distinction protocol §6 draws and
what residual `20260922-proofread-wave · R1` says occurrence-counting cannot make. The prompt changed
punctuation and some `他`/`它` homophones; it did not add or repair a hotword.

**One candidate insertion, and it is the R1 class:**

| item | term | arm A | arm B | arm R | caption over the span |
|---|---|---|---|---|---|
| `BV1wLTP6NE9h:p0` | `马恩牌` | **马恩牌** ×1 | `嘛牌` ×1 | **马恩牌** ×1 | `对其他妈啊` |

At 116.56–131.20 s the speaker is discussing what to call the body. Arm A writes `你打马恩牌我`, arm B writes
`你打嘛牌我也`, the caption writes `对其他妈啊`, and A/R are byte-identical so this is reproducible rather
than noise. `马恩牌` is on the shipped list; `嘛牌`/`妈` are not. This is a hotword-list token appearing where
the caption does not carry it — the failure mode `R1` names, at one occurrence.

It must not be over-read: one occurrence, one item, and the caption is itself a machine transcript rather
than a human one, so "the speaker said something else" rests on the caption being right at that span. That
is why it is reported as a candidate with its span shown, not as a settled insertion. On the protocol's own
bars it is well inside `P3` (`I ≤ 8`) and `P4` (no term > 2 insertions).

## 6. A defect this run found — in the instrument, not the product

The first census run reported **`R = 4`**. That was wrong, and the error was in my census tool, not in the
transcripts: it matched arm B's text by **exact srt-timestamp equality**, and the two arms segment
independently, so the same speech lands in buckets whose boundaries differ by a few hundred milliseconds.

`BV1wLTP6NE9h`, arm A's cue `00:01:09,680`–`00:01:24,160` vs arm B's `00:01:09,840`–`00:01:24,160` — same
speech, different key. The exact-key lookup missed arm B's text, read B as empty, and classified every
inherited occurrence as a recovery. All four `国际劳工仲裁` occurrences were misread this way, plus
`攻势`, `智利`, `国际劳联` and `亚美利坚` — inflating `R` from 0 to 4 and making five terms look recovered
that are in fact inherited.

The fix: `arm_b_text_over()` compares by **time overlap**, and says in its own docstring why the protocol's
`shared bucket` figure is still keyed by exact timestamps (that number is *about* segmentation agreement,
so exact keys are right for it) while this comparison is about which words each arm rendered, where any
overlap is the right basis. The docstring carries the measured example so the next reader cannot quietly
re-introduce the shortcut.

This is recorded because it is the failure mode that matters: a census that over-reports recoveries is a
census that would validate the hotword list on evidence the list did not earn. It was caught by checking the
tool's number against the arms' own text rather than trusting it.

## 7. What this run establishes

- The apparatus runs end to end on the shipped configuration over a real multi-item corpus, on real AAC
  `.m4a` files, with the arm-B edit applied and byte-provenly reverted.
- **P6, P7, P8 and C4 pass**, and P7 passes with zero headroom consumed: arm A and arm R are byte-identical
  on all three items, so the engine is deterministic at this configuration and any A-vs-B difference is
  speech, not sampling.
- On this corpus the hotword list **recovered nothing** and produced **one candidate insertion**.
- `P1`, `P2` and `P5` are **not settled here** — by the protocol's own P9 rule for the first two, and by the
  tool's declared placeholder for the third.

## 8. What this run does not establish

It is **not** the T5 verdict, and neither a PASS nor a FAIL from §3 transfers to `P1`/`P2`. Three items,
25.3 min, one channel, one engine, and a set that speaks 6 of 33 terms cannot decide whether the list earns
its place. The six-item corpus remains the only instrument that can, and this run's value is that it proves
the instrument works before it is spent.

It also says nothing about the six `R2`-restored terms: the items never speak them.
