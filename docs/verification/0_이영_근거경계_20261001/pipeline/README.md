# 합성 등록 오류의 실제 manual pipeline 경계 검증

<!-- [작성: 0 이영 · Codex] 2026-10-01T05:33:12.3128547+09:00 — 원문 로더의 위치/자료 의미 경계를 실제 계산·state·can_approve까지 추적하고, 정확 등록값과 다른 후보를 차단하는 기존 보호와 분리한다. 담당 버전 0. 제품·사람 승인·실제 모델 무수정/미호출. -->

**잘못 작성한 합성 등록 메타데이터 4건이 실제 계산을 거쳐 `SUPPORTED_PREVIEW`, `can_approve=True`에 도달했다. 정확한 등록 정보의 위치와 다른 후보를 제출한 통제 1건은 계산 전에 차단됐다.** 모든 보고서의 사람 승인은 `PENDING`이고 `approved=False`다. 계산이 실행된 6건의 공용 core 판정은 `REVIEW`이며 `human_semantic_confirmed=False`다. 이 관측은 최종 승인·과학적 타당성 확인·실제 모델 오류·공개 UI 등록 공격의 재현이 아니다.

## 실제 결과

| 사례 | source_gate | 실제 계산 | state | can_approve | 의미 |
|---|---|---:|---|---|---|
| PL-NORMAL-PARAGRAPH | true | 평균 15.0 | SUPPORTED_PREVIEW | true | 정확한 A 문단·A 자료 |
| PL-NORMAL-TABLE | true | 평균 15.0 | SUPPORTED_PREVIEW | true | 정확한 A 표·A 자료 |
| PL-WRONG-LOCATION | true | 평균 15.0 | SUPPORTED_PREVIEW | true | A 인용에 B 문단 위치를 잘못 등록 |
| PL-OTHER-TABLE-QUOTE | true | 평균 15.0 | SUPPORTED_PREVIEW | true | A 주장·A 표 위치에 실제 B 표의 인용을 등록 |
| PL-WRONG-EXPERIMENT | true | 평균 15.0 | SUPPORTED_PREVIEW | true | A 원문에 B 실험 CSV 및 그 CSV의 정확 해시를 등록 |
| PL-ROWS-NOT-PEOPLE | true | 행수 2.0 | SUPPORTED_PREVIEW | true | 고유 사람1의 방문2행을 개인2명 주장에 등록 |
| PL-REGISTERED-LOCATION-CANDIDATE-CONTROL | true | 미실행 | MISSING | false | 정확한 A 등록에 source_location만 B인 후보 제출 |

마지막 통제의 검증 오류는 `REGISTERED_FIELD_MISMATCH_SOURCE_LOCATION`이다. 미해결 검토 단계에서 `CRITIQUE_EVIDENCE_NOT_READY`와 `CRITIQUE_UNRESOLVED_ISSUES`도 남는다. 다른 6건의 validation.errors는 빈 배열이지만, 사람 의미 확인은 완료되지 않았다.

집계는 정상2건·잘못등록4건·정확등록에 틀린후보 제출 통제1건으로 구분한다. 이전 source_gate 9건, 기존 pytest, C01~C08 봉인 비교, 사람 승인과 합산하지 않는다.

## 입력과 해석의 전제

이번 감사자가 **합성 trusted-registration fixture를 직접 작성했다.** `source_kind=article_extract`, evidence_status, 원문/자료 해시, 위치를 선언한 주체는 감사자이며 실제 발행사·외부 자료 취득기가 아니다. 부정확한 등록 정보가 등록 정답으로 받아들여졌을 때의 경계다. 기존 등록값을 일반 UI에서 바꿀 수 있다는 주장이 아니다.

합성 문서의 위치는 `source_locations.json`에 먼저 고정했다. A와 B는 서로 다른 문단·표이고 인용 내용도 다르다. A 실험의 두 사람은 나이10/20, B의 두 사람은 나이5/25여서 평균만 같다. 반복 방문 CSV는 A1 한 사람의 방문1/2 두 행이다. 값·자료·원문·registry는 전부 합성이며 실제 논문·개인 자료가 아니다.

이전 source_gate 감사의 네 공격 메커니즘을 새 종단 fixture로 재검증했다. 방문행 사례는 이번에 별도 정확한 원문 문장 `Experiment A contained 2 individual participants.`와 count_rows/보고값2를 사용했다. 따라서 이전 시험의 mean/count 메타데이터 불일치를 그대로 반복하지 않았다. 자료는 고유 사람1인 잘못 연결 자료로 의도적으로 유지했다.

## 사전 봉인과 실행 증거

- 고정 코드: `a6729178963392249b14c9dfbd93bf28704262a4`.
- 사전프로토콜 생성: `2026-10-01T05:24:31.384588+09:00`.
- 사전프로토콜 SHA-256: `d8f526a363bd55a3bc1a48a9878cd6f0c6c7164fa4bd6709164e770a1c9804eb`.
- 실제 7건 함수 실행: `2026-10-01T05:25:33.259693+09:00` ~ `2026-10-01T05:25:48.890070+09:00`.
- 환경: Windows, Python3.13.5, pandas3.0.4, numpy2.2.6, scipy1.15.3, jsonschema4.23.0, streamlit1.45.1, numexpr2.10.1. pandas의 numexpr2.10.2 이상 요구 경고1건이 있었고 종료코드0으로 완료했다. 환경 변경·설치는 하지 않았다.
- `finals_pipeline`·`finals_cases` 실제 모듈을 import하고 `run_case(mode='manual')`을 호출했다. 함수 복제·AST 실행·verify/calculation/model/approval monkeypatch·semantic_confirmed 강제 변경은 하지 않았다.
- 변경한 모듈 전역은 데이터 위치5개뿐이다: `finals_cases.REPO_ROOT`, `finals_cases.AGENT_ROOT`, `finals_cases.REGISTRY`, `finals_pipeline.REPO_ROOT`, `finals_pipeline.AGENT_ROOT`. 모두 이 폴더의 합성 fixture를 가리킨다.
- `finals_provenance.ROOT`은 실제 코드 checkout을 유지한다. 실행 provenance의 `code_commit`은 고정 커밋과 일치한다. 데이터루트에 Git 저장소가 없어 최상위 보고서의 `_commit()` 결과는 `UNAVAILABLE`이다. 이를 실제 코드 커밋 부재로 해석하지 않는다.
- 원 코드14파일의 실행 전/후 바이트 해시와 Git 상태가 동일함을 검사했다. Windows CRLF checkout과 Git LF 객체를 별도 원시 해시로 보존하고, 차이가 CRLF뿐임을 검사했다. imported 소스는 정규화하거나 수정하지 않았다.
- `-B` 및 `sys.dont_write_bytecode=True`로 checkout에 bytecode를 쓰지 않았다. 모델/외부API/사람승인 호출0. 기존 제품 registry·키·비공개 DB·외부 네트워크를 읽거나 호출하지 않았다.

## 확인한 코드 경계

`finals_cases.load_case`는 원문/자료 해시와 원문 전체 인용 포함을 확인한다. 실제 지정 위치나 원문이 가리키는 실험과 CSV 실험의 대응은 확인하지 않는다.

`finals_pipeline._validation`은 후보를 등록된 expected_proposal과 비교한다. 정확한 등록 위치를 바꾼 후보는 차단하지만, 등록 정보 자체가 부정확하면 등록값 일치 검사만으로 그 의미를 검증할 수 없다.

`_calculate`의 분모 검사는 선택 행수와 등록 expected_n 비교다. 반복 방문2행은 이 검사에 맞지만 고유 사람1과는 다르다. `_proposal`이 count_rows의 단위를 individuals로 부여하는 동작도 이번 실제 보고서에 남아 있다. 이는 고유 개인 집계의 수행 증거가 아니다.

`SUPPORTED_PREVIEW`와 `can_approve`는 등록된 매핑 아래 산술 일치·사람 확인 동선의 상태다. 공용 core의 `REVIEW`, 미완료 의미 확인, 사람 승인 대기를 별도로 함께 공개해야 한다. 이번 결과를 “사람 승인을 통과했다” 또는 “논문 전체를 검증했다”로 표시하지 않는다.

## 상대경로 재현

공개된 기존 프로토콜과 결과를 보존하려면 **이 pipeline 폴더의 별도 작업 사본**에서 재현한다. 지정 커밋의 읽기 전용 checkout과 필요한 위 환경의 라이브러리가 준비돼 있어야 한다. 새 설치·계정·API 키는 이 실행기에 포함되지 않는다.

```text
python -B 0_이영_pipeline_audit.py --prepare --snapshot ../snapshot
python -B 0_이영_pipeline_audit.py --run --snapshot ../snapshot
```

`--snapshot`은 실제 고정 커밋의 checkout 경로를 받는다. 모든 저장 데이터·프로토콜·결과·CLI는 개인 절대경로 없이 상대경로를 사용한다. --prepare는 그 작업 사본의 합성 fixture와 새 봉인을 만들며 --run은 입력/코드/실행기 지문이 같을 때만 진행한다. 다른 운영체제의 줄바꿈·환경 지문이면 별도 작업 사본에서 새 --prepare 기록으로 구분한다.

## 파일

- [실제 실행기](0_이영_pipeline_audit.py)
- [사전프로토콜](0_이영_pipeline_protocol.json) 및 [봉인 지문](0_이영_pipeline_protocol.sha256)
- [종합 결과](0_이영_pipeline_results.json)
- `reports/`: 각 실제 run_case 보고서7개. 원문·자료·조건·계산·formal/core·사람 승인 상태를 보존했다.
- `synthetic_fixture/`: 새 합성 문서·정확 위치·CSV·등록 manifest.

새 위치/의미 보강의 수용검사에서는 각각 진짜인 원문·해시가 같은 분석을 가리키는지도 확인하고, 거짓 수용과 충분한 정상 입력 처리율을 함께 측정해야 한다. 이번은 그 보강의 구현·성능 입증이 아니다.
