"""판정 기록: JSON 한 줄씩 추가만 한다. 기존 줄은 고치거나 지우지 않는다."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))


def now_kst():
    return datetime.now(KST).isoformat(timespec="seconds")


def append_record(path, result, *, reference_sha256=None):
    """result에 실행 번호와 실제 KST 실행 시각을 붙여 한 줄 추가한다."""
    path = Path(path)
    if path.exists() and not path.is_file():
        raise ValueError("기록 경로가 일반 파일이 아님")
    entry = {"run_id": uuid.uuid4().hex, "executed_at_kst": now_kst(),
             "reference_sha256": reference_sha256, **result}
    line = json.dumps(entry, ensure_ascii=False, sort_keys=True, allow_nan=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size:
        with path.open("rb") as handle:
            handle.seek(-1, 2)
            if handle.read(1) != b"\n":
                raise ValueError("기록 파일 끝이 줄바꿈이 아님: 손상 여부를 먼저 확인해야 함")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return entry


def read_records(path):
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def reusable_result(path, spec_sha256, data_sha256, reference_sha256=None):
    """명세·자료(·기준) 지문이 모두 같은 가장 최근 기록. 하나라도 다르면 None."""
    for entry in reversed(read_records(path)):
        if (entry.get("spec_sha256") == spec_sha256 and entry.get("data_sha256") == data_sha256
                and entry.get("reference_sha256") == reference_sha256):
            return entry
    return None
