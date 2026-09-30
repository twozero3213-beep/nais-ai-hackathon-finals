"""본선 차단 상태·민감 승인사유·보호 정책 지문의 실제 경계를 검증한다."""
# [작성: 0 이영 · Codex] 2026-10-01 — 잘못된 성공 표시와 본선 라벨 인증값 검사 누락의 회귀. 실 API/실제 사람 승인 없음.
import ast
from pathlib import Path

import pytest

from finals.tests.test_finals_ui import app_factory, compute
import finals_provenance as provenance


class Column:
    def __init__(self):
        self.writes = []
        self.captions = []

    def caption(self, text):
        self.captions.append(text)

    def write(self, text):
        self.writes.append(text)


class MemoryUI:
    def markdown(self, text):
        pass

    def columns(self, count):
        self.items = [Column() for _ in range(count)]
        return self.items


@pytest.mark.parametrize("status,caption", [("PASS", "통과"), ("PENDING", "대기"), ("APPROVED", "사람 확인 완료"), ("REVIEW", "검토 필요"), ("BLOCKED", "보류"), ("FAIL", "실패"), ("NOT_RUN", "미실행"), ("INVALIDATED", "무효"), ("ERROR", "오류"), ("UNKNOWN", "UNKNOWN")])
def test_only_pass_displays_success_icon(status, caption):
    # 실행 검토한 표시 함수만 메모리에서 호출하며 앱 시작/외부 코드/설정 읽기는 없다.
    path = Path(__file__).resolve().parents[1] / "app.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    nodes = [node for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name in {"ai_used", "render_roles"}
             or isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "STEP_ROLES" for t in node.targets)]
    ui = MemoryUI()
    namespace = {"st": ui}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    namespace["render_roles"]({"steps": [{"step": "validate", "status": status}]})
    assert ui.items[0].writes[0].startswith("✓") is (status == "PASS")
    assert ui.items[0].captions[-1] == caption
    if status == "APPROVED":
        assert ui.items[0].writes[0].startswith("👤")


def test_labeled_credential_reason_disables_approval_without_reflecting_value(app_factory):
    app = app_factory()
    compute(app)
    # [수정: 0 이영] 2026-10-01 07:51 KST — 새 단계 화면의 사람 검토로 이동한 뒤 인증값 차단과 정상 사유 허용을 검증한다.
    app.button(key="fin_result_next").click().run()
    app.checkbox(key="fin_human_confirm").set_value(True).run()
    synthetic = "password=" + "SYNTHETIC_NOT_A_REAL_CREDENTIAL"
    app.text_area(key="fin_reason").set_value(synthetic).run()
    assert not app.exception
    assert app.button(key="fin_approve").disabled
    assert app.session_state["fin_report"]["human_approval"]["approved"] is False
    warning = " ".join(item.value for item in app.warning)
    assert "인증 값" in warning
    assert synthetic not in warning
    assert "CREDENTIAL_ASSIGNMENT" not in warning
    app.text_area(key="fin_reason").set_value("공개 원문과 여섯 조건 및 검산을 직접 확인했습니다.").run()
    assert not app.button(key="fin_approve").disabled
    # 버튼을 누르지 않고 종료: 실제 승인 완료 증거로 세지 않는다.


def test_sensitive_policy_change_changes_execution_fingerprint(monkeypatch, tmp_path):
    assert "core/input_security.py" in provenance.CODE_FILES
    for name in provenance.CODE_FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("original", encoding="utf-8")
    monkeypatch.setattr(provenance, "ROOT", tmp_path)
    before = provenance.execution_snapshot()
    (tmp_path / "core/input_security.py").write_text("changed policy", encoding="utf-8")
    after = provenance.execution_snapshot()
    assert before["execution_fingerprint"] != after["execution_fingerprint"]
    assert before["code_files_sha256"]["core/input_security.py"] != after["code_files_sha256"]["core/input_security.py"]
