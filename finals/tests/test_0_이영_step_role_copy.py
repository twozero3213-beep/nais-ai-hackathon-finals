"""AI 조건 제안·실제 비평 수행자·사람 승인 표시의 의미를 분리한다."""
# [작성: 0 이영 · Codex] 2026-10-01 — 저장된 AI 제안과 현재 규칙 비평을 모두 AI가 했다는 잘못된 표시를 막는다. 실제 모델/서비스 호출 없음.
import ast
from pathlib import Path


class Column:
    def __init__(self):
        self.captions = []

    def caption(self, text):
        self.captions.append(text)

    def write(self, text):
        pass


class UI:
    def markdown(self, text):
        pass

    def columns(self, count):
        self.items = [Column() for _ in range(count)]
        return self.items


def actors(*, model_used, critique_source):
    # 앱 시작·외부 연결을 실행하지 않고 체크인된 표시 함수 자체를 검증한다.
    path = Path(__file__).resolve().parents[1] / "app.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    nodes = [node for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name in {"ai_used", "render_roles"}
             or isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "STEP_ROLES" for t in node.targets)]
    ui = UI()
    namespace = {"st": ui}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    report = {"actual_model_output": model_used,
              "critique": {"source": critique_source},
              "steps": [{"step": "proposal", "status": "PASS"},
                        {"step": "critique", "status": "PASS"},
                        {"step": "human_approval", "status": "PENDING"}]}
    namespace["render_roles"](report)
    return [column.captions[0] for column in ui.items]


def test_replayed_ai_proposal_does_not_turn_rule_critique_into_ai():
    assert actors(model_used=True, critique_source="deterministic") == ["AI", "규칙", "사람"]


def test_manual_proposal_and_rule_critique_remain_distinct():
    assert actors(model_used=False, critique_source="deterministic") == ["사람(수동)", "규칙", "사람"]


def test_model_critique_keeps_ai_label_when_model_was_used():
    assert actors(model_used=True, critique_source="model_candidate") == ["AI", "AI", "사람"]
