"""Models implementation."""

from __future__ import annotations

from dataclasses import dataclass, field


def model_constructions_line(command: str, constructions: int, asr_items: int) -> str:
    """The one line a batch prints to state how much reuse it got.

    Single source of the shipped string: README quotes this literal, and the
    in-process ``asr`` / ``pilot`` loops print through it as well
    (``cli._print_in_process_constructions``), so all five labels — ``run``,
    ``schedule`` and ``campaign`` via ``RunCoordinator.run_batch``, ``asr`` and
    ``pilot`` via that CLI helper — come from this one format string.
    """
    return (
        f"{command}: model constructions={constructions} "
        f"for {asr_items} asr item(s)"
    )


@dataclass
class RowResult:
    work_id: str
    final_status: str
    ok: bool = False
    skipped: bool = False
    skip_reason: str = ""
    failure_codes: list[int | str] = field(default_factory=list)


@dataclass
class RunSummary:
    results: list[RowResult] = field(default_factory=list)
    risk_interrupted: bool = False
    # Constructions this batch paid (delta over the batch's runner, so a
    # caller-injected runner reused across batches still reports per-batch
    # truth) and how many rows actually produced an ASR transcript.
    model_constructions: int = 0
    model_load_attempts: int = 0
    asr_items: int = 0
    hotwords_dropped: list[str] = field(default_factory=list)

    @property
    def failed(self) -> list[RowResult]:
        return [r for r in self.results if not r.ok and not r.skipped]

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def skipped_rows(self) -> list[RowResult]:
        return [r for r in self.results if r.skipped]

    @property
    def fully_processed(self) -> bool:
        """True when no row failed/unprocessed and no risk interruption.

        An empty selection is vacuously fully processed. Terminal-scope
        reruns (rows skipped as ``already_terminal``) count as processed:
        nothing remains to do for those rows (F-002).
        """
        return not self.risk_interrupted and all(
            r.ok or r.skip_reason == "already_terminal" for r in self.results
        )
