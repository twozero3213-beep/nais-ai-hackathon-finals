"""저장소 위생·정규성 검사: 줄바꿈, 비밀 형태 문자열, 로컬 절대경로, 이메일, 표기 치환 오염, 중복 설정, JSON 형식.

# [작성: 0 이영 · Claude] 2026-10-01 00:28 KST — 사용자 지시("정규성·재사용성 등 빠진 부분을 계속 점검"). 이 저장소에서 실제로 사고가 난 유형만 검사한다:
# 줄바꿈이 섞여 diff가 전체로 번짐, 표기 정리가 외부 API 경로를 깨뜨림, 설정 파일 중복 표류, 손상된 JSON.
# 읽기 전용이며 종료 코드 0이면 통과. 사용: python tools/repo_hygiene.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "node_modules"}
SKIP_PREFIXES = (("data",), ("finals", "evidence"), ("finals", "results"))   # 원자료·봉인 입력·게시 결과는 바이트를 그대로 둔다
TEXT_SUFFIXES = {".py", ".md", ".json", ".toml", ".yml", ".yaml", ".txt", ".ps1"}
# 줄바꿈은 코드·설정에서만 강제한다. 문서·게시 기록(JSON)은 팀원이 올린 바이트 그대로 지문·기록에 묶여 있을 수 있어 고치지 않는다.
CODE_SUFFIXES = {".py", ".toml", ".yml", ".yaml", ".ps1"}
ALLOW_LOCAL_PATH = "hygiene: allow-local-path"   # 경로를 일부러 다루는 시험 줄에만 붙인다
SECRET = re.compile(r"sk-(?!ant-|test)[A-Za-z0-9_-]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
                    r"|AIza[0-9A-Za-z_-]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----")
LOCAL_PATH = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]|OneDrive|/Users/[A-Za-z0-9_.-]+/|/home/[A-Za-z0-9_.-]+/")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
EMAIL_ALLOWED = ("example.com", "example.org", "example.test", "users.noreply.github.com", "noreply.anthropic.com", "noreply@")
# 시험용 가짜 값 규약: 비밀값 형태 문자열은 sk-test…로 시작하고, 이메일은 예약 도메인(example.*)을 쓴다. 그 밖의 값은 실제 값으로 본다.
# 표기 정리가 버전 표기(v숫자)를 case숫자로 바꿔 URL·API 경로를 깨뜨린 적이 있다(Data.gov). URL 안에 case숫자가 있으면 오염으로 본다.
CASE_IN_URL = re.compile(r"https?://\S*case\d+|['\"]/[A-Za-z0-9_./-]*case\d+[A-Za-z0-9_./?-]*['\"]")


def iter_text_files(root: Path):
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if not path.is_file() or any(p in SKIP_PARTS for p in rel.parts) or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(rel.parts[: len(prefix)] == prefix for prefix in SKIP_PREFIXES):
            continue
        yield rel, path


def check(root: Path = ROOT) -> list[str]:
    findings: list[str] = []
    for rel, path in iter_text_files(root):
        raw = path.read_bytes()
        name = rel.as_posix()
        # [수정: 0 이영 · Claude] 2026-10-01 00:52 KST — 통합 뒤 main에는 CRLF 파일과 LF 파일이 함께 있고(Windows 도구·autocrlf), 작업 트리의 줄바꿈은 각자의
        # git 설정에 따라 달라진다. 파일 전체를 바꾸면 모두의 다음 병합이 충돌하므로 통일을 강제하지 않는다. 한 파일 안에서 두 방식이
        # 섞인 경우만(편집기·스크립트가 일부만 바꾼 사고) 잡는다.
        if path.suffix.lower() in CODE_SUFFIXES and b"\r\n" in raw and raw.count(b"\n") != raw.count(b"\r\n"):
            findings.append(f"{name}: 한 파일에 CRLF와 LF가 섞여 있음")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            findings.append(f"{name}: UTF-8이 아님")
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if SECRET.search(line):
                findings.append(f"{name}:{number}: 비밀값 형태 문자열")
            if LOCAL_PATH.search(line) and name != "tools/repo_hygiene.py" and ALLOW_LOCAL_PATH not in line:
                findings.append(f"{name}:{number}: 로컬 절대경로")
            if CASE_IN_URL.search(line):
                findings.append(f"{name}:{number}: URL·API 경로 안의 case숫자(표기 치환 오염 의심)")
            for match in EMAIL.findall(line):
                if not any(token in match for token in EMAIL_ALLOWED):
                    findings.append(f"{name}:{number}: 이메일 주소")
        if path.suffix.lower() == ".json":
            try:
                json.loads(text, object_pairs_hook=_no_duplicates)
            except ValueError as exc:
                findings.append(f"{name}: JSON 오류 {exc}")
    root_req, finals_req = root / "requirements.txt", root / "finals" / "requirements.txt"
    if root_req.exists() and finals_req.exists() and root_req.read_bytes() != finals_req.read_bytes():
        findings.append("finals/requirements.txt가 루트 requirements.txt와 다름(배포는 루트 파일을 쓴다)")
    if (root / "finals/.streamlit/config.toml").exists() and not (root / ".streamlit/config.toml").exists():
        findings.append("finals/.streamlit/config.toml만 있고 루트 .streamlit/config.toml이 없음(루트 실행에서는 적용되지 않는다)")
    return findings


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"중복 키 {key!r}")
        result[key] = value
    return result


def main() -> int:
    findings = check()
    for line in findings[:60]:
        print(line)
    print(f"위생 검사: {'PASS' if not findings else 'FAIL'} ({len(findings)}건)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
