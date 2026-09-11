## Task 1: Risk classification and resumable CLI handling

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/bili_client.py`
- Modify: `bilibili-asr-archive/src/bili_asr/cli.py`
- Modify: `bilibili-asr-archive/tests/test_fetch_meta.py`
- Modify: `bilibili-asr-archive/tests/test_subtitles.py` if API-error row coverage belongs there
- Modify: `bilibili-asr-archive/tests/test_audio.py` if API-error row coverage belongs there

**Interfaces:**
- Preserve `classify_risk(status: int, body: dict[str, Any] | None) -> str`.
- Add `RISK_API_ERROR` and `APIResponseError(code: int | str)`.
- Preserve all existing public `BiliClient` methods and `ManifestStore` methods.

- [ ] Add failing classification tests for `-101`, `-400`, `-403`, and an unknown negative code; retain gone assertions for HTTP 404, `-404`, and `-62002`.
- [ ] Add a failing CLI test proving a non-gone API error does not write `status=gone`, preserves the row's previous status, records `last_api_error_code`, and returns 1 when mixed with a successful item.
- [ ] Implement the new classification and exception path in both `_request` and `_request_with_cookies`.
- [ ] Catch `APIResponseError` in fetch, subtitle, and audio CLI loops; keep rows resumable and correct the mixed-failure return conditions without echoing secrets.

Run: `python -m pytest bilibili-asr-archive/tests/test_fetch_meta.py bilibili-asr-archive/tests/test_subtitles.py bilibili-asr-archive/tests/test_audio.py -q` -> exit 0; no non-gone row is marked `gone`.

