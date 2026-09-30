"""Team-curated knowledge the agent consults: known paper-error cases and claims it must not make.

# [작성: 0 이영] 2026-09-30 21:58 KST — 사용자 지시("우리 에이전트에 학습시켜")로 1 이채우·3 조지현 취합 JSON
# (origin/main 99ece65)을 에이전트 지식으로 연결. 모델 학습(가중치 변경)이 아니라, 실행 때 읽는 고정 지식이다.
# 원자료를 고치지 않고 읽기만 하며, 지문(SHA-256)을 결과에 남긴다.
"""
from __future__ import annotations
import hashlib
import re

from core.paths import PROJECT_ROOT
from core.research_corpus import strict_json

KNOWLEDGE_PATH = PROJECT_ROOT / 'docs/3_조지현_근거관문_차별점_업그레이드_사례우선순위.json'
_CACHE = {'sha256': None, 'value': None}
_DOI_PREFIX = re.compile(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)')


def load_knowledge():
    """Return (knowledge dict, sha256 of file bytes). Raises if the file is missing or malformed.

    # [수정: 0 이영 · Claude] 2026-10-01 00:33 KST — 기존에는 프로세스가 켜진 뒤 처음 읽은 내용을 계속 썼다(lru_cache). 팀원이 지식 JSON을
    # 고쳐 올려도 서버를 다시 켜기 전에는 이전 금지 주장·사례가 적용되는 적시성 결함이었다. 실행마다 파일 바이트(약 25KB)를 읽어 지문이
    # 바뀐 경우에만 다시 해석한다. 손상된 파일은 지난 값을 조용히 쓰지 않고 예외를 낸다(호출한 쪽이 차단한다).
    """
    raw = KNOWLEDGE_PATH.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if _CACHE['sha256'] != digest:
        _CACHE.update(sha256=digest, value=(strict_json(raw), digest))   # 해석이 실패하면 update가 실행되지 않아 캐시가 바뀌지 않는다
    return _CACHE['value']


def _norm_doi(doi):
    # [수정: 0 이영 · Claude] 2026-10-01 00:33 KST — doi:·http(s)://dx.doi.org/ 표기도 같은 DOI로 본다(정규화).
    return _DOI_PREFIX.sub('', str(doi or '').strip().lower())


def known_error_cases(dois):
    """Curated corrected/retracted cases whose paper or notice DOI appears in `dois`."""
    wanted = {_norm_doi(d) for d in dois} - {''}
    cases = load_knowledge()[0]['paper_error_cases']
    return [{k: case.get(k) for k in ('id', 'doi', 'notice', 'notice_doi', 'error_type', 'level', 'source')}
            for case in cases if wanted & {_norm_doi(case.get('doi')), _norm_doi(case.get('notice_doi'))}]


def forbidden_claims():
    """Claims the team fact-check says the product must not make (e.g. '우리만 오류를 찾는다')."""
    return list(load_knowledge()[0]['differentiation']['do_not_claim'])


if __name__ == '__main__':
    data, digest = load_knowledge()
    assert [c['id'] for c in known_error_cases(['https://doi.org/10.1111/EVO.14483'])] == ['A2']
    assert [c['id'] for c in known_error_cases(['10.1038/sdata.2017.119'])] == ['A1']  # notice DOI
    assert known_error_cases(['10.1234/none', '']) == []
    assert '우리만 오류를 찾는다' in forbidden_claims()
    print('ok', len(data['paper_error_cases']), 'cases', digest[:12])
