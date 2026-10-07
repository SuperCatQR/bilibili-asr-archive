import bili_asr.cli.main as _module_cli_main
from pathlib import Path
import json
import signal
import pytest
from bili_asr import cli
from bili_asr.bili_client import RiskBudgetExhausted
from bili_asr.campaign import CampaignRunner
from bili_asr.coordinator import RunCoordinator
from bili_asr.manifest import ManifestStore
from bili_asr.page_identity import artifact_stem, page_identity
from bili_asr.run_ledger import RunLedger, build_run_record, collect_hotwords_dropped


class VerdictRunner:
    """Small deterministic runner fake shared by batch and ledger tests."""

    def __init__(self, interrupt=None):
        self.interrupt = interrupt
        self.calls = 0
        self.released = 0
        self.hotwords_dropped = ()

    def set_hotword_evidence(self, **kwargs):
        pass

    def rebuild_hotwords_from_first_pass(self, transcript_text):
        return []

    def transcribe(self, path, **kwargs):
        self.calls += 1
        if self.calls == 3 and self.interrupt is not None:
            signal.getsignal(self.interrupt)(self.interrupt, None)
        self.hotwords_dropped = (
            ("扬弃", "此在", "扬弃") if self.calls == 1 else (
                "此在", "总体性", "甲,乙", "cookie=SECRET",
                "SESSDATA=private", "https://signed.example/?token=SECRET",
                "password=private", "C:/private/model", "Traceback private",
            )
        )
        return [{"start": 0, "end": 1, "text": "记录"}]

    def provenance(self):
        return {"model_name": "test-model", "language": "zh"}

    def release(self):
        self.released += 1
        self.hotwords_dropped = ("released-only",)


class RiskOnceRunner(VerdictRunner):
    def __init__(self):
        super().__init__()
        self.risk_seen = False

    def transcribe(self, path, **kwargs):
        if self.calls == 1 and not self.risk_seen:
            self.risk_seen = True
            self.calls += 1
            raise RiskBudgetExhausted(-412)
        return super().transcribe(path, **kwargs)


def _seed_audio(root, count):
    store = ManifestStore(root)
    rows = []
    for index in range(count):
        identity = page_identity("BVhotword", index, 7 + index, f"p{index}")
        declared = f"audio/{artifact_stem(identity)}.m4a"
        audio = Path(root) / declared
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"audio")
        row = {
            "work_id": identity.work_id, "bvid": identity.bvid,
            "page_index": index, "cid": identity.cid, "page_label": identity.page_label,
            "title": "record", "date": "2026-10-05", "duration_s": 1,
            "status": "audio_ok", "audio_path": declared,
        }
        store.upsert(row)
        rows.append((identity.work_id, row))
    return store, rows
