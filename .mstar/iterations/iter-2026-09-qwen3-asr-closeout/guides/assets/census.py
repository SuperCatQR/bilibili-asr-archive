#!/usr/bin/env python3
"""T5 census — per-term recoveries, insertions, fabrications, unresolved.

SSOT for the rules this implements: {ITERATION_DIR}/iter-2026-09-qwen3-asr-closeout/
guides/t5-hotword-measurement-protocol.md §5-§7.  This script computes; it does not
redefine a threshold, and every number it prints is one of the pre-declared ones.

Reads the three arm roots, the caption route, and writes CENSUS.md + census.json.
Never writes into an arm root and never touches the audio.

    python3 census.py <ab-root> [--out <dir>]
"""

from __future__ import annotations

import difflib
import json
import pathlib
import re
import sys
from collections import defaultdict

# The 33 shipped terms, in the literal's order (asr.py:100-164).  Kept in step with the
# protocol's §2 arm table by hand: the census must count the terms the arms actually read
# back, and Amendment 1 is why this list is 33 and not the 26 the Qwen3 rewrite left behind.
TERMS = [
    "未明子", "主义主义", "拟态论", "国际劳工仲裁", "国际劳联", "马恩牌", "攻势", "智利",
    "根正苗红", "亚美利坚", "黑格尔", "海德格尔", "拉康", "齐泽克", "德勒兹", "康德",
    "观念论", "本体论", "现象学", "辩证法", "定在", "自为", "理念性",
    "扬弃", "自在", "变易", "此在", "感性", "实存",
    "International Employment Matters Tribunal", "International", "Employment", "Tribunal",
]

ITEMS = [
    ("BV1iddQYQE7D", 7682),
    ("BV1BdtazGEBE", 6395),
    ("BV1vNTqzFEve", 5112),
    ("BV1Y7M4zNEfF", 2598),
    ("BV11p5qzAE6s", 2408),
    ("BV1zz5zzFENq", 2087),
]
# NOISE_ITEM is the corpus's own longest item; on the short corpus arm R covers
# every item, so the noise floor is computed over the whole set.  The two are
# distinguished by whether arm R holds more than one item, not by a second list
# that can fall out of step with what the arms actually ran.
NOISE_ITEM = "BV1iddQYQE7D"
SHORT_ITEMS = [
    ("BV1aRTA6mEGF", 571),
    ("BV132XgBjER4", 500),
    ("BV1wLTP6NE9h", 449),
]
ROUTE_DIR = pathlib.Path("/mnt/123pan/bili-asr-e2e/proofread-transcripts/align")
# The short corpus has no proofread route: /mnt/123pan/.../align holds the six
# long items and nothing else (checked 2026-09-26).  What it does have is
# machine captions, fetched per item by the API, which is the *same* leg the
# route's `kept` field carries — the caption text over a span.  A route record
# additionally carries `hotwords_asr`/`hotwords_ai` and a proofread decision,
# so a caption-only reading is weaker and must not be mixed silently into a
# route-backed one: `source` says which basis every span used, and the report
# counts them separately.
# Captions live beside the corpus they belong to.  Several dirs are searched so
# the census can serve any corpus without editing a constant per run; the first
# hit wins, and `load_route` records which basis each span used either way.
CAPTION_DIRS = [
    # The long corpus's caption side, fetched from the API after the proofread route on
    # 123pan became unreadable (401 on every read, register R3).  Listed first because it
    # is the corpus whose route is missing.
    pathlib.Path("/root/e2e-asr/ab-hotwords-qwen3/captions"),
    pathlib.Path("/root/e2e-asr/ab-short2/captions"),
    pathlib.Path("/root/e2e-asr/ab-short/captions"),
]

SRT_CUE = re.compile(r"(\d\d:\d\d:\d\d,\d+) --> (\d\d:\d\d:\d\d,\d+)")


def ratio(a: str, b: str) -> float:
    """The knowledge note's fixed basis: autojunk off, because the default scores differently."""
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _duration_from_artifacts(arms: dict, bvid: str) -> int:
    """The duration as the arms themselves recorded it, for an undeclared item."""
    for name in ("with", "without", "repeat"):
        for md in (arms[name] / "transcripts" / "md").glob(f"*_{bvid}.p0_*.md"):
            for line in md.read_text(encoding="utf-8").split("---")[1].strip().splitlines():
                if line.startswith("duration_s: "):
                    try:
                        return int(json.loads(line.split(": ", 1)[1]))
                    except Exception:
                        pass
    return 0


def read_txt(root: pathlib.Path, bvid: str) -> str | None:
    path = root / "transcripts" / "txt" / f"{bvid}.p0.txt"
    return path.read_text(encoding="utf-8") if path.exists() else None


def read_cues(root: pathlib.Path, bvid: str) -> dict[tuple[str, str], str]:
    """Cues keyed by their srt timestamp span — the protocol's shared-bucket key."""
    path = root / "transcripts" / "srt" / f"{bvid}.p0.srt"
    if not path.exists():
        return {}
    cues: dict[tuple[str, str], str] = {}
    blocks = path.read_text(encoding="utf-8").split("\n\n")
    for block in blocks:
        match = SRT_CUE.search(block)
        if not match:
            continue
        text = block[match.end():].strip()
        cues[(match.group(1), match.group(2))] = text
    return cues


def load_route(bvid: str) -> tuple[list[dict], str]:
    """The reading basis for one item, and which basis it is.

    A proofread route is preferred when it exists.  Otherwise a machine caption
    file is used, and the caller is told so: the two are not interchangeable.

    Both probes tolerate OSError.  The route directory lives on an rclone fuse
    mount that answers a miss with EIO rather than ENOENT, so an item the route
    does not cover raises instead of simply not being there — and that is a
    normal state for the short corpus, not a failure.
    """
    path = ROUTE_DIR / f"{bvid}.p0.alignment.jsonl"
    try:
        if path.exists():
            return ([json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()],
                    "proofread-route")
    except OSError:
        pass
    for cap_dir in CAPTION_DIRS:
        cap = cap_dir / f"{bvid}.p0.caption.jsonl"
        try:
            if cap.exists():
                return ([json.loads(line) for line in cap.read_text(encoding="utf-8").splitlines() if line.strip()],
                        "caption-only")
        except OSError:
            continue
    return [], "none"


def route_over(route: list[dict], start: float, end: float) -> list[dict]:
    """Route records overlapping a cue's span; the caption leg reads only these."""
    return [r for r in route if float(r["start"]) < end and float(r["end"]) > start]


def srt_seconds(stamp: str) -> float:
    hh, mm, rest = stamp.split(":")
    ss, ms = rest.split(",")
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000


def arm_b_text_over(cues_b, start: float, end: float) -> tuple[str, bool]:
    """Arm B's text over a time interval, by **overlap** rather than by key equality.

    Returns (text, exact_key_hit).

    Why not `cues_b[(start_stamp, end_stamp)]`: the two arms segment independently,
    so the same speech lands in buckets whose boundaries differ by a few hundred
    milliseconds.  An exact-key lookup therefore misses a span arm B *does* carry,
    reads B as empty, and classifies every inherited occurrence as a recovery —
    inflating `R`, the one number this census exists to produce.  Measured on
    `BV1wLTP6NE9h` 2026-09-26: arm A's cue `00:01:09,680`–`00:01:24,160` vs arm B's
    `00:01:09,840`–`00:01:24,160` over the same speech, which made 4 of
    `国际劳工仲裁`'s 4 occurrences read as recoveries when arm B carries all 4.

    The protocol's `shared bucket` figure (§7) is still keyed by exact timestamps,
    because that number is *about* segmentation agreement; this comparison is about
    which words each arm rendered, where any temporal overlap is the right basis.
    """
    parts = []
    exact = False
    for (b_start, b_end), text in cues_b.items():
        bs, be = srt_seconds(b_start), srt_seconds(b_end)
        if bs < end and be > start:
            parts.append((bs, text))
            if (b_start, b_end) == (_fmt_key(start), _fmt_key(end)):
                exact = True
    parts.sort()
    return "".join(t for _, t in parts), exact


def _fmt_key(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    hh, rem = divmod(ms, 3_600_000)
    mm, rem = divmod(rem, 60_000)
    ss, mss = divmod(rem, 1_000)
    return f"{hh:02d}:{mm:02d}:{ss:02d},{mss:03d}"


def census_term(a_text: str, b_text: str, cues_a, cues_b, route, term: str, basis: str = "proofread-route") -> dict:
    """Classify every occurrence of one term in arm A.

    R — the term is in A where B is worse (homophone or omitted) AND the caption route
        agrees the term was spoken.
    I — the term is in A where B differs and the caption route over that span does not
        contain the term: the speaker said something else.
    U — no reading decides (no route coverage over the span, or an empty caption side).
    """
    counts = {"R": 0, "I": 0, "F": 0, "U": 0}
    spans = []
    if term not in a_text:
        return {"counts": counts, "spans": spans, "exercised_in_a": False, "exercised_in_b": term in b_text}

    for (start_stamp, end_stamp), cue_text in cues_a.items():
        if term not in cue_text:
            continue
        start, end = srt_seconds(start_stamp), srt_seconds(end_stamp)
        b_same_bucket, b_exact_key = arm_b_text_over(cues_b, start, end)
        overlapping = route_over(route, start, end)
        caption = "".join(str(r.get("kept") or "") for r in overlapping)
        caption_asr = "".join(str(r.get("asr_text") or "") for r in overlapping)

        if term in b_same_bucket:
            # Inherited, not a recovery: both arms rendered it.  Counted for exercise only.
            continue
        if not overlapping:
            counts["U"] += 1
            spans.append({"start": start, "end": end, "class": "U", "arm_a": cue_text,
                          "arm_b": b_same_bucket, "caption": "", "basis": basis,
                          "reason": "no %s coverage over the span" % basis})
            continue
        if term in caption or term in caption_asr:
            counts["R"] += 1
            spans.append({"start": start, "end": end, "class": "R", "arm_a": cue_text,
                          "arm_b": b_same_bucket, "caption": caption[:200], "basis": basis,
                          "reason": "arm B is worse at this span and the %s carries the term" % basis})
        else:
            counts["I"] += 1
            spans.append({"start": start, "end": end, "class": "I", "arm_a": cue_text,
                          "arm_b": b_same_bucket, "caption": caption[:200], "basis": basis,
                          "reason": "arm B differs and the %s over the span does not carry the term" % basis})
    return {"counts": counts, "spans": spans,
            "exercised_in_a": True, "exercised_in_b": term in b_text}


def fabrications(a_text: str, b_text: str) -> int:
    """Placeholder kept out of the totals until a span-level reading decides a class.

    A fabrication is a character present in neither arm and not spoken.  Deciding it
    needs a span where A inserted a token the route's caption side does not carry, and
    every such span is already reported as class `I` with its caption text attached, so
    the operator's reading of those spans is what settles `F`.  Returning 0 here keeps
    the number honest: nothing is claimed that a span has not shown.
    """
    return 0


def main() -> int:
    ab = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/root/e2e-asr/ab-hotwords-qwen3")
    out_dir = pathlib.Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else ab
    arms = {name: ab / name for name in ("with", "without", "repeat")}

    report: dict = {"arms": {}, "items": {}, "terms": {}, "noise_floor": {}, "verdict_inputs": {}}

    # ---- per-arm read-back of the configuration actually used -------------------------
    for name, root in arms.items():
        mds = sorted((root / "transcripts" / "md").glob("*.md")) if (root / "transcripts" / "md").exists() else []
        entries = None
        model = None
        for md in mds:
            text = md.read_text(encoding="utf-8")
            if "asr_hotwords" not in text:
                continue
            front = text.split("---")[1]
            for line in front.strip().splitlines():
                key, _, value = line.partition(": ")
                if key == "asr_hotwords":
                    terms = [t for t in str(value).strip().strip('"').split(",") if t]
                    if entries is None:
                        entries = len(terms)
                if key == "asr_model_name":
                    model = value.strip().strip('"')
        report["arms"][name] = {"md_count": len(mds), "asr_hotwords_entries": entries, "asr_model_name": model}

    # ---- which items are we even measuring? ------------------------------------------
    # Read the set off arm A's own artifacts rather than trusting a constant.  A
    # hardcoded list that disagrees with what ran produces a confident report about
    # the wrong corpus — the failure mode this census exists to avoid.  The declared
    # lists are kept only to supply the duration for each item; an artifact whose
    # bvid is in neither list is still measured, with its duration taken from
    # whatever the other arms' rows carry.
    declared = dict(ITEMS)
    declared.update(dict(SHORT_ITEMS))
    found = sorted(p.name[: -len(".p0.txt")]
                   for p in (arms["with"] / "transcripts" / "txt").glob("*.p0.txt"))
    items: list[tuple[str, int]] = []
    for bvid in found:
        dur = declared.get(bvid)
        if dur is None:
            dur = _duration_from_artifacts(arms, bvid)
        items.append((bvid, dur))
    if not items:
        print("census: no transcripts in arm 'with' — nothing to measure", file=sys.stderr)
        return 1
    undeclared = [b for b, _ in items if b not in declared]
    if undeclared:
        print(f"census: measuring {len(undeclared)} item(s) not in either declared list: {undeclared}",
              file=sys.stderr)
    print(f"census: {len(items)} items read from arm 'with': {[b for b, _ in items]}", file=sys.stderr)

    # ---- per item --------------------------------------------------------------------
    per_item = {}
    corpus_a: list[str] = []
    corpus_b: list[str] = []
    for bvid, duration in items:
        a_text = read_txt(arms["with"], bvid)
        b_text = read_txt(arms["without"], bvid)
        cues_a = read_cues(arms["with"], bvid)
        cues_b = read_cues(arms["without"], bvid)
        route, basis = load_route(bvid)
        entry = {"duration_s": duration, "a_present": a_text is not None, "b_present": b_text is not None,
                 "cues_a": len(cues_a), "cues_b": len(cues_b), "route_records": len(route)}
        if a_text is not None and b_text is not None:
            entry["ratio_a_vs_b"] = round(ratio(a_text, b_text), 6)
            shared = set(cues_a) & set(cues_b)
            differing = sum(1 for k in shared if cues_a[k] != cues_b[k])
            entry["shared_buckets"] = len(shared)
            entry["differing_shared_buckets"] = differing
            corpus_a.append(a_text)
            corpus_b.append(b_text)
        per_item[bvid] = entry
    report["items"] = per_item

    joined_a = "\n".join(corpus_a)
    joined_b = "\n".join(corpus_b)
    report["verdict_inputs"]["corpus_ratio_a_vs_b"] = round(ratio(joined_a, joined_b), 6) if corpus_a else None

    # ---- per-term census ------------------------------------------------------------
    term_rows = {}
    totals = {"R": 0, "I": 0, "F": 0, "U": 0}
    exercised = 0
    for term in TERMS:
        acc = {"R": 0, "I": 0, "F": 0, "U": 0}
        spans: list[dict] = []
        exercised_in_b = False
        for bvid, _ in items:
            a_text = read_txt(arms["with"], bvid)
            b_text = read_txt(arms["without"], bvid)
            if a_text is None or b_text is None:
                continue
            route, basis = load_route(bvid)
            result = census_term(a_text, b_text, read_cues(arms["with"], bvid), read_cues(arms["without"], bvid),
                                 route, term, basis)
            for key in acc:
                acc[key] += result["counts"][key]
            exercised_in_b = exercised_in_b or result["exercised_in_b"]
            for span in result["spans"]:
                spans.append({"item": bvid, **span})
        if acc["R"] or acc["I"] or acc["U"] or exercised_in_b:
            exercised += 1
        for key in totals:
            totals[key] += acc[key]
        term_rows[term] = {**acc, "spans": spans, "exercised_in_b": exercised_in_b}

    report["terms"] = term_rows
    report["totals"] = totals
    report["exercised_terms"] = exercised
    report["verdict_inputs"]["E"] = exercised
    report["verdict_inputs"]["max_single_term_insertions"] = max((r["I"] for r in term_rows.values()), default=0)

    # ---- noise floor: arm R vs arm A ------------------------------------------------
    # The floor is measured over every item arm R carries.  On the long corpus that
    # is one item (its longest, §7); on the short corpus arm R repeats the whole set,
    # and a whole-corpus floor is strictly better evidence than a single item's.
    # Reading the set off arm R's artifacts keeps this in step with what ran.
    r_items = sorted(p.name[: -len(".p0.txt")]
                     for p in (arms["repeat"] / "transcripts" / "txt").glob("*.p0.txt"))
    noise: dict = {"arm_r_items": r_items, "per_item": {}, "scope": "whole-corpus" if len(r_items) > 1 else "single-item"}
    for bvid in r_items:
        a_text = read_txt(arms["with"], bvid)
        r_text = read_txt(arms["repeat"], bvid)
        if a_text is None or r_text is None:
            noise["per_item"][bvid] = {"ratio_a_vs_r": None, "error": "arm R or arm A has no txt for this item"}
            continue
        cues_a = read_cues(arms["with"], bvid)
        cues_r = read_cues(arms["repeat"], bvid)
        shared = set(cues_a) & set(cues_r)
        noise["per_item"][bvid] = {
            "ratio_a_vs_r": round(ratio(a_text, r_text), 6),
            "shared_buckets": len(shared),
            "differing_shared_buckets": sum(1 for k in shared if cues_a[k] != cues_r[k]),
            "byte_identical": a_text == r_text,
        }
    scored = [v["ratio_a_vs_r"] for v in noise["per_item"].values() if v.get("ratio_a_vs_r") is not None]
    if scored:
        noise["min_ratio_a_vs_r"] = min(scored)
        noise["all_byte_identical"] = all(v.get("byte_identical") for v in noise["per_item"].values())
    else:
        noise["error"] = "no item had a txt on both arm A and arm R"
    noise["P7_bar"] = 0.995
    noise["P7_passes"] = (noise.get("min_ratio_a_vs_r") is not None
                          and noise["min_ratio_a_vs_r"] >= noise["P7_bar"])
    report["noise_floor"] = noise

    # ---- P8 damage classes ----------------------------------------------------------
    damage = {}
    for bvid, _ in items:
        cues_a = read_cues(arms["with"], bvid)
        cues_b = read_cues(arms["without"], bvid)
        if not cues_a:
            continue
        empty_where_b_long = sum(1 for k, v in cues_a.items()
                                 if not v.strip() and len(cues_b.get(k, "")) >= 4)
        texts = list(cues_a.values())
        runs = max((len(list(g)) for _, g in __import__("itertools").groupby(texts)), default=0)
        damage[bvid] = {"cues_a": len(cues_a), "cues_b": len(cues_b),
                        "empty_where_b_has_4": empty_where_b_long,
                        "longest_identical_run": runs}
    report["verdict_inputs"]["damage"] = damage

    # ---- write ----------------------------------------------------------------------
    (out_dir / "census.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# T5 census", "",
             "Computed by `census.py` from the three arm roots. Thresholds and their verdict mapping are",
             "in `t5-hotword-measurement-protocol.md` §5 — this file reports numbers, it does not set them.", "",
             "## Arm read-back", "",
             "| arm | md files | `asr_hotwords` entries | `asr_model_name` |", "|---|---|---|---|"]
    for name in ("with", "without", "repeat"):
        row = report["arms"][name]
        lines.append(f"| {name} | {row['md_count']} | {row['asr_hotwords_entries']} | {row['asr_model_name']} |")
    lines += ["", "## Per item", "", "| item | duration s | A | B | ratio(A,B) | shared buckets | differing | cues A | cues B |",
              "|---|---|---|---|---|---|---|---|---|"]
    for bvid, duration in items:
        row = per_item[bvid]
        lines.append(f"| {bvid} | {duration} | {row['a_present']} | {row['b_present']} | {row.get('ratio_a_vs_b','—')} | "
                     f"{row.get('shared_buckets','—')} | {row.get('differing_shared_buckets','—')} | {row['cues_a']} | {row['cues_b']} |")
    lines += ["", f"Corpus ratio(A,B) over the completed items: **{report['verdict_inputs'].get('corpus_ratio_a_vs_b')}** (P6 bar: ≥ 0.95)", "",
              "## Per-term census", "", "| term | R | I | U | exercised in B |", "|---|---|---|---|---|"]
    for term in TERMS:
        row = term_rows[term]
        lines.append(f"| `{term}` | {row['R']} | {row['I']} | {row['U']} | {row['exercised_in_b']} |")
    lines += ["", f"**Totals** — R = {totals['R']}, I = {totals['I']}, U = {totals['U']}, "
                  f"E (terms exercised) = {exercised}, max single-term insertions = "
                  f"{report['verdict_inputs']['max_single_term_insertions']}", "",
              "## Noise floor", "", "```json", json.dumps(report["noise_floor"], ensure_ascii=False, indent=2), "```", "",
              "## Damage classes (P8)", "", "```json", json.dumps(damage, ensure_ascii=False, indent=2), "```", "",
              "## Spans", ""]
    for term in TERMS:
        spans = term_rows[term]["spans"]
        if not spans:
            continue
        lines.append(f"### `{term}`")
        lines.append("")
        for span in spans:
            lines.append(f"- **{span['class']}** {span['item']} [{span['start']:.2f}–{span['end']:.2f}] "
                         f"A: {span['arm_a'][:80]!r} | B: {span['arm_b'][:60]!r} | caption: {span['caption'][:60]!r} — {span['reason']}")
        lines.append("")
    (out_dir / "CENSUS.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_dir/'CENSUS.md'} and census.json")
    print(f"R={totals['R']} I={totals['I']} U={totals['U']} E={exercised} "
          f"corpus_ratio={report['verdict_inputs'].get('corpus_ratio_a_vs_b')} "
          f"noise={report['noise_floor'].get('ratio_a_vs_r')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
