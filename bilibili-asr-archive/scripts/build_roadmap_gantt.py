#!/usr/bin/env python3
"""Generate the standalone multi-track roadmap Gantt from one data model.

Why this exists
---------------
The roadmap has three tracks that are *not* phases in a sequence: they run
concurrently after one shared gate, each with its own dependency chain, and the
landing work in two of them is blocked by the third. A flat Mermaid ``gantt``
cannot say that. Mermaid ``section`` blocks are visual bands, not lanes with
independent chains; it has no way to draw a hard cross-lane gate, and it cannot
place two milestones on one lane. The result reads as a waterfall even when the
data says otherwise.

This script renders the roadmap as real swimlanes: one row per track, diamonds
for that track's exit milestones, dashed connectors for cross-lane hard gates,
and a today marker. It is data-first — ``_ROADMAP`` below is the single source
of truth, and the Markdown table in ``docs/roadmap-gantt.md`` is generated from
it, so the diagram and the prose cannot drift apart.

Usage:
    python3 scripts/build_roadmap_gantt.py            # writes docs/roadmap-gantt.html
    python3 scripts/build_roadmap_gantt.py --check    # exit 1 when the HTML is stale
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html
import os
import sys
from dataclasses import dataclass, field
from typing import Literal

# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

Status = Literal["done", "active", "ready", "blocked"]


@dataclass(frozen=True)
class Node:
    """One schedulable item on a lane.

    ``kind`` distinguishes a work slice from an exit milestone. Milestones are
    graph nodes like anything else, which is what lets a task say "after m1"
    without the scheduler having to guess which tasks constitute that gate.
    """

    id: str
    label: str
    lane: str
    kind: Literal["task", "milestone"]
    days: int = 0
    start: str | None = None          # anchors that are not derived from `after`
    status: Status = "blocked"
    after: tuple[str, ...] = ()
    note: str = ""
    critical: bool = False


@dataclass(frozen=True)
class Lane:
    id: str
    title: str
    subtitle: str
    color: str
    role: str


@dataclass
class Roadmap:
    anchor: str
    generated: str
    lanes: list[Lane] = field(default_factory=list)
    nodes: list[Node] = field(default_factory=list)


def _d(iso: str) -> _dt.date:
    return _dt.date.fromisoformat(iso)


#: Single source of truth.
#:
#: Dates are anchored, not relative: an anchor plus a start day reads as a
#: schedule, and moving the plan is one edit to ``anchor``. Durations are
#: deliberately generous — this repo has measured that agent work inverts naive
#: size ordering, so a plan that looks slack usually is not.
_ROADMAP = Roadmap(
    anchor="2026-10-04",
    generated="2026-10-04",
    lanes=[
        Lane("gate", "Phase 0.5 — 证据层",
             "成功与耗尽必须可证实 · 一切并发的硬前置",
             "#dc2626", "gate"),
        Lane("skeleton", "Track A — 骨架",
             "处理器注册表 → 缺口队列（落地主链）",
             "#2563eb", "skeleton"),
        Lane("content", "Track B — 内容",
             "终态谓词 → 画面字节",
             "#7c3aed", "content"),
        Lane("sources", "Track C — 数据源",
             "评论 source → 派生关系",
             "#059669", "sources"),
        Lane("verify", "N=2 检验",
             "第二个非 ASR 处理器真实跑通",
             "#d97706", "verify"),
    ],
    nodes=[
        # ---------------- Phase 0.5: the gate ----------------------------- #
        Node("p05fix", "snapshot 写并发缺陷族", "gate", "task", 4, "2026-10-04",
             "active", note="I-000190 / I-000195 / I-000207"),
        Node("p05a", "caption-exhaustion-attestation", "gate", "task", 4,
             status="active", after=("p05fix",),
             note="已合并 ff11351 · PR #212；此行保留取证轨迹"),
        Node("p05ed", "editorial-stages 裁决", "gate", "task", 2, "2026-10-04",
             "ready", note="parked 两周；close 或恢复为 Phase 4 输入，二选一"),
        Node("p05b", "asr-coverage-attestation", "gate", "task", 5,
             after=("p05a",), status="blocked",
             note="I-000188 · 待操作者放行（D12 / I-000201）"),
        Node("m-gate", "成功与耗尽可证实", "gate", "milestone",
             after=("p05b",), status="blocked", critical=True),

        # ---------------- Track A: skeleton ------------------------------- #
        Node("p1a", "processor_runs + 血缘 schema", "skeleton", "task", 4,
             after=("m-gate",), critical=True,
             note="扩展 acquisition_runs，不建平行表"),
        Node("p1b", "处理器注册表 name@version", "skeleton", "task", 3,
             after=("p1a",), critical=True),
        Node("p1c", "ASR 迁入骨架（第一个实例）", "skeleton", "task", 4,
             after=("p1b",), critical=True),
        Node("m-p1", "Phase 1 出口：重跑零重复行", "skeleton", "milestone",
             after=("p1c",), critical=True),
        Node("p2a", "声明式差集求值", "skeleton", "task", 5, after=("m-p1",),
             critical=True, note="替代 _store_audio_todo 硬编码"),
        Node("p2b", "注册即跑通假想 loudness", "skeleton", "task", 3,
             after=("p2a",), critical=True),
        Node("m-p2", "Phase 2 出口：不写新队列代码", "skeleton", "milestone",
             after=("p2b",), critical=True),

        # ---------------- Track B: content -------------------------------- #
        Node("p4design", "proofread 谓词泛化设计", "content", "task", 4,
             "2026-10-04", "ready", note="纯设计，不产生 schema，不受骨架阻塞"),
        Node("p5design", "画面 schema 草案", "content", "task", 3, "2026-10-04",
             "ready", note="纯设计"),
        Node("p4a", "终态谓词定义机制", "content", "task", 5, after=("m-p1",)),
        Node("p4b", "派生分支追加 + 投影层切换", "content", "task", 5,
             after=("p4a",)),
        Node("m-p4", "Phase 4 出口：<0.75 自动出新分支", "content", "milestone",
             after=("p4b",)),
        Node("p5a", "video_objects / frame_objects", "content", "task", 4,
             after=("m-p4",)),
        Node("p5b", "抽帧 + 场景切分处理器", "content", "task", 5,
             after=("p5a",)),
        Node("p5c", "画面 OCR 与 ASR 对齐", "content", "task", 6, after=("p5b",)),
        Node("m-p5", "画面与音频同一路径", "content", "milestone", after=("p5c",)),

        # ---------------- Track C: sources -------------------------------- #
        Node("p6design", "评论有界观察边界设计", "sources", "task", 2,
             "2026-10-04", "ready", note="时间窗 / 条数封顶 / 采集频率"),
        Node("p7design", "关系类型清单", "sources", "task", 1, "2026-10-04",
             "ready", note="声明 / 派生 / 语料"),
        Node("p6a", "comments / comment_events 表", "sources", "task", 3,
             after=("m-p1",)),
        Node("p6b", "有界观察采集器", "sources", "task", 4, after=("p6a",)),
        Node("m-p6", "评论进入同一派生管线", "sources", "milestone",
             after=("p6b",)),
        Node("p7a", "转录相似度 / embedding 近邻", "sources", "task", 4,
             after=("m-p6",)),
        Node("p7b", "关系带 processor 版本入库", "sources", "task", 5,
             after=("p7a",)),
        Node("m-p7", "关系可随算法重算", "sources", "milestone", after=("p7b",)),

        # ---------------- N=2 verification -------------------------------- #
        Node("p3a", "响度 / 频谱 / 时长统计处理器", "verify", "task", 4,
             after=("m-p2",), critical=True,
             note="现成库优先，血缘字段照记"),
        Node("p3b", "全库特征 artifact 带血缘入库", "verify", "task", 3,
             after=("p3a",), critical=True),
        Node("m-p3", "抽象对多处理器成立", "verify", "milestone", after=("p3b",),
             critical=True),
    ],
)

STATUS_LABEL = {
    "done": "已完成",
    "active": "进行中",
    "ready": "可开始",
    "blocked": "被阻塞",
}
STATUS_FILL = {
    "done": ("#16a34a", "#15803d"),
    "active": ("#dc2626", "#b91c1c"),
    "ready": ("#2563eb", "#1d4ed8"),
    "blocked": ("#64748b", "#475569"),
}

# --------------------------------------------------------------------------- #
# Scheduling
# --------------------------------------------------------------------------- #

DAY_W = 13.2          # horizontal pixels per calendar day (authored scale)
LANE_GAP = 10.0
BAR_H = 24.0
BAR_VGAP = 8.0
LEFT_W = 226.0
HEADER_H = 88.0
FOOTER_H = 58.0
PAD_RIGHT = 34.0


def schedule(rm: Roadmap) -> dict[str, _dt.date]:
    """Resolve every node's start date with a topological pass.

    Both tasks and milestones are nodes, so "after m1" is an ordinary edge and
    no inference about which tasks constitute a gate is needed. A node with a
    literal ``start`` is additionally floored at that date, which is how
    "this design work may begin now, in parallel with the gate" is expressed.
    """
    nodes = {n.id: n for n in rm.nodes}
    resolved: dict[str, _dt.date] = {}
    visiting: set[str] = set()

    def resolve(nid: str) -> _dt.date:
        if nid in resolved:
            return resolved[nid]
        if nid in visiting:
            raise ValueError(f"cyclic `after` edge through {nid}")
        if nid not in nodes:
            raise ValueError(f"unknown dependency {nid!r}")
        visiting.add(nid)
        node = nodes[nid]
        start = _d(node.start) if node.start else _d(rm.anchor)
        for dep in node.after:
            start = max(start, resolve(dep) + _dt.timedelta(days=nodes[dep].days))
        visiting.discard(nid)
        resolved[nid] = start
        return start

    for nid in nodes:
        resolve(nid)
    return resolved


def _text_px(s: str, size: float) -> float:
    """Estimate rendered width: CJK glyphs are full-width, Latin about 0.56em.

    Estimation is deliberate rather than measurement-through-a-browser: this
    script must run without a browser, and the packing rule only needs a
    conservative upper bound so two labels never share a pixel column.
    """
    cjk = sum(1 for ch in s if ord(ch) > 0x2E80)
    other = len(s) - cjk
    return cjk * size + other * size * 0.56


#: A bar narrower than this shows its label outside instead of inside.
INSIDE_LABEL_MIN_PX = 118.0
#: Horizontal breathing room between a label and the next element.
LABEL_GAP_PX = 9.0


def lane_layout(
    rm: Roadmap, starts: dict[str, _dt.date], origin: _dt.date
) -> tuple[dict[str, list[list[str]]], dict[str, float]]:
    """Pack each lane's items into sub-rows, accounting for label extents.

    Sub-row packing (rather than one row per lane) is what keeps a lane legible
    when it legitimately runs two things at once — the design work in Tracks B/C
    overlaps the gate by design, and collapsing that into one row would hide the
    parallelism the diagram exists to show.

    The packing rule is **label-aware**: an item's reserved span is its bar plus
    the label that trails it when the bar is too narrow to hold the text. Packing
    on bar extents alone is what lets a long outside label run under the next bar.
    """
    nodes = {n.id: n for n in rm.nodes}

    def extent(nid: str) -> tuple[float, float]:
        """Reserved [start, end] in day units, including a trailing label."""
        n = nodes[nid]
        s = starts[nid]
        e = s + _dt.timedelta(days=max(n.days, 1))
        x0 = (s - origin).days * DAY_W
        x1 = (e - origin).days * DAY_W
        if n.kind == "milestone":
            # Diamond plus its trailing label.
            return x0, x1 + 13.0 + _text_px(n.label, 10.5) + LABEL_GAP_PX
        if x1 - x0 >= INSIDE_LABEL_MIN_PX:
            return x0, x1 + LABEL_GAP_PX
        return x0, x1 + 7.0 + _text_px(n.label, 11.0) + LABEL_GAP_PX

    rows_by_lane: dict[str, list[list[str]]] = {}
    for lane in rm.lanes:
        tasks = sorted(
            (
                n for n in rm.nodes
                if n.lane == lane.id and n.kind == "task"
            ),
            key=lambda n: (starts[n.id], n.id),
        )
        rows: list[list[str]] = []
        for n in tasks:
            lo, hi = extent(n.id)
            placed = False
            for row in rows:
                clash = any(
                    not (hi <= extent(o)[0] or lo >= extent(o)[1]) for o in row
                )
                if not clash:
                    row.append(n.id)
                    placed = True
                    break
            if not placed:
                rows.append([n.id])

        # Milestones get their own rows, appended after every task row and in
        # chronological order. Packing them together with tasks let a later
        # milestone land on an earlier row — so "Phase 2 exit" could sit *above*
        # "Phase 1 exit", which reads as a schedule going backwards.
        miles = sorted(
            (n for n in rm.nodes if n.lane == lane.id and n.kind == "milestone"),
            key=lambda n: (starts[n.id], n.id),
        )
        mrows: list[list[str]] = []
        for n in miles:
            lo, hi = extent(n.id)
            for row in mrows:
                clash = any(
                    not (hi <= extent(o)[0] or lo >= extent(o)[1]) for o in row
                )
                if not clash:
                    row.append(n.id)
                    break
            else:
                mrows.append([n.id])
        rows.extend(mrows)
        rows_by_lane[lane.id] = rows

    lane_h: dict[str, float] = {}
    for lane in rm.lanes:
        n_rows = max(1, len(rows_by_lane[lane.id]))
        lane_h[lane.id] = n_rows * (BAR_H + BAR_VGAP) + BAR_VGAP + 22
    return rows_by_lane, lane_h


def render_svg(rm: Roadmap, today: _dt.date) -> str:
    starts = schedule(rm)
    nodes = {n.id: n for n in rm.nodes}
    starts_list = [starts[n.id] for n in rm.nodes]
    ends_list = [
        starts[n.id] + _dt.timedelta(days=max(n.days, 1)) for n in rm.nodes
    ]
    lo = min(starts_list)
    lo -= _dt.timedelta(days=lo.weekday())
    hi = max(ends_list) + _dt.timedelta(days=4)

    # Packing and drawing must share one origin, or a packed label extent will
    # not correspond to the pixels it was reserved for.
    rows_by_lane, lane_h = lane_layout(rm, starts, lo)

    def x_of(day: _dt.date) -> float:
        return LEFT_W + (day - lo).days * DAY_W

    # Widen the canvas to the furthest label, not merely the furthest bar: a
    # trailing label that runs past the last bar is content, and clipping it
    # would hide exactly the milestone names the diagram exists to show.
    label_reach = max(
        (
            x_of(starts[n.id] + _dt.timedelta(days=max(n.days, 1)))
            + (
                _text_px(n.label, 10.5) + 13.0
                if n.kind == "milestone"
                else (0.0 if n.days * DAY_W >= INSIDE_LABEL_MIN_PX
                      else _text_px(n.label, 11.0) + 7.0)
            )
            for n in rm.nodes
        ),
        default=0.0,
    )
    width = max(x_of(hi), label_reach) + PAD_RIGHT
    lane_y: dict[str, float] = {}
    y = HEADER_H
    for lane in rm.lanes:
        lane_y[lane.id] = y
        y += lane_h[lane.id] + LANE_GAP
    height = y + FOOTER_H

    out: list[str] = []
    add = out.append
    add(
        f'<svg id="gantt" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'preserveAspectRatio="xMinYMin meet" '
        f'role="img" aria-labelledby="gantt-title gantt-desc" '
        f'xmlns="http://www.w3.org/2000/svg">'
    )
    add("<title id=\"gantt-title\">未明子 ASR 归档平台 — 多轨道路线图</title>")
    add(
        '<desc id="gantt-desc">五条泳道：Phase 0.5 证据层（硬前置）、Track A 骨架、'
        'Track B 内容、Track C 数据源、N=2 检验。菱形为该泳道出口里程碑，'
        '橙色虚线为跨泳道硬门禁。</desc>'
    )

    # Lane bands + labels.
    for i, lane in enumerate(rm.lanes):
        top = lane_y[lane.id]
        h = lane_h[lane.id]
        add(
            f'<rect class="lane-band" x="0" y="{top:.1f}" width="{width:.0f}" '
            f'height="{h:.1f}" fill="{lane.color}" '
            f'opacity="{0.062 if i % 2 == 0 else 0.03}"/>'
        )
        add(
            f'<line class="lane-sep" x1="0" y1="{top - LANE_GAP / 2:.1f}" '
            f'x2="{width:.0f}" y2="{top - LANE_GAP / 2:.1f}"/>'
        )
        add(
            f'<text class="lane-title" x="16" y="{top + 26:.1f}" '
            f'fill="{lane.color}">{html.escape(lane.title)}</text>'
        )
        add(
            f'<text class="lane-sub" x="16" y="{top + 45:.1f}">'
            f'{html.escape(lane.subtitle)}</text>'
        )

    # Month gridlines and axis labels.
    cur = _dt.date(lo.year, lo.month, 1)
    while cur <= hi:
        if cur >= lo:
            gx = x_of(cur)
            add(
                f'<line class="grid" x1="{gx:.1f}" y1="{HEADER_H - 30:.1f}" '
                f'x2="{gx:.1f}" y2="{height - FOOTER_H + 8:.1f}"/>'
            )
            add(
                f'<text class="axis" x="{gx + 5:.1f}" y="{HEADER_H - 38:.1f}">'
                f'{cur.strftime("%Y-%m")}</text>'
            )
        nxt = (cur.replace(day=28) + _dt.timedelta(days=4)).replace(day=1)
        cur = nxt

    # Bars, then milestone diamonds, drawn lane by lane.
    for lane in rm.lanes:
        top = lane_y[lane.id]
        for ri, row in enumerate(rows_by_lane[lane.id]):
            by = top + BAR_VGAP + ri * (BAR_H + BAR_VGAP)
            for nid in [i for i in row if nodes[i].kind == "task"]:
                n = nodes[nid]
                s = starts[nid]
                e = s + _dt.timedelta(days=max(n.days, 1))
                x = x_of(s)
                w = max(DAY_W, x_of(e) - x)
                fill, stroke = STATUS_FILL[n.status]
                cls = "bar crit" if n.critical else "bar"
                tip = (
                    f"{n.label} — {STATUS_LABEL[n.status]}（{n.days} 天，"
                    f"起 {s.isoformat()}）"
                    + ("；关键路径" if n.critical else "")
                    + (f"；{n.note}" if n.note else "")
                )
                add(
                    f'<g class="{cls} {n.status}" tabindex="0" data-node="{nid}">'
                    f"<title>{html.escape(tip)}</title>"
                    f'<rect x="{x:.1f}" y="{by:.1f}" width="{w:.1f}" '
                    f'height="{BAR_H:.1f}" rx="5" fill="{fill}" '
                    f'stroke="{stroke}"/></g>'
                )
                inside = w >= 118
                if inside:
                    add(
                        f'<text class="bar-label" x="{x + 8:.1f}" '
                        f'y="{by + BAR_H / 2 + 4:.1f}">{html.escape(n.label)}'
                        f"</text>"
                    )
                else:
                    add(
                        f'<text class="bar-label outside" x="{x + w + 7:.1f}" '
                        f'y="{by + BAR_H / 2 + 4:.1f}">{html.escape(n.label)}'
                        f"</text>"
                    )

        # Milestones on this lane get their own labelled rows. They are packed
        # like bars (via lane_layout) precisely so a long milestone label cannot
        # run into the neighbouring diamond's text.
        ms_rows = [
            (ri, [nid for nid in row if nodes[nid].kind == "milestone"])
            for ri, row in enumerate(rows_by_lane[lane.id])
        ]
        for ri, row in ms_rows:
            if not row:
                continue
            my = top + BAR_VGAP + ri * (BAR_H + BAR_VGAP) + BAR_H / 2
            for nid in row:
                n = nodes[nid]
                mx = x_of(starts[nid])
                add(
                    f'<g class="milestone" data-node="{nid}">'
                    f"<title>{html.escape(n.label)} — {starts[nid].isoformat()}"
                    f"</title>"
                    f'<path d="M {mx:.1f} {my - 8.5:.1f} L {mx + 8.5:.1f} {my:.1f} '
                    f'L {mx:.1f} {my + 8.5:.1f} L {mx - 8.5:.1f} {my:.1f} Z" '
                    f'fill="{lane.color}"/>'
                    f'<text class="ms-label" x="{mx + 13:.1f}" '
                    f'y="{my + 3.5:.1f}">{html.escape(n.label)}</text></g>'
                )

    # Cross-lane hard gates: derived from every `after` edge that crosses lanes.
    for n in rm.nodes:
        for dep in n.after:
            src, dst = nodes[dep], n
            if src.lane == dst.lane:
                continue
            sx = x_of(starts[src.id] + _dt.timedelta(days=max(src.days, 1)))
            dx = x_of(starts[dst.id])
            y1 = lane_y[src.lane] + lane_h[src.lane] - 4
            y2 = lane_y[dst.lane] + BAR_VGAP + 6
            if y2 < y1:
                y1, y2 = y2, y1
            mid = max(sx, dx) + 15
            tip = html.escape(f"{src.label} → {dst.label}（硬门禁）")
            add(
                f'<path class="gate" d="M {sx:.1f} {y1:.1f} L {sx:.1f} '
                f'{y1 + 11:.1f} L {mid:.1f} {y1 + 11:.1f} L {mid:.1f} '
                f'{y2 - 10:.1f} L {dx:.1f} {y2 - 10:.1f} L {dx:.1f} {y2:.1f}">'
                f"<title>{tip}</title></path>"
            )
            add(
                f'<path class="gate-arrow" d="M {dx - 3.6:.1f} {y2 - 4.6:.1f} '
                f'L {dx:.1f} {y2:.1f} L {dx + 3.6:.1f} {y2 - 4.6:.1f}">'
                f"<title>{tip}</title></path>"
            )

    # Today marker. The label is anchored in the band *above* the axis labels so
    # it cannot sit on top of a month name (measured: the two collided when both
    # were drawn at the same y).
    if lo <= today <= hi:
        tx = x_of(today)
        add(
            f'<line class="today" x1="{tx:.1f}" y1="{HEADER_H - 30:.1f}" '
            f'x2="{tx:.1f}" y2="{height - FOOTER_H + 8:.1f}">'
            f"<title>今天 {today.isoformat()}</title></line>"
        )
        anchor = "start" if tx < width * 0.55 else "end"
        dx = 5.0 if anchor == "start" else -5.0
        add(
            f'<text class="today-label" x="{tx + dx:.1f}" '
            f'y="{HEADER_H - 50:.1f}" text-anchor="{anchor}">'
            f"today {today.isoformat()}</text>"
        )

    # Critical path rail, drawn in the footer for orientation.
    foot_y = height - FOOTER_H / 2 - 4
    crit = [n for n in rm.nodes if n.critical]
    for n in crit:
        s = starts[n.id]
        e = s + _dt.timedelta(days=max(n.days, 1))
        x, w = x_of(s), max(DAY_W, x_of(e) - x_of(s))
        add(
            f'<rect class="crit-rail" x="{x:.1f}" y="{foot_y - 5:.1f}" '
            f'width="{w:.1f}" height="4" rx="2"/>'
        )
    add(
        f'<text class="foot" x="16" y="{foot_y:.1f}">关键路径</text>'
    )
    end_crit = max(
        (starts[n.id] + _dt.timedelta(days=max(n.days, 1)) for n in crit),
        default=_d(rm.anchor),
    )
    add(
        f'<text class="foot" x="{x_of(end_crit) + 8:.1f}" y="{foot_y:.1f}">'
        f"{end_crit.isoformat()}</text>"
    )

    add("</svg>")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# HTML shell
# --------------------------------------------------------------------------- #

_CSS = """
:root {
  --bg:#f6f8fb; --panel:#fff; --text:#0f172a; --muted:#64748b;
  --line:#e2e8f0; --inside:#fff; --outside:#334155; --rail:#dc2626;
}
html[data-theme="dark"] {
  --bg:#020617; --panel:#0b1220; --text:#e2e8f0; --muted:#94a3b8;
  --line:#1e293b; --inside:#fff; --outside:#cbd5e1; --rail:#f87171;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font:14px/1.55 ui-sans-serif,system-ui,"Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif}
header{max-width:1360px;margin:0 auto;padding:22px 22px 8px}
h1{margin:0 0 5px;font-size:20px;letter-spacing:.01em}
.lede{margin:0;color:var(--muted);font-size:13px}
.meta{margin:9px 0 0;color:var(--muted);font-size:12px}
.meta code{background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:1px 5px}
.controls{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:14px 0 0}
.controls button{font:inherit;font-size:12px;padding:5px 11px;cursor:pointer;
  background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:999px}
.controls button[aria-pressed="true"]{background:#2563eb;border-color:#2563eb;color:#fff}
.legend{display:flex;gap:15px;flex-wrap:wrap;margin:13px 0 0;font-size:12px;color:var(--muted)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.swatch{width:11px;height:11px;border-radius:3px;display:inline-block}
.diamond{width:9px;height:9px;display:inline-block;transform:rotate(45deg);background:#dc2626}
.dash{width:16px;height:0;display:inline-block;border-top:2px dashed #d97706}
main{max-width:1360px;margin:0 auto;padding:0 22px 44px}
.scroller{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:8px 8px 4px;overflow-x:auto}
svg#gantt{display:block;width:100%;height:auto;min-width:0}
body.zoom2 svg#gantt{width:200%}
body.zoom3 svg#gantt{width:300%}
.grid,.lane-sep{stroke:var(--line);stroke-width:1}
.lane-title{font-size:14.5px;font-weight:700}
.lane-sub{font-size:11px;fill:var(--muted)}
.axis{font-size:11px;fill:var(--muted);font-weight:600}
.today{stroke:#dc2626;stroke-width:2;opacity:.85}
.today-label{font-size:10px;fill:#dc2626;font-weight:700}
.bar{outline:none}
.bar rect{transition:filter .12s ease,opacity .12s ease}
.bar:hover rect,.bar:focus rect{filter:brightness(1.16)}
.bar.crit rect{stroke-width:2.2}
.bar-label{font-size:11px;fill:var(--inside);font-weight:600}
.bar-label.outside{fill:var(--outside);font-weight:500}
.ms-label{font-size:10.5px;fill:var(--text);font-weight:600}
.gate{fill:none;stroke:#d97706;stroke-width:1.5;stroke-dasharray:5 4;opacity:.92}
.gate-arrow{fill:none;stroke:#d97706;stroke-width:1.5}
.crit-rail{fill:var(--rail);opacity:.55}
.foot{font-size:10.5px;fill:var(--muted)}
body.dim-blocked .bar.blocked{opacity:.26}
body.focus-crit .bar:not(.crit){opacity:.2}
body.focus-crit .gate{opacity:.25}
h2{font-size:15px;margin:26px 0 8px}
ul.notes{margin:0;padding-left:20px}
ul.notes li{margin:5px 0;color:var(--muted)}
ul.notes b{color:var(--text);font-weight:600}
table{border-collapse:collapse;width:100%;margin:8px 0 0;font-size:13px}
th,td{text-align:left;padding:6px 9px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px}
td code{font-size:11.5px;background:var(--bg);border:1px solid var(--line);
  border-radius:4px;padding:0 4px}
"""

_JS = """
(function(){
  var root=document.documentElement;
  function theme(t){
    root.setAttribute('data-theme',t);
    try{localStorage.setItem('roadmap-theme',t)}catch(e){}
    document.getElementById('theme').textContent=(t==='dark')?'浅色':'深色';
  }
  var s=null;try{s=localStorage.getItem('roadmap-theme')}catch(e){}
  theme(s||(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark'));
  document.getElementById('theme').onclick=function(){
    theme(root.getAttribute('data-theme')==='dark'?'light':'dark');
  };
  function tog(id,cls){
    var b=document.getElementById(id);
    b.onclick=function(){
      var on=document.body.classList.toggle(cls);
      b.setAttribute('aria-pressed',on?'true':'false');
    };
  }
  tog('blocked','dim-blocked');
  tog('crit','focus-crit');
  document.getElementById('print').onclick=function(){window.print()};
  var z=1;
  document.getElementById('zoom').onclick=function(){
    document.body.classList.remove('zoom2','zoom3');
    z=z===1?2:(z===2?3:1);
    if(z>1)document.body.classList.add('zoom'+z);
    this.textContent='缩放 '+z+'×';
  };
})();
"""


def render_html(rm: Roadmap, today: _dt.date) -> str:
    starts = schedule(rm)
    svg = render_svg(rm, today)

    rows = "".join(
        "<tr>"
        f"<td><code>{n.id}</code></td><td>{html.escape(n.label)}</td>"
        f"<td>{html.escape(next(l.title for l in rm.lanes if l.id == n.lane))}</td>"
        f"<td>{n.kind}</td><td>{starts[n.id].isoformat()}</td>"
        f"<td>{n.days or '—'}</td><td>{STATUS_LABEL[n.status]}</td>"
        f"<td>{html.escape(n.note)}</td></tr>"
        for n in sorted(rm.nodes, key=lambda n: (starts[n.id], n.id))
    )
    ms_rows = "".join(
        "<tr>"
        f"<td><code>{n.id}</code></td><td>{html.escape(n.label)}</td>"
        f"<td>{html.escape(next(l.title for l in rm.lanes if l.id == n.lane))}</td>"
        f"<td>{starts[n.id].isoformat()}</td>"
        f"<td>{'是' if n.critical else '—'}</td></tr>"
        for n in rm.nodes if n.kind == "milestone"
    )
    gates = "".join(
        "<tr>"
        f"<td><code>{dep}</code></td><td><code>{n.id}</code></td>"
        f"<td>{html.escape(next(l.title for l in rm.lanes if l.id == nodes_lane(rm, dep)))}"
        f" → {html.escape(next(l.title for l in rm.lanes if l.id == n.lane))}</td></tr>"
        for n in rm.nodes for dep in n.after
        if nodes_lane(rm, dep) != n.lane
    )

    crit = " → ".join(n.id for n in rm.nodes if n.critical)
    end = max(
        (starts[n.id] + _dt.timedelta(days=max(n.days, 1)) for n in rm.nodes),
        default=_d(rm.anchor),
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>未明子 ASR 归档平台 — 多轨道路线图</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <h1>未明子 ASR 归档平台 — 多轨道路线图</h1>
  <p class="lede">Phase 0.5 是唯一的硬门禁；三条轨道在它出口后并行，其中两条的<b>落地</b>受 Track A 约束。</p>
  <p class="meta">
    锚点 <code>{rm.anchor}</code> · 生成于 <code>{rm.generated}</code> ·
    末端 <code>{end.isoformat()}</code> · 关键路径 <code>{crit}</code>
  </p>
  <div class="controls">
    <button id="theme" type="button">浅色</button>
    <button id="blocked" type="button" aria-pressed="false">弱化被阻塞项</button>
    <button id="crit" type="button" aria-pressed="false">聚焦关键路径</button>
    <button id="zoom" type="button">缩放 1×</button>
    <button id="print" type="button">打印 / 存 PDF</button>
  </div>
  <div class="legend">
    <span><i class="swatch" style="background:#16a34a"></i>已完成</span>
    <span><i class="swatch" style="background:#dc2626"></i>进行中</span>
    <span><i class="swatch" style="background:#2563eb"></i>可开始</span>
    <span><i class="swatch" style="background:#64748b"></i>被阻塞</span>
    <span><i class="diamond"></i>泳道出口里程碑</span>
    <span><i class="dash"></i>跨泳道硬门禁</span>
  </div>
</header>
<main>
  <div class="scroller">{svg}</div>

  <h2>怎么读这张图</h2>
  <ul class="notes">
    <li><b>竖排是泳道，不是章节。</b>Mermaid 的 <code>section</code> 只是视觉分带，
      无法表达「三条独立依赖链收敛到同一门禁」；这里每条泳道有自己的出口里程碑与依赖链。</li>
    <li><b>菱形 = 该泳道出口。</b>达成日由依赖链推导，不是写死的日历承诺；
      一条泳道可以有多个里程碑。</li>
    <li><b>橙色虚线 = 硬门禁。</b>它由 <code>after</code> 边自动推导，
      因此图与依赖数据不可能对不上。</li>
    <li><b>Track B/C 现在就能开始的是设计，不是落地。</b>
      <code>p4design</code> / <code>p5design</code> / <code>p6design</code> /
      <code>p7design</code> 不产生 schema，因此不受骨架阻塞——这才是「并发探索」的准确含义。</li>
    <li><b>Track B/C 之间无硬依赖。</b>结构上可并行；一人推进时仍建议串行，
      因为注意力切换本身是成本。</li>
    <li><b>底部红线表示关键路径的总跨度</b>，从 Phase 0.5 到 N=2 检验出口。</li>
  </ul>

  <h2>跨泳道硬门禁</h2>
  <table>
    <thead><tr><th>源</th><th>目标</th><th>跨泳道</th></tr></thead>
    <tbody>{gates}</tbody>
  </table>

  <h2>里程碑</h2>
  <table>
    <thead><tr><th>id</th><th>出口</th><th>泳道</th><th>达成日</th><th>关键路径</th></tr></thead>
    <tbody>{ms_rows}</tbody>
  </table>

  <h2>任务台账</h2>
  <table>
    <thead><tr><th>id</th><th>名称</th><th>泳道</th><th>类型</th><th>起</th>
      <th>天</th><th>状态</th><th>备注</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</main>
<script>{_JS}</script>
</body>
</html>
"""


def nodes_lane(rm: Roadmap, nid: str) -> str:
    return next(n.lane for n in rm.nodes if n.id == nid)


def render_markdown_table(rm: Roadmap) -> str:
    starts = schedule(rm)
    out = [
        "| id | 名称 | 泳道 | 起 | 天 | 状态 | 备注 |",
        "|---|---|---|---|---|---|---|",
    ]
    for n in sorted(rm.nodes, key=lambda n: (starts[n.id], n.id)):
        lane = next(l.title for l in rm.lanes if l.id == n.lane)
        kind = "◆" if n.kind == "milestone" else ""
        out.append(
            f"| `{n.id}`{kind} | {n.label} | {lane} | {starts[n.id].isoformat()} | "
            f"{n.days or '—'} | {STATUS_LABEL[n.status]} | "
            f"{n.note + ' ' if n.note else ''}|"
        )
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 when the on-disk HTML differs from a fresh render")
    ap.add_argument("--today", default=None,
                    help="override today's date for a reproducible render")
    ap.add_argument("--table", action="store_true",
                    help="print the Markdown task table instead of writing HTML")
    args = ap.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    out = args.out or os.path.join(root, "docs", "roadmap-gantt.html")
    today = _d(args.today) if args.today else _dt.date.today()

    if args.table:
        print(render_markdown_table(_ROADMAP))
        return 0

    rendered = render_html(_ROADMAP, today)
    if args.check:
        if not os.path.exists(out):
            print(f"stale: {out} does not exist", file=sys.stderr)
            return 1
        with open(out, encoding="utf-8") as fh:
            on_disk = fh.read()
        # The today marker is the only date-dependent part; ignore it so the
        # check stays meaningful on a later calendar day.
        strip = lambda s: "\n".join(
            ln for ln in s.splitlines()
            if "today" not in ln.lower()
        )
        if strip(on_disk) != strip(rendered):
            print(f"stale: {out} differs from a fresh render", file=sys.stderr)
            return 1
        print(f"fresh: {out}")
        return 0

    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(rendered)
    print(f"wrote {out} ({len(rendered)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
