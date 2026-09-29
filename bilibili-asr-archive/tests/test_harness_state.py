# -*- coding: utf-8 -*-
"""The harness-state checker: four legs, and the falsifier each one reaches.

`scripts/validate_harness_state.py` validates every engine-read lifecycle
document under a harness dir by delegating to the engine's own validators, plus
a fourth leg that holds the published-set boundary (compass D11) as a ratchet
over tracked paths. This file runs it against the real harness and against
scratch fixtures.

**Why the negative controls are the point.** Every leg here is an *absence*
assertion — "no document is in a violating shape", "no tracked path is outside
the published set" — and per
`{KNOWLEDGE_DIR}/testing-patterns/absence-assertion-negative-control.md` an
absence assertion is evidence only when the fixture can reach the falsifier.
So each leg gets a control that injects the thing it negates and asserts the
leg goes red *naming it*:

  - ratchet, half one: a force-added path outside the published set → red
    (this is the condition that produced the 11, `git add -f` against
    `.mstar/**`; without the control the leg is an assertion that cannot fail);
  - ratchet, half two: a fixture path on the frozen debt list → green. Without
    this half, "the ratchet works" and "the check is simply off" are
    indistinguishable;
  - register: an out-of-enum `lifecycle` entry → red, with the engine's own
    message;
  - fail-loud: an engine that cannot be reached → `NOT-VALIDATED`, never a
    silent pass.

**The register's expectation is deliberately not "clean".** The live register
currently fails the engine's `validateProjectRegister` rules (144 violations;
Task 2 of `20260928-harness-state-contract` corrects it in place and lands it
through `mstar persist residuals`). So the live cases assert what the leg
actually promises — that it *reaches the engine's reader and reports the
engine's verdict faithfully* — and the exit-0 assertion activates the moment
the engine's verdict is clean, which is Task 2's whole job. Encoding today's
red state as the expectation would make the test celebrate the defect; asserting
today's clean state would make it red on arrival.
"""

from __future__ import annotations

import ast
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

TESTS_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = TESTS_DIR.parent
REPO_ROOT = PACKAGE_ROOT.parent

# The brief's discovery rule: the harness dir sits two levels up from the
# package, i.e. `../../.mstar`. In a git worktree that path holds only the
# tracked (published) subset — the engine documents are gitignored local
# process artifacts and live on the control root only — so the engine legs
# degrade to their explicit "nothing to validate" note there rather than
# silently passing. Cases say which of the two they are looking at.
HARNESS_DIR = REPO_ROOT / ".mstar"
CHECKER = PACKAGE_ROOT / "scripts" / "validate_harness_state.py"
# The checker source is data for the citation guard: its docstrings are the
# claims being verified.
_CHECKER_SOURCE = CHECKER


def _load_checker():
    """Import the checker so the controls read the debt list through its parser.

    The fixture controls must not re-implement the symbol expansion: a second
    copy could drift from the one the checker uses, and then the control would
    prove something about the test rather than about the tool.
    """
    spec = importlib.util.spec_from_file_location("validate_harness_state", CHECKER)
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves field annotations through sys.modules[__module__],
    # so the module must be registered before exec_module runs.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker() if CHECKER.is_file() else None

# The register must hold ZERO engine violations. This was a 144-violation ceiling
# while Task 2 was pending (the pre-Task-2 count, which could only shrink); Task 2
# has landed and the register validates clean, so the guard is now exact. A
# ceiling would not guard: a regression 0 -> 1 satisfies `1 <= 144`, so the very
# failure this assertion exists to catch would pass. Verified by mutating a live
# register entry to `lifecycle: "closed"` and confirming this fails.
REGISTER_VIOLATION_CEILING = 0

# Every separator `str.splitlines()` splits on, and the printable spelling the
# checker substitutes. A path may hold any of them, so the controls below drive
# all of them: a class proven on `\n` alone is not proven, and the checker's own
# escape set once shared that blind spot with the assertion reading its output.
_LINE_SEPARATORS = ("\n", "\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029")
_SEPARATOR_SPELLINGS = {
    "\t": "\\t",
    "\n": "\\n",
    "\r": "\\r",
    "\x0b": "\\x0b",
    "\x0c": "\\x0c",
    "\x1c": "\\x1c",
    "\x1d": "\\x1d",
    "\x1e": "\\x1e",
    "\x85": "\\x85",
    "\u2028": "\\u2028",
    "\u2029": "\\u2029",
}
# One splitter covering the class, so a leak of any separator is visible to a
# reader that treats any of them as a break rather than only `\n`.
_ALL_SEPARATOR_SPLIT_RE = r"[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]"


def _separator_spelling(separator: str) -> str:
    """The escaped form the checker must emit for `separator`.

    `separator` is first put through the same universal-newline decoding the
    checker's own subprocess reads get (`text=True`): a path holding `\\r` is
    handed to `git ls-files` as `\\r` and decoded back as `\\n`, so the spelling
    the checker can emit for a CR path is `\\n`. Asserting `\\r` here would fail
    on correct behaviour — and the raw-separator assertion below still covers
    the CR case, because that decoded `\\n` must not survive unescaped either.
    """
    decoded = separator.replace("\r\n", "\n").replace("\r", "\n")
    return _SEPARATOR_SPELLINGS[decoded]

_DOC_RE = re.compile(r"^\[(?P<leg>[a-z-]+)\] (?P<state>OK|FAIL|NOT-VALIDATED) (?P<rest>.*)$")
_SUMMARY_RE = re.compile(r"^summary: (?P<body>.*)$")


class DocumentLine:
    def __init__(self, leg: str, state: str, rest: str) -> None:
        self.leg = leg
        self.state = state
        if state == "FAIL":
            target, _, tail = rest.rpartition(":")
            self.target = target
            match = re.match(r"\s*(\d+) violations", tail)
            self.count = int(match.group(1)) if match else None
        else:
            self.target = rest
            self.count = None


class CheckerRun:
    """The checker's stdout, parsed into the four legs' verdicts."""

    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.documents = [
            DocumentLine(m.group("leg"), m.group("state"), m.group("rest"))
            for m in (_DOC_RE.match(line) for line in stdout.splitlines())
            if m
        ]
        self.notes = [
            line for line in stdout.splitlines() if re.match(r"^\[[a-z-]+\] note ", line)
        ]
        self.counters: dict[str, int] = {}
        self.summary = ""
        for line in stdout.splitlines():
            match = _SUMMARY_RE.match(line)
            if match:
                self.summary = match.group("body")
                self.counters = {
                    k: int(v) for k, v in re.findall(r"([a-z][a-z-]*)=(\d+)", match.group("body"))
                }

    def leg(self, leg: str) -> list[DocumentLine]:
        return [d for d in self.documents if d.leg == leg]

    def failing(self) -> list[DocumentLine]:
        return [d for d in self.documents if d.state == "FAIL"]

    @property
    def text(self) -> str:
        return self.stdout + self.stderr


def _require_checker() -> None:
    assert CHECKER.is_file(), (
        f"the checker is missing at {CHECKER} — the file this suite exists to exercise is not in the tree"
    )


def _require_engine() -> None:
    _require_checker()
    if shutil.which("mstar") is None:
        pytest.skip(
            "the engine CLI `mstar` is not on PATH, and the checker refuses to validate any "
            "document without it (by design: an unreachable engine is reported NOT-VALIDATED, never "
            "a silent pass). Install @mstar-harness/cli to run the engine-backed legs."
        )


def _require_harness() -> None:
    if not HARNESS_DIR.is_dir():
        pytest.skip(
            f"the harness dir is not reachable at {HARNESS_DIR} (the package expects it two levels up, "
            "`../../.mstar`); there is nothing to validate in this checkout"
        )


def _run_checker(harness: Path, *, env: dict[str, str] | None = None) -> CheckerRun:
    completed = subprocess.run(
        [sys.executable, str(CHECKER), str(harness)],
        cwd=str(PACKAGE_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    return CheckerRun(completed.returncode, completed.stdout, completed.stderr)


def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True, timeout=120)


def _refusal_segments(stderr: str) -> list[str]:
    """The engine's own register violations, split on its `'; '` join.

    `validatePersistPayload` joins per-violation text with `"; "` and prefixes
    the refusal prologue (installed CLI `mstar-harness.js:24847-24848`), so this
    is the engine's *structure*, not a regex over its prose — an instrument
    independent of the checker's own counting, which is the point.
    """
    prologue = "refusing to persist invalid residuals document: "
    assert prologue in stderr, (
        f"the engine did not refuse with its own prologue, so its count is not readable here:\n{stderr}"
    )
    return [segment for segment in stderr.split(prologue, 1)[1].split("; ") if segment.strip()]


def _engine_register_violations(harness: Path, key: str) -> list[str]:
    env = {**os.environ, "MSTAR_HARNESS_DIR": str(harness)}
    completed = subprocess.run(
        # Bound form (`--key=<k>`), matching the checker: a bare `--key` makes the
        # engine read the next token as a top-level option, so a hostile key would
        # have made this oracle agree with the very bug it exists to detect.
        ["mstar", "persist", "get", "--validate", "residuals", f"--key={key}"],
        cwd=str(harness),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 1, (
        f"precondition: the fixture register must be refused by the engine, got exit "
        f"{completed.returncode}:\n{completed.stdout}{completed.stderr}"
    )
    return _refusal_segments(completed.stderr)


def _engine_status_header_count(path: Path) -> int:
    """The engine's own violation count for a status/snapshot document."""
    completed = _run(["mstar", "status", "validate", str(path)], cwd=PACKAGE_ROOT)
    match = re.search(r"FAIL \((\d+) violations?\)", completed.stdout + completed.stderr)
    assert match, f"the engine reported no violation header for {path}:\n{completed.stderr}"
    return int(match.group(1))


# --------------------------------------------------------------------------
# live harness
# --------------------------------------------------------------------------


def test_live_harness_snapshots_pass_the_engine():
    """Leg (a): every `workflows/*/snapshot.json` is engine-valid."""
    _require_harness()
    _require_engine()
    run = _run_checker(HARNESS_DIR)
    documents = run.leg("snapshots")
    assert not [d for d in documents if d.state != "OK"], (
        "a workflow snapshot failed the engine's `status validate`:\n" + run.text
    )
    if not documents:
        assert any("workflows/" in note for note in run.notes), (
            "a leg with no documents must say so — silence here is the silent pass this checker "
            "exists to prevent:\n" + run.text
        )
        pytest.skip(
            f"{HARNESS_DIR} holds no workflows/*/snapshot.json — this checkout carries the published "
            "subset only (engine documents are gitignored local process artifacts; the control root "
            "has them). The leg's engine path is exercised by the fixture cases below."
        )


def test_live_harness_root_register_passes_the_engine():
    """Leg (b): `status.json` is engine-valid."""
    _require_harness()
    _require_engine()
    run = _run_checker(HARNESS_DIR)
    documents = run.leg("status")
    assert not [d for d in documents if d.state != "OK"], (
        "the root register failed the engine's `status validate`:\n" + run.text
    )
    if not documents:
        assert any("status.json" in note for note in run.notes), (
            "a leg with no documents must say so:\n" + run.text
        )
        pytest.skip(
            f"{HARNESS_DIR} holds no status.json — this checkout carries the published subset only. "
            "The leg's engine path is exercised by the fixture cases below."
        )


def test_live_harness_register_leg_reports_the_engine_verdict():
    """Leg (c): the register leg surfaces the engine's own verdict, verbatim.

    The promise under test is *faithful delegation*, not a clean bill: the
    register currently fails the engine's rules and Task 2
    (`20260928-harness-state-contract`) is what corrects it. This case calls
    the engine reader itself and requires the checker to agree with it, so it is
    green both before and after Task 2 — and the `count` ceiling keeps a
    regression visible in the meantime.
    """
    _require_harness()
    _require_engine()
    projects = HARNESS_DIR / "projects"
    registers = sorted(projects.glob("*/residuals.json")) if projects.is_dir() else []
    if not registers:
        pytest.skip(
            f"{HARNESS_DIR} holds no projects/*/residuals.json — this checkout carries the published "
            "subset only. The register leg's engine path is exercised by the fixture case below."
        )

    run = _run_checker(HARNESS_DIR)
    reported = {d.target: d for d in run.leg("registers")}
    assert len(reported) == len(registers), (
        f"the checker reported {len(reported)} register(s), the harness has {len(registers)}:\n" + run.text
    )

    total_engine_violations = 0
    for path in registers:
        key = path.parent.name
        rel = f"projects/{key}/residuals.json"
        # The engine reader is the authority; ask it directly, the same way the
        # checker is required to (`mstar status validate <register>` misroutes
        # and reports `status.migration-required`, which is why this one call is
        # the leg's whole reason to exist).
        env = dict(os.environ)
        env["MSTAR_HARNESS_DIR"] = str(HARNESS_DIR)
        engine = subprocess.run(
            ["mstar", "persist", "get", "--validate", "residuals", f"--key={key}"],
            cwd=str(HARNESS_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert engine.returncode in (0, 1), (
            f"the engine reader exited {engine.returncode} on {rel}, which is neither a clean verdict "
            f"nor a violation list:\n{engine.stdout}{engine.stderr}"
        )

        document = reported[rel]
        if engine.returncode == 0:
            assert document.state == "OK", (
                f"the engine validated {rel} but the checker reported {document.state} — the leg is "
                "not reporting the engine's verdict:\n" + run.text
            )
        else:
            assert document.state == "FAIL", (
                f"the engine refused {rel} but the checker reported {document.state} — a violating "
                "document must not pass:\n" + run.text
            )
            # Every violation code the engine named must appear in the report:
            # the delegation is only faithful if the engine's findings survive
            # into the output the operator reads.
            codes = set(re.findall(r"\[(?:critical|high|medium|low|nit)\]\s+([A-Za-z0-9_.-]+):", engine.stderr))
            for code in codes:
                assert code in run.text, (
                    f"the engine reported {code} on {rel} but the checker's output does not carry it:\n"
                    + run.text
                )

        total_engine_violations += len(
            re.findall(r"\[(?:critical|high|medium|low|nit)\]\s+[A-Za-z0-9_.-]+:", engine.stderr)
        )

    assert total_engine_violations == REGISTER_VIOLATION_CEILING, (
        f"the register carries {total_engine_violations} engine violations, expected "
        f"{REGISTER_VIOLATION_CEILING} — Task 2 drove it to zero, so any count above zero is a "
        "regression to a violating shape, and this assertion is exact rather than a ceiling "
        "precisely so that a 0 -> 1 regression cannot slip through."
    )


def test_live_harness_ratchet_holds_the_published_set():
    """Leg (d): no tracked harness path is outside the published set."""
    _require_harness()
    _require_checker()
    run = _run_checker(HARNESS_DIR)
    documents = run.leg("ratchet")
    assert len(documents) == 1, "the ratchet leg reports exactly one document:\n" + run.text
    assert documents[0].state == "OK", (
        "a tracked path outside the published set is not on the frozen debt list:\n" + run.text
    )
    counters = run.counters
    assert counters["new-out-of-set"] == 0, run.text
    assert counters["published"] + counters["frozen-debt"] == counters["tracked"], (
        "every tracked path is published or frozen debt, nothing unclassified:\n" + run.text
    )
    if counters["published"] == 0:
        pytest.skip(
            f"{HARNESS_DIR} tracks no published path at all — nothing for the boundary to hold "
            "(the fixture cases below exercise the ratchet itself)."
        )


def test_live_harness_run_matches_its_per_document_verdicts():
    """The whole-run exit code is a function of the per-document verdicts.

    Today the register's engine verdict is dirty, so the run exits 1 and the
    register must be the *only* failing document — a snapshot or the root
    register failing here is a regression, not the known register debt. Once
    Task 2 lands, the engine's verdict on the register is clean and this case's
    first branch asserts the brief's exit 0 over the real harness. That flip is
    the point of writing the expectation on the engine's verdict rather than on
    today's state.
    """
    _require_harness()
    _require_engine()
    run = _run_checker(HARNESS_DIR)
    failing_legs = {d.leg for d in run.failing()}
    assert failing_legs <= {"registers"}, (
        "only the register leg may be failing before Task 2 corrects the register; snapshots, the "
        "root register and the ratchet are expected clean:\n" + run.text
    )
    assert run.counters["fail"] == len(run.failing()), (
        "the summary's fail count must equal the failing document lines:\n" + run.text
    )
    if not failing_legs:
        assert run.returncode == 0, "no failing document, yet the run did not exit 0:\n" + run.text
    else:
        assert run.returncode == 1, (
            "a failing document must make the run exit 1 (0 = clean, 1 = violation, 2 = usage):\n"
            + run.text
        )
        assert run.counters["not-validated"] == 0, (
            "an unreachable document is a failure in its own right and must not be mixed into the "
            "violation count:\n" + run.text
        )


# --------------------------------------------------------------------------
# scratch fixtures — the negative controls
# --------------------------------------------------------------------------


@pytest.fixture
def scratch_harness(tmp_path: Path) -> Path:
    """A minimal, engine-clean git repo with a harness dir `./.mstar`.

    The engine documents are written to disk but deliberately left *untracked*,
    exactly as they are in the real repository: `git ls-files .mstar` never
    lists `workflows/`, `status.json` or `projects/` (they are gitignored local
    process artifacts), so the ratchet's tracked set is the published subset and
    a control that force-adds one path is the whole falsifier.
    """
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH, so the tracked-set leg cannot be exercised")
    if shutil.which("mstar") is None:
        pytest.skip("the engine CLI `mstar` is not on PATH, so the routed legs cannot be exercised")

    harness = tmp_path / ".mstar"
    (harness / "workflows" / "w1").mkdir(parents=True)
    (harness / "projects" / "p1").mkdir(parents=True)
    # The real `.gitignore` and the real AGENTS.md: the fixture must classify
    # against the same rules and the same frozen debt list as the repo, or the
    # controls would prove something about a fiction.
    shutil.copyfile(REPO_ROOT / ".gitignore", tmp_path / ".gitignore")
    shutil.copyfile(HARNESS_DIR / "AGENTS.md", harness / "AGENTS.md")
    (harness / "workflows" / "w1" / "snapshot.json").write_text(
        '{"schema_version": 1, "id": "w1", "type": "plan", "status": "completed",'
        ' "started_at": "2026-01-01", "updated_at": "2026-01-01", "ended_at": "2026-01-01", "plans": []}\n',
        encoding="utf-8",
    )
    (harness / "status.json").write_text(
        '{"version": 2, "updated_at": "2026-01-01", "workflows": []}\n', encoding="utf-8"
    )
    (harness / "projects" / "p1" / "residuals.json").write_text(
        '{"entries": {"p1": [{"id": "R1", "title": "t", "severity": "low", "source": "s",'
        ' "scope": "sc", "decision": "defer", "owner": "o", "target": null, "tracking": null,'
        ' "source_plan": "p1", "registered_at": "2026-01-01"}]}}\n',
        encoding="utf-8",
    )
    _run(["git", "init", "-q", "."], cwd=tmp_path)
    # `-A` alone tracks only the un-ignored `.mstar/AGENTS.md`, which is the
    # real repository's shape for the fixture's file set.
    _run(["git", "add", "-A"], cwd=tmp_path)
    return harness


def _force_add(harness: Path, relative: str, content: str = "x\n") -> Path:
    path = harness / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    completed = _run(["git", "add", "-f", str(path.relative_to(harness.parent))], cwd=harness.parent)
    assert completed.returncode == 0, f"the fixture could not force-add {relative}: {completed.stderr}"
    return path


def test_scratch_fixture_is_green_before_any_control(scratch_harness: Path):
    """The controls below are only evidence if the fixture starts green."""
    run = _run_checker(scratch_harness)
    assert run.returncode == 0, "the fixture must be engine-clean before a control falsifies it:\n" + run.text
    assert run.counters["snapshots"] == 1 and run.counters["registers"] == 1, run.text


def test_new_out_of_set_tracked_path_fails_the_ratchet(scratch_harness: Path):
    """Control, ratchet half one: a force-added out-of-set path goes red.

    This is the falsifier the leg exists to reach — `git add -f` against
    `.mstar/**` — and the case also pins *why* the leg reads
    `git check-ignore --no-index`: the plain form is masked by the index and
    reports nothing for exactly this path.
    """
    leak = _force_add(scratch_harness, "plans/20260101-leak.md")
    relative = str(leak.relative_to(scratch_harness.parent))

    # The masking this leg must not fall for, asserted rather than assumed:
    # tracked + ignored means the plain form is silent.
    bare = _run(["git", "check-ignore", relative], cwd=scratch_harness.parent)
    assert bare.returncode == 1 and bare.stdout.strip() == "", (
        "precondition: a tracked, force-added path is masked in the index — the plain "
        f"`git check-ignore` form must report nothing, got {bare.stdout!r}"
    )
    no_index = _run(["git", "check-ignore", "--no-index", "-v", relative], cwd=scratch_harness.parent)
    assert no_index.returncode == 0 and relative in no_index.stdout, (
        f"--no-index must surface the rule for {relative}, got {no_index.stdout!r}"
    )

    run = _run_checker(scratch_harness)
    assert run.returncode == 1, "a new out-of-set tracked path must fail the leg:\n" + run.text
    assert run.counters["new-out-of-set"] == 1, run.text
    ratchet = run.leg("ratchet")
    assert [d.state for d in ratchet] == ["FAIL"], run.text
    assert relative in run.text, "the leg must name the offending path:\n" + run.text
    assert "frozen debt list" in run.text, "the finding must say why the path is not tolerated:\n" + run.text


def test_frozen_debt_path_is_tolerated_by_the_ratchet(scratch_harness: Path):
    """Control, ratchet half two: a frozen debt path stays green.

    Without this half, "the ratchet works" and "the check is simply off" are
    indistinguishable. The path is read out of the real `.mstar/AGENTS.md`, so
    the case cannot drift from the list the checker reads.
    """
    agents_md = (scratch_harness / "AGENTS.md").read_text(encoding="utf-8")
    symbols = checker.parse_symbol_table(agents_md)
    debt = checker.parse_frozen_debt(agents_md, symbols)
    assert debt, f"no **debt** row resolved from {scratch_harness}/AGENTS.md — the control has no input"
    assert symbols, "the § Path symbols table must resolve, or the debt rows cannot expand"
    # The debt table writes paths from the repository root; the fixture harness
    # is `./.mstar` inside its own repo, so strip that prefix for force-add.
    token = debt[0]
    relative = token.split("/", 1)[1] if token.startswith(".mstar/") else token

    _force_add(scratch_harness, relative)

    run = _run_checker(scratch_harness)
    assert run.returncode == 0, (
        f"the frozen debt path {relative} must be tolerated (the list may only shrink by operator "
        "action, not by this check):\n" + run.text
    )
    assert run.counters["frozen-debt"] == 1, run.text
    assert run.counters["new-out-of-set"] == 0, run.text


def test_iteration_process_face_is_rejected_while_iteration_specs_are_published(scratch_harness: Path):
    """Both classification boundaries, on the paths that actually separate them.

    A package README under `{ITERATION_DIR}` is the iteration *process* face,
    which D11 keeps local — a bare `iterations/` prefix would wrongly pass it.
    (The specific index file `{ITERATION_DIR}/README.md` cannot carry this case:
    it is also one of the six frozen debt paths, so its tolerance proves the
    debt list, not the prefix boundary. `test_frozen_debt_path_is_tolerated_by_
    the_ratchet` is the case that pins it.)

    And `{ITERATION_DIR}/<id>/specs/**` is published *even though `.gitignore`
    still ignores it*, which is why the leg's verdict is the D11 prefix list and
    not "is it ignored": five such drafts are tracked in the real repository
    today, and the amendment that publishes them is intent rather than a
    `.gitignore` rule.
    """
    process_face = _force_add(scratch_harness, "iterations/iter-y/README.md")
    specs_path = _force_add(scratch_harness, "iterations/iter-y/specs/contract.md")

    # Both are ignored by the rules; only one is in the published set. A leg
    # that asked git instead of the prefix list would report the wrong one.
    for path in (process_face, specs_path):
        relative = str(path.relative_to(scratch_harness.parent))
        evidence = _run(["git", "check-ignore", "--no-index", "-v", relative], cwd=scratch_harness.parent)
        assert evidence.returncode == 0, (
            f"precondition: {relative} is ignored by the .gitignore rules, so 'is it ignored' cannot "
            "separate the two paths"
        )

    run = _run_checker(scratch_harness)
    assert run.returncode == 1, "an iteration package README is not published:\n" + run.text
    assert run.counters["new-out-of-set"] == 1, run.text
    assert "iterations/iter-y/README.md" in run.text, run.text
    assert "iterations/iter-y/specs/contract.md" not in run.text, (
        "a published contract draft must not be reported as a finding — git ignoring it is not the "
        "verdict:\n" + run.text
    )
    assert run.counters["published"] == 2, (
        "AGENTS.md and the iteration spec are the two published tracked paths:\n" + run.text
    )


def test_register_violation_is_reported_by_the_register_leg(scratch_harness: Path):
    """Control, register leg: an out-of-enum lifecycle goes red, named.

    The fixture reaches the falsifier: `p1/residuals.json` is clean, the entry
    is changed to `lifecycle: "closed"`, and the engine's reader refuses it —
    so the leg's green verdict above means something.
    """
    baseline = _run_checker(scratch_harness)
    assert baseline.counters["registers"] == 1, baseline.text
    assert baseline.leg("registers")[0].state == "OK", baseline.text

    register = scratch_harness / "projects" / "p1" / "residuals.json"
    register.write_text(
        '{"entries": {"p1": [{"id": "R1", "title": "t", "severity": "low", "source": "s",'
        ' "scope": "sc", "decision": "defer", "owner": "o", "target": null, "tracking": null,'
        ' "source_plan": "p1", "registered_at": "2026-01-01", "lifecycle": "closed"}]}}\n',
        encoding="utf-8",
    )

    run = _run_checker(scratch_harness)
    assert run.returncode == 1, "a violating register must fail the run:\n" + run.text
    documents = run.leg("registers")
    assert [d.state for d in documents] == ["FAIL"], run.text
    assert documents[0].target == "projects/p1/residuals.json", run.text
    assert documents[0].count == 1, "the engine reported exactly one violation:\n" + run.text
    assert "status.residual.invalid-lifecycle" in run.text, (
        "the engine's own violation code must survive into the report:\n" + run.text
    )


def test_unreachable_engine_is_reported_not_silently_passed(scratch_harness: Path):
    """The fail-loud clause: no engine, no silent pass.

    The checker must report `NOT-VALIDATED` and exit non-zero for a document it
    cannot put through the engine's rules — a leg that quietly reports "OK" when
    the validator never ran is the failure mode this whole file is built around.
    """
    stripped = {**os.environ, "PATH": "/nonexistent"}
    run = _run_checker(scratch_harness, env=stripped)
    assert run.returncode == 1, "an unreachable engine must not be a clean run:\n" + run.text
    assert run.counters.get("not-validated", 0) >= 1, (
        "the run reported no NOT-VALIDATED document although no validator could run:\n" + run.text
    )
    assert run.counters.get("ok", 0) == 0, (
        "nothing can be OK when nothing was validated:\n" + run.text
    )
    assert "NOT-VALIDATED" in run.text, run.text


def test_engine_resolution_failure_is_reachable_and_fails_loud(scratch_harness, monkeypatch, capsys):
    """The other half of the engine-resolution contract: `_find_mstar` returns None.

    `_find_mstar` has two steps — `shutil.which("mstar")`, then
    `os.access(MSTAR_FALLBACK, os.X_OK)`. The `PATH=/nonexistent` control above
    only drives the *second*: with `which` blinded, the fallback still resolves
    to the installed `/usr/local/bin/mstar`, so `mstar` is a real path and the
    legs fail later, at execution time. So the `if mstar is None:` branches in
    `_status_validate` (L452) and `_register_validate` (L551) were unreachable
    from this suite — mutating either to return `STATE_OK` left it green (13
    passed, measured), because no test ever entered them.

    This control patches both resolution steps to fail, which is the only way to
    reach that branch, and drives the real entry point (`main`, the same
    function the CLI shim calls) so the exit-code contract is exercised too.
    Running in-process is required rather than incidental: `_run_checker` starts
    a subprocess, and no patched module attribute crosses that boundary, so a
    subprocess control here would silently re-test the *other* branch while
    looking like it tested this one.
    """
    assert checker is not None, "the checker must be importable for this control"
    absent = scratch_harness.parent / "no-such-engine" / "mstar"
    assert not absent.exists(), "precondition: the stand-in fallback must not exist"

    monkeypatch.setattr(checker, "MSTAR_FALLBACK", str(absent))
    monkeypatch.setattr(checker.shutil, "which", lambda _name: None)

    # The precondition that makes this control meaningful: with both steps
    # blinded, resolution itself fails.
    assert checker._find_mstar() is None, (
        "the patched resolution still found an engine, so this control cannot reach the "
        "`mstar is None` branch it exists to cover"
    )

    rc = checker.main([str(scratch_harness)])
    captured = capsys.readouterr()
    text = captured.out + captured.err

    assert rc == 1, "an engine that cannot even be resolved must not be a clean run:\n" + text
    assert "not found on PATH or at" in text, (
        "the run did not report the resolution failure itself, so it did not take the "
        "`mstar is None` branch this control targets:\n" + text
    )
    assert str(absent) in text, (
        "the message must name the fallback the control patched, or it describes a different "
        "resolution attempt than the one under test:\n" + text
    )
    # Every routed document consults the engine, so each leg must be represented
    # as NOT-VALIDATED rather than dropped or passed. Only header lines are read
    # here: detail lines carry the same `[<leg>]` prefix by design, so a plain
    # prefix filter would also swallow the explanation under each verdict.
    verdicts = [m for m in (_DOC_RE.match(line) for line in captured.out.splitlines()) if m]
    by_leg: dict[str, list[str]] = {}
    for match in verdicts:
        by_leg.setdefault(match.group("leg"), []).append(match.group("state"))
    assert by_leg.get("snapshots") == ["NOT-VALIDATED"], (
        f"the snapshots leg must report its document as NOT-VALIDATED without an engine: {by_leg}"
    )
    assert by_leg.get("status") == ["NOT-VALIDATED"], (
        f"the root-register leg must report its document as NOT-VALIDATED without an engine: {by_leg}"
    )
    assert by_leg.get("registers") == ["NOT-VALIDATED"], (
        f"the register leg must report its document as NOT-VALIDATED without an engine: {by_leg}"
    )
    assert by_leg.get("ratchet") == ["OK"], (
        f"the ratchet reads git, not the engine, so it must be unaffected: {by_leg}"
    )
    # The ratchet is the one leg that reads git rather than the engine, so it is
    # also the only document that may report OK here. Anything else being OK
    # would be the silent pass this control exists to catch.
    assert not any(state == "FAIL" for states in by_leg.values() for state in states), (
        f"no document can FAIL when no validator ran: {by_leg}"
    )
    assert by_leg.get("ratchet") == ["OK"], f"the ratchet must be unaffected: {by_leg}"


def test_unreadable_document_is_not_validated_rather_than_failed(scratch_harness: Path):
    """Fail-loud, second form: a document the engine never got to validate.

    This is why the checker keys on the engine's `FAIL (N violations)` header
    rather than on exit 1 alone. `mstar status validate <path>` routes by
    basename (`mstar-harness.js:24482` is the basename test) and then calls
    `readSnapshotForCheck` (L24483): a `snapshot.json` path goes through that
    reader, which **throws** on unreadable JSON and is caught into
    `status validate failed: …` with exit 1 and no report at all. Exit-code
    routing would read that as "1 violation"; the header makes it
    NOT-VALIDATED, which is the honest verdict — no validator ran.

    The falsifier here is reachable by construction: put a directory where the
    snapshot file belongs (the engine answers `EISDIR … read`).
    """
    snapshot = scratch_harness / "workflows" / "w1" / "snapshot.json"
    payload = snapshot.read_text(encoding="utf-8")

    snapshot.unlink()
    snapshot.mkdir()
    try:
        run = _run_checker(scratch_harness)
        documents = run.leg("snapshots")
        assert len(documents) == 1, "the leg enumerates the path it cannot validate:\n" + run.text
        assert documents[0].state == "NOT-VALIDATED", (
            "a document the engine could not read must be NOT-VALIDATED — never FAIL (that invents "
            "a violation) and never OK (that is the silent pass this checker exists to prevent):\n"
            + run.text
        )
        assert run.returncode == 1, "not-validated is a failure:\n" + run.text
        assert run.counters["not-validated"] == 1 and run.counters["fail"] == 0, run.text
    finally:
        if snapshot.is_dir():
            snapshot.rmdir()
        snapshot.write_text(payload, encoding="utf-8")

    restored = _run_checker(scratch_harness)
    assert restored.returncode == 0, "the control must restore the fixture:\n" + restored.text


def test_engine_reported_violation_is_fail_with_its_code(scratch_harness: Path):
    """The contrast case that keeps NOT-VALIDATED from being a catch-all.

    Same leg, same file: remove a field the engine actually validates and the
    engine produces a report, so the leg must say `FAIL`, carry the engine's own
    code, and count from the engine's header — distinct from the unreadable case
    above, which is why that one is a separate verdict rather than "exit 1".
    """
    snapshot = scratch_harness / "workflows" / "w1" / "snapshot.json"
    payload = snapshot.read_text(encoding="utf-8")
    # `ended_at` is required for a terminal snapshot (`validateWorkflowSnapshot`,
    # installed CLI `mstar-harness.js:3642`); dropping it is a real violation.
    mutated = re.sub(r',\s*"ended_at": "[^"]*"', "", payload)
    assert mutated != payload, "precondition: the fixture snapshot carries ended_at to remove"
    snapshot.write_text(mutated, encoding="utf-8")

    try:
        run = _run_checker(scratch_harness)
        documents = run.leg("snapshots")
        assert len(documents) == 1, run.text
        assert documents[0].state == "FAIL", run.text
        assert documents[0].count == 1, "the count comes from the engine's own header:\n" + run.text
        assert "workflow.snapshot.missing-ended-at" in run.text, (
            "the engine's violation code must survive into the report:\n" + run.text
        )
        assert run.counters["not-validated"] == 0, run.text
    finally:
        snapshot.write_text(payload, encoding="utf-8")

    restored = _run_checker(scratch_harness)
    assert restored.returncode == 0, "the control must restore the fixture:\n" + restored.text


def _forged_snapshot_report_decoy(harness: Path, name: str, content: str) -> Path:
    """Put `content` where a `snapshot.json` belongs, under a decoy directory.

    Returns the decoy directory. Both halves are document-controlled names: the
    directory name is the count-bearing text, the file is what the engine tries
    to read. Used by the two controls below.
    """
    snapshot = harness / "workflows" / name / "snapshot.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text(content, encoding="utf-8")
    return snapshot.parent


@pytest.mark.parametrize("separator", _LINE_SEPARATORS, ids=lambda s: repr(s))
def test_a_separator_in_a_path_cannot_hide_a_real_violation(tmp_path: Path, separator: str):
    """F1: the anchor must survive a separator in the *path* it is anchored to.

    The anchor for legs (a) and (b) is the engine's own `<path>: FAIL (N
    violations)` header, and the path is document-chosen — so the anchor is only
    as good as its tolerance for what a path may hold. Taking element 0 of
    `str.splitlines()` reads the header's *prefix* whenever the path carries one
    of the separators `splitlines()` splits on, the full-header match then fails,
    and the checker reports `NOT-VALIDATED` for a document the engine reported a
    real violation for. That is a false negative on a real violation: the run
    still exits 1, but the summary says `fail=0 not-validated=1` and the operator
    is told the opposite of what the engine said. The engine writes exactly one
    terminator, `\\n`, so the header scan must use exactly that.

    Both legs are driven because both were affected: (a) a workflow dir holding
    the separator, (b) a harness dir holding it with a v1 root register. The
    expectation is the engine's own verdict, read from the engine first — so this
    cannot pass by the fixture ceasing to be a violation.
    """
    harness = tmp_path / "leg" / f"h{separator}x" / ".mstar"
    _build_harness_at(harness)
    # Leg (a): a `Done`-status snapshot row missing a field the engine validates.
    (harness / "workflows" / "w1" / "snapshot.json").write_text(
        '{"schema_version": 1, "id": "w1", "type": "plan", "status": "completed",'
        ' "started_at": "2026-01-01", "updated_at": "2026-01-01", "plans": []}\n',
        encoding="utf-8",
    )
    # Leg (b): a v1 root register, which the engine reports as a real violation.
    (harness / "status.json").write_text(
        '{"version": 1, "updated_at": "2026-01-01", "plans": []}\n', encoding="utf-8"
    )

    snapshot_expected = _engine_status_header_count(harness / "workflows" / "w1" / "snapshot.json")
    register_expected = _engine_status_header_count(harness / "status.json")
    assert snapshot_expected >= 1 and register_expected >= 1, (
        "precondition: both documents must hold a real engine violation, got "
        f"{snapshot_expected} and {register_expected}"
    )

    # Leg (c), the register: the same separator sits in the harness dir the
    # engine reader is pinned to. This leg's anchor is the engine's first bytes,
    # ahead of every path it echoes, so it must stay immune — the docstring says
    # so, which is a claim that needs this control.
    (harness / "projects" / "p1" / "residuals.json").write_text(
        '{"entries": {"p1": [{"id": "R1", "title": "t", "severity": "low", "source": "s",'
        ' "scope": "sc", "decision": "defer", "owner": "o", "target": null, "tracking": null,'
        ' "source_plan": "p1", "registered_at": "2026-01-01", "lifecycle": "bogus"}]}}\n',
        encoding="utf-8",
    )
    register_leg_expected = len(_engine_register_violations(harness, "p1"))
    assert register_leg_expected >= 1, "precondition: the register fixture must be refused by the engine"

    run = _run_checker(harness)
    for leg, expected in (
        ("snapshots", snapshot_expected),
        ("status", register_expected),
        ("registers", register_leg_expected),
    ):
        documents = run.leg(leg)
        assert len(documents) == 1, run.text
        assert documents[0].state == "FAIL", (
            f"a separator in the path must not turn leg ({leg})'s real violation into "
            f"NOT-VALIDATED (separator {separator!r}):\n" + run.text
        )
        assert documents[0].count == expected, (
            f"leg ({leg}) must report the engine's own {expected} violations:\n" + run.text
        )
    # The three engine-backed legs are what this control is about; the ratchet's
    # own tracked-set decoding is a separate concern (and a separate,
    # pre-existing gap for `\r`), so only these legs' verdicts are asserted.
    assert not [d for d in run.documents if d.leg in ("snapshots", "status", "registers")
                and d.state == "NOT-VALIDATED"], (
        "no document under test was unreadable — the engine reported a violation for each:\n"
        + run.text
    )


def test_a_verdict_is_never_read_out_of_text_a_document_controls(scratch_harness: Path):
    """F1: the count must be the engine's, not a number the document chose.

    This is the critical one. The engine's own header carries the count and it
    carries a *path* that the document's name partly determines — so a directory
    named `FAIL (3 violations)` puts a count-shaped string into the very text
    the verdict is derived from. A checker that searches the output for
    `FAIL (N violations)` anywhere reads 3 from the directory name; one that
    reads the second header of `…/FAIL (3 violations)/snapshot.json: FAIL (1
    violation)` … also reads the decoy. Only anchoring the *whole* line to the
    exact path this leg handed the engine — which consumes the decoy as part of
    the path — recovers the engine's real number, and here the engine produced
    no number at all (the file is unreadable), so the honest verdict is
    NOT-VALIDATED.

    Both decoys below were reproduced against the committed checker before the
    fix; each reported `FAIL … 3 violations` / `FAIL … 1 violations` for a
    document no validator ever saw.
    """
    payload = (scratch_harness / "workflows" / "w1" / "snapshot.json").read_text(encoding="utf-8")
    (scratch_harness / "workflows" / "w1" / "snapshot.json").unlink()

    # Decoy one: the directory is a directory all the way down, so the engine
    # answers `EISDIR` and emits no header. Truth: NOT-VALIDATED.
    decoy_one = _forged_snapshot_report_decoy(scratch_harness, "FAIL (3 violations)", "")
    try:
        run = _run_checker(scratch_harness)
        documents = run.leg("snapshots")
        assert len(documents) == 1, run.text
        assert documents[0].state == "NOT-VALIDATED", (
            "the count in a directory name must not become the verdict:\n" + run.text
        )
        assert run.counters["fail"] == 0, (
            "no FAIL may be reported for a document the engine never validated:\n" + run.text
        )
        assert run.returncode == 1, "not-validated is a failure:\n" + run.text
    finally:
        shutil.rmtree(decoy_one)

    # Decoy two: same idea, but the decoy count is 1 and the file holds invalid
    # JSON whose head is a violation-shaped token — the shape that also forged
    # agreement between a header count and the number of violation-shaped lines
    # (so a "count == number of tokens" reconciliation would accept it too).
    decoy_two = _forged_snapshot_report_decoy(
        scratch_harness, "FAIL (1 violations)", '[low] a: x {"b": 1'
    )
    try:
        run = _run_checker(scratch_harness)
        documents = run.leg("snapshots")
        assert len(documents) == 1, run.text
        assert documents[0].state == "NOT-VALIDATED", (
            "forged agreement between a header count and violation-shaped lines must not "
            "manufacture a verdict the engine never issued:\n" + run.text
        )
        assert run.counters["fail"] == 0, run.text
        assert run.returncode == 1, run.text
    finally:
        shutil.rmtree(decoy_two)
        (scratch_harness / "workflows" / "w1" / "snapshot.json").write_text(payload, encoding="utf-8")

    restored = _run_checker(scratch_harness)
    assert restored.returncode == 0, "the control must restore the fixture:\n" + restored.text


def test_a_document_cannot_manufacture_a_report_row(scratch_harness: Path):
    """F1, the direction that matters: injected text may not suppress a real FAIL.

    The mirror image of the control above. A violation *message* interpolates
    document keys unquoted — `extra.join(", ")`, `mstar-harness.js:3090` — so a
    key containing a newline plus `  - [low] fake.code: x` makes the engine print
    extra lines that look exactly like its own report rows. That can only ever
    *add* lines, never remove them, so a checker that reconciled "the header
    count" against "the number of violation-shaped lines" would demote a genuine
    FAIL to NOT-VALIDATED the moment a document inflated the second number. The
    real violation below (`coordination.row.field`) is the engine's, and the
    count must stay 1 however many extra rows the document prints.

    Measured before the fix: `FAIL 1 violation` became NOT-VALIDATED once the
    injected key produced three rows.
    """
    snapshot = scratch_harness / "workflows" / "w1" / "snapshot.json"
    payload = snapshot.read_text(encoding="utf-8")
    injected = 'evil\\n  - [low] fake.code: injected\\n  - [low] fake2.code: injected'
    snapshot.write_text(
        '{"schema_version": 1, "id": "w1", "type": "plan", "status": "completed",'
        ' "started_at": "2026-01-01", "updated_at": "2026-01-01", "ended_at": "2026-01-01",'
        ' "plans": [{"id": "p", "title": "t", "file": "f", "status": "Todo",'
        f' "coordination": {{"revision": 1, "{injected}": 1}}}}]}}\n',
        encoding="utf-8",
    )
    try:
        # The engine's own count, read from the engine — the number the checker
        # must reproduce. Asserted first so this control cannot pass by the
        # fixture ceasing to be a FAIL.
        expected = _engine_status_header_count(snapshot)
        assert expected == 1, f"precondition: the engine reports one violation, got {expected}"

        run = _run_checker(scratch_harness)
        documents = run.leg("snapshots")
        assert len(documents) == 1, run.text
        assert documents[0].state == "FAIL", (
            "a genuine engine violation must stay FAIL even when the document prints extra "
            "report-shaped lines:\n" + run.text
        )
        assert documents[0].count == expected, (
            f"the count must be the engine's {expected}, not a number the document influenced:\n"
            + run.text
        )
        assert "coordination.row.field" in run.text, (
            "the engine's real code must survive into the report:\n" + run.text
        )
    finally:
        snapshot.write_text(payload, encoding="utf-8")

    restored = _run_checker(scratch_harness)
    assert restored.returncode == 0, "the control must restore the fixture:\n" + restored.text


def _replace_agents_md(harness: Path, text: str) -> None:
    (harness / "AGENTS.md").write_text(text, encoding="utf-8")


def test_unreadable_frozen_debt_list_is_not_validated(scratch_harness: Path):
    """F3, ratchet branch one: the debt list itself cannot be read.

    The ratchet's verdict depends on `{HARNESS_DIR}/AGENTS.md` — the frozen debt
    list is read from it so the two cannot drift. If that file cannot be read,
    the leg has no debt list, so it cannot decide the boundary, and the honest
    verdict is NOT-VALIDATED rather than "no findings" (which would report a
    clean ratchet while the rules were never applied). The falsifier is reached
    by putting a directory where the file belongs: `read_text` raises `EISDIR`.
    """
    agents = scratch_harness / "AGENTS.md"
    payload = agents.read_text(encoding="utf-8")
    agents.unlink()
    agents.mkdir()
    try:
        run = _run_checker(scratch_harness)
        documents = run.leg("ratchet")
        assert len(documents) == 1, run.text
        assert documents[0].state == "NOT-VALIDATED", (
            "an unreadable debt list must not produce a verdict about the boundary:\n" + run.text
        )
        assert "cannot read the frozen debt list" in run.text, (
            "the leg must name the reason it could not decide:\n" + run.text
        )
        assert run.returncode == 1, "not-validated is a failure:\n" + run.text
        # The boundary counters are *unknown* here, not zero: no debt list means
        # no way to classify a tracked path. Reporting `new-out-of-set=0` would
        # be a claim the leg cannot support, so the counter must be absent
        # rather than defaulted.
        assert "new-out-of-set" not in run.counters, (
            "the leg must not claim zero new out-of-set paths when it never classified any:\n"
            + run.text
        )
    finally:
        agents.rmdir()
        _replace_agents_md(scratch_harness, payload)

    restored = _run_checker(scratch_harness)
    assert restored.returncode == 0, "the control must restore the fixture:\n" + restored.text


def test_failed_tracked_set_query_is_not_validated(scratch_harness: Path):
    """F3, ratchet branch two: `git ls-files` fails, so the tracked set is unknown.

    The ratchet is a statement about the tracked set; if that set cannot be
    listed there is nothing to be a ratchet over. A corrupt `.git/index` makes
    the repository still *look* usable — `rev-parse --show-toplevel` succeeds —
    while `ls-files` fails, which is exactly the state that could otherwise be
    misread as "no tracked paths outside the set".
    """
    index = scratch_harness.parent / ".git" / "index"
    payload = index.read_bytes()
    index.write_bytes(b"garbage-not-an-index")
    try:
        run = _run_checker(scratch_harness)
        documents = run.leg("ratchet")
        assert len(documents) == 1, run.text
        assert documents[0].state == "NOT-VALIDATED", (
            "an unlistable tracked set must not be reported as a clean ratchet:\n" + run.text
        )
        assert "ls-files" in run.text, (
            "the leg must name the failed query, not a generic failure:\n" + run.text
        )
        # Same reasoning as the unreadable-debt-list control: an unlistable
        # tracked set fixes no counters, and a zero here would read as "nothing
        # outside the set" — the exact claim the leg could not check.
        assert "new-out-of-set" not in run.counters and "tracked" not in run.counters, (
            "the leg must not report a classified tracked set it never obtained:\n" + run.text
        )
        assert run.returncode == 1, run.text
    finally:
        index.write_bytes(payload)

    restored = _run_checker(scratch_harness)
    assert restored.returncode == 0, "the control must restore the fixture:\n" + restored.text


def test_a_debt_row_naming_an_absent_symbol_is_not_validated(scratch_harness: Path):
    """F3, ratchet branch three: a debt row names a symbol the table does not define.

    Debt rows are written in symbol form and expanded through the § Path symbols
    table. A row naming an undefined symbol expands to nothing usable, so the
    leg cannot tell whether a tracked path is tolerated. Dropping such a row
    silently would *loosen* the ratchet (the path would look like a new
    finding) or skip it entirely; failing loud is the only honest option.
    """
    agents = scratch_harness / "AGENTS.md"
    payload = agents.read_text(encoding="utf-8")
    mutated = payload.replace(
        "`{PLAN_DIR}/20260927-archive-db-queue-cutover.md`",
        "`{NO_SUCH_SYMBOL}/20260927-archive-db-queue-cutover.md`",
    )
    assert mutated != payload, "precondition: the fixture records that debt row"
    _replace_agents_md(scratch_harness, mutated)
    try:
        run = _run_checker(scratch_harness)
        documents = run.leg("ratchet")
        assert len(documents) == 1, run.text
        assert documents[0].state == "NOT-VALIDATED", (
            "a debt row the table cannot expand must not silently loosen the ratchet:\n" + run.text
        )
        assert "absent from the § Path symbols table" in run.text, run.text
        assert "NO_SUCH_SYMBOL" in run.text, (
            "the leg must name the unresolved row, not just that one exists:\n" + run.text
        )
    finally:
        _replace_agents_md(scratch_harness, payload)

    restored = _run_checker(scratch_harness)
    assert restored.returncode == 0, "the control must restore the fixture:\n" + restored.text


def test_reported_counts_are_the_engines_own_numbers(scratch_harness: Path):
    """F3, the count-fidelity half: a forced count of 1 must not survive.

    Every FAIL line prints a count, and a count is a verdict about how much is
    wrong — a leg that printed a constant 1 would understate a two-violation
    document while looking perfectly healthy. Both count sources are driven here
    and each is asserted against the engine's *own* number, read from the engine
    rather than recomputed by the checker's own logic:

      - snapshot leg: the engine's `FAIL (N violations)` header;
      - register leg: the number of violations the engine joins into its refusal.

    Each fixture is built to hold exactly two violations, so a count forced to 1
    is observably wrong rather than coincidentally right.
    """
    snapshot = scratch_harness / "workflows" / "w1" / "snapshot.json"
    snapshot_payload = snapshot.read_text(encoding="utf-8")
    register = scratch_harness / "projects" / "p1" / "residuals.json"
    register_payload = register.read_text(encoding="utf-8")

    # Two real snapshot violations: `id` and `ended_at` are both required
    # (`validateWorkflowSnapshot`, installed CLI `mstar-harness.js:3642`).
    snapshot.write_text(
        '{"schema_version": 1, "type": "plan", "status": "completed",'
        ' "started_at": "2026-01-01", "updated_at": "2026-01-01", "plans": []}\n',
        encoding="utf-8",
    )
    # Two real register violations: a missing `registered_at` and a
    # `source_plan` that does not match the entries key (`validateProjectRegister`,
    # installed CLI `mstar-harness.js:5123`).
    register.write_text(
        '{"entries": {"p1": [{"id": "R1", "title": "t", "severity": "low", "source": "s",'
        ' "scope": "sc", "decision": "defer", "owner": "o", "target": null, "tracking": null,'
        ' "source_plan": "other"}]}}\n',
        encoding="utf-8",
    )
    try:
        snapshot_expected = _engine_status_header_count(snapshot)
        assert snapshot_expected == 2, (
            f"precondition: the snapshot fixture must hold two violations, engine says "
            f"{snapshot_expected}"
        )
        register_violations = _engine_register_violations(scratch_harness, "p1")
        assert len(register_violations) == 2, (
            f"precondition: the register fixture must hold two violations, engine lists "
            f"{len(register_violations)}: {register_violations}"
        )

        run = _run_checker(scratch_harness)
        snapshots = run.leg("snapshots")
        assert len(snapshots) == 1 and snapshots[0].state == "FAIL", run.text
        assert snapshots[0].count == snapshot_expected, (
            f"the snapshot count must be the engine's {snapshot_expected}, not a constant:\n"
            + run.text
        )
        registers = run.leg("registers")
        assert len(registers) == 1 and registers[0].state == "FAIL", run.text
        assert registers[0].count == len(register_violations), (
            f"the register count must be the engine's {len(register_violations)}, not a constant:\n"
            + run.text
        )
        # The two counts must be independently derived, or one constant would
        # satisfy both assertions above.
        assert snapshots[0].count == registers[0].count == 2, run.text
    finally:
        snapshot.write_text(snapshot_payload, encoding="utf-8")
        register.write_text(register_payload, encoding="utf-8")

    restored = _run_checker(scratch_harness)
    assert restored.returncode == 0, "the control must restore the fixture:\n" + restored.text


def test_the_harness_dir_echo_cannot_split_the_report(tmp_path: Path):
    """F5, the branch the ratchet control cannot reach: the caller-supplied dir.

    `main` echoes the harness dir it was handed on its own report line, and that
    string is *input*, not subprocess output — so it never passes through the
    universal-newline decoding that turns a `\\r` in a git-listed path into `\\n`.
    A CR in the harness dir therefore reaches `_one_line` verbatim, and the
    ratchet control above cannot see it: its hostile separators arrive via
    `git ls-files` and are decoded first. Without this control the CR escape row
    has no consumer, and dropping it splits the report's own first line — and
    every finding line that echoes the dir — into unprefixed fragments.

    Measured with the CR row removed from the checker's escape set: the harness
    line and all six stale-debt notes break at the CR, and this control's
    assertion is what goes red.
    """
    harness = tmp_path / "h\rx" / ".mstar"
    _build_harness_at(harness)

    run = _run_checker(harness)
    lines = re.split(r"\n", run.stdout)
    header = [line for line in lines if line.startswith("harness dir:")]
    assert len(header) == 1, (
        "the harness dir must be echoed on exactly one line even when it holds "
        "a carriage return:\n" + run.text
    )
    assert "h\\rx" in header[0], (
        "the CR in the harness dir must be escaped, not left to break the line:\n" + header[0]
    )
    assert "\r" not in header[0], header[0]

    # The same guarantee for the legs that echo the dir: a raw CR anywhere in
    # the report is a break a parser will see, whatever framing this file uses.
    for splitter in (r"\n", _ALL_SEPARATOR_SPLIT_RE):
        unprefixed = [
            line
            for line in re.split(splitter, run.stdout)
            if line and not re.match(r"^(\[[a-z-]+\]|harness dir:|summary:)", line)
        ]
        assert not unprefixed, (
            f"the harness dir leaked an unprefixed line (split {splitter!r}): {unprefixed}"
        )


@pytest.mark.parametrize("separator", _LINE_SEPARATORS, ids=lambda s: repr(s))
def test_a_path_with_a_newline_cannot_split_its_finding(scratch_harness: Path, separator: str):
    """F5: a finding stays one line even when the path it names contains a separator.

    Paths are document data, not report structure, and git tracks a path
    containing `\\n` without complaint (`git ls-files -z` is NUL-delimited
    precisely because names may hold anything but NUL). Echoing such a path raw
    puts the rest of the finding on a line nothing parses: the finding still
    exists, but its path reads as truncated and its reason loses its subject.
    The control forces such a path in — once per separator, because the class is
    the whole class.

    **The separator set is all ten `str.splitlines()` splits on, not just `\\n`.**
    Escaping only `\\n` looks correct to a reader whose splitter is `\\n`, and to
    a checker whose escape set is `\\n` — which is exactly why this control reads
    the output with an explicit `\\n` split *and* with one covering the class: it
    must not share the checker's blind spot. Measured before the escape set was
    widened: a path holding U+2028, U+0085, `\\v`, `\\f`, `\\x1c`-`\\x1e` or U+2029
    leaked its tail as an unprefixed line while the `\\n` case stayed clean.
    """
    spelling = _separator_spelling(separator)
    hostile = f"plans/bad{separator}name.md"
    _force_add(scratch_harness, hostile)
    relative = str((scratch_harness / hostile).relative_to(scratch_harness.parent))
    try:
        run = _run_checker(scratch_harness)
        documents = run.leg("ratchet")
        assert len(documents) == 1 and documents[0].state == "FAIL", run.text
        assert documents[0].count == 1, run.text

        # The splitter is explicit `\n` on purpose: the report is framed as
        # `"\n".join(...)`, so a real break is a break, whatever the checker
        # chose to leave unescaped. `str.splitlines()` here would split in the
        # same places as the checker's own escape set and hide the leak.
        lines = re.split(r"\n", run.stdout)
        findings = [line for line in lines if "is tracked but outside" in line]
        assert len(findings) == 1, (
            f"exactly one finding, on one line, must name the tracked path (separator "
            f"{spelling}):\n" + run.text
        )
        assert f"bad{spelling}name.md" in findings[0], (
            f"the path must survive with its separator escaped ({spelling}), not truncated "
            "at it:\n" + findings[0]
        )
        # The escaped spelling is what keeps the line single: no raw separator
        # may remain in it, and the reason must still be attached to the path.
        # The CR case is checked in its decoded form: `text=True` decodes the
        # subprocess output with universal newlines, so the checker sees a CR in
        # a path as LF (see `_separator_spelling`).
        decoded = separator.replace("\r\n", "\n").replace("\r", "\n")
        assert decoded not in findings[0], findings[0]
        assert "ignore rules say:" in findings[0], (
            "the finding's reason must stay on the same line as the path it is about:\n" + findings[0]
        )
        # Every emitted line must still be prefixed, or a parser would see the
        # tail of this finding as an unprefixed line. Splitting on the report's
        # own framing alone would not reach this falsifier for the eight
        # non-`\n` separators — the leak is a break to `splitlines()`, not to
        # `"\n".split` — so the class-wide splitter below is what makes the
        # assertion fail when an escape is removed.
        for splitter in (r"\n", _ALL_SEPARATOR_SPLIT_RE):
            unprefixed = [
                line
                for line in re.split(splitter, run.stdout)
                if line and not re.match(r"^(\[[a-z-]+\]|harness dir:|summary:)", line)
            ]
            assert not unprefixed, (
                f"a finding leaked an unprefixed line for separator {spelling} "
                f"(split {splitter!r}): {unprefixed}"
            )
    finally:
        (scratch_harness / hostile).unlink()
        _run(["git", "rm", "-q", "--cached", relative], cwd=scratch_harness.parent)

    restored = _run_checker(scratch_harness)
    assert restored.returncode == 0, "the control must restore the fixture:\n" + restored.text


def _build_harness_at(harness: Path) -> None:
    """A minimal engine-clean harness dir at `harness`, tracked by git.

    The same content as the `scratch_harness` fixture, but at a caller-chosen
    path so a control can put document-controlled text into the directory *name*
    — which the fixture's fixed `.mstar` name cannot express.
    """
    (harness / "workflows" / "w1").mkdir(parents=True)
    (harness / "projects" / "p1").mkdir(parents=True)
    shutil.copyfile(REPO_ROOT / ".gitignore", harness.parent / ".gitignore")
    shutil.copyfile(HARNESS_DIR / "AGENTS.md", harness / "AGENTS.md")
    (harness / "workflows" / "w1" / "snapshot.json").write_text(
        '{"schema_version": 1, "id": "w1", "type": "plan", "status": "completed",'
        ' "started_at": "2026-01-01", "updated_at": "2026-01-01", "ended_at": "2026-01-01", "plans": []}\n',
        encoding="utf-8",
    )
    (harness / "status.json").write_text(
        '{"version": 2, "updated_at": "2026-01-01", "workflows": []}\n', encoding="utf-8"
    )
    (harness / "projects" / "p1" / "residuals.json").write_text(
        '{"entries": {"p1": []}}\n', encoding="utf-8"
    )
    _run(["git", "init", "-q", "."], cwd=harness.parent)
    _run(["git", "add", "-A"], cwd=harness.parent)


def test_a_path_cannot_forge_the_register_legs_refusal(tmp_path: Path):
    """F1, register leg: the refusal prologue is anchored, not merely present.

    The register leg keys on the validator's refusal prologue, which is how it
    separates "a validator ran and rejected this" from "the reader could not
    read it". But the could-not-read message echoes the document's *path*, so a
    directory whose name is literally `persist get failed: refusing to persist
    invalid residuals document: [low] a: x` puts those words into the output
    without any validator running. Searching for the prologue anywhere accepts
    that forgery and reports `FAIL … 1 violations` for a document no validator
    ever saw; requiring it at position 0 — where the engine's own `failScript`
    writes it, before it echoes any path — does not.

    Reproduced against the unanchored `.find(prologue)` implementation before
    the fix: truth NOT-VALIDATED, reported FAIL with one invented violation.
    """
    prologue = "persist get failed: refusing to persist invalid residuals document: [low] a: x"
    harness = tmp_path / prologue / ".mstar"
    _build_harness_at(harness)
    # Unreadable content, so no validator can run: the engine's answer is
    # `Invalid JSON in <path>`, which carries the hostile directory name.
    (harness / "projects" / "p1" / "residuals.json").write_text(",, bad\n", encoding="utf-8")

    run = _run_checker(harness)
    registers = run.leg("registers")
    assert len(registers) == 1, run.text
    assert registers[0].state == "NOT-VALIDATED", (
        "words inside the document's own path must not be read as a validator refusal:\n" + run.text
    )
    assert run.counters["fail"] == 0, (
        "no FAIL may be manufactured from a filename:\n" + run.text
    )
    assert run.returncode == 1, run.text


def test_present_but_unreadable_root_register_fails_loud(scratch_harness: Path):
    """F2: a root register that exists but is not a file is not "absent".

    The root register is the one document the checker routes by path rather than
    by glob, so it needs its own existence test — and `is_file()` collapses two
    different situations: nothing is there (this checkout carries the published
    subset only, so a benign "nothing to validate" note is right) and something
    is there that cannot be read as a file (a defect, which must fail loud).
    Treating the second as the first drops the `[status]` document line
    entirely, so the summary reports a clean run while the root register was
    never validated — the silent pass this file exists to prevent.

    Both non-regular shapes are driven, and each is checked against the engine's
    *own* verdict rather than a hand-written expectation: a directory makes the
    engine report a real violation (FAIL), a dangling symlink makes it answer
    "status file not found" over exit 1 with no report (NOT-VALIDATED). The leg
    must reproduce whichever the engine said, which is also why the fix delegates
    both shapes instead of inventing a verdict for them.
    """
    status = scratch_harness / "status.json"
    payload = status.read_text(encoding="utf-8")

    # Shape one: a directory. The engine reports `status.invalid-json: EISDIR`.
    status.unlink()
    status.mkdir()
    try:
        engine_said = _run(["mstar", "status", "validate", str(status)], cwd=PACKAGE_ROOT)
        assert "FAIL (1 violation)" in engine_said.stdout + engine_said.stderr, (
            "precondition: the engine must report a real violation for a directory:\n"
            + engine_said.stdout + engine_said.stderr
        )
        run = _run_checker(scratch_harness)
        documents = run.leg("status")
        assert len(documents) == 1, (
            "a present-but-unreadable root register must still be reported as a document; "
            "dropping it reports a clean run for a document never validated:\n" + run.text
        )
        assert documents[0].state == "FAIL", run.text
        assert documents[0].count == 1, run.text
        assert run.returncode == 1, run.text
    finally:
        status.rmdir()

    # Shape two: a dangling symlink. No file to read, so the engine cannot
    # produce a report at all — the honest verdict is NOT-VALIDATED, and again
    # the document line must exist.
    status.symlink_to(scratch_harness.parent / "no-such-status.json")
    try:
        run = _run_checker(scratch_harness)
        documents = run.leg("status")
        assert len(documents) == 1, run.text
        assert documents[0].state == "NOT-VALIDATED", run.text
        assert run.counters["fail"] == 0, run.text
        assert run.returncode == 1, run.text
    finally:
        status.unlink()
        status.write_text(payload, encoding="utf-8")

    restored = _run_checker(scratch_harness)
    assert restored.returncode == 0, "the control must restore the fixture:\n" + restored.text


# The `file:line` citations in the checker's docstrings are claims about a build
# that can be replaced under it. Naming them in data lets a test re-read each
# line and fail when the build moves, which is how the stale
# `validateStatusV22 (L13693)` block survived an earlier review. The two tables
# cover different bundles because the docstring cites both: the installed CLI it
# shells out to, and the host's in-process dsh bundle it names as orientation.
# `13693` appears in both because the docstring cites that number against both
# builds with different expected text (the CLI `validateStatusV22` duplicate and
# the host bundle's SQL `create table`).
#
# Completeness is not maintained by hand: `_cited_line_numbers` derives the cited
# set from the docstrings and the test asserts the tables equal it, so a citation
# added without a table row (or a row without a citation) fails the guard, and a
# `checked >= N` threshold that cannot notice either does not come back.
_CHECKER_CITATIONS_INSTALLED_CLI = {
    3090: 'violations.push(invalid("coordination.row.field", `${what} has unexpected key(s): ${extra.join(", ")}`));',
    3213: 'async get(ref) {',
    3642: 'function validateWorkflowSnapshot(doc) {',
    4424: 'var RESIDUAL_LIFECYCLES = ["open", "resolved", "waived", "superseded", "duplicate"];',
    4453: 'function validatePlanRow(row) {',
    4490: 'function validateResidual(entry) {',
    4504: None,
    4511: None,
    4531: None,
    4534: None,
    4537: None,
    4574: 'function validateStatusV2(docOrPath, opts = {}) {',
    4597: None,
    4605: None,
    4613: None,
    4681: 'var validateStatus = validateStatusV2;',
    5123: 'function validateProjectRegister(doc) {',
    5141: None,
    5158: None,
    10140: 'function summarize(violations) {',
    10274: 'async function readCoordinatedArtifact(harnessRoot, ref) {',
    10288: 'function assertStoredArtifact(kind, payload, path, harnessRoot) {',
    10298: None,
    13693: 'function validateStatusV22(docOrPath, opts = {}) {',
    13716: None,
    13724: None,
    17139: 'function assertStoredArtifact2(kind, payload, path2, harnessRoot) {',
    17146: 'gate22 = validateProjectRegister2(payload);',
    24455: 'function printViolationList(violations) {',
    24456: 'for (const violation17 of violations) {',
    24457: 'console.error(`  - [${violation17.severity}] ${violation17.code}: ${violation17.message}`);',
    24458: 'if (violation17.fix)',
    24459: 'console.error(`    fix: ${violation17.fix}`);',
    24462: 'function readSnapshotForCheck(snapshotPath) {',
    24466: 'if (!(error instanceof WorkflowSnapshotValidationError))',
    24467: 'throw error;',
    24469: 'console.error(import_picocolors4.default.red(`${snapshotPath}: FAIL (${count} violation${count === 1 ? "" : "s"})`));',
    24470: 'printViolationList(error.violations);',
    24482: 'if (path15.basename(statusPath) === WORKFLOW_SNAPSHOT_FILE) {',
    24483: 'const read = readSnapshotForCheck(statusPath);',
    24499: 'console.error(import_picocolors4.default.red(`${statusPath}: FAIL (${count} violation${count === 1 ? "" : "s"})`));',
    24500: 'printViolationList(gate3.violations);',
    24503: 'console.error(import_picocolors4.default.red(`status validate failed: ${error.message}`));',
    24777: 'var PERSIST_KINDS = ["status", "snapshot", "residuals", "review", "json"];',
    24778: 'var COORDINATED_PERSIST_KINDS = ["status", "snapshot", "residuals"];',
    24833: 'function validatePersistPayload(kind, payload) {',
    24840: 'gate3 = validateProjectRegister(payload);',
    24847: 'const detail = gate3.violations.map((v) => `[${v.severity}] ${v.code}: ${v.message}`).join("; ");',
    24848: 'throw new Error(`refusing to persist invalid ${kind} document: ${detail}`);',
    24908: 'const read = await readCoordinatedArtifact(root, { kind: parsedKind, key });',
    24917: 'validatePersistPayload(parsedKind, payload);',
    24922: 'failScript(error, "persist get");',
    25074: 'function failScript(error, context) {',
    25075: 'if (error instanceof SddScriptError) {',
    25076: 'console.error(import_picocolors4.default.red(`${context} failed: ${error.message}`));',
    25077: 'process.exitCode = error.exitCode;',
    25078: 'return;',
    25079: '}',
    25080: 'console.error(import_picocolors4.default.red(`${context} failed: ${error.message}`));',
    25081: 'process.exitCode = 1;',
}

_CHECKER_CITATIONS_DSH = {
    3103: 'function validateWorkflowSnapshot(doc) {',
    3308: 'function validatePlanRow(row) {',
    3345: 'function validateResidual(entry) {',
    3429: 'function validateStatusV2(docOrPath, opts = {}) {',
    3452: None,
    3460: None,
    3468: None,
    3536: 'var validateStatus = validateStatusV2;',
    4117: 'function validateProjectRegister(doc) {',
    13693: 'workflow_id text primary key references execution_workflows(workflow_id),',
}

# Long single-line sites are matched by substring rather than equality so a
# reformat of the template does not mask a moved symbol; every entry here is a
# key of a table above.
_CITATION_SUBSTRINGS = {
    3090: 'has unexpected key(s): ${extra.join(", ")}',
    4504: '"status.residual.invalid-severity"',
    4511: '"status.residual.invalid-decision"',
    4531: '"status.residual.invalid-lifecycle"',
    4534: '"status.residual.closed-missing-closed-at"',
    4537: '"status.residual.closed-missing-closure-note"',
    4597: '"status.migration-required"',
    4605: '"status.migration-required"',
    4613: '"status.migration-required"',
    5141: '"project.register.invalid-entry-list"',
    5158: '"project.register.mismatched-source-plan"',
    10298: 'fails validation \\u2014 ${summarize(gate2.violations)}',
    13716: 'violation42("high", "status.migration-required"',
    13724: 'violation42("high", "status.migration-required", "v1-shaped status.json (root plans[])',
}

# The same, for the host bundle's three `status.migration-required` sites.
_CITATION_SUBSTRINGS_DSH = {
    3452: 'schema version 2 required',
    3460: 'root plans[]) is not a v2 document',
    3468: 'root residual_findings) is not a v2 document',
}


def _installed_cli_bundle() -> Path | None:
    """The engine bundle the checker actually shells out to, or None."""
    shim = Path(checker.MSTAR_FALLBACK)
    if shim.is_file():
        try:
            text = shim.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        for token in re.findall(r"[\w./@-]*mstar-harness\.js", text):
            for candidate in (Path(token), Path("/usr/lib/node_modules/@mstar-harness/cli/dist/mstar-harness.js")):
                if candidate.is_file():
                    return candidate
    fallback = Path("/usr/lib/node_modules/@mstar-harness/cli/dist/mstar-harness.js")
    return fallback if fallback.is_file() else None


def _cited_line_numbers() -> set[int]:
    """Every `L<n>` the checker's docstrings cite, `L<a>-L<b>` ranges expanded.

    Derived from the checker source, never from the tables below: that is what
    lets the guard fail when a *citation* is added or removed without the tables
    following. A `checked >= <constant>` assertion cannot see that — the table
    can be kept at its old size while a new citation goes unchecked, which is
    exactly how the dsh block and the "old, wrong" numbers stayed unverified.
    """
    tree = ast.parse(_CHECKER_SOURCE.read_text(encoding="utf-8"))
    numbers: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        doc = ast.get_docstring(node, clean=False)
        if not doc:
            continue
        numbers |= {int(n) for n in re.findall(r"L(\d+)", doc)}
        for start, end in re.findall(r"L(\d+)\s*-\s*L?(\d+)", doc):
            numbers |= set(range(int(start), int(end) + 1))
    return numbers


def _cited_dsh_bundle() -> Path | None:
    """The host bundle the docstring names, resolved from the docstring itself.

    The block names one exact path and its byte size, so the guard reads *that*
    path instead of guessing among installed profiles: if the session's profile
    changes, the citation is stale and the guard must say so rather than quietly
    checking a different bundle and reporting green. The docstring wraps the path
    across two source lines, so whitespace is collapsed before matching — the
    citation is the path, not its line wrapping.
    """
    doc = ast.get_docstring(ast.parse(_CHECKER_SOURCE.read_text(encoding="utf-8")), clean=False) or ""
    flattened = re.sub(r"\s+", " ", doc)
    match = re.search(r"(/[^\s]*?node_modules/)\s*(@mstar-harness/dsh/dist/index\.js)", flattened)
    if match is None:
        return None
    path = Path((match.group(1) + match.group(2)).replace(" ", ""))
    return path if path.is_file() else None


def test_checker_docstring_citations_still_name_what_they_claim():
    """F4: every `file:line` the docstring cites must still hold that line.

    A citation is a claim about a specific build. The docstring carried a block
    naming `validateStatusV22 (L13693)` and `assertStoredArtifact2 (L17139)`
    that no longer existed anywhere — those numbers pointed at SQL `create
    table` text — and nothing failed, because prose cannot fail. This test reads
    each cited line out of the bundle the docstring names for it and compares it,
    so the block goes red when the build moves and the citation block must be
    re-verified.

    **Both bundles, and every cited line.** The docstring cites 69 line numbers
    across the installed CLI and the host dsh bundle; the tables must equal that
    set exactly, which is the count-change guard the earlier `checked >= 43`
    could not provide. The earlier table also left the whole dsh block and the
    four "old, wrong" numbers the fix pass quotes as corrected unchecked, so the
    two prior citation errors lived precisely where the guard was blind.
    """
    cited = _cited_line_numbers()
    declared = set(_CHECKER_CITATIONS_INSTALLED_CLI) | set(_CHECKER_CITATIONS_DSH)
    assert declared == cited, (
        "the citation tables and the docstrings' `L<n>` tokens have drifted apart — a "
        "citation was added, moved or removed without the tables following, so part of "
        "the docstring is unchecked.\n"
        f"  cited but untabled: {sorted(cited - declared)}\n"
        f"  tabled but uncited: {sorted(declared - cited)}"
    )

    cli_bundle = _installed_cli_bundle()
    if cli_bundle is None:
        pytest.skip("no installed @mstar-harness/cli bundle to check citations against")
    cli_lines = cli_bundle.read_text(encoding="utf-8", errors="replace").splitlines()

    dsh_bundle = _cited_dsh_bundle()
    if dsh_bundle is None:
        pytest.skip(
            "the host dsh bundle the checker's docstring names by exact path is not installed, "
            "so its block cannot be re-read here"
        )
    dsh_lines = dsh_bundle.read_text(encoding="utf-8", errors="replace").splitlines()

    # The block states the bundle's size, so a replaced build is a red guard even
    # before a line is compared.
    stated = re.search(r"dist/index\.js,\s*(\d+)\s*bytes", _CHECKER_SOURCE.read_text(encoding="utf-8"))
    assert stated, "the docstring must state the dsh bundle's size for the citation to be checkable"
    assert dsh_bundle.stat().st_size == int(stated.group(1)), (
        f"the docstring cites {dsh_bundle} as {stated.group(1)} bytes, but it is "
        f"{dsh_bundle.stat().st_size} — the build moved and the block must be re-verified"
    )

    checked = 0
    for bundle, lines, table, substrings in (
        (cli_bundle, cli_lines, _CHECKER_CITATIONS_INSTALLED_CLI, _CITATION_SUBSTRINGS),
        (dsh_bundle, dsh_lines, _CHECKER_CITATIONS_DSH, _CITATION_SUBSTRINGS_DSH),
    ):
        for number, expected in table.items():
            assert 1 <= number <= len(lines), f"cited line L{number} is past the end of {bundle}"
            actual = lines[number - 1].strip()
            if expected is None:
                needle = substrings[number]
                assert needle in actual, (
                    f"{bundle.name}:L{number} no longer contains {needle!r}; the docstring cites "
                    f"this line for a symbol that has moved or gone. Actual line: {actual[:140]!r}"
                )
            else:
                assert actual == expected, (
                    f"{bundle.name}:L{number} no longer reads as the docstring claims.\n"
                    f"  cited: {expected!r}\n  actual: {actual[:160]!r}\n"
                    "Re-verify the docstring's citation block with `sed -n` and update it."
                )
            checked += 1
    # Every cited number is re-read once per bundle it is cited against; `13693`
    # is cited against both, which is why it may legitimately be read twice.
    assert checked == len(_CHECKER_CITATIONS_INSTALLED_CLI) + len(_CHECKER_CITATIONS_DSH), checked
    assert checked == len(cited) + len(set(_CHECKER_CITATIONS_DSH) & {13693}), (
        f"every cited line must be re-read exactly once except a number cited against both "
        f"bundles: checked={checked}, cited={len(cited)}"
    )


def test_ratchet_reports_an_unresolvable_work_tree(tmp_path: Path):
    """F3, the three git-boundary branches: no usable work tree, no ratchet.

    The ratchet is a statement about a harness subtree *inside a git work tree*.
    Each way of failing to establish that — not in a work tree at all, in one
    that does not contain the harness dir, and a harness dir that *is* the work
    tree root — leaves the tracked set undefined, so the leg has nothing to
    ratchet over and must say NOT-VALIDATED rather than report a clean boundary.
    Reporting OK for "no tracked paths outside the set" while the set was never
    obtained is the silent-pass failure mode; all three shapes are driven here
    because they are three separate branches with the same obligation.
    """
    agents = (HARNESS_DIR / "AGENTS.md").read_text(encoding="utf-8")

    # Shape one: the harness dir is not inside any git work tree.
    loose = tmp_path / "loose" / ".mstar"
    loose.mkdir(parents=True)
    (loose / "AGENTS.md").write_text(agents, encoding="utf-8")
    run = _run_checker(loose)
    ratchet = run.leg("ratchet")
    assert len(ratchet) == 1 and ratchet[0].state == "NOT-VALIDATED", run.text
    assert "not inside a git work tree" in run.text, run.text
    assert run.returncode == 1, run.text

    # Shape two: the harness dir is the work tree root, so there is no subtree
    # for the published-set boundary to be defined against.
    root = tmp_path / "rooted"
    root.mkdir()
    (root / "AGENTS.md").write_text(agents, encoding="utf-8")
    _run(["git", "init", "-q", "."], cwd=root)
    _run(["git", "add", "-A"], cwd=root)
    run = _run_checker(root)
    ratchet = run.leg("ratchet")
    assert len(ratchet) == 1 and ratchet[0].state == "NOT-VALIDATED", run.text
    assert "harness dir is the repository root" in run.text, run.text

    # Shape three: a work tree exists but does not contain the harness dir. The
    # engine is pointed at a work tree elsewhere via GIT_WORK_TREE, which is a
    # real configuration a caller can be under rather than a contrived one.
    elsewhere = tmp_path / "elsewhere" / ".mstar"
    elsewhere.mkdir(parents=True)
    (elsewhere / "AGENTS.md").write_text(agents, encoding="utf-8")
    repo = tmp_path / "otherrepo"
    repo.mkdir()
    _run(["git", "init", "-q", "."], cwd=repo)
    env = {
        **os.environ,
        "GIT_DIR": str(repo / ".git"),
        "GIT_WORK_TREE": str(repo),
    }
    run = _run_checker(elsewhere, env=env)
    ratchet = run.leg("ratchet")
    assert len(ratchet) == 1 and ratchet[0].state == "NOT-VALIDATED", run.text
    assert "outside its git work tree" in run.text, (
        "the leg must say the harness dir is outside the work tree it found:\n" + run.text
    )
    # Independent of which shape: no boundary counter may be claimed when the
    # tracked set was never established.
    assert "new-out-of-set" not in run.counters, (
        "the leg must not claim a boundary it never classified:\n" + run.text
    )


def test_the_engines_fix_guidance_survives_into_the_report(scratch_harness: Path):
    """The engine's `fix:` line is part of its verdict and must not be dropped.

    `printViolationList` emits a violation row and, when the violation carries
    one, an indented `fix:` line under it (`mstar-harness.js:24457` then
    `:24459`). That guidance is operator-facing output of the engine, so a
    report that kept the row and dropped the fix would be quietly less useful
    than what the engine said — and a detail-line filter that matches only
    violation rows (rather than whole violations) does exactly that.

    The v1 root register is used because the engine attaches a fix to
    `status.migration-required` ("run `mstar migrate`"), which makes the fix
    line's presence observable.
    """
    status = scratch_harness / "status.json"
    payload = status.read_text(encoding="utf-8")
    status.write_text('{"version": 1, "updated_at": "2026-01-01"}\n', encoding="utf-8")
    try:
        # The engine's own output for this document, to assert against rather
        # than a hand-written expectation of what it says.
        engine = _run(["mstar", "status", "validate", str(status)], cwd=PACKAGE_ROOT)
        engine_text = engine.stdout + engine.stderr
        assert "status.migration-required" in engine_text, (
            "precondition: the engine must report the migration violation:\n" + engine_text
        )
        assert "fix: " in engine_text, (
            "precondition: the engine must attach a fix line to this violation:\n" + engine_text
        )

        run = _run_checker(scratch_harness)
        documents = run.leg("status")
        assert len(documents) == 1 and documents[0].state == "FAIL", run.text
        assert "status.migration-required" in run.text, run.text
        assert "fix: run `mstar migrate`" in run.text, (
            "the engine's fix guidance must survive into the report:\n" + run.text
        )
        # And it must still be attributed and on its own line, or it would read
        # as a finding rather than as guidance for the row above it.
        fix_lines = [line for line in run.stdout.splitlines() if "fix: run `mstar migrate`" in line]
        assert len(fix_lines) == 1, run.text
        assert fix_lines[0].startswith("[status] "), (
            "the fix line must carry the leg prefix like every other detail line:\n" + fix_lines[0]
        )
    finally:
        status.write_text(payload, encoding="utf-8")

    restored = _run_checker(scratch_harness)
    assert restored.returncode == 0, "the control must restore the fixture:\n" + restored.text


@pytest.mark.parametrize("payload", ['"just a string"', "42", "null", "[1, 2, 3]"])
def test_parsable_json_of_the_wrong_shape_is_a_violation_not_a_skip(scratch_harness: Path, payload: str):
    """F1 (fix pass #3 re-review): the shape class must not adjudicate validity.

    Parsable JSON whose top level is not the object the engine expects is *not*
    an unreadable document — the engine reads it and reports a real violation
    against it (`workflow.snapshot.invalid`, `status.invalid-doc`,
    `project.register.invalid`). Classifying it as "invalid JSON" hid that
    violation behind NOT-VALIDATED on the snapshot and register legs, while the
    root register happened to answer correctly only because it has a rule code
    of its own. The expectation is taken from the engine, so this cannot pass by
    the fixture ceasing to be a violation.
    """
    snapshot = scratch_harness / "workflows" / "w1" / "snapshot.json"
    register = scratch_harness / "projects" / "p1" / "residuals.json"
    original_snapshot = snapshot.read_text(encoding="utf-8")
    original_register = register.read_text(encoding="utf-8")
    snapshot.write_text(payload, encoding="utf-8")
    register.write_text(payload, encoding="utf-8")
    try:
        # Leg (a): the engine reports a real violation for this shape.
        engine_said = _run(["mstar", "status", "validate", str(snapshot)], cwd=PACKAGE_ROOT)
        assert "FAIL (" in engine_said.stdout + engine_said.stderr, (
            "precondition: the engine must report a violation for parsable non-object JSON:\n"
            + engine_said.stdout + engine_said.stderr
        )
        run = _run_checker(scratch_harness)
        for leg in ("snapshots", "registers"):
            documents = run.leg(leg)
            assert len(documents) == 1, run.text
            assert documents[0].state == "FAIL", (
                f"leg ({leg}): parsable JSON of the wrong shape is a violation the engine "
                f"reported, and must not be demoted to NOT-VALIDATED:\n" + run.text
            )
    finally:
        snapshot.write_text(original_snapshot, encoding="utf-8")
        register.write_text(original_register, encoding="utf-8")

    restored = _run_checker(scratch_harness)
    assert restored.returncode == 0, "the control must restore the fixture:\n" + restored.text


def test_a_project_name_cannot_reach_argv(scratch_harness: Path):
    """QC1-F1: the project directory name is document-controlled; argv is a channel.

    `_register_validate` derives `key` from the *directory name* under
    `projects/`. Passing it as a separate token (`--key <name>`) let the name
    reach argv, and the engine parses a bare `--key` as a complete option pair
    and reads the next token as a new top-level option — so a project directory
    named `--version` made the reader print its version and **exit 0**. Since the
    verdict *is* the exit code, a genuinely invalid register then reported `OK`
    and the whole run exited 0.

    Binding the value to its flag (`--key=<name>`) keeps the name out of argv
    entirely. The expectation is the engine's own answer for the same bytes under
    a legal key, so this control cannot pass by the fixture ceasing to be invalid.
    """
    projects = scratch_harness / "projects"
    hostile = projects / "--version"
    legal = projects / "p1"
    hostile.mkdir(parents=True)
    legal.mkdir(parents=True, exist_ok=True)
    body = "{}"  # invalid: the engine refuses with project.register.missing-entries
    (hostile / "residuals.json").write_text(body, encoding="utf-8")
    (legal / "residuals.json").write_text(body, encoding="utf-8")
    try:
        # Precondition: the engine refuses these bytes, so the only question is
        # whether the name lets the checker escape that refusal.
        env = {**os.environ, "MSTAR_HARNESS_DIR": str(scratch_harness)}
        engine_said = subprocess.run(
            ["mstar", "persist", "get", "--validate", "residuals", "--key=p1"],
            cwd=str(scratch_harness), env=env, capture_output=True, text=True, timeout=300,
        )
        assert "refusing to persist invalid" in engine_said.stdout + engine_said.stderr, (
            "precondition: the engine must refuse this register:\n"
            + engine_said.stdout + engine_said.stderr
        )

        run = _run_checker(scratch_harness)
        documents = {d.target: d for d in run.leg("registers")}
        assert "projects/--version/residuals.json" in documents, run.text
        assert documents["projects/--version/residuals.json"].state == "FAIL", (
            "a project named `--version` must not let an invalid register report OK "
            "(the name reached argv and the engine answered its version, exit 0):\n" + run.text
        )
        assert run.returncode == 1, run.text
    finally:
        shutil.rmtree(hostile, ignore_errors=True)
        shutil.rmtree(legal, ignore_errors=True)
