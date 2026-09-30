# 지현 제출 메타데이터 검색 편입

2026-09-29. 제출 `조지현_20260929_v2`의 `paper_manifest.csv`와 `sources.csv`에서 제목·DOI·주제·공개 링크·라이선스 위치만 선별했다. 한국어 제목은 제출자의 미검토 초안이며 `title_ko_unverified`에 보존한다. 실제 전문가 승인·정답·재현·모델 학습 자료로 승격하지 않는다.

원본 `data/combined_papers_index.json` **전체 900편**과 DOI 소문자/공백/DOI URL 접두사 정규화로 대조했다. 제출 20편, 고유 20편, 신규 20편, 중복 0편. 환경·경제·교육·보건·공학 각 4편. 대조한 원본 목록과 제출 CSV의 SHA256은 `metadata.json`의 provenance에 기록한다. 제품 전체 본문·별도 인터넷 자료와 대조한 결과라는 주장은 하지 않는다.

기존 `core.research_corpus.search_corpus(..., mode='bibliography')`와 논문 근거 도서관의 서지 검색에서 두 검색 구분(development/validation)에 따라 제목 후보가 나온다. 기존 900편 저장 코퍼스·본문 수·단락·검증 해시는 유지한다. 새 메타데이터는 code-bound SHA256, 필드·타입·DOI·URL·상대경로·상태 검사 후 추가된다. DOI가 기존 목록과 겹치면 기존 레코드를 유지하고 새 후보를 제외한다. 새 목록은 본문 검색 모드에 들어가지 않는다.

제출 XML 15편은 재배포 검증 없이 복사하지 않았다(`REDISTRIBUTION_NOT_VERIFIED`). 나머지 5편의 본문 미확보는 `FULLTEXT_NOT_ACQUIRED`로 유지한다. 공개 라이선스 링크와 본문 위치는 제출자의 관찰 포인터이며 권리 인증이 아니다. 제출 원문·가공 단락·API JSON·25개 미계산 주장·가드 코드·성능 점수는 반입하지 않았다. 네트워크·유료 API 호출은 없다.

`tests/test_case105_team_corpus.py`는 신규 제목 검색, 본문 후보 없음, 기존 레코드 보존, 중복 제외, XML 미읽기, 변조·삭제 차단과 URL/경로/상태 경계를 검사한다. 실제 실행 결과는 총괄의 시험 영수증을 따른다.
