---
iteration_id: iter-2026-09-text-and-ledger-precision
plan_id: 20260918-transcript-text-precision
guide: hotword-ab-20260918
date: 2026-09-18
subject: Six Chinese homophone hotwords (扬弃 自在 变易 此在 感性 实存) — measured A/B
residual: "e2e-23191782-season-7686105 · R3"
decision: confirms
---

# Hotword A/B — the six Chinese homophones measured (2026-09-18)

**Question.** The six entries added to `DEFAULT_HOTWORDS` on 2026-09-17 were added on **measured
errors** — 118 mis-renderings across the season archive, every one the exact homophone of a common
word. Their **benefit was unverified**. This is that measurement: same audio, two hotword lists,
compare the text.

**Verdict (Step 5 rule, fixed before the run): CONFIRMS.** Correct forms rise (+34), homophones fall
(−33), global difference 2.48 % against a ≤5 % bar. **The entire measured effect is `扬弃`'s**: the
other five terms are inert on this lecture (§6, §9). → **`R3` is closable** (the PM closes the
register; see §10).

**Run identity.** Part `BV1H69sB6EeF:p0` — 《逻辑学》第二讲 存有论（2）扬弃-定在, the part the
register names as the worst affected (扬弃 4 correct vs 57 wrong). cid **37953865549**, 6870 s
(114.5 min), read from the season manifest at run time. Model `/root/e2e-asr/nano/master`
(`FunAudioLLM/Fun-ASR-Nano-2512`), `BILI_ASR_DEVICE=cuda` (AMD Radeon RX 7800 XT, gfx1101,
ROCm/HIP 7.2), `HSA_ENABLE_DXG_DETECTION=1`, language 中文. Archive host: `chosenecho@192.168.3.21`
(WSL2). Target checkout at commit **`ef5e1e8`** (already carries the 33-entry list).

---

## 1. Host preconditions (Step 1 — recorded, not assumed)

```
$ test -x /root/e2e-asr/tools/ab.sh      → 0  (ab.sh OK)
$ test -d /root/e2e-asr/ab-hotwords      → 0  (ab-hotwords OK)
$ /root/gpu-venv/bin/python -m bili_asr check-asr-env
  check: dxg-detection ok
  check: rocm-loader-path ok
  check: torch-present ok
  check: hsa-runtime ok
  check: device ok name=AMD Radeon RX 7800 XT arch=gfx1101 vram_gb=15.8 hip=7.2.26015-fc0010cf6a
  asr-env: verified   (exit 0)
$ du -sh /root/e2e-asr/nano/master       → 2.0G
```

Both `/root/e2e-asr/tools/ab.sh` and `/root/e2e-asr/ab-hotwords` were **present**, so the plan's
"write a sibling driver" branch was not forced — but `ab.sh` is the Latin-acronym A/B and its
*positive* mechanism does not transfer, so a sibling driver was written anyway (§2).

**A note on `torch.cuda.is_available()`:** it returns **False** without
`HSA_ENABLE_DXG_DETECTION=1` in the environment, and **True** with it. The driver exports it before
any Python runs. This is the same trap the repo's env check exists to catch.

## 2. Why the "without" arm needs a code edit, not the env knob

`_extra_hotwords` (`src/bili_asr/asr.py` L456-467) **skips any term already in
`DEFAULT_HOTWORDS`**:

```python
if term and term not in terms and term not in DEFAULT_HOTWORDS:
    terms.append(term)
```

So `BILI_ASR_HOTWORDS` can only **add** — it cannot subtract a default entry. The Latin A/B worked
by re-adding removed acronyms through this knob; that trick is unavailable here, because the six
terms are *in* the committed default list. The "without" arm is therefore produced by a
**temporary, uncommitted** edit that removes the six lines from `asr.py`, restored immediately
after the run (§4).

Driver: `/root/e2e-asr/tools/ab-hotwords-cn.sh` (mode `setup|with|repeat|without|readback`),
sha256 `614656afff442ba619f8e7444ae6cec133dce364f58c396e6c18dcf04ffe437c`. Three archive roots —
`{with,without,repeat}` — one seeded row each, sequential runs, artifact-based comparison. The
`repeat` root is the noise-floor control (§5).

## 3. Identity side — proven from the products, not the invocation

`asr_hotwords` read back from each arm's produced md frontmatter:

| arm | entries | six present |
|---|---|---|
| `with` | **33** | `['扬弃','自在','变易','此在','感性','实存']` |
| `without` | **27** | `[]` |

```
only in WITH   : ['扬弃', '自在', '变易', '此在', '感性', '实存']
only in WITHOUT: []
DIFF is exactly the six terms: True
```

**The diff is exactly the six terms.** Nothing else changed in the list.

*(A driver bug was caught by its own precondition guard and fixed before any arm ran: the
six-term counter used `grep -c` with `\|` alternation, which under BRE returned 0 and made the
driver refuse rather than remove nothing. Fixed to `grep -cE`; `asr.py` was verified untouched
afterwards (`git status --porcelain` empty for that path, blob hash equal to HEAD's). Two
subsequent runs of the corrected driver are the evidence above. No arm was ever run against a
half-applied list.)*

## 4. Restoration proof for the temporary edit

Removal: `ab-cn: WITHOUT arm — removed 6 terms, 0 remain in asr.py`.
After the run, in the same script:

```
ab-cn: asr.py restored
ab-cn: RESTORATION PROOF — asr.py porcelain EMPTY (clean)
ab-cn: six terms back in asr.py: 6/6
```

Independently re-verified live, after all three arms — on the **archive host's** checkout:

**Which checkout these commands describe.** `/root/workspace/bilibili-asr-archive` *on the archive
host* (`chosenecho@192.168.3.21`, WSL2), HEAD **`ef5e1e8`**. That is the **same absolute path** as
the control root but a **different checkout**: the control root has since advanced past it (HEAD
`1cc1b2a`+, `2c46040` when this note was written). The `git -C /root/workspace/bilibili-asr-archive …`
invocations below therefore describe the **host's** working tree, not the control root's.

```
$ git -C /root/workspace/bilibili-asr-archive status --porcelain -- bilibili-asr-archive/src/bili_asr/asr.py
   (empty)
$ git hash-object bilibili-asr-archive/src/bili_asr/asr.py   → 80acd8df8bafa17a0c1072d0c5a5604f666bd80a
$ git rev-parse HEAD:bilibili-asr-archive/src/bili_asr/asr.py → 80acd8df8bafa17a0c1072d0c5a5604f666bd80a
```

Working file **byte-identical to `HEAD`** — doubly proven (porcelain empty + blob hash equal).

`git status --porcelain` at the repository root shows one entry, `?? .env.bak-20260917-181947`.
This is **pre-existing and not mine**: untracked, mtime **Sep 8 12:46**, predating this task by ten
days and present before the first arm was seeded. It is a stray credential backup outside the
hotword scope; leaving it alone is the surgical choice. It does not affect the restoration proof
above, which is scoped to `asr.py` and corroborated by the blob hash.

**Reading the porcelain (plan Task 2 Step 2, relaxed).** Step 2's literal check — `cd
/root/workspace/bilibili-asr-archive && git status --porcelain` at the repository root, "no output
means clean" — is read in its **`.mstar/**`-aware** form, because an unscoped whole-tree porcelain is
not empty on either checkout. On the host the single entry is the pre-existing untracked
`.env.bak-20260917-181947` above; on the control root it is the **PM-owned** `.mstar/**`
modifications instead (harness process artifacts, unrelated to this A/B). The restoration claim is
the scoped reading it was always about — porcelain **empty for
`bilibili-asr-archive/src/bili_asr/asr.py`** — corroborated by the blob hash against `HEAD`.

## 5. Noise floor — the measurement that makes the treatment interpretable

The decoder was **not** assumed deterministic. A third run (`repeat`) used the **identical**
configuration as `with` and was compared to it:

| comparison | identical-char ratio | cues | mean conf | low-conf | vad segs |
|---|---|---|---|---|---|
| `with` vs `repeat` — **SAME config** | **1.0000** (0.0000 %) | 1400 / 1400 | 0.751 / 0.751 | 48 / 48 | 522 / 522 |
| `with` vs `without` — treatment | 0.9752 (2.4751 %) | 1400 / 1410 | 0.751 / 0.751 | 48 / 51 | 522 / 518 |
| `without` vs `repeat` — control | 0.9752 (2.4751 %) | 1410 / 1400 | 0.751 / 0.751 | 51 / 48 | 518 / 522 |

Run windows (**CST**), read from each arm's `coordinator/attempts.jsonl`: `with`
**13:17:16–13:35:41**, `without` **14:11:41–14:30:10**, `repeat` **14:32:49–14:51:08**.

**Both metrics are basis-dependent, so their bases are stated here.**
- *identical-char ratio* — `difflib.SequenceMatcher` over the **raw txt**
  (`transcripts/txt/*.txt`), with `autojunk=False`. The library default `autojunk=True` scores the
  same `with`/`without` pair at **0.9731** rather than 0.9752; that gap is why the basis is named
  instead of left implicit.
- *"shared timing buckets"* — cues keyed by their **srt timestamp span**: a bucket is a span present
  in **both** arms, so the arms are compared bucket-by-bucket rather than line-by-line. The
  `with`/`without` pair yields **1275** shared buckets, **209** of which differ (§8).

**The noise floor is zero — within the configuration it controls.** Two independent runs of the same
configuration produced **byte-identical transcripts** (0 of 1400 shared cues differ). That control
covers the **33-entry** configuration only: the third run re-ran `with`, so the **27-entry
("without") arm has a single sample** and no repeat of its own. Every difference between `with` and
`without` is therefore attributable to the six-term removal **within the controlled configuration**
— including the differences that do *not* mention a hotword (§8). The `without` arm is the sole
outlier of the three.

## 6. Benefit side — six terms × their measured homophones, absolute counts

Pairing source (checked, not re-derived): `src/bili_asr/asr.py` **L156-161**, the season run's
term/homophone table.

| term | homophone(s) | `with` correct | `with` hom | `without` correct | `without` hom |
|---|---|---|---|---|---|
| **扬弃** | 阳气 / 洋气 | **38** | **26** (阳气 6, 洋气 20) | **4** | **59** (阳气 23, 洋气 36) |
| 自在 | 子在 | 0 | 0 | 0 | 0 |
| 变易 | 变异 | 0 | 3 | 0 | 3 |
| 此在 | 次在 / 词在 | 0 | 0 | 0 | 0 |
| 感性 | 感兴 | 4 | 0 | 4 | 0 |
| 实存 | 时存 | 3 | 0 | 3 | 0 |
| **TOTAL** | | **45** | **29** | **11** | **62** |

- correct forms: `with` 45 vs `without` 11 → **+34**
- homophones: `with` 29 vs `without` 62 → **−33**

**The entire measured effect is `扬弃`.** 扬弃 **4 → 38** (×9.5) while its homophones collapse
**59 → 26**. The other five terms are **inert on this lecture**: 自在, 此在 and 变易 appear in
neither correct nor homophone form (变易's homophone 变异 is 3 in *both* arms — unrelated to the
term); 感性 (4) and 实存 (3) are identical in both arms. This is expected, not disappointing: this
lecture is *about* 扬弃 (its title ends 扬弃-定在), and the season run's other five terms are spread
across other lectures. Five of six showing no movement on a lecture that does not exercise them is a
**null**, not a refutation — and it is stated here so no reader reads "six terms verified".

The season-run baseline for this part (`扬弃` 4 correct vs 57 wrong) is **reproduced** at 4 vs 59 in
the `without` arm — an independent confirmation that the `without` arm genuinely reinstates the
pre-hotword condition.

## 7. Cost side

| metric | `with` | `without` | note |
|---|---|---|---|
| identical-char ratio vs the other arm | 0.9752 | 0.9752 | **2.48 % global difference**, bar is ≤5 % |
| txt length (chars) | 35 478 | 35 630 | −152 |
| cue count (raw segments) | 1400 | 1410 | +10 in `without` |
| `asr_mean_confidence` | 0.751 | 0.751 | unchanged |
| `asr_low_confidence_cues` | **48** | **51** | **−3 with the terms** |
| `asr_vad_segments` | 522 | 518 | |
| `asr_vad_captured_s` | 5884.91 | 5904.92 | ratio 0.857 vs 0.860 |

The `identical-char ratio` row is `difflib.SequenceMatcher` over the **raw txt** with
`autojunk=False`; under the library default `autojunk=True` the same pair scores **0.9731** (§5).
The cost side is **benign, and mildly favourable**: mean confidence is unchanged, low-confidence
cues are **three fewer** with the terms present, and the global difference sits at half the allowed
bar. No new damage class appears.

## 8. Attribution of the 2.48 % difference — the honest decomposition

209 of 1275 shared timing buckets differ. Because the noise floor is **zero** (§5), all 209 are
caused by the list change. They decompose as:

| class | cues |
|---|---|
| 扬弃 / 阳气 / 洋气 related — **the intended effect** | **38** |
| other hotword mentioning (国际劳工仲裁, 定在, 黑格尔, 理念性 …) | 7 |
| no hotword mentioned — prompt-list side effects | 164 |

**Provenance of this table.** The 209 total is read from the two arms' artifacts; the **38 / 7 / 164**
sub-split is **implementer-attested, not independently re-derived** by the PM, and is carried here as
reported. The attribution it rests on is bounded exactly as §5 bounds it: the noise floor is measured
on the **33-entry** configuration, and the 27-entry `without` arm is a single sample.

The 38 intended cues are the benefit. The 7 hotword-mentioning cues are collateral on *other*
entries in the list (e.g. `国际劳工仲裁` present in `with`, dropped in `without`; `诗歌`→`实则`).

The **164 no-hotword cues** are the honest cost: the prompt list perturbs the decoder globally.
They are overwhelmingly interchangeable filler and function-word slips —
`呃`↔`嗯` (125.5 s, 135.0 s), `Two`↔`To` (258.0 s), `施加`↔`实下` (305.0 s), `four`↔`your`,
`form`↔`from` (288.1 s). None introduces a new *class* of error, mean confidence does not move, and
low-confidence cues fall by 3. This is what "difference dominated by new damage" would *not* look
like; it is the ordinary jitter of a prompt change, and it is disclosed rather than netted out.

## 9. Step-5 decision, applied as written

The rule was fixed before the run (plan Task 2 Step 5). Applying it literally:

| clause | requirement | measured | met |
|---|---|---|---|
| confirms | correct forms **rise** | +34 (45 vs 11) | ✔ |
| confirms | homophones **fall** | −33 (29 vs 62) | ✔ |
| confirms | global difference **≤5 %** | 2.4751 % | ✔ |
| refutes | `with` worse / dominated by new damage | mean conf flat, low-conf −3, no new error class | ✘ |

**Decision: CONFIRMS the entries → `R3` is closable, citing both arms.**

Restated with its limits, because the counts do not support more:
- The confirmation rests **on `扬弃` alone** (+34/−33 is essentially its 4→38 and 59→26).
- The other five terms are **not** shown to do anything on this lecture — they are unexercised
  there, and this run neither confirms nor refutes them.
- One lecture, one part, one model. This closes the register entry the register itself specified
  ("re-transcribe one affected lecture with and without them"); it is not a corpus-wide claim.

## 10. Register disposition

`R3` (`e2e-23191782-season-7686105 · R3`) is **closable on this evidence**. Per **plan Task 2
Step 6**, the register write is the **PM's** domain — this guide reports the decision and the counts;
it does not edit `{PROJECT_DIR}/_default/residuals.json`. (The compass's Non-Goals bullet that forbids
adding, removing or reordering hotwords and requires the "without" arm's temporary uncommitted edit to
be restored before close — the bullet beginning 不新增、不删除、不重排热词 — fixes **arm-construction
discipline**, not register ownership.)

Suggested closure note: confirmed on `BV1H69sB6EeF:p0` (114.5 min, GPU, `ef5e1e8`); 扬弃 4→38
correct and 59→26 homophones; global difference 2.48 % (bar ≤5 %); mean confidence unchanged
(0.751), low-confidence cues 51→48; noise floor measured at 0.0000 % on a same-config repeat run;
other five terms inert on this part.

## 11. Reproduce

**Checkout and run windows.** These commands were run on the **archive host's** checkout —
`/root/workspace/bilibili-asr-archive` on `chosenecho@192.168.3.21` (WSL2), HEAD **`ef5e1e8`** — the
**same absolute path** as, but a **different checkout** from, the control root (now `1cc1b2a`+,
`2c46040` when this note was written; §4). Run them there: on the control root the same
`git status --porcelain` reports the PM-owned `.mstar/**` modifications instead of the host's tree.
Complete run windows (**CST**), read from each arm's `coordinator/attempts.jsonl`: `with`
**13:17:16–13:35:41**, `without` **14:11:41–14:30:10**, `repeat` **14:32:49–14:51:08** — three arms,
one window each, one sample per arm.

```bash
# on the archive host (WSL2), driver already present:
/root/e2e-asr/tools/ab-hotwords-cn.sh setup      # seeds {with,without,repeat} from the season manifest
/root/e2e-asr/tools/ab-hotwords-cn.sh with       # arm WITH   (~18 min; re-downloads ~35 MB)
/root/e2e-asr/tools/ab-hotwords-cn.sh without    # arm WITHOUT — removes, runs, restores, proves
/root/e2e-asr/tools/ab-hotwords-cn.sh repeat     # noise-floor control, same config as `with`
/root/e2e-asr/tools/ab-hotwords-cn.sh readback   # md frontmatter `asr_hotwords` per arm

# restoration, independently:
git -C /root/workspace/bilibili-asr-archive status --porcelain -- bilibili-asr-archive/src/bili_asr/asr.py
git -C /root/workspace/bilibili-asr-archive hash-object bilibili-asr-archive/src/bili_asr/asr.py
git -C /root/workspace/bilibili-asr-archive rev-parse HEAD:bilibili-asr-archive/src/bili_asr/asr.py
```

Artifacts:

| path | what |
|---|---|
| `/root/e2e-asr/ab-hotwords-cn/{with,without,repeat}/transcripts/md/*.md` | the three bundles; `asr_hotwords` readback lives here |
| `/root/e2e-asr/ab-hotwords-cn/{with,without,repeat}/transcripts/txt/*.txt` | the counted text |
| `/root/e2e-asr/ab-hotwords-cn/{with,without,repeat}/transcripts/raw/*.json` | `segments` (cue counts, confidences) |
| `/root/e2e-asr/tools/ab-hotwords-cn.sh` | the driver |

Consumed evidence that remains applicable: the season manifest row's `cid`/`duration_s`
(read at run time, not the plan literal) and the term/homophone table at `asr.py` L156-161.
Audiobook audio is **not** consumed evidence: each arm re-downloaded it by design.

---

## 12. Appendix — host scaffolding and the arm readbacks (captured 2026-09-18)

Everything below lives **on the archive host, not in this repository**. It is reproduced from a
read-only capture of the host so that the measurement survives the host roots:

- the driver is **host-side scaffolding** — a sibling of `/root/e2e-asr/tools/ab.sh`, written for this
  A/B and never committed to this repository;
- its sha256 pins content **a reader of this repository cannot fetch**: there is no copy in the repo to
  hash, diff or re-run, so the digest is meaningful only beside the reproduced text below;
- the reason to carry the text at all is the **subtraction arm**. Removing terms is the measurement's
  only way to build the `without` arm — `BILI_ASR_HOTWORDS` can only **add** (§2) — and that arm exists
  only as a temporary uncommitted edit on the host. If the host roots are pruned, this appendix is what
  keeps the arm's construction and its readbacks recoverable from the closure artifacts.

### 12.1 Arm readbacks — md frontmatter `asr_hotwords`, verbatim

```
with     asr_hotwords: "未明子,主义主义,拟态论,国际劳工仲裁,国际劳联,马恩牌,攻势,智利,根正苗红,亚美利坚,黑格尔,海德格尔,拉康,齐泽克,德勒兹,康德,观念论,本体论,现象学,辩证法,定在,自为,理念性,扬弃,自在,变易,此在,感性,实存,International Employment Matters Tribunal,International,Employment,Tribunal"
without  asr_hotwords: "未明子,主义主义,拟态论,国际劳工仲裁,国际劳联,马恩牌,攻势,智利,根正苗红,亚美利坚,黑格尔,海德格尔,拉康,齐泽克,德勒兹,康德,观念论,本体论,现象学,辩证法,定在,自为,理念性,International Employment Matters Tribunal,International,Employment,Tribunal"
repeat   asr_hotwords: "未明子,主义主义,拟态论,国际劳工仲裁,国际劳联,马恩牌,攻势,智利,根正苗红,亚美利坚,黑格尔,海德格尔,拉康,齐泽克,德勒兹,康德,观念论,本体论,现象学,辩证法,定在,自为,理念性,扬弃,自在,变易,此在,感性,实存,International Employment Matters Tribunal,International,Employment,Tribunal"
only in WITH   : ['扬弃', '自在', '变易', '此在', '感性', '实存']
only in WITHOUT: []
```

§3 tabulates the `with`/`without` pair; the `repeat` line above is the third arm and is identical to
`with`, which is what makes §5's noise-floor comparison a same-configuration pair.

### 12.2 Driver — `/root/e2e-asr/tools/ab-hotwords-cn.sh`, verbatim

sha256 `614656afff442ba619f8e7444ae6cec133dce364f58c396e6c18dcf04ffe437c` (also cited in §2).

```bash
#!/usr/bin/env bash
# A/B one part through the ASR chain with two different Chinese-hotword lists.
#
# Question: do the six Chinese homophone entries added to DEFAULT_HOTWORDS on
# 2026-09-17 (扬弃 自在 变易 此在 感性 实存) earn their place?  Their *errors* were
# measured on the season run (118 mis-renderings); their *benefit* is unverified.
# This pair re-runs the single most affected lecture — BV1H69sB6EeF.p0,
# 《逻辑学》第二讲 (worst item: 扬弃 4 correct vs 57 wrong) — with and without them.
#
# Two archive roots, one row each, same audio, same model, same device.
#
# The "without" arm CANNOT use the BILI_ASR_HOTWORDS knob: `_extra_hotwords`
# (asr.py L456) *skips* terms already in DEFAULT_HOTWORDS, so the env var can
# only add, never subtract.  The arm is therefore produced by a temporary,
# uncommitted edit to asr.py that removes the six lines, restored immediately
# after the run and proven restored by `git status --porcelain`.
#
# Both arms are proven from the md frontmatter's `asr_hotwords` field, never
# from the invocation.
set -euo pipefail

REPO=/root/workspace/bilibili-asr-archive
PRODUCT=$REPO/bilibili-asr-archive
SRC=$PRODUCT/src
PY=/root/gpu-venv/bin/python
SEASON=/root/e2e-asr/e2e50
AB=/root/e2e-asr/ab-hotwords-cn
PART=BV1H69sB6EeF:p0
WORK_ID=BV1H69sB6EeF.p0
ASR_PY=$SRC/bili_asr/asr.py

export PYTHONPATH=$SRC
export HSA_ENABLE_DXG_DETECTION=1
export BILI_ASR_MODEL=/root/e2e-asr/nano/master
export BILI_ASR_MODEL_ID=FunAudioLLM/Fun-ASR-Nano-2512
export BILI_ASR_DEVICE=cuda
export BILI_ASR_LANGUAGE=中文

load_sessdata() {
  set -a
  [ -f "$REPO/.env" ] && . "$REPO/.env"
  set +a
  if [ -z "${BILI_SESSDATA:-}" ] && [ -f "$HOME/.config/bili-asr/session.env" ]; then
    set -a; . "$HOME/.config/bili-asr/session.env"; set +a
  fi
  : "${BILI_SESSDATA:?no SESSDATA in $REPO/.env or ~/.config/bili-asr/session.env}"
  case "$BILI_SESSDATA" in
    *[!\ -~]*) echo "ab-cn: SESSDATA contains non-ASCII; refusing" >&2; exit 1 ;;
  esac
  echo "ab-cn: sessdata present (${#BILI_SESSDATA} chars)"
}

seed_root() {  # $1 = root
  local root=$1
  mkdir -p "$root/manifest"
  "$PY" - "$SEASON/manifest/manifest.jsonl" "$root/manifest/manifest.jsonl" "$PART" <<'PY'
import json, sys, pathlib
src, dst, part = sys.argv[1], sys.argv[2], sys.argv[3]
rows = [json.loads(l) for l in pathlib.Path(src).read_text(encoding="utf-8").splitlines() if l.strip()]
matching = [d for d in rows if d.get("work_id") == part]
if not matching:
    raise SystemExit(f"{part} not found in {src}")
row = max(matching, key=lambda d: len(d))   # the archived row carries cid
keep = ("bvid", "work_id", "page_index", "cid", "page_label", "title",
        "duration_s", "pubdate", "pubdate_str")
fresh = {k: row[k] for k in keep if k in row}
fresh["status"] = "needs_audio"
pathlib.Path(dst).write_text(json.dumps(fresh, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"ab-cn: seeded {dst}: {fresh['work_id']} cid={fresh['cid']} {fresh['duration_s']}s")
PY
}

remove_six() {
  local before after
  before=$(grep -cE '^    "(扬弃|自在|变易|此在|感性|实存)",$' "$ASR_PY")
  [ "$before" = "6" ] || { echo "ab-cn: expected 6 term lines, found $before; refusing" >&2; exit 1; }
  "$PY" - "$ASR_PY" <<'PY'
import re, sys, pathlib
p = pathlib.Path(sys.argv[1])
t = p.read_text(encoding="utf-8")
for term in ("扬弃", "自在", "变易", "此在", "感性", "实存"):
    t, n = re.subn(rf'^    "{term}",\n', "", t, count=1, flags=re.M)
    assert n == 1, f"{term}: {n} removals"
p.write_text(t, encoding="utf-8")
PY
  after=$(grep -cE '^    "(扬弃|自在|变易|此在|感性|实存)",$' "$ASR_PY" || true)
  echo "ab-cn: WITHOUT arm — removed $before terms, $after remain in asr.py"
  git -C "$REPO" status --porcelain -- bilibili-asr-archive/src/bili_asr/asr.py
}

restore_asr() {
  git -C "$REPO" checkout -- bilibili-asr-archive/src/bili_asr/asr.py
  echo "ab-cn: asr.py restored"
  local out
  out=$(git -C "$REPO" status --porcelain -- bilibili-asr-archive/src/bili_asr/asr.py)
  if [ -z "$out" ]; then echo "ab-cn: RESTORATION PROOF — asr.py porcelain EMPTY (clean)"; else echo "ab-cn: RESTORE FAILED:"; echo "$out"; exit 1; fi
  echo "ab-cn: six terms back in asr.py: $(grep -cE '^    "(扬弃|自在|变易|此在|感性|实存)",$' "$ASR_PY")/6"
}

run_arm() {  # $1 = arm
  local arm=$1
  load_sessdata
  cd "$PRODUCT"
  unset BILI_ASR_HOTWORDS || true
  echo "ab-cn: arm $arm starting at $(date -Is)"
  "$PY" -m bili_asr run --scope pending --archive-root "$AB/$arm" --max-audio-gb 0
  echo "ab-cn: arm $arm finished at $(date -Is)"
}

readback() {  # $1 = arm
  local arm=$1
  local md
  md=$(ls "$AB/$arm"/transcripts/md/*.md 2>/dev/null | head -1)
  [ -n "$md" ] || { echo "  $arm: NO ARTIFACT"; return; }
  "$PY" - "$arm" "$md" <<'PY'
import json, re, sys, pathlib
arm, md = sys.argv[1], sys.argv[2]
t = pathlib.Path(md).read_text(encoding="utf-8")
fw = t.split("---")[1]
fm = {}
for line in fw.strip().splitlines():
    k, _, v = line.partition(": ")
    try: fm[k] = json.loads(v)
    except Exception: fm[k] = v
terms = str(fm.get("asr_hotwords", "")).split(",") if fm.get("asr_hotwords") else []
six = ["扬弃", "自在", "变易", "此在", "感性", "实存"]
print(f"  {arm}: {len(terms)} entries | six-present={[x for x in six if x in terms]}")
for k in ("asr_model_id","asr_device","asr_language","asr_mean_confidence",
          "asr_low_confidence_cues","asr_vad_segments","asr_vad_captured_s",
          "asr_vad_captured_ratio","source"):
    if k in fm: print(f"     {k} = {fm[k]}")
pathlib.Path(f"/tmp/abhot/{arm}-hotwords.txt").write_text(",".join(terms), encoding="utf-8")
PY
}

case "${1:-}" in
  setup)
    load_sessdata >/dev/null
    rm -rf "$AB"; mkdir -p "$AB"
    seed_root "$AB/with"
    seed_root "$AB/without"
    seed_root "$AB/repeat"
    echo "ab-cn: both roots seeded under $AB"
    ;;
  with)    run_arm with ;;
  repeat)  run_arm repeat ;;
  without) remove_six; run_arm without; restore_asr ;;
  readback) for a in with without repeat; do readback "$a"; done ;;
  *)
    echo "usage: ab-hotwords-cn.sh {setup|with|repeat|without|readback}" >&2; exit 2 ;;
esac
```
