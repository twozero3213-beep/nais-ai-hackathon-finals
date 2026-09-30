"""Canonical structured JSONL logger for Evidence Gate.

case29 LOGGING CHANGE — WHY:
case28 still imported ``structured_logging_case25`` and wrote case28 events into a case25-named file.
A verification product cannot make version provenance ambiguous.  New code uses this stable,
version-neutral module and writes app/engine versions into every event instead of the filename.
"""
from __future__ import annotations
import hashlib, json, logging, os, re, threading, traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from .activity_privacy import ACTIVITY_TIME_FIELDS, activity_view
from .paths import AUDIT_JSONL_PATH
# [수정: 0 이영] 2026-10-01 03:11 KST — 개인정보·라벨 인증값의 공통 순수 입력 경계를 재사용하고 기존 로그 라벨 정제도 동일 정규식을 사용한다.
from .input_security import CREDENTIAL_ASSIGNMENT, sensitive_content_kinds

_FIELDS=("claim_id","contract_type","dataset_hash","state","rows_used","engine_version","app_version","actor","source")
_SETUP_LOCK=threading.RLock()
_ASSIGNMENT=CREDENTIAL_ASSIGNMENT
_BEARER=re.compile(r'(?i)\b(Bearer)\s+([^\s"\',;]+)')
_PREFIXED_KEY=re.compile(r'\b(?:sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]{8,}|xox[baprs]-[A-Za-z0-9-]{8,})\b')
_TIME_ASSIGNMENT=re.compile(r'''(?i)\b('''+'|'.join(sorted(ACTIVITY_TIME_FIELDS,key=len,reverse=True))+r''')\b(\s*["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;\]}]+)''')


def _sensitive_placeholder(value):
    """Keep detection kinds, never retain the matched string or partial key body."""
    kinds = sensitive_content_kinds(value)
    return '[REDACTED: ' + ','.join(kinds) + ']' if kinds else value


def _clean_object(value):
    if isinstance(value,dict):
        # [수정: 0 이영] 2026-10-01 02:53 KST — 민감 문자열만 종류로 대체하고 검산 수치·안전한 사건 필드는 보존한다. 키에 담긴 연락처도 표시용 사본에서 차단한다.
        return {_sensitive_placeholder(str(key)): ('[REDACTED]' if re.fullmatch(r'(?i)(?:api[_-]?key|access[_-]?token|token|password|secret|authorization)',str(key)) else _clean_object(item))
                for key,item in activity_view(value).items()}
    if isinstance(value,(list,tuple)):
        return [_clean_object(item) for item in value[:32]]
    if isinstance(value,str):
        return _sensitive_placeholder(value)
    return value


def _redact(value):
    if isinstance(value,(dict,list,tuple)):
        value=json.dumps(_clean_object(value),ensure_ascii=False,default=str)
    if not isinstance(value,str):
        return value
    if value.lstrip().startswith(('{','[')):
        try:
            value=json.dumps(_clean_object(json.loads(value)),ensure_ascii=False,default=str)
        except (TypeError,ValueError):
            pass
    value=_BEARER.sub(r'\1 [REDACTED]',value)
    value=_ASSIGNMENT.sub(r'\1\2"[REDACTED]"',value)
    value=_TIME_ASSIGNMENT.sub(r'\1\2"[ACTIVITY_TIME_REMOVED]"',value)
    # [수정: 0 이영] 2026-10-01 02:53 KST — 자유 문장 로그에서도 연락처·주민등록번호·Google형 키·개인 키 본문을 종류만 남겨 차단한다.
    return _sensitive_placeholder(_PREFIXED_KEY.sub('[REDACTED]',value))[:8192]


def _safe_exception(exc_info):
    kind, _, tb=exc_info
    frames=traceback.extract_tb(tb) if tb else []
    where=f' at {Path(frames[-1].filename).name}:{frames[-1].lineno}' if frames else ''
    return f'{kind.__name__}{where}' if kind else 'Exception'


def _file_logger(path,namespace,formatter):
    target=str(Path(path).resolve())
    key=hashlib.sha256(os.path.normcase(target).encode()).hexdigest()
    logger=logging.getLogger(f'evidence_gate.{namespace}.{key}')
    with _SETUP_LOCK:
        logger.propagate=False
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            Path(target).parent.mkdir(parents=True,exist_ok=True)
            handler=RotatingFileHandler(target,maxBytes=2*1024*1024,backupCount=3,encoding='utf-8')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
    return logger

class JsonLineFormatter(logging.Formatter):
    def format(self,record):
        # [수정: 0 이영] 2026-10-01 02:59 KST — 인자 없는 구조화 메시지는 repr로 바꾸기 전에 사본을 정제해 안전한 검산 수치와 JSON 구조를 유지한다.
        message = record.getMessage() if record.args else record.msg
        payload={"level":record.levelname,
                 "logger":record.name,"event":_redact(getattr(record,"event","LOG")),"message":_redact(message)}
        for key in _FIELDS:
            val=getattr(record,key,None)
            if val not in (None,""):payload[key]=_redact(val)
        if record.exc_info:payload["exception"]=_safe_exception(record.exc_info)
        return json.dumps(payload,ensure_ascii=False,default=str)

# [작성/수정: 전문가4] 2026-09-26 case64
# 무엇을·왜: 감사 경로별 logger를 재사용해 서로 다른 기록 파일의 사건 혼합을 막는다.
# 독립 재검토 후: handler도 resolve된 경로로 열어 Windows 대소문자 별칭의 중복 기록을 차단한다.
# 입력·출력: 파일 경로 -> 전용 logger / 검증: tests/test_case64_audit.py의 두 파일 격리·중복 방지.
def get_event_logger(path=None):
    return _file_logger(path or AUDIT_JSONL_PATH,'audit',JsonLineFormatter())

def event(logger,name,message="",**fields):
    logger.info(message or name,extra={"event":name,**fields})
