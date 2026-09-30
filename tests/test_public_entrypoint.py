"""[0 이영] 배포 연구 데스크에서 등록된 검산 페이지로 이동하고 직접 승인 경계를 확인한다."""
from pathlib import Path
from streamlit.testing.v1 import AppTest

def test_deployment_entrypoint_loads():
    # [수정: 0 이영] 2026-10-01 07:46 KST — 최종 팀 화면의 실제 제목과 네 단계 이동을 대조한다. 직접 계산·PENDING·승인 비활성 기대는 유지하며 제품 코드는 변경하지 않는다.
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "0_이영_웹사이트.py"), default_timeout=60).run()
    assert not app.exception
    assert any(x.value == "확인할 수치를 고르고, 근거부터 검토하세요" for x in app.title)
    assert [tab.label for tab in app.tabs] == ["논문 둘러보기", "공공·위성 데이터", "연구 과제", "대학 연구 소식", "연구 관심 순위", "다른 AI와 연결"]
    app.switch_page("finals/app.py").run()
    assert not app.exception
    assert app.session_state["fin_step"] == 1
    app.button(key="fin_source_next").click().run()
    assert not app.exception and app.session_state["fin_step"] == 2
    app.button(key="fin_manual_load").click().run()
    assert not app.exception and app.session_state["fin_step"] == 2
    app.button(key="fin_conditions_next").click().run()
    assert not app.exception and app.session_state["fin_step"] == 3
    app.button(key="fin_compute").click().run()
    assert not app.exception
    assert app.session_state["fin_report"]["can_approve"] is True
    assert app.session_state["fin_report"]["human_approval"]["status"] == "PENDING"
    app.button(key="fin_result_next").click().run()
    assert not app.exception and app.session_state["fin_step"] == 4
    assert app.session_state["fin_report"]["human_approval"]["status"] == "PENDING"
    assert app.button(key="fin_approve").disabled is True
