"""Exact received UTF-8 JATS byte positions and safe paragraph candidates.

These helpers neither acquire a paper nor verify its identity, licence or meaning.
Call only with the licensed, identity-checked bytes from the relations adapter.
Byte ranges are end-exclusive and include the element's closing tag or '/>'.
"""
# [작성: 0 이영 · Codex] 2026-10-01 KST — 재직렬화·문자 오프셋 추정 없이 실제 받은 XML의 선택 위치를 바이트로 결속한다.
import re
import xml.etree.ElementTree as ET
from xml.parsers import expat

from core.research_integration_relations import _availability, _tag, _text, _xml_index
from core.research_web_search import SENSITIVE, safe_text

MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_LOCATORS = 100
_LOCATOR = re.compile(r"/article\[1\](?:/[A-Za-z_][A-Za-z0-9_.-]*\[[1-9][0-9]{0,6}\])*")


def _source(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_SOURCE_BYTES:
        raise ValueError("JATS_SOURCE_INVALID")
    try:
        raw.decode("utf-8-sig")
    except UnicodeError:
        raise ValueError("JATS_UTF8_REQUIRED") from None
    return raw


def _local(name):
    return name.rsplit("}", 1)[-1]


def _tag_end(raw, start):
    """Find the end of the actual opening/closing token, preserving quoted '>'."""
    if not 0 <= start < len(raw) or raw[start:start + 1] != b"<":
        raise ValueError("JATS_POSITION_INVALID")
    quote = None
    for index in range(start + 1, len(raw)):
        byte = raw[index]
        if quote is not None:
            if byte == quote:
                quote = None
        elif byte in (34, 39):
            quote = byte
        elif byte == 62:
            return index + 1
    raise ValueError("JATS_POSITION_INVALID")


def _index(raw):
    raw = _source(raw)
    parser = expat.ParserCreate(encoding="utf-8", namespace_separator="}")
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    stack, spans, seen_ids = [], {}, set()
    node_count = 0

    def forbidden(*args):
        raise ValueError("JATS_DTD_ENTITY_BLOCKED")

    def external_doctype(name, system_id, public_id, has_internal_subset):
        # [수정: 0 이영 · Codex] 2026-10-01 KST — 실제 표준 JATS external DOCTYPE는 선언만 받아들이고 외부 DTD 로딩·내부subset·entity 실행은 모두 차단한다. 원바이트는 수정하지 않는다.
        if (has_internal_subset or name.rsplit(":", 1)[-1] != "article" or
                not isinstance(system_id, str) or not system_id):
            raise ValueError("JATS_DTD_ENTITY_BLOCKED")

    def declaration(version, encoding, standalone):
        if encoding is not None and encoding.lower().replace("-", "").replace("_", "") != "utf8":
            raise ValueError("JATS_UTF8_REQUIRED")

    def start(name, attrs):
        nonlocal node_count
        node_count += 1
        if node_count > 100000 or len(stack) >= 100:
            raise ValueError("JATS_STRUCTURE_TOO_LARGE")
        name = _local(name)
        if stack:
            counters = stack[-1]["children"]
            counters[name] = counters.get(name, 0) + 1
            path = stack[-1]["path"] + f"/{name}[{counters[name]}]"
        else:
            if name != "article" or spans:
                raise ValueError("JATS_ROOT_INVALID")
            path = "/article[1]"
        if len(path) > 4000:
            raise ValueError("JATS_STRUCTURE_TOO_LARGE")
        for key, value in attrs.items():
            if _local(key) == "id":
                if not value or value != value.strip():
                    raise ValueError("JATS_ID_INVALID")
                if value in seen_ids:
                    raise ValueError("JATS_DUPLICATE_ID")
                seen_ids.add(value)
        index = parser.CurrentByteIndex
        opening_end = _tag_end(raw, index)
        empty = raw[index:opening_end - 1].rstrip().endswith(b"/")
        stack.append({"name": name, "path": path, "start": index,
                      "opening_end": opening_end, "empty": empty, "children": {}})

    def end(name):
        if not stack or stack[-1]["name"] != _local(name):
            raise ValueError("JATS_POSITION_INVALID")
        node = stack.pop()
        if node["empty"]:
            end_index = node["opening_end"]
        else:
            closing_start = parser.CurrentByteIndex
            if raw[closing_start:closing_start + 2] != b"</" or closing_start < node["opening_end"]:
                raise ValueError("JATS_POSITION_INVALID")
            end_index = _tag_end(raw, closing_start)
        spans[node["path"]] = {"locator": node["path"], "start_byte": node["start"], "end_byte": end_index}

    parser.XmlDeclHandler = declaration
    parser.StartElementHandler, parser.EndElementHandler = start, end
    parser.StartDoctypeDeclHandler = external_doctype
    parser.EntityDeclHandler = forbidden
    parser.ExternalEntityRefHandler = forbidden
    parser.SkippedEntityHandler = forbidden
    try:
        parser.Parse(raw, True)
    except expat.ExpatError:
        raise ValueError("JATS_XML_INVALID") from None
    if stack or "/article[1]" not in spans:
        raise ValueError("JATS_XML_INVALID")
    return spans


def jats_spans(source_bytes, locators):
    """Return exact spans for every requested relations XPath or a fixed error.

    Pure external article DOCTYPE is metadata only: parameter entity parsing is
    NEVER and every entity/external reference handler rejects access. Internal
    DTD subsets and entity declarations are blocked. No partial output is
    returned on malformed XML, duplicate IDs, absent locators or non-UTF-8 input.
    The full XML is validated
    even when the requested node occurred before a truncated document tail.
    """
    if (type(locators) is not list or not 1 <= len(locators) <= MAX_LOCATORS or
            any(not isinstance(value, str) or len(value) > 4000 or not _LOCATOR.fullmatch(value) for value in locators) or
            len(set(locators)) != len(locators)):
        raise ValueError("JATS_LOCATORS_INVALID")
    spans = _index(source_bytes)
    if any(locator not in spans for locator in locators):
        raise ValueError("JATS_LOCATOR_NOT_FOUND")
    return [dict(spans[locator]) for locator in locators]


def jats_contexts(source_bytes, limit=80):
    """Safe body paragraphs and explicit availability candidates, never raw XML.

    Text and attributes containing contact/authentication forms suppress that
    entire candidate. Reference lists are excluded. A candidate is a selection
    aid and does not prove that its content supplies the requested conditions.
    """
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("JATS_CONTEXT_LIMIT_INVALID")
    spans = _index(source_bytes)
    try:
        article = ET.fromstring(source_bytes)
    except ET.ParseError:
        raise ValueError("JATS_XML_INVALID") from None
    paths, parents, body_paragraphs = _xml_index(article)
    contexts = []
    for node in article.iter():
        if node not in body_paragraphs and not _availability(node):
            continue
        cursor, in_references = node, False
        while cursor is not None:
            in_references = in_references or _tag(cursor) == "ref-list"
            cursor = parents.get(cursor)
        if in_references:
            continue
        locator = paths[node]
        if locator not in spans:
            raise ValueError("JATS_POSITION_INVALID")
        span = spans[locator]
        selected_raw = source_bytes[span["start_byte"]:span["end_byte"]].decode("utf-8")
        if (SENSITIVE.search(selected_raw) or
                any(SENSITIVE.search(value) for child in node.iter() for value in child.attrib.values())):
            continue
        original_text = _text(node)
        text = safe_text(original_text, 1500)
        if not text:
            continue
        contexts.append({"locator": locator, "text": text, "text_truncated": len(original_text) > 1500})
        if len(contexts) >= limit:
            break
    return contexts
