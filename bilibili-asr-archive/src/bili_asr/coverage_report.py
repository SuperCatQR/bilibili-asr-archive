"""Deterministic read-only corpus coverage projection."""
from __future__ import annotations
import csv, io, json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_DIAGNOSTICS=1000
COLUMNS=("work_id","category","status","cumulative_complete","batch_complete","artifact_present","report_state","denominator_count","cumulative_count","batch_count","diagnostics")

@dataclass(frozen=True)
class CoverageReport:
    data: dict[str,Any]
    @classmethod
    def build(cls, archive_root: Path, *, scope: str|None=None):
        root=Path(archive_root); di=[]; rows={}; valid=True
        path=root/"manifest"/"manifest.jsonl"
        if not path.is_file(): di.append({"code":"denominator_unavailable","detail":"manifest_snapshot_missing"}); valid=False
        else:
            try: lines=path.read_text(encoding="utf-8").splitlines()
            except (OSError,UnicodeError): lines=[]; di.append({"code":"denominator_unavailable","detail":"manifest_snapshot_unreadable"}); valid=False
            for n,line in enumerate(lines,1):
                if not line.strip(): continue
                try: e=json.loads(line)
                except (ValueError,TypeError): di.append({"code":"manifest_malformed","detail":f"line_{n}"}); valid=False; continue
                if not isinstance(e,dict): di.append({"code":"manifest_invalid","detail":f"line_{n}"}); valid=False; continue
                key=str(e.get("work_id") or e.get("bvid") or "")
                if not key: di.append({"code":"manifest_invalid","detail":f"line_{n}"}); valid=False; continue
                if key in rows: di.append({"code":"manifest_duplicate_work_id","detail":key}); valid=False; continue
                rows[key]=e
        selected,ok=_select(rows,scope)
        if not ok: di.append({"code":"scope_unavailable","detail":"unknown_scope"}); valid=False
        scheduler=_read_json(root/"scheduler.json",di,"scheduler")
        cursor=_read_json(root/"meta-cursor.json",di,"meta_cursor")
        ledger=_read_jsonl(root/"run-ledger.jsonl",di,"run_ledger")
        attempts=_read_jsonl(root/"coordinator"/"attempts.jsonl",di,"attempts")
        if cursor and cursor.get("mid") is not None:
            pass
        batch_ids=set(scheduler.get("processed_work_ids",[])) if scheduler else set()
        if scheduler and scheduler.get("scope") and ledger:
            newest=ledger[-1]; ids=newest.get("work_ids")
            if isinstance(ids,list) and set(map(str,ids))!=batch_ids: di.append({"code":"sidecar_work_id_contradiction","detail":"scheduler_run_ledger"})
        out=[]
        for key,e in sorted(selected.items()):
            status=str(e.get("status") or "unknown"); artifact=_artifact(root,e)
            cumulative=status in {"archived","gone"} and (artifact if status=="archived" else True)
            if status=="archived" and not artifact: di.append({"code":"terminal_missing_artifact","detail":key})
            out.append({"work_id":key,"category":_category(status),"status":status,"cumulative_complete":cumulative,"batch_complete":key in batch_ids and cumulative,"artifact_present":artifact})
        di=sorted(di,key=lambda x:(x["code"],x["detail"]))[:MAX_DIAGNOSTICS]
        denom=len(out) if valid else None
        cum=sum(r["cumulative_complete"] for r in out); bat=sum(r["batch_complete"] for r in out)
        state=(scheduler or {}).get("state") if scheduler else None
        batch_state=state if state in {"complete","limited","risk_interrupted"} else ("incomplete" if batch_ids else "unavailable")
        data={"schema":"coverage-report-v1","scope":scope,"denominator":{"unit":"work_items","count":denom,"source":"manifest_snapshot","state":"available" if valid else "unavailable"},"cumulative":{"unit":"work_items","complete":cum,"total":len(out),"state":"complete" if valid and cum==len(out) else "incomplete"},"batch":{"unit":"work_items","complete":bat,"total":len(batch_ids),"state":batch_state},"rows":out,"diagnostics":di}
        return cls(data)
    def to_json(self): return json.dumps(self.data,ensure_ascii=False,sort_keys=False,separators=(",",":"))
    def to_csv(self):
        out=io.StringIO(newline=""); w=csv.DictWriter(out,fieldnames=COLUMNS,lineterminator="\n"); w.writeheader(); d=self.data
        summary=f"{len(d['diagnostics'])}:{','.join(x['code'] for x in d['diagnostics'])}"
        for r in d['rows']: w.writerow({**r,"report_state":d["denominator"]["state"],"denominator_count":d["denominator"]["count"],"cumulative_count":d["cumulative"]["complete"],"batch_count":d["batch"]["complete"],"diagnostics":summary})
        return out.getvalue()

def _read_json(p,di,name):
    if not p.exists(): return None
    try:
        x=json.loads(p.read_text(encoding="utf-8")); return x if isinstance(x,dict) else (_bad(di,name) or None)
    except (OSError,UnicodeError,ValueError,TypeError): return _bad(di,name)
def _read_jsonl(p,di,name):
    if not p.exists(): return []
    try: lines=p.read_text(encoding="utf-8").splitlines()
    except (OSError,UnicodeError): _bad(di,name); return []
    out=[]
    for line in lines:
        if line.strip():
            try:
                x=json.loads(line)
                if isinstance(x,dict): out.append(x)
                else: _bad(di,name)
            except (ValueError,TypeError): _bad(di,name)
    return out
def _bad(di,name): di.append({"code":"sidecar_malformed","detail":name}); return None
def _select(rows,scope):
    if not scope:return rows,True
    t=set(scope.replace(","," ").split())
    if "pending" in t:return {k:v for k,v in rows.items() if v.get("status") not in {"archived","gone"}},True
    if "failed" in t:return {k:v for k,v in rows.items() if v.get("status")=="failed"},True
    x={k:v for k,v in rows.items() if k in t or str(v.get("bvid")) in t}; return x,bool(x)
def _category(s): return "transcript" if s in {"archived","asr_done"} else "audio" if s in {"needs_audio","audio_ok"} else "unavailable" if s=="gone" else "metadata"
def _artifact(root,e):
    if e.get("status")!="archived": return False
    try:
        from .archive import archive_stem
        stem=archive_stem(e)
    except (KeyError,TypeError,ValueError): return False
    return any((root/"transcripts"/d/f"{stem}{ext}").is_file() for d,ext in (("srt",".srt"),("txt",".txt"))) or bool(e.get("md_path") and (root/str(e["md_path"])).is_file())
