## Task 2: WBI/SESSDATA playurl contract and quality semantics

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/bili_client.py`
- Modify: `bilibili-asr-archive/src/bili_asr/audio.py`
- Modify: `bilibili-asr-archive/tests/test_audio.py`
- Modify: `bilibili-asr-archive/tests/test_subtitles.py` only if shared WBI/cookie assertions need a focused extension

**Interfaces:**
- Preserve `BiliClient.fetch_playurl_audio(bvid: str) -> list[dict[str, Any]]`.
- Preserve `audio.download_audio(...) -> str`.
- Preserve `sign_wbi(params, img_key, sub_key, wts=None) -> dict[str, Any]`.

- [ ] Add a failing transport test asserting `/x/player/wbi/playurl`, signed `wts`/`w_rid`, required bvid/cid/fnval/qn parameters, and SESSDATA cookie forwarding.
- [ ] Add failing quality tests proving 30232 means 132K and does not trigger FLAC fallback/remux by ID; use explicit FLAC URL/MIME for any FLAC fallback test.
- [ ] Implement the WBI-signed playurl request using `_wbi_keys()` and the configured cookie channel.
- [ ] Correct audio comments and container detection to use URL/MIME evidence rather than the 30232 ID.

Run: `python -m pytest bilibili-asr-archive/tests -q` -> exit 0 with no live HTTP or model downloads.

## Out of Scope

- Multi-part media identity and all-page enumeration (audit plan 001).
- Metadata pagination cursor persistence (audit plan 002).
- Pilot execution (audit plan 003), full entrypoint integration coverage (audit plan 004), search, diarization, model changes, dependency locking, and CI.
- Live Bilibili requests, credential acquisition, ffmpeg execution, or model downloads.

## STOP Conditions

- If the frozen spec and local API reference disagree on gone codes, stop before changing classification.
- If WBI keys cannot be obtained from the existing `nav` response seam, stop instead of adding hardcoded keys or unsigned fallback.
- If preserving old manifest rows requires a schema migration beyond an additive `last_api_error_code` field, stop and revise this plan before implementation.
- If an existing test contradicts the locked quality mapping, update the test only after confirming the local reference and record the contradiction in the implementation report.

## Drift Check

Before execution run:

`git diff --stat ab3cd97..HEAD -- bilibili-asr-archive/src/bili_asr/bili_client.py bilibili-asr-archive/src/bili_asr/cli.py bilibili-asr-archive/src/bili_asr/audio.py bilibili-asr-archive/tests bilibili-asr-archive/README.md .mstar/specs/asr-archive-cli.md`

If any listed file changed, compare the current risk constants, exception paths, playurl URL, WBI helper, cookie plumbing, and audio quality comments with this plan before editing.

## Done Criteria

- [ ] Only frozen gone codes classify as `RISK_GONE`; auth/request/unknown codes use `RISK_API_ERROR`.
- [ ] Non-gone API errors remain resumable, retain the prior status, record `last_api_error_code`, and never write `gone`.
- [ ] Mixed-success subtitle/audio batches return 1 when any per-video item fails.
- [ ] Playurl requests use the WBI endpoint, signature, and SESSDATA cookie channel without leaking values.
- [ ] Tests encode 30232=132K and prove it is not treated as FLAC.
- [ ] `python -m pytest bilibili-asr-archive/tests -q` exits 0.
- [ ] `git diff --check` exits 0.
- [ ] `git status --short` shows only in-scope implementation/test files plus this plan artifact.

## Handoff

Implement Task 1 with a fresh SDD implementer and task review, then Task 2 with a fresh implementer and task review. After both tasks, run plan-level QC and QA before merging the feature branch into the project integration branch. No Pull Request is to be created.
