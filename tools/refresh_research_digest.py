# 작성: 공개 digest CLI 담당 | 2026-09-29 case95 | 하루 1회 workflow에서 무료 고정 검색 실행
# 입력/출력: --output/--previous 경로, schema1 JSON | 검증: tests/test_case95_digest.py
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.research_digest import atomic_write_digest, build_digest, load_digest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Refresh bounded public research digest")
    parser.add_argument("--output", default="data/research_digest.json")
    parser.add_argument("--previous", help="Prior digest; defaults to the output file when it exists")
    args = parser.parse_args(argv)
    output = Path(args.output)
    previous_path = Path(args.previous) if args.previous else output
    try:
        previous = load_digest(previous_path) if previous_path.exists() else None
        digest = build_digest(previous)
        size = atomic_write_digest(output, digest)
    except Exception:
        print("digest_error=INVALID_PREVIOUS_OR_WRITE")
        return 2
    ok = sum(entry["status"] == "ok" for entry in digest["entries"])
    failed = len(digest["entries"]) - ok
    print(f"entries={len(digest['entries'])} ok={ok} error={failed} bytes={size}")
    return 1 if ok == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
