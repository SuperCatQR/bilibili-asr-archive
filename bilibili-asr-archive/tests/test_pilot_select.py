from bili_asr.cli import _pilot_select


def test_pilot_select_includes_both_branches_and_short_items():
    entries = {
        "sub": {"bvid": "sub", "status": "subtitle_done", "duration_s": 10},
        "aud": {"bvid": "aud", "status": "needs_audio", "duration_s": 20},
        "other": {"bvid": "other", "status": "meta_ok", "duration_s": 1},
    }
    selected = _pilot_select(entries, 2)
    assert {e["bvid"] for e in selected} == {"sub", "aud"}
