# T5 — the second short-corpus result (`short2`, nine items)

**Status: a real measurement with a declared limit, and the second substitute for the frozen corpus.**
Run 2026-09-26 over nine items ≤600 s, staged on `/mnt/e` (a local disk) rather than 123pan. The P1–P9
verdict remains the six-item corpus's job — which is currently **unreachable**; see §7.

## 1. What ran, and why this set

The first short set (`short`, three items) was already measured. This set is the **remainder** of a deeper
sweep for parts under ten minutes: pages 1–10 of the uploader's 1 691 videos (210 scanned, 3 pages lost to
rate-limiting or a shape error), which found **12** parts at ≤600 s. Three of those twelve were already
measured in `short`, so nine remain — and they are the sweep's remainder, not a pick. No item was added or
dropped for how it scored.

| item | duration | title |
|---|---|---|
| `BV11Z421N7AM:p0` | 565 s | 【行动建议】把这两类妄人从我们的团队里清除出去 |
| `BV16D7azJEcm:p0` | 560 s | 【行动建议】与其害怕死亡，更应害怕衰老 |
| `BV1kEVszWEbm:p0` | 560 s | 【实事求是】这不是巧合，这是历史的真实的普遍性 |
| `BV1acKfzEEWS:p0` | 539 s | 【实事求是】为什么职业革命家一定要学习黑格尔哲学 |
| `BV1DT3UzwEbj:p0` | 529 s | 【实事求是】心之三贼：但是、一直、其实 |
| `BV1qR7az2EzY:p0` | 469 s | 【随便聊聊】如何看待陈腐者 |
| `BV1WQpBewEyZ:p0` | 431 s | 【逃生通道】造神容易拜神危险 |
| `BV1aAhLzsENb:p0` | 374 s | 【实事求是】大勇者必有大怯 |
| `BV1YFEUzpEsT:p0` | 74 s | 【实事求是】5000元真伪现场探访 |

4 101 s = 68.3 min per arm; three arms = 205 min of audio. Command
`CORPUS=short2 ITEM_ORDER=shortest-first ab-hotwords-qwen3.sh all`, same one driver, same host.

**Two items carry no caption track at all** (`BV1DT3UzwEbj`, `BV1aAhLzsENb`) — the API returns zero tracks,
twice checked. They are recorded that way rather than replaced, and the census reports `route=0` for them.

## 2. Arm identity and the restore

From the arms' own frontmatter, all nine items each:

| arm | `asr_hotwords` | 
|---|---|
| **A** `with` | **33** on all 9 |
| **B** `without` | **0** on all 9 |
| **R** `repeat` | **33** on all 9 |

Restore proof is byte-anchored and passed:

```
  expected sha256: cf5358107337690fb584bf812c07ec4c55654e305b5665b6b2d3eeb7f1f1a0f7
  actual   sha256: cf5358107337690fb584bf812c07ec4c55654e305b5665b6b2d3eeb7f1f1a0f7
  RESTORE PROVEN: bytes identical to the pre-edit snapshot
```

## 3. The clauses this corpus settles

| clause | bar | measured | verdict |
|---|---|---|---|
| **P6** global identity | `ratio(A,B) ≥ 0.95` | **0.980279** | **PASS** |
| **P7** noise floor | `ratio(A,R) ≥ 0.995` every item | **1.000000**, all nine **byte-identical** | **PASS** |
| **P8** damage classes | no degenerate class | 0 empty cues where B has ≥4 chars; longest identical run = 1 | **PASS** |
| **C4** throughput | ≤ 0.40× realtime | **0.1573× / 0.1161× / 0.1173×** | **PASS** |

Per item `ratio(A,B)`: 0.942278 (74 s, the shortest) · 0.974831 · 0.976365 · 0.980831 · 0.981355 ·
0.982482 · 0.982639 · 0.984234 · 0.991055. Nine of nine clear 0.94; none falls below P6's outlier line.

## 4. P1/P2 again **uninformative**, and worse than the first short set

`E = 3` — three terms spoken anywhere in these nine items: `黑格尔` (12×), `自为` (3×), `观念论` (1×).
P9's own rule (`E < 8` ⇒ P1/P2 uninformative) applies, more strongly than in the three-item set (`E = 6`).
The other **30 of 33 terms are never spoken**.

**Every one of the three is rendered identically by both arms** — verified occurrence by occurrence:

| item | term | A | B | R |
|---|---|---|---|---|
| `BV1acKfzEEWS` | `黑格尔` | 12 | 12 | 12 |
| `BV1acKfzEEWS` | `观念论` | 1 | 1 | 1 |
| `BV1WQpBewEyZ` | `自为` | 3 | 3 | 3 |

So **`R = 0` and `I = 0`**: on this corpus the prompt recovered nothing and inserted nothing detectable.
That is a weaker statement than it sounds — with `E = 3`, all three terms inherited, this set could not
have shown a recovery even if the list worked perfectly.

`P5` remains **unsettled**: `F = 0` is still `fabrications()`'s declared placeholder, not a measurement.

## 5. Throughput — the one clause this corpus measures well

Arm A is the slowest (0.1573× vs B's 0.1161×): the 33-term prompt costs **≈35 % more wall time** on the
same audio, consistently in the expected direction. All three arms sit far inside C4's 0.40× ceiling.

## 6. What this run establishes, and what it does not

**Establishes:** the apparatus works end to end over a nine-item corpus on a **local disk**, with the
arm-B edit applied and byte-provenly reverted; P6, P7, P8 and C4 pass; the engine is deterministic at this
configuration (all nine items byte-identical between A and R); and the prompt costs ≈35 % wall time.

**Does not establish:** anything about whether the hotword list earns its place. `E = 3`, P1/P2
uninformative by the protocol's own rule, P5 unsettled. Neither this nor the first short set is a verdict,
and a PASS from §3 must not be read as one.

## 7. The measurement this replaces, and why it cannot run

The frozen six-item corpus (compass C6) is the **only** instrument that can settle P1/P2, and its audio was
lost on 2026-09-26: the 123pan WebDAV mount began answering every read with `401 Unauthorized` while
directory listings still succeeded from cache, and a re-seed of the T5 arms — whose `setup` deleted the
staged arms before copying from that mount — destroyed the local copies. An exhaustive search found no
other copy (`/root`, `/mnt/e`, the control host, the rclone VFS cache).

Registered as `20260924-qwen3-asr-transformers · R3` (high). The driver is hardened so it cannot recur: it
now verifies the audio source is readable **before** removing anything, reuses already-staged arms, and
requires `FORCE_SETUP=1` to rebuild.

**Update, same day: the six were re-staged.** They were re-downloaded from Bilibili with the product's own
downloader into `/mnt/e/asr-archive-c6/audio` (a local disk, no WebDAV dependency), identity cross-checked
against the independent cid/duration table in the `subtitle-publish` e2e report before any download, and every
duration matches the frozen C6 record within 2 s. The six-item corpus run therefore follows, and its result —
not this one — is what the P1–P9 verdict comes from. Nothing in this guide should be read as covering those
six items: this is the nine-item substitute, and it stays a substitute.

**A limit this run shares with the first short set, stated plainly:** the uploader's short videos are
mostly not about the subjects the hotword list exists for. Across the twelve parts under ten minutes, the
exercised terms are a handful of philosophical names; the six Hegel homophones (`R2`'s restoration) and the
Latin-script terms appear **zero** times. A corpus drawn from sub-ten-minute clips therefore cannot test
the list, however many items it holds — that is a property of the source, not of the sample size.
