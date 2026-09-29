---
iteration_id: iter-2026-09-qwen3-asr-closeout
plan_id: 20260924-qwen3-asr-transformers
guide: t5-hotword-measurement-protocol
date: 2026-09-25
subject: The two-arm hotword measurement under the shipping Qwen3-ASR engine — pre-declared protocol
decision: pre-declared (thresholds fixed before any arm runs)
status: awaiting execution
---

# T5 — hotword-list measurement protocol (pre-declared)

Reference document. Everything a reader at HEAD needs to run the measurement and to judge it is on this
page: the arms, the command, the numbers that decide the verdict, the noise floor, the artifact paths, and
the traps that must abort the run. The numbers in §5 are **fixed now**; a bar chosen after seeing the data
measures nothing (`{KNOWLEDGE_DIR}/testing-patterns/hotword-list-measurement.md`, Method step 4: "A bar chosen
after seeing the number measures nothing").

## 1. What T5 settles, and what it does not

The question is narrow: **does the shipped `DEFAULT_HOTWORDS` list earn its place under the engine that
ships**, as a free-form prompt? The list reaches the model as `prompt` (`bilibili-asr-archive/src/bili_asr/asr.py:697`),
not as a decode-time bias — the mechanism changed with the engine, so every FunASR-era hotword figure is
stale for this run (`README.md:170-176`).

The failure mode that matters is residual `20260922-proofread-wave · R1` (high, `.mstar/projects/_default/residuals.json`):
the list is also an **insertion source** — it wrote tokens into transcripts where the speaker said something
else. That row also names why the project's own scoring missed it: counting surface occurrences cannot
separate a recovered term from an injected one. **This protocol counts them separately.**

Not settled here: whether any individual term should be added, removed or reordered (that is a change to
shipped configuration, not a measurement); the corpus-wide quality of the engine (one corpus, six items);
cross-engine comparison against the stored FunASR text (excluded by compass C3).

## 2. The two arms, declared

| arm | root | configuration |
|---|---|---|
| **A — with** | `/root/e2e-asr/ab-hotwords-qwen3/with` | shipping engine, shipped `DEFAULT_HOTWORDS`, shipped prompt |
| **B — without** | `/root/e2e-asr/ab-hotwords-qwen3/without` | same engine/audio/model, `DEFAULT_HOTWORDS` literal temporarily reduced to the empty tuple |
| **R — repeat** | `/root/e2e-asr/ab-hotwords-qwen3/repeat` | byte-for-byte the same configuration as A (noise floor, §7) |

Both treatment arms use the engine that ships (`asr.py:1`); compass C3 fixed them single-engine, which also
keeps the measurement on the product path the plan's §6 T5 hedged about (`re-run under both engines`) — the
plan's own §5 D2 consequences note that a cross-engine comparison would have to run as a one-off script
against a retired revision. This one runs `bili-asr asr` for every arm; the driver only orchestrates the
arms and reads the census.

**Arm B is a temporary source edit, and it has to be.** `_extra_hotwords` skips every term already in
`DEFAULT_HOTWORDS` (`asr.py:257-266`, the skip at `:265`) and `default_config()` only ever appends
(`asr.py:286` `hotwords=DEFAULT_HOTWORDS + _extra_hotwords(...)`), so `BILI_ASR_HOTWORDS` can **add** and can
never **subtract**. The removal is exact: the literal spans `asr.py:100`–`:164` (open paren to close paren,
33 terms — see Amendment 1); reduce it to `DEFAULT_HOTWORDS: tuple[str, ...] = ()` and touch nothing else in the file. Leave
`BILI_ASR_HOTWORDS` unset for every arm (a precondition check asserts it).

**Expected read-back, per arm, from the written artifact** — never from the invocation. `ASRRunner.provenance()`
publishes `hotwords` as `_redact(",".join(config.hotwords))` (`asr.py:815`) and `write_archive` maps it to the
frontmatter key `asr_hotwords` (`bilibili-asr-archive/src/bili_asr/archive.py:492-493`):

| arm | `asr_hotwords` in `transcripts/md/*.md` | entries |
|---|---|---|
| A | the 33 shipped terms in literal order, comma-joined — `未明子,主义主义,拟态论,国际劳工仲裁,国际劳联,马恩牌,攻势,智利,根正苗红,亚美利坚,黑格尔,海德格尔,拉康,齐泽克,德勒兹,康德,观念论,本体论,现象学,辩证法,定在,自为,理念性,扬弃,自在,变易,此在,感性,实存,International Employment Matters Tribunal,International,Employment,Tribunal` | **33** |
| B | `""` (the empty join: `asr.py:815` returns the value unchanged when there is nothing to redact) | **0** |

If an operator extra is present the counts move (`33 + n`, `0 + n`) and the delta must still be exactly the
33 shipped terms; **if `asr_hotwords` does not match this table, the arm is void** — do not explain the
difference away. Never trust a run whose list cannot be read back.

> **Amendment 1 (2026-09-26, before any arm of this protocol ran).** This table first read **26**, taken
> from the list as it stood at `2548ca9`. That list was itself the defect: the rewrite that introduced
> the Qwen3 boundary had silently deleted the six homophone entries of 2026-09-17 (扬弃 自在 变易 此在
> 感性 实存), re-added `ITEM`/`AITEM` after `ef5e1e8` deliberately removed them, and dropped the three
> Latin shards — none of it authorised, mentioned in the commit, or asserted by a test. The list is now
> restored to its documented 33 entries (commit `83ba8d0`), so every number in this protocol that was
> derived from the count is restated for 33. The *rules* did not change, only the constants they are
> quoted against; a measurement whose list cannot be read back is still void.

## 3. Command, seeding and run order

One arm root is one archive: `manifest/manifest.jsonl` (`asr.py`-adjacent writer,
`bilibili-asr-archive/src/bili_asr/manifest.py:39`), `coordinator/` (a lock file only — the `asr` path
writes no attempt ledger, see Amendment 2), and `transcripts/{srt,txt,md,raw}/`
(`archive.py:464-470`). Per arm, seed the six rows and stage the six audio files:

```bash
# on the target host, per arm root R in {with,without,repeat}
#   R/audio/<bvid>.p0.m4a        hardlink or copy — NEVER a symlink
#   R/manifest/manifest.jsonl    one row per part:
#     {work_id: "<bvid>:p0", bvid, page_index: 0, cid, title, duration_s, pubdate_str, status: "audio_ok"}
```

`--pending` selects `audio_ok` rows (`cli.py:2184-2189`), and a row with no caption document falls to the
ASR branch, whose default audio path is `audio/<stem>.m4a` with `stem = <bvid>.p0`
(`cli.py:2251`, `archive.py:34-38`). The audio path policy is strict: the recorded path must be exactly two
parts, `audio/<name>.m4a|.flac` (`bilibili-asr-archive/src/bili_asr/path_policy.py:16-29`), the open is
`O_NOFOLLOW` (`:60-65`) and a symlinked entry point is refused (`:101-106`) — a symlinked staging directory
silently resolves to no file and the row fails as `invalid audio path`. Hardlinks are regular files and are
accepted.

```bash
export HSA_ENABLE_DXG_DETECTION=1                     # without it torch.cuda.is_available() is False here
export BILI_ASR_MODEL=<in-project ASR dir>            # D9/D10: local dirs, no runtime fetch
export BILI_ASR_ALIGNER_MODEL=<in-project aligner dir>
export BILI_ASR_MODEL_ID=Qwen/Qwen3-ASR-1.7B-hf       # recorded identity; never reaches the loader
export HF_HUB_OFFLINE=1
unset BILI_ASR_HOTWORDS BILI_ASR_CHUNK_SECONDS
bili-asr asr --pending --archive-root /root/e2e-asr/ab-hotwords-qwen3/with
```

Run order — **reference item first** (compass C4/§13.6: the 47.4 min `BV13hEB63En5.p0`, plan
`{PLAN_DIR}/20260924-qwen3-asr-transformers.md:430`), as a smoke on each arm before the corpus; then arm A
over the six items, then arm B, then arm R. If the reference item's audio is not staged on the target host,
record it as unavailable and run the corpus longest-first instead — never substitute a different item
silently. One invocation per arm keeps one runner across its rows (`README.md:282-291`). Record each run's
window from the invocation itself, the venv that executed it, and the `check-asr-env` result (§8);
the arm's own evidence is its artifacts' frontmatter and the manifest row's `archived` status, because
`asr` writes no attempt ledger (Amendment 2).

## 4. Restore discipline — prove it twice, or the run is void

`asr.py` is returned to `HEAD` before arm B is treated as valid, by whichever route the driver uses
(`git checkout -- <path>` is the prior round's route):

```bash
git -C /root/workspace/bilibili-asr-archive status --porcelain -- bilibili-asr-archive/src/bili_asr/asr.py
git -C /root/workspace/bilibili-asr-archive hash-object    bilibili-asr-archive/src/bili_asr/asr.py
git -C /root/workspace/bilibili-asr-archive rev-parse HEAD:bilibili-asr-archive/src/bili_asr/asr.py
```

**Both** checks must pass: the scoped porcelain prints nothing, **and** the two blob hashes are equal.
Either failing → the run is not reportable, and `asr.py` is left restored before anything else happens.
Scope the porcelain to `asr.py`: the whole-tree form is not empty on either checkout (the control root
carries the PM-owned `.mstar/**` modifications; the host carried an untracked `.env.bak-*`). A precondition
counter that removes the 33 terms must **abort on 0** as well as on any other number (assert 33 before, 0
after) — the prior round's counter used BRE alternation that returned 0 and correctly refused
(knowledge note, Method step 2). The empty tuple is inert only as an edit: `ASRConfig.hotwords` type-checks
each *member* and raises only on a non-string or blank one, so `()` passes (`asr.py:219-222`); `:697` then
evaluates the falsy branch and passes no `prompt` at all — a real decode path, not a stub.

## 5. Pre-declared thresholds — numbers, fixed now

**Basis of every comparison.** Text: `transcripts/txt/<stem>.txt`, compared with
`difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()` — the basis the knowledge note fixes (its
"state the ratio's basis" trap), because the library default `autojunk=True` scores the same pair
differently. Timing: cues keyed by their **srt timestamp span**; a *shared bucket* is a span present in both
arms. Per-item figures are reported for all six items; the bars apply to the corpus figure computed on the
six items concatenated in bvid order.

**Per-term census** — for each of the 33 shipped terms, over the whole corpus:

- `R` **recoveries** — the term appears in arm A at a span where arm B has a homophone or an omission, and
  the term is **correct against the audio/subtitle route** (§6); a term that appears nowhere in arm B is only
  an insertion *candidate* until §6 decides it.
- `I` **insertions** — the term appears in arm A at a span where the speaker said something else: arm B
  differs and the caption route over the same span is unrelated text (residual R1's criterion, less its
  confidence leg, which does not exist under this engine — compass D4 removed per-cue scores, so the third
  leg is replaced by "arm B differs at the same span" and the substitution is stated in the verdict).
- `F` **fabrications** — a character present in neither arm and not spoken: the residual's worst measured
  class (two instances under the old engine).
- `U` **unresolved** — a span no reading decides. `U` is excluded from `R` and `I` and reported as its own
  count; it is never quietly folded into either.

Let Let `E` = the number of shipped terms **exercised** — occurring in either arm at least once — assessed
against the audio/caption route, not against arm A alone (a term present only in A is an insertion
candidate, never evidence of exercise). Let `R_term` be a single term's recovery count, so `R = Σ R_term`.

| # | clause | rule | why this number |
|---|---|---|---|
| P1 | recoveries | `R ≥ 33` corpus-wide | one recovery per shipped term on average over 26 282 s. Amendment 1 raised this from 26 to 33 and, more importantly, restored the term the older precedent actually measured: the 2026-09-18 run (33 entries, 114.5 min, **+34 recoveries**) was **`扬弃` alone** (4 correct → 38). `扬弃` is in the shipped list again, on the same audio family, so that precedent now bears on this bar instead of being excluded from it — which is why 33 remains a floor and still not a forecast: it is one term's measured recovery applied across 33 terms. |
| P2 | exercise coverage | at least `0.6 × E` exercised terms have `R_term ≥ 1` | three-fifths of *terms* must recover, not just three-fifths of *hits*: P1 alone could be satisfied by `扬弃` contributing all 33 on its own, which the 2026-09-18 precedent shows is not a hypothetical. |
| P3 | insertions | `I ≤ 8` corpus-wide | the proofread wave measured these same six items under the old engine and counted **at least 25** instances — `13 × 国际劳工仲裁`, `≥9 × 未明子`, `3 × 马恩牌` — across eight shipped terms, plus **2 fabrications** (the other five terms are named without a count, so 25 is a floor, not the total). 8 is roughly a third of that floor, on the same six items, falsifiable by the same method. |
| P4 | concentration | no single term carries more than `2` insertions | one term cannot eat the P3 budget. |
| P5 | fabrications | `F = 0` | the one class no budget excuses. |
| P6 | global identity | corpus `ratio ≥ 0.95`; per-item outliers (any item `ratio < 0.90`) named individually | carried verbatim from the knowledge note's ≤5 % bar; the old run measured 2.48 %. |
| P7 | noise floor | the R-vs-A comparison of §7 must reach `ratio ≥ 0.995` | 0.5 % of same-configuration headroom before a 5 % treatment bar becomes unreadable. Below it the verdict is `not interpretable at this bar`. |
| P8 | damage classes | no cue in A that is empty where B has ≥4 characters; no run of ≥3 consecutive identical cues in A; any item with `cue_count(A) < 0.5×` or `> 2×` `cue_count(B)` is read by hand and reported | the engine's known degenerate failure modes (repetition, degenerate windows, plan §13.6 defects), in numbers rather than adjectives. |
| P9 | interpretive floor | if `E < 8` the recovery clauses P1/P2 are declared **uninformative** | five-of-six terms inert on a lecture that never speaks them is a null, not a refutation (knowledge note, "What it did not establish"). |

**Verdict mapping, written before the run.**

- **CONFIRMS** — all of P1–P8 hold.
- **REFUTES** — any of: `I > 8`; some term `> 2` insertions; any `F`; any P8 class appears; or (`E ≥ 8` and
  fewer than `0.6 × E` exercised terms recover).
- **PARTIAL** — the third state, and a legitimate outcome: fewer than 4 of 6 items complete on both arms,
  or `E < 8`, or `U > 12` corpus-wide, or the P7 floor is not reached. The completed items are reported as
  completed and the rest as not run — no extrapolation (`delivery-compass.md` risk register).
- A **negative** verdict is recordable, not a failure of the round: the residual exists precisely because a
  hotword list that injects is worse than a list that merely under-recovers.

No threshold may be edited after the first arm runs. A number found to be wrong is an **amendment**: the
original stays on this page with the reason and the data that changed it, recorded in the results guide.

## 6. Reading a span: recovery vs insertion

For each candidate span of a shipped term in arm A: (1) take arm B's text over the same timing bucket;
(2) take the caption route for that item. The route is already on disk, built by the 2026-09-22 proofreading
wave and **not** re-derived here:
`/mnt/123pan/bili-asr-e2e/proofread-transcripts/align/<bvid>.p0.alignment.jsonl`, whose records carry
`{start, end, kept, reason, similarity, asr_text, ai_text, hotwords_asr, hotwords_ai, asr_segments}` — one
record per span, with the caption side in `ai_text` and the pre-existing ASR side in `asr_text`
(**FunASR-era**: it is the caption route and the span map that carry over, never that engine's text as a
stand-in for arm A or B). `hotwords_asr` / `hotwords_ai` per record are the same token-in-run-provenance
test residual R1 used, so the caption leg needs no new extraction. (3) read the span only when both
disagree with A.
Record, per candidate: `start`, `end`, arm A cue text, arm B text, caption text, class (`R`/`I`/`U`),
and one line of reason. Where the alignment record already classifies the span, quote its `reason` and
`similarity` rather than re-judging it. A term present in A and B identically is **inherited**, not a
recovery: it has no place in `R`. Counting occurrences is exactly what R1 says cannot separate the classes, so `R` exists only
where B is worse and the term is right.

## 7. Noise floor

Arm R is a same-configuration repeat of arm A over the **reference item** (or, if that audio is unavailable,
the longest corpus item — `BV1iddQYQE7D.p0`, 7682 s, the one long enough to expose a chunk-boundary defect at
the 180 s cap). Report `ratio(A, R)` on the raw txt over shared cues, the shared-bucket count and the count of
differing shared buckets. **Without this number the measurement is not reportable.** The 2026-09-18 repeat
was byte-identical (floor 0.0000 %, 0 of 1400 shared cues differing); this one is measured, never assumed,
and it controls arm A's configuration only — arm B is a single sample in both rounds.

## 8. Scope, environment, corpus

- **Corpus (compass C6):** the six UID-23191782 parts `BV11p5qzAE6s`, `BV1BdtazGEBE`, `BV1iddQYQE7D`,
  `BV1vNTqzFEve`, `BV1Y7M4zNEfF`, `BV1zz5zzFENq`; 26 282 s ≈ 7.30 h; audio at
  `/mnt/123pan/bili-asr-e2e/asr-vs-subtitle/audio/<bvid>.p0.m4a`; per-item durations are read from the
  on-disk frontmatter (7682, 6395, 5112, 2598, 2408, 2087 s).
- **Host (compass C5):** `chosenecho@192.168.3.21` (WSL, gfx1101). This is a **measurement environment**,
  not a real-machine E2E acceptance gate — the operator authorised the measurement there, and the
  `mstar-e2e` workflow still owns machine acceptance.
- **Per-run environment record:** the venv that ran, `HSA_ENABLE_DXG_DETECTION=1`, and
  `python -m bili_asr check-asr-env` (script `bilibili-asr-archive/scripts/check_asr_env.py`; CLI entry
  `cli.py:601-602,3439`) exiting 0. Two venvs are interchangeable on that host, so an unrecorded run cannot
  be told from its sibling.
- **Partial coverage:** a run that completes four of six items reports four of six. Per-item results land as
  they arrive; nothing is extrapolated.

## 9. Where the artifacts land, and what the verdict does

| path (target host unless noted) | what |
|---|---|
| `/root/e2e-asr/ab-hotwords-qwen3/{with,without,repeat}/` | the three arms: `manifest/`, `coordinator/`, `transcripts/{srt,txt,md,raw}/` |
| `/root/e2e-asr/ab-hotwords-qwen3/CENSUS.md` and `census.json` | the per-item, per-term `R`/`I`/`F`/`U` sheet with its spans and reasons; the noise-floor pair; the amendment log (§5) |
| `/mnt/123pan/bili-asr-e2e/proofread-transcripts/align/<bvid>.p0.alignment.jsonl` | **consumed evidence, not a T5 output**: the caption route (§6) — read it, do not overwrite it |
| `/root/e2e-asr/tools/ab-hotwords-qwen3.sh` | **written by the T5 execution round** (host-side scaffolding, never committed): `setup | with | without | repeat | census | readback`, with the §4 proofs inside `without` |
| `{ITERATION_DIR}/iter-2026-09-qwen3-asr-closeout/guides/t5-hotword-measurement-results.md` | the results guide: numbers, verdict, amendments, deviations |
| `{PLAN_DIR}/20260924-qwen3-asr-transformers.md` — the registered-residuals passage (`:54-56`) and the §14 open-item list | the verdict on `20260922-proofread-wave · R1`, including a negative one (Acceptance Criteria 7) |

The register row itself (`.mstar/projects/_default/residuals.json`) is written by the **PM** round, not by
T5's execution round. Per compass **C7** this host has **no issue store** (`.mstar/store.db` is absent):
nothing written anywhere may claim an issue was filed — the residual lives in the register file, the plan's
residual record and the artifact frontmatter, and the wording must say exactly that.

## 10. What this measurement is not

Not a corpus-wide quality claim (six items, 7.30 h, one channel, one engine); not a per-term verdict
on terms the corpus never speaks (`E` is reported so the null is visible); not a cross-engine comparison
(C3 excludes it); not a real-machine E2E gate; and not a licence to edit `DEFAULT_HOTWORDS` — the
measurement decides whether the list pays, the operator decides the list.

## 11. The one dropped variant

**The 1200 s / no-timestamps branch is dropped, not deferred, and is not a T5 item.** The aligner's
documented limit is minutes (`asr.py:46-49`) and this implementation carries timestamps on every path, so
the cap is a caller-supplied bound on one aligned window: `DEFAULT_CHUNK_SECONDS = 180.0` (`asr.py:52`),
adjustable only through `BILI_ASR_CHUNK_SECONDS` (`asr.py:93`, resolver `asr.py:241-253`). No code path
reads or wants a longer constant. T5 must not spend a run on it.

## Amendment 2 (2026-09-26, after the dry run, before any corpus arm)

**The `asr` command writes no attempt ledger.** §3 and §9 first told the reader to take each run's window
from `coordinator/attempts.jsonl`. That file is real, but only the **coordinator** path writes it:
`RunCoordinator` constructs the `AttemptLedger` (`src/bili_asr/coordinator.py:357`), which the `run` and
`campaign` commands reach. `bili-asr asr` calls the runner in-process and writes `manifest/manifest.jsonl`,
`coordinator/archive-writer.lock` and `transcripts/**` — and **no** `attempts.jsonl`, so an arm root driven
by `asr` has a `coordinator/` directory holding only a lock file.

Found by looking for the file after a real 448 s run instead of assuming the protocol was right. Recorded
here rather than silently corrected because the instruction was wrong in a way that would have surfaced as a
missing-evidence report at the end of a three-hour corpus run: the window must come from the invocation, and
the arm's own evidence is the artifact frontmatter (`asr_hotwords`, `asr_model_name`, `asr_chunk_seconds`,
`asr_device`, `source`) together with the manifest row's `archived` status.

What this costs the measurement: nothing that `attempts.jsonl` would have supplied. No clause in P1–P9 reads
an attempt count, and a per-row failure surfaces as a missing transcript for that item — which the census
already reports as `A absent` / `B absent`, per item, rather than silently.

## Amendment 3 (2026-09-26, before the short corpus ran)

**A second corpus is admitted, with a narrower reading, because the frozen six cannot be shortened.**

Asked to test on videos under ten minutes, the measurement's options were checked against the data rather
than assumed:

- **The frozen corpus cannot be filtered down to ten minutes.** The six C6 items are 2 087 / 2 408 / 2 598 /
  5 112 / 6 395 / 7 682 s — the *shortest* is 34.8 min. So "the six, but short" does not exist, and
  substituting different items into C6 would silently change what the verdict is about.
- **Captions are obtainable for short items.** The gateway returns one `ai-zh` track for them exactly as for
  the corpus (`get_subtitle_tracks` → `fetch_subtitle_segments`), so the caption-attested reading that
  separates a recovery from an insertion is available. This is the fact that makes a short corpus usable at
  all — without it, every hit would be unreadable.
- **The ≤600 s set is three items, and it is lopsided.** The complete local corpus holds exactly three items
  at or under 600 s (449 / 500 / 571 s), taken whole rather than cherry-picked. Their caption-attested
  hotword coverage is **E = 5 terms** — `国际劳工仲裁` 4, `国际劳联` 1, `攻势` 1, `智利` 1, `亚美利坚` 1 —
  and **the other 28 terms are never spoken.**

**What that means for the verdict, stated before the run rather than after it.** §5's own P9 says an
`E < 8` corpus leaves P1 and P2 uninformative, and here `E = 5`. So:

- **P1 and P2 are uninformative on the short corpus** by the protocol's own rule, not by a judgement made
  once the numbers were in.
- **P5–P8 remain informative** (they are about damage and identity, not about coverage), and **C4's
  throughput gate is the sharpest thing this corpus measures**.
- **The six terms restored by `R2` are not testable here at all**: 扬弃 自在 变易 此在 感性 实存 have
  **zero** occurrences across all eleven short items on disk, not merely across the three. A corpus that
  never speaks a term cannot measure that term, and the protocol forbids reading a null as a negative.

**How the three were chosen.** Every item in the local corpus with `duration_s ≤ 600 s`, taken as a set —
no filtering on whether it happens to say a hotword. Choosing items *because* they contain a term would
manufacture coverage and make E a number of the selection's making rather than the corpus's. The set is
seeded longest-first for the same reason §3 runs the long corpus that way.

**Arm R covers the whole short set** (all three items, ~26 min), because at this length a full repeat is
affordable and a whole-corpus noise floor is strictly better evidence than one item's. The long corpus keeps
arm R on its single longest item (`BV1iddQYQE7D.p0`, 7 682 s) exactly as §7 specifies.

**Arm roots are separate trees.** `CORPUS=short` writes `/root/e2e-asr/ab-short-corpus/{with,without,repeat}`
and `CORPUS=long` writes `/root/e2e-asr/ab-hotwords-qwen3/{...}`, so neither corpus can overwrite the
other's artifacts. One driver serves both, because the arm-B source edit and its restore proof must not
exist in two copies that can drift apart.

**What the short corpus is for, and what it is not.** It is a fast instrument: it establishes that the
apparatus runs on the shipped configuration over a real multi-item corpus, and it measures the damage and
throughput clauses well. It is **not** a substitute verdict, and a PASS or FAIL from it does not transfer to
P1/P2. Its result is recorded as its own finding with those limits attached; the six-item corpus remains
the only instrument that can settle whether the list earns its place.

### Amendment 3a — the restore proof is byte-anchored, not git-anchored (2026-09-26)

§4's restore was specified as a scoped `git status --porcelain` plus `git hash-object` equal to
`git rev-parse HEAD:<path>` — "prove it twice". That pair is unsound on a host whose fix is **uncommitted**,
and the target host is exactly that: its working tree carried the 33-entry restoration while `HEAD` still
held the 26-entry list the restoration replaced.

On such a tree a `git checkout` restore silently reverts the fix, and the git-shaped proof **passes**,
because reverting is precisely what makes `porcelain` empty and `blob == HEAD` true. Arm R would then have
measured 26 terms while every check reported the run sound. The failure is invisible in the direction that
matters: it does not break the run, it changes what the run measured.

The proof is therefore **byte-anchored**: the driver snapshots `asr.py` to a temp file before any edit,
records its sha256, and after the arm requires the file's sha256 to equal that recorded value. This restores
whatever the run actually started from, is independent of the host's commit state, and cannot be satisfied
by a revert. The git reading is still printed, but as a *description* of the tree — on an uncommitted fix,
"working differs from HEAD" is the correct state and is now named as such instead of failing.

The pre-run snapshot also reports the shipped term count and warns when it is not 33, so an arm can no
longer measure a configuration nobody declared.
