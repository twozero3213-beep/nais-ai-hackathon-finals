"""명령행: python -m evidence_gate check --spec 명세.json --data 자료.csv [--record 기록.jsonl]

종료 코드: 0 MATCH, 2 MISMATCH·NEEDS_REVIEW, 3 BLOCK.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .gate import evaluate
from .nexus import NexusError, tip_labels
from .record import append_record, now_kst, reusable_result

EXIT = {"MATCH": 0, "MISMATCH": 2, "NEEDS_REVIEW": 2, "BLOCK": 3}


def _strict_json(text):
    # [수정: 0 이영 · Claude] 2026-09-30 23:51 KST — json.loads 기본값은 중복 키(마지막 값이 이김)와 NaN을 조용히 받아들여, 숨은 두 번째 tolerance로 MATCH를 만들 수 있었다.
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"중복 키: {key}")
            result[key] = value
        return result

    def refuse(constant):
        raise ValueError(f"허용되지 않는 값: {constant}")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=refuse)


def _blocked(reason, message):
    print(json.dumps({"verdict": "BLOCK", "reason_code": reason, "message": message}, ensure_ascii=False, indent=2))
    return EXIT["BLOCK"]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="evidence_gate")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="명세와 자료로 결정론적 재계산·판정")
    check.add_argument("--spec", required=True, type=Path)
    check.add_argument("--data", required=True, type=Path)
    check.add_argument("--reference-ids", type=Path, help="row_alignment 기준 식별자(한 줄에 하나)")
    check.add_argument("--reference-nexus", type=Path, help="row_alignment 기준: NEXUS 계통수의 끝 이름 목록")
    check.add_argument("--approve-reorder", action="store_true", help="식별자 기준 재정렬 승인(사람이 직접 입력)")
    check.add_argument("--approve-normalize", action="append", default=[], metavar="자료값=기준값",
                       help="제시된 표기 변환 후보 하나를 승인. 여러 번 쓸 수 있음")
    check.add_argument("--approver", help="승인한 사람")
    check.add_argument("--approval-basis", help="승인 근거")
    check.add_argument("--record", type=Path, help="판정 기록 JSONL(추가만)")
    args = parser.parse_args(argv)

    try:
        spec = _strict_json(args.spec.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        return _blocked("SPEC_JSON_INVALID", f"명세 JSON을 읽을 수 없음: {exc}")
    data = args.data.read_bytes()
    reference_ids, reference_sha = None, None
    if args.reference_ids and args.reference_nexus:
        parser.error("--reference-ids와 --reference-nexus는 하나만 씀")
    if args.reference_ids or args.reference_nexus:
        raw = (args.reference_ids or args.reference_nexus).read_bytes()
        reference_sha = hashlib.sha256(raw).hexdigest()
        try:
            text = raw.decode("utf-8")
            reference_ids = tip_labels(text) if args.reference_nexus else [line for line in text.splitlines() if line.strip()]
        except (NexusError, UnicodeError) as exc:
            return _blocked("REFERENCE_INVALID", f"기준 식별자를 읽을 수 없음: {exc}")
    approvals = {}
    if args.approve_reorder or args.approve_normalize:
        if not (args.approver and args.approval_basis):
            parser.error("승인에는 --approver와 --approval-basis가 모두 필요")
        common = {"approver": args.approver, "basis": args.approval_basis, "approved_at_kst": now_kst(),
                  "data_sha256": hashlib.sha256(data).hexdigest()}
        if reference_ids is not None:  # [수정: 0 이영 · Claude] 2026-09-30 23:51 KST — 이 실행에서 만든 승인을 이 자료·기준 목록에 묶는다(gate가 쓰는 정의와 같음)
            common["reference_sha256"] = hashlib.sha256("\n".join(reference_ids).encode("utf-8")).hexdigest()
        if args.approve_reorder:
            approvals["reorder"] = dict(common)
        if args.approve_normalize:
            pairs = [dict(zip(("from", "to"), item.split("=", 1))) for item in args.approve_normalize]
            approvals["normalize"] = dict(common, pairs=pairs)

    result = evaluate(spec, data, reference_ids=reference_ids, approvals=approvals)
    if args.record:
        prior = reusable_result(args.record, result["spec_sha256"], result["data_sha256"], reference_sha)
        result["prior_run_same_inputs"] = prior["run_id"] if prior else None
        result = append_record(args.record, result, reference_sha256=reference_sha)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return EXIT[result["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
