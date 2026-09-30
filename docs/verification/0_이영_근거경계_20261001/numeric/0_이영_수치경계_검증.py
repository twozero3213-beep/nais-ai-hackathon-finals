#!/usr/bin/env python3
# [작성: 0 이영 · Codex · 버전 0] 실제 작성 시각은 protocol의 sealed_at_kst에 기록한다.
# 이유: 합성 입력/예상을 실행 전에 봉인하고 수정 없는 실제 필터·검산·계약 함수를 비교한다.
# 제품 코드 수정·monkeypatch·모델/네트워크/키 접근 없이 독립 numeric 경로에만 산출한다.
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import warnings

COMMIT = "a6729178963392249b14c9dfbd93bf28704262a4"
OUT = Path(__file__).resolve().parent
PROTOCOL = OUT / "0_이영_수치경계_protocol.json"
HASH = OUT / "0_이영_수치경계_hash.json"
RESULTS = OUT / "0_이영_수치경계_results.json"
REPORT = OUT / "0_이영_수치경계_report.md"
SOURCES = ["core/normalization.py", "core/statistics.py", "core/typed_contracts.py",
           "core/models.py", "core/verifier.py", "core/semantic.py", "core/decision_provenance.py",
           "finals/finals_pipeline.py", "finals/finals_cases.py", "finals/finals_privacy.py",
           "finals/finals_provider.py", "finals/finals_provenance.py"]

def now():
    return datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")

def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()

def source_hashes(repo):
    return {name: sha((repo / name).read_bytes()) for name in SOURCES}

def variant(name, data, target, reported, wanted_indices, wanted_mean, kind="mean", **extra):
    return dict(name=name, data=data, filter_target=target, reported_value=reported,
                expected_selected_indices=wanted_indices, semantic_expected_value=wanted_mean,
                method=kind, tolerance=0, missing_policy="error", **extra)

def pairs():
    # 预先固定的领域语义，不能用实际归一化输出重新定义期望。
    # 아래 exact_code는 데이터 사전이 서로 다른 범주라고 정의한 합성 전제다.
    return [
      {"id":"N01", "topic":"문자 코드의 앞자리 0", "severity_if_observed":"P1 계산 조건 의미 경계",
       "attack":variant("distinct_codes", {"group":["01","1"],"age":[10,30]}, "01", 20, [0], "10", semantics="exact_code"),
       "normal":variant("numeric_representation", {"group":[1,1.0],"age":[10,30]}, "1", 20, [0,1], "20", semantics="numeric_measure")},
      {"id":"N02", "topic":"퍼센트 문자열과 수치 1 혼용", "severity_if_observed":"P1 계산 조건 의미 경계",
       "attack":variant("percent_is_distinct_code", {"group":["1%",1],"age":[10,30]}, "1%", 20, [0], "10", semantics="exact_code"),
       "normal":variant("same_numeric_group", {"group":["1.0",1],"age":[10,30]}, "1", 20, [0,1], "20", semantics="numeric_measure")},
      {"id":"N03", "topic":"2^53 이후 정수 식별자 충돌", "severity_if_observed":"P1 결정적 잘못된 표본 선택",
       "attack":variant("large_integer_codes", {"group":["9007199254740992","9007199254740993"],"age":[10,30]}, "9007199254740992", 20, [0], "10", semantics="exact_code"),
       "normal":variant("small_integer_codes", {"group":["2","3"],"age":[10,30]}, "2", 10, [0], "10", semantics="exact_code")},
      {"id":"N04", "topic":"boolean alias와 고유 문자열 코드", "severity_if_observed":"P1 계산 조건 의미 경계",
       "attack":variant("three_distinct_codes", {"group":["true","1","yes"],"age":[10,20,30]}, "true", 20, [0], "10", semantics="exact_code"),
       "normal":variant("confirmed_binary_alias", {"group":[True,1,"yes"],"age":[10,20,30]}, True, 20, [0,1,2], "20", semantics="binary_alias")},
      {"id":"N05", "topic":"null/NaN/inf 평균 보호 경계", "severity_if_observed":"보호 동작 확인",
       "attack":variant("null_value", {"group":["A","A"],"age":[10,None]}, "A", 10, [0,1], None, should_block=True),
       "attack_variants":[variant("nan_value", {"group":["A","A"],"age":[10,{"special":"nan"}]}, "A", 10, [0,1], None, should_block=True),
                          variant("inf_value", {"group":["A","A"],"age":[10,{"special":"inf"}]}, "A", 10, [0,1], None, should_block=True)],
       "normal":variant("finite_mean", {"group":["A","A"],"age":[10,20]}, "A", 15, [0,1], "15")},
      {"id":"N06", "topic":"빈 집단의 row_count=0 범위", "severity_if_observed":"P2 정상 0건 처리 정책 차이",
       "attack":variant("zero_selected_rows", {"group":["A"],"age":[10]}, "B", 0, [], "0", kind="row_count", zero_is_valid_for_defined_row_count=True),
       "normal":variant("one_selected_row", {"group":["A"],"age":[10]}, "A", 1, [0], "1", kind="row_count")},
      {"id":"N07", "topic":"유한 입력 평균의 중간 합 overflow", "severity_if_observed":"P2 계산 가능 입력 거절",
       "attack":variant("finite_true_mean_overflow", {"group":["A","A"],"age":[1e308,1e308]}, "A", 1e308, [0,1], "1E+308"),
       "normal":variant("finite_without_overflow", {"group":["A","A"],"age":[1e307,1e307]}, "A", 1e307, [0,1], "1E+307")},
      {"id":"N08", "topic":"거대 정수 평균과 보고 정수의 float 비교", "severity_if_observed":"P1 정확 오차 1을 차이 0으로 계산",
       "attack":variant("integer_exact_mean", {"group":["A","A"],"age":[9007199254740992,9007199254740994]}, "A", 9007199254740993, [0,1], "9007199254740993"),
       "normal":variant("small_integer_exact_mean", {"group":["A","A"],"age":[2,4]}, "A", 3, [0,1], "3")},
      {"id":"N09", "topic":"동일 참가자 중복행의 평균 가중 변화", "severity_if_observed":"P1 관측 단위 입력 위험",
       "attack":variant("duplicate_person_weight", {"group":["A","A","A"],"person":["p1","p1","p2"],"age":[10,10,20]}, "A", 40/3, [0,1,2], "15", semantics="one_record_per_individual"),
       "normal":variant("one_row_each_person", {"group":["A","A"],"person":["p1","p2"],"age":[10,20]}, "A", 15, [0,1], "15", semantics="one_record_per_individual")},
      {"id":"N10", "topic":"명시 허용오차 0과 숨은 절대오차 1e-12", "severity_if_observed":"P2 허용오차 계약 정책",
       "attack":variant("nonzero_with_zero_tolerance", {"group":["A"],"age":[5e-13]}, "A", 0, [0], "5E-13", expected_within_tolerance=False),
       "normal":variant("exact_zero", {"group":["A"],"age":[0]}, "A", 0, [0], "0", expected_within_tolerance=True)},
    ]

def seal(repo):
    if PROTOCOL.exists() or HASH.exists():
        raise SystemExit("protocol already exists; use a new allowed output directory for another protocol")
    assert git(repo, "rev-parse", "HEAD") == COMMIT
    protocol = {"_change_note":"[0 이영] 버전0: 공개 합성 데이터의 의미 예상·정상 반례를 실제 함수 실행 전에 고정한다.",
                "sealed_at_kst":now(), "commit":COMMIT, "source_sha256":source_hashes(repo),
                "scope":"pure_real_functions_with_synthetic_case_inputs; no loader/UI/approval/LLM/API execution",
                "oracle":"literal code/binary dictionary and exact decimal/rational expectation, not function output",
                "pairs":pairs()}
    dump(PROTOCOL, protocol)
    dump(HASH, {"_change_note":"[0 이영] 사전 예상과 실행 스크립트의 지문을 봉인한다.", "sealed_at_kst":now(),
                "protocol_sha256":sha(PROTOCOL.read_bytes()), "script_sha256":sha(Path(__file__).read_bytes())})
    print(json.dumps({"phase":"sealed", "at_kst":protocol["sealed_at_kst"], "pairs":len(protocol["pairs"]),
                      "protocol_sha256":sha(PROTOCOL.read_bytes())}, ensure_ascii=False))

def expand(value):
    if isinstance(value,dict) and set(value)=={"special"}:
        return {"nan":math.nan,"inf":math.inf,"-inf":-math.inf}[value["special"]]
    if isinstance(value,dict): return {k:expand(v) for k,v in value.items()}
    if isinstance(value,list): return [expand(v) for v in value]
    return value

def clean(value):
    if isinstance(value,float) and not math.isfinite(value):return {"nonfinite":repr(value)}
    if isinstance(value,dict):return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [clean(v) for v in value]
    if hasattr(value,"item"):return clean(value.item())
    return value

def capture(function, *args):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            value=function(*args)
            out={"ok":True,"data":clean(value)}
        except Exception as exc:
            out={"ok":False,"error_type":type(exc).__name__,"error":str(exc)}
        out["warnings"]=[{"category":w.category.__name__,"message":str(w.message)} for w in caught]
        return out

def run(repo):
    if RESULTS.exists() or REPORT.exists(): raise SystemExit("results already exist; refusing overwrite")
    recorded=json.loads(HASH.read_text(encoding="utf-8"))
    assert sha(PROTOCOL.read_bytes())==recorded["protocol_sha256"]
    assert sha(Path(__file__).read_bytes())==recorded["script_sha256"]
    protocol=json.loads(PROTOCOL.read_text(encoding="utf-8"))
    assert git(repo,"rev-parse","HEAD")==COMMIT
    assert source_hashes(repo)==protocol["source_sha256"]
    # 사용자 요청 범위: import는 공개 코드 정의를 로드하며 공급자/키 함수는 호출하지 않는다.
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(repo))
    sys.path.insert(0,str(repo/"finals"))
    import pandas as pd
    from core.normalization import filter_mask
    from core.statistics import descriptive
    from core.typed_contracts import build_typed_contract, check_evidence_sufficiency
    from core.verifier import verify
    from finals_pipeline import _calculate, _validation, _claim
    for module in (_calculate,filter_mask,descriptive,build_typed_contract):
        assert Path(sys.modules[module.__module__].__file__).resolve().is_relative_to(repo.resolve())
    started=now()
    results=[]
    for pair in protocol["pairs"]:
        variants=[("attack",pair["attack"]), *(("attack_variant",v) for v in pair.get("attack_variants",[])),("normal",pair["normal"])]
        for arm, spec in variants:
            data=expand(spec["data"])
            df=pd.DataFrame({k:pd.Series(v,dtype=object) if k!="age" else pd.Series(v) for k,v in data.items()})
            target=expand(spec["filter_target"])
            mask=filter_mask(df["group"],target)
            filtered=df[mask]
            csv=df.to_csv(index=False).encode("utf-8")
            quote="Synthetic registered descriptive claim. Group and row meaning are defined by the sealed input dictionary."
            proposal={"claim_text":"Synthetic calculation boundary", "reported_value":spec["reported_value"],
                      "source_quote":quote,"source_location":"synthetic:table1",
                      "method":spec["method"],"column":"__dataset__" if spec["method"]=="row_count" else "age",
                      "filters":[{"column":"group","value":target}],
                      "denominator":{"rule":"filtered_rows","expected_n":len(spec["expected_selected_indices"])},
                      "missing_policy":spec["missing_policy"],"unit":"individuals" if spec["method"]=="row_count" else "years",
                      "tolerance":spec["tolerance"]}
            # 이는 함수의 공개 dict 입력이다. 실제 loader/등록 파일/출처 검사 결과를 바꾸지 않는다.
            case={"id":pair["id"],"dataframe":df,"source_gate":True,"source":{"data_file":"synthetic.csv"},
                  "input_sha256":sha(csv),"source_sha256":sha(quote.encode()),"expected_proposal":deepcopy(proposal)}
            claim=_claim(case,proposal,confirmed=True)
            contract=build_typed_contract(claim,"synthetic.csv",sha(csv))
            check=check_evidence_sufficiency(contract,df)
            pure=capture(descriptive,filtered,proposal["column"],proposal["method"])
            calc=capture(_calculate,case,proposal)
            validation=capture(_validation,case,proposal)
            verified=capture(verify,claim,df)
            selected=filtered.index.tolist()
            got_value=calc["data"]["value"] if calc["ok"] else None
            wanted=spec["semantic_expected_value"]
            exact_match=(Decimal(str(got_value))==Decimal(wanted)) if got_value is not None and wanted is not None else None
            results.append({"pair_id":pair["id"],"arm":arm,"name":spec["name"],"topic":pair["topic"],
                            "at_kst":now(),"input_sha256":sha(csv),"input_dtypes":{k:str(v) for k,v in df.dtypes.items()},
                            "selected_indices":selected,"expected_selected_indices":spec["expected_selected_indices"],
                            "selection_matches":selected==spec["expected_selected_indices"],"semantic_expected_value":wanted,
                            "value_exactly_matches_semantic_oracle":exact_match,"should_block":spec.get("should_block",False),
                            "expected_within_tolerance":spec.get("expected_within_tolerance"),
                            "typed_contract_with_explicit_human_confirmation":{"executable":check.executable,"missing":check.missing,"reason":check.reason},
                            "case_source_gate_input_assumed":True,"synthetic_case_validation":validation,
                            "pure_descriptive":pure,"finals_calculate":calc,"core_verify_with_human_confirmation":verified,
                            "individual_count":len(set(data["person"])) if "person" in data else None})
    assert source_hashes(repo)==protocol["source_sha256"]
    assert sha(PROTOCOL.read_bytes())==recorded["protocol_sha256"]
    results_doc={"_change_note":"[0 이영] 버전0: 사전 봉인 후 수정 없는 실제 함수 실행 결과. 합성 source_gate/human-confirmed 입력 전제를 최종 UI/실승인 결과로 전이하지 않는다.",
                 "started_at_kst":started,"ended_at_kst":now(),"commit":COMMIT,"protocol_sha256":recorded["protocol_sha256"],
                 "script_sha256":recorded["script_sha256"],"source_sha256":protocol["source_sha256"],
                 "environment":{"python":sys.version,"implementation":platform.python_implementation(),"platform":platform.platform(),
                                "packages":{name:importlib.metadata.version(name) for name in ("pandas","numpy","scipy","jsonschema")}},
                 "limits":{"network_calls":0,"paid_ai_calls":0,"key_reads":0,"database_reads":0,
                           "product_changes":0,"monkeypatches":0,"ui_executions":0,"approval_executions":0,
                           "source_gate":"provided true as synthetic function precondition, not actual source verification",
                           "human_confirmation":"explicit Claim input precondition, not a real human approval event"},
                 "source_hashes_unchanged":True,"results":results}
    dump(RESULTS,results_doc)
    lines=["# 0 이영 · 허용 계산/정규화 경계 실험", "",
           f"<!-- [작성: 0 이영 · Codex · 버전 0] {results_doc['ended_at_kst']} — 사전 예상·지문 봉인 뒤 실제 함수를 합성 자료로 실행했다. 제품 수정·모델·키·네트워크·실DB·최종 승인 실행 없음. -->", "",
           f"고정 소스: `{COMMIT}`. 봉인 {protocol['sealed_at_kst']}, 실행 {started} ~ {results_doc['ended_at_kst']}.",
           f"10쌍, 총 {len(results)}개 입력. 결과의 source_gate=True와 human-confirmed=True는 합성 입력 전제다. 실제 loader/원문 검증·최종 UI·최종 사람 승인 결과가 아니다.",
           "", "|쌍|입력|선택행(예상)|실제 finals 계산|의미 예상|실제 core verify|분모 일치|", "|---|---|---|---|---|---|---|"]
    for item in results:
        calc=item["finals_calculate"]
        calculated=str(calc["data"]["value"]) if calc["ok"] else calc["error_type"]+":"+calc["error"]
        cv=item["core_verify_with_human_confirmation"]
        status=cv["data"][0] if cv["ok"] else cv["error_type"]
        denom=calc["data"]["denominator_matches"] if calc["ok"] else "미실행"
        lines.append(f"|{item['pair_id']}|{item['arm']}:{item['name']}|{item['selected_indices']} ({item['expected_selected_indices']})|{calculated}|{item['semantic_expected_value']}|{status}|{denom}|")
    lines += ["", "## 해석 경계", "",
              "문자 코드의 의미 예상은 프로토콜에 고정된 사전 전제다. 숫자 1과 1.0을 같은 수치 집단으로 보는 정상 사례와 고유 코드의 오병합을 구분한다. 현재 정규화에 열별 사전/동치 정책이 없어 이 구별이 자동으로 되지 않는지 관측한다.",
              "null/NaN/inf·빈 집단·overflow에서 실제 차단된 결과는 보호 동작 또는 정상 처리 범위의 정책 차이로 남긴다. 차단된 사례를 성공 반환 취약점으로 계산하지 않는다.",
              "중복 참가자 사례는 행 평균 자체의 산술 오류가 아니다. 참가자 한 명당 동일 가중이라는 의미 계약을 현재 행 기반 입력이 표현하지 못해 평균이 바뀌는 입력 위험이다.",
              "공개 원문/새 논문 재현·LLM 응답·브라우저 상태·실제 승인 결과를 실행하지 않았다. 최소 수정 위치와 확인된 사실은 아래 후속 해석에 적는다."]
    REPORT.write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({"phase":"executed","pairs":10,"inputs":len(results),"ended_at_kst":results_doc["ended_at_kst"],
                      "results_sha256":sha(RESULTS.read_bytes()),"source_hashes_unchanged":True},ensure_ascii=False))

def main():
    parser=argparse.ArgumentParser(description="Seal then run real calculation boundaries on public synthetic inputs.")
    parser.add_argument("phase",choices=("seal","run"))
    parser.add_argument("--repo",type=Path,required=True)
    args=parser.parse_args()
    repo=args.repo.resolve()
    if args.phase=="seal":seal(repo)
    else:run(repo)

if __name__=="__main__":main()
