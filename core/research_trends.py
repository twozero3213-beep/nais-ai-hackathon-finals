# 작성: Google 급상승 RSS 기능 담당 | 2026-09-29 case95 | 고정 KR/US 무료 공식 RSS, 수동 조회만
# 입력: geo allowlist KR/US | 출력: 검색어·근사 트래픽·발행시각·원문링크 최대10건 | 검증: test_case95_trends.py
from datetime import datetime, timezone
import http.client
import re
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

import streamlit as st

from core.research_news import MAX_BYTES, NewsError, _item_date, _plain
from core.research_tasks_ui import scoped_key

TIMEOUT = 15
GEOS = {"KR": "대한민국", "US": "미국"}
RSS_NS = "https://trends.google.com/trending/rss"


def _safe_link(value):
    if not isinstance(value, str) or len(value) > 2000 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.hostname == "trends.google.com" and parsed.port in (None, 443) and not parsed.username and not parsed.password:
            return value
    except ValueError:
        pass
    return None


def _fetch_bytes(geo):
    if geo not in GEOS:
        raise NewsError("UNKNOWN_TRENDS_REGION")
    connection = None
    try:
        connection = http.client.HTTPSConnection("trends.google.com", timeout=TIMEOUT)
        connection.request("GET", "/trending/rss?geo=" + geo, headers={"User-Agent": "NAIS public trends viewer"})
        response = connection.getresponse()
        if response.status != 200:
            raise NewsError("TRENDS_HTTP_ERROR")
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise NewsError("TRENDS_TOO_LARGE")
        return raw
    except NewsError:
        raise
    except Exception:
        raise NewsError("TRENDS_UNAVAILABLE") from None
    finally:
        if connection is not None:
            connection.close()


def parse_trends_feed(raw, geo, *, as_of=None):
    if geo not in GEOS or not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise NewsError("TRENDS_INVALID_INPUT")
    if b"\x00" in raw:
        raise NewsError("TRENDS_INVALID_ENCODING")
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        raise NewsError("TRENDS_INVALID_ENCODING") from None
    declaration = re.match(r"\s*<\?xml\s+[^?]*encoding\s*=\s*['\"]([^'\"]+)['\"]", text, flags=re.I)
    if declaration and declaration.group(1).lower().replace("_", "-") not in {"utf-8", "utf8"}:
        raise NewsError("TRENDS_INVALID_ENCODING")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, flags=re.I):
        raise NewsError("TRENDS_UNSAFE_XML")
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, ValueError):
        raise NewsError("TRENDS_INVALID_XML") from None
    if root.tag.rsplit("}", 1)[-1].lower() != "rss":
        raise NewsError("TRENDS_INVALID_FEED")
    found = root.findall("./channel/item")
    items = []
    for index, item in enumerate(found[:10], 1):
        query = _plain(item.findtext("title"))[:300]
        traffic = _plain(item.findtext(f"{{{RSS_NS}}}approx_traffic"))[:100]
        link = _safe_link((item.findtext("link") or "").strip())
        if query and link:
            items.append({"title": query, "approximate_traffic": traffic or None,
                          "published": _item_date(item.findtext("pubDate")),
                          "link": link, "source_order": index})
    return {"geo": geo, "label": GEOS[geo], "source": "Google Trends 급상승 검색어",
            "feed_url": f"https://trends.google.com/trending/rss?geo={geo}",
            "source_url": f"https://trends.google.com/trending?geo={geo}",
            "as_of": as_of or datetime.now(timezone.utc).isoformat(), "feed_items_seen": len(found), "items": items}


def fetch_trends(geo):
    return parse_trends_feed(_fetch_bytes(geo), geo)


def validate_trends_result(value):
    if not isinstance(value, dict) or set(value) != {"geo", "label", "source", "feed_url", "source_url", "as_of", "feed_items_seen", "items"}:
        raise ValueError("Invalid trends result")
    geo = value["geo"]
    if (geo not in GEOS or value["label"] != GEOS[geo] or value["source"] != "Google Trends 급상승 검색어"
            or value["feed_url"] != f"https://trends.google.com/trending/rss?geo={geo}"
            or value["source_url"] != f"https://trends.google.com/trending?geo={geo}"
            or type(value["feed_items_seen"]) is not int or not 0 <= value["feed_items_seen"] <= 10000
            or not isinstance(value["items"], list) or len(value["items"]) > 10):
        raise ValueError("Invalid trends result")
    try:
        timestamp = datetime.fromisoformat(value["as_of"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp > datetime.now(timezone.utc):
            raise ValueError("Invalid trends timestamp")
    except (AttributeError, TypeError, ValueError):
        raise ValueError("Invalid trends timestamp") from None
    for item in value["items"]:
        if (not isinstance(item, dict) or set(item) != {"title", "approximate_traffic", "published", "link", "source_order"}
                or not isinstance(item["title"], str) or not 1 <= len(item["title"]) <= 300
                or item["approximate_traffic"] is not None
                and (not isinstance(item["approximate_traffic"], str) or len(item["approximate_traffic"]) > 100)
                or item["published"] is not None and (not isinstance(item["published"], str) or len(item["published"]) > 60)
                or not _safe_link(item["link"]) or type(item["source_order"]) is not int
                or not 1 <= item["source_order"] <= 10):
            raise ValueError("Invalid trends item")
    return value


def render_research_trends(actor, on_topic=None, initial_result=None):
    st.subheader("Google 급상승 검색어 · 논문 검색량 아님")
    st.caption("Google Trends RSS 표시순서와 제공된 대략적 검색량 표기입니다. 논문 검색량이나 학술적 중요도를 나타내지 않습니다.")
    geo = st.selectbox("지역", list(GEOS), format_func=lambda value: GEOS[value],
                       key=scoped_key(actor, "google_trends_geo"))
    key = scoped_key(actor, "google_trends_" + geo)
    if isinstance(initial_result, dict) and initial_result.get("geo") == geo:
        try:
            validate_trends_result(initial_result)
            cached = st.session_state.get(key)
            cached_time = datetime.fromisoformat(cached["as_of"].replace("Z", "+00:00")) if cached else None
            new_time = datetime.fromisoformat(initial_result["as_of"].replace("Z", "+00:00"))
            if cached_time is None or new_time > cached_time:
                st.session_state[key] = initial_result
                st.session_state[key + "_origin"] = "예약 자료"
        except (ValueError, TypeError, AttributeError):
            pass
    if st.button("급상승 검색어 불러오기", key=key + "_load"):
        try:
            st.session_state[key] = fetch_trends(geo)
            st.session_state[key + "_origin"] = "직접 조회 자료"
        except NewsError as exc:
            st.session_state[key + "_error"] = str(exc)
        else:
            st.session_state.pop(key + "_error", None)
    error = st.session_state.get(key + "_error")
    if error:
        st.error("검색어를 불러오지 못했습니다 (" + error + "). 이전 성공 결과가 있으면 계속 표시합니다.")
    result = st.session_state.get(key)
    if not result:
        st.info("지역을 선택한 뒤 버튼을 눌러 한 곳만 조회하세요.")
        return
    try:
        result = validate_trends_result(result)
    except ValueError:
        st.error("저장된 검색어 자료가 올바르지 않아 표시할 수 없습니다.")
        return
    fetched = datetime.fromisoformat(result["as_of"].replace("Z", "+00:00"))
    age_hours = (datetime.now(timezone.utc) - fetched.astimezone(timezone.utc)).total_seconds() / 3600
    freshness = st.session_state.get(key + "_origin", "세션 자료")
    if age_hours > 15:
        freshness += " · 15시간보다 오래됨"
    st.caption(result["label"] + " · RSS "
               + str(result["feed_items_seen"]) + "건 중 최대 10건 · " + freshness)
    st.caption("RSS 순서대로 표시합니다. 급상승 검색량은 원문 표기를 유지하며 전체 검색량·논문 검색 인기도가 아닙니다.")
    for item in result["items"][:10]:
        with st.container(border=True):
            st.subheader(item["title"])
            traffic = item["approximate_traffic"] or "제공된 대략적 검색량 없음"
            date_label = item["published"] or "발행일 확인 불가"
            st.text(f"RSS 표시순서 {item['source_order']} · 대략적 검색량 {traffic} · 발행 {date_label}")
            st.link_button("Google Trends 원문 보기", item["link"], key=key + "_link_" + str(item["source_order"]))
            if st.button("이 주제로 논문 찾기", key=key + "_topic_" + str(item["source_order"])):
                query = item["title"][:200]
                if on_topic:
                    on_topic(query)
                else:
                    st.session_state[scoped_key(actor, "discovery_query")] = query
                    st.session_state[scoped_key(actor, "home_next")] = "논문 둘러보기"
                    st.rerun()
    st.link_button("Google Trends 출처 페이지", result["source_url"], key=key + "_source")
