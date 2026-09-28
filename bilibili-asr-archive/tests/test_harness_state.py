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

# The register's violation count may only shrink. Recorded 2026-09-28 from
# `MSTAR_HARNESS_DIR=.mstar mstar persist get --validate residuals --key
# _default` on the pre-Task-2 register: 144 violations. Task 2 drives it to 0;
# a number *above* this ceiling means some entry regressed to a violating shape,
# which is the one register failure this file can assert before Task 2 lands.
REGISTER_VIOLATION_CEILING = 144

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
            ["mstar", "persist", "get", "--validate", "residuals", "--key", key],
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

    assert total_engine_violations <= REGISTER_VIOLATION_CEILING, (
        f"the register carries {total_engine_violations} engine violations, above the "
        f"{REGISTER_VIOLATION_CEILING} recorded 2026-09-28 — the count may only shrink "
        "(Task 2 drives it to 0), so this is a regression to a violating shape."
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


def test_unreadable_document_is_not_validated_rather_than_failed(scratch_harness: Path):
    """Fail-loud, second form: a document the engine never got to validate.

    This is why the checker keys on the engine's `FAIL (N violations)` header
    rather than on exit 1 alone. `mstar status validate <path>` routes by
    basename (`mstar-harness.js:24483`): a `snapshot.json` path goes through
    `readSnapshotForCheck`, which **throws** on unreadable JSON and is caught
    into `status validate failed: …` with exit 1 and no report at all. Exit-code
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
