# 실제 논문·저자 원자료 쌍: V55 수집 기록

V59 후속 검증: `horse/REPRODUCTION.md`와 `horse/audit_result.json`은 Table 3 elevated-neck 관측 합계 PR 1/Control 4·결측 2/1을 기록한다. lowered-neck 혼합모형 OR는 미실행으로 BLOCK이다. `monarch/REPRODUCTION.md`와 `monarch/audit_result.json`은 저자 공통환경 성체 972행의 크기 PCA 96.4087000405%가 보고 96.4%와 반올림 일치함을 기록한다. 출판 문단에 모집단이 직접 쓰이지 않았고 저자 R 전체가 미실행이라 전체 재현은 BLOCK이다. 아래 V55 기록은 수집 당시 상태를 보존한다.

2026-09-25에 논문 본문의 자료 공개 진술과 저자 자료 저장소를 대조하고, 아래 파일만 내려받아 SHA-256 해시로 고정했다. 논문의 통계 결과를 재현했다는 뜻은 아니다. 평가용 사람이 승인한 정답 라벨도 아직 없다.

## 말 행동·먹이 보상 (PLOS ONE, 2023)

- 논문: https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0286045
- 저자 자료: https://doi.org/10.6084/m9.figshare.21714233.v1 (Figshare, CC BY 4.0). 논문 Data Availability가 이 DOI를 직접 가리킨다.
- 원자료: `horse/Dados_Laize_ISAE2021.csv` (Figshare file 38522228, 9,954 B, SHA-256 `33bf5378de32b8c54c412ed4ea929f45174bc1981031f194813daed92f1fcbde`); `horse/data_EquiFACS_Extras_and_all_F.csv` (38522231, 4,102 B, `1d545da538d86569cf29c84b80a247412cb816a7fc136bc645855654780d2abd`); `horse/EquiFACS_AUH13_And_Extras.csv` (38522234, 2,957 B, `a6c71418a8fa6ee9f52d920b5514e0f7a43fa3e5a34e19803ed4a5bf6577a9c8`). 다운로드 URL은 `https://ndownloader.figshare.com/files/` 뒤에 각 번호를 붙인다.
- 저자 분석 스크립트: `horse/running_script_Carmo_et_al.Rmd` (38522207, 28,478 B, `bef787092de1ca6764f48fd0fcc2ffb26c12952b334a82d74d54af421cecae60`). 실행하지 않았다. PDF 형태의 실행 출력은 포함하지 않았다.
- 논문 정량 주장 후보: 13마리 암말; 먹이 보상 단계의 lowered neck 확률이 baseline 대비 낮다는 혼합 로지스틱 분석(OR 0.05, 95% CI 0.00–0.56, P=0.05). 보상 단계와 대조 단계 차이는 P=0.11이었다. 분석은 개체 반복측정과 교차 설계를 반영해야 하므로 `NECK_ABAIXO` 열의 단순 평균으로 OR을 검증하면 안 된다.
- 파일 구조 점검: 주 행동 CSV 117행·24열, `NOME` 고유값 13개. 이는 표본 수에 대한 기초 점검이며 OR 재현이 아니다.
- 상태: `SOURCE_PAIR_ACQUIRED_ANALYSIS_PENDING`; 사람 승인 라벨 없음. 통계 명세와 원본 스크립트 환경을 확인할 때까지 OR 실행 차단.

## 왕나비 날개 형태 (PNAS, 2020)

- 논문: https://www.pnas.org/doi/10.1073/pnas.2001283117
- 저자 등록 자료: https://datadryad.org/dataset/doi:10.25338/B81S7C (Dryad, CC0). 이 레코드는 논문 DOI와 주 분석 원자료·코드를 직접 연결한다.
- 파일 확보 경로: 저자 공개 GitHub 저장소 `https://github.com/micahfreedman/manuscripts/tree/9f10e8807b644e0ea33ffc3b152584e62e776ea4/Freedman_et_al_monarch_global_wing_morphology/data_and_analysis/monarch_morphology_primary_analysis`. 두 파일을 이 커밋의 원파일과 바이트 대조했다. Dryad 직접 다운로드는 이 환경에서 401/403으로 막혀 저자 미러를 사용했다. 따라서 Dryad 수록본과 바이트 동일성을 주장하지 않는다.
- 원자료: `monarch/wings_04.25.20.csv` (1,337,388 B, SHA-256 `4208ca6ee43815c0da845fe59200b3ec1005cff0a778217b7eed4bf1c47a88f2`). 저자 분석 코드: `monarch/global_monarch_wing_morphology.R` (45,911 B, `8a25e90d0f8054c26f3fd1ac8914d46787f02816493a44f38903f85c719df308`). 코드는 실행하지 않았다.
- 논문 정량 주장 후보: 박물관 표본 6,000개 이상 측정. CSV는 7,039행·27열, `SampleID` 고유값 6,741개다. 논문 분석에 실제 포함된 표본은 저자 스크립트의 필터·결측 처리에 따라 달라지므로 이 행 수만으로 주장 재현 결론을 내리지 않는다.
- 상태: `SOURCE_PAIR_ACQUIRED_ANALYSIS_PENDING`; 사람 승인 라벨 없음. 도판별 분석 집단과 필터 확인 전까지 통계 결과 실행 차단.

## 제외한 후보

가뭄 실험 논문과 Dryad 자료 DOI `10.5061/dryad.3j9kd51rb`의 연결은 확인했다. 하지만 이 환경에서 저자 원파일 다운로드가 401/403으로 실패했다. 메타데이터만 가진 사례를 확보 완료 수에 넣지 않았다.
