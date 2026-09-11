# Task 2 L2 review — Pin idempotent reruns and dependency errors

Review range: `8de38460fc58294e12fc97c2ef318965d7875b67..301c48e0bae68213e164defa84aa42b6269d694b`
Diff file: `review/task-2.diff`
Working branch: `plan/20260825-executable-pilot-workflow`

### Spec Compliance

- ✅ Spec compliant for Task 2 pins: completed mixed rerun is a no-op on artifacts/JSONL; missing `ASRDependencyError` is nonzero, prints the install hint, does not mark the audio row `archived`; subtitle path still never reaches `transcribe` (existing mixed test + ASR fail after subtitle archive).
- `_pilot_select` / `_expand_selected_pages` still only take `_PILOT_PROCESSABLE` (`meta_ok`, `subtitle_done`, `needs_audio`, `audio_ok`). After a finished mixed run, `selected` is empty, so the new empty-selection skip is the path that implements idempotency. That matches Global Constraints (no schema change, last-write-wins unused on rerun).
- ⚠️ Cannot verify from diff: README “rerun / optional-ASR failure” (not in this diff; implementer points at Task 1). ⚠️ Cannot verify from diff: `git status --short` in-scope only. ⚠️ Cannot verify from diff: implementer pytest (`8 passed` / `175 passed` on `301c48e`); PM already recorded 175 passed — do not re-run here.

### Strengths

- Rerun test is behavioral, not mock-count only: byte-equal `manifest.jsonl`, same on-disk file set, ASR call list unchanged.
- Missing-ASR test keeps the mixed fixture, archives the subtitle row, asserts audio row `status != archived` and no `srt_path`, and requires the exact `pip install -e "bilibili-asr-archive/[asr]"` string on stderr.
- `ASRDependencyError` now prints branch counts before `return 1`, so the operator still sees `subtitle=` / `audio-asr=` when the run aborts mid-loop.
- Lazy `from . import asr` inside `_cmd_pilot` / `_pilot_archive_asr` is unchanged; FunASR is not imported at module load.

### Issues

#### Critical

None.

#### Important

None.

#### Minor

- Empty-selection skip is `any(status == "archived")` over the whole manifest, not “the N selected work_ids are archived.” A store with one leftover `archived` row plus only `gone`/excluded leftovers will exit 0 with “all selected work already archived” instead of “no processable rows.” Task 2’s completed mixed rerun is still correct.
- Loop `if status == "archived": continue` is unreachable with the current selector (`archived` is not processable). Harmless; the implementer report overstates it as the skip mechanism.
- `ASRDependencyError` still runs after `download_audio`, so a failed ASR row can sit at `audio_ok` with an m4a on disk. Spec only forbids `archived`; worth knowing for resume, not a Task 2 miss.

### Assessment

**Task quality:** Approved
