# 0 이영 · 허용 계산/정규화 경계 실험

<!-- [작성: 0 이영 · Codex · 버전 0] 2026-10-01T05:27:03+09:00 — 사전 예상·지문 봉인 뒤 실제 함수를 합성 자료로 실행했다. 제품 수정·모델·키·네트워크·실DB·최종 승인 실행 없음. -->

고정 소스: `a6729178963392249b14c9dfbd93bf28704262a4`. 봉인 2026-10-01T05:26:36+09:00, 실행 2026-10-01T05:27:02+09:00 ~ 2026-10-01T05:27:03+09:00.
10쌍, 총 22개 입력. 결과의 source_gate=True와 human-confirmed=True는 합성 입력 전제다. 실제 loader/원문 검증·최종 UI·최종 사람 승인 결과가 아니다.

|쌍|입력|선택행(예상)|실제 finals 계산|의미 예상|실제 core verify|분모 일치|
|---|---|---|---|---|---|---|
|N01|attack:distinct_codes|[0, 1] ([0])|20.0|10|Status.SUPPORTED|False|
|N01|normal:numeric_representation|[0, 1] ([0, 1])|20.0|20|Status.SUPPORTED|True|
|N02|attack:percent_is_distinct_code|[0, 1] ([0])|20.0|10|Status.SUPPORTED|False|
|N02|normal:same_numeric_group|[0, 1] ([0, 1])|20.0|20|Status.SUPPORTED|True|
|N03|attack:large_integer_codes|[0, 1] ([0])|20.0|10|Status.SUPPORTED|False|
|N03|normal:small_integer_codes|[0] ([0])|10.0|10|Status.SUPPORTED|True|
|N04|attack:three_distinct_codes|[0, 1, 2] ([0])|20.0|10|Status.SUPPORTED|False|
|N04|normal:confirmed_binary_alias|[0, 1, 2] ([0, 1, 2])|20.0|20|Status.SUPPORTED|True|
|N05|attack:null_value|[0, 1] ([0, 1])|ValueError:MISSING_OR_NONNUMERIC_OBSERVATION|None|Status.SUPPORTED|미실행|
|N05|attack_variant:nan_value|[0, 1] ([0, 1])|ValueError:MISSING_OR_NONNUMERIC_OBSERVATION|None|Status.SUPPORTED|미실행|
|N05|attack_variant:inf_value|[0, 1] ([0, 1])|ValueError:NONFINITE_OBSERVATION|None|Status.REVIEW|미실행|
|N05|normal:finite_mean|[0, 1] ([0, 1])|15.0|15|Status.SUPPORTED|True|
|N06|attack:zero_selected_rows|[] ([])|ValueError:NO_OBSERVATIONS_AFTER_FILTER|0|Status.SUPPORTED|미실행|
|N06|normal:one_selected_row|[0] ([0])|1.0|1|Status.SUPPORTED|True|
|N07|attack:finite_true_mean_overflow|[0, 1] ([0, 1])|ValueError:기술통계 결과를 유한하게 계산할 수 없습니다.|1E+308|Status.REVIEW|미실행|
|N07|normal:finite_without_overflow|[0, 1] ([0, 1])|1e+307|1E+307|Status.SUPPORTED|True|
|N08|attack:integer_exact_mean|[0, 1] ([0, 1])|9007199254740992.0|9007199254740993|Status.SUPPORTED|True|
|N08|normal:small_integer_exact_mean|[0, 1] ([0, 1])|3.0|3|Status.SUPPORTED|True|
|N09|attack:duplicate_person_weight|[0, 1, 2] ([0, 1, 2])|13.333333333333334|15|Status.SUPPORTED|True|
|N09|normal:one_row_each_person|[0, 1] ([0, 1])|15.0|15|Status.SUPPORTED|True|
|N10|attack:nonzero_with_zero_tolerance|[0] ([0])|5e-13|5E-13|Status.SUPPORTED|True|
|N10|normal:exact_zero|[0] ([0])|0.0|0|Status.SUPPORTED|True|

## 해석 경계

문자 코드의 의미 예상은 프로토콜에 고정된 사전 전제다. 숫자 1과 1.0을 같은 수치 집단으로 보는 정상 사례와 고유 코드의 오병합을 구분한다. 현재 정규화에 열별 사전/동치 정책이 없어 이 구별이 자동으로 되지 않는지 관측한다.
null/NaN/inf·빈 집단·overflow에서 실제 차단된 결과는 보호 동작 또는 정상 처리 범위의 정책 차이로 남긴다. 차단된 사례를 성공 반환 취약점으로 계산하지 않는다.
중복 참가자 사례는 행 평균 자체의 산술 오류가 아니다. 참가자 한 명당 동일 가중이라는 의미 계약을 현재 행 기반 입력이 표현하지 못해 평균이 바뀌는 입력 위험이다.
공개 원문/새 논문 재현·LLM 응답·브라우저 상태·실제 승인 결과를 실행하지 않았다. 최소 수정 위치와 확인된 사실은 아래 후속 해석에 적는다.

<!-- [추가: 0 이영 · Codex · 버전 0] 2026-10-01T05:40:20+09:00 — 결과를 source_gate/human-confirmed 합성 전제로 한정하고 별도 교정 기대 회귀와 최소 수정안을 인계한다. 원프로토콜/실행결과는 변경하지 않는다. -->

N08에서는 실제 값 9007199254740992.0과 정확한 평균/보고 정수 9007199254740993의 차이가 0으로 반환됐다. N10은 선언 오차 0/1e-13을 고정 1e-12로 넓힌다. N01~N04 필터 오병합은 분모 불일치가 실제로 검출되었으므로 최종 통과 문제로 보고하지 않는다. 회귀 교정 기대는 12시험 중 예상 실패7/정상 성공5/errors0이며, 기존 10쌍22입력과 합산하지 않는다. 상세 정책/수정 pending/기존 회귀는 0_이영_수치경계_패치제안.md에 있다.
