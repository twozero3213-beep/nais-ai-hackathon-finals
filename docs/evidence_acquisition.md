# case61 신규 논문·원자료 확보

2026-09-26 확인. 신규 독립 원자료 1쌍 확보, 새 실행 검증 Claim 0건. 등록 제안은 PENDING이며 기존 registered_cases.json은 수정하지 않았다.

## 원출처와 이용조건

Skylark WJ, Callan MJ (2021), Personal relative deprivation and pro-environmental intentions, PLOS ONE 16(11), e0259711.
- 논문: https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0259711
- 원 CSV: https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0259711.s005&type=supplementary
- 저자 R: https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0259711.s008&type=supplementary
- 라이선스: CC BY 4.0, https://creativecommons.org/licenses/by/4.0/
- 출판사 정책: https://journals.plos.org/plosone/s/licenses-and-copyright

논문 copyright의 CC BY 4.0 링크와 출판사 정책의 출판물 범위를 확인했다. S1 Data 및 S1 Script는 논문에 직접 연결된 저자 보충자료다. 위 저자·출처를 표시하고, CSV/R 다운로드 바이트는 변경하지 않았다. 원본 CSV에는 공개된 익명 응답 ID와 설문 응답·시각이 있다. 재식별·외부 데이터 결합은 하지 않았다.

웹 도구의 보충자료 캐시 리다이렉트는 실패했으나 동일 출판사 공식 URL에 PowerShell Invoke-WebRequest를 실행하여 CSV와 R을 정상 확보했다. 새 PDF는 생성·다운로드하지 않았다. 인용 발췌는 공식 HTML에서 문자열 일치를 확인해 UTF-8로 저장했다. 전체 HTML 사본은 보관하지 않았다. 정확한 UTC 시각·URL·SHA-256·크기는 data/evaluation/paper_pairs/deprivation/provenance.json에 있다.

## 연결할 수 있는 범위

Methods / Participants 마지막 문단의 16단어 발췌:
> The final samples comprised 308, 409 and 423 participants for Studies 1, 2, and 3, respectively

Study 1의 최종 분석표본 308명만 후보로 삼았다. 본문에서 최초 383명이라는 문장은 발견하지 못했다. 따라서 관측 CSV의 383행을 새 논문 Claim으로 바꾸지 않는다.

원 CSV는 383행·45열, ResponseId 383개가 서로 다르다. 저자 R 361–363행은 S1 Data를 읽어 US의 get_exclusions를 적용한다. 13–50행의 제외 과정을 일회성 PowerShell Import-Csv/Where-Object로 옮겨 산술 대조했다.

| 단계 | 남은 행 |
| --- | ---: |
| 원 CSV | 383 |
| 전체 열 complete case (빈 문자열·NA 제외) | 367 |
| SSS가 포함된 열의 합 = 1 | 329 |
| duplicate = 0 | 311 |
| 18 ≤ age ≤ 100 | 311 |
| ENV_5 = 2 | 308 |

308은 보고값과 산술적으로 일치한다. 이 대조는 저자 R 전체 실행도, 제품 계산 경로 실행도, 의미 범위 인증도 아니다. 인과효과·상관·회귀·다른 연구 표본은 검증하지 않았다. 파생 CSV를 만들지 않았고 기존 원본·엔진·Claim ID 분기는 변경하지 않았다.

기존 등록의 count_rows 및 단순 동등조건만으로는 전체 열 완전사례, 행별 SSS 합, 연령 범위를 표현할 수 없다. 원 CSV 전체를 계산하면 383이므로 보고값 308 검증 성공으로 기록하면 잘못이다. 이 사례는 자료 연결과 지원되지 않는 전처리의 차단 근거이며 신규 실행 검증 0건으로 집계한다.

## 인계

- 제안: docs/evidence_acquisition_proposal.json, scope_status=PENDING.
- 원본·발췌·출처: data/evaluation/paper_pairs/deprivation/.
- 산술 대조: acquisition_audit.json. 사람 정답 라벨·확인자·외부 전문가 인증은 만들지 않았다.
- 향후 작업: 실제 지원되는 명시적 전처리 계약과 별도 검사 없이는 등록 상태를 실행 가능으로 바꾸지 않는다. 현재 작업에서 이를 억지로 구현하지 않았다.
