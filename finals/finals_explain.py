"""판정 코드를 사람이 읽는 문장으로 바꾼다. 코드 자체는 그대로 두고 화면 설명에만 쓴다.

# [작성: 0 이영 · Claude] 2026-10-01 00:37 KST — 검토 중 실제 브라우저에서 확인: "근거 부족"·"자료 변경" 사례의 이유가 JSON 안의 영문 코드
# (ORIGINAL_SOURCE_UNAVAILABLE_OR_HASH_MISMATCH 등)로만 보여 시연 두 번째·세 번째 장면을 처음 보는 사람이 이해하기 어려웠다.
# 순수 함수라 화면과 분리해 시험한다. 알 수 없는 코드는 숨기지 않고 원문 그대로 보여 준다.
"""
from __future__ import annotations

CONDITION_LABELS = {"METHOD": "분석 방법", "COLUMN": "사용 열", "FILTERS": "포함·제외 조건", "DENOMINATOR": "분모",
                    "MISSING_POLICY": "결측 처리", "UNIT": "단위"}
FIELD_LABELS = {"REPORTED_VALUE": "보고값", "SOURCE_QUOTE": "원문 인용", "SOURCE_LOCATION": "원문 위치",
                "CLAIM_TEXT": "주장 문장", "TOLERANCE": "허용오차"}
FIXED = {
    "ORIGINAL_SOURCE_UNAVAILABLE_OR_HASH_MISMATCH": "등록된 원문 출처를 확인하지 못했거나 원문 지문이 달라 계산을 보류했습니다.",
    "SCHEMA_INVALID": "후보 JSON이 허용된 형식이 아닙니다. 필드 이름·형식·값의 범위를 확인하세요.",
    # [수정: 0 이영 · Claude] 작성 시각 미확인; 03 검토 2026-10-01T02:08:17+09:00 — 개인정보 보호 안전장치(finals_privacy) 코드의 설명. 값은 어디에도 싣지 않고 종류만 안내한다.
    "SENSITIVE_CONTENT_BLOCKED": "인증 값이나 개인정보(이메일·전화번호·주민등록번호) 형태의 문자열이 있어 차단했습니다.",
    "APPROVAL_REASON_PERSONAL_DATA": "승인 사유에 이메일·전화번호 같은 개인정보나 인증 값 형태가 있어 저장하지 않았습니다. 이름·연락처를 빼고 다시 적어 주세요.",
    "PERSONAL_DATA_IN_OUTBOUND_PAYLOAD": "외부 AI로 보낼 본문에 개인정보나 인증 값 형태가 있어 전송하지 않았습니다.",
    "EXPLICIT_HUMAN_CONFIRMATION_AND_REASON_REQUIRED": "직접 확인 표시와 3자 이상의 승인 사유가 필요합니다.",
    "NONFINITE_OR_BOOLEAN_NUMBER": "보고값·허용오차는 유한한 숫자여야 합니다.",
    "DUPLICATE_JSON_KEY": "JSON에 같은 키가 두 번 있습니다. 어느 값이 쓰일지 알 수 없어 거부했습니다.",
    "NONFINITE_JSON": "JSON에 NaN·무한대 같은 값이 있습니다.",
    "JSON_INPUT_TOO_LARGE": "입력이 허용 크기(256KB)를 넘었습니다.",
    "DENOMINATOR_MISMATCH": "선언한 분모와 실제로 선택된 행 수가 다릅니다.",
    "APPROVAL_DENOMINATOR_MISMATCH": "선언한 분모와 실제로 선택된 행 수가 달라 승인할 수 없습니다.",
    "NO_OBSERVATIONS_AFTER_FILTER": "필터를 적용하면 남는 행이 없습니다.",
    "MISSING_OR_NONNUMERIC_OBSERVATION": "결측이거나 숫자가 아닌 값이 있어 계산하지 않았습니다.",
    "NONFINITE_OBSERVATION": "무한대·NaN 관측값이 있어 계산하지 않았습니다.",
    "COMMON_BUDGET_EXCEEDED": "정해 둔 모델 호출 횟수·시간 상한을 넘어 중단했습니다.",
    "LIVE_AI_NOT_ALLOWED": "실시간 AI가 운영자 설정으로 꺼져 있습니다.",
    "LIVE_AI_BUDGET_EXHAUSTED": "실시간 AI 호출 상한을 모두 사용했습니다.",
    "MODEL_HTTP_429": "AI 공급자의 사용 한도·잔액 문제로 요청이 중단됐습니다.",
    "MODEL_KEY_UNAVAILABLE": "AI 연결에 필요한 인증 설정이 없습니다.",
    "CANDIDATE_OR_PROVIDER_ERROR": "후보나 AI 응답을 처리하지 못했습니다.",
    "REAL_SAVED_REPLAY_UNAVAILABLE": "저장된 실제 AI 응답을 찾지 못했습니다.",
}
PREFIXES = (("CONDITION_MISMATCH_", CONDITION_LABELS, "후보의 ‘{}’이(가) 등록된 조건과 다릅니다."),
            ("REGISTERED_FIELD_MISMATCH_", FIELD_LABELS, "후보가 ‘{}’을(를) 바꿨습니다. 보고값·인용·허용오차는 후보가 바꿀 수 없습니다."))


def reason_text(code: str) -> str:
    if code in FIXED:
        return FIXED[code]
    for prefix, labels, template in PREFIXES:
        if code.startswith(prefix):
            return template.format(labels.get(code[len(prefix):], code[len(prefix):]))
    if code.startswith("MODEL_HTTP_"):
        return f"AI 공급자가 요청을 처리하지 못했습니다({code[len('MODEL_HTTP_'):]})."
    return code


def reasons(report: dict) -> list[str]:
    """보고서의 오류·검사 실패·보류 사유를 순서를 유지하고 중복 없이 한국어 문장으로 돌려준다."""
    codes = []
    for source in (report.get("errors"), (report.get("validation") or {}).get("errors"), report.get("remaining_issues")):
        codes.extend(str(item) for item in (source or []))
    seen, result = set(), []
    for code in codes:
        text = reason_text(code)
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _number(value) -> str | None:
    return format(value, ".10g") if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def calculation_summary(calculation: dict | None) -> str | None:
    """실행된 산술 검산을 한 문장으로 요약한다. 실행되지 않았으면 None."""
    if not calculation or not calculation.get("executed"):
        return None
    computed, reported = _number(calculation.get("calculated_value")), _number(calculation.get("reported_value"))
    delta, tolerance = _number(calculation.get("delta")), _number(calculation.get("tolerance"))
    if None in (computed, reported, delta, tolerance):
        return None
    verdict = "허용오차 안에서 일치합니다" if calculation.get("within_tolerance") else "허용오차를 벗어났습니다"
    if calculation.get("denominator_matches"):
        denominator = f"선택한 {calculation.get('selected_rows')}행이 선언한 분모와 같습니다."
    else:
        denominator = f"선택된 행 수 {calculation.get('selected_rows')}이(가) 선언한 분모 {calculation.get('expected_denominator')}와 다릅니다."
    return f"계산값 {computed} · 보고값 {reported} · 차이 {delta}(허용오차 {tolerance}) — {verdict}. {denominator}"


# [작성: 0 이영 · Claude] 작성 시각 미확인; 03 검토 2026-10-01T02:13:04+09:00 — 배포본 직접 확인(02:05): '자료 변경 후 재검산' 뒤에도 결과 칸이 "허용오차 안에서 일치합니다"를 그대로 보여 차단 판정과
# 모순돼 보였고, 무엇이 바뀌었는지(이전·현재 지문, 빠진 행, 바뀐 자료로 다시 계산한 값)는 화면 어디에도 없었다. 혁신성의 핵심 장면이라 문장으로 풀어 준다.
def change_summary(report: dict | None) -> list[str]:
    """자료 변경 재검산 결과를 '무엇이 바뀌었나' 문장 목록으로 돌려준다. 변경이 없으면 빈 목록."""
    changed = (report or {}).get("changed_input") or {}
    if not changed.get("detected"):
        return []
    lines = []
    prior, current = str(changed.get("prior_input_sha256") or ""), str(changed.get("current_input_sha256") or "")
    if prior and current:
        lines.append(f"입력 자료의 지문이 달라졌습니다: {prior[:12]}… → {current[:12]}…")
    removed = changed.get("removed_rows")
    if isinstance(removed, int) and not isinstance(removed, bool) and removed > 0:
        lines.append(f"메모리 사본에서 {removed}행이 빠졌습니다. 원본 파일은 바뀌지 않았습니다.")
    calculated_value = (report.get("formal_verification") or {}).get("calculated")
    reported_value = (report.get("calculation") or {}).get("reported_value")
    recalculated, reported = _number(calculated_value), _number(reported_value)
    if recalculated is not None and reported is not None:
        # [수정: 3 조지현 · 2026-10-01T02:16:15+09:00] 표시 문자열의 10자리 반올림이 실제 차이를 숨겨 '같습니다'가 되지 않도록 원수치로 비교한다.
        same_value = calculated_value == reported_value
        if not same_value and recalculated == reported:
            recalculated, reported = format(calculated_value, ".17g"), format(reported_value, ".17g")
        relation = "같습니다" if same_value else "다릅니다"
        lines.append(f"바뀐 자료로 다시 계산하면 {recalculated}이고 보고값은 {reported}로 {relation}. 변경 전의 일치 결과는 더 이상 쓸 수 없습니다.")
    else:
        lines.append("변경 전의 계산·승인은 더 이상 쓸 수 없습니다. 새로 검산하고 사람이 다시 확인해야 합니다.")
    previous = (report.get("human_approval") or {}).get("previous_approval") or {}
    lines.append("이전 사람 승인은 해제됐습니다." if previous.get("approved") else "해제할 이전 사람 승인은 없었습니다.")
    return lines
# [수정: 3 조지현 · 2026-10-01T02:08:17+09:00] 기준 커밋보다 뒤인 주석 시각은 원작성 시각으로 확인할 수 없어 미확인으로 표시했다. 원표기는 별도 검토 기록에 보존한다.

# [3 조지현 · 2026-10-01T02:13:04+09:00] 통합 후 추가 주석의 원작성 시각을 확인할 수 없어 미확인 표시; 실제 검토 시각과 원표기를 분리 기록한다.
