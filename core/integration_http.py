"""Bounded public GET transport for research metadata and fixed scholarly feeds."""
# [작성: 0 이영 · Codex] 2026-10-01 KST — 신규 연결을 같은 시간·응답 지문·실패 상태로 확인한다.
# 키·이메일·원문 다운로드를 받지 않으며, 공유 rate DB로 양쪽 MCP 프로세스의 호출 간격을 조정한다.
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import sqlite3
from threading import RLock
import time
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

ALLOWED_HOSTS = frozenset({
    'zenodo.org', 'api.figshare.com', 'dataverse.harvard.edu', 'api.crossref.org',
    'eutils.ncbi.nlm.nih.gov', 'rss.arxiv.org', 'connect.biorxiv.org', 'www.kisti.re.kr',
})
MAX_BYTES = 2 * 1024 * 1024
CACHE_TTL = 300
_ARXIV_CONNECTION_WAIT_SECONDS = 30.0
_CACHE = {}
_LOCK = RLock()
_SENSITIVE = re.compile(r'(?:sk-(?:proj-)?[\w-]{20,}|gh[pousr]_[\w]{20,}|AIza[\w-]{25,}|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})')


# [수정: 0 이영 · Codex] 2026-10-01 01:54 KST — arXiv 공식 단일 연결 조건을 두 MCP 프로세스에도 적용한다. 버전 0, 별도 빈 SQLite 잠금을 HTTP 종료까지 보유하며 모의 동시 호출·시간 제한 시험으로 검증.
def _arxiv_connection_guard(host):
    if host != 'rss.arxiv.org':
        return None
    rate_path = Path(os.environ.get('NAIS_PUBLIC_RATE_DB', str(Path(__file__).resolve().parents[1] / 'data/.nais_public_rate.sqlite')))
    path = Path(str(rate_path) + '.arxiv-connection')
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + _ARXIV_CONNECTION_WAIT_SECONDS
    guard = sqlite3.connect(path, timeout=_ARXIV_CONNECTION_WAIT_SECONDS)
    try:
        # No request, response, key or owner row is written; process exit releases the SQLite lock.
        guard.execute('CREATE TABLE IF NOT EXISTS guard (unused INTEGER)')
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('ARXIV_CONNECTION_BUSY')
        # Both schema initialization and lock acquisition share one bounded wait budget.
        guard.execute('PRAGMA busy_timeout=' + str(int(remaining * 1000)))
        guard.execute('BEGIN EXCLUSIVE')
        return guard
    except (sqlite3.Error, ValueError):
        guard.close()
        raise


def _reserve_slot(host):
    # Shared file stores only provider group and next timestamp; no query or response content.
    path = Path(os.environ.get('NAIS_PUBLIC_RATE_DB', str(Path(__file__).resolve().parents[1] / 'data/.nais_public_rate.sqlite')))
    path.parent.mkdir(parents=True, exist_ok=True)
    group = 'arxiv' if host.endswith('.arxiv.org') else host
    interval = 3.1 if group == 'arxiv' else 1.0
    with sqlite3.connect(path, timeout=15) as db:
        db.execute('CREATE TABLE IF NOT EXISTS rate (provider TEXT PRIMARY KEY, next_at REAL NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT next_at FROM rate WHERE provider=?', (group,)).fetchone()
        now = time.time()
        slot = max(now, row[0] if row else now)
        # Do not queue an unbounded number of requests within one tool operation.
        if slot - now > 30:
            raise ValueError('RATE_QUEUE_FULL')
        db.execute('INSERT OR REPLACE INTO rate VALUES (?,?)', (group, slot + interval))
    if slot > now:
        time.sleep(slot - now)


def _constant(value):
    raise ValueError('NONFINITE_JSON')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def _request(host, path, params, kind):
    if host not in ALLOWED_HOSTS or not isinstance(path, str) or not path.startswith('/') or path.startswith('//'):
        raise ValueError('허용된 공식 제공자 경로만 조회할 수 있습니다.')
    if len(path) > 600 or any(c in path for c in ('\r', '\n', '#', '\\')):
        raise ValueError('조회 경로 형식 오류')
    params = {} if params is None else params
    if not isinstance(params, dict) or len(params) > 12:
        raise ValueError('조회 매개변수 형식 오류')
    if any(re.search(r'key|token|secret|password|email|authorization', str(k), re.I) for k in params):
        raise ValueError('이 공개 연결은 인증값이나 이메일을 받지 않습니다.')
    values = path + ' ' + ' '.join(str(x) for x in params.values())
    if len(values) > 2000 or _SENSITIVE.search(values) or any(c in values for c in ('\r', '\n', '\x00')):
        raise ValueError('공개 메타데이터 조회 입력을 확인하세요.')
    suffix = urlencode(params, doseq=True)
    target = path + (('&' if '?' in path else '?') + suffix if suffix else '')
    source_url = 'https://' + host + target
    cache_key = (source_url, kind)
    with _LOCK:
        cached = _CACHE.get(cache_key)
        if cached and time.monotonic() - cached[0] < CACHE_TTL:
            envelope = deepcopy(cached[1])
            envelope['cached'] = True
            return envelope
    envelope = {'ok': False, 'http_status': None, 'data': None, 'source_url': source_url,
                'retrieved_at_kst': datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds'),
                'response_sha256': None, 'cached': False, 'error': None}
    connection = None
    arxiv_guard = None
    try:
        arxiv_guard = _arxiv_connection_guard(host)
        _reserve_slot(host)
        connection = http.client.HTTPSConnection(host, timeout=20)
        connection.request('GET', target, headers={
            'User-Agent': 'NAIS-EvidenceGate-PublicMetadata/1 (bounded read-only research)',
            'Accept': 'application/json' if kind == 'json' else 'application/xml,application/rss+xml,application/atom+xml,text/xml',
            'Accept-Encoding': 'identity',
        })
        response = connection.getresponse()
        envelope['retrieved_at_kst'] = datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds')
        envelope['http_status'] = response.status
        if response.status != 200:
            envelope['error'] = 'HTTP_' + str(response.status)
            return envelope
        raw = response.read(MAX_BYTES + 1)
        envelope['retrieved_at_kst'] = datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds')
        if len(raw) > MAX_BYTES:
            envelope['error'] = 'RESPONSE_TOO_LARGE'
            return envelope
        envelope['response_sha256'] = hashlib.sha256(raw).hexdigest()
        if kind == 'json':
            data = json.loads(raw, parse_constant=_constant, object_pairs_hook=_pairs)
        else:
            if b'<!ENTITY' in raw.upper():
                raise ValueError('XML_ENTITY_NOT_ALLOWED')
            data = ET.fromstring(raw)
        envelope.update(ok=True, data=data)
        with _LOCK:
            if len(_CACHE) >= 128:
                _CACHE.pop(next(iter(_CACHE)))
            _CACHE[cache_key] = (time.monotonic(), deepcopy(envelope))
        return envelope
    # [수정: 0 이영] 2026-10-01 KST — 과도한 JSON 중첩도 실패 응답으로 반환하고 관측 시각을 수신 시각으로 남긴다.
    except (OSError, http.client.HTTPException, ValueError, ET.ParseError, sqlite3.Error, UnicodeError, RecursionError):
        envelope['retrieved_at_kst'] = datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds')
        envelope.update(ok=False, data=None, error='CONNECTION_OR_RESPONSE_ERROR')
        return envelope
    finally:
        # [수정: 0 이영 · Codex] 2026-10-01 01:54 KST — HTTP 연결을 먼저 닫고 공유 배타 잠금을 해제하여 느린 응답·오류에서도 arXiv 연결 중첩을 막는다. 버전 0.
        try:
            if connection is not None:
                connection.close()
        finally:
            if arxiv_guard is not None:
                try:
                    arxiv_guard.rollback()
                finally:
                    arxiv_guard.close()


def get_json(host, path, params=None):
    return _request(host, path, params, 'json')


def get_xml(host, path, params=None):
    return _request(host, path, params, 'xml')
