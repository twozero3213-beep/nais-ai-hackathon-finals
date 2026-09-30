"""Check exact registered evidence bytes, optionally against the staged Git index."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


# [작성: 전문가8] 2026-09-26 case61
# 무엇을: 원자료·원문 참조의 로컬/스테이지 지문 확인 / 왜: 로컬 시험 통과 후 배포 줄바꿈 변경으로 차단되는 문제 사전 탐지 / 입력·출력: root·manifest 목록·git_index -> 검사 결과 / 검증: test_case61_release_assets 정상·변조·경로·Git 변환.
def check_assets(root, manifests, *, git_index=False):
    root = Path(root).resolve()
    errors, checked = [], set()
    for manifest in manifests:
        path = Path(manifest)
        path = (path if path.is_absolute() else root / path).resolve()
        try:
            if not path.is_relative_to(root):
                raise ValueError("manifest outside project")
            # [작성/수정: 전문가5·6] 2026-09-26 case61
            # 무엇을: manifest 자체의 스테이지 바이트 검사 / 왜: 로컬만 고친 지문으로 배포 검사를 통과하지 못하게 함.
            # 입력·출력: 로컬/index manifest -> 불일치 또는 누락 오류 / 검증: test_release_assets_reject_unstaged_manifest_fix.
            manifest_raw = path.read_bytes()
            if git_index:
                manifest_name = path.relative_to(root).as_posix()
                staged_manifest = subprocess.run(["git", "-C", str(root), "show", ":" + manifest_name], capture_output=True, timeout=20)
                if staged_manifest.returncode or staged_manifest.stdout != manifest_raw:
                    errors.append(f"git index manifest mismatch or missing: {manifest_name}")
            rows = json.loads(manifest_raw)["cases"]
            if not isinstance(rows, list) or not rows:
                raise ValueError("empty or invalid cases")
            for row in rows:
                for field, hash_field in (("source_file", "source_sha256"), ("data_file", "data_sha256")):
                    if field not in row and hash_field not in row:
                        continue
                    relative, expected = row.get(field), row.get(hash_field)
                    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
                        raise ValueError("missing or absolute asset path")
                    asset = (root / relative).resolve()
                    if not asset.is_relative_to(root):
                        raise ValueError("asset outside project")
                    name = asset.relative_to(root).as_posix()
                    if not isinstance(expected, str) or len(expected) != 64:
                        raise ValueError(f"invalid SHA-256: {name}")
                    raw = asset.read_bytes()
                    if hashlib.sha256(raw).hexdigest() != expected:
                        errors.append(f"local digest mismatch: {name}")
                    if git_index:
                        staged = subprocess.run(["git", "-C", str(root), "show", ":" + name], capture_output=True, timeout=20)
                        if staged.returncode or hashlib.sha256(staged.stdout).hexdigest() != expected:
                            errors.append(f"git index digest mismatch or missing asset: {name}")
                    checked.add(name)
        except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired) as error:
            errors.append(f"{path.name}: {type(error).__name__}: {error}")
    if not checked and not errors:
        errors.append("no registered assets")
    return {"ok": not errors, "checked_assets": len(checked), "git_index_checked": git_index,
            "errors": sorted(set(errors)), "scope": "exact bytes only; not source identity, semantic mapping or human approval"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", action="append", default=None)
    parser.add_argument("--git-index", action="store_true")
    args = parser.parse_args()
    result = check_assets(args.root, args.manifest or ["data/evaluation/cases.json", "data/evaluation/registered_cases.json"], git_index=args.git_index)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)
