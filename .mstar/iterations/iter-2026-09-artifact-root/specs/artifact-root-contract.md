# Spec: the artifact root — relocatable products, state that stays put

**Status:** architecture locked (2026-09-19, architect pass) — iteration `iter-2026-09-artifact-root`, Phase 1.
**Consumers:** plan `20260919-artifact-output-root` (`{PLAN_DIR}/20260919-artifact-output-root.md`).
**Charter:** iteration compass `D1`–`D6` (user-locked 2026-09-19,
`{ITERATION_DIR}/iter-2026-09-artifact-root/delivery-compass.md:43-52`) plus the decisions this contract settles
(D7–D20, §3–§10).
**Placement:** iteration-level contract. The frozen repo-level spec `{SPECS_DIR}/asr-archive-cli.md` is **not**
edited by this iteration; §12 states the revision it owes and who owns it (D19).
**Reading discipline:** every claim below names the file and line it rests on. Code lines are pinned to
`HEAD 5961800` (the plan's drift-check stamp); if a cited line moved, re-read before trusting the claim. Two
recon line numbers were wrong and are corrected in §15 — the corrections are part of the deliverable, not
errata.

---

## 1. What this contract fixes

The location of the pipeline's **products** — audio, transcript bundles, harvested subtitle documents — becomes
configurable per invocation, so an operator can point it at a WebDAV FUSE mount (`/mnt/123pan`) while the
repository, the worktrees and the project **state** stay where they are (D1). Audio is retained indefinitely
(D5); there is no migration (D6).

Three sentences carry the whole design:

1. **The recorded paths do not change.** `audio_path`, `srt_path`, `txt_path`, `md_path`, `raw_path` stay what
   they are today — artifact-root-relative, e.g. `audio/{stem}.m4a`, `transcripts/srt/{stem}.srt` — so the
   manifest's bytes are unaffected by this feature and no reader needs to know which root a row was written
   under (D7).
2. **Only the base changes.** A reader resolves a recorded relative path against an ordered pair of bases
   (configured artifact root first, then the archive root), each probed and validated **at its own base**
   (D8). This is what makes D6's "an existing archive root keeps working" true rather than merely stated.
3. **The guard is re-based, not weakened.** `path_policy.py` is already root-parameterized and is **not
   modified**; what changes is which root the callers hand it (D4, §6).

## 2. The split this contract rests on

### 2.0 The decision register this contract adds (D7–D19)

`D1`–`D6` are the user-locked charter (compass `:43-52`). Everything below was settled in this pass and is
binding on the plan; each row names where it is argued.

| # | Decision | § |
|---|---|---|
| **D7** | Every recorded artifact path (`audio_path`, `srt_path`, `txt_path`, `md_path`, `raw_path`) stays an **artifact-root-relative** string with its shipped shape; the manifest's bytes are unaffected by the feature | §5 |
| **D8** | Reads resolve a recorded path over an **ordered pair of bases** (artifact root, then archive root), each candidate validated at its own base by that family's existing guard — never a cross-root path computation | §5 |
| **D9** | Precedence `--artifact-root` > `BILI_ARTIFACT_ROOT` > archive root; blank counts as unset at either level; `~` expanded; a relative value resolves against the CWD; the lexical path is kept (never `realpath`-resolved) | §3.2 |
| **D10** | A configured value equal to the archive root is the **identity case** (no second base, no further validation); otherwise it must already be an existing directory or the command refuses with exit 1; a **missing root is never created**; a root **inside** the archive root is accepted | §3.3 |
| **D11** | A different filesystem is legal and expected; no cross-device rename exists because every publish stages and renames inside one directory descriptor | §3.3, §4 |
| **D12** | The artifact root is **recorded nowhere durable** (no sidecar, no manifest field); a later run with a different root neither rewrites nor invalidates earlier rows, and no previous root is ever discovered | §5 |
| **D13** | Only **products** relocate; state (`manifest/`, `archive.db`, `coordinator/`, sidecars, `search.db`) stays at the archive root | §2, §4 |
| **D14** | **No second writer lock** on the artifact root; the archive-writer lock stays archive-root-scoped and one artifact root per archive root is the supported configuration | §8 |
| **D15** | Retention is resolved **once at the command boundary** into a value passed down; `reclaim_audio` stops reading `os.environ`; `--keep-audio/--no-keep-audio` on the five archiving commands; the default flips to **retain** | §7 |
| **D16** | The audio cap and the campaign peak measure the **configured root's** `audio/`; legacy audio on the other device is not summed in | §8 |
| **D17** | An unusable configured root is a **refusal** (exit 1, named stderr line, no report body) for every flag-carrying command — never an empty inventory | §9, §14 |
| **D18** | The flag exists **only where it is honoured**: eleven commands for `--artifact-root`, five for the retention pair, six excluded with their reasons | §9 |
| **D19** | The `{SPECS_DIR}/asr-archive-cli.md` revision this iteration owes is **recorded, not written**: PM-owned, three specific rows named | §12 |

**Q1** (the retained-audio × `--max-audio-gb` interaction) is **not** decided here: it is a product trade-off
escalated to the user with options and a recommendation, §12.

### 2.1 Products (relocatable)

| Product | Written by | Anchor |
|---|---|---|
| `{root}/audio/{stem}.m4a` (or `.flac`) | `audio.download_audio` | `audio.py:201-202`, `:233`; staged+renamed inside the audio dir `:209-238` |
| `{root}/transcripts/{srt,txt,md,raw}/{stem}.*` | `archive.write_archive` | `archive.py:466-471`, published by `_publish_bundle` `:220-261` |
| `{root}/transcripts/srt/{stem}.srt` (harvested caption) | `subtitles.harvest_subtitle` | `subtitles.py:136-147` |
| `{root}/subtitles/raw/{stem}.json` (harvested caption document) | `subtitles.harvest_subtitle` | `subtitles.py:136-137`, `:142-145` |

Every one of these values is stored **relative to the root it was written under**: `audio.py:276-279`
(`os.path.relpath(final_path, root)` then `entry["audio_path"] = final_rel`), `archive.py:488`
(`{key: os.path.relpath(path, root) ...}`), `subtitles.py:152` (`os.path.relpath(srt_path, root)`).

### 2.2 State (stays at the archive root)

| State | Path | Anchor |
|---|---|---|
| Manifest (append-only JSONL, fsync pair per append) | `{root}/manifest/manifest.jsonl` | `manifest.py:101-107`, `_append_record` `:178-191` (fsync at `:186`, `:189`), `_replace_snapshot` `:193-228` (fsync `:214`, `:220`) |
| Archive database (SQLite, deferred isolation, no WAL) | `{root}/archive.db` | `config.py:57`, `storage/database.py:40`, `open_database` `:196` |
| Coordinator attempts + writer lock | `{root}/coordinator/` | `coordinator.py:72-95` (`archive_writer`), `:183` (attempts ledger) |
| Cursor, scheduler, run ledger, campaign checkpoint, search index | `{root}/meta-cursor.json`, `{root}/scheduler.json`, `{root}/run-ledger.jsonl`, `{root}/campaign.json`, `{root}/search.db` | `coverage_report.py:77-83`, `run_ledger.py:336-345`, `campaign.py:117`, `search_index.py:354-355` |

The placement hazard this split respects: SQLite locking and the manifest's per-append fsync pair cannot be
carried onto a FUSE/WebDAV mount (compass §1, `## 5`). Relocating state would trade a correctness guarantee for
a path preference; that is why D1 is a split and not a move.

## 3. The artifact root: resolution, precedence, validation

### 3.1 Naming (D3, checked)

`--artifact-root` / `BILI_ARTIFACT_ROOT`. **Collision check (2026-09-19, this pass):**
`grep -rn "artifact_root\|ARTIFACT_ROOT\|artifact-root" bilibili-asr-archive/src bilibili-asr-archive/tests
bilibili-asr-archive/docs .mstar/specs` returns **no match** — no symbol, config key, CLI flag or doc uses the
name. The vocabulary it joins is already in the codebase: `page_identity.artifact_stem`
(`page_identity.py:41`, "filesystem names use `artifact_stem` only", `:4`),
`_record(..., artifact_paths=...)` (`coordinator.py:361`), and the archive
root is the single root today (`cli.py:28` `DEFAULT_ARCHIVE_ROOT = os.path.join("archive")`). The name reads as
"where the artifacts go when that is not the archive root". **No rename is proposed and no collision exists.**

### 3.2 Precedence and lexical rules (D9)

Resolution order, locked:

```text
--artifact-root <value>          (non-blank)   → use it
else BILI_ARTIFACT_ROOT          (non-blank)   → use it
else                                            → the archive root  (today's behaviour, byte-for-byte)
```

- **Blank never blocks the next level.** An empty or whitespace-only value at either level counts as *unset*
  and falls through (the value that resolves is stripped). This is `resolve_proxy`'s idiom
  (`config.py:154-175`), not `resolve_sessdata`'s (`config.py:128-141`): `resolve_sessdata`'s
  "a blank flag never falls through" rule exists because a credential has a security-relevant *anonymous* mode
  (`config.py:133-136`); a path has no such mode, and `export BILI_ARTIFACT_ROOT=` in a shell profile must not
  silently shadow a real flag.
- **`~` is expanded** (`os.path.expanduser`) before anything else touches the value.
- **A relative value is resolved against the process CWD** and stored absolute (`os.path.abspath`), exactly as
  `--archive-root` behaves today (`manifest.py:101-107` keeps the string; `archive._lexical_archive_root`
  `:264-265` and `path_policy.confined_audio_path` `:91-93` both apply `abspath`). A relative root therefore
  means "relative to where this command ran" — documented, and the reason the *recorded* paths stay
  root-relative (they survive a different CWD; the configuration does not).
- **The lexical path is kept, not `realpath`-resolved.** D4's guarantee is descriptor-anchored
  (`path_policy.open_audio_directory:32-57`, `archive._lexical_archive_root:264-275` open the root itself with
  `O_NOFOLLOW`). Calling `resolve()` first would defeat that check by silently following a symlinked root.
  Consequence, stated for the operator: **a symlinked artifact root is refused** — pass the real path. This is
  today's behaviour for the archive root, unchanged.

### 3.3 Validation (D10)

Applied once, at the command boundary, to the value that resolved:

| Value | Verdict | Why |
|---|---|---|
| lexically equal to the archive root (`os.path.abspath` comparison) | **accepted, identity case** — one base, today's code path, not validated further | an explicit no-op must be a no-op: the archive root's own lifecycle (created on demand by the shipped writers, `manifest._open_manifest_dir(create=True):108-127`) must not change because someone passed a redundant flag |
| an existing directory | accepted; the artifact subdirectories (`audio/`, `transcripts/{srt,txt,md,raw}/`, `subtitles/raw/`) are created on demand inside it exactly as today (`path_policy.open_audio_directory(create=True):47-55`, `archive._open_transcript_dirs(create=True):72-88`, `subtitles.py:139-140`) | the root is the operator's mount point; the product tree below it is the pipeline's |
| does not exist | **refused** — exit 1, before any work: `artifact root does not exist (<path>)` | creating it is the wrong default: an unmounted FUSE mount point still exists as an empty directory, and auto-creating a *missing* one would publish products to the underlying filesystem instead of the mount. Fail closed, name the path |
| exists, not a directory | **refused** — exit 1: `artifact root is not a directory (<path>)` | nothing can be written below a non-directory |
| a path inside the archive root (e.g. `{archive}/artifacts`) | **accepted** | a legitimate "keep the root clean" layout; the two bases are distinct and the ordered resolution (D8) handles it. Refusing it would need a `relative_to` test whose only effect is to forbid something harmless |
| a path on a different filesystem | **accepted — this is the point** | no cross-device rename can arise: every publish stages and renames inside **one** directory descriptor (`audio.py:221-238`, `archive.py:104-106`, `_publish_bundle:228-243`), so no `EXDEV` path is added (D11) |

**Partially configured state (the user's question, answered):** "artifact root set but the directory is
missing" is the *refused* row above, never created. "The root exists but `audio/` is absent" is the
*accepted* row: the pipeline creates the subdirectories on demand, exactly as it does today.

### 3.4 The resolved value object (D7, D8, D10 in one type)

```python
# src/bili_asr/artifact_root.py  (new leaf module)
ARTIFACT_ROOT_ENV_VAR = "BILI_ARTIFACT_ROOT"
KEEP_AUDIO_ENV_VAR = "BILI_KEEP_AUDIO"
KEEP_AUDIO_DEFAULT = True

class ArtifactRootError(ValueError):
    """A configured artifact root cannot be used → the command's usage/config exit (1)."""

@dataclass(frozen=True)
class ArtifactRoots:
    archive_root: Path          # absolute, lexical
    artifact_root: Path         # absolute, lexical; == archive_root when unconfigured

    @classmethod
    def of(cls, archive_root, artifact_root=None) -> "ArtifactRoots": ...   # abspath only, no isdir check
    @property
    def configured(self) -> bool: ...          # artifact_root != archive_root
    @property
    def write_base(self) -> Path: ...          # always artifact_root
    def read_bases(self) -> tuple[Path, ...]:  # (artifact_root, archive_root) if configured else (archive_root,)
        ...

def resolve_artifact_root(value: str | None, environ: Mapping[str, str]) -> str | None: ...
def resolve_keep_audio(flag_value: bool | None, environ: Mapping[str, str]) -> bool: ...
def roots_for(archive_root, *, flag_value=None, environ=None) -> ArtifactRoots: ...   # resolves + validates (§3.2/§3.3)
def resolve_audio_path(roots: ArtifactRoots, declared, *, require_exists: bool = True) -> Path | None: ...
```

`ArtifactRoots.of` is the one constructor the **libraries** use (their keyword default is
`artifact_roots=None` → `ArtifactRoots.of(archive_root)`, the identity case); `roots_for` is the one the
**CLI** uses, and it is the only place precedence and validation live.

`resolve_artifact_root` and `resolve_keep_audio` are **pure** (no filesystem, no `os.environ` read of their
own — the mapping is a parameter, following `config.resolve_proxy`'s signature). `roots_for` is the only
function that touches the filesystem, and only with `isdir`. `ArtifactRoots` is the single value the CLI
builds and every layer consumes; **no library module resolves configuration itself** — that is the "first-class"
part of D5/D15 restated as a layering rule (the shipped counter-example being `reclaim_audio` reading
`os.environ` inside the library, `audio_reclaim.py:44-47`).

**Layering.** The new module is a shared policy leaf like `path_policy.py` — consumed by `cli`, `audio`,
`coordinator`, `subtitles`, `campaign`, `audio_reclaim`, `coverage_report`, `integrity`, `export`, `quality`,
`search_index`. It imports only stdlib + `path_policy`. It does **not** import `manifest`, `storage`, or any
artifact writer, so the cross-layer rule (`{SPECS_DIR}/asr-archive-cli.md:61`, "`subtitles`/`audio`/`asr`/
`archive` never import each other; only `cli` composes") is not widened: `path_policy` is a shared leaf today,
imported by `audio` (`audio.py:28-33`), `coordinator` (`coordinator.py:32`), `coverage_report`
(`coverage_report.py:12`), `audio_reclaim` (`audio_reclaim.py:11`) and `cli` lazily inside its handlers
(`cli.py:1260`, `:1905`, `:2019`), and the new module takes its place in the same position.

## 4. Where the pipeline writes what

Every write resolves its base from `ArtifactRoots.write_base`; no write is ever split across both roots.

| Stage | Today | Under a configured root |
|---|---|---|
| `download-audio` | `out_path = os.path.join(args.archive_root, "audio", f"{stem}.m4a")` (`cli.py:1246-1248`, `:1253-1255`); root re-derived from `store.root`/the path (`audio.py:127-154`); re-confined against `args.archive_root` (`cli.py:1260-1272`) | the same three steps with the artifact root; `out_path = {artifact_root}/audio/{stem}.m4a`, `_archive_root_for_download(..., artifact_roots=...)` returns the artifact root and the unchanged `audio/<name>.<ext>` relative form, and the re-confinement uses the artifact root |
| `run`/`schedule`/`campaign` download stage | `RunCoordinator(args.archive_root, store, ...)` (`cli.py:2571`, `:2744`; `campaign.py:324`) → `out_path = os.path.join(self.root, "audio", ...)` (`coordinator.py:597`) → `download_audio(..., store=self.store)` (`:599-601`) → `_mark_audio_ok` writes `audio_path` relative to `store.root` (`audio.py:271-279`) | the coordinator gains the artifact root; `out_path` and the `_mark_audio_ok` base are the artifact root; `store.root` (state) is untouched |
| `run`/`schedule`/`campaign` ASR/archive stage | `write_archive(self.root, ...)` (`coordinator.py:542-545`), `archive_bundle_complete(self.root, paths)` (`:553`), `audio_rel = os.path.relpath(audio_path, self.root)` (`:566-570`) | the artifact root for all three; the recorded `audio_path` and bundle paths keep their exact strings |
| subtitle-archive stage | `_subtitle_segments` reads `{root}/subtitles/raw/{stem}.json` (`coordinator.py:396-413`) and `write_archive(self.root, ...)` (`:454-456`) | reads through the ordered bases (§5), writes to the artifact root |
| `asr` (in-process) | `write_archive(args.archive_root, ...)` (`cli.py:1915-1919`), `confined_audio_file(args.archive_root, declared)` (`:1911`), `declared = entry.get("audio_path") or os.path.join("audio", f"{stem}.m4a")` (`:1906`) | artifact root for the write, the descriptor open, and the default candidate; the `or` default string is already root-relative and does not change |
| `pilot` | `subtitles.harvest_subtitle(client, target, store, args.archive_root)` (`cli.py:2190-2191`), `_pilot_archive_subtitle(store, args.archive_root, ...)` (`:2196`), `_pilot_archive_asr(store, client, args.archive_root, ...)` (`:2225-2228`) with its `out_path` (`:2016`), download (`:2027`), `relative_to(Path(root).resolve())` (`:2029`), `confined_audio_path` (`:2032`), `relpath` (`:2036`) and `write_archive` (`:2046`) | the artifact root replaces the archive root at each of those points; `_subtitle_segments(root, ...)` (`cli.py:1754-1766`) becomes a two-base read |
| `harvest-subs` (SQLite path) | writes no filesystem projection at all (knowledge: `bilibili-asr-archive-cli.md`, projection/feeder boundary; the writer is `services/subtitle_ingest.py`) | **unchanged**, and therefore takes no new flag (§9) |
| `campaign` checkpoint / scheduler / run ledger | `{root}/campaign.json` (`campaign.py:117`), `{root}/scheduler.json`, `{root}/run-ledger.jsonl` | **unchanged** — state (D13) |

**Consequence to state plainly (D6 + this section):** with a root configured, artifacts written **before** the
switch stay at the archive root and artifacts written **after** it land at the artifact root. Nothing is
copied, moved or rewritten by the tool. The operator's own move (`mv archive/audio/* /mnt/123pan/audio/`, or
`rclone`) plus the configured root is the migration, and it breaks nothing: after the move the first base
resolves and the second is never consulted. Until the move, the second base resolves and the first
misses — which is exactly what keeps an existing archive working on day one (D6, D8).

## 5. How a recorded artifact path is resolved

**Decision (D7/D8):** a recorded value stays a **relative path under a root**; resolution walks
`roots.read_bases()` in order and returns the first hit, with **each candidate validated at its own base** by
that family's existing guard. There is no cross-root path arithmetic, and no absolute path is ever recorded.

```python
def resolve_audio_path(roots, declared, *, require_exists=True) -> Path | None:
    for base in roots.read_bases():
        confined = path_policy.confined_audio_path(base, declared, require_exists=require_exists)
        if confined is not None:
            return confined
    return None
```

Why this and not the alternatives:

- **Why the recorded value cannot become absolute.** `path_policy._audio_parts` (`:16-29`) refuses an absolute
  path, any `..` component, any first component other than `audio`, and any length other than 2; the same
  shape rule for bundles is `archive._component_names` (`:52-59`) + `_owned_bundle_parts` (`:155-168`). An
  absolute `audio_path` is therefore not merely unfashionable — it is **rejected by every audio reader today**
  (`confined_audio_path` returns `None`, `coordinator.py:428`, `coverage_report.py:458`, `cli.py:2021`).
  Keeping the value root-relative is what makes the manifest bytes a no-op for this feature.
- **Why two bases and not one.** A single-base reader would report every pre-existing artifact as missing the
  instant `BILI_ARTIFACT_ROOT` is exported: `coverage` would emit `artifact_present: false`
  (`coverage_report.py:446-468`), `verify` would raise defects and exit 1 (`integrity.py:262-288`,
  `cli.py:3108`), `export` would strip the path fields (`export.py:108-139`). D6 forbids that, and it would
  make the feature unusable on the archive it was built for.
- **Why not record the base durably** (the user's question, answered): nothing durable is written (D12). A
  sidecar or manifest field would be a second source of truth that goes stale the moment the operator moves
  files or runs once with a different root, and "trust the recorded base" resolution would then break exactly
  where the ordered probes keep working. Consequence, stated: **a later run with a different root neither
  rewrites nor invalidates earlier rows**, and the tool never discovers or remembers a previous root. The
  price is one extra probe per artifact read, on a path that already stats the file.
- **Refusal is not final; each base is judged independently.** If the artifact root holds
  `audio/x.m4a` as a symlink (refused there, `path_policy:105-106`) while the archive root holds a regular
  `audio/x.m4a`, the ordered probe returns the archive-root file. Nothing insecure follows — no symlink is
  followed and the returned path is validated against *its own* base — but the shadowing is disclosed here
  rather than discovered: a tampered entry in the configured root can be masked by a valid legacy copy. The
  alternative ("refusal at the configured root is final") was rejected because the audio guard is the only one
  of the two families that can distinguish refusal from absence (`path_policy:94-108` returns `None` for both
  under `require_exists=True`), so it would buy a narrow signal at the cost of two different resolution rules —
  see §13's risk row.

**Legacy case, spelled out (D6).** A row written before this iteration holds `audio_path: "audio/{stem}.m4a"`
and, when it was written, that string meant "under the archive root" — the writer stored
`os.path.relpath(final_path, store.root)` (`audio.py:271-279`) and every reader joined it with the archive root
(`coordinator.py:420`, `cli.py:2029`). **No reader is changed to stop doing that:** the archive root remains a
base, now the *second* one. An existing row therefore keeps resolving to its existing file with the archive
root configured and unconfigured alike, and a row written under a configured root resolves from the artifact
root while the second probe is never reached. Bundle paths (`srt_path`/`txt_path`/`md_path`/`raw_path`) and the
legacy bare-`bvid` `srt_path` from `subtitles.py:152` follow the identical rule.

**Per-family guards are not unified.** The audio family keeps the descriptor-anchored
`path_policy.confined_*` functions (`:78-139`); the transcript family keeps `archive._lexical_archive_root`
(`:264-275`) + `_open_declared` (`:138-152`) + `archive_bundle_complete` (`:170-206`); the reader-side
containment checks (`coverage_report._contained_path:471-478`, `integrity._safe_path:532-533`,
`quality._contained:392-396`, `export._safe_contained_relpath:108-139`) keep their own `resolve`-based
mechanisms, applied per base. Unifying them would be a rewrite of two security mechanisms in an iteration whose
contract says "re-base"; §6 states what each one still refuses.

## 6. The confinement guard, re-based (D4 — the security decision)

**What changes:** the root handed to each guard becomes the root the artifact is being read or written under.
`path_policy.py`, `archive._lexical_archive_root`, `_open_declared` and the readers' containment checks are all
already root-parameterized; only call sites change.

**What the guard refuses after this iteration that it allowed before** — nothing new becomes reachable, and
two things that were impossible become possible *by design*:

| | Today | After |
|---|---|---|
| an **absolute** artifact root distinct from the archive root | impossible to express (one root) | **allowed** (D1/D4) — that is the feature |
| an artifact root **inside** the archive root | impossible to express | **allowed** (§3.3) |
| a value with `..` after normalisation | n/a — `abspath` is applied at the root boundary (`archive.py:265`) | still impossible to *record* (`path_policy._audio_parts:23`, `archive._component_names:57`) |
| an `audio_path` that escapes the root it is validated against | refused (`path_policy:87-89`) | refused, now per base — `audio/../secret.m4a`, `/tmp/x.m4a`, `audio/x.wav`, `audio/sub/x.m4a` all still return `None` (`tests/test_persistence_scale.py:527-546` pins this) |
| a **symlinked root** | refused (ELOOP from `O_NOFOLLOW` on the root, `path_policy:38-40`, `archive.py:266-269`) | refused for **either** root — the configured root is not `resolve()`d (§3.2) |
| a **symlinked `audio/` directory** | refused (`path_policy:43-46`) | refused under either base |
| a **symlinked audio file** | refused at open (`path_policy:63-65`, `O_NOFOLLOW`; ELOOP → `ValueError` in `unlink_confined_audio:167-169`) and at stat (`:101-106`) | refused under either base |
| a **non-regular** entry (directory, fifo, device) | refused (`:68-69`, `:105-106`) | refused under either base |
| an audio file whose inode changed between validation and unlink | refused, quarantine + restore (`unlink_confined_audio:171-199`) | unchanged, applied per base |

**What it no longer refuses:** only "an artifact that lives outside the archive root". That was never a
security property — it was a consequence of there being one root — and the descriptor-anchored properties
(`O_NOFOLLOW` on every component, `dir_fd`-relative opens, `fstat` regular-file check, inode identity check
before unlink) are exactly the ones D4 requires to survive, and they do, because they are properties of how
the path is opened rather than of which root it sits under.

**Descriptor anchoring is what makes the mount safe.** Every audio read/write goes through an fd
(`audio.py:203-252`, `coordinator.py:528`, `cli.py:1911`, `:2041`), and every bundle publish through
`_open_transcript_dirs` + `dir_fd`-relative `os.replace` (`archive.py:72-88`, `:236-243`), so a symlink swapped
in mid-operation cannot redirect a write. That guarantee is untouched by a WebDAV/FUSE target — the mount
provides POSIX file semantics for these calls (it is the *locking* and *fsync* semantics it does not carry,
which is why state does not move: §2.2).

## 7. Retention (D5, D15)

- **Default flips to retain.** `reclaim_audio` is invoked only when the resolved policy says reclaim.
- **The flag:** `--keep-audio` / `--no-keep-audio` (`argparse.BooleanOptionalAction`, `default=None` so "unset"
  is representable) on the five commands that archive rows and therefore reclaim: `asr`, `pilot`, `run`,
  `schedule`, `campaign`.
- **Precedence:** flag wins; else `BILI_KEEP_AUDIO == "1"` → keep; `== "0"` → reclaim; anything else or absent
  → **default (keep)**. `audio_reclaim.py:46` (`os.environ.get("BILI_KEEP_AUDIO") == "1"`) is **removed**: the
  library receives `keep: bool` and never reads the environment (D15). Existing behaviour is preserved for
  both documented values — `=1` keeps and `=0` reclaims, as `tests/test_audio_retention_policy.py:31-33`,
  `:63-65`, `:93-95` assert today; only the *unset* case changes, which is the user-locked flip.
- **Where it takes effect:** `coordinator._reclaim_audio` (`:497-505`) and `cli._reclaim_after_archive`
  (`:1951-1958`) both call `reclaim_audio`. Each gains the resolved value; the best-effort
  `except (OSError, ValueError): pass` stays (a row is already `archived` when reclaim runs, `:487`).
- **What reclaim removes, when it is asked for:** the row's audio candidates under **both** bases, in order
  (`audio_reclaim._candidate_paths:20-37` is root-parameterized; the loop runs per base) — "do not keep this
  row's audio" means the copy, wherever it is.
- **The consequence of retention is a product question, not an engineering one — see Q1 (§12).**

## 8. Budget, peak and the writer lock (D14, D16)

- **The audio cap measures the configured root's `audio/`.** `audio_budget.audio_dir_usage_bytes` (`:32-45`) is
  already root-parameterized; callers pass the artifact root: `coordinator._note_audio_peak` (`:489-495`),
  `coordinator._stage_download` (`:586`), `cli._cmd_pilot` (`:2212-2214`), `cli._cmd_schedule` (`:2766`,
  `:2782`), `long_live.campaign_plan` (`:76-79`). Legacy audio still sitting at the archive root is **not**
  counted: it is on another device and it is not where new bytes land; summing two filesystems' usage is not a
  peak anyone can act on.
- **The writer lock stays archive-root-scoped.** `archive_writer` (`coordinator.py:72-95`) takes
  `{archive_root}/coordinator/archive-writer.lock`; `main()` takes it before dispatch (`cli.py:3261-3266`) and
  `CampaignRunner` takes it in-process (`campaign.py:279`). No second lock is added on the artifact root. The
  reason: the lock protects **state** — the manifest's read-modify-append and the SQLite writes — while artifact
  publication is per-stem, staged inside its own directory and atomically replaced (`audio.py:221-238`,
  `archive.py:228-243`), and the fixed staging name fails loudly rather than interleaving
  (`archive.py:229-230` raises `OSError("archive staging directory already exists")`). **Supported
  configuration: one artifact root per archive root for concurrent writers.** Two archive roots sharing one
  artifact root is outside this iteration's contract (non-goal) and is not detected — §13 carries it as a risk.

## 9. The operator surface (D18)

`--artifact-root <path>` (default `None`; help text names `BILI_ARTIFACT_ROOT` and states that the default is
the archive root) is added to the **eleven** commands that touch an artifact path:

| Command | Why it carries the flag |
|---|---|
| `asr` (`cli.py:103`) | reads audio, writes bundles, reclaims |
| `pilot` (`:122`) | harvest + download + ASR + archive, all four |
| `download-audio` (`:198`) | writes audio |
| `run` (`:251`), `schedule` (`:294`), `campaign` (`:335`) | the coordinator chain |
| `coverage` (`:388`, both modes: `--quality` is a flag on the same subparser, `:395-399`) | reads bundles, audio, transcript text |
| `verify` (`:413`), `recover` (`:424`) | `recover` calls `IntegrityVerifier().verify(root)` internally (`integrity.py:330`), so its defect selection depends on the artifact root |
| `export` (`:472`) | sanitises artifact path fields (`export.py:163-210`) and reads transcript text with `--with-text` |
| `search` (`:381`) | builds its index by reading transcripts from disk (`search_index.py:440-466`) |

It is **not** added to `fetch-meta` (`:69`), `status` (`:85`), `runs` (`:96`), `probe-subs` (`:149`),
`harvest-subs` (`:176`), `derive-manifest` (`:223`) — none of them resolves an artifact path (`status` reports
SQLite counts only, `_cmd_status:1331-1376`; `harvest-subs` writes no filesystem projection; `derive-manifest`
writes manifest rows). An accepted-but-ignored flag would be a false statement in the interface; the precedent
for scoping a flag to the commands that honour it is `--trusted-local` (`:395`, `:419`, `:429`).

`--keep-audio/--no-keep-audio` is added to `asr`, `pilot`, `run`, `schedule`, `campaign` only (§7).

**Resolution happens once, in `main()`, before the writer lock** (`cli.py:3255-3270`; resolution into
`args.artifact_roots` sits between `parse_args` and the `archive_writer` block):

- one place decides precedence and validity, so per-command drift is impossible;
- a doomed invocation does not create `{archive_root}/coordinator/` (the lock's documented side effect,
  `bilibili-asr-archive-cli.md:231-236`) before discovering it cannot proceed;
- the refusal cannot be swallowed by a command's broad `except Exception` (e.g. `_cmd_coverage:1636-1638`
  prints `coverage: diagnostic coverage_report_unavailable` for anything raised inside its try block) — the
  operator gets the real reason.

**Exact refusal lines (stderr, exit 1, no report body), pinned by test:**

```text
<command>: artifact root does not exist (<path>)
<command>: artifact root is not a directory (<path>)
```

Exit-code taxonomy is unchanged: these are usage/config errors, the frozen exit `1`
(`{SPECS_DIR}/asr-archive-cli.md:100`), the same class as `archive_busy` (`cli.py:3267-3269`). **No new exit
code** (D18).

## 10. The readers, one by one

| Reader | What it reads | What it must now do |
|---|---|---|
| `coverage` | bundles + audio via `_transcript_evidence(root, entry)` (`coverage_report.py:446-468`): `_contained_path` for the four bundle paths (`:471-478`), `archive_bundle_complete(root, ...)` (`:453`), `confined_audio_path(root, ...)` (`:458`, `:465`) | build with `artifact_roots=`; probe the bundle and audio candidates over `read_bases()` in order. The sidecars it also reads — manifest (`:66`), meta-cursor (`:77`), scheduler (`:80`), run-ledger (`:83`), attempts (`:95`) — stay at the archive root (state). **One command, two roots**, which is the cleanest demonstration of D1 |
| `coverage --quality` | `QualityAnalyzer.analyze(entry, root, reference)` (`cli.py:1464`) → `_artifact_paths(row, archive_root)` (`quality.py:339-390`) probing `transcripts/{srt,txt,md,raw}`, `subtitles/raw`, and `root/transcripts/md` globbing (`:369-380`), each behind `_contained` (`:392-396`) | `analyze(..., artifact_roots=...)`; the md glob and the inferred candidates probe both bases in order; the manifest/attempt projections stay at the archive root (`cli.py:1404-1417`) |
| `verify` | `_RootConfinedReader` rooted at `root` (`integrity.py:109-...`), manifest (`:206`) and attempts (`:209`, `:235`) — state; `_required_paths`/`_canonical_required_paths` (`:465-479`), `archive_bundle_complete(root, ...)` (`:280`), `subtitles/raw/{stem}.json` (`:282`), all behind `_safe_path` (`:532-533`) | `verify(..., artifact_roots=...)`: state reads unchanged; artifact reads probe both bases per path, each validated by `_safe_path` against its own base. `report.authoritative` stays a function of the **state** reads, so a missing artifact root is a *configuration* refusal (§9), not a non-authoritative report |
| `recover` | `IntegrityVerifier().verify(root)` (`integrity.py:330`) + the audit sidecar under `coordinator/` (`:349`) | passes the artifact root through to `verify`; its own writes stay state |
| `export` | `_safe_contained_relpath(root, value)` (`export.py:108-139`) for the five path fields (`:31`, `:187`, `:195`), `extract_transcript_text(root, entry)` with `--with-text` (`:205`) | the containment base for the **artifact** fields becomes the artifact root (the path fields are written by the artifact writers); a value that resolves under only the archive root still exports as a normalized relative path instead of being stripped to `""` |
| `search` | the module entry point `search(archive_root, query)` (`search_index.py:823-835`, index built at `:833`) → `SearchIndex(root)` (`:352-355`) — `self.root` serves both `search.db` (state) and the on-disk transcript probes (`:440-463`), plus `extract_transcript_text` (`:138-235`, including the `subtitles/raw` fallback `:212`) | `search(..., artifact_roots=...)`; the class holds both roots: `search.db` stays at the archive root, transcript probes walk both bases in order |
| legacy-row migration probe | `manifest._foreign_page_stems(root, bvid)` (`manifest.py:418-437`) over `_ARTIFACT_REL_DIRS` (`:408-415`: `audio`, `subtitles/raw`, `transcripts/{srt,txt,md,raw}`), reached from `migrate_legacy_rows` (`:332-405`) which `subtitles.harvest_subtitle` calls (`subtitles.py:101-105`) | scan **both** bases (a foreign page stem in either root means the bare-`bvid` row is ambiguous and must stay frozen, `:387-401`); the parameter is renamed `artifact_root` because it is now the *additional* base, with `self.root` = the archive root still scanned |
| `status` | SQLite only (`cli.py:1331-1376`) | **unchanged.** The compass's verification sketch lists `status` among the readers that must report the same inventory; it reads no artifact path at all, so it has nothing to re-base and carries no flag (§15, correction 3) |

## 11. Interfaces

**Consumes**

| Input | Contract |
|---|---|
| `path_policy.confined_audio_path` / `confined_audio_file` / `unlink_confined_audio` / `open_audio_directory` (`path_policy.py:32-201`) | unchanged, root-parameterized; the resolver in §3.4 wraps `confined_audio_path` only |
| `archive._lexical_archive_root` / `_open_transcript_dirs` / `archive_bundle_complete` / `write_archive` (`archive.py:72-88`, `:170-206`, `:264-275`, `:452-488`) | unchanged; `write_archive(root=artifact_root, ...)` returns the same relative strings (`:488`) |
| `ManifestStore(root=archive_root)` (`manifest.py:101-107`), `load()`/`upsert()` | unchanged; **state only** |
| the shipped audio/bundle writers' create-on-demand behaviour (`path_policy:47-55`, `archive.py:66-69`, `subtitles.py:139-140`) | unchanged; applied inside the artifact root |

**Produces**

| Output | Contract |
|---|---|
| `src/bili_asr/artifact_root.py` | `ArtifactRootError`, `ArtifactRoots`, `resolve_artifact_root`, `resolve_keep_audio`, `roots_for`, `resolve_audio_path`, `ARTIFACT_ROOT_ENV_VAR`, `KEEP_AUDIO_ENV_VAR`, `KEEP_AUDIO_DEFAULT` (§3.4, verbatim) |
| `cli.py` | `--artifact-root` on the eleven commands, `--keep-audio/--no-keep-audio` on the five; one resolution in `main()` into `args.artifact_roots`; the two refusal lines; `args.keep_audio` resolved once into the same namespace |
| every library entry point that needs a root | one **keyword-only** parameter of the same type, defaulted to the identity case (`artifact_roots=None` → `ArtifactRoots.of(archive_root)`): `audio.download_audio`, `coordinator.RunCoordinator`, `subtitles.harvest_subtitle`, `campaign.CampaignRunner`, `audio_reclaim.reclaim_audio` (`keep` is keyword-only and **required**), `coverage_report.CoverageReport.build`, `integrity.IntegrityVerifier.verify`/`recover`, `export.export_manifest`, `quality.QualityAnalyzer.analyze`, `search_index.SearchIndex`/`search`/`extract_transcript_text`, `manifest.ManifestStore.migrate_legacy_rows` |

**Why the keyword default exists, and what it costs (disclosed).** The default keeps every layer independently
testable and lets the plan land in reviewable slices: `cli.py` is one file and belongs to one task, so the
library changes precede the wiring. The cost is a library caller that omits the parameter silently writing to
the archive root. The mitigations are that the parameter is keyword-only, that the identity default is
asserted equal to today's layout by test, and that the CLI — the only product caller — always passes an
explicit `ArtifactRoots` (the plan's final task proves it by moving files, not by reading source).

## 12. Deferred, the revision the frozen spec is owed, and the open question

| Item | Where it is tracked |
|---|---|
| **D19 — `{SPECS_DIR}/asr-archive-cli.md` revision (PM-owned; not edited here)**: (a) the frozen CLI surface (`:30-40`) gains `--artifact-root` on the eleven commands and the retention flag on five; (b) the Outputs block (`:124-133`) says `audio/{bvid}.m4a # optional retain; cleanup flag is next-iteration scope` — after D5 audio is **retained by default** and the *cleanup* is the opt-in, and the whole product tree may live under a configured artifact root; (c) the module-boundary block (`:46-62`) gains the `artifact_root.py` leaf beside `path_policy.py`. Exit taxonomy (`:97-101`) needs **no** change | §12, plan Task 4 records it in `README.md`/`docs`; the spec edit and its sign-off are the PM's (`{SPECS_DIR}/asr-archive-cli.md:6`) |
| A cosmetic rename of anything else the name `archive_root` mis-describes (e.g. `long_live.campaign_plan`'s first parameter, which now receives the artifact root) | Not worth a cross-task edit this iteration; recorded here so it is a decision, not an oversight |
| Any **state** relocation, cloud publication/sync, second writer lock, or multi-archive-shared-artifact-root support | Compass `## Non-Goals`; §8 states the supported configuration |
| A migration/copy tool for moving legacy artifacts to a new root | D6 — the operator's `mv`/`rclone` plus the configured root is the migration (§4); the tool never copies between roots |
| The SRT/TXT/MD projection rebuild, SQLite audio-evidence widening, and the other queue-bridge deferrals | Unchanged, tracked by `iter-2026-09-queue-bridge` (`queue-derivation-bridge.md`); untouched here |

**Q1 — open question for the user (product-level, escalated, not decided here).**

*The retained-audio default and the shipped `--max-audio-gb 10.0` cap are in tension.* The cap defaults to
10.0 GiB on `pilot`, `run`, `schedule` and `campaign` (`cli.py:124`, `:247`, `:281`, `:329`) and fail-closes:
`would_exceed_budget` (`audio_budget.py:72-90`) returns `True` when `usage + estimate > cap`, so the download
stage skips the row with `audio_budget` (`coordinator.py:583-594`) and `pilot` counts it as a failure
(`cli.py:2210-2222`). With D5's retain-by-default, audio accumulates indefinitely, so a full-corpus run
**stops downloading once the artifact root's `audio/` passes the cap**, and every later row is reported as a
budget skip — a behaviour the operator will read as a failure, not as "your disk is full of the thing you asked
to keep".

- **(a) Recommended — keep the cap's semantics and make the interaction explicit.** `--max-audio-gb 0`
  (unlimited) remains the documented way to retain and keep downloading; the flag help for the four commands
  names the retention interaction, and the skip line says the cap was reached. Cost: an operator who retains
  must read one line of help, or set one flag. No shipped default changes.
- **(b) Change the default to 0 (unlimited) when retention is on.** Removes the trap for an inattentive
  operator, and removes the only guard against filling the artifact device on a first unbounded corpus run.
- **(c) Stop counting retained audio toward the cap.** Makes the cap meaningless — it exists to bound the disk
  the downloads land on (`audio_budget.py:1-6`).

Everything else the Assignment asked this pass to converge is decided above (D7–D18) and needs no ruling.

## 13. Risks and rollback

| Risk | Mitigation / proof |
|---|---|
| A reader resolves a legacy path against only one base and reports a live archive as broken | §5's ordered probe, proven by the plan's readers task: an archive whose artifacts are at the archive root reports identically with and without a configured root |
| `audio_path` is written with a `..`-laden or absolute value, so every reader rejects the row silently (the failure mode found in `audio.py:271-279`: `os.path.relpath` against `store.root` with the artifact outside it yields `../../…`, `confined_audio_path` returns `None`, and `_mark_audio_ok` returns **without upserting** — the row never reaches `audio_ok`) | §4's write map re-bases the relpath at every site; the plan's write task asserts the stored value is exactly `audio/{stem}.m4a` for a root outside the archive root |
| The refusals are swallowed by a command's broad `except Exception` | §9: resolution happens in `main()` before dispatch; the plan's CLI task asserts each refusal line directly |
| A shadowed tampered artifact (symlink at the configured root, valid legacy copy at the archive root) reads as present | §5's disclosure; accepted, with the reason the alternative rule was rejected. No symlink is followed either way |
| Two archive roots sharing one artifact root interleave | §8: unsupported and undetected; the fixed staging directory name fails loudly (`archive.py:229-230`) rather than corrupting, and per-stem names collide only if both archives hold the same bvid |
| The retention flip silently changes an operator's disk use | §7: `=1` and `=0` keep their meanings; only the unset case flips (user-locked D5), and it is documented in `README.md` + `docs/audio-retention-policy.md` by the plan's final task |
| A configured-but-unmounted root silently writes to the underlying filesystem | §3.3: a non-existent root is refused; the unmounted-mount-point case (the directory exists, the mount does not) is **not** detectable by the pipeline and is stated as an operator responsibility in the docs |

**Rollback.** Unset the flag and the variable: `--artifact-root` absent and `BILI_ARTIFACT_ROOT` absent means
one base — the archive root — and every path is today's. Files written under a configured root are found again
the moment the same root is configured (their recorded paths are root-relative and unchanged, §5), so nothing
has to be moved back. No schema change, no migration step, no new dependency, no state written to the new
root. The only irreversible part is D5's deletion behaviour: audio already reclaimed by earlier runs (or by an
explicit `--no-keep-audio`) cannot be restored.

## 14. Validation plan — how the compass criteria become checkable

| Compass criterion | What makes it checkable, from this contract |
|---|---|
| Unset root → byte-identical behaviour to today (compass §4) | §3.2's identity resolution + the existing suites as the regression evidence; the plan runs the shipped audio/coordinator/coverage/verify/export suites unmodified as part of each task's selectors |
| Configured root → audio and bundles land there; `coverage`, `verify`, `export`, `coverage --quality` report the same inventory | §4's write map (a fixture run with the root outside the archive root produces the file there and the *same* recorded `audio_path`/bundle strings) + §10's reader table (the same fixture reports the same inventory with and without the root configured) |
| The confinement guard still refuses an out-of-root path for the configured root, and a symlinked target directory | §6's table; the plan's core task re-runs the shipped confinement cases (`tests/test_persistence_scale.py:527-556`) against a configured root and adds the two-base cases |
| Retention: with the retain policy, a row reaching `archived` leaves its audio in place | §7; the plan's write task asserts `archived` ⇒ the audio file still exists with retention on, and is removed with `--no-keep-audio` |
| (added by this contract) A configured but unusable root never masquerades as an empty archive | §3.3 + §9: the two refusal lines, asserted per flag-carrying command |

## 15. Corrections to the recon (2026-09-19)

The compass's and the Assignment's line numbers were re-checked against `HEAD 5961800`. Two were wrong, and
three claims are narrower than stated. Everything else held.

1. **`config.py:123-141` "`resolve_credential`-style precedence"** — there is no `resolve_credential`. The
   precedence idiom is `resolve_sessdata` (`config.py:128-141`, called at `:122-124`) and, closer to a path,
   `resolve_proxy` (`:154-175`). §3.2 follows `resolve_proxy`'s blank-falls-through rule and says why.
2. **`database.py:187` "opened below the root"** — `:183-193` is the tail of `require_subtitle_schema`
   (`SchemaContractError` at `:187`); `archive.db` is opened by `open_database` at **`database.py:196`**. The
   name constant `_ARCHIVE_DATABASE_NAME = "archive.db"` is at `:40` as the recon said.
3. **`status` is not a manifest-shaped reader** for this feature: `_cmd_status` (`cli.py:1331-1376`) reads
   `archive.db` only and touches no artifact path, so it is unchanged and carries no flag (§10).
4. **`cli.py` line numbers drifted**: the download-audio audio paths are `:1246-1248`/`:1253-1255` and the
   re-confinement `:1260-1272` (not `:1123`/`:1130`/`:1136-1143`); `_subtitle_segments` is `:1754-1766` (not
   `:1782`); the `asr` audio open is `:1905-1911` and the archive write `:1915-1919` (not `:1895-1908`);
   `_ARCHIVE_WRITER_COMMANDS` is `:3199-3210`; `main()`'s lock block is `:3261-3269`.
5. **The harvested-subtitle product tree is two directories, not one**: `harvest_subtitle` writes
   `{root}/subtitles/raw/{stem}.json` **and** `{root}/transcripts/srt/{stem}.srt` (`subtitles.py:23-24`,
   `:136-147`) and records only the SRT path (`:152`). Both are products of D1's artifact root, and the second
   one shares a directory with the ASR bundle output.
6. **The reader blast radius is wider than the four readers the compass names.** `search`
   (`search_index.py:440-466`), `recover` (through its internal `verify`, `integrity.py:330`),
   `coverage --quality`'s on-disk md glob (`quality.py:369-380`) and the legacy-row migration probe
   (`manifest._foreign_page_stems`, `manifest.py:418-437`) all resolve artifact paths and are enumerated in
   §10.
7. **The failure mode of an artifact outside the archive root is silent, not an exception.** `coordinator.py:566-568`
   raises `OSError("audio path outside archive")` only when `os.path.relpath` raises `ValueError` — i.e. on
   Windows across drives. On POSIX the relpath succeeds with `..` components, which `_audio_parts`
   (`path_policy.py:23`) rejects on the next read, so the symptom is a row that silently never reaches
   `audio_ok` (`audio.py:276-280` returns before `upsert`) plus `missing_audio` skips later. §13 carries this as
   the write-path risk the plan asserts against.

## Recall receipt (Prepare input, per `mstar-phase-gates` §A)

**Read and reused**

- `.mstar/knowledge/architecture-patterns/bilibili-asr-archive-cli.md` — the projection/feeder boundary (why
  `harvest-subs` needs no flag), the writer-lock ordering (why the lock stays archive-root-scoped), the exit
  taxonomy.
- `.mstar/knowledge/architecture-patterns/operational-sidecars.md` — the durable append/projection and
  single-writer boundaries: the reason §2 splits products from the manifest's fsync-per-append ledger.
- `.mstar/knowledge/architecture-patterns/queue-derivation-bridge.md` — the one-way bridge and the
  `missing_subtitle_raw` filesystem trap: the reason §10 treats the subtitle/transcript reads as artifact
  reads rather than store reads.
- `.mstar/knowledge/testing-patterns/worktree-test-invocation.md` — the pinned invocation every task's
  verification command uses (`PYTHONPATH=$PWD/src` + the resolved-`bili_asr.__file__` probe).
- `{SPECS_DIR}/asr-archive-cli.md` — the frozen interface rows §12 owes a revision against, honoured verbatim
  here (no new exit code, no edit).
- `.mstar/knowledge/best-practices/claim-scope-discipline.md` — the reason §4, §5 and §13 state the
  consequences (legacy split across two roots, shadowing, the cap interaction) as part of the claim.

**Read and rejected**

- "One root, absolute paths recorded" — rejected: absolute and `..`-bearing values are refused by the audio
  guard (`path_policy.py:21-29`) and by the bundle shape rule (`archive.py:52-59`, `:155-168`), so it would be
  a manifest schema change plus a migration, i.e. D6 and the non-goals.
- "Record the artifact root durably (sidecar or manifest field)" — rejected in §5 (stale second source of
  truth; ordered probes already answer the question).
- "Auto-create a missing artifact root" — rejected in §3.3 (unmounted mount point).
- "Refuse an artifact root inside the archive root" — rejected in §3.3 (harmless layout; the check would only
  forbid).
- "Refusal at the configured root is final (no fall-through)" — rejected in §5 (one two-valued family vs one
  three-valued family; two rules for one concept).
- "Add a second writer lock on the artifact root" — rejected in §8/§14 (the lock protects state; publication is
  staged per stem).
- "Relocate state too" — rejected by D1 and §2.2 (SQLite locking and the manifest fsync pair on FUSE).
