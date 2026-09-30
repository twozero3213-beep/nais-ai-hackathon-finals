"""Google Scholar navigation and an explicit path to original evidence."""
# [작성: 0 이영 · Codex] 2026-10-01 KST — Scholar를 발견 경로로 추가하고 검색 결과와 원논문·원자료 검증을 구분한다.
import re
from urllib.parse import urlencode


def scholar_discovery(query: str) -> dict:
    """Build a browser search link; do not scrape Scholar or assert evidence validity."""
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 300:
        return {'ok': False, 'error': 'INVALID_QUERY', 'verification_pass': False}
    # [수정: 0 이영] 2026-10-01 KST — trim 이전 제어문자와 Google 키 형태도 공개 URL에서 제외한다.
    if any(ord(char) < 32 or ord(char) == 127 for char in query) or re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|sk-(?:proj-)?[\w-]{20,}|gh[pousr]_[\w]{20,}|AIza[\w-]{25,}|(?:api.?key|password|secret|token)\s*[=:]', query, re.I):
        return {'ok': False, 'error': 'PRIVATE_OR_CONTROL_INPUT', 'verification_pass': False}
    query = query.strip()
    return {
        'ok': True, 'operation': 'BROWSER_NAVIGATION_ONLY',
        'search_url': 'https://scholar.google.com/scholar?' + urlencode({'hl': 'ko', 'q': query}),
        'query': query, 'retrieved': False, 'verification_pass': False, 'approved': False,
        'help_url': 'https://scholar.google.com/intl/en/scholar/help.html',
        'evidence_steps': [
            '검색 결과에서 제목·연도·DOI와 출판사 또는 저자 저장소의 논문을 대조한다.',
            '출판본·저자 최종본·사전 공개본과 버전을 구분하고 정정·철회 관계를 조회한다.',
            '논문의 Data availability·Supplementary information에서 원자료 DOI를 찾는다.',
            'repository_record로 원자료의 고정 버전·라이선스·파일 체크섬을 조회한다.',
            '확보한 허용 자료의 실제 바이트와 계산 조건을 근거관문에 넣어 검산한 뒤 사람이 판단한다.',
        ],
        'limitations': ['인용 수·검색 순위·요약문만으로 원자료의 정확성이나 논문의 재현을 판정하지 않습니다.',
                        'Google Scholar는 대량 조회를 제공하지 않습니다. 이 도구는 검색 링크만 생성합니다.'],
    }
