"""사례 A2 시연: 저자 공개 파일로 행 대응 차단 → 사람 승인 재정렬 → 기록.

python -m evidence_gate.demo_a2 --workdir 작업폴더 [--record 기록.jsonl] [--approver 이름]

저자 저장소에 라이선스 파일이 없어 자료는 저장소에 넣지 않는다. 실행할 때 고정 커밋에서 받아
작업 폴더에만 두고, 전체 SHA-256이 다르면 멈춘다. 상태 3~5의 변형은 메모리 사본에서만 만든다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

from .gate import evaluate
from .nexus import tip_labels
from .record import append_record, now_kst, reusable_result

ROOT = Path(__file__).resolve().parent
COMMIT = "0217d9d103fe5829329e7abab3df08f11c6b88ac"
BASE = f"https://raw.githubusercontent.com/AndersonDrew/Primate_ARE/{COMMIT}/"
FILES = {
    "S5-primdfall.csv": ("Supplemental_Table/S5-primdfall.csv",
                         "b40a0d3a6178bacc330e22712d841f26ba5234badc3a6e60ca97525345ab8ece"),
    "treeall.nex": ("StuffUsed/treeall.nex",
                    "85abccce8dcf2437f17f2566dd01f84b84ba6fda8e4d5fec96c43368a4d0659f"),
}
NOTICE = ("철회 공지(2023-11-24, 부정행위 아님)의 원인 유형을 저자 공개 파일로 재구성한 시연이며, "
          "원 논문 계통 통계 모델의 재현은 아님.")


def fetch(workdir, download=True):
    """작업 폴더의 두 파일 바이트. 없으면 받고, 지문이 다르면 멈춘다."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    blobs = {}
    for name, (path, expected) in FILES.items():
        target = workdir / name
        if not target.exists():
            if not download:
                raise FileNotFoundError(target)
            with urllib.request.urlopen(BASE + path, timeout=30) as response:
                target.write_bytes(response.read())
        raw = target.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected:
            raise SystemExit(f"{name}: 지문 불일치({actual}). 고정 커밋 자료가 아니므로 중단")
        blobs[name] = raw
    return blobs


def _without_line(data, predicate):
    lines = data.decode("utf-8").split("\n")
    return "\n".join([lines[0]] + [l for l in lines[1:] if not predicate(l)]).encode("utf-8")


def run(blobs, approver, record=None):
    spec = json.loads((ROOT / "examples" / "a2_primate_alignment.spec.json").read_text(encoding="utf-8"))
    data, tree = blobs["S5-primdfall.csv"], blobs["treeall.nex"]
    reference = tip_labels(tree.decode("utf-8"))
    tree_sha = hashlib.sha256(tree).hexdigest()
    states = []

    def step(name, spec_used, data_used, approvals=None):
        result = evaluate(spec_used, data_used, reference_ids=reference, approvals=approvals)
        result = dict(result, demo_state=name, demo_notice=NOTICE)
        if record:
            prior = reusable_result(record, result["spec_sha256"], result["data_sha256"], tree_sha)
            result["prior_run_same_inputs"] = prior["run_id"] if prior else None
            result = append_record(record, result, reference_sha256=tree_sha)
        states.append(result)
        return result

    step("1_원본_그대로", spec, data)
    first = reference[0]
    approval = {"approver": approver, "basis": "Species 열 이름 기준 재정렬", "approved_at_kst": now_kst(),
                "data_sha256": spec["data_fingerprint"],
                # [수정: 0 이영 · Claude] 2026-09-30 23:51 KST — 시연 승인도 기준 목록 지문에 묶어 기준이 바뀌면 이전 승인을 쓰지 못하게 한다.
                "reference_sha256": hashlib.sha256("\n".join(reference).encode("utf-8")).hexdigest()}
    step("2_사람_승인_재정렬", spec, data, {"reorder": approval})

    dropped = _without_line(data, lambda line: line.startswith(first + ","))
    step("3_합성_한종_삭제", dict(spec, data_fingerprint=hashlib.sha256(dropped).hexdigest()), dropped)
    duplicate_line = next(l for l in data.decode("utf-8").split("\n") if l.startswith(first + ","))
    duplicated = data.rstrip(b"\n") + b"\n" + duplicate_line.encode("utf-8")
    step("4_합성_한종_복제", dict(spec, data_fingerprint=hashlib.sha256(duplicated).hexdigest()), duplicated)
    changed = data.replace(b"\n", b"\r\n")
    step("5_자료_바이트_변경_뒤_이전_승인", spec, changed, {"reorder": approval})
    return states


def summary(states):
    lines = []
    for s in states:
        d = s.get("details", {})
        extra = ""
        if s["reason_code"] == "ROW_ORDER_REORDER_REQUIRED":
            first = d["order_differences"][0]
            extra = (f"순서 다른 위치 {d['order_differences_count']}/{d['data_count']}곳, 첫 차이 {first['position']}번째: "
                     f"자료 {first['data_id']} ↔ 계통수 {first['reference_id']}")
        elif s["reason_code"] == "ROW_MEMBERSHIP_MISMATCH":
            extra = f"자료에 없음 {d['missing_in_data']}, 중복 {d['duplicates_data']}"
        elif s["reason_code"] == "ROWS_REORDERED_WITH_APPROVAL":
            extra = f"대응표 {len(s['alignment_table'])}행, 승인자 {s['approvals'][-1]['approver']}"
        lines.append(f"{s['demo_state']}: {s['verdict']} {s['reason_code']} {extra}".rstrip())
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="evidence_gate.demo_a2")
    parser.add_argument("--workdir", required=True, type=Path, help="저자 파일을 받을 폴더(저장소 밖 권장)")
    parser.add_argument("--record", type=Path, help="판정 기록 JSONL(추가만)")
    parser.add_argument("--approver", default="시연 연구자", help="상태 2 재정렬 승인자 이름")
    parser.add_argument("--json", action="store_true", help="전체 결과 JSON 출력")
    args = parser.parse_args(argv)
    states = run(fetch(args.workdir), args.approver, args.record)
    print(json.dumps(states, ensure_ascii=False, indent=2) if args.json else NOTICE + "\n" + summary(states))
    return 0


if __name__ == "__main__":
    sys.exit(main())
