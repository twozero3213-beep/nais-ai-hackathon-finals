"""Metadata checkpoints for one integration run, using TaskStore and its audit DB.

No worker, network call, model call, artifact upload, or approval is performed here.
File bytes are not persisted: a resumed caller must reacquire and hash the files.
"""
# [작성: 0 이영] 2026-10-01 03:25 KST — 전체연동의 actor·입력·시도·감사 결속을 기존 SQLite 원장에 저장한다.
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
import re
import sqlite3
from threading import RLock
import uuid

from .audit_store import AuditStore
from .research_tasks import TaskStore, _json, _text, utc_now

STAGES = ('search', 'relations', 'original', 'file', 'conditions', 'calculation', 'human_review')
NEXT_ACTIONS = {'CONTINUE', 'RETRY', 'REACQUIRE_AND_RECHECK', 'CONFIRM_CONDITIONS',
                'REVIEW', 'DONE', 'CHECK_ACCESS', 'CHECK_INPUT'}
METADATA_KEYS = {'provider', 'record_id', 'version', 'doi', 'url', 'count', 'byte_count',
                 'sha256', 'artifact_sha256', 'source_sha256', 'data_sha256', 'spec_sha256',
                 'reference_sha256', 'receipt_sha256', 'result_sha256', 'approval_receipt_sha256',
                 'record_sha256', 'paper_context_sha256', 'prompt_sha256', 'policy_sha256',
                 'observed_at_kst', 'observation_kind', 'http_status', 'elapsed_ms', 'usage_unknown',
                 'engine_source_revision', 'status', 'code', 'conditions_confirmed'}
EMAIL = re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')
# [수정: 0 이영] 2026-10-01 04:25 KST — HTTPS의 s:/를 Windows 드라이브로 오인하지 않되 실제 로컬 경로 차단은 유지한다.
PRIVATE_PATH = re.compile(r'(?i)(?:(?<![A-Za-z0-9])[a-z]:[\\/]|/(?:home|users)/|\\\\[^\\]+\\)')
SENSITIVE_KEY = re.compile(r'(?i)(?:password|passwd|secret|token|authorization|api[_-]?key|email|cookie|credential)')
MAX_ATTEMPTS = 70
LIMITATION = 'METADATA_ONLY_REACQUIRE_BYTES_AND_RECHECK_SHA256'


def fingerprint(value):
    """Hash small public JSON inputs; never retain the input values in the DB."""
    nodes = 0
    def check(item, depth=0):
        nonlocal nodes
        nodes += 1
        if nodes > 256 or depth > 5:
            raise ValueError('INPUT_METADATA_TOO_LARGE')
        if isinstance(item, str):
            if len(item) > 1000 or EMAIL.search(item) or PRIVATE_PATH.search(item):
                raise ValueError('UNSAFE_METADATA')
        elif isinstance(item, dict):
            if len(item) > 32:
                raise ValueError('INPUT_METADATA_TOO_LARGE')
            for key, child in item.items():
                if not isinstance(key, str) or len(key) > 80 or SENSITIVE_KEY.search(key):
                    raise ValueError('UNSAFE_METADATA')
                check(key, depth + 1)
                check(child, depth + 1)
        elif isinstance(item, list):
            if len(item) > 32:
                raise ValueError('INPUT_METADATA_TOO_LARGE')
            for child in item:
                check(child, depth + 1)
        elif item is not None and type(item) not in (bool, int, float):
            raise ValueError('METADATA_ONLY_NO_BYTES')
    check(value)
    raw, digest = _json(value)
    if len(raw.encode('utf-8')) > 8192:
        raise ValueError('INPUT_METADATA_TOO_LARGE')
    return digest


def _identifier(value, size=128):
    value = _text(value, size, True)
    fingerprint(value)
    return value


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
        raise ValueError('INVALID_SHA256')
    return value


def _revision(value):
    if type(value) is not int or value < 0:
        raise ValueError('INVALID_REVISION')
    return value


def _metadata(value):
    if not isinstance(value, dict) or set(value) - METADATA_KEYS:
        raise ValueError('OUTPUT_METADATA_ONLY')
    fingerprint(value)
    for key, item in value.items():
        if type(item) not in (str, int, bool, type(None)):
            raise ValueError('OUTPUT_METADATA_ONLY')
        if key not in {'count', 'byte_count', 'conditions_confirmed', 'http_status', 'elapsed_ms', 'usage_unknown'} and item is not None and not isinstance(item, str):
            raise ValueError('OUTPUT_METADATA_ONLY')
        if isinstance(item, str) and len(item) > 300:
            raise ValueError('OUTPUT_METADATA_TOO_LARGE')
        if key.endswith('sha256') and item is not None:
            _sha(item)
        if key in {'count', 'byte_count'} and (type(item) is not int or item < 0):
            raise ValueError('INVALID_METADATA_COUNT')
        if key == 'conditions_confirmed' and type(item) is not bool:
            raise ValueError('INVALID_METADATA_BOOLEAN')
        # [수정: 0 이영] 2026-10-01 04:15 KST — 기존 관측 시각·HTTP·경과·usage 상태만 좁게 허용하고 현재 DB 기록 시각과 구분한다.
        if key == 'http_status' and item is not None and (type(item) is not int or not 100 <= item <= 599):
            raise ValueError('INVALID_METADATA_HTTP_STATUS')
        if key == 'elapsed_ms' and item is not None and (type(item) is not int or item < 0):
            raise ValueError('INVALID_METADATA_ELAPSED_MS')
        if key == 'usage_unknown' and type(item) is not bool:
            raise ValueError('INVALID_METADATA_BOOLEAN')
        if key == 'observation_kind' and (not isinstance(item, str) or not item.strip() or len(item) > 80):
            raise ValueError('INVALID_METADATA_OBSERVATION_KIND')
        if key == 'observed_at_kst' and item is not None:
            try:
                observed = datetime.fromisoformat(item)
                if observed.tzinfo is None or observed.utcoffset() != timedelta(hours=9):
                    raise ValueError('INVALID_METADATA_OBSERVATION_TIME')
            except (TypeError, ValueError):
                raise ValueError('INVALID_METADATA_OBSERVATION_TIME') from None
        if key == 'url' and item is not None:
            # A provenance URL is never an authenticated/private URL.
            if not isinstance(item, str):
                raise ValueError('UNSAFE_METADATA_URL')
            from urllib.parse import urlsplit
            parts = urlsplit(item)
            if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
                raise ValueError('UNSAFE_METADATA_URL')
    return deepcopy(value)


class IntegrationRunStore:
    """Actor-scoped stage bookkeeping; callers still enforce access/consent/gates.

    ``begin_stage`` returns execute=False for idempotent retries. Never execute the
    external operation again in that case. ``resume`` invalidates an interrupted
    attempt, but does not terminate a remote operation or recover its file bytes.
    ``finish_stage(human_review)`` records a receipt hash, never grants approval.
    """
    def __init__(self, task_store=None):
        self.tasks = task_store if task_store is not None else TaskStore()
        self.audit = AuditStore(self.tasks.path)
        self.con = self.audit.con
        self.con.row_factory = sqlite3.Row
        self._lock = RLock()

    def close(self):
        self.con.close()

    @contextmanager
    def _transaction(self):
        # 같은 store의 동시 UI 호출도 직렬화하며 외부 도구 실행은 트랜잭션 밖에서 수행한다.
        with self._lock:
            if not self.audit.verify_audit_chain():
                raise ValueError('AUDIT_CHAIN_INVALID')
            with self.con:
                self.con.execute('BEGIN IMMEDIATE')
                yield

    def _load(self, actor, run_id):
        row = self.con.execute('SELECT task_id FROM runs WHERE id=? AND actor=?', (run_id, actor)).fetchone()
        if row is None:
            raise PermissionError('RUN_NOT_FOUND_OR_NOT_OWNED')
        task = self.tasks._read(self.con, actor, row['task_id'])
        report = task['latest_run']
        if report is None or report['id'] != run_id:
            raise ValueError('RUN_SUPERSEDED')
        data = report.get('integration')
        if (not isinstance(data, dict) or data.get('schema') != 1
                or data.get('run_id') != run_id or data.get('storage_limit') != LIMITATION
                or data.get('approved') is not False):
            raise ValueError('STORED_INTEGRATION_INVALID')
        _sha(data.get('root_input_sha256'))
        _revision(data.get('revision'))
        if not isinstance(data.get('attempts'), list) or len(data['attempts']) > MAX_ATTEMPTS:
            raise ValueError('STORED_INTEGRATION_INVALID')
        _, digest = _json(data)
        audit = self.con.execute('SELECT detail FROM lifecycle WHERE claim_id=? AND actor_id=? ORDER BY id DESC LIMIT 1',
                                 ('integration:' + run_id, actor)).fetchone()
        if audit is None or json.loads(audit['detail']).get('checkpoint_sha256') != digest:
            raise ValueError('CHECKPOINT_AUDIT_MISMATCH')
        return report

    def _event(self, report, event, source):
        data = report['integration']
        _, digest = _json(data)
        detail = json.dumps({'run_id': report['id'], 'revision': data['revision'],
                             'checkpoint_sha256': digest}, sort_keys=True)
        self.audit.append('integration:' + report['id'], event, actor='TEAM', actor_id=report['actor'],
                          detail=detail, source=source, app_version='0', dataset_hash=data['root_input_sha256'])

    def _save(self, report, old_sha, event, source):
        raw, digest = _json(report)
        changed = self.con.execute('UPDATE runs SET status=?,finished_at=?,report_json=?,report_sha256=? '
                                  'WHERE id=? AND actor=? AND report_sha256=?',
                                  (report['status'], report['finished_at'], raw, digest,
                                   report['id'], report['actor'], old_sha)).rowcount
        if changed != 1:
            raise ValueError('STALE_CHECKPOINT')
        self.con.execute('UPDATE tasks SET status=?,active_run=? WHERE id=? AND actor=?',
                         (report['status'], report['id'] if report['status'] == 'RUNNING' else None,
                          report['task_id'], report['actor']))
        self._event(report, event, source)

    @staticmethod
    def _view(report, **extra):
        return dict(deepcopy(report['integration']), task_id=report['task_id'], **extra)

    @staticmethod
    def _check(report, root_sha, revision=None):
        if report['integration']['root_input_sha256'] != _sha(root_sha):
            raise ValueError('ROOT_INPUT_CHANGED_START_NEW_RUN')
        if revision is not None and report['integration']['revision'] != _revision(revision):
            raise ValueError('STALE_CHECKPOINT')

    def start(self, actor, inputs, *, idempotency_key):
        actor = _identifier(actor)
        root_sha = fingerprint(inputs)
        key_sha = fingerprint(_identifier(idempotency_key))
        with self._transaction():
            found = self.con.execute("SELECT id FROM runs WHERE actor=? AND CASE WHEN json_valid(report_json) "
                                     "THEN json_extract(report_json,'$.integration.start_key_sha256') END=?",
                                     (actor, key_sha)).fetchall()
            if len(found) > 1:
                raise ValueError('IDEMPOTENCY_RECORD_INVALID')
            if found:
                report = self._load(actor, found[0]['id'])
                self._check(report, root_sha)
                return self._view(report, reused=True)
            if self.con.execute('SELECT count(*) FROM tasks WHERE actor=?', (actor,)).fetchone()[0] >= 1000:
                raise ValueError('TASK_CAPACITY_REACHED')
            # Reuse TaskStore's exact existing task/run schema; creation and audit are atomic.
            now = utc_now().isoformat()
            task_id, run_id = uuid.uuid4().hex, uuid.uuid4().hex
            task = dict(id=task_id, actor=actor, question='연구 전체 연동 단계 기록', query='', doi='',
                        case_id='', daily_hour=None, next_due=None, created_at=now)
            raw, digest = _json(task)
            self.con.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,?)',
                             (task_id, actor, raw, digest, 'CHECKED_PARTIAL', None, None))
            report = dict(id=run_id, task_id=task_id, actor=actor, status='CHECKED_PARTIAL', started_at=now,
                          finished_at=now, steps=[], evidence=[], metadata=None, calculation=None,
                          known=[], unknown=[LIMITATION], next_actions=[], approved=False, executed=False,
                          integration=dict(schema=1, run_id=run_id, root_input_sha256=root_sha,
                                           start_key_sha256=key_sha, revision=0, state='READY',
                                           stages=list(STAGES), attempts=[], next_stage=STAGES[0],
                                           next_action='CONTINUE', storage_limit=LIMITATION, approved=False))
            raw, digest = _json(report)
            self.con.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)',
                             (run_id, task_id, actor, report['status'], now, now, raw, digest))
            self._event(report, 'ANALYSIS_STARTED', 'start')
            return self._view(report, reused=False)

    def get(self, actor, run_id):
        actor, run_id = _identifier(actor), _identifier(run_id, 64)
        with self._transaction():
            return self._view(self._load(actor, run_id))

    def begin_stage(self, actor, run_id, stage, *, input_sha256, root_input_sha256,
                    expected_revision, idempotency_key):
        actor, run_id = _identifier(actor), _identifier(run_id, 64)
        if stage not in STAGES:
            raise ValueError('UNKNOWN_STAGE')
        input_sha256 = _sha(input_sha256)
        key_sha = fingerprint(_identifier(idempotency_key))
        _revision(expected_revision)
        with self._transaction():
            report = self._load(actor, run_id)
            self._check(report, root_input_sha256)
            data = report['integration']
            for attempt in data['attempts']:
                if attempt['key_sha256'] == key_sha:
                    if attempt['stage'] != stage or attempt['input_sha256'] != input_sha256:
                        raise ValueError('IDEMPOTENCY_INPUT_CONFLICT')
                    return self._view(report, attempt=deepcopy(attempt), execute=False)
            self._check(report, root_input_sha256, expected_revision)
            if data['next_stage'] != stage or any(a['status'] == 'RUNNING' for a in data['attempts']):
                raise ValueError('STAGE_NOT_READY')
            previous = [a for a in data['attempts'] if a['stage'] == stage]
            if previous and previous[-1]['input_sha256'] != input_sha256:
                raise ValueError('STAGE_INPUT_CHANGED_START_NEW_RUN')
            if len(data['attempts']) >= MAX_ATTEMPTS:
                raise ValueError('ATTEMPT_CAPACITY_REACHED')
            old_sha = _json(report)[1]
            successes = [a for a in data['attempts'] if a['status'] == 'SUCCEEDED']
            attempt = dict(attempt_id=uuid.uuid4().hex, stage=stage, input_sha256=input_sha256,
                           parent_attempt_id=successes[-1]['attempt_id'] if successes else None,
                           parent_output_sha256=successes[-1]['output_sha256'] if successes else None,
                           attempt=1 + sum(a['stage'] == stage for a in data['attempts']), key_sha256=key_sha,
                           status='RUNNING', started_at=utc_now().isoformat(), finished_at=None,
                           output_sha256=None, output_metadata=None, error_code=None, next_action='CONTINUE')
            data['attempts'].append(attempt)
            data.update(revision=data['revision'] + 1, state='RUNNING')
            report.update(status='RUNNING', finished_at=None)
            self._save(report, old_sha, 'ANALYSIS_STARTED', attempt['attempt_id'])
            return self._view(report, attempt=deepcopy(attempt), execute=True)

    def finish_stage(self, actor, run_id, *, attempt_id, input_sha256, root_input_sha256,
                     expected_revision, output_metadata=None, error_code=None, next_action='CONTINUE'):
        """Persist an observation; output_sha256 hashes metadata, not file bytes."""
        actor, run_id = _identifier(actor), _identifier(run_id, 64)
        attempt_id, input_sha256 = _identifier(attempt_id, 64), _sha(input_sha256)
        _revision(expected_revision)
        if not isinstance(next_action, str) or next_action not in NEXT_ACTIONS:
            raise ValueError('INVALID_NEXT_ACTION')
        if error_code is not None and (not isinstance(error_code, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}', error_code)):
            raise ValueError('ERROR_CODE_ONLY_NO_EXCEPTION_TEXT')
        if error_code is not None and output_metadata is not None:
            raise ValueError('ERROR_AND_OUTPUT_CONFLICT')
        output = None if error_code is not None else _metadata(output_metadata)
        outcome_sha = fingerprint({'output': output, 'error_code': error_code, 'next_action': next_action})
        with self._transaction():
            report = self._load(actor, run_id)
            self._check(report, root_input_sha256)
            data = report['integration']
            attempt = next((a for a in data['attempts'] if a['attempt_id'] == attempt_id), None)
            if attempt is None or attempt['input_sha256'] != input_sha256:
                raise ValueError('ATTEMPT_INPUT_MISMATCH')
            if attempt.get('outcome_sha256') == outcome_sha and attempt['status'] in {'SUCCEEDED', 'FAILED'}:
                return self._view(report, reused=True)
            self._check(report, root_input_sha256, expected_revision)
            if attempt['status'] != 'RUNNING' or report['status'] != 'RUNNING':
                raise ValueError('ATTEMPT_NO_LONGER_ACTIVE')
            if error_code is None and attempt['stage'] == 'human_review' and not output.get('approval_receipt_sha256'):
                raise ValueError('HUMAN_REVIEW_RECEIPT_REQUIRED')
            old_sha = _json(report)[1]
            now = utc_now().isoformat()
            attempt.update(status='FAILED' if error_code else 'SUCCEEDED', finished_at=now,
                           output_metadata=output, output_sha256=fingerprint(output) if output is not None else None,
                           error_code=error_code, outcome_sha256=outcome_sha, next_action=next_action)
            index = STAGES.index(attempt['stage'])
            next_stage = attempt['stage'] if error_code else STAGES[index + 1] if index + 1 < len(STAGES) else None
            data.update(revision=data['revision'] + 1, state='NEEDS_ATTENTION' if error_code else 'READY' if next_stage else 'COMPLETE_METADATA',
                        next_stage=next_stage, next_action=next_action)
            report.update(status='NEEDS_ATTENTION' if error_code else 'CHECKED_PARTIAL', finished_at=now)
            self._save(report, old_sha, 'ANALYSIS_FAILED' if error_code else 'EXECUTION_SNAPSHOT', attempt_id)
            return self._view(report, reused=False)

    def resume(self, actor, run_id, *, root_input_sha256, input_sha256, expected_revision):
        actor, run_id = _identifier(actor), _identifier(run_id, 64)
        input_sha256 = _sha(input_sha256)
        with self._transaction():
            report = self._load(actor, run_id)
            self._check(report, root_input_sha256, expected_revision)
            data = report['integration']
            current = [a for a in data['attempts'] if a['stage'] == data['next_stage']]
            if current and current[-1]['input_sha256'] != input_sha256:
                raise ValueError('STAGE_INPUT_CHANGED_START_NEW_RUN')
            if not current and input_sha256 != data['root_input_sha256']:
                raise ValueError('RESUME_INPUT_NOT_YET_CHECKPOINTED')
            old_sha = _json(report)[1]
            now = utc_now().isoformat()
            if current and current[-1]['status'] == 'RUNNING':
                current[-1].update(status='INTERRUPTED', finished_at=now, error_code='EXPLICIT_RESUME_INVALIDATED_ATTEMPT',
                                   next_action='REACQUIRE_AND_RECHECK')
            data.update(revision=data['revision'] + 1, state='READY' if data['next_stage'] else 'COMPLETE_METADATA',
                        next_action='REACQUIRE_AND_RECHECK')
            report.update(status='CHECKED_PARTIAL', finished_at=now)
            self._save(report, old_sha, 'REVERIFIED', 'resume')
            return self._view(report)
