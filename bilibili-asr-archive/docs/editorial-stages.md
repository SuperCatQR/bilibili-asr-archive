# Editorial stages: `align-transcripts` and `verify-proofread`

This is an **operator document** for the two commands that make the proofread
stage repeatable: one builds the **two-route alignment** for a stored part, one
**verifies** a proofread candidate against that part's own rules. The design
record is the iteration contract
(`iter-2026-09-transcript-editorial-stages/specs/editorial-stage-contract.md`;
decisions cited below as **D11**–**D18**).

Read this beside [`artifact-root.md`](artifact-root.md) — both commands read the
archive and one of them writes below the configured artifact root.

---

## What the stage is, in one paragraph

A part's transcript exists twice: a **local ASR** route (the bundle's `raw`
sidecar) and a **caption** route (B站's AI/CC subtitle, in `archive.db`). An
editorial proofread produces a third text, the **candidate**. The two commands
here do not proofread anything: `align-transcripts` says **which input unit
landed in which block** and accounts for every unit; `verify-proofread` checks
the candidate's bytes against the part's own rules and refuses, by name, when
one is broken. The editorial judgement stays with the operator (or the agent
running the skill); the commands only ever report.

**Neither route is ground truth.** They are both machine transcripts of the same
audio, they disagree, and a disagreement is information — `align-transcripts`
keeps it visible instead of resolving it, and `verify-proofread` checks the
candidate against **both** rather than electing one.

**No audio is listened to.** Neither command opens a socket, downloads,
transcribes or reads audio. Every line either one prints was decided from files
below the archive root and rows in `archive.db`. A candidate that "reads
better" is not thereby accepted: only the written rules decide.

---

## `bili-asr align-transcripts`

```
bili-asr align-transcripts [--bvid <bvid[:pN]>] [--archive-root <root>] [--artifact-root <root>]
```

Align a part's two machine routes into one **block accounting**.

### Where the two routes come from (D13)

| route | source | unit |
|---|---|---|
| ASR | `<archive-root>/transcripts/raw/<stem>.json` — the bundle's `raw` sidecar, `{segments, source, provenance}` | seconds in the file, converted to **milliseconds** by the command |
| caption | `archive.db`, read **read-only**: `subtitle-ai` / `subtitle-cc` | milliseconds in the store |

`<stem>` is the archive writer's own name (`<bvid>.pN` for a resolved part), so
the sidecar is read at the path `publish-transcripts` wrote it to. Nothing is
read from a loose file the operator names: there is no route flag, by design.

### What it prints

One accounting line per candidate, then a closing counts line:

```
BV1zz5zzFENq:p0: aligned blocks=50 segments_in=425 segments_attached=425 segments_unattached=0 cues_in=797 cues_attached=783 cues_unattached=14
align-transcripts: candidates=1 aligned=1 refused=0
```

The two identities are a **subtraction you can perform on the printed line**:

```
segments_in == segments_attached + segments_unattached
cues_in     == cues_attached     + cues_unattached
```

`*_unattached` is not an error and is never dropped to make the identity true.
A caption cue whose midpoint falls outside every block is an unattached cue:
the routes genuinely disagree there, and the number is the operator's signal to
look. The arithmetic is printed, never inferred from an exit code.

**Blocks** are formed from the ASR route alone: a new block starts when a
segment begins more than `GAP_MS = 1500` ms after the previous segment ended.
Cues do not create blocks; they attach to the block their midpoint falls in.

### What it writes (D16)

```
<artifact-root>/alignments/<work_id>.jsonl
```

The first line is a header (`kind: "header"`, plus the six counts and `blocks`),
then one line per input unit — every ASR segment, then every caption cue, in
input order — each naming its `kind`, `index`, `start_ms`, `end_ms` and the
1-based `block` it landed in (or `null` for an unattached unit). No transcript
text is written; the artifact is an index into the two routes, not a copy of
them.

The root comes from the **existing** `--artifact-root` flag (or
`BILI_ARTIFACT_ROOT`); with neither set it is the archive root, exactly as for
the other artifact-writing commands. There is **no** flag to switch the write
off and none to redirect it: persistence is unconditional. A second run rewrites
the same bytes, so the artifact is reproducible and safe to re-derive.

**Nothing is ever written under `transcripts/{srt,txt,md,raw}`.** Those four
families belong to `publish-transcripts`; the alignment is not a transcript.

### Range and exit

- With **no** `--bvid`: every stored part holding both routes.
- With `--bvid <bvid>`: every stored part of that video.
- With `--bvid <bvid:pN>`: exactly that part.

An unknown selector is the shipped configuration error
`align-transcripts: unknown --bvid <value>` on **exit 1**.

Exit `0` when every candidate aligned — **including zero candidates**, which is
the normal answer today (no store holds an ASR route; the route is the sidecar).
Exit `1` for a configuration error and for a candidate the command **refused**.

**`2` is never produced.** There is no socket to fail and argparse's own usage
error is mapped to `1`.

### A named selector is an assertion

With no selector, a part that lacks a route is **outside the range**: it produces
no candidate and no line at all. Naming the part changes the act's meaning —
`--bvid <bvid:pN>` asserts the part is ready, so a missing route is refused:

```
BV1T3ALIGN:p0: refused (route_absent_for_part) at asr route (absent)
```

That line carries the rule id the contract's §E defines for it, and the location
names **which** route is absent. A part whose sidecar is unreadable, shapeless,
or whose stored caption cannot be read back is reported the same way, with the
cause in parentheses.

---

## `bili-asr verify-proofread`

```
bili-asr verify-proofread --candidate <path> --bvid <bvid[:pN]> [--archive-root <root>]
```

Verify one proofread candidate against its part's two routes. Unlike the
builder, `--bvid` is **required** and always names exactly one part: the
candidate is checked against *that* part's routes, and a candidate whose own
frontmatter `work_id` disagrees with the selector is refused by name. There is
no artifact flag — this command writes nothing.

### What it prints

```
BV1zz5zzFENq:p0: ok (body_chars=8148 marks=10 record_rows=68)
verify-proofread: candidates=1 ok=1 refused=0
```

A violation prints `<work_id>: refused (<rule>) at <location>`; an advisory
prints `<work_id>: warning (<rule>) at <location>` and **changes neither the
verdict nor the exit**. Locations are `<basename>:<line>` for sites in the
candidate — the basename only, never your parent directories — and `[hh:mm:ss]`
or a cue index for sites on a route.

The rules checked are the contract's §E vocabulary: marker vocabulary
normalised (`‹?›` vs `〔?〕`) with body-marker ↔ record-row **parity**, every
recorded change carrying its evidence, character-level containment against
**both** routes, and the hotword-table screen.

Exit `0` when the candidate is ok, `1` for a refusal or a configuration error
(an unknown `--bvid`, a missing or unreadable database, an unreadable
`--candidate`, a part whose routes are not both reachable). `2` is never
produced.

**This command does not proofread and never repairs the candidate it is given.**
It reads the file, reports, and stops.

---

## Reproducing a measurement: the corpus

The stage's numbers were measured against a six-item delivered corpus held
**outside** this repository, at `/mnt/123pan/bili-asr-e2e`. The test suite
references it by path and pins each file by sha256; the corpus is never copied
into the repository, and the suite stays green on a machine that has never seen
it — the corpus cases `skipif` it is absent rather than failing.

The replay loads the caption sidecar into a synthetic store and copies the ASR
sidecar to the bundle path the writer's own rule names, then runs the command
over both, so the two routes it reads are the two routes an archive publishes.
A missing or digest-mismatched corpus file is a **refusal naming that file**,
never a silent pass.

The wave's own `INDEX.md` counts 对齐块 with a different algorithm (the
machine-baseline's ~12-second chunking), so its column is **not** the oracle for
`blocks=`; the replay's recorded lines are.

---

## What neither command proves

- **No audio was listened to.** Both routes are machine output; so is every
  count here. A human who has heard the audio knows something these commands
  cannot.
- **The judgement is the agent's.** `verify-proofread` checks a candidate
  against written rules; it cannot tell whether the candidate is *right*, only
  whether it is *accounted for*.
- **Neither route is ground truth.** Containment is checked against both
  routes because electing one would import its errors as the standard.
- **A clean exit is not a proofread.** Exit `0` means "every rule I know was
  satisfied", not "this text is correct".

---

## Related documents

- [`artifact-root.md`](artifact-root.md) — the two roots, and which commands
  carry `--artifact-root`.
- [`metadata-storage.md`](metadata-storage.md) — `archive.db`, where the caption
  route lives.
- `.mstar/specs/asr-archive-cli.md` — the CLI surface's frozen spec, including
  the added-command enumeration and the exit taxonomy.
