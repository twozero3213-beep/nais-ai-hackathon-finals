# 작성: 연구뉴스 backend·small render | 2026-09-29 case95 | 검증된 대학별 공식 RSS/API 중 하나만 명시 조회
# 입력: 고정 provider ID | 출력: 기사 메타데이터 8건 | 검증: test_case95_news.py (출처·구조·경계·렌더)
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
import http.client
import json
import re
import xml.etree.ElementTree as ET

import streamlit as st

from core.research_tasks_ui import scoped_key

MAX_BYTES = 1024 * 1024
TIMEOUT = 15
MAX_ITEMS = 8
SOURCES = {
    "mit": {"label": "MIT News · 연구", "host": "news.mit.edu", "path": "/rss/research",
            "url": "https://news.mit.edu/rss/research", "format": "rss",
            "domains": {"news.mit.edu"}, "verification_url": "https://news.mit.edu/rss"},
    "kaist": {"label": "KAIST · 뉴스", "host": "www.kaist.ac.kr",
              "path": "/_module/api/json.php?site_dvs_cd=kr&code=news&start=1&display=20",
              "url": "https://www.kaist.ac.kr/_module/api/json.php?site_dvs_cd=kr&code=news&start=1&display=20",
              "format": "json", "domains": {"news.kaist.ac.kr", "www.kaist.ac.kr", "kaist.ac.kr"},
              "verification_url": "https://www.kaist.ac.kr/kr/html/footer/0819.html"},
    "harvard": {"label": "Harvard Gazette · 과학·기술", "host": "news.harvard.edu",
                "path": "/gazette/section/science-technology/feed/",
                "url": "https://news.harvard.edu/gazette/section/science-technology/feed/",
                "format": "rss", "domains": {"news.harvard.edu"},
                "verification_url": "https://news.harvard.edu/gazette/rss-feeds/"},
}


class NewsError(ValueError):
    """Safe, user-displayable RSS failure code."""


class _TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _plain(value):
    parser = _TextOnly()
    parser.feed(unescape(value or ""))
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def _fetch_bytes(source_id="mit"):
    source = SOURCES.get(source_id)
    if source is None:
        raise NewsError("UNKNOWN_SOURCE")
    connection = None
    try:
        connection = http.client.HTTPSConnection(source["host"], timeout=TIMEOUT)
        connection.request("GET", source["path"], headers={"User-Agent": "NAIS public research news viewer"})
        response = connection.getresponse()
        # Never follow redirects or read remote error bodies.
        if response.status != 200:
            raise NewsError("RSS_HTTP_ERROR")
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise NewsError("RSS_TOO_LARGE")
        return raw
    except NewsError:
        raise
    except Exception:
        raise NewsError("RSS_UNAVAILABLE") from None
    finally:
        if connection is not None:
            connection.close()


def _item_date(value):
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def _safe_article_link(value, source_id="mit"):
    from urllib.parse import urlsplit
    if not isinstance(value, str) or len(value) > 2000 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    source = SOURCES.get(source_id)
    if source is None:
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme == "https" and parsed.hostname in source["domains"]
                and parsed.port in (None, 443) and not parsed.username and not parsed.password):
            return value
    except ValueError:
        pass
    return None


def _response(source_id, articles, count, categories, *, as_of=None):
    source = SOURCES[source_id]
    category_counts, category_articles = Counter(), 0
    for article in articles:
        if article["categories"]:
            category_articles += 1
            category_counts.update(article["categories"])
    denominator = sum(category_counts.values())
    return {"source_id": source_id, "source": source["label"], "feed_url": source["url"],
            "verification_url": source["verification_url"],
            "as_of": as_of or datetime.now(timezone.utc).isoformat(), "feed_items_seen": count,
            "articles": articles, "category_counts": [
                {"name": name, "count": value, "denominator": denominator, "article_denominator": category_articles}
                for name, value in category_counts.most_common(5)],
            "category_data_available": bool(category_counts)}


def parse_research_feed(raw, *, source_id="mit", as_of=None):
    """Parse fixed-source RSS or API JSON and return metadata only."""
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise NewsError("RSS_TOO_LARGE_OR_INVALID")
    source = SOURCES.get(source_id)
    if source is None:
        raise NewsError("UNKNOWN_SOURCE")
    if source["format"] == "json":
        try:
            data = json.loads(raw.decode("utf-8-sig", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise NewsError("API_INVALID_JSON") from None
        if not isinstance(data, list):
            raise NewsError("API_INVALID_RESPONSE")
        articles = []
        for item in data[:MAX_ITEMS]:
            if not isinstance(item, dict):
                continue
            title = _plain(item.get("subject"))[:500]
            link = _safe_article_link(item.get("view_link"), source_id)
            if title and link:
                date = item.get("reg_date")
                date = date[:10] if isinstance(date, str) and re.match(r"^\d{4}-\d{2}-\d{2}", date) else None
                articles.append({"title": title, "link": link, "published": date, "categories": []})
        return _response(source_id, articles, len(data), [], as_of=as_of)
    if b"\x00" in raw:
        raise NewsError("RSS_INVALID_ENCODING")
    try:
        xml_text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        raise NewsError("RSS_INVALID_ENCODING") from None
    declaration = re.match(r"\s*<\?xml\s+[^?]*encoding\s*=\s*['\"]([^'\"]+)['\"]", xml_text, flags=re.I)
    if declaration and declaration.group(1).lower().replace("_", "-") not in ("utf-8", "utf8"):
        raise NewsError("RSS_INVALID_ENCODING")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", xml_text, flags=re.I):
        raise NewsError("RSS_UNSAFE_XML")
    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, ValueError):
        raise NewsError("RSS_INVALID_XML") from None
    if root.tag.rsplit("}", 1)[-1].lower() != "rss":
        raise NewsError("RSS_INVALID_FEED")
    items = root.findall("./channel/item")
    articles = []
    for item in items[:MAX_ITEMS]:
        title = _plain(item.findtext("title"))[:500]
        link = _safe_article_link((item.findtext("link") or "").strip(), source_id)
        if not title or not link:
            continue
        categories = list(dict.fromkeys(_plain(node.text or "")[:100] for node in item.findall("category") if _plain(node.text or "")))
        articles.append({
            "title": title,
            "link": link,
            "published": _item_date(item.findtext("pubDate")),
            "categories": categories,
        })
    return _response(source_id, articles, len(items), [], as_of=as_of)


def fetch_research_news(source_id="mit"):
    return parse_research_feed(_fetch_bytes(source_id), source_id=source_id)


def _date_label(value, as_of):
    if not value:
        return "발행일 확인 불가"
    try:
        published = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if published.tzinfo is None:
            return "발행 " + published.strftime("%Y-%m-%d") + " · 시각/시간대 미제공"
        reference = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        days = (reference - published).days
        label = "발행 " + published.astimezone(timezone.utc).strftime("%Y-%m-%d")
        if days < 0:
            return label + " · 미래 날짜, 확인 필요"
        if days > 30:
            return label + " · 오래된 소식"
        return label
    except (ValueError, TypeError):
        return "발행일 확인 불가"


def render_research_news(actor, on_topic=None):
    """Render a small manual-refresh panel; only button clicks make network calls."""
    st.subheader("대학 연구 소식")
    st.caption("선택한 대학의 공식 RSS/API 메타데이터입니다. 세계 인기순위나 논문 정답 순위가 아닙니다.")
    source_id = st.selectbox("대학 소식 출처", list(SOURCES), format_func=lambda value: SOURCES[value]["label"],
                             key=scoped_key(actor, "research_news_source"))
    key = scoped_key(actor, "research_news_" + source_id)
    if st.button("최신 연구 소식 불러오기", key=key + "_load"):
        try:
            st.session_state[key] = fetch_research_news(source_id)
        except NewsError as exc:
            st.session_state[key + "_error"] = str(exc)
        else:
            st.session_state.pop(key + "_error", None)
    error = st.session_state.get(key + "_error")
    if error:
        st.error("뉴스를 불러오지 못했습니다 (" + error + "). 다시 시도해 주세요.")
    data = st.session_state.get(key)
    if not data:
        st.info("선택한 대학의 소식은 버튼을 눌렀을 때만 조회합니다.")
        return
    st.caption("조회된 RSS 기사 " + str(data["feed_items_seen"]) + "건 중 최대 8건 표시")
    categories = data["category_counts"]
    if categories:
        category_denominator = categories[0]["denominator"]
        article_denominator = categories[0]["article_denominator"]
        st.caption("분류어는 RSS가 제공한 category만 집계합니다: 상위 " + str(len(categories))
                   + "개 / 전체 분류 부여 횟수 " + str(category_denominator)
                   + "회, category가 하나 이상 있는 표시대상 기사 " + str(article_denominator) + "건 기준.")
    for index, article in enumerate(data["articles"][:3]):
        with st.container(border=True):
            st.markdown("### " + article["title"])
            st.caption(_date_label(article["published"], data["as_of"]) + " · "
                       + (" · ".join(article["categories"]) if article["categories"] else "RSS 분류어 없음"))
            st.link_button("대학 원문 보기", article["link"], key=key + "_link_" + str(index))
            topic = article["categories"][0] if article["categories"] else article["title"][:200]
            if st.button("이 주제로 논문 찾기", key=key + "_topic_" + str(index)):
                if on_topic:
                    on_topic(topic[:200])
                else:
                    st.session_state[scoped_key(actor, "discovery_query")] = topic[:200]
                    st.session_state[scoped_key(actor, "home_next")] = "논문 둘러보기"
                    st.rerun()
    st.link_button("공식 출처 안내", data["verification_url"], key=key + "_feed")
