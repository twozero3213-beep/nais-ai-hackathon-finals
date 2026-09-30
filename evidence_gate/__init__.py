"""근거관문 최소 실행 경로: 정규 명세 v2 → 결정론적 계산 → 판정 → 추가 전용 기록."""

from .gate import evaluate
from .spec import validate

__all__ = ["evaluate", "validate"]
