"""case93 Korean explanations; arithmetic checks never approve scientific claims."""

# [작성: 일반사용자 UX 담당] 2026-09-29 case93
# 무엇·왜: 숫자와 판정을 쉬운 말로 분리 / 입력·출력: 통계 용어→고정 설명 / 검증: test_case93_ux.
STATISTIC_HELP = {
    'count_rows': '기록 수는 등록한 조건에 해당하는 자료의 행 개수입니다. 한 사람이 여러 행을 가질 수 있어 사람 수와 같다고 단정할 수 없습니다. 평균·정상 범위·효과 크기를 뜻하지 않습니다.',
    'missing_count': '결측 수는 선택한 열에서 값이 비어 있는 기록의 개수입니다. 빈 값이 생긴 이유나 분석에서 제외해도 되는지는 별도 확인이 필요합니다.',
    'mean': '평균은 선택한 표본의 값을 합해 관측수로 나눈 값입니다. 전체 사람의 정상 범위나 개인의 건강 상태를 뜻하지 않습니다. 결측값 제외와 대상 조건에 따라 달라집니다.',
    'tolerance': '허용오차는 보고값과 재계산값을 비교할 때 미리 선언한 차이의 기준입니다. 건강·정상 범위가 아닙니다. 근거 없이 기준을 넓혀 숫자를 맞추면 안 됩니다.',
    'p': 'p값은 가정한 모형과 귀무가설 아래에서 관측한 결과만큼 또는 더 극단적인 결과가 나올 확률입니다. 가설이 참일 확률이나 효과의 크기가 아닙니다. 작은 p값만으로 인과관계·중요성을 확정할 수 없습니다.',
    'ci': '신뢰구간은 표본과 계산 방법의 불확실성을 나타냅니다. 같은 조건의 표집과 계산을 반복하면, 예를 들어 95% 신뢰구간의 약 95%가 고정된 모수를 포함한다는 방법의 성질입니다. 이미 계산한 구간 안에 참값이 있을 확률을 95%라고 단정하지 않습니다.',
    'df': '자유도(df)는 모형과 계산 방법에 따라 남는 독립적인 정보의 수를 나타냅니다. 회귀의 잔차 자유도는 보통 관측수에서 설계행렬의 순위를 뺍니다. 논문에 적힌 자유도와 같은 정의인지 먼저 확인해야 합니다.',
    'coefficient': '회귀계수(b)는 해당 모형에서 다른 설명변수 조건을 두고 결과가 얼마나 변하는지 나타냅니다. 단위·코딩·대상·모형 가정에 의존하며, 산술 일치만으로 인과관계를 확인하지 않습니다.',
    'se': '표준오차(SE)는 추정값이 표집에 따라 얼마나 흔들릴지 나타내는 수치입니다. 자료의 표준편차와 다르며, 계산 방법과 모형 가정에 의존합니다.',
}

STATISTIC_LABELS = {'count_rows': '기록 수', 'missing_count': '결측 수', 'mean': '평균', 'tolerance': '허용오차', 'p': 'p값', 'ci': '신뢰구간',
                    'df': '자유도(df)', 'coefficient': '회귀계수(b)', 'se': '표준오차(SE)'}

STATUS_LABELS = {'READY': '선택한 근거 안에서 답변 초안 작성', 'BLOCKED': '답변 보류 · 근거 확인 필요'}

REASON_HELP = {
    'INVALID_QUESTION': '질문의 길이와 내용을 확인하고 더 짧게 적어 주세요.',
    'NO_EVIDENCE': '사용할 원문 근거가 없습니다. 공개 원문을 먼저 확보하세요.',
    'NO_EVIDENCE_OR_INVALID_COUNT': '선택한 근거 개수를 확인하세요.',
    'INVALID_EVIDENCE': '근거 본문 형식을 확인할 수 없습니다. 원문 검색을 다시 실행하세요.',
    'INVALID_EVIDENCE_METADATA': '원문 식별자·DOI·인용 위치를 확인할 수 없습니다.',
    'DUPLICATE_EVIDENCE_ID': '같은 근거가 중복되었습니다. 원문을 다시 검색하세요.',
    'MISSING_OR_INVALID_API_KEY': '서버 연결 설정을 담당자가 확인해야 합니다.',
    'MISSING_OR_INVALID_MODEL': '서버의 허용 모델 설정을 담당자가 확인해야 합니다.',
    'PROVIDER_HTTP_ERROR': '제공사가 요청을 처리하지 못했습니다. 연결·사용량 설정을 담당자가 확인해야 합니다.',
    'PROVIDER_UNAVAILABLE_OR_INVALID_RESPONSE': '제공사 연결이나 응답을 확인하지 못했습니다. 연결 설정을 점검한 뒤 다시 시도하세요.',
    'REQUEST_TOO_LARGE': '전송할 내용이 너무 큽니다. 질문과 근거 개수를 줄여 주세요.',
    'RESPONSE_TOO_LARGE': '응답이 허용 크기를 넘었습니다. 질문 범위를 좁혀 다시 시도하세요.',
    'MODEL_OUTPUT_TOO_LARGE': '모델 답변이 허용 크기를 넘었습니다. 질문 범위를 좁혀 주세요.',
    'INCOMPLETE_MODEL_OUTPUT': '모델 답변이 끝까지 완성되지 않았습니다. 더 짧은 질문으로 다시 시도하세요.',
    'INVALID_OR_MISSING_CITATIONS': '답변의 인용을 선택한 원문에 연결할 수 없어 보류했습니다. 근거를 더 확보하세요.',
    'CRITIC_UNSUPPORTED': '추가 AI 검토에서 답변의 근거가 부족하다고 판단해 보류했습니다. 원문을 더 확보하거나 질문을 좁히세요.',
    'SECRET_IN_INPUT': '비공개 연결정보가 질문 또는 근거에 포함되어 전송을 차단했습니다.',
    'SECRET_IN_MODEL_OUTPUT': '비공개 연결정보가 응답에 포함되어 표시를 차단했습니다.',
    'AGENT_UNAVAILABLE': '검토를 완료하지 못했습니다. 담당자가 응답 형식과 연결을 점검해야 합니다.',
    'Model-reviewed draft; excerpt support is not independent factual verification.': 'AI가 선택한 단락을 검토한 초안입니다. 독립적인 사실 확인이나 사람 승인 완료를 뜻하지 않습니다.',
    'Input excerpts were truncated to the documented byte budget.': '입력 원문이 허용 길이로 축약되었습니다. 원문 전체와 비교한 뒤 사용하세요.',
}


def explain_reason(value):
    text = str(value)
    if text in REASON_HELP:
        return REASON_HELP[text]
    if text.startswith(('INVALID_', 'NON_TEXT_')):
        return '응답 구조를 확인할 수 없어 답변을 보류했습니다. 담당자가 허용 응답 형식을 확인해야 합니다.'
    return text


# [작성: 쉬운 과제 UX 담당] 2026-09-29 case95
# 무엇·왜: 실행상태와 도구능력을 생활언어로 표시 / 입력·출력: 과제·단계코드→한국어 / 검증: test_case95_tasks_ui, 기존 case93 키 유지.
TASK_STATUS_LABELS = {'PENDING': '실행 대기', 'RUNNING': '확인 중',
                      'CHECKED_PARTIAL': '확인 완료 · 한계 포함', 'NEEDS_ATTENTION': '일부 확인 미완료 · 다시 시도 가능'}
TASK_STEP_LABELS = {'search': '공개 원문에서 근거 찾기', 'metadata': '논문 제목·정정 정보 확인',
                    'search_refinement': '선택 논문 안에서 한 번 더 찾기', 'fulltext': '허용된 공개 원문 확인',
                    'calculation': '등록된 논문의 숫자 재계산', 'llm': '유료 AI 사용 여부',
                    'report': '종합 보고서 저장', 'recovery': '중단된 실행 상태 복구'}
TASK_STEP_STATUS_LABELS = {'CHECKED': '확인 완료', 'SKIPPED': '이번 과제에서 사용하지 않음',
                           'NEEDS_ATTENTION': '확인 미완료'}
TASK_TOOL_HELP = {
    'search': '질문이나 검색어로 앱에 보관된 공개 논문 원문을 찾습니다. 결과는 원문 단락·DOI·인용 위치입니다. 인터넷 전체 검색이나 질문의 정답 판정은 아닙니다.',
    'metadata': '선택한 DOI의 공식 Crossref 서지를 조회합니다. 결과는 논문 제목·정정 연결·이전 조회 이후의 서지 변화입니다. 모든 정정·철회를 탐지하지 못합니다. 실행할 때 DOI만 무료 외부 API로 전송합니다.',
    'calculation': '미리 등록한 공개 논문자료와 분석조건만 재계산합니다. 결과는 원문 보고값·계산값·차이·선언된 허용오차입니다. 내 질문으로 찾은 논문이나 내 원자료를 자동 분석하지 않습니다.',
    'llm': '이 과제 실행에서는 유료 AI를 호출하지 않습니다. 근거 수집·서지 조회·등록 계산 결과를 규칙에 따라 모아 보고합니다. 자연어 의미의 진위는 확정하지 않습니다.',
}
TASK_CALCULATION_LABELS = {'ARITHMETIC_MATCH': '보고값과 산술 일치', 'ARITHMETIC_MISMATCH': '보고값과 산술 불일치',
                           'COEFFICIENT_MATCH': '등록 조건의 계수 일치', 'COEFFICIENT_MISMATCH': '등록 조건의 계수 불일치',
                           'MATCH': '등록 비교 기준 충족', 'MISMATCH': '등록 비교 기준 불일치',
                           'BLOCK': '계산 보류', 'BLOCKED': '계산 보류'}
