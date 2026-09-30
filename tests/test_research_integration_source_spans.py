"""Exact raw byte offsets, fail-closed XML and non-sensitive candidate contexts."""
# [작성: 0 이영 · Codex] 2026-10-01 KST — UTF-8 다중 바이트·BOM·CRLF·빈 태그와 위치/보안 실패에 추정 결과가 없음을 검증한다.
import json
import xml.etree.ElementTree as ET

import pytest

from core.research_integration_relations import _xml_index
from core.research_integration_source_spans import jats_contexts, jats_spans

P = "/article[1]/body[1]/p[1]"


def test_exact_korean_multibyte_bom_crlf_and_closing_tag():
    selected = '<p id="p1">분모는 12명입니다. &amp; 값 ≤ 3.</p>'.encode()
    raw = b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8"?>\r\n<article>\r\n<body>' + selected + b'\r\n</body></article>\r\n'
    span = jats_spans(raw, [P])[0]
    assert span == {"locator": P, "start_byte": raw.index(selected), "end_byte": raw.index(selected) + len(selected)}
    assert raw[span["start_byte"]:span["end_byte"]] == selected
    assert span["start_byte"] != len(raw[:span["start_byte"]].decode('utf-8-sig'))


@pytest.mark.parametrize("selected", [b'<p/>', b'<p />', b'<p id="a"/>', b'<p title="x > y" />', b"<p title='x > y'/>"])
def test_empty_element_exact_end(selected):
    raw = b'<article><body>' + selected + b'<p>second</p></body></article>'
    span = jats_spans(raw, [P])[0]
    assert raw[span["start_byte"]:span["end_byte"]] == selected


def test_same_localtag_namespace_occurrences_match_relations_paths():
    raw = b'<j:article xmlns:j="urn:jats" xmlns:other="urn:other"><j:body><!--comment--><j:p id="a">one</j:p><?test value?><other:p id="b">two</other:p><j:sec><j:p>three</j:p></j:sec></j:body></j:article>'
    article = ET.fromstring(raw)
    paths, _, _ = _xml_index(article)
    locators = list(paths.values())
    spans = jats_spans(raw, locators)
    assert len(spans) == len(paths)
    second = next(item for item in spans if item["locator"] == "/article[1]/body[1]/p[2]")
    assert raw[second["start_byte"]:second["end_byte"]] == b'<other:p id="b">two</other:p>'


def test_nested_requested_elements_and_input_order():
    raw = b'<article><body><sec><title>Methods</title><p><italic>Mean</italic> is 2.</p></sec></body></article>'
    locators = ["/article[1]/body[1]/sec[1]/p[1]", "/article[1]/body[1]/sec[1]", "/article[1]"]
    spans = jats_spans(raw, locators)
    assert [s["locator"] for s in spans] == locators
    assert raw[spans[0]["start_byte"]:spans[0]["end_byte"]] == b'<p><italic>Mean</italic> is 2.</p>'
    assert raw[spans[-1]["start_byte"]:spans[-1]["end_byte"]] == raw


@pytest.mark.parametrize("raw,code", [
    (b'<!DOCTYPE article><article/>', 'JATS_DTD_ENTITY_BLOCKED'),
    (b'<!DOCTYPE article [<!ENTITY x "expanded">]><article/>', 'JATS_DTD_ENTITY_BLOCKED'),
    (b'<!DOCTYPE article SYSTEM "https://example.invalid/dtd" []><article/>', 'JATS_DTD_ENTITY_BLOCKED'),
    (b'<article><body><p id="same"/><p id="same"/></body></article>', 'JATS_DUPLICATE_ID'),
    (b'<article><body><p id="same"/><p xml:id="same"/></body></article>', 'JATS_DUPLICATE_ID'),
    (b'<article><body><p>valid</p></body>', 'JATS_XML_INVALID'),
    (b'<article><body><p>&unknown;</p></body></article>', 'JATS_XML_INVALID'),
    (b'<article><body><p>\xff</p></body></article>', 'JATS_UTF8_REQUIRED'),
    (b'<?xml version="1.0" encoding="ISO-8859-1"?><article/>', 'JATS_UTF8_REQUIRED'),
    (b'<other/>', 'JATS_ROOT_INVALID'),
    (b'<article id=""/>', 'JATS_ID_INVALID'),
])
def test_invalid_xml_has_fixed_errors_without_partial_spans(raw, code):
    with pytest.raises(ValueError, match='^' + code + '$'):
        jats_spans(raw, ["/article[1]"])
    with pytest.raises(ValueError, match='^' + code + '$'):
        jats_contexts(raw)


# [수정: 0 이영 · Codex] 2026-10-01 KST — 4MiB 입력을 pytest 이름/Windows 환경변수에 복제하지 않도록 짧은 ID를 지정한다.
@pytest.mark.parametrize("raw", [b'', 'not bytes', bytearray(b'<article/>'), b' ' * (4 * 1024 * 1024 + 1)], ids=['empty', 'string', 'mutable-bytes', 'over-4mib'])
def test_source_size_and_bytes_type(raw):
    with pytest.raises(ValueError, match='JATS_SOURCE_INVALID'):
        jats_spans(raw, ["/article[1]"])


@pytest.mark.parametrize("locators", [[], P, [P, P], [P + '/..'], ['/article[0]'], ['/article[1]//*'], ['/article[1]/p[1]'] * 101])
def test_invalid_locator_contract(locators):
    with pytest.raises(ValueError, match='JATS_LOCATORS_INVALID'):
        jats_spans(b'<article/>', locators)


def test_missing_locator_is_not_guessed_or_partial():
    with pytest.raises(ValueError, match='JATS_LOCATOR_NOT_FOUND'):
        jats_spans(b'<article><body><p>one</p></body></article>', [P, '/article[1]/body[1]/p[2]'])


def test_depth_bound_and_entire_tail_validated():
    raw = b'<article>' + b'<sec>' * 100 + b'</sec>' * 100 + b'</article>'
    with pytest.raises(ValueError, match='JATS_STRUCTURE_TOO_LARGE'):
        jats_spans(raw, ['/article[1]'])
    with pytest.raises(ValueError, match='JATS_XML_INVALID'):
        jats_spans(b'<article><body><p>complete selected node</p><broken', [P])


def test_contexts_include_body_and_explicit_availability_not_bibliography():
    raw = b'<article><front><abstract><p>Abstract excluded.</p></abstract><notes><title>Data Availability</title><p>Repository statement.</p></notes></front><body><sec><title>Methods</title><p>Denominator is 12.</p><p>Missing values excluded.</p></sec><ref-list><p>Reference not a source paragraph.</p><sec><title>Data Availability</title><p>Not an availability section.</p></sec></ref-list></body></article>'
    contexts = jats_contexts(raw)
    assert [c['locator'] for c in contexts] == ['/article[1]/front[1]/notes[1]', '/article[1]/body[1]/sec[1]/p[1]', '/article[1]/body[1]/sec[1]/p[2]']
    spans = jats_spans(raw, [c['locator'] for c in contexts])
    assert len(spans) == 3
    assert 'Abstract excluded' not in json.dumps(contexts) and 'Reference not' not in json.dumps(contexts)
    assert all(set(c) == {'locator', 'text', 'text_truncated'} for c in contexts)


def test_contexts_suppress_email_authentication_and_encoded_sensitive_attributes():
    raw = b'<article><body><p>Contact synthetic@example.invalid</p><p api-key="synthetic">Hidden auth attribute.</p><p email="synthetic&#64;example.invalid">Encoded email attribute.</p><p><ext-link href="https://example.org?token=synthetic">Hidden query auth.</ext-link></p><p>Safe public paragraph.</p></body></article>'
    contexts = jats_contexts(raw)
    assert contexts == [{'locator': '/article[1]/body[1]/p[5]', 'text': 'Safe public paragraph.', 'text_truncated': False}]


def test_contexts_limit_truncation_and_utf8_text():
    text = '한글' * 800
    raw = ('<article><body><p>' + text + '</p><p>Second</p></body></article>').encode()
    contexts = jats_contexts(raw, limit=1)
    assert len(contexts) == 1 and len(contexts[0]['text']) == 1500 and contexts[0]['text_truncated']
    assert contexts[0]['text'].startswith('한글')


@pytest.mark.parametrize("limit", [True, 0, 201, 1.0, '80'])
def test_context_limit_strict_integer(limit):
    with pytest.raises(ValueError, match='JATS_CONTEXT_LIMIT_INVALID'):
        jats_contexts(b'<article/>', limit)


def test_candidate_text_preserves_no_semantic_or_license_claim():
    raw = b'<article><body><p>Counts are reported here.</p></body></article>'
    contexts = jats_contexts(raw)
    assert contexts == [{'locator': P, 'text': 'Counts are reported here.', 'text_truncated': False}]
    assert not {'verified', 'approved', 'license'} & set(contexts[0])


@pytest.mark.parametrize('declaration', [
    b'<!DOCTYPE article SYSTEM "https://example.invalid/jats.dtd">',
    b'<!DOCTYPE article PUBLIC "-//NLM//DTD JATS 1.3//EN" "JATS-journalpublishing1-3.dtd">',
    b'<!DOCTYPE article SYSTEM "file:///never-read-private.dtd">',
])
def test_pure_external_doctype_metadata_only_offsets_unchanged(monkeypatch, declaration):
    # [수정: 0 이영 · Codex] 2026-10-01 KST — pure external 선언만 허용하며 외부파일/네트워크가 실행되지 않고 원문위치가 그대로임을 검증한다.
    import builtins
    import socket
    from pathlib import Path
    from urllib import request
    def blocked(*args, **kwargs):
        pytest.fail('external DTD network/file access')
    monkeypatch.setattr(builtins, 'open', blocked)
    monkeypatch.setattr(Path, 'read_bytes', blocked)
    monkeypatch.setattr(request, 'urlopen', blocked)
    monkeypatch.setattr(socket, 'create_connection', blocked)
    selected = '<p>실제 12명.</p>'.encode()
    raw = b'\xef\xbb\xbf<?xml version="1.0" encoding="UTF-8"?>\r\n' + declaration + b'\r\n<article><body>' + selected + b'</body></article>'
    span = jats_spans(raw, [P])[0]
    assert span['start_byte'] == raw.index(selected)
    assert raw[span['start_byte']:span['end_byte']] == selected
    assert jats_contexts(raw) == [{'locator': P, 'text': '실제 12명.', 'text_truncated': False}]


@pytest.mark.parametrize('raw', [
    b'<!DOCTYPE article SYSTEM "https://example.invalid/dtd" [<!ENTITY a "value">]><article/>',
    b'<!DOCTYPE article SYSTEM "https://example.invalid/dtd" [<!ENTITY % p SYSTEM "file:///private">%p;]><article/>',
    b'<!DOCTYPE article SYSTEM "https://example.invalid/dtd"><article><body><p>&external;</p></body></article>',
    b'<!DOCTYPE different SYSTEM "https://example.invalid/dtd"><article/>',
])
def test_external_declaration_never_enables_internal_or_general_parameter_entities(raw):
    with pytest.raises(ValueError, match='JATS_DTD_ENTITY_BLOCKED'):
        jats_spans(raw, ['/article[1]'])
    with pytest.raises(ValueError, match='JATS_DTD_ENTITY_BLOCKED'):
        jats_contexts(raw)
