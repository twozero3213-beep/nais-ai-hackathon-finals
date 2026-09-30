"""담당 번호와 본선 작업 시각의 의미를 읽기 전용으로 검사한다."""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {"이영": 0, "이채우": 1, "임도윤": 2, "조지현": 3}
PRODUCT_VERSION = re.compile(r"(?i)(?<![a-z0-9@])v([0-9]+)(?![a-z0-9])")
EXTERNAL_REFERENCE = re.compile(
    r"(?i)(?:[a-z][a-z0-9+.-]*://[^\s<>\"']+|\b10\.[0-9]{4,9}/[^\s<>\"']+)"
)
# [수정: 0 이영] 2026-10-01T01:05:53+09:00 — Data.gov 공식 API 이름·경로의 실제 버전만 구간 단위로 제외하고 같은 문장의 제품 표기는 검사한다.
EXTERNAL_API_LABEL = re.compile(r"(?i)\bData\.gov(?:\s+(?:공식\s+)?API)?\s+v[4]\b")
EXTERNAL_API_PATH = re.compile(r"/technology/datagov/v[4]/search\b")
TEXT_SUFFIXES = {".md", ".json", ".txt", ".py", ".js", ".html", ".css", ".yml", ".yaml", ".toml"}
# [수정: 0 이영] 2026-10-01 00:13 KST — Git 제외된 운영 원출력·팀 저장소는 공개 제품 표시 검사 범위와 분리한다.
IGNORED_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "audit", "team_data", "runtime"}
PROTECTED_PREFIXES = (("data",), ("finals", "evidence"))


def has_product_version(text):
    visible = EXTERNAL_REFERENCE.sub("", text)
    visible = EXTERNAL_API_LABEL.sub("", visible)
    visible = EXTERNAL_API_PATH.sub("", visible)
    label = "".join(chr(code) for code in (0xC900, 0xBE44, 0xBCF8))
    numeric_release = re.finditer(r"(?i)(?<![a-z0-9.])([0-9]+)\.0\.0(?![a-z0-9.])", visible)
    return (label in visible
            or any(int(match.group(1)) >= 4 for match in PRODUCT_VERSION.finditer(visible))
            or any(int(match.group(1)) >= 4 for match in numeric_release))


def product_version_failures(root):
    failures = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(relative.parts[:len(prefix)] == prefix for prefix in PROTECTED_PREFIXES) or any(part in IGNORED_PARTS for part in relative.parts):
            continue
        if has_product_version(relative.as_posix()):
            failures.append(f"{relative}: 프로젝트 버전 파일명 불일치")
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(content.splitlines(), 1):
            if has_product_version(line):
                failures.append(f"{relative}:{number}: 프로젝트 버전 표기 불일치")
    return failures


def check():
    failures = []
    team = json.loads((ROOT / "TEAM_VERSIONS.json").read_text(encoding="utf-8"))
    actual = {entry["name"]: entry["version"] for entry in team["contributors"]}
    if actual != EXPECTED:
        failures.append("담당자 번호 불일치")
    chat = team["this_chat"]
    if EXPECTED.get(chat["name"]) != chat["version"] or chat["commit_prefix"] != f"[{chat['version']} {chat['name']}]":
        failures.append("이 채팅 담당 번호 불일치")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    lead = version.split(".")[0]
    if version not in {str(v) for v in EXPECTED.values()}:
        failures.append("VERSION은 담당자 고정 번호 0/1/2/3이어야 함")

    upload_baseline = datetime.fromisoformat(team["upload_not_before_kst"])
    failures.extend(product_version_failures(ROOT))
    if os.environ.get("GITHUB_ACTIONS") == "true":
        subject = subprocess.check_output(["git", "log", "-1", "--format=%s"], cwd=ROOT, text=True).strip()
        match = re.match(r"^\[([0-3]) (이영|이채우|임도윤|조지현)\]", subject)
        if not match or EXPECTED.get(match[2]) != int(match[1]) or match[1] != version:
            failures.append("업로드 담당자와 VERSION 불일치")
        for field in ("%aI", "%cI"):
            stamp = datetime.fromisoformat(subprocess.check_output(["git", "log", "-1", f"--format={field}"], cwd=ROOT, text=True).strip())
            if stamp < upload_baseline or stamp > datetime.now(stamp.tzinfo):
                failures.append("커밋 시각이 업로드 기준 범위를 벗어남")

    baseline = datetime.fromisoformat(team["finals_started_at_kst"])
    now = datetime.now(baseline.tzinfo)
    json_count = 0
    for path in [ROOT / "TEAM_VERSIONS.json", *sorted((ROOT / "docs").rglob("*.json"))]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            json_count += 1
            if not isinstance(data, dict):
                continue
            for key in ("recorded_at_kst", "document_updated_at_kst", "review_started_at_kst"):
                value = data.get(key)
                if value is None:
                    continue
                stamp = datetime.fromisoformat(value)
                if stamp.utcoffset() != baseline.utcoffset() or not baseline <= stamp <= now:
                    failures.append(f"{path.relative_to(ROOT)}: {key} 불일치")
        except (ValueError, KeyError, TypeError) as exc:
            failures.append(f"{path.relative_to(ROOT)}: 형식 오류 {type(exc).__name__}")

    for name in ("README.md", "AGENTS.md"):
        for target in re.findall(r"\]\(([^)]+)\)", (ROOT / name).read_text(encoding="utf-8")):
            if "://" not in target and not (ROOT / target.split("#", 1)[0]).exists():
                failures.append(f"{name}: 연결 파일 누락 {target}")

    return {
        "contributor_version": int(lead) if lead.isdigit() else None,
        "checked_at_kst": now.isoformat(timespec="seconds"),
        "scope": "담당 번호·JSON 형식·선택된 KST 작업 필드·핵심 문서 링크·현재 제품 표기",
        "json_files_checked": json_count,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "limits": "앱 동작·날짜의 사실성·논문·LLM 성능을 검증한 결과가 아님",
    }


if __name__ == "__main__":
    result = check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["status"] == "PASS" else 1)
