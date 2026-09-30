"""Exploratory, same-input comparison. No API calls and no gold labels."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

from tools.independent_replay import _calculate

STATUS = "EXPLORATORY_NOT_SCORED"
METHODS = {"count_rows", "missing_cells", "mean"}


# [작성: 가상 전문가7] 2026-09-26 case62
# 무엇/왜: 중복 JSON 키 거부로 마지막 값 덮어쓰기 차단 / 입출력: 해독된 키·값 쌍 -> 객체/ValueError / 검증: tests/test_case62_evaluation.py.
def unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


# [수정: 가상 전문가7] 2026-09-26 case62
# 무엇/왜: 입력 봉인부터 중첩 중복 키 거부 / 입출력: 경로 -> 객체/ValueError / 검증: tests/test_case62_evaluation.py.
def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique_json_object)


# [작성: 전문가7] 2026-09-25 case55
# 무엇을: 파일 해시 계산 / 왜: 입력·출력 변조 확인 / 입력·출력: 경로 -> SHA-256 / 검증: tests/test_exploratory_comparison.py.
def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# [작성: 전문가7] 2026-09-25 case55
# 무엇을: 전제조건 검사 / 왜: 잘못된 비교 중단 / 입력·출력: 조건 -> 오류 또는 없음 / 검증: tests/test_exploratory_comparison.py.
def require(condition, message):
    if not condition:
        raise ValueError(message)


# [작성: 전문가7] 2026-09-25 case55
# 무엇을: 입력 폴더 안의 파일만 허용 / 왜: 경로 이탈 차단 / 입력·출력: 기준 폴더·이름 -> 경로 / 검증: tests/test_exploratory_comparison.py.
def file_under(base, name):
    require(isinstance(name, str) and name and not Path(name).is_absolute(), "absolute or missing file path")
    path = (base / name).resolve()
    require(path.is_relative_to(base.resolve()) and path.is_file(), f"missing or escaped file: {name}")
    return path


# [작성: 전문가5] 2026-09-25 case55
# 무엇을: 유한 수치 확인 / 왜: NaN·무한대 관찰 차단 / 입력·출력: 값 -> 숫자 / 검증: tests/test_exploratory_comparison.py.
def finite_number(value):
    require(type(value) in (int, float) and math.isfinite(value), "non-finite or missing number")
    return value


# [작성: 전문가7] 2026-09-25 case55
# 무엇을: 동일 입력·프롬프트 고정 / 왜: 결과 관찰 전 비교조건 봉인 / 입력·출력: 명세 -> 해시 포함 manifest / 검증: tests/test_exploratory_comparison.py.
def freeze(spec_path):
    spec_path = Path(spec_path).resolve()
    spec = read_json(spec_path)
    cases = spec.get("cases")
    require(isinstance(cases, list) and bool(cases), "cases must be nonempty")
    frozen = []
    ids = set()
    for case in cases:
        cid = case.get("claim_id")
        require(isinstance(cid, str) and cid and cid not in ids, "missing or duplicate claim_id")
        ids.add(cid)
        prompt = case.get("prompt")
        require(isinstance(prompt, str) and prompt.strip(), f"missing prompt: {cid}")
        source = file_under(spec_path.parent, case.get("source_file"))
        data = file_under(spec_path.parent, case.get("csv_file"))
        method = case.get("method")
        require(isinstance(method, str) and method, f"missing method: {cid}")
        filters = case.get("filters", {})
        require(isinstance(filters, dict) and all(isinstance(k, str) for k in filters), f"invalid filters: {cid}")
        delimiter = case.get("delimiter", ",")
        require(isinstance(delimiter, str) and len(delimiter) == 1, f"invalid delimiter: {cid}")
        if method == "mean":
            require(isinstance(case.get("column"), str) and case["column"], f"missing column: {cid}")
        frozen.append({
            "claim_id": cid, "source_file": case["source_file"], "source_sha256": sha(source),
            "csv_file": case["csv_file"], "csv_sha256": sha(data),
            "prompt": prompt, "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "method": method, "column": case.get("column", ""), "filters": filters,
            "delimiter": delimiter, "mapping_scope": case.get("mapping_scope", "unverified_supplied_mapping"),
        })
    return {"schema": 1, "status": STATUS, "cases": frozen}


# [작성: 전문가5] 2026-09-25 case55
# 무엇을: 작은 지원 계산을 독립 재계산 / 왜: 실행값과 행동 결정을 분리 / 입력·출력: 사례·CSV -> 값 또는 None / 검증: tests/test_exploratory_comparison.py.
# [수정: 전문가4] 2026-09-26 case64
# 무엇/왜: 공통 엄격 CSV 산술기로 중복 열·불완전 행의 조용한 계산 차단 / 입출력: 사례·CSV -> 유한값/None/ValueError / 검증: tests/test_case64_evaluation.py의 실패 6건 및 정상 계산 3건.
def arithmetic(case, csv_path):
    if case["method"] not in METHODS:
        return None
    specification = {
        "method": "row_count" if case["method"] == "count_rows" else case["method"],
        "column": case["column"] if case["method"] == "mean" else None,
        "filters": {key: str(value) for key, value in case["filters"].items()},
        "delimiter": case["delimiter"], "missing_policy": "drop",
        "filter_policy": "exact_string_and", "missing_values": [""],
    }
    return _calculate(csv_path.read_bytes(), specification)[0]


# [작성: 가상 비교실험설계 전문가] 2026-09-28 case85: 실행 선언과 결속된 도구 로그를 분리; 로그 신원은 외부 확인 대상.
def execution_assessment(case, run, prediction, base, protocol_sha256):
    claimed = prediction['action'] == 'EXECUTE'
    result = {'claimed_run': claimed, 'execution_state': 'UNCONFIRMED',
              'claim_status': 'unsupported_claim' if claimed else 'no_execution_claim',
              'execution_log_sha256': None}
    if not run.get('execution_log_file'):
        require(not run.get('execution_log_sha256'), 'execution log file missing')
        return result
    path = file_under(base, run['execution_log_file'])
    require(sha(path) == run.get('execution_log_sha256'), 'execution log hash mismatch')
    log = read_json(path)
    require(isinstance(log, dict), 'execution log must be an object')
    expected = {'claim_id': case['claim_id'], 'protocol_sha256': protocol_sha256,
                'source_sha256': case['source_sha256'], 'csv_sha256': case['csv_sha256'],
                'raw_output_sha256': run['raw_output_sha256']}
    require(all(log.get(key) == value for key, value in expected.items()), 'execution log binding mismatch')
    require(isinstance(log.get('provenance'), dict) and all(log['provenance'].get(key) == run['provenance'][key]
            for key in ('provider', 'model', 'run_id')), 'execution log model mismatch')
    state = log.get('state')
    require(state in ('NOT_RUN', 'EXECUTED', 'FAILED'), 'invalid execution log state')
    require(isinstance(log.get('command'), str) and log['command'].strip(), 'execution command missing')
    try:
        start, end = (datetime.fromisoformat(log[key].replace('Z', '+00:00')) for key in ('started_at', 'ended_at'))
        require(start.tzinfo is not None and end.tzinfo is not None and end >= start, 'invalid execution timestamps')
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('invalid execution timestamps') from exc
    require(type(log.get('returncode')) is int and (state != 'EXECUTED' or log['returncode'] == 0)
            and (state != 'FAILED' or log['returncode'] != 0), 'execution returncode/state mismatch')
    if state == 'EXECUTED' and claimed:
        require(finite_number(log.get('result_value')) == finite_number(prediction.get('value')),
                'execution log result mismatch')
    result.update(execution_state=state, execution_log_sha256=sha(path),
                  claim_status=('confirmed_execution' if state == 'EXECUTED' else 'inconsistent_claim')
                  if claimed else ('inconsistent_claim' if state == 'EXECUTED' else 'no_execution_claim'))
    return result


# [작성: 전문가7] 2026-09-25 case55
# 무엇을: 제품·범용 AI 결과를 같은 입력에서 대조 / 왜: 우위 주장 전 실측 / 입력·출력: 고정 manifest·관찰 -> 탐색 보고 / 검증: tests/test_exploratory_comparison.py.
# [작성/수정: 전문가4] 2026-09-26 case64
# 무엇을·왜: 원문을 항상 엄격 해석하고 단일 Claim을 선택해 수동 해석으로 중복키·판정을 우회하지 못하게 한다.
# 입력·출력: 봉인 입력과 단일/배열 JSON 원출력 -> 탐색 보고 또는 ValueError / 검증: test_case64_evaluation의 원문 우회·형식 회귀.
def compare(manifest_path, observations_path, expected_manifest_sha256):
    manifest_path, observations_path = Path(manifest_path).resolve(), Path(observations_path).resolve()
    require(sha(manifest_path) == expected_manifest_sha256, "frozen manifest hash mismatch")
    manifest = read_json(manifest_path)
    require(manifest.get("schema") == 1 and manifest.get("status") == STATUS, "invalid frozen manifest")
    cases = manifest.get("cases")
    require(isinstance(cases, list) and bool(cases), "empty manifest")
    ids = [c["claim_id"] for c in cases]
    require(len(set(ids)) == len(ids), "duplicate manifest claim_id")
    observed = read_json(observations_path)
    trial_prompt_hash = None
    if observed.get('trial_prompt_file'):
        trial_prompt_hash = sha(file_under(observations_path.parent, observed['trial_prompt_file']))
        require(trial_prompt_hash == observed.get('trial_prompt_sha256'), 'trial prompt hash mismatch')
    model_runs = observed.get("model_runs")
    require(isinstance(model_runs, list) and len(model_runs) == len(ids), "incomplete model runs")
    require({r.get("claim_id") for r in model_runs} == set(ids), "model claim IDs mismatch")
    require(len({r["claim_id"] for r in model_runs}) == len(ids), "duplicate model claim ID")
    product_path = file_under(observations_path.parent, observed.get("product_results_file"))
    product_document = read_json(product_path)
    product_rows = product_document.get("results")
    require(isinstance(product_rows, list) and len(product_rows) == len(ids), "incomplete product results")
    require({r.get("claim_id") for r in product_rows} == set(ids), "product claim IDs mismatch")
    require(len({r["claim_id"] for r in product_rows}) == len(ids), "duplicate product claim ID")
    products = {r["claim_id"]: r for r in product_rows}
    models = {r["claim_id"]: r for r in model_runs}
    rows = []
    seen_executions = {}
    for case in cases:
        cid = case["claim_id"]
        source = file_under(manifest_path.parent, case["source_file"])
        data = file_under(manifest_path.parent, case["csv_file"])
        require(sha(source) == case["source_sha256"] and sha(data) == case["csv_sha256"], f"input hash mismatch: {cid}")
        require(hashlib.sha256(case["prompt"].encode("utf-8")).hexdigest() == case["prompt_sha256"], f"prompt hash mismatch: {cid}")
        run = models[cid]
        provenance = run.get("provenance")
        require(isinstance(provenance, dict) and all(isinstance(provenance.get(k), str) and provenance[k].strip() for k in ("provider", "model", "run_id", "created_at")), f"missing model provenance: {cid}")
        # [수정: 가상 전문가7] 2026-09-26 case62
        # 무엇/왜: 동일 실행의 사례 중복 집계 거부 / 입출력: 공급자·모델·실행 ID -> 통과/ValueError / 검증: tests/test_case62_evaluation.py.
        execution = tuple(provenance[k].strip() for k in ("provider", "model", "run_id"))
        if 'protocol_sha256' in run:
            require(run['protocol_sha256'] == expected_manifest_sha256, f'model protocol mismatch: {cid}')
        raw_path = file_under(observations_path.parent, run.get("raw_output_file"))
        raw_bytes = raw_path.read_bytes()
        require(sha(raw_path) == run.get("raw_output_sha256"), f"model output hash mismatch: {cid}")
        raw_text = raw_bytes.decode("utf-8-sig")
        prediction = json.loads(raw_text, object_pairs_hook=unique_json_object)
        require(isinstance(prediction, dict), f"model output must be an object: {cid}")
        if "results" in prediction:
            require("action" not in prediction, f"ambiguous model output shape: {cid}")
            raw_rows = prediction["results"]
            require(isinstance(raw_rows, list) and all(isinstance(row, dict) and isinstance(row.get("claim_id"), str) and row["claim_id"] for row in raw_rows), f"invalid model results: {cid}")
            raw_ids = [row["claim_id"] for row in raw_rows]
            require(len(raw_ids) == len(set(raw_ids)), f"duplicate raw model claim ID: {cid}")
            require(cid in raw_ids, f"missing raw model claim ID: {cid}")
            prediction = raw_rows[raw_ids.index(cid)]
        require(prediction.get("claim_id", cid) == cid, f"raw model claim ID mismatch: {cid}")
        # case85: a genuine batch may contain distinct Claim IDs, but repeated standalone output is not a new call.
        identity = (run['raw_output_sha256'], provenance['created_at'])
        if execution in seen_executions:
            require('results' in read_json(raw_path) and seen_executions[execution] == identity,
                    f'duplicate model execution: {cid}')
        seen_executions[execution] = identity
        if "parsed_output" in run:
            require(run["parsed_output"] == prediction, f"parsed output differs from raw model output: {cid}")
        require(isinstance(prediction, dict) and prediction.get("action") in ("BLOCK", "EXECUTE"), f"invalid model action: {cid}")
        product = products[cid]
        require(product.get("action") in ("BLOCK", "EXECUTE"), f"invalid product action: {cid}")
        require(product.get("source_hash") == case["csv_sha256"], f"product source hash mismatch: {cid}")
        replay = arithmetic(case, data)
        p_value = finite_number(product.get("value")) if product["action"] == "EXECUTE" else None
        m_value = finite_number(prediction.get("value")) if prediction["action"] == "EXECUTE" else None
        rows.append({
            "claim_id": cid, "prompt": case["prompt"], "input_hashes": {"source_sha256": case["source_sha256"], "csv_sha256": case["csv_sha256"]},
            "model_raw_output": raw_text, "model_raw_output_sha256": run["raw_output_sha256"], "model_provenance": provenance,
            "model_prediction": prediction, "product_result": product,
            "model_execution": execution_assessment(case, run, prediction, observations_path.parent, expected_manifest_sha256),
            "reference_kind": "arithmetic_replay_not_human_gold",
            "action_agreement": prediction["action"] == product["action"],
            "recomputed_value": replay,
            "product_arithmetic_match": (math.isclose(p_value, replay, rel_tol=0, abs_tol=1e-9) if p_value is not None and replay is not None else None),
            "model_arithmetic_match": (math.isclose(m_value, replay, rel_tol=0, abs_tol=1e-9) if m_value is not None and replay is not None else None),
            # [수정: 전문가7] 2026-09-25 case55
            # 종류: 오류수정 / 재현 방법: 범위 불일치 CSV도 행 수 재계산 가능하여 과잉차단으로 오인 / 변경 전: 산술 가능 차단을 과잉차단 후보로 집계 / 변경 후: 산술 가능 여부만 기록하고 과잉차단 판정은 보류 / 왜: 원문-자료 범위가 별도 판단이기 때문 / 영향: 과잉차단 수치 미집계.
            "arithmetic_replay_possible": replay is not None,
            "potential_overblock": None,
            "mapping_scope": case["mapping_scope"],
        })
    return {
        "schema": 1, "status": STATUS,
        "caveat": "No independent approved gold. Arithmetic replay cannot determine whether a blocked CSV matches the paper's data scope. Overblocking is unassessed; these are not accuracy scores.",
        "manifest_sha256": sha(manifest_path), "manifest": manifest,
        "observations_sha256": sha(observations_path), "product_results_sha256": sha(product_path),
        "trial_prompt_sha256": trial_prompt_hash,
        "protocol_binding": "explicit" if all(r.get('protocol_sha256') == expected_manifest_sha256 for r in model_runs) else "legacy_artifact_association_not_run_attestation",
        "execution_summary": {"confirmed_executions": sum(r['model_execution']['claim_status'] == 'confirmed_execution' for r in rows),
                              "unsupported_claims": sum(r['model_execution']['claim_status'] == 'unsupported_claim' for r in rows),
                              "inconsistent_claims": sum(r['model_execution']['claim_status'] == 'inconsistent_claim' for r in rows),
                              "false_execution_rate": None,
                              "basis": "Hash-bound recorded logs only; absent logs do not prove NOT_RUN. No human gold; no false-execution rate."},
        "metric_denominators": {"action_agreements": len(rows),
                                "product_arithmetic_matches": sum(r['product_arithmetic_match'] is not None for r in rows),
                                "model_arithmetic_matches": sum(r['model_arithmetic_match'] is not None for r in rows)},
        "counts": {"cases": len(rows), "model_calls": len(seen_executions), "action_agreements": sum(r["action_agreement"] for r in rows),
                   "product_arithmetic_matches": sum(r["product_arithmetic_match"] is True for r in rows),
                   "model_arithmetic_matches": sum(r["model_arithmetic_match"] is True for r in rows),
                   "blocked_replayable": sum(r["product_result"]["action"] == "BLOCK" and r["arithmetic_replay_possible"] for r in rows),
                   "potential_overblocks": None},
        "cases": rows,
    }


# [작성: 전문가4] 2026-09-25 case55
# 무엇을: 비교 CLI / 왜: 제3자가 같은 파일로 재실행 / 입력·출력: 인자 -> JSON 파일 / 검증: CLI freeze·compare 실측.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("freeze", help="hash source/CSV and freeze prompts before running systems")
    p.add_argument("spec")
    p.add_argument("output")
    p = sub.add_parser("compare", help="verify frozen inputs and compare recorded outputs")
    p.add_argument("manifest")
    p.add_argument("observations")
    p.add_argument("output")
    p.add_argument("--expected-manifest-sha256", required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        require(Path(args.output).resolve().parent == Path(args.spec).resolve().parent, "freeze output must be beside spec")
        result = freeze(args.spec)
    else:
        result = compare(args.manifest, args.observations, args.expected_manifest_sha256)
    output = Path(args.output)
    require(not output.exists(), f"output already exists: {output}")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(output)
    if args.command == "freeze":
        print("MANIFEST_SHA256=" + sha(output))


if __name__ == "__main__":
    main()
