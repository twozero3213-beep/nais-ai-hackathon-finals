"""Validate Scholar navigation privacy and the evidence boundary."""
# [작성: 0 이영 · Codex] 2026-10-01 KST — 실제 조회를 가장하지 않고 발견 URL과 검증 경계를 점검한다.
from urllib.parse import parse_qs, urlsplit
import pytest
from core.scholar_discovery import scholar_discovery


def test_encoded_query_and_evidence_boundary():
    result = scholar_discovery('원자료 & "machine learning"')
    parts = urlsplit(result['search_url'])
    assert parts.hostname == 'scholar.google.com'
    assert parse_qs(parts.query)['q'] == ['원자료 & "machine learning"']
    assert result['retrieved'] is False
    assert result['verification_pass'] is False
    assert result['approved'] is False


@pytest.mark.parametrize('query', ['', 'a', 'a' * 301, 'name@example.org', 'api_key=secret', 'query\nmalicious', '\nquery', 'query\x7f', 'AIza' + 'A' * 35])
def test_private_or_invalid_query_rejected(query):
    result = scholar_discovery(query)
    assert result['ok'] is False
    assert 'search_url' not in result
