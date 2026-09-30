"""[0 이영] Synthetic registration -> actual manual pipeline, without approval.

Reason: trace source-location/data-unit registration errors beyond the loader.
Use --prepare before --run. The exact checkout remains read-only (-B imports).
No business function, calculator, verifier, model, or approval is replaced.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "synthetic_fixture"
REVISION = "a6729178963392249b14c9dfbd93bf28704262a4"
KST = timezone(timedelta(hours=9))
CODE_FILES = (
    "finals/finals_pipeline.py", "finals/finals_cases.py", "finals/finals_provenance.py",
    "finals/finals_provider.py", "finals/finals_privacy.py", "core/models.py",
    "core/normalization.py", "core/statistics.py", "core/typed_contracts.py",
    "core/verifier.py", "core/semantic.py", "core/provenance.py",
    "core/decision_provenance.py", "core/input_security.py",
)


def now():
    return datetime.now(KST).isoformat(timespec="microseconds")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def git(snapshot, *args):
    return subprocess.run(["git", "-C", str(snapshot), *args], check=True, capture_output=True).stdout


def code_receipt(snapshot):
    assert git(snapshot, "rev-parse", "HEAD").decode().strip() == REVISION, "WRONG_SNAPSHOT_REVISION"
    records = []
    for name in CODE_FILES:
        raw = (snapshot / name).read_bytes()
        object_raw = git(snapshot, "show", REVISION + ":" + name)
        # Windows checkout may use CRLF. Accept only that known Git checkout transform,
        # preserving both exact raw hashes; never normalize the imported source file.
        exact_bytes = raw == object_raw
        assert exact_bytes or raw.replace(b"\r\n", b"\n") == object_raw, "SNAPSHOT_CODE_DIFFERS_FROM_FIXED_COMMIT"
        records.append({"git_path": name, "sha256": sha(raw), "git_object_sha256": sha(object_raw),
                        "bytes": len(raw), "exact_git_object_bytes": exact_bytes,
                        "checkout_difference": "NONE" if exact_bytes else "CRLF_CHECKOUT_ONLY"})
    return {"git_revision": REVISION, "code_files": records,
            "tracked_status_before": git(snapshot, "status", "--porcelain").decode().splitlines()}


def environment():
    dependencies = {}
    for package in ("pandas", "numpy", "scipy", "jsonschema", "streamlit", "numexpr"):
        try:
            dependencies[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            dependencies[package] = "UNAVAILABLE"
    return {"python_version": platform.python_version(), "platform": platform.system(),
            "dependencies": dependencies, "bytecode_writes_disabled": sys.dont_write_bytecode}


def prepare(snapshot):
    quote_a = "In Experiment A, two individual participants had a mean age of 15 years."
    quote_b = "In Experiment B, two individual participants had a mean age of 15 years."
    quote_n = "Experiment A contained 2 individual participants."
    source = ("SYNTHETIC PAPER; NOT AN EXTERNAL PUBLICATION\n"
              "[Methods/p-A]\n" + quote_a + "\n"
              "[Methods/p-B]\n" + quote_b + "\n"
              "[Methods/p-A-count]\n" + quote_n + "\n"
              "[Table/T-A/caption]\n" + quote_a + "\n"
              "[Table/T-A/header]\nparticipant_id | experiment | age_years\n"
              "[Table/T-A/rows]\nA1 | A | 10\nA2 | A | 20\n"
              "[Table/T-B/caption]\n" + quote_b + "\n"
              "[Table/T-B/header]\nparticipant_id | experiment | age_years\n"
              "[Table/T-B/rows]\nB1 | B | 5\nB2 | B | 25\n").encode("utf-8")
    csv_a = b"participant_id,experiment,age_years\nA1,A,10\nA2,A,20\n"
    csv_b = b"participant_id,experiment,age_years\nB1,B,5\nB2,B,25\n"
    csv_visits = b"participant_id,experiment,visit,age_years\nA1,A,1,10\nA1,A,2,20\n"
    files = {"source/document.txt": source, "data/experiment_a.csv": csv_a,
             "data/experiment_b.csv": csv_b, "data/repeated_visits.csv": csv_visits}
    for relative, raw in files.items():
        path = FIXTURE / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    locations = {"Methods/p-A": quote_a, "Methods/p-B": quote_b, "Methods/p-A-count": quote_n,
                 "Table/T-A/caption": quote_a, "Table/T-B/caption": quote_b}
    dump(FIXTURE / "source_locations.json", locations)
    base = {"claim_text": quote_a, "method": "mean", "reported_value": 15,
            "column": "age_years", "filters": {}, "delimiter": ",", "missing_policy": "error",
            "tolerance": 0, "data_file": "data/experiment_a.csv", "data_sha256": sha(csv_a),
            "source_file": "source/document.txt", "source_sha256": sha(source),
            "source_quote": quote_a, "source_location": "Methods/p-A", "source_kind": "article_extract",
            "evidence_status": "SYNTHETIC_AUDITOR_DECLARED_REGISTRATION",
            "paper_url": "https://example.invalid/synthetic-a",
            "scope_note": "Synthetic registration written by auditor; no external acquisition or publisher authority."}
    specifications = [
        ("PL-NORMAL-PARAGRAPH", "normal", {}, {}, "NORMAL_SUPPORTED_PREVIEW", True),
        ("PL-NORMAL-TABLE", "normal", {"source_location": "Table/T-A/caption"}, {}, "NORMAL_SUPPORTED_PREVIEW", True),
        ("PL-WRONG-LOCATION", "registration_boundary", {"source_location": "Methods/p-B"}, {}, "LOCATION_SHOULD_NOT_CONFIRM_MEANING", False),
        ("PL-OTHER-TABLE-QUOTE", "registration_boundary", {"source_quote": quote_b, "source_location": "Table/T-A/caption"}, {}, "OTHER_TABLE_SHOULD_NOT_CONFIRM_TARGET_ANALYSIS", False),
        ("PL-WRONG-EXPERIMENT", "registration_boundary", {"data_file": "data/experiment_b.csv", "data_sha256": sha(csv_b)}, {}, "EXACT_B_HASH_DOES_NOT_BIND_A_EXPERIMENT", False),
        ("PL-ROWS-NOT-PEOPLE", "registration_boundary", {"claim_text": quote_n, "source_quote": quote_n,
          "source_location": "Methods/p-A-count", "method": "count_rows", "reported_value": 2,
          "column": "", "data_file": "data/repeated_visits.csv", "data_sha256": sha(csv_visits)}, {},
          "TWO_VISIT_ROWS_DO_NOT_PROVE_TWO_PEOPLE", False),
        ("PL-REGISTERED-LOCATION-CANDIDATE-CONTROL", "candidate_control", {}, {"source_location": "Methods/p-B"},
          "CANDIDATE_LOCATION_DIFFERS_FROM_ACCURATE_REGISTRY", False),
    ]
    registry, tests = [], []
    for case_id, kind, changes, candidate_changes, expectation, desired in specifications:
        item = deepcopy(base)
        item.update(changes)
        item["claim_id"] = case_id
        registry.append(item)
        tests.append({"case_id": case_id, "kind": kind, "registered_item": item,
                      "candidate_overrides": candidate_changes, "semantic_expectation": expectation,
                      "desired_can_approve_if_location_and_data_meaning_are_claimed": desired,
                      "registered_quote_at_registered_location": item["source_quote"] in locations.get(item["source_location"], ""),
                      "data_actual_experiment": "B" if case_id == "PL-WRONG-EXPERIMENT" else "A",
                      "data_actual_unique_people": 1 if case_id == "PL-ROWS-NOT-PEOPLE" else 2})
    dump(FIXTURE / "data/evaluation/public_reproduction_cases.json", {"cases": registry,
         "_change_note": "New synthetic trusted-registration fixture intentionally includes bad metadata; no product registry read or modified."})
    (FIXTURE / "finals").mkdir(parents=True, exist_ok=True)
    records = code_receipt(snapshot)
    input_paths = list(files) + ["source_locations.json", "data/evaluation/public_reproduction_cases.json"]
    protocol = {"version": 0, "created_at_kst": now(), "code": records, "environment": environment(),
                "runner_sha256": sha(Path(__file__).read_bytes()),
                "tests": tests,
                "input_files": [{"relative_path": p, "sha256": sha((FIXTURE / p).read_bytes())} for p in input_paths],
                "data_root_overrides": {"finals_cases.REPO_ROOT": "synthetic_fixture",
                    "finals_cases.AGENT_ROOT": "synthetic_fixture/finals",
                    "finals_cases.REGISTRY": "synthetic_fixture/data/evaluation/public_reproduction_cases.json",
                    "finals_pipeline.REPO_ROOT": "synthetic_fixture", "finals_pipeline.AGENT_ROOT": "synthetic_fixture/finals"},
                "overrides_are_only_data_roots": True, "business_functions_replaced": [],
                "scope": "Actual run_case(mode=manual), computation/state/can_approve only; approve_report never invoked.",
                "synthetic_registration_assumption": "Auditor authored source_kind=article_extract, evidence_status, hashes and locators. Not a public UI registration exploit or external paper acquisition.",
                "earlier_audit_relation": "Same four mechanisms as prior source_gate audit; fresh presealed coherent fixture. Row-count claim is now an exact separate source sentence, not a mean/count metadata mismatch.",
                "model_calls": 0, "external_api_calls": 0,
                "_change_note": "Prespecify semantic boundary and accurate-registry candidate control before executing actual pipeline."}
    path = ROOT / "0_이영_pipeline_protocol.json"
    dump(path, protocol)
    digest = sha(path.read_bytes())
    (ROOT / "0_이영_pipeline_protocol.sha256").write_text(digest + "\n", encoding="ascii")
    print(json.dumps({"phase": "PREPARED_NOT_EXECUTED", "case_count": len(tests), "protocol_sha256": digest,
                      "created_at_kst": protocol["created_at_kst"]}, ensure_ascii=False))


def run(snapshot):
    protocol_path = ROOT / "0_이영_pipeline_protocol.json"
    sealed = (ROOT / "0_이영_pipeline_protocol.sha256").read_text(encoding="ascii").strip()
    assert sha(protocol_path.read_bytes()) == sealed, "PROTOCOL_CHANGED"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    assert sha(Path(__file__).read_bytes()) == protocol["runner_sha256"], "RUNNER_CHANGED"
    for item in protocol["input_files"]:
        assert sha((FIXTURE / item["relative_path"]).read_bytes()) == item["sha256"], "FIXTURE_CHANGED"
    before = code_receipt(snapshot)
    assert before == protocol["code"], "SNAPSHOT_CHANGED_AFTER_PROTOCOL"
    sys.path.insert(0, str(snapshot))
    sys.path.insert(0, str(snapshot / "finals"))
    import finals_cases
    import finals_pipeline
    # Explicitly listed data globals only. Function objects and their source are untouched.
    finals_cases.REPO_ROOT = FIXTURE
    finals_cases.AGENT_ROOT = FIXTURE / "finals"
    finals_cases.REGISTRY = FIXTURE / "data/evaluation/public_reproduction_cases.json"
    finals_pipeline.REPO_ROOT = FIXTURE
    finals_pipeline.AGENT_ROOT = FIXTURE / "finals"
    assert Path(finals_pipeline.run_case.__code__.co_filename).resolve() == snapshot / "finals/finals_pipeline.py"
    assert Path(finals_cases.load_case.__code__.co_filename).resolve() == snapshot / "finals/finals_cases.py"
    started = now()
    outcomes = []
    for test in protocol["tests"]:
        case_id = test["case_id"]
        loaded = finals_cases.load_case(case_id)
        candidate = None
        if test["candidate_overrides"]:
            candidate = deepcopy(loaded["manual_proposal"])
            candidate.update(test["candidate_overrides"])
        report = finals_pipeline.run_case(case_id, mode="manual", proposal_text=candidate)
        assert not report["llm_executed"] and not report["actual_model_output"]
        assert not report["provider_calls"] and not report["model_stage_records"]
        assert report["human_approval"]["approved"] is False
        assert report["validation"].get("human_semantic_confirmed") is False
        assert report["execution_provenance"]["code_commit"] == REVISION
        dump(ROOT / "reports" / (case_id + ".json"), report)
        frame = loaded["dataframe"]
        outcomes.append({"case_id": case_id, "kind": test["kind"], "recorded_at_kst": report["recorded_at_kst"],
            "finished_at_kst": report["finished_at_kst"], "source_gate": loaded["source_gate"],
            "registered_quote_at_registered_location": test["registered_quote_at_registered_location"],
            "input_data_sha256": loaded["input_sha256"], "actual_unique_people": int(frame["participant_id"].nunique()),
            "actual_experiments": sorted(frame["experiment"].unique().tolist()), "actual_rows": len(frame),
            "source_quote": loaded["source_quote"], "registered_source_location": loaded["source_location"],
            "submitted_candidate": deepcopy(report["proposal"]), "state": report["state"],
            "can_approve": report["can_approve"], "calculation": report["calculation"],
            "validation": report["validation"], "formal_verification": report.get("formal_verification"),
            "human_approval": report["human_approval"], "llm_executed": report["llm_executed"],
            "provider_call_count": len(report["provider_calls"]), "errors": report["errors"],
            "remaining_issues": report["remaining_issues"], "elapsed_ms": report["elapsed_ms"],
            "report_path": "reports/" + case_id + ".json",
            "report_sha256": sha((ROOT / "reports" / (case_id + ".json")).read_bytes()),
            "desired_can_approve_if_location_and_data_meaning_are_claimed": test["desired_can_approve_if_location_and_data_meaning_are_claimed"]})
    after = code_receipt(snapshot)
    assert after == before, "SNAPSHOT_MUTATED"
    result = {"version": 0, "git_revision": REVISION, "started_at_kst": started, "finished_at_kst": now(),
              "protocol_sha256": sealed, "environment": environment(), "code_before": before, "code_after": after,
              "data_root_overrides": protocol["data_root_overrides"], "business_functions_replaced": [],
              "scope": protocol["scope"], "synthetic_registration_assumption": protocol["synthetic_registration_assumption"],
              "model_calls": 0, "external_api_calls": 0, "human_approval_calls": 0, "cases": outcomes,
              "_change_note": "Actual manual pipeline observations; preserve unresolved meaning and pending human approval separately."}
    dump(ROOT / "0_이영_pipeline_results.json", result)
    print(json.dumps({"git_revision": REVISION, "started_at_kst": started, "finished_at_kst": result["finished_at_kst"],
                      "cases": [{"case_id": row["case_id"], "source_gate": row["source_gate"], "state": row["state"],
                                 "calculated": row["calculation"].get("value"), "can_approve": row["can_approve"],
                                 "validation_errors": row["validation"]["errors"],
                                 "human_approved": row["human_approval"]["approved"]} for row in outcomes]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Actual manual-pipeline boundary audit; no approval or model.")
    phase = parser.add_mutually_exclusive_group(required=True)
    phase.add_argument("--prepare", action="store_true")
    phase.add_argument("--run", action="store_true")
    parser.add_argument("--snapshot", type=Path, default=ROOT.parent / "snapshot")
    args = parser.parse_args()
    snapshot = args.snapshot.resolve()
    if args.prepare:
        prepare(snapshot)
    else:
        run(snapshot)
