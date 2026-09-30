"""현재 추적 파일을 편입 매니페스트의 공개 지문과 대조해 세 갈래로 나눈다(읽기 전용). 사용: python tools/provenance_survey.py [저장소 루트]

# [작성: 0 이영 · Claude] 작성 시각 미확인; 03 검토 2026-10-01T02:36:15+09:00 — docs/0_이영_출처기록.md의 분류표를 누구나 다시 계산할 수 있게 한다.
# 분류 기준은 docs/intake 매니페스트의 public_path·public_copy_sha256 하나뿐이다. '매니페스트에 없음'이 본선 중 작성을 증명하지는 않는다.
# 지문은 HEAD의 blob 바이트로 계산해 작업 트리의 줄바꿈 변환(autocrlf)에 영향을 받지 않는다.
"""
from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path
import subprocess
import sys

MANIFESTS = ("docs/intake/0_이영_case105_import_manifest.json", "docs/intake/0_이영_case105_import_manifest_2.json")
SAME, CHANGED, ABSENT = "편입과 같음", "편입 뒤 수정", "매니페스트에 없음"


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True).stdout


def public_fingerprints(root: Path) -> dict[str, str]:
    """공개 저장소에 넣은 편입 파일의 경로 → 공개 사본 SHA-256."""
    result = {}
    for name in MANIFESTS:
        for entry in json.loads((root / name).read_text(encoding="utf-8"))["files"]:
            if entry.get("public_path"):
                result[entry["public_path"]] = entry["public_copy_sha256"]
    return result


def classify(root: Path) -> collections.defaultdict:
    imported = public_fingerprints(root)
    table = collections.defaultdict(collections.Counter)
    for raw in git(root, "ls-files", "-z").split(b"\0"):
        if not raw:
            continue
        name = raw.decode("utf-8")
        digest = hashlib.sha256(git(root, "show", f"HEAD:{name}")).hexdigest()
        kind = ABSENT if name not in imported else (SAME if imported[name] == digest else CHANGED)
        table[name.split("/")[0] if "/" in name else "(루트 파일)"][kind] += 1
    return table


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    table = classify(root)
    total = collections.Counter()
    print(f"{'폴더':24s}{SAME:>10s}{CHANGED:>10s}{ABSENT:>14s}")
    for folder, counts in sorted(table.items(), key=lambda item: -sum(item[1].values())):
        print(f"{folder:24s}{counts[SAME]:>10d}{counts[CHANGED]:>10d}{counts[ABSENT]:>14d}")
        total.update(counts)
    print(f"{'합계':24s}{total[SAME]:>10d}{total[CHANGED]:>10d}{total[ABSENT]:>14d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# [3 조지현 · 2026-10-01T02:36:15+09:00] 원주석의 작성 시각을 확인할 수 없어 미확인으로 표시하고 실제 검토 시각을 기록한다.
