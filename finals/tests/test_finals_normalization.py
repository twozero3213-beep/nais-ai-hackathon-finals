"""정규성·적시성: 원문 인용 비교가 유니코드·공백 표기 차이에 흔들리지 않고, 팀 지식은 파일이 바뀌면 다음 실행에 반영된다.

# [작성: 0 이영 · Claude] 2026-10-01 00:33 KST — 실제 모델은 인용문을 되풀이할 때 공백·따옴표·유니코드 정규형을 조금씩 바꾼다(특히 한글 NFC/NFD, 줄바꿈으로
# 끊긴 PDF 원문). 정확 일치로 비교하면 내용이 같아도 REGISTERED_FIELD_MISMATCH로 막혀 첫 실호출이 자주 실패한다. 내용 변경은 계속 막아야 한다.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unicodedata

FINALS = Path(__file__).resolve().parents[1]
ROOT = FINALS.parent
for path in (ROOT, FINALS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import finals_cases
import finals_pipeline as pipeline
from core import team_knowledge


def test_text_key_ignores_presentation_differences_only():
    key = finals_cases.text_key
    assert key("The  table has\nfour rows.") == key("The table has four rows.")
    assert key("“group A” – mean") == key('"group A" - mean')
    assert key(unicodedata.normalize("NFD", "표본 크기는 344개체")) == key(unicodedata.normalize("NFC", "표본 크기는 344개체"))
    assert key("Ａ ｇｒｏｕｐ") == key("A group")                  # 전각 → 반각(NFKC)
    assert key("mean is 15") != key("mean is 16")                 # 내용 변경은 그대로 구분한다
    assert key(15) == key(15) and key(15) != key(16)


def test_candidate_with_reformatted_quote_is_accepted_but_changed_content_is_blocked():
    case = finals_cases.load_case("NORMAL-PENG-ROWS")
    proposal = json.loads(json.dumps(case["manual_proposal"]))
    proposal["source_quote"] = "  " + case["source_quote"].replace(" ", "  ") + " "
    proposal["claim_text"] = unicodedata.normalize("NFD", case["source"]["claim_text"])
    assert pipeline._validation(case, proposal)["valid"] is True

    altered = json.loads(json.dumps(case["manual_proposal"]))
    altered["source_quote"] = case["source_quote"].replace("344", "345")
    result = pipeline._validation(case, altered)
    assert result["valid"] is False and "REGISTERED_FIELD_MISMATCH_SOURCE_QUOTE" in result["errors"]


def test_structural_conditions_stay_exact():
    case = finals_cases.load_case("NORMAL-BAT-MEAN")
    proposal = json.loads(json.dumps(case["manual_proposal"]))
    proposal["column"] = proposal["column"] + " "
    result = pipeline._validation(case, proposal)
    assert result["valid"] is False and "CONDITION_MISMATCH_COLUMN" in result["errors"]


def test_source_gate_finds_a_quote_that_the_source_wraps_across_lines(monkeypatch, tmp_path):
    csv = tmp_path / "d.csv"
    csv.write_bytes(b"g,v\n" + b"a,1\n" * 3)
    source = tmp_path / "s.txt"
    source.write_bytes("Group A has\nthree   rows.".encode("utf-8"))
    sha = finals_cases._sha
    item = {"claim_id": "WRAP-1", "claim_text": "a 그룹은 3행", "source_quote": "Group A has three rows.", "source_location": "p1",
            "paper_url": "https://example.org", "method": "count_rows", "column": "g", "filters": {"g": "a"}, "reported_value": 3,
            "tolerance": 0, "missing_policy": "error", "delimiter": ",", "data_file": "d.csv", "source_file": "s.txt",
            "source_kind": "article_extract", "evidence_status": "READY", "data_sha256": sha(csv.read_bytes()),
            "source_sha256": sha(source.read_bytes())}
    monkeypatch.setattr(finals_cases, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(finals_cases, "_registered_claims", lambda: {"WRAP-1": item})
    assert finals_cases.load_case("WRAP-1")["source_gate"] is True
    item["source_quote"] = "Group A has four rows."
    assert finals_cases.load_case("WRAP-1")["source_gate"] is False


def test_team_knowledge_follows_file_changes_without_restart(tmp_path, monkeypatch):
    path = tmp_path / "knowledge.json"
    base = {"paper_error_cases": [], "differentiation": {"do_not_claim": ["첫 번째 금지 주장"]}}
    path.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(team_knowledge, "KNOWLEDGE_PATH", path)
    first = team_knowledge.load_knowledge()
    assert team_knowledge.forbidden_claims() == ["첫 번째 금지 주장"]
    base["differentiation"]["do_not_claim"] = ["첫 번째 금지 주장", "두 번째 금지 주장"]
    path.write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")
    second = team_knowledge.load_knowledge()
    assert second[1] != first[1]
    assert team_knowledge.forbidden_claims() == ["첫 번째 금지 주장", "두 번째 금지 주장"]
    path.write_text("{ 손상", encoding="utf-8")
    try:
        team_knowledge.load_knowledge()
    except ValueError:
        pass
    else:
        raise AssertionError("손상된 지식 파일은 조용히 지난 값을 쓰면 안 된다")


def test_doi_forms_are_normalized_before_matching_known_cases():
    for form in ("10.1111/evo.14483", "DOI:10.1111/EVO.14483", "https://doi.org/10.1111/evo.14483", "http://dx.doi.org/10.1111/evo.14483"):
        assert [case["id"] for case in team_knowledge.known_error_cases([form])] == ["A2"], form
    assert team_knowledge.known_error_cases(["10.1111/evo.99999"]) == []
