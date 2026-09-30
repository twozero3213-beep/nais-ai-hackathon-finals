"""Presentation-only helpers. No verification decisions belong here."""
from .models import Status

LABELS={Status.SUPPORTED:'근거 일치',Status.CONFLICT:'수치 불일치',Status.MISSING:'근거 없음',Status.OVERCLAIM:'표현 범위 검토',Status.REVIEW:'검토 필요',Status.VALIDATED:'검증 완료'}
PRIORITY={Status.CONFLICT:0,Status.OVERCLAIM:1,Status.MISSING:2,Status.REVIEW:3,Status.SUPPORTED:4,Status.VALIDATED:5}

def status_label(s): return LABELS.get(s,str(s))
def status_priority(s): return PRIORITY.get(s,99)
