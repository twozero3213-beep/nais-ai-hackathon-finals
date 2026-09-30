"""[0 이영] 본선의 출처가 있는 입력과 통제된 오류 사례를 제공한다."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import unicodedata

import pandas as pd

AGENT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = AGENT_ROOT.parent
for _code_path in (REPO_ROOT, AGENT_ROOT):
    if str(_code_path) not in sys.path:
        sys.path.insert(0, str(_code_path))
# [수정: 0 이영 · Claude] 2026-09-30 23:56 KST — 공급자·모델 이름은 finals_provider 한 곳에서만 정한다.
from finals_provider import MODEL, PROVIDER
REGISTRY = REPO_ROOT / "data/evaluation/public_reproduction_cases.json"

# 수정 이유: 정상 자료·통제 오류·근거 부족·입력 변경을 같은 두 원문에 연결한다.
# 변경 CSV는 메모리에서만 만들며 저자의 원본과 BAT ND 자료의 바이트를 보존한다.
_DEFINITIONS = (
    ("NORMAL-PENG-ROWS", "정상 · 펭귄 344개체", "normal", "PENG-RAW-ROWS", None),
    ("NORMAL-BAT-MEAN", "정상 · BAT 양성 평균 연령", "normal", "BAT-POSITIVE-MEAN-AGE", None),
    ("MISMATCH-PENG-DROP1", "수치 불일치 · 펭귄 한 행 누락", "mismatch", "PENG-RAW-ROWS", "drop1"),
    ("MISMATCH-PENG-DROP2", "수치 불일치 · 펭귄 두 행 누락", "mismatch", "PENG-RAW-ROWS", "drop2"),
    ("MISSING-PUBLISHER", "근거 부족 · 발행사 원문 미확보", "evidence_missing", "WINE-RED-N", "source_missing"),
    ("MISSING-MISSING-POLICY", "근거 부족 · 결측 처리 명세 미확정", "evidence_missing", "BAT-POSITIVE-MEAN-AGE", "missing_policy"),
    ("CHANGED-PENG-CSV", "자료 변경 · 등록 결과와 CSV 지문 상이", "data_changed", "PENG-RAW-ROWS", "changed_data"),
    ("CHANGED-BAT-CONTRACT", "명세 변경 · 등록 필터 지문 상이", "data_changed", "BAT-POSITIVE-MEAN-AGE", "changed_contract"),
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


_PUNCTUATION = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "−": "-"})


def text_key(value) -> str:
    """문장 비교용 정규형: 유니코드 NFKC, 따옴표·대시 통일, 연속 공백·줄바꿈을 한 칸으로. 숫자·구조 값은 표준 JSON 그대로.

    # [수정: 0 이영 · Claude] 2026-10-01 00:33 KST — 인용문·주장 문장을 정확 일치로 비교하면 모델이 되풀이하면서 바꾸는 공백·따옴표·한글 정규형(NFC/NFD),
    # PDF 줄바꿈 때문에 내용이 같아도 막혔다. 내용이 다르면 여전히 다른 키가 된다. 열 이름·필터 같은 구조 값에는 쓰지 않는다(정확 일치 유지).
    """
    if isinstance(value, str):
        return " ".join(unicodedata.normalize("NFKC", value).translate(_PUNCTUATION).split())
    return _canonical(value)


def _safe_path(relative: str) -> Path:
    target = (REPO_ROOT / relative).resolve()
    if not target.is_relative_to(REPO_ROOT.resolve()):
        raise ValueError("REGISTERED_PATH_OUTSIDE_AGENT")
    return target


def _registered_claims() -> dict:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8-sig"))
    return {item["claim_id"]: item for item in registry["cases"]}


def _selected_count(frame: pd.DataFrame, filters: dict) -> int:
    # [수정: 0 이영 · Claude] 2026-09-30 23:56 KST — 분모(expected_n)를 등록 자료에서 직접 센다. 기존에는 필터가 있으면 무조건 53으로 적어(BAT 사례의 값)
    # 필터가 있는 새 등록 사례를 추가하면 잘못된 분모가 조용히 들어갔다.
    from core.normalization import filter_mask
    selected = frame
    for column, value in filters.items():
        selected = selected[filter_mask(selected[column], value)]
    return len(selected)


def _proposal(item: dict, expected_n: int) -> dict:
    method = "row_count" if item["method"] == "count_rows" else item["method"]
    filters = [{"column": key, "value": value} for key, value in item["filters"].items()]
    return {
        "claim_text": item["claim_text"], "reported_value": item["reported_value"],
        "source_quote": item["source_quote"], "source_location": item["source_location"],
        "method": method, "column": "__dataset__" if method == "row_count" else item["column"],
        "filters": filters,
        "denominator": {"rule": "filtered_rows" if filters else "all_rows", "expected_n": expected_n},
        "missing_policy": item["missing_policy"], "unit": "years" if method == "mean" else "individuals",
        "tolerance": item["tolerance"],
    }


def list_cases() -> list[dict]:
    return [{"id": cid, "label": label, "category": category} for cid, label, category, _, _ in _DEFINITIONS]


def load_case(case_id: str) -> dict:
    definition = next((row for row in _DEFINITIONS if row[0] == case_id), None)
    if definition is None:
        # 등록 claim_id도 수동 검토에 쓸 수 있으나 비교 8개 모집단에는 추가하지 않는다.
        registered = _registered_claims()
        if case_id not in registered:
            raise ValueError("UNKNOWN_CASE_ID")
        definition = (case_id, registered[case_id]["claim_text"], "normal", case_id, None)
    cid, label, category, registered_id, mutation = definition
    item = deepcopy(_registered_claims()[registered_id])
    data_path, source_path = _safe_path(item["data_file"]), _safe_path(item["source_file"])
    original = data_path.read_bytes()
    source = source_path.read_bytes()
    original_frame = pd.read_csv(io.BytesIO(original), delimiter=item["delimiter"])
    frame = original_frame.copy(deep=True)
    manual = _proposal(item, _selected_count(original_frame, item["filters"]))
    expected = deepcopy(manual)
    if mutation in {"drop1", "drop2", "changed_data"}:
        drop = 2 if mutation == "drop2" else 1
        frame = frame.iloc[:-drop].copy()
    if mutation == "missing_policy":
        manual["missing_policy"] = "unspecified"
    if mutation == "changed_contract":
        manual["filters"] = [{"column": "Readout.bat", "value": "0"}]
    # 수정 이유: 출처 취득일은 관측 사실로 보존하고 새 계산 입력만 별도 지문으로 기록한다.
    input_bytes = original if frame.equals(original_frame) else frame.to_csv(index=False).encode("utf-8")
    source_gate = (
        item.get("source_kind") == "article_extract"
        and _sha(source) == item["source_sha256"]
        and _sha(original) == item["data_sha256"]
        and text_key(item["source_quote"]) in text_key(source.decode("utf-8", errors="replace"))
        and not item.get("evidence_status", "").startswith("BLOCKED")
    )
    return {
        "id": cid, "case_id": cid, "label": label, "category": category,
        "registered_claim_id": registered_id, "source_quote": item["source_quote"],
        "source_location": item["source_location"], "paper_url": item["paper_url"],
        "dataframe": frame, "manual_proposal": manual, "expected_proposal": expected,
        "source": item, "source_gate": bool(source_gate), "data_bytes": input_bytes,
        "input_sha256": _sha(input_bytes), "registered_data_sha256": item["data_sha256"],
        "source_sha256": _sha(source), "mutation": mutation,
        "registered_contract_sha256": _sha(_canonical(expected).encode("utf-8")),
        "original_rows": len(original_frame), "current_rows": len(frame),
        "scope_note": "등록된 원문 수치의 산술 검산만 수행. 저자 코드 실행·논문 전체 재현·사람 승인은 별도 범위.",
    }


def list_replays() -> list[dict]:
    """실제 공급자 영수증이 있는 저장 응답만 선택지로 제공한다."""
    found = []
    directory = AGENT_ROOT / "data/finals/replays"
    if not directory.exists():
        return found
    for path in sorted(directory.glob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8-sig"))
            if item.get("provider") == PROVIDER and item.get("model") == MODEL and not item.get("mock") and str(item.get("request_id", "")).startswith("resp_") and len(str(item.get("raw_sha256", ""))) == 64 and isinstance(item.get("output"), dict):
                found.append({"path": str(path), "label": path.stem})
        except (OSError, ValueError):
            continue
    return found
