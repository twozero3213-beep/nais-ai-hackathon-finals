"""[0 이영] 합성 원문 위치 공격: 실제 Git 함수 AST를 변경 없이 실행한다.

작성 이유: 등록 원문 문자열 존재와 실제 위치/실험자료 의미 결속을 구분한다.
검증: --prepare로 사전 조건·입력 해시 봉인 후 --run으로 load_case만 호출한다.
제품·등록 원 사례·키·사설 DB를 읽지 않으며 네트워크·유료 호출은 없다.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import types
import unicodedata

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "synthetic_fixture"
REVISION = "d8d952b43eff8ab416421da8f0f431a64e8b9241"
KST = timezone(timedelta(hours=9))
FUNCTIONS = {"_sha", "_canonical", "text_key", "_safe_path", "_registered_claims", "_selected_count", "_proposal", "load_case"}


def now():
    return datetime.now(KST).isoformat(timespec="microseconds")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def prepare():
    # 합성 문단/표의 실제 위치는 아래 source_locations.json에 먼저 고정한다.
    quote_a = "For Experiment A, the mean age of two individual participants was 15 years."
    quote_b = "For Experiment B, the mean age of two individual participants was 15 years."
    source = ("SYNTHETIC DOCUMENT; NOT A REAL PAPER\n"
              "[Methods/p-A]\n" + quote_a + "\n"
              "[Methods/p-B]\n" + quote_b + "\n"
              "[Table/T-A/caption]\n" + quote_a + "\n"
              "[Table/T-A/header]\nparticipant_id | experiment | age_years\n"
              "[Table/T-A/rows]\nA1 | A | 10\nA2 | A | 20\n"
              "[Table/T-B/caption]\n" + quote_b + "\n"
              "[Table/T-B/header]\nparticipant_id | experiment | age_years\n"
              "[Table/T-B/rows]\nB1 | B | 5\nB2 | B | 25\n").encode("utf-8")
    data_a = b"participant_id,experiment,age_years\nA1,A,10\nA2,A,20\n"
    data_b = b"participant_id,experiment,age_years\nB1,B,5\nB2,B,25\n"
    data_visits = b"participant_id,experiment,visit,age_years\nA1,A,1,10\nA1,A,2,20\n"
    files = {"source/document.txt": source, "data/experiment_a.csv": data_a,
             "data/experiment_b.csv": data_b, "data/repeated_visits.csv": data_visits}
    for relative, raw in files.items():
        path = FIXTURE / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    locations = {"Methods/p-A": quote_a, "Methods/p-B": quote_b,
                 "Table/T-A/caption": quote_a, "Table/T-B/caption": quote_b}
    dump(FIXTURE / "source_locations.json", locations)
    base = {"claim_id": "SG-NORMAL-PARAGRAPH", "claim_text": quote_a,
            "method": "mean", "reported_value": 15, "column": "age_years", "filters": {},
            "delimiter": ",", "missing_policy": "error", "tolerance": 0,
            "data_file": "data/experiment_a.csv", "data_sha256": sha(data_a),
            "source_file": "source/document.txt", "source_sha256": sha(source),
            "source_quote": quote_a, "source_location": "Methods/p-A", "source_kind": "article_extract",
            "evidence_status": "SYNTHETIC_REGISTRATION_FOR_AUDIT", "paper_url": "https://example.invalid/synthetic-a"}
    definitions = [
        ("SG-NORMAL-PARAGRAPH", "normal", True, {}, "Exact quote at exact paragraph"),
        ("SG-NORMAL-TABLE", "normal", True, {"source_location": "Table/T-A/caption"}, "Exact quote at target table caption"),
        ("SG-WRONG-LOCATION", "attack", False, {"source_location": "Methods/p-B"}, "A quote exists globally but is absent at claimed B paragraph"),
        ("SG-OTHER-TABLE-QUOTE", "attack", False, {"source_quote": quote_b, "source_location": "Table/T-A/caption"}, "B quote exists at B table while claim and location target A"),
        ("SG-WRONG-SOURCE-HASH", "negative_control", False, {"source_sha256": "0" * 64}, "Incorrect source hash must block"),
        ("SG-QUOTE-ABSENT", "negative_control", False, {"source_quote": "ABSENT QUOTE: the true value is 999 years."}, "Quote absent everywhere must block"),
        ("SG-WRONG-DATA-HASH", "negative_control", False, {"data_sha256": "0" * 64}, "Incorrect data hash must block"),
        ("SG-WRONG-EXPERIMENT", "provenance_boundary", False, {"data_file": "data/experiment_b.csv", "data_sha256": sha(data_b)}, "Exact registered hash of B CSV is not evidence that it belongs to A experiment"),
        ("SG-ROWS-NOT-PEOPLE", "unit_boundary", False, {"method": "count_rows", "reported_value": 2, "column": "", "data_file": "data/repeated_visits.csv", "data_sha256": sha(data_visits)}, "Two visit rows belong to one person; proposal unit must not imply count_rows proves individuals"),
    ]
    cases, protocol_cases = [], []
    for case_id, kind, desired, overrides, meaning in definitions:
        item = deepcopy(base)
        item.update(overrides)
        item["claim_id"] = case_id
        cases.append(item)
        protocol_cases.append({"case_id": case_id, "kind": kind, "desired_gate_if_semantic_location_is_claimed": desired,
                               "meaning": meaning, "manifest": deepcopy(item),
                               "quote_at_declared_location": item["source_quote"] in locations.get(item["source_location"], ""),
                               "data_semantic_origin": "B" if case_id == "SG-WRONG-EXPERIMENT" else "A",
                               "unique_person_count": 1 if case_id == "SG-ROWS-NOT-PEOPLE" else 2})
    registry = FIXTURE / "data/evaluation/public_reproduction_cases.json"
    dump(registry, {"cases": cases, "_change_note": "All records are newly authored synthetic registration metadata; no existing product registry read."})
    input_files = list(files) + ["source_locations.json", "data/evaluation/public_reproduction_cases.json"]
    protocol = {"version": 0, "created_at_kst": now(), "git_revision": REVISION,
                "function": "finals/finals_cases.py::load_case", "method": "unchanged AST function nodes and exact normalization module",
                "fixture_registration_author": "0 이영; synthetic manifest authored by auditor before execution",
                "code_snapshot": json.loads((ROOT / "0_이영_code_snapshot.json").read_text(encoding="utf-8")),
                "inputs": [{"relative_path": p, "sha256": sha((FIXTURE / p).read_bytes())} for p in input_files],
                "cases": protocol_cases, "paid_calls": 0, "network_calls": 0,
                "scope": "load_case source_gate and generated proposal only; no pipeline final approval, UI mutation, model, provider or private DB",
                "interpretation": "Desired gates test a stronger semantic/location claim, not an assumption that existing source_gate promised that scope."}
    path = ROOT / "0_이영_pre_execution_protocol.json"
    dump(path, protocol)
    digest = sha(path.read_bytes())
    (ROOT / "0_이영_pre_execution_protocol.sha256").write_text(digest + "\n", encoding="ascii")
    print(json.dumps({"phase": "PREPARED_NOT_EXECUTED", "case_count": len(cases), "protocol_sha256": digest, "created_at_kst": protocol["created_at_kst"]}, ensure_ascii=False))


def actual_namespace():
    snapshot = ROOT / "code_snapshot/finals/finals_cases.py"
    raw = snapshot.read_bytes()
    tree = ast.parse(raw.decode("utf-8"), filename=str(snapshot))
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module == "finals_provider":
                continue  # Provider constants are used only by unselected replay listing, never load_case.
            nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {"_DEFINITIONS", "_PUNCTUATION", "REGISTRY"} for t in node.targets):
            nodes.append(node)
    assert {node.name for node in nodes if isinstance(node, ast.FunctionDef)} == FUNCTIONS
    # Only environment roots point to our new fixture. No actual function or result is patched.
    namespace = {"__name__": "source_gate_audit_actual_functions", "__file__": str(snapshot),
                 "REPO_ROOT": FIXTURE, "AGENT_ROOT": FIXTURE / "finals"}
    core = types.ModuleType("core")
    core.__path__ = [str(ROOT / "code_snapshot/core")]
    sys.modules["core"] = core
    spec = importlib.util.spec_from_file_location("core.normalization", ROOT / "code_snapshot/core/normalization.py")
    normalization = importlib.util.module_from_spec(spec)
    sys.modules["core.normalization"] = normalization
    spec.loader.exec_module(normalization)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(snapshot), "exec"), namespace)
    return namespace, sha(raw), {node.name: {"start_line": node.lineno, "end_line": node.end_lineno,
                               "ast_sha256": sha(ast.dump(node, include_attributes=True).encode("utf-8"))}
                              for node in nodes if isinstance(node, ast.FunctionDef)}


def run():
    started = now()
    path = ROOT / "0_이영_pre_execution_protocol.json"
    expected_sha = (ROOT / "0_이영_pre_execution_protocol.sha256").read_text(encoding="ascii").strip()
    assert sha(path.read_bytes()) == expected_sha, "PROTOCOL_CHANGED"
    protocol = json.loads(path.read_text(encoding="utf-8"))
    for item in protocol["inputs"]:
        assert sha((FIXTURE / item["relative_path"]).read_bytes()) == item["sha256"], "FIXTURE_CHANGED"
    for item in protocol["code_snapshot"]["files"]:
        assert sha(Path(item["saved_path"]).read_bytes()) == item["sha256"], "CODE_SNAPSHOT_CHANGED"
    namespace, module_sha, functions = actual_namespace()
    rows = []
    for entry in protocol["cases"]:
        case = namespace["load_case"](entry["case_id"])
        source = case["source"]
        desired = entry["desired_gate_if_semantic_location_is_claimed"]
        rows.append({"case_id": entry["case_id"], "kind": entry["kind"], "executed_at_kst": now(),
                     "actual_source_gate": case["source_gate"], "desired_stronger_gate": desired,
                     "meets_stronger_location_semantic_expectation": case["source_gate"] == desired,
                     "actual_source_sha256": case["source_sha256"], "registered_source_sha256": source["source_sha256"],
                     "actual_data_sha256": case["input_sha256"], "registered_data_sha256": source["data_sha256"],
                     "source_location": case["source_location"], "source_quote": case["source_quote"],
                     "quote_at_declared_location_by_presealed_fixture": entry["quote_at_declared_location"],
                     "manual_proposal": case["manual_proposal"], "original_rows": case["original_rows"],
                     "actual_unique_people": int(case["dataframe"]["participant_id"].nunique()),
                     "actual_experiments": sorted(case["dataframe"]["experiment"].unique().tolist()),
                     "model_called": False, "human_approval_called": False})
    result = {"version": 0, "git_revision": REVISION, "started_at_kst": started, "finished_at_kst": now(),
              "protocol_sha256": expected_sha, "actual_module_sha256": module_sha, "actual_function_nodes": functions,
              "execution_method": "Unmodified AST nodes compiled with source line numbers; synthetic REPO_ROOT only; exact core.normalization import",
              "network_calls": 0, "paid_calls": 0, "cases": rows,
              "scope": protocol["scope"], "limitations": ["Synthetic new registry authored by auditor, not existing UI registration mutation.",
              "source_gate=True is not final scientific validation or human approval.",
              "No final approval function, model, existing registered case, private database or secret file was invoked/read."]}
    dump(ROOT / "0_이영_source_gate_results.json", result)
    print(json.dumps({"git_revision": REVISION, "started_at_kst": started, "finished_at_kst": result["finished_at_kst"],
                      "cases": [{"case_id": r["case_id"], "actual_source_gate": r["actual_source_gate"],
                                 "desired_stronger_gate": r["desired_stronger_gate"]} for r in rows],
                      "network_calls": 0, "paid_calls": 0}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if sys.argv[1:] == ["--prepare"]:
        prepare()
    elif sys.argv[1:] == ["--run"]:
        run()
    else:
        raise SystemExit("Use --prepare first, then --run.")
