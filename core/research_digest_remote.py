"""case95: read the scheduled metadata snapshot; never send research inputs or keys to sources."""
import base64
import http.client
from pathlib import Path
import re

import streamlit as st
from core.research_corpus import strict_json
from core.team_workspace import settings

SNAPSHOT_PATH = 'data/research_digest.json'
BRANCH = 'research-feed'
MAX_BYTES = 1024 * 1024


# [작성: 운영 담당] 2026-09-29 case95 / 고정 GitHub branch→검증된 JSON / 검증: 경로·크기·HTTP·fallback 시험.
@st.cache_data(ttl=300, show_spinner=False)
def _remote(repo, _token):
    from core.research_digest import validate_digest
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('DIGEST_REPO_INVALID')
    connection = http.client.HTTPSConnection('api.github.com', timeout=10)
    try:
        connection.request('GET', f'/repos/{repo}/contents/{SNAPSHOT_PATH}?ref={BRANCH}', headers={
            'Authorization': 'Bearer ' + _token, 'Accept': 'application/vnd.github+json',
            'User-Agent': 'NAIS-ResearchDigest/95', 'X-GitHub-Api-Version': '2022-11-28'})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError('DIGEST_REMOTE_UNAVAILABLE')
        raw = response.read(2 * MAX_BYTES + 1)
        if len(raw) > 2 * MAX_BYTES:
            raise ValueError('DIGEST_TOO_LARGE')
        payload = strict_json(raw)
        if payload.get('encoding') != 'base64' or payload.get('path') != SNAPSHOT_PATH:
            raise ValueError('DIGEST_INVALID_RESPONSE')
        decoded = base64.b64decode(''.join(payload['content'].split()), validate=True)
        if len(decoded) > MAX_BYTES:
            raise ValueError('DIGEST_TOO_LARGE')
        result = strict_json(decoded)
        validate_digest(result)
        return result
    except Exception:
        raise ValueError('DIGEST_REMOTE_UNAVAILABLE') from None
    finally:
        connection.close()


def load_digest():
    """Return (validated digest or None, source label, safe error or None)."""
    from core.research_digest import validate_digest
    error = None
    config = settings()
    if config.get('repo') and config.get('token'):
        try:
            return _remote(config['repo'], config['token']), 'GitHub 자동 갱신 자료', None
        except ValueError:
            error = 'DIGEST_REMOTE_UNAVAILABLE'
    try:
        path = Path(__file__).resolve().parents[1] / SNAPSHOT_PATH
        with path.open('rb') as handle:
            raw = handle.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('DIGEST_TOO_LARGE')
        result = strict_json(raw)
        validate_digest(result)
        return result, '배포 시 보관한 자료 · 실시간 갱신 확인 안 됨', error
    except (OSError, ValueError, TypeError, KeyError):
        return None, '자동 수집 자료 없음', error or 'DIGEST_NOT_READY'
