# -*- coding: utf-8 -*-
"""
未明子(bvid 23191782) 投稿元数据全量抓取
API: x/series/recArchivesByKeywords (无需wbi签名, 亲测可用)
输出: archive/manifest/manifest.jsonl  (bvid/aid/标题/时长秒/发布时间戳/播放/分区状态)
用法: python fetch_meta.py [--resume]
"""
import json, time, random, sys, os
from pathlib import Path
from datetime import datetime

import requests

MID = 23191782
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "archive" / "manifest" / "manifest.jsonl"
API = "https://api.bilibili.com/x/series/recArchivesByKeywords"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "Referer": f"https://space.bilibili.com/{MID}/video",
}

session = requests.Session()
session.headers.update(HEADERS)

def warmup():
    """访问主页获取 buvid3 等风控 cookie"""
    for url in ("https://www.bilibili.com/", f"https://space.bilibili.com/{MID}/video"):
        try:
            session.get(url, timeout=20)
            time.sleep(random.uniform(0.5, 1.0))
        except Exception as e:
            print(f"warmup {url} failed: {e}")
    print(f"cookies: {list(session.cookies.keys())}")

def fetch_page(pn: int, ps: int = 30, retries: int = 4):
    for attempt in range(1, retries + 1):
        try:
            r = session.get(API, params={"mid": MID, "keywords": "", "ps": ps, "pn": pn},
                            timeout=20)
            r.raise_for_status()
            data = r.json()
            if data.get("code") != 0:
                print(f"  [pn={pn}] API code={data.get('code')} {data.get('message')}", flush=True)
                return None
            return data["data"]
        except Exception as e:
            wait = 3 * attempt
            print(f"  [pn={pn}] attempt{attempt} failed: {e} -> sleep {wait}s", flush=True)
            if attempt < retries:
                time.sleep(wait)
                if "412" in str(e) or "403" in str(e):
                    warmup()
    return None

def main():
    warmup()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if OUT.exists() and "--resume" in sys.argv:
        with OUT.open(encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                existing[rec["bvid"]] = rec
        print(f"resume: {len(existing)} records loaded")

    all_records = dict(existing)
    pn, total, empty_streak = 1, None, 0
    while True:
        data = fetch_page(pn)
        if data is None:
            print(f"page {pn} failed after retries, stop. (use --resume to continue)")
            break
        total = data.get("page", {}).get("total")
        arcs = data.get("archives") or []
        if not arcs:
            empty_streak += 1
            if empty_streak >= 2:
                break
            pn += 1
            continue
        empty_streak = 0
        new_cnt = 0
        for a in arcs:
            bv = a.get("bvid")
            if not bv or bv in all_records:
                continue
            all_records[bv] = {
                "bvid": bv,
                "aid": a.get("aid"),
                "title": a.get("title", "").strip(),
                "duration_s": a.get("duration", 0),
                "pubdate": a.get("pubdate"),
                "pubdate_str": datetime.fromtimestamp(a["pubdate"]).strftime("%Y-%m-%d") if a.get("pubdate") else "",
                "view": (a.get("stat") or {}).get("view"),
                "interactive_video": a.get("interactive_video", False),
                "state": a.get("state"),
            }
            new_cnt += 1
        print(f"pn={pn:3d} got={len(arcs):3d} new={new_cnt:3d} total_seen={len(all_records)} (api_total={total})", flush=True)
        # 若某页全部为已知记录(按时间倒序遍历到旧数据), 继续翻完以容错
        pn += 1
        if total and len(all_records) >= total and new_cnt == 0:
            break
        time.sleep(random.uniform(0.8, 1.6))

    with OUT.open("w", encoding="utf-8") as f:
        for rec in all_records.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ---- 统计 ----
    recs = list(all_records.values())
    total_s = sum(r["duration_s"] for r in recs)
    years = {}
    for r in recs:
        y = r["pubdate_str"][:4] or "unknown"
        d, c = years.get(y, (0, 0))
        years[y] = (d + r["duration_s"], c + 1)
    print("\n==== SUMMARY ====")
    print(f"records: {len(recs)}  api_total: {total}")
    print(f"total duration: {total_s/3600:.1f} h  ({total_s/86400:.1f} days)")
    for y in sorted(years):
        d, c = years[y]
        print(f"  {y}: {c:4d} videos, {d/3600:8.1f} h")

if __name__ == "__main__":
    main()
