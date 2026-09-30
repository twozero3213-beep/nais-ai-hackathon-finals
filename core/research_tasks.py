"""case95 persistent, actor-isolated research tasks. No LLM, paid API, or approval.

Daily schedules require an external runner to call run_due(). Interrupted work
is never retried silently: the owner can recover a run after 15 minutes. An old
worker's result cannot replace a recovered run. Local DB access is trusted;
SHA256 detects corrupt records, not a malicious administrator replacing hashes.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import uuid

from core.paths import DATA_DIR
from core.research_agent import search_evidence, prepare_evidence
from core.research_corpus import strict_json
from core.research_watch import fetch_metadata, compare_metadata
from core.public_fulltext import fetch_selected_fulltext

KST = timezone(timedelta(hours=9))
MAX_JSON_BYTES = 256 * 1024
STALE_AFTER = timedelta(minutes=15)
STATES = {'PENDING', 'RUNNING', 'CHECKED_PARTIAL', 'NEEDS_ATTENTION'}
SECRET_PATTERN = re.compile(r'sk-(?:ant-)?[A-Za-z0-9_-]{6,}|AKIA[A-Z0-9]{16}|github_pat_[A-Za-z0-9_]{8,}|gh[pousr]_[A-Za-z0-9]{20,}|Bearer\s+\S+|(?:api[_ -]?key|password|secret|token)\s*[=:]\s*\S+', re.I)
SECRET_FIELDS = {'api_key', 'apikey', 'password', 'secret', 'access_token', 'authorization'}


# [작성: 과제 백엔드] 2026-09-29 case95 / UTC주입 가능 시계→재현가능 KST예약 / 검증: test_case95_tasks 일일시각.
def utc_now():
    return datetime.now(timezone.utc)


# [작성: 과제 백엔드] 2026-09-29 case95 / 지연import등록목록→고정case허용 / 검증: 미등록 ID차단.
def list_cases():
    from core.research_cases import list_cases as catalog
    return catalog(include_extensions=True)


# [작성: 과제 백엔드] 2026-09-29 case95 / 등록case→매회 실제재계산 / 검증: 모의fresh2회·실제8쌍.
def run_case(case_id):
    from core.research_cases import run_case as run
    return run(case_id)


# [작성: 과제 백엔드] 2026-09-29 case95 / JSON→유한크기·유한숫자·비밀패턴차단 / 검증: Nan·키·과대출력.
def _json(value):
    count = 0
    def visit(item, depth=0):
        nonlocal count
        count += 1
        if depth > 12 or count > 12000:
            raise ValueError('CONTENT_LIMIT')
        if item is None or type(item) in (bool, int):
            if type(item) is int and abs(item) > 10**30:
                raise ValueError('CONTENT_LIMIT')
        elif type(item) is float:
            if not math.isfinite(item): raise ValueError('INVALID_JSON_NUMBER')
        elif isinstance(item, str):
            if len(item) > 16000 or SECRET_PATTERN.search(item): raise ValueError('UNSAFE_OR_OVERSIZED_CONTENT')
        elif isinstance(item, list):
            if len(item) > 1000: raise ValueError('CONTENT_LIMIT')
            for child in item: visit(child, depth+1)
        elif isinstance(item, dict):
            if len(item) > 1000: raise ValueError('CONTENT_LIMIT')
            for key, child in item.items():
                if not isinstance(key, str) or key.casefold() in SECRET_FIELDS: raise ValueError('UNSAFE_CONTENT_FIELD')
                visit(key, depth+1); visit(child, depth+1)
        else: raise ValueError('INVALID_JSON_TYPE')
    visit(value)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(raw.encode('utf-8')) > MAX_JSON_BYTES: raise ValueError('CONTENT_LIMIT')
    return raw, hashlib.sha256(raw.encode('utf-8')).hexdigest()


# [작성: 과제 백엔드] 2026-09-29 case95 / 저장bytes+hash→독립snapshot / 검증: DB직접변조·중복키차단.
def _decode(raw, digest):
    try:
        if not isinstance(raw, str) or len(raw.encode()) > MAX_JSON_BYTES or hashlib.sha256(raw.encode()).hexdigest() != digest:
            raise ValueError()
        value = strict_json(raw)
        _json(value)
        return value
    except Exception:
        raise ValueError('STORED_DATA_INVALID') from None


# [작성: 과제 백엔드] 2026-09-29 case95 / 문자열→필드상한·제어/비밀검사 / 검증: actor격리·키패턴입력.
def _text(value, size, required=False):
    if not isinstance(value, str) or len(value) > size or (required and not value.strip()) or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ValueError('INVALID_TASK_INPUT')
    if SECRET_PATTERN.search(value): raise ValueError('SECRET_LIKE_INPUT_NOT_ALLOWED')
    return value.strip()


# [작성: 과제 백엔드] 2026-09-29 case95 / 시간옵션→KST최초미래시각 / 검증: bool·24시·오늘시각이미경과.
def _schedule(hour, now):
    if hour is None: return None
    if type(hour) is not int or not 0 <= hour <= 23: raise ValueError('INVALID_DAILY_HOUR')
    due = now.astimezone(KST).replace(hour=hour, minute=0, second=0, microsecond=0)
    if due <= now.astimezone(KST): due += timedelta(days=1)
    return due.astimezone(timezone.utc).isoformat()


# [작성: 과제 백엔드] 2026-09-29 case95 / DOI/case→공개등록범위 고정 / 검증: 임의case·논문혼합거부.
def _case(case_id, doi):
    if not case_id: return None
    cases = list_cases()
    selected = next((row for row in cases if row['id'] == case_id), None)
    if selected is None: raise ValueError('UNREGISTERED_CASE')
    if doi and doi != str(selected.get('doi', '')).lower(): raise ValueError('CASE_DOI_MISMATCH')
    return selected


def _checked_search(query, *, doi=None):
    """One bounded local search; never accept partial/truncated or mixed-DOI evidence."""
    evidence = search_evidence(query, limit=5, **({'doi': doi} if doi else {}))
    _json(evidence)
    if not isinstance(evidence, list) or len(evidence) > 5:
        raise ValueError('INVALID_SEARCH_RESULT')
    if evidence:
        prepared, truncated = prepare_evidence(evidence)
        if truncated or prepared != evidence or (doi and any(row['doi'].strip().lower() != doi for row in evidence)):
            raise ValueError('INVALID_SEARCH_RESULT')
    return evidence


class TaskStore:
    # [작성: 과제 백엔드] 2026-09-29 case95 / SQLite초기화→영속과제·이력 / 검증: 재접속·독립actor.
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else DATA_DIR / 'research_tasks_case95.db'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, actor TEXT NOT NULL, data_json TEXT NOT NULL,
                    data_sha256 TEXT NOT NULL, status TEXT NOT NULL, active_run TEXT, next_due TEXT);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), actor TEXT NOT NULL,
                    status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
                    report_json TEXT NOT NULL, report_sha256 TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS tasks_actor ON tasks(actor);
                CREATE INDEX IF NOT EXISTS tasks_due ON tasks(next_due);
                CREATE INDEX IF NOT EXISTS runs_task ON runs(task_id,actor);
                CREATE TABLE IF NOT EXISTS worker_runs (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL, started_at TEXT NOT NULL,
                    finished_at TEXT, last_activity_at TEXT NOT NULL,
                    processed_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0);
            ''')

    # [작성: 과제 백엔드] 2026-09-29 case95 / 짧은연결/txn→네트워크잠금없음 / 검증: concurrent slow검색중create.
    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try: yield conn
        finally:
            if conn.in_transaction: conn.rollback()
            conn.close()

    # [작성: 과제 백엔드] 2026-09-29 case95 / actor+ID→허용데이터만 조회 / 검증: unauthorized get/run deny.
    def _read(self, conn, actor, task_id, summary=False):
        row = conn.execute('SELECT id,actor,substr(data_json,1,?) data_json,data_sha256,status,active_run,next_due FROM tasks WHERE id=? AND actor=?',
                           (MAX_JSON_BYTES+1, task_id, actor)).fetchone()
        if row is None: raise PermissionError('TASK_NOT_FOUND_OR_NOT_OWNED')
        data = _decode(row['data_json'], row['data_sha256'])
        keys = {'id','actor','question','query','doi','case_id','daily_hour','next_due','created_at'}
        if not isinstance(data, dict) or set(data) != keys or data['id'] != row['id'] or data['actor'] != actor or data['next_due'] != row['next_due'] or row['status'] not in STATES:
            raise ValueError('STORED_DATA_INVALID')
        run_count = conn.execute('SELECT count(*) FROM runs WHERE task_id=? AND actor=?',(task_id,actor)).fetchone()[0]
        if run_count > 1000: raise ValueError('STORED_DATA_INVALID')
        if summary:
            stored = conn.execute('SELECT id,status,started_at,finished_at FROM runs WHERE task_id=? AND actor=? ORDER BY rowid DESC LIMIT 1',(task_id,actor)).fetchone()
            latest = dict(stored,approved=False) if stored else None
            if (latest and latest['status'] != row['status']) or (not latest and row['status'] != 'PENDING'):
                raise ValueError('STORED_DATA_INVALID')
            return dict(data,status=row['status'],latest_run=latest,runs=[],run_count=run_count,history_truncated=run_count>0)
        reports = []
        # case95: full history stays in SQLite; each response holds <=20 reports (~5MiB maximum), test history retention.
        for stored in conn.execute('SELECT id,status,started_at,finished_at,substr(report_json,1,?) report_json,report_sha256 FROM runs WHERE task_id=? AND actor=? ORDER BY rowid DESC LIMIT 20',
                                   (MAX_JSON_BYTES+1, task_id, actor)):
            report = _decode(stored['report_json'], stored['report_sha256'])
            if (not isinstance(report, dict) or report.get('id') != stored['id'] or report.get('task_id') != task_id
                    or report.get('actor') != actor or report.get('status') != stored['status']
                    or report.get('started_at') != stored['started_at'] or report.get('finished_at') != stored['finished_at']
                    or report.get('approved') is not False or report.get('status') not in STATES):
                raise ValueError('STORED_DATA_INVALID')
            reports.append(report)
        reports.reverse()
        latest = reports[-1] if reports else None
        if (latest and latest['status'] != row['status']) or (not latest and row['status'] != 'PENDING'):
            raise ValueError('STORED_DATA_INVALID')
        if (row['status'] == 'RUNNING' and (not latest or latest['id'] != row['active_run'])) or (row['status'] != 'RUNNING' and row['active_run'] is not None):
            raise ValueError('STORED_DATA_INVALID')
        return dict(data,status=row['status'],latest_run=latest,runs=reports,run_count=run_count,history_truncated=run_count>len(reports))

    # [작성: 과제 백엔드] 2026-09-29 case95 / 명시과제→개인영속기록 / 검증: 상한·공개DOI·case일치.
    def create(self, actor, question, query='', doi='', case_id='', daily_hour=None):
        actor = _text(actor,128,True); question = _text(question,1000,True)
        query = _text(query,1000); doi = _text(doi,200).lower(); case_id = _text(case_id,80)
        if doi and not re.fullmatch(r'10\.\d{4,9}/[^\s]+',doi): raise ValueError('INVALID_DOI')
        _case(case_id,doi)
        now = utc_now(); task_id = uuid.uuid4().hex
        data = dict(id=task_id,actor=actor,question=question,query=query,doi=doi,case_id=case_id,
                    daily_hour=daily_hour,next_due=_schedule(daily_hour,now),created_at=now.isoformat())
        raw,digest = _json(data)
        with self._connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT count(*) FROM tasks WHERE actor=?',(actor,)).fetchone()[0] >= 1000:
                raise ValueError('TASK_CAPACITY_REACHED')
            conn.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,?)',(task_id,actor,raw,digest,'PENDING',None,data['next_due']))
            conn.commit()
        return self.get(actor,task_id)

    # [작성: 과제 백엔드] 2026-09-29 case95 / actor→이력목록 / 검증: 두actor서로누락.
    def list(self, actor):
        actor = _text(actor,128,True)
        with self._connection() as conn:
            conn.execute('BEGIN')
            ids = [row[0] for row in conn.execute('SELECT id FROM tasks WHERE actor=? ORDER BY rowid DESC',(actor,))]
            if len(ids) > 1000: raise ValueError('STORED_DATA_INVALID')
            return [self._read(conn,actor,task_id,summary=True) for task_id in ids]

    # [작성: 과제 백엔드] 2026-09-29 case95 / actor+ID→일관snapshot / 검증: 저장변조시safe차단.
    def get(self, actor, task_id):
        actor = _text(actor,128,True); task_id = _text(task_id,64,True)
        with self._connection() as conn:
            conn.execute('BEGIN')
            return self._read(conn,actor,task_id)

    # [작성: 과제 백엔드] 2026-09-29 case95 / hour옵션→미래예약변경/해제 / 검증: 최초일일시각·None.
    def update_schedule(self, actor, task_id, daily_hour):
        actor = _text(actor,128,True)
        with self._connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            task = self._read(conn,actor,task_id)
            data = {k:v for k,v in task.items() if k not in {'status','latest_run','runs','run_count','history_truncated'}}
            data.update(daily_hour=daily_hour,next_due=_schedule(daily_hour,utc_now()))
            raw,digest = _json(data)
            conn.execute('UPDATE tasks SET data_json=?,data_sha256=?,next_due=? WHERE id=? AND actor=?',
                         (raw,digest,data['next_due'],task_id,actor)); conn.commit()
        return self.get(actor,task_id)

    # [작성: 과제 백엔드] 2026-09-29 case95 / 原子claim→단일RUNNING / 검증: 동시중복·두scheduler.
    def _claim(self, actor, task_id, due=False):
        actor = _text(actor,128,True)
        with self._connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            task = self._read(conn,actor,task_id); now = utc_now()
            if task['status'] == 'RUNNING': return None
            if due and (not task['next_due'] or datetime.fromisoformat(task['next_due']) > now): return None
            if task['run_count'] >= 1000: raise ValueError('RUN_HISTORY_CAPACITY_REACHED')
            report = dict(id=uuid.uuid4().hex,task_id=task_id,actor=actor,status='RUNNING',started_at=now.isoformat(),
                          finished_at=None,steps=[],evidence=[],metadata=None,calculation=None,known=[],
                          unknown=['검토 실행 중입니다. 과거 성공은 이번 실행 결과가 아닙니다.'],next_actions=[],approved=False,executed=False)
            raw,digest = _json(report)
            conn.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)',
                         (report['id'],task_id,actor,'RUNNING',report['started_at'],None,raw,digest))
            data = {k:v for k,v in task.items() if k not in {'status','latest_run','runs','run_count','history_truncated'}}
            data['next_due'] = _schedule(task['daily_hour'],now)
            raw,digest = _json(data)
            conn.execute('UPDATE tasks SET status=?,active_run=?,data_json=?,data_sha256=?,next_due=? WHERE id=? AND actor=?',
                         ('RUNNING',report['id'],raw,digest,data['next_due'],task_id,actor)); conn.commit()
        return task,report

    # [작성: 과제 백엔드] 2026-09-29 case95 / 완료보고+claim→조건저장 / 검증: 회복후늦은결과불승격.
    def _write(self, conn, actor, task_id, report):
        if report.get('actor') != actor or report.get('task_id') != task_id or report.get('approved') is not False or report.get('status') not in {'CHECKED_PARTIAL','NEEDS_ATTENTION'}:
            raise ValueError('INVALID_RUN_REPORT')
        raw,digest = _json(report)
        changed = conn.execute('UPDATE tasks SET status=?,active_run=NULL WHERE id=? AND actor=? AND status=? AND active_run=?',
                               (report['status'],task_id,actor,'RUNNING',report['id'])).rowcount
        if not changed: return False
        changed = conn.execute('UPDATE runs SET status=?,finished_at=?,report_json=?,report_sha256=? WHERE id=? AND task_id=? AND actor=? AND status=? AND started_at=?',
                               (report['status'],report['finished_at'],raw,digest,report['id'],task_id,actor,'RUNNING',report['started_at'])).rowcount
        if changed != 1: raise ValueError('STORED_DATA_INVALID')
        return True

    # [작성: 과제 백엔드] 2026-09-29 case95 / 저장txn분리→느린hook중락없음 / 검증: 새run+oldclaim불저장.
    def _save(self, actor, task_id, report):
        with self._connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            saved = self._write(conn,actor,task_id,report); conn.commit()
            return saved

    # [작성: 과제 백엔드] 2026-09-29 case95 / 최근20회밖 기준선도1보고만조회 / 검증: 21번실패뒤이전서지와비교.
    def _previous_metadata(self, actor, task_id):
        with self._connection() as conn:
            stored=conn.execute('''SELECT substr(report_json,1,?) report_json,report_sha256 FROM runs
                WHERE task_id=? AND actor=? AND CASE WHEN json_valid(report_json)
                    THEN json_type(report_json,'$.metadata.current') END='object'
                ORDER BY rowid DESC LIMIT 1''',(MAX_JSON_BYTES+1,task_id,actor)).fetchone()
        if not stored:return None
        report=_decode(stored['report_json'],stored['report_sha256'])
        if report.get('task_id')!=task_id or report.get('actor')!=actor or report.get('approved') is not False:
            raise ValueError('STORED_DATA_INVALID')
        return report['metadata']['current']

    # [작성: 과제 백엔드] 2026-09-29 case95 / 고정무료도구3단계→쉬운종합·실패보존 / 검증: 모의단계실패·fresh통합.
    def _perform(self, task, report, retrieve_fulltext=False):
        failed = False
        search_failed = False
        report['unknown'] = ['최종 사실 확증·분석 타당성·사람의 승인까지 확인한 결과가 아닙니다.']
        def step(role,status,detail):
            report['steps'].append(dict(role=role,status=status,detail=detail))
        try:
            evidence = _checked_search(task['query'] or task['question'])
            if not evidence: raise ValueError('NO_EVIDENCE')
            report['evidence'] = evidence
            report['known'].append(f'보관 원문에서 관련 조각 {len(evidence)}개를 찾았습니다. 원문 인용 위치를 함께 보존했습니다.')
            step('search','CHECKED','검증된 공개 원문 검색을 수행했습니다.')
        except Exception:
            # case95 2026-09-29: search index failure is separate from registered source quotations; no-match test.
            search_failed=True; step('search','NEEDS_ATTENTION','검색용 원문 색인에서 결과가 없거나 색인·연결 원문을 확인하지 못했습니다. 등록 계산의 원문 인용과는 별도입니다.')
            report['unknown'].append('첫 전체 검색에서 근거를 확보하지 못했습니다. 이후 추가 검색 결과와 등록 계산의 원문 인용은 별도이며, 관련 문헌이 없다는 뜻은 아닙니다.')
            report['next_actions'].append('검색용 원문 색인의 검색어를 좁히고 색인·연결 원문의 무결성을 확인하세요.')
        # case100: source DOI binds coverage; related papers remain useful but never cover the selected DOI.
        direct = [row for row in report['evidence'] if task['doi'] and row['doi'].strip().lower() == task['doi']]
        related = [row for row in report['evidence'] if row not in direct]
        # One conditional local recovery, no query invention, network expansion, or retry loop.
        if task['doi'] and not direct:
            try:
                recovered = _checked_search(task['query'] or task['question'], doi=task['doi'])
                if not recovered or {row['id'] for row in recovered} & {row['id'] for row in related}:
                    raise ValueError('NO_SELECTED_EVIDENCE')
                direct = recovered
                report['evidence'] = direct + related
                step('search_refinement','CHECKED','처음 검색에 선택 논문의 조각이 없어, 같은 검색어와 선택 DOI로 보관 원문을 한 번 더 확인했습니다.')
                report['known'].append(f'선택 DOI로 범위를 좁힌 추가 검색에서 직접 근거 {len(direct)}개를 확보했습니다. 내용의 타당성 판단은 별도입니다.')
            except Exception:
                step('search_refinement','NEEDS_ATTENTION','선택 DOI로 보관 원문을 한 번 더 확인했으나 사용할 직접 근거를 확보하지 못했습니다. 자동 재검색은 여기서 멈춥니다.')
        else:
            step('search_refinement','SKIPPED','선택 DOI가 없거나 직접 근거가 있어 추가 검색이 필요하지 않습니다.')
        fulltext = None
        if retrieve_fulltext and task['doi']:
            try:
                fulltext = fetch_selected_fulltext(task['doi'], task['query'] or task['question'])
                _json(fulltext)
                if (not isinstance(fulltext, dict) or fulltext.get('doi') != task['doi']
                        or fulltext.get('approved') is not False
                        or fulltext.get('status') not in {'EXCERPTS_RETRIEVED','NOT_AVAILABLE','LICENSE_UNCONFIRMED','NO_BODY_EXCERPTS'}):
                    raise ValueError()
                remote = fulltext.get('evidence')
                if not isinstance(remote, list):raise ValueError()
                if fulltext['status'] == 'EXCERPTS_RETRIEVED':
                    prepared, _ = prepare_evidence(remote)
                    if prepared != remote or any(row['doi'] != task['doi'] for row in remote):raise ValueError()
                    direct.extend(remote)
                    report['evidence'].extend(remote)
                    step('fulltext','CHECKED','명시 요청으로 Europe PMC OA 원문의 DOI·PMCID·라이선스를 대조하고 읽기 전용 조각을 확보했습니다. 전체 검토는 아닙니다.')
                else:
                    if remote:raise ValueError()
                    step('fulltext','NEEDS_ATTENTION','선택 DOI의 허용된 OA 원문 조각을 확보하지 못했습니다. 관련 문헌과 구분합니다.')
            except Exception:
                fulltext = dict(status='FAILED',doi=task['doi'],source='Europe PMC',evidence=[],approved=False)
                failed=True
                step('fulltext','NEEDS_ATTENTION','이번 OA 원문 조회·DOI·라이선스 확인에 실패했습니다. 이전 원문은 이번 근거로 재사용하지 않습니다.')
        else:
            step('fulltext','SKIPPED','OA 원문 조회는 별도 명시 버튼으로만 실행합니다. 기본·예약 실행은 추가 원문 네트워크 조회를 하지 않습니다.')
        report.update(direct_evidence=direct,related_evidence=related,
                      selected_paper=dict(doi=task['doi'] or None,
                          status=('EXCERPTS_NOT_REVIEWED' if direct else 'FULLTEXT_MISSING') if task['doi'] else 'NOT_SELECTED',
                          direct_count=len(direct),related_count=len(related),fulltext=fulltext,
                          scope='DOI가 같은 원문 조각만 직접 근거입니다. 다른 DOI는 관련 문헌이며 선택 논문 검토 범위에 합산하지 않습니다. 논문 전체 검토·자동 승인은 하지 않았습니다.'))
        if task['doi']:
            report['known'].append(f'선택 DOI 직접 근거 {len(direct)}개 · 관련 문헌 {len(related)}개입니다. 관련 문헌은 선택 논문 검토 범위에 포함하지 않습니다.')
            report['unknown'].append('선택 논문 전체 원문은 검토하지 않았습니다. 직접 조각의 존재도 내용 타당성·재현을 확인하지 않습니다.')
            if not direct:
                failed=True
                report['unknown'].insert(0,'선택 논문 원문 미확보·미검토: 이번 실행의 직접 근거는 0개입니다. 서지 조회와 다른 논문 근거는 선택 논문 내용 검토가 아닙니다.')
                report['next_actions'].insert(0,'선택 DOI의 무료 OA 원문 포함 실행을 요청하거나 DOI 링크의 원문을 직접 확인하세요. 공개 허용 원문·인용 위치를 확보한 뒤 다시 검토하세요. 유료 원문·임의 URL은 자동 다운로드하지 않습니다.')
        failed |= search_failed and not direct
        if task['doi']:
            try:
                current=fetch_metadata(task['doi']); _json(current)
                if not isinstance(current,dict) or current.get('doi')!=task['doi']:raise ValueError()
                previous=self._previous_metadata(task['actor'],task['id'])
                metadata=compare_metadata(current,previous); _json(metadata)
                if metadata.get('approved') is not False:raise ValueError()
                report['metadata']=metadata
                report['known'].append('선택한 DOI의 현재 공식 서지를 조회하고 이전 조회와 비교했습니다.')
                report['unknown'].append('서지 조회는 모든 철회·정정이나 논문 내용 변경을 탐지하지 못합니다.')
                step('metadata','CHECKED','선택 DOI만 무료 공식 서지 API에 전송했습니다.')
            except Exception:
                failed=True; step('metadata','NEEDS_ATTENTION','이번 DOI 서지를 확인하지 못했습니다. 과거 조회를 현재 결과로 사용하지 않습니다.')
                report['unknown'].append('이번 공식 서지 조회 결과는 없습니다.')
                report['next_actions'].append('DOI·무료 서지 API 연결을 확인한 뒤 다시 실행하세요.')
        else: step('metadata','SKIPPED','DOI를 선택하지 않아 외부 조회를 생략했습니다.')
        if task['case_id']:
            try:
                selected = _case(task['case_id'],task['doi'])
                calculation=run_case(task['case_id']); _json(calculation)
                if not isinstance(calculation,dict) or calculation.get('case_id')!=task['case_id'] or calculation.get('approved') is not False:
                    raise ValueError()
                if calculation.get('doi') != selected.get('doi'):raise ValueError()
                for field in ('known','unknown','next_actions'):
                    if not isinstance(calculation.get(field),list) or any(not isinstance(x,str) for x in calculation[field]):raise ValueError()
                report['calculation']=calculation
                for field in ('known','unknown','next_actions'): report[field].extend(calculation[field])
                # Reuse engine row decisions: receiving a report is not successful verification.
                # Fixed catalog yields nonempty rows; keep the existing empty-row legacy schema compatible.
                needs_attention = any(row.get('status') not in {'ARITHMETIC_MATCH', 'COEFFICIENT_MATCH'}
                                      for row in calculation.get('rows', []))
                failed |= needs_attention
                step('calculation','NEEDS_ATTENTION' if needs_attention else 'CHECKED',
                     '등록 계산에 차단·불일치·미확인 결과가 있습니다. 보고서의 비교 결과와 입력 조건을 확인하세요.' if needs_attention
                     else '선택 등록 사례를 이번 실행에서 다시 계산했습니다. 과거 계산을 재사용하지 않았습니다.')
            except Exception:
                failed=True; step('calculation','NEEDS_ATTENTION','등록 사례의 입력·소스·계산을 확인하지 못했습니다. 과거 성공을 현재 결과로 사용하지 않습니다.')
                report['unknown'].append('이번 등록 사례 계산 결과는 없습니다.')
                report['next_actions'].append('등록 원문·자료·소스 지문과 분석조건을 확인하고 다시 실행하세요.')
        else: step('calculation','SKIPPED','등록 사례를 선택하지 않아 실제 검산을 생략했습니다.')
        step('llm','SKIPPED','이 자동 과제 실행기는 LLM·유료 API를 호출하지 않습니다.')
        if not report['next_actions']: report['next_actions'].append('원문 문맥·계산조건·아직 미확인인 항목을 확인하세요.')
        report.update(status='NEEDS_ATTENTION' if failed else 'CHECKED_PARTIAL',finished_at=utc_now().isoformat())
        try: self._save(task['actor'],task['id'],report)
        except ValueError:
            report.update(status='NEEDS_ATTENTION',evidence=[],metadata=None,calculation=None,known=[],
                          direct_evidence=[],related_evidence=[],selected_paper=dict(doi=task['doi'] or None,status='REPORT_FAILED',direct_count=0,related_count=0,fulltext=None),
                          unknown=['보고서 저장 상한 또는 형식 검사를 통과하지 못했습니다.'],next_actions=['범위를 줄이고 다시 실행하세요.'])
            report['steps']=[dict(role='report',status='NEEDS_ATTENTION',detail='안전한 보고서만 저장하며 이전 성공을 재사용하지 않습니다.')]
            self._save(task['actor'],task['id'],report)
        return self.get(task['actor'],task['id'])

    # [작성: 과제 백엔드] 2026-09-29 case95 / 명시run→claim단일실행 / 검증: 실패재시도·동시요청.
    def run(self, actor, task_id, *, retrieve_fulltext=False):
        if type(retrieve_fulltext) is not bool:raise ValueError('INVALID_FULLTEXT_OPTION')
        claimed=self._claim(actor,task_id)
        return self._perform(*claimed,retrieve_fulltext=retrieve_fulltext) if claimed else self.get(actor,task_id)

    # case105: aggregate operational observations only; never return task/actor IDs or error text.
    # STALE means no activity for 15 minutes, not proof the process stopped or was terminated.
    def worker_health(self, actor=None):
        now = utc_now()
        if actor is not None: actor = _text(actor,128,True)
        with self._connection() as conn:
            conn.execute('BEGIN')
            latest = conn.execute('SELECT * FROM worker_runs ORDER BY rowid DESC LIMIT 1').fetchone()
            active, stale = conn.execute('''SELECT count(*), coalesce(sum(last_activity_at<=?),0)
                FROM worker_runs WHERE status='RUNNING' ''', ((now-STALE_AFTER).isoformat(),)).fetchone()
            # Public health exposes worker observations, never other owners' schedule counts/times.
            scheduled, due, next_due = (None, None, None)
            if actor is not None:
                scheduled, due, next_due = conn.execute('''SELECT count(*), coalesce(sum(next_due<=? AND status!='RUNNING'),0),
                    min(next_due) FROM tasks WHERE next_due IS NOT NULL AND actor=?''', (now.isoformat(),actor)).fetchone()
            last_failed = conn.execute("SELECT max(finished_at) FROM worker_runs WHERE status='FAILED'").fetchone()[0]
        return dict(status='STALE' if stale else 'RUNNING' if active else latest['status'] if latest else 'NEVER_RUN',
                    last_started_at=latest['started_at'] if latest else None,
                    last_finished_at=latest['finished_at'] if latest else None,
                    last_activity_at=latest['last_activity_at'] if latest else None,
                    last_failed_at=last_failed, processed_count=latest['processed_count'] if latest else 0,
                    failed_count=latest['failed_count'] if latest else 0, active_count=active, stale_count=stale,
                    scheduled_count=scheduled, due_count=due, next_due=next_due)

    # case105: persistent invocation state survives reopening; task claims remain the concurrency gate.
    def run_due(self):
        worker_id = uuid.uuid4().hex
        started = utc_now().isoformat()
        with self._connection() as conn:
            conn.execute('INSERT INTO worker_runs(id,status,started_at,last_activity_at) VALUES (?,?,?,?)',
                         (worker_id,'RUNNING',started,started))
        reports=[]
        failed = 0
        try:
            with self._connection() as conn:
                due=conn.execute('SELECT actor,id FROM tasks WHERE next_due<=? AND status!=? ORDER BY next_due LIMIT 20',
                                 (utc_now().isoformat(),'RUNNING')).fetchall()
            # ponytail: sequential batch <=20; parallel workers only if measured schedule backlog needs them.
            for actor,task_id in due:
                before = len(reports)
                try:
                    claimed=self._claim(actor,task_id,due=True)
                except ValueError as error:
                    # Invalid stored task is quarantined; do not starve later due work.
                    with self._connection() as conn:
                        conn.execute('BEGIN IMMEDIATE')
                        if error.args == ('RUN_HISTORY_CAPACITY_REACHED',):
                            # Valid data at capacity must keep its signed JSON and due column aligned.
                            task = self._read(conn,actor,task_id,summary=True)
                            data = {k:v for k,v in task.items() if k not in {'status','latest_run','runs','run_count','history_truncated'}}
                            data['next_due'] = None
                            raw,digest = _json(data)
                            conn.execute("UPDATE tasks SET data_json=?,data_sha256=?,next_due=NULL WHERE id=? AND actor=? AND status!='RUNNING'",
                                         (raw,digest,task_id,actor))
                        else:
                            conn.execute("UPDATE tasks SET status='NEEDS_ATTENTION',next_due=NULL WHERE id=? AND actor=? AND status!='RUNNING'",
                                         (task_id,actor))
                        conn.commit()
                    reports.append({'status':'NEEDS_ATTENTION','approved':False,'executed':False,
                                    'reason': ('RUN_HISTORY_CAPACITY_REACHED' if error.args == ('RUN_HISTORY_CAPACITY_REACHED',)
                                               else 'STORED_TASK_INVALID')})
                    failed += 1
                    claimed = None
                if claimed:
                    report = self._perform(*claimed)
                    reports.append(report)
                    failed += report['status'] != 'CHECKED_PARTIAL'
                if len(reports) != before:
                    with self._connection() as conn:
                        conn.execute('UPDATE worker_runs SET processed_count=?,failed_count=?,last_activity_at=? WHERE id=?',
                                     (len(reports),failed,utc_now().isoformat(),worker_id))
        except BaseException:
            # Fixed state/counters only: no exception details, question, actor, or credentials.
            finished = utc_now().isoformat()
            with self._connection() as conn:
                conn.execute('UPDATE worker_runs SET status=?,finished_at=?,last_activity_at=?,processed_count=?,failed_count=? WHERE id=?',
                             ('FAILED',finished,finished,len(reports),failed+1,worker_id))
            raise
        finished = utc_now().isoformat()
        with self._connection() as conn:
            conn.execute('UPDATE worker_runs SET status=?,finished_at=?,last_activity_at=?,processed_count=?,failed_count=? WHERE id=?',
                         ('FAILED' if failed else 'COMPLETED',finished,finished,len(reports),failed,worker_id))
        return reports

    # [작성: 과제 백엔드] 2026-09-29 case95 / 15분중단run→명시실패회복 / 검증: 살아있는claim보호·늦은worker폐기.
    def recover_stale(self, actor, task_id):
        actor=_text(actor,128,True)
        with self._connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            task=self._read(conn,actor,task_id); report=task['latest_run']; now=utc_now()
            if task['status']!='RUNNING' or now-datetime.fromisoformat(report['started_at'])<STALE_AFTER:
                raise ValueError('RUN_NOT_STALE')
            report.update(status='NEEDS_ATTENTION',finished_at=now.isoformat(),
                          unknown=['15분 이상 완료되지 않은 실행을 명시적으로 중단 처리했습니다. 실제 원격 작업 종료를 증명하지는 않습니다.'],
                          next_actions=['연결·입력 상태를 확인한 뒤 새 실행을 시작하세요.'])
            report['steps'].append(dict(role='recovery',status='NEEDS_ATTENTION',detail='과거 성공은 현재 결과로 승격하지 않습니다. 늦게 끝난 기존 실행의 저장 권한을 폐기했습니다.'))
            self._write(conn,actor,task_id,report);conn.commit()
        return self.get(actor,task_id)
