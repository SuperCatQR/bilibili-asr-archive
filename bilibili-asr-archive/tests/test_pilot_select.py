from bili_asr.cli import _expand_selected_pages, _pilot_select


def test_pilot_select_includes_both_branches_and_short_items():
    entries = {
        "sub": {"bvid": "sub", "status": "subtitle_done", "duration_s": 10},
        "aud": {"bvid": "aud", "status": "needs_audio", "duration_s": 20},
        "other": {"bvid": "other", "status": "meta_ok", "duration_s": 1},
    }
    selected = _pilot_select(entries, 2)
    assert {e["bvid"] for e in selected} == {"sub", "aud"}


def test_pilot_select_from_meta_ok_prefers_short_items():
    entries = {
        "long": {"bvid": "long", "work_id": "long:p0", "status": "meta_ok", "duration_s": 90},
        "short": {"bvid": "short", "work_id": "short:p0", "status": "meta_ok", "duration_s": 3},
        "mid": {"bvid": "mid", "work_id": "mid:p0", "status": "meta_ok", "duration_s": 12},
        "gone": {"bvid": "gone", "work_id": "gone:p0", "status": "gone", "duration_s": 1},
    }
    selected = _pilot_select(entries, 2)
    assert [e["bvid"] for e in selected] == ["short", "mid"]


def test_expand_selected_pages_includes_sibling_work_ids():
    entries = {
        "BV1m:p0": {
            "bvid": "BV1m", "work_id": "BV1m:p0", "status": "meta_ok",
            "duration_s": 4, "page_index": 0,
        },
        "BV1m:p1": {
            "bvid": "BV1m", "work_id": "BV1m:p1", "status": "meta_ok",
            "duration_s": 40, "page_index": 1,
        },
        "other:p0": {
            "bvid": "other", "work_id": "other:p0", "status": "meta_ok",
            "duration_s": 5,
        },
    }
    selected = _pilot_select(entries, 1)
    assert [e["work_id"] for e in selected] == ["BV1m:p0"]
    expanded = _expand_selected_pages(entries, selected)
    assert {e["work_id"] for e in expanded} == {"BV1m:p0", "BV1m:p1"}
