"""Portable, local-only actual-function integrity experiment; not a human decision.

# [작성: 0 이영] version 0; actual creation time is recorded in protocol-seal.json.
# Reason: exercise approval/export/reopen with synthetic inputs without touching product files.
# Only finals_cases data-root/registry globals are isolated; no business function is replaced.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import subprocess
import sys

REV = "a6729178963392249b14c9dfbd93bf28704262a4"
HERE = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))
REASON = "synthetic local test reviewer: checked fixture source and arithmetic; not a real human decision"
FILES = ("finals/finals_pipeline.py", "finals/finals_cases.py", "finals/finals_provenance.py", "finals/finals_privacy.py", "finals/finals_provider.py", "core/models.py", "core/verifier.py", "core/statistics.py", "core/normalization.py", "core/typed_contracts.py")

def now(): return datetime.now(KST).isoformat()
def rawhash(raw): return hashlib.sha256(raw).hexdigest()
def canon(value): return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
def sha(value): return rawhash(canon(value))
def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+"\n", encoding="utf-8")
def read(path): return json.loads(path.read_text(encoding="utf-8"))
def git(root, *args): return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL, text=True).strip()
def setpath(obj, path, value):
    parts = path.split("."); cur = obj
    for p in parts[:-1]: cur = cur[int(p)] if isinstance(cur, list) else cur[p]
    cur[parts[-1]] = deepcopy(value)

def prepare(snapshot):
    if (HERE/"protocol-seal.json").exists(): raise RuntimeError("ALREADY_SEALED_NO_OVERWRITE")
    if git(snapshot, "rev-parse", "HEAD") != REV or git(snapshot, "status", "--short"): raise RuntimeError("SNAPSHOT_REVISION_OR_CLEANLINESS_MISMATCH")
    csv = "group,age\nA,10\nA,30\nB,40\n"
    source = "SYNTHETIC LOCAL FIXTURE. Group A has two records, with mean age 20 years. All selected ages are observed. This is not a published scientific claim.\n"
    item = {"claim_id":"SYNTHETIC-INTEGRITY-MEAN", "claim_text":"Synthetic group A mean age is 20 years", "reported_value":20, "source_quote":"Group A has two records, with mean age 20 years.", "source_location":"synthetic paragraph 1", "source_file":"source.txt", "source_sha256":rawhash(source.encode()), "data_file":"data.csv", "data_sha256":rawhash(csv.encode()), "delimiter":",", "method":"mean", "column":"age", "filters":{"group":"A"}, "missing_policy":"error", "tolerance":0.01, "source_kind":"article_extract", "evidence_status":"SYNTHETIC_LOCAL_TEST", "paper_url":"https://example.invalid/synthetic-integrity", "license":"Synthetic test fixture", "scope_note":"Synthetic only; not an actual paper or actual human approval."}
    cases = []
    def add(cid, op="approve", changes=None, fixture=None, expected=None, **extra):
        cases.append({"id":cid,"operation":op,"report_changes":changes or {},"fixture_changes":fixture or {},"expected":expected or {},**extra})
    add("N01-normal-approval-export-reopen", "roundtrip", expected={"approval_state":"APPROVED", "reopen_state":"IMPORTED_REVIEW", "reopen_active":False, "calculation":20})
    add("R01-calculation-value-tamper", changes={"calculation.value":999,"calculation.calculated_value":999,"calculation.delta":979}, expected={"safe_calculation":20})
    add("R02-within-tolerance-tamper", changes={"calculation.within_tolerance":False}, expected={"safe_within_tolerance":True})
    add("R03-calculation-envelope-tamper", changes={"calculation.executed":False,"calculation.reported_value":999,"calculation.selected_rows":999,"calculation.denominator_matches":False,"calculation.engine":"synthetic untrusted engine label","calculation.meta":{"untrusted_marker":True}}, expected={"safe_calculation_envelope":True})
    add("A01-can-approve-false", changes={"can_approve":False}, expected={"error":"REPORT_NOT_APPROVABLE"})
    add("A02-can-approve-true-on-real-conflict", changes={"can_approve":True}, fixture={"before_run":{"reported_value":999}}, expected={"error":"APPROVAL_ARITHMETIC_CONFLICT"})
    add("A03-unresolved-critique", changes={"critique.issues":["synthetic unresolved evidence issue"]}, expected={"error":"APPROVAL_CRITIQUE_UNRESOLVED"})
    add("A04-critique-not-ready", changes={"critique.evidence_ready":False}, expected={"error":"APPROVAL_CRITIQUE_UNRESOLVED"})
    add("A05-pending-approval-metadata-tamper", changes={"human_approval.reason":"untrusted pending reason","human_approval.actor":"untrusted pending actor"}, expected={"approval_state":"APPROVED","reason":REASON,"actor":"HUMAN_USER"})
    add("A06-no-explicit-confirmation", confirmed=False, expected={"error":"EXPLICIT_HUMAN_CONFIRMATION_AND_REASON_REQUIRED"})
    add("A07-empty-reason", reason="", expected={"error":"EXPLICIT_HUMAN_CONFIRMATION_AND_REASON_REQUIRED"})
    add("A08-second-reason-binding", reason=REASON+"; alternate synthetic reason", expected={"approval_state":"APPROVED","reason":REASON+"; alternate synthetic reason","actor":"HUMAN_USER"})
    add("B01-proposal-mutated-hash-unchanged", changes={"proposal.source_location":"synthetic different location"}, expected={"error":"APPROVAL_INPUT_CHANGED"})
    add("B02-proposal-rehashed-but-wrong", changes={"proposal.filters.0.value":"B"}, rebind=True, expected={"error":"APPROVAL_EVIDENCE_INVALID"})
    add("B03-csv-bytes-changed", fixture={"after_run":{"csv_append":"B,50\n"}}, expected={"error":"APPROVAL_INPUT_CHANGED"})
    add("B04-source-bytes-changed", fixture={"after_run":{"source_append":"Additional synthetic note.\n"}}, expected={"error":"APPROVAL_INPUT_CHANGED"})
    add("B05-registered-source-location-changed", fixture={"after_run":{"source_location":"synthetic paragraph 2"}}, expected={"error":"APPROVAL_EVIDENCE_INVALID"})
    add("B06-registered-filters-changed", fixture={"after_run":{"filters":{"group":"B"}}}, expected={"error":"APPROVAL_EVIDENCE_INVALID"})
    add("B07-recorded-engine-metadata-tamper", changes={"code_commit":"synthetic untrusted recorded commit","code_worktree_sha256":"0"*64,"execution_provenance.execution_fingerprint":"0"*64,"execution_provenance.code_files_sha256":{"core/statistics.py":"0"*64}}, expected={"approval_state":"APPROVED"}, scope="Recorded provenance metadata only; actual loaded engine code is unchanged.")
    add("E01-saved-body-edited-with-old-digest", "export_edit", changes={"calculation.calculated_value":999}, expected={"error":"REPORT_INTEGRITY_MISMATCH"})
    add("E02-edited-body-reexported", "reexport", changes={"calculation.calculated_value":999}, expected={"reopen_state":"IMPORTED_REVIEW","reopen_active":False,"reopen_calculation":20})
    add("E03-edited-body-unsigned", "unsigned", changes={"calculation.calculated_value":999}, expected={"reopen_state":"IMPORTED_REVIEW","reopen_active":False,"reopen_calculation":20,"import_integrity":"UNSIGNED_RECORD_ONLY"})
    add("E04-historical-reason-edited-reexported", "reexport", changes={"human_approval.reason":"synthetic edited historical reason"}, expected={"reopen_state":"IMPORTED_REVIEW","reopen_active":False,"historical_reason":"synthetic edited historical reason"})
    add("E05-current-csv-changed-before-reopen", "roundtrip", fixture={"before_reopen":{"csv_append":"B,50\n"}}, expected={"approval_state":"APPROVED","reopen_state":"BLOCKED_CHANGED_INPUT","reopen_active":False})
    add("E06-real-in-memory-input-change", "recheck", expected={"recheck_state":"BLOCKED_CHANGED_INPUT","recheck_active":False})
    protocol = {"_change_note":"[0 이영] version 0; freeze synthetic inputs/independent boundary expectations before invoking actual product functions.", "created_at_kst":now(),"product_commit":REV,"source_file_sha256":{p:rawhash((snapshot/p).read_bytes()) for p in FILES},"fixture":{"csv":csv,"source":source,"registry":{"cases":[item]}},"cases":cases,"scope":{"actual_functions":["run_case_manual","approve_report","export_report","reopen_report","recheck_changed_input"],"save_report_function":"absent; UI downloads export_report output", "network":0,"real_model_calls":0,"actual_human_decisions":0,"product_mutations":0,"synthetic_reviewer":REASON,"isolation":"finals_cases.REPO_ROOT and finals_cases.REGISTRY point to experiment fixture only. No business-function replacement. Actual code/engine changes are not performed; B07 changes only report metadata.","expected":"Manual independent integrity boundary expectations, not model comparison or scientific correctness scoring."}}
    write(HERE/"protocol.json",protocol)
    write(HERE/"protocol-seal.json",{"_change_note":"[0 이영] version 0; seal written before product import or execution.","sealed_at_kst":now(),"protocol_file_sha256":rawhash((HERE/"protocol.json").read_bytes()),"runner_file_sha256":rawhash(Path(__file__).read_bytes())})
    write(HERE/"fixtures/initial.json",protocol["fixture"])
    print(json.dumps({"prepared":True,"protocol_sha256":rawhash((HERE/"protocol.json").read_bytes()),"cases":len(cases)}))

def run(snapshot):
    seal=read(HERE/"protocol-seal.json"); protocol=read(HERE/"protocol.json")
    if rawhash((HERE/"protocol.json").read_bytes()) != seal["protocol_file_sha256"] or rawhash(Path(__file__).read_bytes()) != seal["runner_file_sha256"]: raise RuntimeError("PROTOCOL_OR_RUNNER_CHANGED")
    if git(snapshot,"rev-parse","HEAD")!=REV or git(snapshot,"status","--short"): raise RuntimeError("SNAPSHOT_REVISION_OR_CLEANLINESS_MISMATCH")
    actual_hash={p:rawhash((snapshot/p).read_bytes()) for p in FILES}
    if actual_hash != protocol["source_file_sha256"]: raise RuntimeError("PRODUCT_SOURCE_CHANGED")
    network_attempts=[]
    def audit(event,args):
        if event in {"socket.connect","socket.connect_ex"}: network_attempts.append(event); raise RuntimeError("NETWORK_FORBIDDEN_LOCAL_EXPERIMENT")
    sys.addaudithook(audit)
    sys.path[:0]=[str(snapshot/"finals"),str(snapshot)]
    pipeline=importlib.import_module("finals_pipeline"); cases_module=importlib.import_module("finals_cases")
    fixture_root=HERE/"fixtures/active"; fixture_root.mkdir(parents=True,exist_ok=True)
    cases_module.REPO_ROOT=fixture_root; cases_module.REGISTRY=fixture_root/"registry.json"
    def reset():
        f=protocol["fixture"]
        (fixture_root/"data.csv").write_bytes(f["csv"].encode()); (fixture_root/"source.txt").write_bytes(f["source"].encode()); write(fixture_root/"registry.json",f["registry"])
    def mutate_fixture(changes):
        registry=read(fixture_root/"registry.json"); item=registry["cases"][0]
        for key,value in changes.items():
            if key=="csv_append":
                with (fixture_root/"data.csv").open("ab") as f:f.write(value.encode())
            elif key=="source_append":
                with (fixture_root/"source.txt").open("ab") as f:f.write(value.encode())
            else:item[key]=deepcopy(value)
        write(fixture_root/"registry.json",registry)
    def freeze_input(cid,stage,value):
        path=HERE/"inputs"/(cid+"-"+stage+".json");write(path,value)
        return {"path":path.relative_to(HERE).as_posix(),"sha256":rawhash(path.read_bytes()),"frozen_before_call_at_kst":now()}
    results=[]; started=now()
    for spec in protocol["cases"]:
        cid=spec["id"]; row={"id":cid,"operation":spec["operation"],"started_at_kst":now(),"expected":spec["expected"],"inputs":[],"error":None}
        reset(); mutate_fixture(spec["fixture_changes"].get("before_run",{}))
        row["fixture_before_run"]={p:rawhash((fixture_root/p).read_bytes()) for p in ("data.csv","source.txt","registry.json")}
        baseline=pipeline.run_case_manual("SYNTHETIC-INTEGRITY-MEAN")
        row["baseline"]={"state":baseline["state"],"can_approve":baseline["can_approve"],"calculation":deepcopy(baseline["calculation"]),"errors":baseline["errors"]}
        report=deepcopy(baseline); op=spec["operation"]
        if op=="approve":
            for key,value in spec["report_changes"].items():setpath(report,key,value)
            if spec.get("rebind"):
                report["proposal_sha256"]=pipeline._sha(report["proposal"])
                report["input_bindings"]=pipeline._input_bindings(cases_module.load_case(report["case_id"]),report["proposal"])
        mutate_fixture(spec["fixture_changes"].get("after_run",{}))
        reason=spec.get("reason",REASON); confirmed=spec.get("confirmed",True)
        row["inputs"].append(freeze_input(cid,"approve",{"report":report,"reason":reason,"confirmed":confirmed,"fixture_hashes":{p:rawhash((fixture_root/p).read_bytes()) for p in ("data.csv","source.txt","registry.json")}}))
        try:
            approved=pipeline.approve_report(report,reason,confirmed=confirmed)
            row["approval_state"]=approved["state"];row["approved"]=approved["human_approval"]["approved"];row["approval_active"]=approved["human_approval"].get("active")
            row["approved_calculation"]=deepcopy(approved["calculation"]);row["approved_claim_current_value"]=approved["claim_snapshot"]["current_value"];row["reason"]=approved["human_approval"]["reason"];row["actor"]=approved["human_approval"]["actor"]
            write(HERE/"reports"/(cid+"-approved.json"),approved)
            if op=="recheck":
                row["inputs"].append(freeze_input(cid,"recheck",approved)); changed=pipeline.recheck_changed_input(approved)
                row["recheck_state"]=changed["state"];row["recheck_active"]=changed["human_approval"].get("active");write(HERE/"reports"/(cid+"-rechecked.json"),changed)
            elif op!="approve":
                export_input=deepcopy(approved)
                if op in {"reexport","unsigned"}:
                    for key,value in spec["report_changes"].items():setpath(export_input,key,value)
                row["inputs"].append(freeze_input(cid,"export",export_input)); saved=pipeline.export_report(export_input)
                body=json.loads(saved)
                if op=="export_edit":
                    for key,value in spec["report_changes"].items():setpath(body,key,value)
                    saved=json.dumps(body,ensure_ascii=False,allow_nan=False)
                if op=="unsigned":body.pop("export_integrity_sha256");saved=json.dumps(body,ensure_ascii=False,allow_nan=False)
                (HERE/"reports"/(cid+"-saved.json")).write_text(saved,encoding="utf-8")
                mutate_fixture(spec["fixture_changes"].get("before_reopen",{}))
                row["inputs"].append(freeze_input(cid,"reopen",{"serialized_report":saved,"fixture_hashes":{p:rawhash((fixture_root/p).read_bytes()) for p in ("data.csv","source.txt","registry.json")}}))
                reopened=pipeline.reopen_report(saved);row["reopen_state"]=reopened["state"];row["reopen_active"]=reopened["human_approval"].get("active");row["reopen_calculation"]=reopened["calculation"].get("calculated_value");row["import_integrity"]=reopened["import_integrity"];row["historical_reason"]=reopened["imported_approval_record"].get("reason")
                write(HERE/"reports"/(cid+"-reopened.json"),reopened)
        except Exception as exc:row["error"]={"type":type(exc).__name__,"code":str(exc)}
        checks={}
        for key,value in spec["expected"].items():
            if key=="error":actual=row["error"]["code"] if row["error"] else None
            elif key=="calculation":actual=row.get("approved_calculation",{}).get("calculated_value")
            elif key=="safe_calculation":actual=row.get("approved_calculation",{}).get("calculated_value") if not row["error"] else value
            elif key=="safe_within_tolerance":actual=row.get("approved_calculation",{}).get("within_tolerance") if not row["error"] else value
            elif key=="safe_calculation_envelope":actual=row.get("approved_calculation")==row["baseline"]["calculation"] if not row["error"] else True
            else:actual=row.get(key)
            checks[key]={"actual":actual,"expected":value,"matches":actual==value}
        row["boundary_checks"]=checks;row["all_expected_boundaries_match"]=all(v["matches"] for v in checks.values());row["finished_at_kst"]=now();results.append(row)
        write(HERE/"results-progress.json",{"started_at_kst":started,"completed_cases":results})
        print(json.dumps({"id":cid,"error":row["error"],"approval_state":row.get("approval_state"),"calculation":row.get("approved_calculation",{}).get("calculated_value"),"boundary_match":row["all_expected_boundaries_match"]}),flush=True)
    reset()
    output={"_change_note":"[0 이영] version 0; actual function outputs from synthetic local fixtures; not real human approval or LLM experiment.","product_commit":REV,"source_file_sha256":actual_hash,"protocol_file_sha256":seal["protocol_file_sha256"],"runner_file_sha256":seal["runner_file_sha256"],"started_at_kst":started,"finished_at_kst":now(),"actual_functions":{name:{"file":"finals/finals_pipeline.py","first_line":inspect.getsourcelines(getattr(pipeline,name))[1],"function_source_sha256":rawhash(inspect.getsource(getattr(pipeline,name)).encode())} for name in protocol["scope"]["actual_functions"]},"network_attempts":network_attempts,"model_calls":0,"actual_human_decisions":0,"product_mutations":0,"business_function_replacements":0,"isolation":protocol["scope"]["isolation"],"cases":results,"counts":{"cases":len(results),"boundary_matches":sum(r["all_expected_boundaries_match"] for r in results),"boundary_mismatches":sum(not r["all_expected_boundaries_match"] for r in results)}}
    write(HERE/"results.json",output);write(HERE/"results-sha256.json",{"_change_note":"[0 이영] version 0; result file bytes after completion.","recorded_at_kst":now(),"results_file_sha256":rawhash((HERE/"results.json").read_bytes())})
    if git(snapshot,"status","--short"):raise RuntimeError("PRODUCT_WORKTREE_CHANGED")
    print(json.dumps(output["counts"]))

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--snapshot",type=Path,required=True);parser.add_argument("--prepare",action="store_true");args=parser.parse_args()
    (prepare if args.prepare else run)(args.snapshot.resolve())
