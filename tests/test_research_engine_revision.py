"""The downloaded-data gate and actual review code belong to engine identity."""
# [작성: 0 이영] 2026-10-01 05:06 KST — 계산·승인 직전 fresh 지문 범위는 유지하고 idle 화면 최적화와 구분한다.
import pytest
from core import source_revision as revision


@pytest.fixture
def tree(tmp_path, monkeypatch):
    for name, body in {'app.py': 'pass\n', 'requirements.txt': '', 'VERSION': '0\n',
                       'core/gate.py': 'pass\n', 'tools/run.py': 'pass\n',
                       'evidence_gate/compute.py': 'def compute(): return 20\n',
                       'finals/finals_cases.py': 'def case(): return 1\n',
                       'finals/tests/test_example.py': 'pass\n'}.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding='utf-8')
    monkeypatch.setattr(revision, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(revision, '_git_sha', lambda: 'same-commit-label')
    return tmp_path


@pytest.mark.parametrize('path', ['evidence_gate/compute.py', 'finals/finals_cases.py'])
def test_uncommitted_actual_engine_change_has_different_hash(tree, path):
    before = revision.source_revision()
    target = tree / path
    target.write_text(target.read_text(encoding='utf-8') + '\n# changed implementation\n', encoding='utf-8')
    assert revision.source_revision() != before


def test_final_ui_test_changes_are_not_engine_changes(tree):
    before = revision.source_revision()
    (tree / 'finals/tests/test_example.py').write_text('assert True\n', encoding='utf-8')
    assert revision.source_revision() == before
