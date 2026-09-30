"""case80 canonical persistence service with atomic audit hash-chain."""
from __future__ import annotations
import hashlib,json,sqlite3,uuid
from datetime import datetime,timezone
from pathlib import Path
from .rbac import require_permission

def _now(): return datetime.now(timezone.utc).isoformat(timespec='milliseconds')
def _j(v): return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str)
def _h(v): return hashlib.sha256(_j(v).encode()).hexdigest()
def _event_hash(prev, fields): return hashlib.sha256((prev+'|'+_j(fields)).encode()).hexdigest()
def _sql_audit_hash(prev,entity_type,entity_id,event_type,actor_id,payload_json,app_version,engine_version,created_at):
    try: payload=json.loads(payload_json)
    except Exception: payload=payload_json
    fields={'entity_type':entity_type,'entity_id':entity_id,'event_type':event_type,'actor_id':actor_id,'payload':payload,'app_version':app_version,'engine_version':engine_version,'created_at':created_at}
    return _event_hash(prev,fields)

class CanonicalService:
    def __init__(self,path,schema_path=None):
        self.path=str(Path(path)); Path(self.path).parent.mkdir(parents=True,exist_ok=True)
        self.con=sqlite3.connect(self.path)
        # [수정: 0 이영 · Codex] 2026-10-01 03:12 KST — 누락·잘못된 스키마 초기화가 열린 연결을 남겨 Windows에서 임시 DB 삭제가 실패했다. 실패 시 연결을 닫고 원 예외를 유지한다.
        try:
            self.con.create_function('eg_audit_hash',9,_sql_audit_hash,deterministic=True); self.con.execute('PRAGMA foreign_keys=ON'); self.con.execute('PRAGMA busy_timeout=5000'); self.con.execute('PRAGMA journal_mode=WAL')
            schema_path=schema_path or Path(__file__).resolve().parents[1]/'db'/'schema_case80.sql'
            self.con.executescript(Path(schema_path).read_text(encoding='utf-8')); self.con.commit()
        except Exception:
            self.con.close()
            raise
    def _audit(self,entity_type,entity_id,event_type,actor_id,payload,app_version,engine_version,created_at):
        prev=self.con.execute('SELECT event_hash FROM audit_events ORDER BY audit_id DESC LIMIT 1').fetchone(); prev=prev[0] if prev else ''
        fields={'entity_type':entity_type,'entity_id':entity_id,'event_type':event_type,'actor_id':actor_id,'payload':payload,'app_version':app_version,'engine_version':engine_version,'created_at':created_at}
        eh=_event_hash(prev,fields)
        self.con.execute('INSERT INTO audit_events(entity_type,entity_id,event_type,actor_id,payload_json,app_version,engine_version,created_at,prev_hash,event_hash) VALUES(?,?,?,?,?,?,?,?,?,?)',(entity_type,entity_id,event_type,actor_id,_j(payload),app_version,engine_version,created_at,prev,eh))
    def verify_audit_chain(self):
        prev=''
        for row in self.con.execute('SELECT entity_type,entity_id,event_type,actor_id,payload_json,app_version,engine_version,created_at,prev_hash,event_hash FROM audit_events ORDER BY audit_id'):
            et,eid,evt,actor,payload,app,eng,created,ph,eh=row
            try: payload_obj=json.loads(payload)
            except Exception:return False
            fields={'entity_type':et,'entity_id':eid,'event_type':evt,'actor_id':actor,'payload':payload_obj,'app_version':app,'engine_version':eng,'created_at':created}
            if ph!=prev or eh!=_event_hash(prev,fields): return False
            prev=eh
        return True
    def record_execution(self,*,attempt_id=None,contract_id,dataset_id,reproduction_key,result,app_version,engine_version,nondeterministic=False,actor_id=None):
        aid=attempt_id or 'AT-'+uuid.uuid4().hex; now=_now(); rh=_h(result)
        with self.con:
            self.con.execute('BEGIN IMMEDIATE')
            self.con.execute('INSERT INTO execution_attempts(attempt_id,contract_id,dataset_id,reproduction_key,result_hash,result_json,app_version,engine_version,created_at,nondeterministic) VALUES(?,?,?,?,?,?,?,?,?,?)',(aid,contract_id,dataset_id,reproduction_key,rh,_j(result),app_version,engine_version,now,int(nondeterministic)))
            self._audit('EXECUTION',aid,'EXECUTED',actor_id,{'result_hash':rh,'reproduction_key':reproduction_key},app_version,engine_version,now)
        return aid
    def approve(self,*,review_id,approver_id,role,note,app_version,engine_version):
        require_permission(role,'approve'); ap='AP-'+uuid.uuid4().hex; now=_now()
        with self.con:
            self.con.execute('BEGIN IMMEDIATE')
            self.con.execute('INSERT INTO approvals(approval_id,review_id,approver_id,note,created_at,status) VALUES(?,?,?,?,?,?)',(ap,review_id,approver_id,note,now,'ACTIVE'))
            self._audit('APPROVAL',ap,'APPROVED',approver_id,{'review_id':review_id},app_version,engine_version,now)
        return ap
    def integrity(self):
        return {'integrity':self.con.execute('PRAGMA integrity_check').fetchone()[0],'foreign_key_violations':self.con.execute('PRAGMA foreign_key_check').fetchall(),'foreign_keys':self.con.execute('PRAGMA foreign_keys').fetchone()[0],'audit_chain':self.verify_audit_chain()}
