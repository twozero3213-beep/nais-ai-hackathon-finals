"""Preregistered internal exploratory comparison; no model calls or human labels created."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics

from tools.compare_exploratory import compare, freeze, sha, require, finite_number, file_under, unique_json_object


# [작성: 가상 전문가7] 2026-09-26 case61 — 비유한 JSON과 잘못된 구조를 입력 경계에서 거부.
def read_document(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    # [작성: 가상 전문가7] 2026-09-26 case61 — 비표준 JSON 상수 거부.
    def reject_constant(value):
        raise ValueError(f"non-finite JSON: {value}")
    # [작성: 가상 전문가5] 2026-09-26 case61 — JSON의 극단 정수가 산술 검증을 넘지 않도록 거부.
    def bounded_integer(value):
        result = int(value)
        try:
            finite_number(result)
        except OverflowError as exc:
            raise ValueError("integer exceeds finite numeric range") from exc
        return result
    # [수정: 가상 전문가7] 2026-09-26 case62
    # 무엇/왜: 라벨·시각·판정 중복 키 덮어쓰기 차단 / 입출력: JSON 원문 -> 객체/ValueError / 검증: tests/test_case62_evaluation.py.
    obj = json.loads(text, parse_constant=reject_constant, parse_int=bounded_integer, object_pairs_hook=unique_json_object)
    # JSON exponent overflow (1e999) is not handled by parse_constant.
    json.dumps(obj, allow_nan=False)
    require(isinstance(obj, dict), "JSON object required")
    return obj


# [작성: 가상 전문가7] 2026-09-26 case61 — 시간대 없는/잘못된 시간 거부, 시각은 자기신고임.
def timestamp(value):
    require(isinstance(value, str), "timestamp required")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    require(result.tzinfo is not None, "timezone required")
    return result


# [작성: 가상 전문가7] 2026-09-26 case61 — 팀 역할·개발 관여를 공개하고 정답/실행 전 고정 선언 확인.
def validate_protocol(protocol):
    require(isinstance(protocol, dict), "internal_protocol required")
    require(protocol.get("labels_and_runs_not_started") is True, "freeze before labels and runs")
    require(isinstance(protocol.get("decision_rubric"), str) and protocol["decision_rubric"].strip(), "decision rubric required")
    descriptions = protocol.get("system_descriptions")
    require(isinstance(descriptions, dict) and set(descriptions) == {"product", "model"} and all(isinstance(v, str) and v.strip() for v in descriptions.values()), "two system descriptions required")
    reviewers = protocol.get("reviewers")
    require(isinstance(reviewers, list) and reviewers, "human reviewer role disclosures required")
    ids = []
    for reviewer in reviewers:
        require(isinstance(reviewer, dict), "invalid reviewer")
        require(all(isinstance(reviewer.get(k), str) and reviewer[k].strip() for k in ("reviewer_id", "role")), "reviewer id and role required")
        require(type(reviewer.get("developer_involvement")) is bool, "developer involvement disclosure required")
        ids.append(reviewer["reviewer_id"])
    require(len(set(ids)) == len(ids), "duplicate reviewers")
    return set(ids)


# [작성: 가상 전문가7] 2026-09-26 case61 — 기존 입력 봉인을 재사용하며 내부 평가 규칙과 현재 시각 고정.
def freeze_internal(spec_path):
    spec = read_document(spec_path)
    protocol = spec.get("internal_protocol")
    validate_protocol(protocol)
    require(not spec.get("human_labels") and not spec.get("model_runs"), "labels/runs cannot precede freeze")
    require(isinstance(spec.get("cases"), list) and all(isinstance(c, dict) for c in spec["cases"]), "invalid cases")
    result = freeze(spec_path)
    result["internal_protocol"] = protocol
    result["frozen_at"] = datetime.now(timezone.utc).isoformat()
    result["evaluation_tier"] = "INTERNAL_EXPLORATORY"
    return result


# [작성: 가상 전문가7] 2026-09-26 case61 — 같은 프로토콜 해시·입력의 완전한 쌍만 내부 판정, 외부 게이트 유지.
def compare_internal(manifest_path, observations_path, expected_manifest_sha256):
    manifest_path, observations_path = Path(manifest_path), Path(observations_path)
    require(sha(manifest_path) == expected_manifest_sha256, "frozen manifest hash mismatch")
    manifest, observed = read_document(manifest_path), read_document(observations_path)
    require(manifest.get("evaluation_tier") == "INTERNAL_EXPLORATORY", "wrong evaluation tier")
    reviewers = validate_protocol(manifest.get("internal_protocol"))
    frozen_at = timestamp(manifest.get("frozen_at"))
    cases = manifest.get("cases")
    require(isinstance(cases, list) and cases and all(isinstance(c, dict) and isinstance(c.get("claim_id"), str) for c in cases), "invalid frozen cases")
    ids = {c["claim_id"] for c in cases}
    require(len(ids) == len(cases), "duplicate cases")
    labels = observed.get("human_labels", [])
    require(isinstance(labels, list) and all(isinstance(x, dict) for x in labels), "invalid human labels")
    if not labels:
        return {"status": "NOT_SCORED", "evaluation_tier": "INTERNAL_EXPLORATORY", "reason": "PENDING_REAL_HUMAN_LABELS", "protocol_sha256": expected_manifest_sha256}
    require(all(isinstance(x.get("claim_id"), str) for x in labels), "invalid label IDs")
    require(len(labels) == len(ids) and {x["claim_id"] for x in labels} == ids, "complete unique labels required")
    gold = {x["claim_id"]: x for x in labels}
    for case in cases:
        label = gold[case["claim_id"]]
        require(label.get("human_attestation") is True and label.get("blind_to_outputs") is True, "genuine blinded human record required")
        require(isinstance(label.get("reviewer_id"), str) and label["reviewer_id"] in reviewers, "undisclosed reviewer")
        require(label.get("protocol_sha256") == expected_manifest_sha256 and label.get("source_hash") == case.get("csv_sha256"), "label protocol/input mismatch")
        require(timestamp(label.get("reviewed_at")) > frozen_at, "label predates protocol freeze")
        require(all(isinstance(label.get(k), str) and label[k].strip() for k in ("source_location", "rationale")), "label evidence required")
        require(label.get("expected_action") in ("BLOCK", "EXECUTE"), "invalid expected action")
        require(finite_number(label.get("tolerance")) >= 0, "negative tolerance")
        if label["expected_action"] == "EXECUTE":
            finite_number(label.get("expected_value"))
        else:
            require(label.get("expected_value") is None, "blocked label must not carry value")
        data = file_under(manifest_path.parent, case.get("csv_file"))
        with data.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=case.get("delimiter", ","))
            require(reader.fieldnames and len(set(reader.fieldnames)) == len(reader.fieldnames), "invalid CSV header")
            require(all(None not in row and None not in row.values() for row in reader), "malformed CSV row")
    last_label_at = max(timestamp(label["reviewed_at"]) for label in labels)
    product = read_document(file_under(observations_path.parent, observed.get("product_results_file")))
    model_runs, product_runs = observed.get("model_runs"), product.get("results")
    run_times = {}
    for name, runs in (("model", model_runs), ("product", product_runs)):
        require(isinstance(runs, list) and all(isinstance(r, dict) for r in runs), "invalid runs")
        require(all(isinstance(r.get("claim_id"), str) for r in runs), "invalid run IDs")
        require(len(runs) == len(ids) and {r["claim_id"] for r in runs} == ids, "complete paired runs required")
        for run in runs:
            require(run.get("protocol_sha256") == expected_manifest_sha256, "run protocol mismatch")
            provenance = run.get("provenance") if name == "model" else run
            require(isinstance(provenance, dict), "invalid provenance")
            require(timestamp(provenance.get("created_at")) > last_label_at, "all human labels must precede runs")
            run_times[(name, run["claim_id"])] = timestamp(provenance["created_at"])
            if name == "model":
                require("parsed_output" not in run, "use raw JSON output; manual parsing is not preregistered")
                read_document(file_under(observations_path.parent, run.get("raw_output_file")))
    comparison = compare(manifest_path, observations_path, expected_manifest_sha256)
    records = observed.get("human_review_records", [])
    require(isinstance(records, list) and all(isinstance(r, dict) for r in records), "invalid human review records")
    seen, times = set(), {"product": [], "model": []}
    for record in records:
        system, cid = record.get("system"), record.get("claim_id")
        require(isinstance(system, str) and isinstance(cid, str) and system in times and cid in ids and (system, cid) not in seen, "invalid or duplicate review timing")
        seen.add((system, cid))
        require(record.get("human_attestation") is True and record.get("kind") == "human_review" and isinstance(record.get("reviewer_id"), str) and record["reviewer_id"] in reviewers, "genuine human review time required")
        require(record.get("protocol_sha256") == expected_manifest_sha256 and isinstance(record.get("record_ref"), str) and record["record_ref"].strip(), "review timing evidence required")
        start, end = timestamp(record.get("started_at")), timestamp(record.get("ended_at"))
        require(start >= run_times[(system, cid)], "review precedes corresponding run")
        seconds = finite_number(record.get("seconds"))
        require(start > frozen_at and end >= start and seconds >= 0 and abs((end-start).total_seconds()-seconds) <= .001, "invalid elapsed human review time")
        times[system].append(seconds)
    timing_complete = all(len(values) == len(ids) for values in times.values())
    systems = {}
    blocked = [c for c in ids if gold[c]["expected_action"] == "BLOCK"]
    executable = [c for c in ids if gold[c]["expected_action"] == "EXECUTE"]
    for system, field in (("product", "product_result"), ("model", "model_prediction")):
        predictions = {r["claim_id"]: r[field] for r in comparison["cases"]}
        false_exec = sum(predictions[c]["action"] == "EXECUTE" for c in blocked)
        reproduced = sum(predictions[c]["action"] == "EXECUTE" and abs(predictions[c]["value"]-gold[c]["expected_value"]) <= gold[c]["tolerance"] for c in executable)
        correct = sum(predictions[c]["action"] == gold[c]["expected_action"] for c in ids)
        systems[system] = {"false_execution_rate": false_exec/len(blocked) if blocked else None, "false_execution_numerator": false_exec, "false_execution_denominator": len(blocked), "decision_accuracy": correct/len(ids), "decision_denominator": len(ids), "numeric_reproduction_rate": reproduced/len(executable) if executable else None, "numeric_reproduction_denominator": len(executable), "review_seconds_median": statistics.median(times[system]) if timing_complete else None, "review_time_n": len(times[system]), "review_time_total_cases": len(ids), "review_time_paired_complete": timing_complete}
    return {"status": "INTERNAL_EXPLORATORY_SCORED", "evaluation_tier": "INTERNAL_EXPLORATORY", "protocol_sha256": expected_manifest_sha256, "developer_bias_disclosed": any(r["developer_involvement"] for r in manifest["internal_protocol"]["reviewers"]), "reviewers": manifest["internal_protocol"]["reviewers"], "assurance": "Self-reported human records; identity, chronology and blinding are not independently verified. No external validation or superiority claim.", "systems": systems, "arithmetic_observations": comparison}


# [작성: 가상 전문가4] 2026-09-26 case61 — 별도 CLI로 내부 계층을 명시, 덮어쓰기 방지.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("freeze")
    p.add_argument("spec")
    p.add_argument("output")
    p = sub.add_parser("compare")
    p.add_argument("manifest")
    p.add_argument("observations")
    p.add_argument("output")
    p.add_argument("--expected-manifest-sha256", required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        require(Path(args.output).resolve().parent == Path(args.spec).resolve().parent, "freeze output must be beside spec")
        result = freeze_internal(args.spec)
    else:
        result = compare_internal(args.manifest, args.observations, args.expected_manifest_sha256)
    with Path(args.output).open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(args.output)
    if args.command == "freeze":
        print("MANIFEST_SHA256=" + sha(args.output))


if __name__ == "__main__":
    main()
