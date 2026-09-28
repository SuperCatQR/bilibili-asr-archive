# Output layout: the measured survey and the shape options

**Status: investigation complete; the target shape is NOT decided.** This document is the Phase-1
investigation conclusion for the "输出目录结构太分散" complaint. It states what the layout is today, the
naming defect the scatter hides (§2), what constrains any new shape, and what each candidate shape would
cost — measured, with anchors. It deliberately does not pick a winner: the decision is reserved (§5,
`Decision required`).

Survey date: 2026-09-26. Baseline commit: `9d530cd`. Method: three independent read-only reconnaissance
passes plus the author's own verification; every count below was produced by opening the files, not by
estimate. Source anchors are module-relative to `bilibili-asr-archive/src/bili_asr/`; `README.md` and
`docs/…` are package-relative, `.mstar/…` and `.tmp/…` repo-root-relative.

---

## 1. What is written today

### 1.1 Products (relocate with `--artifact-root` / `BILI_ARTIFACT_ROOT`; write base = `ArtifactRoots.write_base`)

| # | Path | Writer | Naming rule |
|---|------|--------|-------------|
| 1 | `transcripts/srt/{stem}.srt` | `archive.py:466` | `stem = {bvid}.p{page_index}` |
| 2 | `transcripts/srt/{stem}.srt.bundle-ready` | `archive.py:234` | marker name derived from the srt name; suffix `BUNDLE_MARKER_SUFFIX = ".bundle-ready"` (`archive.py:17`) |
| 3 | `transcripts/txt/{stem}.txt` | `archive.py:467` | `{stem}` |
| 4 | `transcripts/raw/{stem}.json` | `archive.py:469` | `{stem}` |
| 5 | `transcripts/md/{pubdate_str}_{stem}_{safe}(title).md` | `archive.py:468` | **different rule** — see §2 |
| 6 | `transcripts/.archive-bundle-stage` | `archive.py:224` | fixed staging name, mode `0o700`, removed at `:255` unless killed |
| 7 | `audio/{stem}.m4a` (or `.flac`) | `audio.py:229`, `:260` | `{stem}` |
| 8 | `audio/.audio-stage-<32 hex>.download\|.m4a` | `audio.py:90` | unpredictable stage entry |
| 9 | `subtitles/raw/{stem}.json` | `subtitles.py:147` | `RAW_SUB_DIR` (`subtitles.py:24`) |
| 10 | `transcripts/srt/{stem}.srt` (caption path) | `subtitles.py:153` | `SRT_DIR` (`subtitles.py:25`) — same destination as #1 |

### 1.2 State (always at the archive root — the `iter-2026-09-artifact-root` contract's **D13**, a different document from this iteration's own D13; a FUSE/WebDAV mount cannot carry the fsync pair or SQLite locks)

| # | Path | Writer |
|---|------|--------|
| 1 | `manifest/manifest.jsonl` (+ `.lock`, `.manifest.jsonl.<pid>.<id>.tmp`) | `manifest.py:39`, `:147`, `:204` |
| 2 | `archive.db` | `config.py:57`, `storage/database.py:40` |
| 3 | `search.db` | `search_index.py:412` |
| 4 | `coordinator/attempts.jsonl` (+ `.lock`) | `coordinator.py:58`, `:213` |
| 5 | `coordinator/archive-writer.lock` | `coordinator.py:59` |
| 6 | `coordinator/recovery-audit.jsonl` (+ `.lock`, `.recovery-audit.*.tmp\|.rollback`) | `integrity.py:42-43`, `:493`, `:504`, `:516` |
| 7 | `meta-cursor.json` (+ `.tmp`) | `meta_cursor.py:14`, `:114` |
| 8 | `scheduler.json` (+ `.tmp`) | `scheduler.py:19`, `:193` |
| 9 | `run-ledger.jsonl` (+ `.lock`) | `run_ledger.py:19`, `:346` |
| 10 | `campaign.json` (+ `.{name}.tmp`) | `campaign.py:122`, `:126` |

**Totals: 10 product families, 10 state families.**

### 1.3 What the documentation already promises

`README.md:470-475`:

> **Products move; state does not.** `audio/`, `transcripts/{srt,txt,md,raw}/` and `subtitles/raw/` are
> written under the configured root. `manifest/`, `archive.db`, `coordinator/`, `meta-cursor.json`,
> `scheduler.json`, `run-ledger.jsonl`, `campaign.json` and `search.db` stay at the archive root — the
> manifest's per-append fsync pair and SQLite's locking are exactly what a FUSE/WebDAV mount cannot carry.

`README.md:602-607`:

> An archive generation is exactly four files: `transcripts/srt/<stem>.srt`, `transcripts/txt/<stem>.txt`,
> one `transcripts/md/*.md`, and `transcripts/raw/<stem>.json`. `<srt>.bundle-ready` is published last and
> names those exact four relative paths with their SHA-256 digests. Readers accept only a complete
> marker-matched generation.

Note the hedge: the published promise pins **three** of the four families to `<stem>` and leaves the md as a
wildcard (`one transcripts/md/*.md`). That wildcard is where the real defect lives.

---

## 2. The defect the scatter hides: two naming rules for one work id

`archive.py:452-470` states the rule verbatim in its own docstring:

> The names are the writer's rule: `archive_stem(entry)` for the srt, txt and raw families, and
> `"{pubdate_str}_{stem}_{_safe_name(title)}.md"` for the markdown one.

| Aspect | Rule A (3 of 4 files) | Rule B (the md) |
|---|---|---|
| Inputs | identity only (`bvid`, `page_index`) | identity **+ `pubdate_str` + `title`** |
| Stability | immutable for a given part | changes whenever the title or the pubdate moves |
| Read sites | many | 4 sites probe the **dead** Rule-A name `transcripts/md/{stem}.md`: `search_index.py:209`, `:518`, `quality.py:412`, `integrity.py:570` |

`_safe_name` (`archive.py:31`) strips `<>:"/\|?*`, collapses whitespace, and truncates at `[:120]`
**characters** with no byte guard. Measured md filename lengths in the two real corpora: 69, 69, 75, 105,
117, 129 bytes; longest seen anywhere 146 bytes.

**What a title change between runs actually breaks** (each anchor verified):

1. The md filename changes → a **new** md is written and the **old** one is never removed. `archive.py`
   unlinks only the marker (`:216`) and stage entries (`:249`); grep confirms no md cleanup anywhere.
   **This is the orphaning the operator's complaint describes.**
2. `integrity.py:360` raises `IDENTITY_PATH_MISMATCH` as soon as the row's title no longer reproduces its
   recorded md filename.
3. The glob at `quality.py:416` now matches **both** generations and `sorted()` (`:417`) picks the stalest,
   because equal transcript ranks never displace each other (`quality.py:245-256`).
4. The marker payload pins the old four paths (`archive.py:111`) and `:195` requires
   `item["path"] == paths[key]` byte-for-byte, so the old generation stops being a valid bundle.
5. `cli.py:1328` states the intent outright: *"a re-derivation would disagree with it the moment a title or
   a pubdate moved."*

---

## 3. What constrains any new shape

### 3.1 The recorded-path contract buys a *root* change, not a *shape* change

`artifact_root.py:46-55` (the `contract` its comment names is
`iter-2026-09-artifact-root/specs/artifact-root-contract.md`):

> Reads (contract §5, D7/D8) never see an absolute recorded path. The recorded strings stay
> artifact-root-relative (`audio/{stem}.m4a`, `transcripts/srt/{stem}.srt`), so the manifest's bytes are
> unchanged by this feature and no reader needs to know which root a row was written under.

Verified on disk (`.tmp/qa-probe/F-A/manifest/manifest.jsonl:1`): rows record
`"srt_path":"transcripts/srt/BV1CHAIN.p0.srt"` — relative, exactly the shipped shape. And
`README.md:490`: *"Recorded paths stay root-relative and the manifest is never rewritten"*.

**But:** the ordered probe is a **root** probe, not a **shape** probe. `artifact_root.py:300-304` iterates
`read_bases()` and validates **the same recorded string** against each. `quality.py:394` and
`integrity.py:225` do the same. So a shape change leaves every recorded string pointing at nothing, and the
existing tolerance does not cover that.

### 3.2 The validator is the hard gate

`archive.py:155-168` returns `False` unless, for each of the four keys,
`len(parts) == 3 and parts[:2] == ("transcripts", directory)`. `archive.py:195` additionally requires the
marker's own `item["path"]` to equal the produced path byte-for-byte.

**Consequence:** the day the writer emits a new shape, `archive_bundle_complete` returns `False` for every
previously-archived legacy row, and through `coverage_report.py:470` and `integrity.py:356-369` each of
those rows reports missing/not-a-transcript. **A plan that assumes "relative paths means no migration" is
wrong.** Any shape change must make `_owned_bundle_parts` and the read probes accept **both** shapes,
legacy-first.

### 3.3 Load-bearing structures (cannot move without breaking a guarantee)

| # | Structure | Anchor | Why it is load-bearing |
|---|---|---|---|
| 1 | The four-product tuple `_REQUIRED_ARTIFACT_KEYS` | `archive.py:18`, restated in 6 places (`integrity.py:60`, `cli.py:1317`, `services/transcript_projection.py:88`, `coverage_report.py:464`, `search_index.py:196`) | The marker schema `"schema": "archive-bundle-v1"` (`archive.py:114`) is a **stored, read-back** contract |
| 2 | The marker lives in the srt dir, named after the srt | `archive.py:234`, read at `:186` | Completeness derives the marker path from `paths["srt_path"]` |
| 3 | The stem rule `{bvid}.p{page_index}` | `page_identity.py:41-45` | Makes raw/SRT/audio/transcripts collision-free across pages (`README.md:1302`); asserted never to contain `:` |
| 4 | The audio confinement guard **is** the layout | `path_policy.py:25`: `if declared.parts[0] != "audio" or len(declared.parts) != 2` | Every audio reader/writer/reclaimer/budget probe runs through it |
| 5 | The 3-component transcript shape | `archive.py:160` | See §3.2 |
| 6 | `_ARTIFACT_REL_DIRS` | `manifest.py:416-423`, consumed by `_foreign_page_stems` (`:426-451`) | It `os.listdir`s each of six dirs under **both** bases to freeze bare-`bvid` rows. A new directory that page artifacts can land in, not added here, makes bare-bvid migration silently mis-assign pages |
| 7 | Staging must be on the same filesystem | `archive.py:241-242` | The publish is `os.replace` between descriptors |

### 3.4 Merely historical (removable without breaking a guarantee)

- `AUDIO_DIR` (`audio.py:36`) — dead constant.
- `RAW_SUB_DIR` / `SRT_DIR` (`subtitles.py:24-25`) — single-use constants.
- The fuzzy `stem in md_name` containment check (`archive.py:168`).
- The four dead Rule-A md probes (§2).

### 3.5 Cost of a shape change: 53 product-path code lines

Verbatim grep over `src/bili_asr/*.py`: `transcripts` 96 lines, `subtitles` 38 lines, `"audio"` literal 24
lines. Filtering to lines that actually build or consult a product **relative** path: **53 sites in 13
modules**.

| Kind | Count | Sites |
|---|---|---|
| **Authority** (owns the layout) | **16** | `archive.py` 75, 160, 464; `manifest.py` 417-422; `path_policy.py` 25, 44, 50, 53; `subtitles.py` 24-25; `audio.py` 36 |
| **Re-derive** by string join | **37** | `search_index.py` 10; `audio.py` 5; `cli.py` 5; `integrity.py` 5; `quality.py` 5; `coordinator.py` 3; `audio_reclaim.py` 2; `audio_budget.py` 1; `coverage_report.py` 1 |

Of the 37 re-derived: **26 are read/probe**, 7 write/construct, 4 other. **26 read probes is the honest
cost driver** — a layout change must keep the old probe alive for legacy rows (§3.1).

Test surface: 40 of 53 test files mention the product layout; 332 `transcripts` lines, 120 `"audio"` lines,
82 `audio/` lines, 113 `subtitles` lines.

### 3.6 Measured on-disk shape of real roots

| Root | Files | Dirs | Notable |
|---|---|---|---|
| `/mnt/123pan/bili-asr-e2e/asr-vs-subtitle` | 36 | 6 | **Pure product tree** — zero state files. `transcripts/srt` holds 12 (6 `.srt` + 6 markers) |
| `/mnt/123pan/bili-asr-e2e/subtitle-publish` | 30 | 6 | Contains a leftover `transcripts/.archive-bundle-stage/` — a kill residue, exactly the wedge `cli.py:1360-1366` documents |
| `.tmp/qa-probe/F-A` (local) | full root | — | `archive.db`, `manifest/`, `coordinator/`, `transcripts/`, **plus** a second product subtree `control-asr/transcripts/{srt,txt,md,raw}` — an artifact root **nested inside** the archive root, which `artifact_root.py:42-44` explicitly accepts |

The nested case is evidence that a shape change must work for a base that is itself inside another base.

---

## 4. Candidate shapes with measured cost

### Target A — per-work bundle directory

```
transcripts/{bvid}.p{page}/{bundle.srt,bundle.txt,bundle.md,bundle.raw.json,.bundle-ready}
```

| Aspect | Assessment |
|---|---|
| Addresses | All of §2 (one rule for all four files); the orphaning defect disappears |
| Changes | `archive.py:160` (shape check) **and** `:186` (marker derivation) **and** `:155-168` validator; `_ARTIFACT_REL_DIRS` (`manifest.py:417-422`) must become a bounded scan — **it cannot enumerate an unbounded set of per-work dirs** (the bare-`bvid` mis-assignment risk, §3.3 #6); all 26 read probes |
| Migration | Legacy rows keep the old shape; validator and probes must accept both, legacy-first |
| Cost | **Highest.** 3 load-bearing structures + 26 read probes. The unbounded-directory problem is a correctness risk, not just work |
| Risk | `manifest._foreign_page_stems`' guarantee is hard to preserve |

### Target B — one directory, kind in the extension

```
transcripts/{stem}.{srt,txt,md,json}
```

| Aspect | Assessment |
|---|---|
| Addresses | §2 and the 4-level nesting; the md becomes `{stem}.md` |
| Changes | `archive.py:464` (one line), the 4 dead Rule-A probes **become correct**, the glob at `quality.py:416` can be dropped |
| Migration | Legacy rows: `archive_bundle_complete` (§3.2) still owed a both-shapes reader |
| Cost | **Low.** The `transcripts/srt|txt|md|raw` quartet collapses to one dir |
| Risk | **Conflicts with the published promise** (`README.md:602-607` names `transcripts/srt/<stem>.srt` and `transcripts/txt/<stem>.txt` explicitly). The marker-in-srt-dir derivation (§3.3 #2) must move to the shared dir, and `.archive-bundle-stage` then shares a directory with live products |

### Target C — keep the four kind dirs; fix the md name only

```
transcripts/srt/{stem}.srt    transcripts/txt/{stem}.txt
transcripts/md/{stem}.md      transcripts/raw/{stem}.json
```

| Aspect | Assessment |
|---|---|
| Addresses | **§2 only** — the measured orphaning defect and the one inconsistent rule. Does *not* reduce the number of directories (the complaint as literally stated) |
| Changes | `archive.py:468` (one line); 4 dead probes become live; the `quality.py:416` glob can be dropped; `integrity.py:360`'s identity check becomes stable |
| Migration | **None for old rows in the completeness sense**: the four-family shape is unchanged, so `_owned_bundle_parts` (§3.2) still accepts every legacy row. Only the *md filename* differs, and legacy rows still record their own |
| Cost | **Lowest.** 1 writer line + 4 probe fixes + tests |
| Risk | None identified beyond the deliberate frontmatter/filename format revision |
| Limitation | It is a defect fix, not the restructure. If the operator wants fewer directories, this does not deliver it |

---

## 5. Decision required

## DECIDED 2026-09-28: L1 = **A**, and the decision is closed

The operator chose **A (per-work bundle directory)**, with two further rulings
given in the same turn that this survey did not anticipate:

- **L2 is answered "revise it".** The published four-family promise is revised as
  a deliberate, documented format revision rather than preserved.
- **No backward compatibility.** L4's both-shapes reader is *not* owed: the
  operator ruled "不要考虑兼容旧的", matching the rule `archive.db` already
  follows (rebuildable by policy, no migration path).

Delivered on branch `feat/layout-shape-a` (not this iteration's branch — the
iteration was already closed when the decision landed). As built:

```
transcripts/{stem}/bundle.srt | bundle.txt | bundle.md | bundle.raw.json | .bundle-ready
```

One correction to this survey's own cost estimate, found while implementing: A's
"26 read probes" was accurate as a count but understated where the danger sat. The
two load-bearing structures that actually broke were not the probes (which are
mechanical) but the two places that **derived identity from a file name** —
`quality._check_identity` and `manifest._foreign_page_stems`. The second was the
serious one: it guards a permissive failure (migrating onto files that already
exist), and it silently went blind to every artifact published before the
revision. That is the failure mode to look for when moving identity from a name
to a directory.

The original survey text follows, unedited, as the record of what was known
before the decision.

---

The operator chose (2026-09-26) to **hold the target shape open** pending this survey. The decision below is
therefore **open** and owned by the user; the layout-migration plan cannot be written until it lands.

| # | Decision | Options | Blocking? |
|---|---|---|---|
| L1 | Which target shape? | A (per-work dir) / B (flat, kind-in-extension) / C (four dirs, md renamed) / a combination — e.g. **C now, A later** | **Yes** |
| L2 | Is the published four-family promise (`README.md:602-607`) negotiable? | Keep it / revise it as a deliberate documented format revision | Yes for A and B; no for C |
| L3 | Does the operator want fewer directories at all, or only the naming defect fixed? | The complaint says "too scattered"; the measured defect is §2 | Yes — it selects C vs A/B |
| L4 | Is a both-shapes reader owed permanently, or only for one transition release? | Permanent read tolerance (legacy-first) / bounded transition window | Yes for A and B; moot for C |

**Label map to the compass** (the two documents name the same slate differently): `L1` is the compass's
**Q4**, `L2` is **Q5**, `L3` is **Q6** — row for row, same questions and same blocking flags. The compass's
Q4 also points at "decision items L1-L4" as a group, but **L4** has no question row of its own; it is this
survey's subsidiary question, owed only if A or B is chosen.

### Recommendation (not a decision)

**C now, and re-decide A/B with the operator's own answer to L3.** Reasoning, in the order that matters:

1. C removes the **measured** defect (the orphaning rule) at the lowest cost, with **no** completeness
   migration — because the four-family shape stays, `_owned_bundle_parts` keeps accepting every legacy row.
   A and B each owe a both-shapes reader (§3.2) and touch the unbounded-directory risk (§3.3 #6).
2. C and B share their first line of work: both fix the md name. If the operator later wants B, C's change is
   a strict prerequisite, not a discarded effort.
3. A is the only shape that removes the last structural risk (the two-rules problem) *and* reduces nesting,
   but it pays the highest price and endangers the bare-`bvid` guarantee. It should be chosen on L3's answer,
   not by default.
4. **A follow-up plan is owed under any answer** for the 37 re-derive sites: a single layout module
   (`paths.py`) returning names by `(family, stem, extras)` would let the 16 authority sites keep owning the
   layout while the 26 read probes stop restating it. That refactor is shape-independent and is the durable
   half of the operator's complaint. It is **not** in this iteration — it is item 3 of `## Roadmap
   Position` in this iteration's `delivery-compass.md`, scheduled behind the shape decision.

---

## 6. What is deliberately NOT in scope

- Migrating existing archives on disk: the shipped non-goal (`.mstar/iterations/iter-2026-09-artifact-root/
  specs/artifact-root-contract.md:443`). Recorded paths stay relative; any physical `mv` is the operator's.
- Moving the 10 **state** families: `README.md:470-475` explains why they cannot move (fsync pair, SQLite
  locking across FUSE/WebDAV). Out of scope permanently, not deferred.
- The `.archive-bundle-stage` wedge (a hard kill leaves it and wedges later publications): already registered
  as `20260920-transcript-projections · R2` (medium). It is adjacent — a shared-dir shape (B) would make it
  worse — but it is a separate fix.
