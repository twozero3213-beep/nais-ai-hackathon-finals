"""Resource and spreadsheet-export guards.

Reproducibility rule: validation never mutates source data. Formula-injection
neutralization is applied only to exported representations, never to calculations.
"""
from __future__ import annotations
import csv, io, json, re, unicodedata
from finals.finals_privacy import sensitive_kinds
MAX_CSV_BYTES=100*1024*1024
MAX_CSV_ROWS=1_000_000
MAX_CSV_COLUMNS=1_000
MAX_CELL_CHARS=128*1024
DANGEROUS_PREFIXES=('=','+','-','@')

# [수정: 0 이영] 2026-10-01 03:11 KST — 기존 순수 탐지기에 라벨 인증값 검사를 더하여 에이전트·로그·팀 저장이 같은 경계를 재사용한다. 표준 빈값/정제 표시를 인증값으로 재차 차단하지 않는다.
CREDENTIAL_ASSIGNMENT = re.compile(r'''(?i)\b(api[_-]?key|access[_-]?token|token|password|secret|authorization)\b(\s*["']?\s*[:=]\s*)("[^"]*"|'[^']*'|\[REDACTED\]|[^\s,;\]}]+)''')
_SAFE_CREDENTIAL_MARKERS = frozenset({'', '[REDACTED]', '[비공개 설정]', 'null', 'None'})


def sensitive_content_kinds(value) -> tuple[str, ...]:
    """Return fixed detection kinds only; input and matched values remain untouched."""
    kinds = sensitive_kinds(value)
    try:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    if any(match.group(3).strip('"\'') not in _SAFE_CREDENTIAL_MARKERS
           for match in CREDENTIAL_ASSIGNMENT.finditer(text)):
        return kinds + ('CREDENTIAL_ASSIGNMENT',)
    return kinds

# [수정: 전문가8·11·15] 2026-09-28 case81: 실제 CSV parser 기본 128 Ki문자 한도로 정렬하고 전역 한도 변경 없이 입력 오류를 반환.
def validate_csv_bytes(data:bytes):
    if not isinstance(data,(bytes,bytearray)): raise TypeError('CSV input must be bytes')
    if len(data)>MAX_CSV_BYTES: raise ValueError('CSV exceeds byte limit')
    text=bytes(data).decode('utf-8-sig',errors='strict')
    reader=csv.reader(io.StringIO(text))
    rows=0
    try:
        for row in reader:
            rows+=1
            if rows>MAX_CSV_ROWS: raise ValueError('CSV exceeds row limit')
            if len(row)>MAX_CSV_COLUMNS: raise ValueError('CSV exceeds column limit')
            if any(len(cell)>MAX_CELL_CHARS for cell in row): raise ValueError('CSV cell exceeds length limit')
    except csv.Error as exc:
        raise ValueError('CSV cell exceeds parser length limit or CSV is invalid') from exc
    return {'rows':rows,'bytes':len(data)}

# [수정: 전문가9·14] 2026-09-28 case81: Unicode 공백·제어·서식 접두 뒤 수식도 export에서만 텍스트화.
def neutralize_spreadsheet_formula(value):
    if not isinstance(value,str): return value
    # Attackers may hide a formula after spaces/tabs/CR/LF. Inspect the first
    # non-whitespace/control character but preserve the original representation.
    start=0
    while start<len(value) and (value[start].isspace() or unicodedata.category(value[start]) in {'Cc','Cf'}):
        start+=1
    probe=value[start:]
    return "'"+value if probe.startswith(DANGEROUS_PREFIXES) else value


# [작성: 전문가9·12·14] 2026-09-28 case81: 다운로드 전용 CSV 안전 사본; 헤더·셀만 보호하고 저장/계산 원본 bytes는 불변.
def safe_csv_export_bytes(data:bytes)->bytes:
    validate_csv_bytes(data)
    output=io.StringIO(newline='')
    writer=csv.writer(output)
    for row in csv.reader(io.StringIO(bytes(data).decode('utf-8-sig'),newline='')):
        writer.writerow([neutralize_spreadsheet_formula(cell) for cell in row])
    return output.getvalue().encode('utf-8-sig')
