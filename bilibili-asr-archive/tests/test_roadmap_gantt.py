"""The roadmap Gantt must not drift from the data model that produces it.

`docs/roadmap-gantt.html` and the generated table inside `docs/roadmap-gantt.md`
are both rendered from `scripts/build_roadmap_gantt.py`'s `_ROADMAP`. This test
holds the two halves of that contract:

1. the committed HTML equals a fresh render (a hand-edited diagram is a defect —
   the previous Mermaid version drifted from the prose precisely because the two
   were maintained separately);
2. the Markdown table block equals the generator's own output.

It also pins the *semantic* properties the diagram exists to communicate, so a
future edit cannot quietly reintroduce a waterfall reading:

* every lane has at least one exit milestone;
* milestones within a lane are emitted in chronological order (a later milestone
  drawn above an earlier one reads as a schedule running backwards);
* every cross-lane dependency is visible as a gate connector;
* nothing is rendered outside the viewBox.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "build_roadmap_gantt.py"
HTML = REPO / "docs" / "roadmap-gantt.html"
MD = REPO / "docs" / "roadmap-gantt.md"

#: Fixed so the render is reproducible; `today` only draws a marker line.
FROZEN_TODAY = "2026-10-04"


def _load_script():
    """Import the generator by path (it is a script, not an installed module)."""
    spec = importlib.util.spec_from_file_location("build_roadmap_gantt", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen():
    return _load_script()


def test_committed_html_matches_a_fresh_render(gen):
    """A hand-edited diagram is a defect: regenerate instead of patching."""
    fresh = gen.render_html(gen._ROADMAP, dt.date.fromisoformat(FROZEN_TODAY))
    on_disk = HTML.read_text(encoding="utf-8")

    # Drop the today marker: it is the only date-dependent element, and this
    # test should keep passing tomorrow.
    strip = lambda s: "\n".join(
        ln for ln in s.splitlines() if "today" not in ln.lower()
    )
    assert strip(on_disk) == strip(fresh), (
        "docs/roadmap-gantt.html is stale — run "
        "`python3 scripts/build_roadmap_gantt.py`"
    )


def test_markdown_table_matches_the_generator(gen):
    block = re.search(
        r"<!-- BEGIN GENERATED: build_roadmap_gantt\.py --table -->\n(.*?)\n"
        r"<!-- END GENERATED -->",
        MD.read_text(encoding="utf-8"),
        re.S,
    )
    assert block, "docs/roadmap-gantt.md lost its generated-table markers"
    assert block.group(1).strip() == gen.render_markdown_table(gen._ROADMAP).strip()


def test_every_lane_has_an_exit_milestone(gen):
    """A lane without an exit cannot be said to be done."""
    lanes_with_milestones = {
        n.lane for n in gen._ROADMAP.nodes if n.kind == "milestone"
    }
    assert lanes_with_milestones == {lane.id for lane in gen._ROADMAP.lanes}


def test_milestones_render_in_chronological_order(gen):
    """A later milestone drawn above an earlier one reads as time running backwards."""
    svg = gen.render_svg(gen._ROADMAP, dt.date.fromisoformat(FROZEN_TODAY))
    found = re.findall(
        r'data-node="(m-[a-z0-9]+)">.*?<text class="ms-label" x="([\d.]+)" '
        r'y="([\d.]+)"',
        svg,
        re.S,
    )
    assert found, "no milestone labels found in the rendered SVG"

    starts = gen.schedule(gen._ROADMAP)
    by_lane: dict[str, list[tuple[float, str]]] = {}
    lanes = {n.id: n.lane for n in gen._ROADMAP.nodes}
    for mid, x, y in found:
        by_lane.setdefault(lanes[mid], []).append((float(y), starts[mid].isoformat()))

    for lane, items in by_lane.items():
        ordered = sorted(items)
        dates = [d for _, d in ordered]
        assert dates == sorted(dates), (
            f"lane {lane!r} draws its milestones out of chronological order: "
            f"{dates}"
        )


def test_every_cross_lane_dependency_is_drawn_as_a_gate(gen):
    """The gate connectors are derived, so losing one means losing information."""
    svg = gen.render_svg(gen._ROADMAP, dt.date.fromisoformat(FROZEN_TODAY))
    drawn = svg.count('class="gate"')

    lanes = {n.id: n.lane for n in gen._ROADMAP.nodes}
    expected = sum(
        1
        for n in gen._ROADMAP.nodes
        for dep in n.after
        if lanes[dep] != n.lane
    )
    assert drawn == expected, (
        f"{expected} cross-lane dependencies exist but {drawn} gates were drawn"
    )


def test_no_rendered_text_escapes_the_viewbox(gen):
    """Clipped labels hide exactly what the diagram exists to show."""
    svg = gen.render_svg(gen._ROADMAP, dt.date.fromisoformat(FROZEN_TODAY))
    width, height = (
        float(v)
        for v in re.search(r'viewBox="([^"]+)"', svg).group(1).split()[2:]
    )

    for m in re.finditer(
        r'<text class="([a-z-]+(?: outside)?)" x="([\d.]+)" y="([\d.]+)">'
        r"([^<]*)</text>",
        svg,
    ):
        cls, x, y, text = m.group(1), float(m.group(2)), float(m.group(3)), m.group(4)
        size = {"ms-label": 10.5, "axis": 11.0, "today-label": 10.0}.get(cls, 11.5)
        reach = x + gen._text_px(text, size)
        assert reach <= width, (
            f"{cls} label {text!r} reaches {reach:.0f}px, "
            f"past the {width:.0f}px viewBox"
        )
        assert y <= height, (
            f"{cls} label {text!r} sits at y={y:.0f}, "
            f"below the {height:.0f}px viewBox"
        )


def test_generator_check_flag_agrees_with_the_committed_file(gen):
    """`--check` is how CI (and a human) will notice drift; it must work."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check", "--today", FROZEN_TODAY],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"--check reported the artifact stale:\n{result.stdout}{result.stderr}"
    )
