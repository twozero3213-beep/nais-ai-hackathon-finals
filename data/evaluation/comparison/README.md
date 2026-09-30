# 동일 입력 탐색 대조 — V55

2026-09-25 한 번 실행했다. 네 사례 모두 R Journal 펭귄 논문의 같은 문단을 근거로 한다. 17열 저자 원자료와 8열 저자 가공본 각각에서 344행을 확인하는 정상 2건, 원문이 지목한 자료의 열 범위와 CSV가 다른 차단 2건이다. 부정 사례는 평가자가 구성한 범위 교환 대조군이며 독립 사람 정답이 아니다.

- 입력: `paper_excerpt.txt`, `raw.csv`, `curated.csv`, `spec.json`. 각각 저자 출처는 상위 `SOURCE_ATTRIBUTION.md`와 `README.md`를 참조한다.
- 결과 관찰 전 `tools/compare_exploratory.py freeze`로 `manifest.json`을 만들었다. 고정 SHA-256은 `078b771c1a99f228e280cdfb53fa16e930997d4c1563b2a5ededf10b325b38b9`이다. `trial_prompt.txt`는 네 사례를 한 번의 모델 호출에 전달한 정확한 전체 지시이며 SHA-256은 `c4d881e3e23a5acbd066855f7b0a191889a23507b8351b3616b7f5293ad4bfe4`이다.
- 범용 모델: 격리된 입력 폴더, Codex CLI `gpt-6-sol`, medium, 읽기 전용, 단일 호출. 최종 원출력 `model_raw.json`을 수정 없이 보존했다. ChatGPT 일반 사용자의 결과나 여러 모델 반복 결과가 아니다.
- 제품: 동일 Claim 문구·CSV·집계 방법·자료 범위를 `product_cases.json`의 확인된 평가용 매핑으로 주고 `tools.run_corpus_system.run_system`을 호출했다. 실제 사람의 의미 연결 확인은 없으며 `confirmation_source=evaluation_oracle_fixture_not_human`이다. 제품은 원문을 자율적으로 읽고 매핑하지 않았다.
- 관찰: 두 시스템 모두 정상 2건 `EXECUTE` 344, 범위 불일치 2건 `BLOCK`; 행동 일치 4/4, 제품 산술 재계산 일치 2/2. **제품의 범용 AI 우위는 관찰되지 않았다.** 4건이 같은 논문·간단한 행 수에 국한되어 거짓 실행률, 재현률, 검토 시간 또는 통계적 우위를 계산하지 않는다.
- 초기 비교 도구가 산술 계산 가능한 두 범위 불일치 사례를 `potential_overblock`으로 집계했다. 이 판정은 틀렸다. V55 회귀 시험에서 수정 전 실패를 확인하고, `report.json`에 `potential_overblocks: null`과 별도의 `blocked_replayable: 2`를 기록했다. 산술 가능성은 원문-자료 범위 적합성의 근거가 아니다.

압축을 푼 루트에서 재검증:

```powershell
python tools/compare_exploratory.py compare data/evaluation/comparison/manifest.json data/evaluation/comparison/observations.json data/evaluation/comparison/rechecked.json --expected-manifest-sha256 078b771c1a99f228e280cdfb53fa16e930997d4c1563b2a5ededf10b325b38b9
```

`rechecked.json`이 이미 있으면 도구는 덮어쓰지 않고 중단한다. `report.json`은 최초 기록이며 `observations.json`에 제품 출력·원출력 해시·모델 정보를 연결했다. SHA-256은 파일 변조를 감지하지만 논문-자료 의미 연결과 모델 제공자 신원을 증명하지 않는다.
