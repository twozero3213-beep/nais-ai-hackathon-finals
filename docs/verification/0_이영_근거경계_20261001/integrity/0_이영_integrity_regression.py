"""[0 이영] version 0; proposed post-fix regression using actual functions.

Reason: check the same R01/R02/R03 fields without replacing any product function.
This file is a separate regression proposal, not a claimed execution result.
The original frozen experiment already measured these inputs and outputs.
Usage: python -B 0_이영_integrity_regression.py --snapshot PRODUCT_ROOT
All reviewer decisions here are synthetic local tests, not actual human approval.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--snapshot",required=True,type=Path);args=parser.parse_args()
    root=args.snapshot.resolve();here=Path(__file__).resolve().parent
    protocol=json.loads((here/"protocol.json").read_text(encoding="utf-8"))
    seal=json.loads((here/"protocol-seal.json").read_text(encoding="utf-8"))
    if hashlib.sha256((here/"protocol.json").read_bytes()).hexdigest()!=seal["protocol_file_sha256"]:raise RuntimeError("FROZEN_FIXTURE_CHANGED")
    def audit(event,args):
        if event in {"socket.connect","socket.connect_ex"}:raise RuntimeError("NETWORK_FORBIDDEN")
    sys.addaudithook(audit)
    sys.path[:0]=[str(root/"finals"),str(root)]
    pipeline=importlib.import_module("finals_pipeline");cases=importlib.import_module("finals_cases")
    failures=[];results=[]
    with tempfile.TemporaryDirectory(prefix="synthetic-integrity-",dir=here) as temp:
        fixture=Path(temp);cases.REPO_ROOT=fixture;cases.REGISTRY=fixture/"registry.json"
        initial=protocol["fixture"]
        (fixture/"data.csv").write_bytes(initial["csv"].encode());(fixture/"source.txt").write_bytes(initial["source"].encode())
        cases.REGISTRY.write_text(json.dumps(initial["registry"]),encoding="utf-8")
        for spec in protocol["cases"]:
            if not spec["id"].startswith(("R01-","R02-","R03-")):continue
            normal=pipeline.run_case_manual("SYNTHETIC-INTEGRITY-MEAN")
            assert normal["can_approve"] is True, "NORMAL_PREVIEW_MUST_BE_APPROVABLE"
            modified=deepcopy(normal)
            for path,value in spec["report_changes"].items():
                parts=path.split(".");target=modified
                for part in parts[:-1]:target=target[part]
                target[parts[-1]]=deepcopy(value)
            result=pipeline.approve_report(modified,protocol["scope"]["synthetic_reviewer"],confirmed=True)
            check=(result["state"]=="APPROVED" and result["calculation"]==normal["calculation"])
            results.append({"id":spec["id"],"fresh_calculation_in_approved_output":check})
            if not check:failures.append(spec["id"])
        original=pipeline.approve_report(normal,protocol["scope"]["synthetic_reviewer"],confirmed=True)
        reopened=pipeline.reopen_report(pipeline.export_report(original))
        assert reopened["human_approval"]["active"] is False and reopened["state"]=="IMPORTED_REVIEW", "IMPORTED_APPROVAL_MUST_BE_INACTIVE"
    commit=subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip()
    print(json.dumps({"recorded_at_kst":datetime.now(timezone(timedelta(hours=9))).isoformat(),"product_commit":commit,"pipeline_file_sha256":hashlib.sha256((root/"finals/finals_pipeline.py").read_bytes()).hexdigest(),"results":results,"failed":failures,"actual_human_decisions":0,"model_calls":0,"product_mutations":0}))
    return int(bool(failures))

if __name__=="__main__":raise SystemExit(main())
