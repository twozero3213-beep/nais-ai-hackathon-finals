# 내부 사전등록 탐색 평가 — case61

현재 실제 사람 라벨과 실제 대조 모델 실행은 없습니다. 빈 템플릿은 `NOT_SCORED / PENDING_REAL_HUMAN_LABELS`입니다. 테스트의 모든 사람·모델 기록은 **합성 fixture**이며 실제 검토자, 실제 시간, 독립 검증 또는 제품 우위의 증거가 아닙니다. 코드의 가상 전문가 표기도 AI 작업 역할입니다.

`core/evaluation.py`의 기존 외부 독립 판정자 2인 게이트는 변경하지 않았습니다. 별도 `tools/internal_evaluation.py`는 팀원/개발자의 실제 사람 검토를 허용하되 개발 관여와 역할을 공개하는 내부 탐색 계층입니다. 결과 상태는 `INTERNAL_EXPLORATORY_SCORED`이며 외부 검증 점수와 바꿔 쓸 수 없습니다.

1. 기존 exploratory spec의 cases(원문 파일, CSV, 고정 프롬프트, 계산 방식)에 `internal_protocol`을 추가합니다. blank template의 해당 구조를 사용합니다. 실제 검토자 ID·역할·개발 관여, 두 시스템의 버전/모델/설정, 판정 기준(범위 일치, 허용 오차 결정 규칙 포함)을 먼저 작성합니다. `labels_and_runs_not_started`는 사실일 때만 true로 바꿉니다. 입력 cases는 비워 두면 freeze를 통과하지 않습니다.
2. 라벨 작성과 시스템 실행 **이전**에 `python -m tools.internal_evaluation freeze spec.json manifest.json`을 실행합니다. 같은 폴더에 manifest를 만들고 출력된 SHA-256을 팀 기록에 별도로 보관합니다. 시각과 선언은 자기신고이며 로컬 해시는 외부 타임스탬프/신원 인증을 대신하지 않습니다. 프로토콜 변경 시 새 평가로 시작하며 기존 출력에 맞춰 규칙을 수정하지 않습니다.
3. 등록된 실제 사람이 출력에 블라인드된 상태에서 모든 claim의 `human_labels`를 작성합니다. 각 행에 claim_id, reviewer_id, human_attestation=true, blind_to_outputs=true, protocol_sha256, source_hash(CSV), source_location, rationale, reviewed_at(시간대 포함), expected_action(BLOCK/EXECUTE), expected_value(BLOCK이면 null), tolerance(유한한 0 이상 숫자)를 기록합니다. 개발 참여자가 검토하면 편향이 남으며 독립 검증이라고 표현하지 않습니다.
4. 같은 모든 입력·프롬프트로 product/model을 각각 실행하여 기존 exploratory observations의 product_results_file와 model_runs를 채웁니다. 모든 행에 protocol_sha256, product 행에 created_at, model provenance에 provider/model/run_id/created_at을 기록합니다. 모든 사람 라벨 확정 시각은 freeze 이후, 두 시스템의 모든 실행 시각은 모든 라벨 확정 이후여야 합니다. 모델 원시 파일은 action/value JSON이고 해시로 보존합니다. 수동 parsed_output은 이 프로토콜에서 허용하지 않습니다. 실패·차단도 빼지 말고 기록합니다. 이 도구는 모델 호출을 실행하지 않습니다.
5. `python -m tools.internal_evaluation compare manifest.json observations.json report.json --expected-manifest-sha256 <보관한 SHA-256>`으로 검증합니다. 출력 덮어쓰기는 거부합니다. `freeze_internal(spec_path)`와 `compare_internal(manifest_path, observations_path, hash)` Python API도 동일합니다.

지표 정의:

- false_execution_rate = 사람이 BLOCK으로 판정한 사례에서 EXECUTE한 수 / 사람이 BLOCK으로 판정한 모든 사례 수. 분모 0이면 null.
- decision_accuracy = 사람 행동 판정과 일치한 수 / 전체 사례 수. 숫자가 맞아도 부적절한 실행은 행동 정답이 아닙니다.
- numeric_reproduction_rate = 사람이 EXECUTE로 판정한 사례에서 실제 EXECUTE하고 사람 예상값과 허용 오차 내 일치한 수 / 사람이 EXECUTE로 판정한 모든 사례 수. 차단도 분모에 포함하며 분모 0이면 null.
- arithmetic_observations는 기존 독립 재계산 결과이며 원문과 자료 범위의 적합성을 증명하지 않습니다.
- 사람 검토시간은 선택 항목입니다. observations의 `human_review_records`에 system(product/model), claim_id, reviewer_id, human_attestation=true, kind=human_review, seconds, started_at, ended_at, record_ref, protocol_sha256를 실제 타이머/활동 기록에서 입력합니다. seconds는 두 시각 차이와 일치해야 하며 started_at은 대응 시스템/Claim의 실행 결과 created_at 이후(동일 시각 포함)여야 합니다. 양쪽 시스템에서 모든 동일 Claim의 사람 기록이 완비된 경우에만 중앙값을 표시합니다. 불완전·비대응 기록은 중앙값 null과 관찰 표본 수를 분리하며 review_time_paired_complete=false로 표시합니다. 누락 시간을 추정하지 않습니다. 머신 실행시간을 사람시간으로 복사하면 안 됩니다. 기록 없으면 중앙값 null, n=0입니다.

인증 한계: 도구는 파일·해시·구조·선후관계의 일관성을 검사합니다. 인간 여부, 블라인드 준수, 진짜 시각, 신원, 프로토콜 해시의 최초 공개 시점은 외부에서 확인해야 합니다. 내부 소표본 탐색 결과만으로 통계적 우위·시간 절감·현장 효과를 주장하지 않습니다.

검증: `uv run --no-project --python 3.13 --with-requirements requirements.txt python -m pytest -q tests/test_case61_evaluation.py`.
