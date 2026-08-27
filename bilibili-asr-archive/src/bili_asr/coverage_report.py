"""Deterministic, read-only corpus coverage projection."""
from __future__ import annotations
import csv, io, json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "coverage-report-v1"
STATES = {"complete", "limited", "risk_interrupted", "incomplete", "unavailable"}
CSV_COLUMNS = ("schema_version","scope","denominator_unit","denominator_count","denominator_state","denominator_source","cumulative_unit","cumulative_complete","cumulative_total","cumulative_state","batch_unit","batch_complete","batch_total","batch_state","work_id","category","status","artifact_present","diagnostics")
MAX_DIAGNOSTICS = 100

@dataclass(frozen=True)
class CoverageReport:
    data: dict[str, Any]

    @classmethod
    def build(cls, archive_root: Path, *, scope: str | None = None):
        root = Path(archive_root); diagnostics: list[dict[str,str]] = []
        manifest, manifest_ok = _manifest(root / "manifest" / "manifest.jsonl", diagnostics)
        selected, scope_ok = _select(manifest, scope, _attempts(root / "coordinator" / "attempts.jsonl", diagnostics)[0])
        if not scope_ok: diagnostics.append({"code":"scope_unavailable","detail":"unknown_scope"})
        cursor, cursor_ok = _sidecar(root/"meta-cursor.json", diagnostics, "meta_cursor")
        scheduler, scheduler_ok = _sidecar(root/"scheduler.json", diagnostics, "scheduler")
        ledger, ledger_ok = _jsonl(root/"run-ledger.jsonl", diagnostics, "run_ledger")
        attempts, attempts_ok = _attempts(root/"coordinator"/"attempts.jsonl", diagnostics)
        if not cursor_ok or not scheduler_ok or not ledger_ok or not attempts_ok: diagnostics.append({"code":"evidence_unavailable","detail":"sidecar"})
        batch_ids = _ids(scheduler, "processed_work_ids", diagnostics, "scheduler_invalid_batch")
        latest = ledger[-1] if ledger else {}
        if isinstance(latest.get("work_ids"), list) and set(latest["work_ids"]) != batch_ids: diagnostics.append({"code":"sidecar_work_id_contradiction","detail":"scheduler_run_ledger"})
        if cursor and cursor.get("state") not in {None,"complete","limited","risk_interrupted","incomplete","unavailable"}: diagnostics.append({"code":"cursor_invalid_state","detail":"meta_cursor"})
        if scheduler and scheduler.get("state") not in {None,*STATES}: diagnostics.append({"code":"scheduler_invalid_state","detail":"state"})
        selected_ids=set(selected); batch_ids &= selected_ids
        rows=[]
        for wid, entry in sorted(selected.items()):
            status=str(entry.get("status") or "unknown"); artifact=_artifact(root, entry)
            terminal=status=="gone" or (status=="archived" and artifact)
            if status=="archived" and not artifact: diagnostics.append({"code":"terminal_missing_artifact","detail":wid})
            relevant=[a for a in attempts if str(a.get("work_id"))==wid]
            if len(relevant)>1: diagnostics.append({"code":"duplicate_attempts","detail":wid})
            if relevant and any(a.get("outcome") in {"failed","error","retryable","nonterminal"} for a in relevant) and not terminal: diagnostics.append({"code":"retryable_attempt","detail":wid})
            rows.append({"work_id":wid,"category":_category(status),"status":status,"artifact_present":artifact,"cumulative_complete":terminal,"batch_complete":wid in batch_ids and terminal})
        denom_ok=manifest_ok and scope_ok
        cumulative_complete=sum(r["cumulative_complete"] for r in rows)
        batch_complete=sum(r["batch_complete"] for r in rows)
        cstate="unavailable" if not denom_ok else ("complete" if cumulative_complete==len(rows) and not diagnostics else "incomplete")
        bstate=(scheduler or {}).get("state") if scheduler else "unavailable"
        if bstate not in STATES: bstate="unavailable"
        if bstate=="complete" and (not batch_ids or any(not r["batch_complete"] for r in rows if r["work_id"] in batch_ids)): bstate="incomplete"
        data={"schema_version":SCHEMA_VERSION,"scope":scope,"denominator":{"unit":"work_items","count":len(rows) if denom_ok else None,"state":"available" if denom_ok else "unavailable","source":"manifest_snapshot"},"cumulative":{"unit":"work_items","complete":cumulative_complete,"total":len(rows),"state":cstate},"batch":{"unit":"work_items","complete":batch_complete,"total":len(batch_ids),"state":bstate},"evidence":{"manifest":{"state":"available" if manifest_ok else "malformed"},"cursor":{"state":"available" if cursor_ok and cursor else "missing"},"scheduler":{"state":"available" if scheduler_ok and scheduler else "missing"},"run_ledger":{"state":"available" if ledger_ok and ledger else "missing"},"attempts":{"state":"available" if attempts_ok and attempts else "missing"}},"rows":rows,"diagnostics":sorted(diagnostics,key=lambda x:(x["code"],x["detail"]))[:MAX_DIAGNOSTICS]}
        return cls(data)

    def to_json(self): return json.dumps(self.data, ensure_ascii=False, sort_keys=True, separators=(",",":"))
    def to_csv(self):
        out=io.StringIO(newline=""); w=csv.DictWriter(out,fieldnames=CSV_COLUMNS,lineterminator="\n"); w.writeheader(); d=','.join(x['code'] for x in self.data['diagnostics']); den=self.data['denominator']; c=self.data['cumulative']; b=self.data['batch']
        for r in self.data['rows']: w.writerow({"schema_version":self.data['schema_version'],"scope":self.data['scope'] or "","denominator_unit":den['unit'],"denominator_count":den['count'] if den['count'] is not None else "","denominator_state":den['state'],"denominator_source":den['source'],"cumulative_unit":c['unit'],"cumulative_complete":c['complete'],"cumulative_total":c['total'],"cumulative_state":c['state'],"batch_unit":b['unit'],"batch_complete":b['complete'],"batch_total":b['total'],"batch_state":b['state'],"work_id":r['work_id'],"category":r['category'],"status":r['status'],"artifact_present":r['artifact_present'],"diagnostics":d})
        return out.getvalue()

def _manifest(path, ds):
    if not path.is_file(): ds.append({"code":"denominator_unavailable","detail":"manifest_snapshot_missing"}); return {},False
    out={}; ok=True
    try: lines=path.read_text(encoding='utf-8').splitlines()
    except (OSError,UnicodeError): ds.append({"code":"denominator_unavailable","detail":"manifest_snapshot_unreadable"}); return {},False
    for n,line in enumerate(lines,1):
        try: v=json.loads(line)
        except (ValueError,TypeError): ds.append({"code":"manifest_malformed","detail":f"line_{n}"}); ok=False; continue
        wid=v.get('work_id') if isinstance(v,dict) else None
        if not isinstance(wid,str) or not wid or wid in out: ds.append({"code":"manifest_duplicate_work_id" if wid in out else "manifest_invalid","detail":f"line_{n}"}); ok=False; continue
        out[wid]=v
    return out,ok

def _sidecar(path,ds,name):
    if not path.exists(): return None,True
    try: v=json.loads(path.read_text(encoding='utf-8')); return (v,True) if isinstance(v,dict) else (None,False)
    except (OSError,UnicodeError,ValueError,TypeError): ds.append({"code":"sidecar_malformed","detail":name}); return None,False

def _jsonl(path,ds,name):
    if not path.exists(): return [],True
    try: lines=path.read_text(encoding='utf-8').splitlines()
    except (OSError,UnicodeError): ds.append({"code":"sidecar_malformed","detail":name}); return [],False
    out=[]; ok=True
    for n,l in enumerate(lines,1):
        try: v=json.loads(l); out.append(v) if isinstance(v,dict) else (_ for _ in ()).throw(ValueError())
        except (ValueError,TypeError): ds.append({"code":"sidecar_malformed","detail":f"{name}_line_{n}"}); ok=False
    return out,ok

def _attempts(path,ds): return _jsonl(path,ds,'attempts')
def _ids(obj,key,ds,code):
    ids=obj.get(key) if obj else None
    if ids is None: return set()
    if not isinstance(ids,list) or any(not isinstance(x,str) for x in ids): ds.append({"code":code,"detail":key}); return set()
    return set(ids)

def _select(rows,scope,attempts):
    if scope is None:return rows,True
    if scope=='pending':return {k:v for k,v in rows.items() if v.get('status') not in {'archived','gone'}},True
    if scope=='failed':
        bad={str(a.get('work_id')) for a in attempts if a.get('outcome') in {'failed','error'}}; return {k:v for k,v in rows.items() if k in bad},True
    toks=scope.replace(',',' ').split(); out={}
    for t in toks:
        matches={k:v for k,v in rows.items() if k==t or str(v.get('bvid'))==t}
        if not matches:return {},False
        out.update(matches)
    return out,True

def _category(s): return 'transcript' if s in {'archived','subtitle_done','asr_done'} else 'audio' if s in {'needs_audio','audio_ok'} else 'unavailable' if s=='gone' else 'metadata'
def _artifact(root,e):
    if e.get('status')!='archived': return False
    for p in (e.get('srt_path'),e.get('txt_path'),e.get('md_path')):
        if isinstance(p,str) and (root/p).is_file(): return True
    return False
