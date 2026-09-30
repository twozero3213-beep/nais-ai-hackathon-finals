"""개인정보·인증 값 형태 탐지. 값은 돌려주거나 기록하지 않고 종류만 돌려준다.

# [작성: 0 이영 · Claude] 작성 시각 미확인; 03 검토 2026-10-01T02:08:17+09:00 — 모의 심사 피드백(활용성 20점: 개인정보·데이터 보호, 오남용 방지 장치)에 대응한다.
# 이전에는 인증 값 형태(sk-·Bearer)만 막았고, 이메일·전화번호·주민등록번호가 승인 사유·후보 JSON·외부 AI 전송 본문에 섞여도 통과했다.
# 탐지 지점은 한 곳(이 모듈)에 두고 파이프라인(후보·승인 사유·보고서)과 공급자(외부 전송 직전)가 같은 함수를 쓴다.
# 한계: 형태 검사이며 이름·주소 같은 자유 문장의 개인정보는 잡지 못한다. 그래서 화면 고지가 "개인정보를 넣지 마세요"를 함께 안내한다.
"""
from __future__ import annotations

import json
import re

# 종류 이름은 오류 코드·로그·화면에 그대로 쓰므로 영문 대문자로 고정한다(값은 어디에도 남기지 않는다).
_PATTERNS = (
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")),
    # 하이픈으로 구분된 국내 전화번호만 본다(구분 없는 숫자열은 자료 값과 구별할 수 없어 오탐이 많다).
    ("KR_PHONE", re.compile(r"(?<![\d-])(?:01[016789]|0[2-6]\d?)-\d{3,4}-\d{4}(?![\d-])")),
    ("KR_RRN", re.compile(r"(?<!\d)\d{6}-[1-4]\d{6}(?!\d)")),
    # 'task-…'·'risk-…'처럼 단어 안의 sk-는 키가 아니므로 앞이 영숫자이면 제외한다.
    ("API_KEY", re.compile(r"(?<![A-Za-z0-9])(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
                           r"|AIza[0-9A-Za-z_-]{30,}|AKIA[0-9A-Z]{16})")),
    ("BEARER_TOKEN", re.compile(r"(?i)(?<![A-Za-z0-9])bearer\s+[A-Za-z0-9._~+/-]{12,}")),
    ("PRIVATE_KEY", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)
PERSONAL = ("EMAIL", "KR_PHONE", "KR_RRN")          # 사람을 식별하는 값
SECRETS = ("API_KEY", "BEARER_TOKEN", "PRIVATE_KEY")  # 인증 값
LABELS = {"EMAIL": "이메일 주소", "KR_PHONE": "전화번호", "KR_RRN": "주민등록번호", "API_KEY": "API 키",
          "BEARER_TOKEN": "인증 토큰", "PRIVATE_KEY": "개인 키"}


def _text(value) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def sensitive_kinds(value) -> tuple[str, ...]:
    """문자열·JSON 값에서 발견한 개인정보·인증 값의 종류(중복 없음, 고정 순서)를 돌려준다. 값은 돌려주지 않는다."""
    text = _text(value)
    return tuple(name for name, pattern in _PATTERNS if pattern.search(text))


def is_public_text(value) -> bool:
    """개인정보·인증 값 형태가 없으면 True. 파이프라인의 '공개 가능한 본문' 검사가 쓴다."""
    return not sensitive_kinds(value)


def describe(kinds) -> str:
    """종류 목록을 화면에 보여 줄 한국어 문장 조각으로 바꾼다(값은 포함하지 않는다)."""
    return "·".join(LABELS.get(kind, kind) for kind in kinds)
# [수정: 3 조지현 · 2026-10-01T02:08:17+09:00] 기준 커밋보다 뒤인 주석 시각은 원작성 시각으로 확인할 수 없어 미확인으로 표시했다. 원표기는 별도 검토 기록에 보존한다.
