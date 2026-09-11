# Subtitle CLI Contract (iteration spec)

> Iteration `iter-2026-09-subtitle-transcript-sqlite`, spec point 3.
> Status: architecture locked (2026-09-11); product intent reviewed (product-manager,
> 2026-09-11); writing/corpus hygiene reviewed (writing-specialist, 2026-09-11);
> PM lock: locked (project-manager, 2026-09-11).
> Command vocabulary, exit codes, and output shapes below are the shipped archive
> conventions (`argparse` usage errors exit `1` via `_UsageErrorArgumentParser`,
> `sessdata: present|absent` via `redact_sessdata`, `bvid:pN` via
> `page_identity.parse_work_id`), reused rather than reinvented.

## Goal

Make the existing `bili-asr` executable the operator surface for subtitle acquisition
against the SQLite archive: enumerate pending parts from the database, acquire AI/CC
subtitles through the typed gateway, store normalized transcripts, and report bounded
outcomes — without reading or writing any JSONL sidecar on the new path.

Product framing: this spec owns everything the operator sees. Two rules govern every line of
output. First, the operator can always tell *what happened* — what was attempted, what was
stored, what was unchanged, what had no visible caption, what failed and with which bounded
code. Second, the operator is never shown a credential value, a signed URL, or a raw upstream
error, and is never given a number that reads like coverage of the corpus.

## 1. Operator semantics (locked)

**"No subtitle" means "nothing was visible".** A part is reported as `no-subtitle` when no
usable track was visible for it with the credential in effect at that attempt. It does **not**
mean the video has no captions: AI tracks may not exist yet, uploader CC may never have been
provided, and login-gated tracks are invisible anonymously. Every run therefore reports
whether a credential was in effect, and a part recorded as `no-subtitle` stays eligible for a
later attempt. The classification also covers a part upstream no longer serves (a `not_found`
or `-101` answer) — the wording in the docs is "no usable track was visible for this part at
this attempt", never "this video has no captions".

**Outcome mapping** — exactly one outcome per attempted part:

| Gateway result | Part outcome | Operator reading |
|---|---|---|
| Listing returned zero tracks, or the fetch answered `not_found` | `no-subtitle` | Nothing visible now; retry later or with a credential — not a failure. |
| Content identical to what is stored for this part/source/language | `unchanged` | The archive already holds this caption; nothing was rewritten. |
| New content, or content that differs from every stored version | `stored` | A new version was written; earlier versions stay readable. |
| `rate_limited`, `transport_error`, `response_error`, `shape_error` | `failed` (with the bounded code) | Retry later for the first two; the last two need investigation. |

**Honesty rules** — each is testable:

1. A run always prints all four counts — `stored`, `unchanged`, `no-subtitle`, `failed` —
   including the zeros, plus the run id, credential presence, and the number of parts still
   without a transcript. A zero count is never omitted: the operator must not have to infer it.
2. `no-subtitle` is never counted as `failed`, and a run in which every attempted part had no
   visible caption still exits `0` — with the printed counts making clear that nothing was
   stored.
3. Partial failure stays visible in the counts, not in the exit code. Exit `2` is reserved for
   a run that failed on every attempted part, or for an unexpected internal error reported
   with a fixed bounded message.
4. A part without a visible caption is never given a success marker, and a part that was never
   attempted is never presented as if it had been.
5. Credential reporting is presence-only (`sessdata: present|absent`); the value never appears.
6. Neither command writes an on-disk projection: no `subtitles/raw/*.json`, no
   `transcripts/srt/*.srt`. The transcript lives in `archive.db`; rebuilding files from it is
   deferred work owned by the next iteration (documented, not silently dropped).

## 2. Commands

Both commands are added to the existing `bili-asr` entrypoint (`cli.py`); the command names
already exist and their legacy manifest behaviour is replaced by this contract.

```text
bili-asr probe-subs  [--archive-root PATH] (--bvid BVID|BVID:pN | --limit-parts N) [--sessdata VALUE]
bili-asr harvest-subs [--archive-root PATH] [--bvid BVID|BVID:pN] [--limit-parts N]
                      [--language PREF[,PREF...]] [--sessdata VALUE]
```

- `--archive-root PATH` (default `archive`): the archive root holding `archive.db`.
- `--bvid BVID` selects **every part of that video already in the database**;
  `--bvid BVID:pN` selects exactly one part, using the archive's own zero-based part
  vocabulary (`page_identity.parse_work_id`). A selector that resolves to zero rows in
  `video_parts` is a configuration error (exit `1`, fixed message
  `unknown --bvid <value>`), never an empty result.
- `--limit-parts N` (positive integer) bounds the run.
- `--sessdata VALUE` (or `BILI_SESSDATA`): same resolution and redaction path as the shipped
  metadata commands (`resolve_sessdata`, `redact_sessdata`).
- `--language PREF[,PREF...]` (`harvest-subs` only): the selection preference (section 3).

### 2.1 `bili-asr probe-subs` (read-only)

Lists the subtitle tracks the selected parts expose. It performs **no writes at all**: no
database creation, no transcript row, no acquisition run or attempt row, no lock file.

- Selection: exactly one of `--bvid` / `--limit-parts` must be given; giving neither (or both)
  is a usage error (exit `1`). `--limit-parts N` probes the first N parts of the pending
  enumeration (section 4 order). `--bvid` probes every part of that video already in the
  database, or the single `bvid:pN` part named.
- The database must already exist: a missing `archive.db` prints the shipped read-command line
  (`probe-subs: no archive database at <root>; run fetch-meta to create it`) and exits `1`.
- `probe-subs` is **not** an archive-writer command: it is removed from
  `_ARCHIVE_WRITER_COMMANDS`, so it takes no `coordinator/archive-writer.lock` and creates no
  file under the archive root. It stays a reader while another process writes, exactly like
  `status` / `runs`.
- Output, in this order:

  ```text
  sessdata: <present|absent>
  probe <work_id> tracks=<n>
    track <lan> <ai|cc> <lan_doc>
    ...   (repeated once per visible track)
  probe <work_id> tracks=0
    (no subtitles visible)
  probe <work_id> failed <error_code>
  probe-subs: probed=<n> with_tracks=<n> without_tracks=<n> failed=<n>
  ```

  One `probe` line per selected part, in selection order; a zero-track part is printed with its
  explicit `(no subtitles visible)` marker and never omitted, so "no tracks" cannot be
  confused with "not attempted". A part whose listing failed carries the bounded code on its
  own line (no track lines, no success marker), and the summary counts it under `failed=`.
  Each track line prints the upstream `lan`, the `ai`/`cc` marker, and the display label last
  (labels contain spaces). Never a signed URL, raw JSON, credential, or upstream message text.
- Exit codes: `0` the probe ran (including parts with zero visible tracks); `1` usage/config
  (missing database, unknown `--bvid`, neither or both selectors, schema guard); `2` the probe
  failed on every selected part, or an unexpected internal error. Partial per-part failure is
  visible in the printed `failed=` count and does not by itself decide the exit code — the same
  discipline `harvest-subs` applies to its per-part failures.

### 2.2 `bili-asr harvest-subs`

Acquires subtitles for the selected parts and stores normalized transcripts plus per-part
attempt evidence.

- Selection:
  - default (no `--bvid`) — the parts of the pending enumeration (section 4), never-attempted
    first;
  - `--bvid BVID` — every part of that video already in the database, **including parts that
    already have a transcript**. That explicit path is how the operator re-checks a video after
    upstream adds or revises a caption; the run then reports `unchanged` or stores a new
    version.
- `--limit-parts N` is required whenever the selection is not a single `bvid:pN` part; a single
  explicit part is bounded by construction, so the bound may be omitted there. No unbounded
  runs: omitting the bound on a non-single-part selection is a usage error (exit `1`).
- Per part: list tracks through the gateway → select one track with the preference rule
  (section 3) → fetch the segments → store the transcript and the attempt evidence in one
  transaction. The `cid` always comes from `video_parts` for that part; the subtitle path never
  fetches a pagelist and never calls upstream for a part that is not in the database.
- One `acquisition_runs` row per run (`kind='subtitle'`, `selector_kind`/`selector_target`
  from the selector, `requested_limit`, `credential_present`, `started_at`, `finished_at`,
  `outcome`), and exactly one `acquisition_attempts` row per attempted part, written by the
  storage contract in `specs/transcript-storage.md`.
- Output, in this order:

  ```text
  sessdata: <present|absent>
  harvest <work_id> stored <source_kind> <language> v<version>
  harvest <work_id> unchanged <source_kind> <language> v<version>
  harvest <work_id> no-subtitle
  harvest <work_id> failed <error_code>
  harvest-subs: run_id=<run_id> attempted=<n> stored=<n> unchanged=<n> no-subtitle=<n> failed=<n> remaining_without_transcript=<n>
  ```

  One line per attempted part in attempt order, then one summary line. `stored`/`unchanged`
  lines carry the stored or matched source kind, language, and version, so the operator can see
  *which* caption was kept. All four counts appear on the summary line including zeros;
  `remaining_without_transcript` is `count_pending_subtitle_parts()` read after the run. Never
  a credential, signed URL, raw body, or upstream message text.
- Exit codes: `0` the bounded run completed, including "no subtitle visible" for every
  attempted part and including a run whose selection was empty (`attempted=0`); `1`
  usage/config (missing database, unknown `--bvid`, bound required, schema guard in section 5);
  `2` the run failed on every attempted part (`attempted > 0` and every part `failed`), or an
  unexpected internal error (fixed line `harvest-subs: unexpected error`, no traceback) — in
  both variants the run row is finished as `failed` when it was opened, and the per-part
  evidence already written stays readable.

## 3. Track selection preference (locked mechanism)

The service selects exactly one track from the listed inventory. Upstream `lan` codes differ
between caption kinds for the same spoken language (uploader Chinese is `zh-CN` / `zh-Hans` /
`zh-Hant`; AI Chinese is `ai-zh`), so the default is defined on a **language family** derived
from the two normalized facts the DTO already guarantees — `language` and `is_ai` — instead of
on a fixed list of exact codes or on an AI↔CC translation table. A fixed list silently
mis-ranks any code upstream adds; an equivalence table has to be maintained against upstream
vocabulary and can flip without warning.

Family derivation (total, because the gateway rejects a `lan` without a non-empty primary
subtag):

```python
def language_family(language: str, is_ai: bool) -> str:
    code = language.strip().lower()
    if is_ai and code.startswith("ai-"):
        code = code[3:]
    return code.split("-", 1)[0]
```

- **Default (no `--language`)**: rank by the default family order `("zh", "en")`, then every
  remaining family in upstream order; inside one family prefer `is_ai = False` (CC) over AI;
  then keep upstream order. Implemented as a stable sort on
  `(family_rank, is_ai, upstream_index)` and taking the first track.
  - Property the tests pin: for **any** Chinese CC code and **any** Chinese AI code, in either
    upstream order, the CC track is selected.
  - The shipped legacy order (`subtitles._LAN_PREFERENCE = ("ai-zh", "zh-CN", "zh-Hans",
    "en")`, i.e. AI first) is thereby replaced; the docs and `--help` say so, and
    `--language` keeps the AI track reachable.
- **`--language PREF[,PREF...]`**: each entry is matched **exactly** against a track's
  `language` (the code `probe-subs` prints), first preference with a match wins; among tracks
  matching the same preference, CC before AI, then upstream order. Entries are trimmed,
  case-sensitive upstream codes; an empty entry is a usage error (exit `1`). A valid preference
  that matches no track of a part yields `no-subtitle` for that part (nothing usable *for the
  requested language* was visible), never `failed`.
- The selected track is reported per part (`source_kind` + `language` + version), so the
  operator can always see which caption a run kept, and `--language ai-zh` retrieves the other
  one.

## 4. Pending enumeration contract (consumed, not redefined)

`harvest-subs` (default selection) and `probe-subs --limit-parts` consume
`TranscriptRepository.list_pending_subtitle_parts(limit)` — `v_pending_subtitles` ordered by
`attempted ASC, last_attempt_at ASC, bvid ASC, page_index ASC`, as locked in
`specs/transcript-storage.md` §2.5. Consequences the CLI relies on:

- parts with a stored transcript are excluded;
- never-attempted parts are attempted before previously attempted ones;
- a part previously recorded `no-subtitle` stays in the set with its last outcome, timestamp,
  and credential presence;
- `probe-subs` records nothing, so "previously attempted" means "previously attempted by
  `harvest-subs`".

## 5. Service boundary and composition (locked names)

- `src/bili_asr/services/subtitle_ingest.py` defines `SubtitleIngestor`, which owns the
  candidate enumeration order, the selection preference, the per-part transaction boundary, the
  run-record lifecycle, and the outcome mapping. It depends on the `BilibiliGateway` protocol
  and `TranscriptRepository` only — never on the concrete adapter or a response dictionary.
- Surface (synchronous, like `MetadataIngestor`; the async gateway calls run on one event loop
  per operation):

  ```python
  @dataclass(frozen=True, slots=True)
  class SubtitleSelection:
      bvid: str | None = None           # None → the pending enumeration
      page_index: int | None = None     # set only together with bvid (from `bvid:pN`)
      limit: int | None = None          # required unless page_index is set
      languages: tuple[str, ...] = ()   # () → the default preference

  @dataclass(frozen=True, slots=True)
  class SubtitleProbePart:
      work_id: str
      tracks: tuple[SubtitleTrack, ...]     # () when nothing is visible
      error_code: str | None = None         # the bounded code when the listing failed

  @dataclass(frozen=True, slots=True)
  class ProbeResult:
      credential_present: bool
      parts: tuple[SubtitleProbePart, ...]

  @dataclass(frozen=True, slots=True)
  class SubtitlePartOutcome:
      work_id: str
      outcome: str                      # stored | unchanged | no-subtitle | failed
      error_code: str | None
      source_kind: str | None
      language: str | None
      version: int | None

  @dataclass(frozen=True, slots=True)
  class HarvestResult:
      run_id: str
      attempted: int
      stored: int
      unchanged: int
      no_subtitle: int
      failed: int
      credential_present: bool
      remaining_without_transcript: int
      parts: tuple[SubtitlePartOutcome, ...]

  class SubtitleIngestor:
      def __init__(self, gateway: BilibiliGateway, repository: TranscriptRepository,
                   *, clock: Callable[[], int] = ...) -> None: ...
      def probe(self, selection: SubtitleSelection) -> ProbeResult: ...
      def harvest(self, selection: SubtitleSelection) -> HarvestResult: ...
  ```

- `probe` writes nothing (no run row); `harvest` opens exactly one acquisition run, finishes it
  with the derived outcome (`complete | partial | failed`), and returns every number the
  summary prints, so the CLI stays a formatter and the honesty rules are assertable at the
  service level.
- Composition root in `cli.py`: `--archive-root` → the database existence check (**neither
  subtitle command creates `archive.db`, and `open_database` does create it**, so the file is
  checked before opening; a missing database prints the shipped `<command>: no archive database
  at <root>; run fetch-meta to create it` line and exits `1`) → `open_database` →
  `require_subtitle_schema` (subtitle commands only; a `SchemaContractError` prints the fixed
  rebuild line and exits `1`) → `TranscriptRepository(connection)` (the only repository these
  commands need: it reads `v_video_parts` and `v_pending_subtitles` and owns the transcript and
  attempt writes; `MetadataRepository` is not constructed, and no metadata write path is
  touched) → `BilibiliApiGateway(sessdata=...)` (the composition root, not the service,
  constructs the concrete adapter) → `SubtitleIngestor` → command handler prints.
- Expected gateway failures are resolved inside the service (`GatewayError.code` → part
  outcome); anything escaping the handler is an unexpected internal error: fixed line, exit
  `2`, no traceback — the shipped `fetch-meta` discipline.

## 6. Global constraints

- The new path never reads or writes `manifest.jsonl`, `meta-cursor.json`, or
  `run-ledger.jsonl`; tests assert absence of those files in the temporary archive root.
- The new path writes no file projection of the transcript (`subtitles/raw/*.json`,
  `transcripts/srt/*.srt`); `archive.db` is the only destination, and neither command creates
  a file under the archive root except `harvest-subs`'s database writes.
  > Dated PM note (2026-09-11, plan QC seat 2 QC2-003): read this together with the shipped writer lock —
  > `harvest-subs` is an archive-writer command and additionally takes `coordinator/archive-writer.lock`
  > (coordination state, pinned as exact behaviour by the E2E); `probe-subs` takes none. The database remains
  > the only content file either command writes.
- Only the typed gateway imports `bilibili_api`; the CLI composes config → database →
  repository → gateway → service.
- `SESSDATA` is redacted to presence-only in every display path.
- No new executable and no new command name: the existing `bili-asr` entrypoint gains the
  (already named) `probe-subs` / `harvest-subs` commands; their legacy manifest semantics are
  replaced and the replacement is documented (`README.md`, `docs/metadata-storage.md`).
- Command vocabulary follows the archive: `bvid` or `bvid:pN` addresses a part and every run is
  bounded.
- Existing ASR/pilot/manifest commands keep working unchanged — this iteration does not migrate
  them, and the docs record that boundary explicitly. Two consequences the docs must state:
  those commands still read the manifest, and `harvest-subs` no longer produces the manifest
  status `needs_audio`, so the legacy audio feeder (`download-audio --missing-subs`) gains no
  new entries from the SQLite path.
- Operator documentation (`README.md`, `docs/metadata-storage.md`) must describe what the
  commands actually do: the two commands, their bounds, the exit codes, the preference rule,
  the credential handling, the SQLite-only projection boundary, the untouched legacy path, and
  the rebuild procedure when the database predates the transcript schema.

## 7. Tests

- Parser/usage tests: `--limit-parts` required unless a single `bvid:pN` is named; `probe-subs`
  requires exactly one of `--bvid`/`--limit-parts`; a missing database on a read command →
  exit `1`; an unknown `--bvid` → exit `1`; an empty `--language` entry → exit `1`; every usage
  error exits `1`, never `2` (`_UsageErrorArgumentParser`).
- Preference tests: the CC-before-AI property for a table of Chinese CC/AI code pairs in both
  upstream orders; family ranking (`zh` before `en` before the rest); exact `--language`
  matching, including that `--language ai-zh` selects the AI track and an unmatched valid
  preference yields `no-subtitle`.
- Offline E2E over the fake seam: store → re-run `unchanged` → changed body appends a version
  with the earlier version still readable; a part with no visible caption recorded as
  timestamped `no-subtitle` evidence and never as success; that same part acquiring a
  transcript in a later run; a never-attempted part attempted before an already-attempted one;
  `probe-subs` leaving no file and no database behind when none exists; no-sidecar assertions.
- Output assertions for the honesty rules: all four counts including zeros, run id, credential
  presence, remaining parts without a transcript, zero-track parts printed by `probe-subs` with
  their explicit marker, and the exact `probe` / `harvest` / summary line shapes of section 2.
- No-leak scans over output and all persisted rows (credential + signed-URL sentinels), plus an
  assertion that neither command creates a file under `subtitles/raw/` or `transcripts/srt/`.
- Schema-guard tests: a database with the pre-iteration `transcripts` shape makes both commands
  exit `1` with the fixed rebuild line while `status` keeps working.
- One opt-in bounded live smoke (temporary archive root, a small `--limit-parts` bound) that
  asserts real normalized rows when a visible caption exists, and records an explicit bounded
  blocker otherwise — never a claim about the corpus.

## 8. Acceptance

- `harvest-subs` on a fresh database with a bounded selection produces normalized transcripts
  (or bounded evidence for parts without visible captions), is idempotent on re-run, advances
  on the next run, and leaves no sidecar or projection file behind.
- `probe-subs` prints track metadata only, prints zero-track parts explicitly, writes nothing,
  and never creates the database.
- Every run summary is complete (four counts including zeros, run id, credential presence,
  remaining parts without a transcript), and no output claims corpus or caption coverage.
- Exit codes match the taxonomy above, and partial per-part failure is visible in the counts.
- The selection rule is deterministic, documented, overridable with `--language`, and reports
  the stored source kind, language, and version per part.
- `SESSDATA` appears only as presence; no signed URL, raw body, or traceback reaches output,
  logs, or rows.
- Operator documentation matches the shipped behaviour: bounds, exit codes, preference rule,
  projection boundary, rebuild procedure, and the untouched legacy manifest path.
