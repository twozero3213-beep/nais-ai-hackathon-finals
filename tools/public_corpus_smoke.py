"""Bounded, read-only Europe PMC open-access extraction smoke benchmark.

This is not model training or quantitative-claim reproduction: raw study data and
human gold labels are absent. No PDF or article full text is saved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from core.pdf_claims import extract_numeric_claims

API = "https://www.ebi.ac.uk/europepmc/webservices/rest"
QUERY = "OPEN_ACCESS:Y AND IN_PMC:Y AND FIRST_PDATE:[2020 TO 2024]"


# [작성: 전문가7] 2026-09-25 case40
# 무엇을: Europe PMC 공식 API의 JSON/XML을 제한 크기와 재시도로 읽는다.
# 왜: 공개 논문 반복 실험의 출처·오류를 기록하고 무제한 크롤링을 피한다.
# 입력·출력: URL -> bytes; HTTP 오류는 삼키지 않는다.
# 검증: 100개 실제 요청의 HTTP 결과와 manifest에 실패 수 기록.
def fetch(url: str, attempts: int = 3) -> bytes:
    last = None
    for index in range(attempts):
        try:
            req = Request(url, headers={"User-Agent": "NAIS-Evidence-Gate/40 research-benchmark"})
            with urlopen(req, timeout=25) as response:
                return response.read(4_000_001)
        except Exception as exc:
            last = exc
            time.sleep(1 + index * 2)
    raise RuntimeError(f"Europe PMC request failed: {url}") from last


# [작성: 전문가7] 2026-09-25 case40
# 무엇을: 논문 XML의 초록과 Results 문단만 후보 추출 입력으로 바꾼다.
# 왜: 표/참고문헌/서론의 숫자를 결과 Claim 후보로 대량 오인하지 않기 위해서다.
# 입력·출력: XML bytes -> 결과 문단 텍스트 목록.
# 검증: 동일 XML의 두 번 추출 해시를 비교한다.
def result_paragraphs(xml_bytes: bytes) -> list[str]:
    root = ET.fromstring(xml_bytes)
    chosen = []
    seen = set()
    for parent in root.iter():
        tag = parent.tag.rsplit("}", 1)[-1]
        title = next((" ".join(child.itertext()).strip().lower() for child in parent if child.tag.rsplit("}", 1)[-1] == "title"), "")
        # [수정: 전문가7] 2026-09-25 case40
        # 종류: 오류수정
        # 재현 방법: 실제 공개 논문에서 초록/결과 중복과 서론 문단 혼입을 확인했다.
        # 변경 전: sec 첫 60자 전체에 result가 나오면 Results 절로 오분류.
        # 변경 후: section 제목/타입만 검사하고 동일 문단은 1회만 넣는다.
        # 왜: 실제 논문 후보 수를 부풀리는 반복·문맥 오류를 줄인다.
        # 영향: 공개 XML smoke benchmark의 후보 수가 줄 수 있으나 원문 추출기는 그대로다.
        is_result = tag == "sec" and ("result" in parent.attrib.get("sec-type", "").lower() or title.startswith("results"))
        if tag == "abstract" or is_result:
            for node in parent.iter():
                if node.tag.rsplit("}", 1)[-1] == "p":
                    text = " ".join(" ".join(node.itertext()).split())
                    if text and text not in seen:
                        chosen.append(text)
                        seen.add(text)
    return chosen[:200]


# [작성: 전문가7] 2026-09-25 case40
# 무엇을: 공개 논문 N편에서 후보 추출의 처리량·결정성·사람 확인 전 차단을 기록한다.
# 왜: 특정 합성 PDF 몇 편에 맞춘 규칙을 정확도처럼 소개하지 않기 위해서다.
# 입력·출력: 논문 수와 manifest 경로 -> JSON 결과; 본문·PDF 저장 없음.
# 검증: 실제 Europe PMC 조회 후 manifest 수치, 실패·제외 건수를 대조한다.
def run(limit: int, output: Path) -> dict:
    params = urlencode({"query": QUERY, "format": "json", "pageSize": min(limit, 100), "resultType": "core"})
    search_url = f"{API}/search?{params}"
    records = json.loads(fetch(search_url))["resultList"]["result"]
    rows = []
    for record in records[:limit]:
        pmcid = record.get("pmcid")
        row = {"pmcid": pmcid, "doi": record.get("doi"), "title": record.get("title"), "year": record.get("pubYear"),
               "source_url": f"https://europepmc.org/articles/{pmcid}" if pmcid else None,
               "state": "NO_FULLTEXT_ID", "candidate_count": 0, "stable": None, "raw_data_verified": False}
        if pmcid:
            try:
                xml = fetch(f"{API}/{pmcid}/fullTextXML")
                texts = result_paragraphs(xml)
                first = extract_numeric_claims([(i + 1, t) for i, t in enumerate(texts)], limit=200)
                second = extract_numeric_claims([(i + 1, t) for i, t in enumerate(texts)], limit=200)
                row.update(state="EXTRACTED", result_paragraphs=len(texts), candidate_count=len(first),
                           stable=first == second, xml_sha256=hashlib.sha256(xml).hexdigest(),
                           candidate_sha256=hashlib.sha256(json.dumps(first, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                           human_confirmed=False, executed=False)
            except Exception as exc:
                row.update(state="ERROR", error=f"{type(exc).__name__}: {str(exc)[:160]}")
        rows.append(row)
        time.sleep(0.2)
    summary = {"requested": limit, "returned": len(rows), "full_text_extracted": sum(r["state"] == "EXTRACTED" for r in rows),
               "errors": sum(r["state"] == "ERROR" for r in rows), "candidate_total": sum(r["candidate_count"] for r in rows),
               "deterministic": all(r["stable"] for r in rows if r["state"] == "EXTRACTED"),
               "verified_reproductions": 0, "accuracy_measured": False}
    # [수정: 0 이영] 2026-09-30 21:05 KST — 새 수집 기록에 사전 버전 "case40"이 고정 기록되던 문제 수정; 실행 시 VERSION 값 기록.
    manifest = {"version": (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip(), "collected_at_utc": datetime.now(timezone.utc).isoformat(),
                "source_api": API, "search_url": search_url, "query": QUERY,
                "method": "official open-access XML; abstract/results text; same extractor twice; no gold labels or raw datasets",
                "summary": summary, "papers": rows}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output", type=Path, default=Path("data/real_paper_corpus/manifest.json"))
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be 1..100")
    print(json.dumps(run(args.limit, args.output), ensure_ascii=False))
