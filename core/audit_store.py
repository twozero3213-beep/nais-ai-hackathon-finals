"""Canonical persistent audit ledger and reproducible execution attempts.

case31 REPRODUCIBILITY LEDGER
FAILURE: case30 content-addressed execution IDs included result data.
RISK: the same scientific inputs producing different outputs were not recognised as a
non-deterministic reproduction failure.
WHY: inputs identify the reproduction target; each run is an attempt; output is separately hashed.
CHANGE: SQLite remains the canonical ledger. reproduction_key, attempt_id and result_hash are
separate, runtime environment is snapshotted, and conflicting result hashes are flagged.
REGRESSION: tests/test_case31.py
"""
from datetime import datetime,timezone
import json,sqlite3,uuid
from pathlib import Path
from .paths import AUDIT_DB_PATH
from .reproducibility import canonical_json,hash_json,runtime_environment,reproduction_key
EVENT_LABELS={'CLAIM_EXTRACTED':'주장 추출','EVIDENCE_PROPOSED':'근거 후보 제안','EVIDENCE_SELECTED':'근거 선택','EVIDENCE_CONFIRMED':'근거 확정','METHOD_PROPOSED':'분석방법 후보 제안','METHOD_SELECTED':'분석방법 선택','METHOD_CONFIRMED':'분석방법 확정','ANALYSIS_POLICY_CONFIRMED':'분석 명세 확정','CONTRACT_CREATED':'검증 계약 생성','CONTRACT_BLOCKED':'실행 차단','CONTRACT_EXECUTED':'결정론적 재실행','REPRODUCTION_RESULT':'재현 결과','NONDETERMINISM_DETECTED':'결정론 불일치 감지','VALUE_REVISED':'보고값 수정','REVERIFIED':'재검증','APPROVED':'최종 승인','SCOPE_SPEC_CONFIRMED':'범위 검증 조건 확정'}
# [수정: 가상 검토 역할1·6] 2026-09-28 case81: 실제 앱에서 쓰는 사건을 등록하여 업로드·실행·승인 취소의 감사 기록 실패를 방지.
EVENT_LABELS.update({'ANALYSIS_STARTED':'분석 시작','ANALYSIS_FAILED':'분석 실패','EXECUTION_SNAPSHOT':'실행 스냅샷','APPROVAL_REVOKED':'승인 해제'})

# [작성: 가상 검토 역할1·4·5] 2026-09-28 case81: 기존 두 원장의 행 전체를 공통 체인에 결속하며 과거 행은 검증되지 않은 이관 기준점으로 명시.
def _ledger_hash(previous,table,key,payload,legacy):
    return hash_json([previous,table,str(key),json.loads(payload),int(legacy)])

# [작성: 가상 검토 역할1] 2026-09-28 case81: SQL 트리거와 Python 검증이 같은 행 JSON 표현을 사용.
def _row_json(*fields):
    return canonical_json(dict(zip(fields[::2],fields[1::2])))
def sha256_json(v): return hash_json(v)
def _now(): return datetime.now(timezone.utc).isoformat(timespec='milliseconds')
class AuditStore:
    def __init__(self,path=None):
        self.path=str(Path(path or AUDIT_DB_PATH).resolve());Path(self.path).parent.mkdir(parents=True,exist_ok=True);self.con=sqlite3.connect(self.path,check_same_thread=False);self.con.execute('PRAGMA journal_mode=WAL');self.con.execute('PRAGMA foreign_keys=ON')
        # [수정: 가상 검토 역할1·5] 2026-09-28 case81: 쓰기 잠금으로 별도 세션의 체인 머리 경쟁을 직렬화; SQL 직접 삽입도 동일 해시 트리거를 통과.
        self.con.execute('PRAGMA busy_timeout=5000')
        self.con.create_function('eg_ledger_hash',5,_ledger_hash,deterministic=True)
        self.con.create_function('eg_row_json',-1,_row_json,deterministic=True)
        self.con.execute('''CREATE TABLE IF NOT EXISTS lifecycle(id INTEGER PRIMARY KEY,at TEXT NOT NULL,claim_id TEXT NOT NULL,event TEXT NOT NULL,actor TEXT NOT NULL,actor_id TEXT,detail TEXT,source TEXT,app_version TEXT,engine_version TEXT,dataset_hash TEXT,event_key TEXT UNIQUE)''')
        self.con.execute('''CREATE TABLE IF NOT EXISTS execution_attempt(attempt_id TEXT PRIMARY KEY,at TEXT NOT NULL,reproduction_key TEXT NOT NULL,claim_id TEXT NOT NULL,contract_hash TEXT NOT NULL,dataset_hash TEXT NOT NULL,result_hash TEXT NOT NULL,app_version TEXT NOT NULL,engine_version TEXT NOT NULL,runtime_json TEXT NOT NULL,claim_json TEXT NOT NULL,contract_json TEXT NOT NULL,analysis_spec_json TEXT NOT NULL,result_json TEXT NOT NULL,nondeterministic INTEGER NOT NULL DEFAULT 0)''')
        self.con.execute('CREATE INDEX IF NOT EXISTS idx_attempt_rk ON execution_attempt(reproduction_key)')
        # case73 AUDIT IMMUTABILITY: reproducibility claims require the canonical ledger to be append-only.
        # Test isolation must use a disposable DB, never DELETE production provenance.
        self.con.execute("CREATE TRIGGER IF NOT EXISTS lifecycle_no_update BEFORE UPDATE ON lifecycle BEGIN SELECT RAISE(ABORT,'lifecycle is append-only'); END")
        self.con.execute("CREATE TRIGGER IF NOT EXISTS lifecycle_no_delete BEFORE DELETE ON lifecycle BEGIN SELECT RAISE(ABORT,'lifecycle is append-only'); END")
        self.con.execute("CREATE TRIGGER IF NOT EXISTS execution_no_update BEFORE UPDATE ON execution_attempt BEGIN SELECT RAISE(ABORT,'execution_attempt is append-only'); END")
        self.con.execute("CREATE TRIGGER IF NOT EXISTS execution_no_delete BEFORE DELETE ON execution_attempt BEGIN SELECT RAISE(ABORT,'execution_attempt is append-only'); END")
        self.con.commit()
        self._initialize_chain()

    # [작성: 가상 검토 역할1·4·5] 2026-09-28 case81: 원본 행을 변경하지 않고 최초 이관을 한 트랜잭션으로 수행; 이후 행 누락을 재이관으로 숨기지 않음.
    def _initialize_chain(self):
        with self.con:
            self.con.execute('BEGIN IMMEDIATE')
            existed=self.con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ledger_hash_chain'").fetchone()
            self.con.execute('''CREATE TABLE IF NOT EXISTS ledger_hash_chain(seq INTEGER PRIMARY KEY,table_name TEXT NOT NULL CHECK(table_name IN('lifecycle','execution_attempt')),record_key TEXT NOT NULL,row_json TEXT NOT NULL,legacy_baseline INTEGER NOT NULL DEFAULT 0 CHECK(legacy_baseline IN(0,1)),prev_hash TEXT NOT NULL,event_hash TEXT NOT NULL CHECK(length(event_hash)=64),UNIQUE(table_name,record_key))''')
            self.con.execute("CREATE TRIGGER IF NOT EXISTS ledger_chain_no_update BEFORE UPDATE ON ledger_hash_chain BEGIN SELECT RAISE(ABORT,'ledger chain is append-only'); END")
            self.con.execute("CREATE TRIGGER IF NOT EXISTS ledger_chain_no_delete BEFORE DELETE ON ledger_hash_chain BEGIN SELECT RAISE(ABORT,'ledger chain is append-only'); END")
            self.con.execute("""CREATE TRIGGER IF NOT EXISTS ledger_chain_check BEFORE INSERT ON ledger_hash_chain BEGIN
                SELECT CASE WHEN NEW.prev_hash!=COALESCE((SELECT event_hash FROM ledger_hash_chain ORDER BY seq DESC LIMIT 1),'') THEN RAISE(ABORT,'ledger prev_hash mismatch') END;
                SELECT CASE WHEN NEW.event_hash!=eg_ledger_hash(NEW.prev_hash,NEW.table_name,NEW.record_key,NEW.row_json,NEW.legacy_baseline) THEN RAISE(ABORT,'ledger event_hash mismatch') END;
            END""")
            for table,key in (('lifecycle','id'),('execution_attempt','attempt_id')):
                columns=[row[1] for row in self.con.execute(f'PRAGMA table_info({table})')]
                if not existed:
                    for row in self.con.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall():
                        payload=dict(zip(columns,row));previous=self.con.execute('SELECT event_hash FROM ledger_hash_chain ORDER BY seq DESC LIMIT 1').fetchone();previous=previous[0] if previous else ''
                        self.con.execute('INSERT INTO ledger_hash_chain(table_name,record_key,row_json,legacy_baseline,prev_hash,event_hash) VALUES(?,?,?,?,?,?)',(table,str(payload[key]),canonical_json(payload),1,previous,_ledger_hash(previous,table,payload[key],canonical_json(payload),1)))
                fields=','.join(f"'{column}',NEW.{column}" for column in columns)
                previous="COALESCE((SELECT event_hash FROM ledger_hash_chain ORDER BY seq DESC LIMIT 1),'')"
                self.con.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_hash_insert AFTER INSERT ON {table} BEGIN
                    INSERT INTO ledger_hash_chain(table_name,record_key,row_json,legacy_baseline,prev_hash,event_hash)
                    VALUES('{table}',CAST(NEW.{key} AS TEXT),eg_row_json({fields}),0,{previous},eg_ledger_hash({previous},'{table}',NEW.{key},eg_row_json({fields}),0));
                END""")

    # [작성: 가상 검토 역할4·7] 2026-09-28 case81: 체인 연속성·해시·원본 행 일치·누락을 모두 검증; DB 전체 교체는 외부 기준점 없이는 감지할 수 없음.
    def verify_audit_chain(self):
        with self.con:
            self.con.execute('BEGIN')
            previous='';seen=set()
            for table,key,payload,legacy,ph,eh in self.con.execute('SELECT table_name,record_key,row_json,legacy_baseline,prev_hash,event_hash FROM ledger_hash_chain ORDER BY seq'):
                try:
                    if ph!=previous or eh!=_ledger_hash(previous,table,key,payload,legacy):return False
                    pk='id' if table=='lifecycle' else 'attempt_id'
                    cursor=self.con.execute(f'SELECT * FROM {table} WHERE {pk}=?',(key,));row=cursor.fetchone()
                    if row is None or json.loads(payload)!=dict(zip((d[0] for d in cursor.description),row)):return False
                except (ValueError,TypeError,sqlite3.Error):return False
                seen.add((table,key));previous=eh
            return len(seen)==sum(self.con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in ('lifecycle','execution_attempt'))

    # [작성: 가상 검토 역할2·6] 2026-09-28 case81: 실제 앱 승인과 취소의 마지막 영속 사건을 데이터셋별로 조회.
    def approval_state(self,claim_id,dataset_hash):
        row=self.con.execute("SELECT event,detail,source FROM lifecycle WHERE claim_id=? AND dataset_hash=? AND event IN('APPROVED','APPROVAL_REVOKED') ORDER BY id DESC LIMIT 1",(claim_id,dataset_hash)).fetchone()
        return dict(zip(('event','detail','source'),row)) if row else None
    @staticmethod
    def _key(claim_id,event,actor,detail,source,dataset_hash): return hash_json([claim_id,event,actor,detail or '',source or '',dataset_hash or ''])
    # [수정: 전문가4] 2026-09-25 case39
    # 종류: 오류수정 | 재현 방법: 같은 승인 사건을 다른 검토자가 기록.
    # 변경 전: actor_id 없는 중복 키 / 변경 후: actor_id를 포함.
    # 왜: 두 사람의 검토를 하나로 합치지 않음 / 영향: 기존 행은 보존.
    def append(self,claim_id,event,*,actor='SYSTEM',actor_id='',detail='',source='',app_version='',engine_version='',dataset_hash=''):
        if event not in EVENT_LABELS: raise ValueError(f'unknown lifecycle event: {event}')
        # [수정: 가상 검토 역할1·6] 2026-09-28 case81: 외부 승인 트랜잭션에 참여하고 독립 쓰기는 실패 시 롤백; 해시 트리거와 원본은 함께 저장.
        owned=not self.con.in_transaction
        at=_now();key=hash_json([self._key(claim_id,event,actor,detail,source,dataset_hash),actor_id])
        try:
            self.con.execute('''INSERT OR IGNORE INTO lifecycle(at,claim_id,event,actor,actor_id,detail,source,app_version,engine_version,dataset_hash,event_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(at,claim_id,event,actor,actor_id,str(detail or ''),str(source or ''),app_version,engine_version,dataset_hash,key))
            if owned:self.con.commit()
        except Exception:
            if owned:self.con.rollback()
            raise
        return key
    def record_execution(self,*,claim_id,claim_snapshot,contract_snapshot,analysis_spec_snapshot,result_snapshot,dataset_hash,app_version,engine_version,runtime_snapshot=None,random_seed=None):
        runtime_snapshot=runtime_snapshot or runtime_environment(random_seed=random_seed)
        contract_hash=hash_json(contract_snapshot);result_hash=hash_json(result_snapshot)
        rk=reproduction_key(claim_snapshot=claim_snapshot,contract_snapshot=contract_snapshot,analysis_spec_snapshot=analysis_spec_snapshot,dataset_hash=dataset_hash,engine_version=engine_version,runtime_snapshot=runtime_snapshot)
        # Every real run is an attempt. Unlike case30, identical reruns are retained for reproducibility evidence.
        aid='AT-'+uuid.uuid4().hex[:20];at=_now()
        # case73 DML ATOMICITY: an execution and its nondeterminism audit event are one logical action.
        # Committing them separately can leave a reproducibility attempt without the event that explains it.
        with self.con:
            # [수정: 가상 검토 역할1·2·7] 2026-09-28 case81: 비교·삽입·승인 무효화·변조 감지 체인을 같은 쓰기 잠금 안에서 실행.
            self.con.execute('BEGIN IMMEDIATE')
            previous={r[0] for r in self.con.execute('SELECT result_hash FROM execution_attempt WHERE reproduction_key=?',(rk,)).fetchall()}
            nondeterministic=bool(previous and result_hash not in previous)
            self.con.execute('''INSERT INTO execution_attempt(attempt_id,at,reproduction_key,claim_id,contract_hash,dataset_hash,result_hash,app_version,engine_version,runtime_json,claim_json,contract_json,analysis_spec_json,result_json,nondeterministic) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(aid,at,rk,claim_id,contract_hash,dataset_hash,result_hash,app_version,engine_version,canonical_json(runtime_snapshot),canonical_json(claim_snapshot),canonical_json(contract_snapshot),canonical_json(analysis_spec_snapshot),canonical_json(result_snapshot),int(nondeterministic)))
            approval=self.approval_state(claim_id,dataset_hash)
            if approval and approval['event']=='APPROVED':
                self.append(claim_id,'APPROVAL_REVOKED',detail='새 실행으로 이전 승인 실행 결속이 해제되었습니다.',source=aid,app_version=app_version,engine_version=engine_version,dataset_hash=dataset_hash)
            if nondeterministic:
                detail=f'{rk}: result hash changed'; actor='ENGINE'; actor_id='ENGINE'; event='NONDETERMINISM_DETECTED'; source=aid
                key=hash_json([self._key(claim_id,event,actor,detail,source,dataset_hash),actor_id])
                self.con.execute('''INSERT OR IGNORE INTO lifecycle(at,claim_id,event,actor,actor_id,detail,source,app_version,engine_version,dataset_hash,event_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(_now(),claim_id,event,actor,actor_id,detail,source,app_version,engine_version,dataset_hash,key))
        return {'attempt_id':aid,'execution_id':rk,'reproduction_key':rk,'contract_hash':contract_hash,'result_hash':result_hash,'nondeterministic':nondeterministic,'at':at,'runtime':runtime_snapshot}
    # [수정: 전문가4] 2026-09-23 case38
    # 종류: 오류수정
    # 재현 방법: 서로 다른 PDF/CSV가 모두 C-01을 만들면 for_claim('C-01')이 두 데이터셋의 계보를 함께 반환했다.
    # 변경 전: lifecycle/execution 조회가 claim_id만 조건으로 사용.
    # 변경 후: dataset_hash가 주어지면 claim_id + dataset_hash로 조회하고, 생략 시 기존 호환 동작 유지.
    # 왜: Claim ID는 문서 내부 식별자이므로 데이터셋 경계를 넘는 전역 키가 아니다.
    # 영향: 현재 Workspace의 Audit Trail과 재현 원장이 다른 데이터셋 기록을 섞지 않음. 기존 호출 호환성은 유지.
    def for_claim(self,claim_id,dataset_hash=None):
        sql='''SELECT at,claim_id,event,actor,actor_id,detail,source,app_version,engine_version,dataset_hash FROM lifecycle WHERE claim_id=?'''
        params=[claim_id]
        if dataset_hash is not None: sql+=' AND dataset_hash=?';params.append(dataset_hash)
        sql+=' ORDER BY id'
        cur=self.con.execute(sql,tuple(params));cols=['at','claim_id','event','actor','actor_id','detail','source','app_version','engine_version','dataset_hash'];out=[]
        for row in cur.fetchall():d=dict(zip(cols,row));d['label']=EVENT_LABELS.get(d['event'],d['event']);out.append(d)
        return out
    def attempts_for_claim(self,claim_id,dataset_hash=None):
        sql='''SELECT attempt_id,at,reproduction_key,claim_id,contract_hash,dataset_hash,result_hash,app_version,engine_version,runtime_json,claim_json,contract_json,analysis_spec_json,result_json,nondeterministic FROM execution_attempt WHERE claim_id=?'''
        params=[claim_id]
        if dataset_hash is not None: sql+=' AND dataset_hash=?';params.append(dataset_hash)
        # [수정: 가상 검토 역할2·7] 2026-09-28 case81: 동일 밀리초 실행은 실제 삽입 순서로 최신 실행을 결정.
        sql+=' ORDER BY rowid'
        cur=self.con.execute(sql,tuple(params));cols=['attempt_id','at','reproduction_key','claim_id','contract_hash','dataset_hash','result_hash','app_version','engine_version','runtime_json','claim_json','contract_json','analysis_spec_json','result_json','nondeterministic'];out=[dict(zip(cols,r)) for r in cur.fetchall()]
        for d in out: d['execution_id']=d['reproduction_key']  # case30 compatibility alias; case31 UI should prefer attempt_id.
        return out
    def executions_for_claim(self,claim_id,dataset_hash=None):
        # case30 compatibility view: one row per reproduction target. case31 callers that audit
        # repeated attempts must use attempts_for_claim().
        out=[];seen=set()
        for d in self.attempts_for_claim(claim_id,dataset_hash=dataset_hash):
            if d['reproduction_key'] not in seen: out.append(d);seen.add(d['reproduction_key'])
        return out
    def clear(self):
        raise PermissionError('canonical audit ledger is append-only; use a disposable test database for isolation')
