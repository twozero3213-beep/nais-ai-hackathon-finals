"""[0 이영] 배포 연구 데스크에서 등록된 검산 페이지로 이동하고 직접 승인 경계를 확인한다."""
from pathlib import Path
from streamlit.testing.v1 import AppTest

def test_deployment_entrypoint_loads():
    # [수정: 0 이영] 2026-10-01 00:17 KST — 배포 기본 화면이 연구 데스크로 바뀌어 실제 navigation을 통해 검산에 진입한다.
    # 이전 집중 화면 app.py의 제목 기대는 hero 의미/6탭으로 갱신하며 수동 검산·PENDING 승인 기대는 유지한다.
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "0_이영_웹사이트.py"), default_timeout=60).run()
    assert not app.exception
    assert any("연구를 발견하고," in x.value and "그 근거까지 확인하세요." in x.value for x in app.markdown)
    assert [tab.label for tab in app.tabs] == ["논문 둘러보기", "공공·위성 데이터", "연구 과제", "대학 연구 소식", "연구 관심 순위", "다른 AI와 연결"]
    app.switch_page("finals/app.py").run()
    assert not app.exception
    app.button(key="fin_manual_load").click().run()
    app.button(key="fin_compute").click().run()
    assert not app.exception
    assert app.session_state["fin_report"]["can_approve"] is True
    assert app.session_state["fin_report"]["human_approval"]["status"] == "PENDING"
    assert app.button(key="fin_approve").disabled is True
