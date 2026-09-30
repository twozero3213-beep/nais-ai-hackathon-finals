"""[0 이영] 2026-10-01 KST: explicit public feed probes; no keys or model calls."""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.research_integration_feeds import get_integration_feed, list_feed_providers


def main():
    parser = argparse.ArgumentParser(description="고정 공개 RSS/API 발견 메타데이터를 한 번씩 조회합니다.")
    parser.add_argument("--providers", nargs="+", choices=[x["provider"] for x in list_feed_providers()],
                        default=["arxiv", "biorxiv", "kisti", "mit", "harvard", "kaist", "trends_kr", "trends_us"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("원 실행 기록을 덮어쓸 수 없습니다.")
    kst = timezone(timedelta(hours=9))
    started = datetime.now(kst).isoformat(timespec="seconds")
    results = []
    for provider in dict.fromkeys(args.providers):
        value = get_integration_feed(provider, limit=3, refresh=True)
        # Preserve only bounded observation facts, never feed bodies, contacts or credentials.
        public = {key: value.get(key) for key in (
            "provider", "kind", "ok", "status", "count", "observed_at", "checked_at",
            "last_success_at", "cached", "stale", "error", "source_url", "documentation_url", "response_sha256")}
        public["metadata_item_sha256"] = [item["metadata_sha256"] for item in value["items"]]
        public["normalized_snapshot_sha256"] = hashlib.sha256(json.dumps(value, ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        results.append(public)
        print(json.dumps({key: public[key] for key in ("provider", "ok", "status", "count", "error")}, ensure_ascii=False), flush=True)
    report = {"_change_note": "0 이영 — 명시적 무키 공개 GET 관측. 성공은 발견 메타데이터이며 검산/모델/사람 승인 완료가 아니다.",
              "contributor_version": 0, "started_at_kst": started,
              "finished_at_kst": datetime.now(kst).isoformat(timespec="seconds"),
              "model_calls": 0, "credential_files_read": 0, "observations": results,
              "code_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
                  "core/research_integration_feeds.py", "core/scholarly_feeds.py", "tools/0_이영_전체연동_실조회.py")},
              "limitations": "프로세스 캐시; 재시작 후 지속 보존은 미구현. 기존 뉴스/Trends 함수는 HTTP 원응답 지문을 제공하지 않아 normalized snapshot 지문과 구분한다. 계정/개인 라이브러리 조회 없음."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
