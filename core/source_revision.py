"""Source revision and runtime environment manifest for reproducible executions.

case32 REPRODUCIBILITY CHANGE
FAILURE: case31 stored a human-readable engine version but not the exact source revision.
RISK: two different code states could both call themselves ``rule-engine-case31``.
WHY: scientific reproduction requires identifying both the runtime environment and executable source.
CHANGE: always hash executable source and dependency/version files; Git and override are labels only.
REGRESSION: tests/test_case32.py, tests/test_case64_source.py
"""
from __future__ import annotations
import hashlib, os, subprocess
from pathlib import Path
from .paths import PROJECT_ROOT

EXCLUDED_DIRECTORIES = {"__pycache__", ".git", ".venv", "venv", ".pytest_cache", "cache", "logs", "data", "secrets"}

def _git_sha():
    try:
        return subprocess.check_output(["git","rev-parse","HEAD"],cwd=PROJECT_ROOT,stderr=subprocess.DEVNULL,text=True,timeout=2).strip()
    except Exception:
        return ""

# [작성: 전문가4] 2026-09-26 case64
# 무엇/왜: 디렉터리 읽기 실패를 누락으로 처리하지 않음 / 입출력: 파일시스템 오류 -> 같은 오류 전파 / 검증: tests/test_case64_source.py.
def _raise_scan_error(error):
    raise error


# [수정: 전문가4] 2026-09-26 case64
# 무엇/왜: Git·고정 override에도 실제 실행 내용 항상 결속 / 입출력: 실행 트리 -> 정렬된 상대경로·내용 지문과 보조 라벨 / 검증: tests/test_case64_source.py의 정책·도구·앱·환경 변경 및 읽기 오류.
def source_revision():
    files = {"app.py", "requirements.txt", "VERSION"}
    for path in PROJECT_ROOT.iterdir():
        if path.suffix == ".py" or path.name in {"pyproject.toml", "uv.lock", "requirements.lock"} or (path.name.startswith("requirements") and path.suffix == ".txt"):
            files.add(path.relative_to(PROJECT_ROOT).as_posix())
    # [수정: 0 이영] 2026-10-01 05:06 KST — 새 수신 경로가 직접 쓰는 계산·등록 검토 코드도 실제 바이트 지문에 포함한다. 시험 파일은 실행 엔진이 아니므로 제외한다.
    for folder in ("core", "tools", "evidence_gate", "finals"):
        for directory, directories, names in os.walk(PROJECT_ROOT / folder, onerror=_raise_scan_error):
            directories[:] = [name for name in directories if name not in EXCLUDED_DIRECTORIES and not (folder == "finals" and name == "tests")]
            for name in names:
                if name.endswith(".py"):
                    files.add((Path(directory) / name).relative_to(PROJECT_ROOT).as_posix())
    digest = hashlib.sha256()
    for rel in sorted(files):
        digest.update(rel.encode("utf-8") + b"\0")
        digest.update(hashlib.sha256((PROJECT_ROOT / rel).read_bytes()).digest())
    revision = "srcsha256:" + digest.hexdigest()
    git = _git_sha()
    forced = os.environ.get("EVIDENCE_GATE_SOURCE_REVISION", "").strip()
    if git:
        revision += "|git:" + git
    if forced:
        revision += "|label:" + forced
    return revision
