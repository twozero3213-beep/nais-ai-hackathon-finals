"""External API version and destination guard regression, with no live request."""
# [수정: 0 이영 · Codex] 2026-10-01 00:04 KST — 제품 담당번호 변경이 외부 API 주소를 훼손하지 않도록 요청 경계에서 확인한다.
import pytest

from core import research_data_sources as data


def test_external_api_catalog_and_https_boundary(monkeypatch):
    calls = []
    closed = []

    class Response:
        status = 200

        def read(self, size):
            assert size == data.MAX_RESPONSE_BYTES + 1
            return b'{"results":[]}'

    class Connection:
        def __init__(self, host, timeout):
            assert host == 'api.gsa.gov' and timeout == 15

        def request(self, method, path, headers):
            calls.append((method, path, headers))

        def getresponse(self):
            return Response()

        def close(self):
            closed.append(True)

    monkeypatch.setattr(data.http.client, 'HTTPSConnection', Connection)
    monkeypatch.setattr(data, '_key', lambda *_: None)
    card = next(card for card in data.source_catalog() if card['id'] == 'data_gov')
    assert card['name'] == '미국 Data.gov v4'
    assert card['url'] == 'https://api.gsa.gov/technology/datagov/v4/search'
    assert data._request('data_gov', '/technology/datagov/v4/search?q=climate') == {'results': []}
    assert len(calls) == 1 and calls[0][0] == 'GET'
    assert calls[0][1] == '/technology/datagov/v4/search?q=climate' and closed == [True]


@pytest.mark.parametrize('path', [
    '/technology/datagov/case4/search?q=climate',
    '/technology/datagov/v4/search',
    'https://api.gsa.gov/technology/datagov/v4/search?q=climate',
    '/technology/datagov/v4/search?q=climate\n',
])
def test_incorrect_endpoint_rejected_before_https(monkeypatch, path):
    monkeypatch.setattr(data.http.client, 'HTTPSConnection', lambda *_a, **_k: pytest.fail('invalid path reached transport'))
    with pytest.raises(ValueError, match='RESEARCH_DATA_INVALID_REQUEST'):
        data._request('data_gov', path)
