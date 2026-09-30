# 원논문·공지 후보 컬렉션
원문 바이트를 변경하지 않은331개 문서와 메타데이터를 보관한다. 원논문170, 공지161, 양쪽 본문과 직접 연결159쌍, 후보178개. 기존900편 색인과 독립이다.
원문 attribution(애트리뷰션, 저자·출처 표시), 저작권 및 면허는 각 XML front/article-meta에 있다. CC BY/CC0 링크 확인 자료만 수용했다. 해시는 inventory와 intake_audit 참조.
Retraction Watch 파생 후보3342행의 출처·면허: https://www.crossref.org/documentation/retrieve-metadata/ (CC0, 2026-09-28 확인). 이는 본문 면허를 대신하지 않는다. n3_filter_report는 팀원 제공 주장으로 원본 필터링 과정 전체를 재실행하지 않았다.
입력 manifest의 실패/재시도도 감사용으로 보존하며, 해당 path가 전부 배포물 안에 있다는 뜻은 아니다. 수용 파일 경로의 기준은 inventory.json이다.
AI 사전분류는 정답·사람 판정·실행 결과가 아니다. 새 원자료·저자 코드0. 자료 확보는 모델 가중치 학습이 아니다.
전수 검증: python -m pytest -q tests/test_v86.py
상세 피드백·다음 수집 명령: docs/TEAM_INTAKE_REVIEW.md
