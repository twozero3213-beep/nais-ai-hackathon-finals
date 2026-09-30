# 공개 논문 본문 출처

- 논문: Horst, Hill & Gorman (2022), *Palmer Archipelago Penguins Data in the palmerpenguins R Package*, The R Journal, RJ-2022-020.
- 공식 페이지: https://journal.r-project.org/articles/RJ-2022-020/
- 본문 라이선스: Creative Commons Attribution 4.0 International (CC BY 4.0). 저작자와 출처를 표시하여 재사용.
- `penguin_article_text.txt`: 공식 HTML의 본문 문단·표 행·제목·그림 설명을 `core.pdf_claims.extract_html_blocks`로 순서대로 추출한 텍스트. 선택한 수치 문장만 발췌하지 않았음. 그림과 수식 구조는 완전히 보존되지 않으므로 HTML/PDF와 사람 대조가 필요.
- 수집일: 2026-09-25. 수집한 공식 HTML SHA-256: `6709038972ec7b55ad9ac68bcaf783758d3659b3d8c6c9ec9c030e8f10f3d71e`.
- 변환 본문 SHA-256: `82d1f6ac3c5a80103a865e9d09e84a422f29ac9b05f819170b91baeda042604a`.
- `data/penguins_public_benchmark.csv`는 이전 버전부터 포함된 원자료이며, 해당 파일의 별도 출처·가공 내역은 기존 README와 데이터 문서를 참조.

원문 후보 추출은 정답 라벨이 아니다. 344개 행과 19개 결측 셀은 이 사례에서 재계산되지만, 같은 문장이 의도한 데이터 범위는 연구자가 원문과 데이터 설명을 확인해야 한다.


## V53 원자료 원출처 대조

- 저자 공식 GitHub 저장소 `allisonhorst/palmerpenguins`, 커밋 `8957207b78d6ccd1b4654a9dd9c9041b657478ab`: `inst/extdata/penguins_raw.csv`, `inst/extdata/penguins.csv`. 파일 해시·행·열·결측 변환 검사는 `data/evaluation/README.md`와 `tests/test_v53.py`에 기록했다.
- UCI Wine Quality 공식 ZIP: `https://archive.ics.uci.edu/static/public/186/wine+quality.zip`. 재다운로드한 CSV 두 개와 묶음의 파일 바이트 일치를 확인했다.
- Datasaurus는 여전히 공개 미러이며 저자 원본과 바이트 동일성 미확인이다.
