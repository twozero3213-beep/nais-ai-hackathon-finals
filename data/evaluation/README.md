# 실제 논문·원자료 평가 묶음

V55 새 자료 두 쌍은 `paper_pairs/README.md`, 사전 고정한 동일 입력 네 건의 제품·범용 AI 탐색 대조는 `comparison/README.md`를 참조한다. 네 건은 모두 같은 펭귄 논문의 행 수 사례여서 동률이며, 사람 승인 정답 점수나 우위 근거가 아니다. 아래 V53 대조 기록은 당시 정보 비대칭을 보존한 역사 자료다.

V46에는 R Journal 논문 전체 본문을 변환한 `penguin_article_text.txt`가 포함됩니다. 앱은 이 파일 전체에서 위치가 붙은 후보를 뽑습니다. 344행 문장은 17변수 원자료를 말하므로 8열 CSV를 연결하면, 행 수가 같아도 범위 충돌로 차단합니다. 19결측 셀은 명시 범위 충돌이 없으면 사람 확인 뒤 재계산합니다. 이는 연구자 승인 정답 평가가 아닙니다. 원문 라이선스·변환·해시는 `SOURCE_ATTRIBUTION.md`를 보세요. 평가 도구 `run_corpus_system`은 Claim ID 분기 없이 typed contract를 사용하지만, `oracle_mapping_supplied`가 참인 세 사례에만 평가용 조건 매핑이 제공됩니다. 이 수치를 블라인드 추출 성공률로 해석하지 마세요.

`cases.json`은 펭귄, Wine Quality, Datasaurus 연구의 원문 수치·원자료 경로·해시·분석 조건을 담습니다. `gold_proposals.json`은 평가 전 별도 사람이 확인해야 하는 **제안 라벨**입니다. 현재 6건 모두 `PENDING_HUMAN`이며 공식 거짓 실행률·재현률을 계산하지 않습니다. 연구자 1명의 검토로 후보를 만들고, 다른 독립 연구자가 앱·범용 인공지능 결과를 보지 않은 채 같은 원문·원자료를 판정해야 합니다. 두 사람이 동의하지 않으면 이견을 해결하기 전까지 점수화하지 않습니다. `verified_by`의 팀원 이름과 `APPROVED`만 입력해도 승인되지 않습니다.

V49 채점 라벨은 각 Claim에 `independent_reviews` 두 건 이상을 요구합니다. 각 기록에는 서로 다른 `reviewer_id`, 외부에서 관리하는 `identity_check_ref`, `independent_of_development=true`, `blind_to_outputs=true`, `source_location`, `data_sha256`, `expected_action`, 실행 가능한 경우 `expected_value`, `rationale`가 필요합니다. 두 판정의 행동·값과 사례 원자료 해시가 최종 라벨과 일치해야 합니다. 승인 수정 이력과 신원 확인 근거는 팀 밖에서 보존·검수하세요. 비교기는 **필드 구조와 값의 일치만** 확인하며, 이름·블라인드 선언·신원 확인 참조의 진실성은 자동 인증하지 못합니다. 실제 외부 연구자 기록은 아직 없습니다.

V50에서 비교 명령은 매니페스트에 적힌 해시를 현재 `data_file`의 실제 바이트와 다시 비교합니다. 원자료가 누락되거나 1바이트라도 달라지면 수치 비교 전에 `NOT_SCORED`입니다. 이는 파일 무결성만 확인하며 논문 원문과의 의미 연결·저자 원본 동일성은 사람 검토가 필요합니다.

출처:

- Horst et al. (2022), [The R Journal 논문](https://journal.r-project.org/articles/RJ-2022-020/), [저자 원자료 저장소](https://github.com/allisonhorst/palmerpenguins/blob/main/inst/extdata/penguins.csv). 기존 `data/penguins_public_benchmark.csv` 재사용.
- Cortez et al. (2009), [출판사 논문](https://www.sciencedirect.com/science/article/pii/S0167923609001377), [저자 제공 UCI 원자료](https://archive.ics.uci.edu/dataset/186/wine+quality), CC BY 4.0. 적·백포도주 CSV를 UCI ZIP에서 추출.
- Matejka & Fitzmaurice (2017), [Autodesk 저자 설명](https://www.research.autodesk.com/publications/same-stats-different-graphs/), [공개 CSV 배포본](https://github.com/rfordatascience/tidytuesday/blob/main/data/2020/2020-10-13/datasaurus.csv). 저자 사이트 원본 다운로드가 403이어서 배포본을 사용했습니다. 따라서 동일 파일 여부는 미확인이고 이 사례의 라벨 승인은 보류해야 합니다.

압축을 푼 폴더에서 `python -m tools.independent_replay`를 실행하면 앱 엔진을 import하지 않는 표준 라이브러리 재계산 결과가 출력됩니다. 원자료 해시가 바뀌면 중단합니다. `python -m tools.compare_models --system SYSTEM.json --baseline BASELINE.json`은 각 사례의 `claim_id`, `action`(`EXECUTE`/`BLOCK`), `value`, `source_hash`를 대조합니다. 두 외부 판정 기록이 없으면 `NOT_SCORED`를 반환합니다. `review_seconds`는 실제 사람이 각 결과를 검토한 시간만 입력하며, 누락 시 검토 시간 지표는 비웁니다. 컴퓨터 실행시간을 사람 검토시간이라고 부르지 않습니다.

거짓 실행률의 분모는 `BLOCK` 정답 사례 수이고, 재현률의 분모는 `EXECUTE` 정답 사례 수입니다. 사례 수가 작고 분야가 제한돼 이 묶음으로 범용 성능 우위를 주장할 수 없습니다.

## V53 출처와 탐색적 대조

- 저자 저장소 커밋 `8957207b78d6ccd1b4654a9dd9c9041b657478ab`의 `penguins_raw.csv`(17열, 344행, SHA-256 `144f623143c9360fd77322a4f86acb06dc198814dbd2669724c63e6457b907bd`)를 `author_penguins_raw.csv`로 묶었다. `PENG-ROWS`는 이제 이 원자료를 가리킨다.
- 같은 커밋의 `penguins.csv`(8열, 344행, SHA-256 `f204db2c753b0937caac3cb35258562c14f073e4bbc76be24b4c51ce22767a93`)는 `author_penguins.csv`로 묶었다. 기존 `penguins_public_benchmark.csv`는 저자 배포본의 `NA` 19개를 빈칸으로 바꾸면 행과 값이 모두 같음을 회귀시험으로 확인했다. 바이트 동일 파일이라는 뜻은 아니다.
- UCI 공식 배포 ZIP `https://archive.ics.uci.edu/static/public/186/wine+quality.zip`을 재다운로드해 SHA-256 `3ed56667f4b828242bd732d7d1dd7f2861e54432239d7fa63877014cbb0304d4`를 확인했다. 그 안의 적·백 와인 CSV는 패키지 파일과 **바이트 단위로 동일**했다.
- `codex_baseline_prompt.txt`와 `codex_baseline_raw.json`은 분리된 입력 폴더에서 `codex exec -m gpt-6-sol`, medium, 읽기 전용으로 실행한 단일 탐색 시험의 입력 지시·최종 원출력이다. 입력은 `cases.json`의 공개 Claim·방법·파일 해시와 CSV, 펭귄 논문 본문이었다. 정답 제안·제품 코드·제품 출력은 제공하지 않았다. `codex_baseline_run.json`은 원출력의 행동·수치를 바꾸지 않고 고정 매니페스트 해시만 붙인 비교기 입력이다.
- 원출력: 6건 중 `EXECUTE` 5건, `BLOCK` 1건. 현 제품의 평가용 실행 파일은 `EXECUTE` 3건, `BLOCK` 3건이다. 펭귄 2건의 차이는 제품에 평가용 사전 조건 매핑이 없고, 일반 모델에 사례별 방법·파일을 준 **비대칭 프로토콜**에서 생겼다. 이 숫자는 정확도·거짓 실행률·범용 AI 우위가 아니다. 모델은 ChatGPT가 아니라 Codex 코딩 모델이다. 같은 프로토콜의 여러 반복·블라인드 정답·사람 검토시간도 없다.
- `tools.compare_models` 결과는 계속 `NOT_SCORED`다. 사용자 요청에 따라 외부 전문가 모집은 이번 작업 범위에서 제외했으나, 미승인 정답을 승인으로 바꾸지 않는다.
- 자동 화면 시험(AppTest, 로컬 모드)에서 첫 로드 약 14.9초, 공개 사례 불러오기 약 0.27초, C-06 근거 선택 확인 약 0.56초, 예외 0건과 독립 재실행 ZIP 버튼 노출을 관찰했다. 이것은 **한 PC의 자동 실행시간**이며 처음 쓰는 연구자의 완료율·검토시간이 아니다.
