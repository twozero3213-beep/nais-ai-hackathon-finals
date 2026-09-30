"""Publish one bounded metadata file to research-feed using repository GITHUB_TOKEN."""
import base64
import http.client
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research_digest import build_digest, validate_digest


# [작성: 운영 담당] 2026-09-29 case95 / 예약 갱신→별도 branch 저장 / main·team-data 불변, API 실패 시 이전 데이터 보존.
def main():
    repo = os.environ['GITHUB_REPOSITORY']
    token = os.environ['GITHUB_TOKEN']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('Invalid repository')
    def api(path, payload=None, missing=False):
        connection=http.client.HTTPSConnection('api.github.com',timeout=30)
        method='GET' if payload is None else ('PUT' if path.startswith('/contents/') else 'POST')
        try:
            connection.request(method,'/repos/'+repo+path,
                body=None if payload is None else json.dumps(payload).encode(),
                headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
                         'User-Agent':'NAIS-ScheduledResearch/95','Content-Type':'application/json'})
            response=connection.getresponse()
            if missing and response.status==404:return None
            if response.status not in {200,201}:raise RuntimeError('GitHub request failed: HTTP '+str(response.status))
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError('GitHub response too large')
            return json.loads(raw)
        finally:connection.close()
    branch = 'research-feed'
    if api('/git/ref/heads/'+branch, missing=True) is None:
        commit = api('/git/ref/heads/main')['object']['sha']
        api('/git/refs', {'ref':'refs/heads/'+branch, 'sha':commit})
    path = '/contents/data/research_digest.json'
    previous_file = api(path+'?ref='+branch, missing=True)
    previous = None
    if previous_file:
        previous = json.loads(base64.b64decode(previous_file['content']))
        validate_digest(previous)
    result = build_digest(previous)
    validate_digest(result)
    payload = {'message':'Refresh public research metadata · '+result['generated_at'], 'branch':branch,
               'content':base64.b64encode(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()).decode()}
    if previous_file:
        payload['sha'] = previous_file['sha']
    api(path, payload)
    counts = {'ok':sum(e['status']=='ok' for e in result['entries']),
              'error':sum(e['status']=='error' for e in result['entries'])}
    print(json.dumps(counts))
    # All-source outage is visible in Actions; the saved snapshot still records each failure.
    if not counts['ok']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
