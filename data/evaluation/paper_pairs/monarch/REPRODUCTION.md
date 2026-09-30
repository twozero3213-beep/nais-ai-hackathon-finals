# V59 왕나비 PCA 재계산: 모집단을 고정한 부분 일치

작성: 전문가7 / 2026-09-25. 실제 외부 통계학자·저자 확인을 받은 결과는 아니다.

## 판정

**공통환경 사육 성체 자료의 크기 PC1 설명분산은 96.4087000405%로, 출판 96.4%의 소수 첫째 자리 반올림 범위와 일치한다.** 이는 저자 코드가 지정한 공통환경 성체의 상관행렬 PCA 단계에 한정한 `MATCH_SCOPED_PCA`다. 논문 전체 재현은 `BLOCK`, `reproduced=false`다. 원문의 해당 문장은 PCA 모집단을 명시하지 않으므로 코드에 따른 모집단 연결임을 반드시 함께 표시한다. R 스크립트 자체, 혼합모형, 유의확률, 효과크기, 다른 도판은 실행하지 않았다.

- 출판 근거: [Freedman et al. PNAS 2020, DOI 10.1073/pnas.2001283117](https://doi.org/10.1073/pnas.2001283117).
- 확인한 원문: [저자 연구실 PDF](https://www.sanramlab.org/pubs/Freedman_et_al_2020.pdf), PDF 5/7쪽, Materials and Methods → Data Analysis 첫 문단. 길이·너비·면적의 size PC1 설명분산을 96.4%로 보고한다.
- 모집단 연결: `global_monarch_wing_morphology.R` 440–461행은 common garden data 구간이고 `adult_morphology.csv`를 읽는다. 460행은 `princomp(adults.size.keep, cor = T)`, 461행은 96.4% 주석이다. 이는 야외·박물관 자료의 별도 PCA 163–165행과 구별된다.

## 출처·원파일 무결성

[Dryad DOI 10.25338/B81S7C](https://datadryad.org/dataset/doi:10.25338/B81S7C)는 해당 논문과 자료를 연결하고, adult_morphology.csv를 공통환경 사육 나비의 측정값으로 설명한다. [DataCite DOI 메타데이터](https://api.datacite.org/dois/10.25338/B81S7C)의 rightsList에서 CC0-1.0을 2026-09-25 확인했다. 이는 등록 데이터셋의 라이선스 기록이다.

새 파일은 [저자 GitHub 고정 커밋 원파일](https://raw.githubusercontent.com/micahfreedman/manuscripts/9f10e8807b644e0ea33ffc3b152584e62e776ea4/Freedman_et_al_monarch_global_wing_morphology/data_and_analysis/monarch_morphology_primary_analysis/adult_morphology.csv)에서 받았다. Dryad 사본과 바이트 동일성을 주장하지 않는다. 이 GitHub 사본은 210,773 bytes, SHA-256 `d85aec46430c571546504a2c6b8982fd187b8d60f2d0e517f890b46bc349a39b`다.

기존 wings CSV `4208ca6ee43815c0da845fe59200b3ec1005cff0a778217b7eed4bf1c47a88f2`와 R 코드 `8a25e90d0f8054c26f3fd1ac8914d46787f02816493a44f38903f85c719df308`는 변경하지 않았다. 세 파일을 감사 실행 때 모두 확인하며, 하나라도 달라지면 계산 전에 차단한다.

## 정확한 모집단·계산·분모

1. `adult_morphology.csv`의 1,076행에서 R 코드 446행과 같이 오른쪽 면적 RArea 결측인 104행을 제외한다. 남는 분석 관측은 972행이며 AU/CA/ENA/GU/HI/PR의 여섯 모집단을 포함한다.
2. 각 행에서 왼쪽·오른쪽의 면적, 길이, 너비를 각각 평균한다. 한쪽만 있으면 그쪽을 사용한다(`rowMeans(..., na.rm=T)`). 야외 표본의 성별·지역·연도 필터를 적용하지 않는다. 감염 여부·암수 필터도 이 PCA에는 없다.
3. 행렬 열 순서는 MArea, MLength, MWidth. 972행 모두 이 세 값이 유효하다. 예상 밖 양쪽 결측/비유한 값은 임의 보간이나 추가 제외 없이 오류로 중단한다.
4. 저자 `cor=T`와 같이 상관행렬을 구해 고유값을 내림차순 정렬하고 `100 × 최대 고유값 / 고유값 합계`로 계산한다. 고유값은 약 2.892261001215, 0.093271819156, 0.014467179629다. 고유값 합계 3은 표준화된 세 변수의 총분산이며, 관측 분모는 972행이다.
5. 결과 96.4087000405%와 출판 96.4% 차이는 0.0087000405%p. 비교 허용범위는 소수 첫째 자리 반올림에 따른 0.05%p이다. 분석에 사용한 CSV 행번호 순서의 해시도 JSON에 남긴다.

[R princomp 공식 문서](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/princomp.html)는 `cor`에 따라 상관/공분산 행렬을 사용함을 설명한다. 기본값은 FALSE지만 이 성체 분석 코드는 명시적으로 TRUE를 준다. 반올림 일치는 전체 연구의 통계 타당성을 입증하지 않는다.

## 교차검증에서 수정한 오연결

초기 탐색에서 야외·박물관 wings 자료의 공분산 PCA를 같은 96.4%와 비교해 99.1782214971%(6,356행)를 얻었다. 코드 뒤쪽의 공통환경 PCA를 확인하자 **다른 모집단·다른 표준화 설정을 비교한 것이 드러났다**. 따라서 이를 논문 오류나 확정 MISMATCH로 채택하지 않았다. 최종 JSON은 성체 PCA만 다루며 원문의 모집단 명시 부족은 별도 BLOCK 사유로 유지한다.

## 실행 및 시험

```powershell
python tools/reproduce_monarch.py --output data/evaluation/paper_pairs/monarch/audit_result.json
python -m pytest tests/test_v59_monarch.py -q
```

감사 CLI의 Python 종료코드 2는 전체 논문 재현 승인이 BLOCK임을 뜻한다. JSON은 시간·랜덤값 없이 결정적이다. 같은 입력에서 다시 생성한 결과와 저장 JSON을 시험으로 대조한다.

테스트를 먼저 만들었을 때 모듈 미구현으로 수집 실패했다. 모집단 오연결을 바로잡는 시험을 먼저 바꾼 뒤 이전 구현에서 3개 실패/2개 통과를 확인했다. 올바른 성체 필터·상관 PCA 구현 후 **5개 통과, 환경 경고 1개**(로컬 numexpr가 pandas 권장 버전보다 낮음). 검증은 출판 반올림·분모, 한쪽/양쪽 결측, 변조 원파일 사전차단, 독립 pandas 전처리+표준화 SVD와 NumPy 상관행렬 고유값 결과의 일치, 저장 JSON 현재성을 포함한다.

실행 환경: Python 3.13.5, NumPy 2.2.6, pandas 3.0.4, pytest 8.3.4. 이 환경에서의 Python 재계산이며 프로젝트 requirements 버전 그대로의 설치나 R 3.6.3 실행을 주장하지 않는다.

남은 일은 출판 문장의 모집단을 저자 근거로 더 명확히 고정하고, R/패키지 환경에서 원본을 실행해 보관하는 것이다. 그 전에는 `paper_population_explicit=false`, `r_script_executed=false`, 전체 `BLOCK`을 유지한다.
