"""External metadata must fail closed and preserve public response provenance."""
# [작성: 0 이영 · Codex] 2026-10-01 KST — 실제 오류·과대 응답·비정상 JSON을 성공으로 저장하지 않도록 검증.
import unittest
import sys
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event, Lock
import time
from unittest.mock import MagicMock, patch
from core import integration_http as transport


class TransportTests(unittest.TestCase):
    def setUp(self):
        transport._CACHE.clear()

    def response(self, raw, status=200):
        connection = MagicMock()
        connection.getresponse.return_value.status = status
        connection.getresponse.return_value.read.return_value = raw
        return connection

    def fetch(self, raw, kind='json', status=200):
        with patch.object(transport, '_reserve_slot'), patch.object(transport.http.client, 'HTTPSConnection', return_value=self.response(raw, status)):
            return transport._request('zenodo.org', '/api/records/1', {}, kind)

    def test_provenance_and_cache_preserve_observation(self):
        first = self.fetch(b'{"id":1}')
        self.assertTrue(first['ok'])
        self.assertEqual(len(first['response_sha256']), 64)
        second = transport.get_json('zenodo.org', '/api/records/1')
        self.assertTrue(second['cached'])
        self.assertEqual(first['retrieved_at_kst'], second['retrieved_at_kst'])

    def test_no_external_or_sensitive_target(self):
        for host, path, params in [('localhost', '/x', {}), ('zenodo.org', '//bad', {}),
                                   ('zenodo.org', '/x', {'email': 'PRIVATE'}),
                                   ('zenodo.org', '/x', {'q': 'sk-' + 'a' * 30})]:
            with self.assertRaises(ValueError):
                transport.get_json(host, path, params)

    def test_http_error_is_not_empty_success(self):
        result = self.fetch(b'{"items":[]}', status=429)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'HTTP_429')

    def test_nonfinite_duplicate_and_oversize_responses_fail(self):
        for raw in (b'{"x":NaN}', b'{"x":1,"x":2}', b'x' * (transport.MAX_BYTES + 1)):
            self.assertFalse(self.fetch(raw)['ok'])

    def test_external_xml_entity_is_rejected(self):
        self.assertFalse(self.fetch(b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///private">]><rss>&x;</rss>', 'xml')['ok'])

    def test_deep_json_is_a_failure_response(self):
        depth = sys.getrecursionlimit() + 100
        result = self.fetch(b'[' * depth + b'0' + b']' * depth)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'CONNECTION_OR_RESPONSE_ERROR')
        self.assertIsNone(result['data'])

    # [수정: 0 이영 · Codex] 2026-10-01 01:54 KST — 시작 간격 예약이 만료돼도 arXiv 연결이 중첩되지 않고 다른 제공자는 진행함을 실제 SQLite와 모의 HTTP로 검증한다. 버전 0, 외부 네트워크 없음.
    def test_arxiv_connections_serialize_until_close_without_blocking_other_hosts(self):
        first_requested, first_closed, release_first = Event(), Event(), Event()
        second_attempted, second_requested = Event(), Event()
        attempts, overlap = [], []
        count_lock = Lock()
        original_guard = transport._arxiv_connection_guard

        def acquire(host):
            if host == 'rss.arxiv.org':
                with count_lock:
                    attempts.append(host)
                    if len(attempts) == 2:
                        second_attempted.set()
            return original_guard(host)

        class FakeConnection:
            def __init__(self, host, timeout):
                self.host, self.target = host, None
            def request(self, method, target, headers):
                self.target = target
                if target == '/rss/first':
                    first_requested.set()
                elif target == '/rss/second':
                    overlap.append(not first_closed.is_set())
                    second_requested.set()
            def getresponse(self):
                response = MagicMock(status=200)
                def read(limit):
                    if self.target == '/rss/first' and not release_first.wait(5):
                        raise TimeoutError('MOCK_RELEASE_TIMEOUT')
                    return b'<rss/>' if self.host == 'rss.arxiv.org' else b'{"id":1}'
                response.read.side_effect = read
                return response
            def close(self):
                if self.target == '/rss/first':
                    first_closed.set()

        with TemporaryDirectory() as directory, patch.dict(os.environ, {'NAIS_PUBLIC_RATE_DB': str(Path(directory) / 'rate.sqlite')}), \
                patch.object(transport, '_reserve_slot'), patch.object(transport, '_arxiv_connection_guard', side_effect=acquire), \
                patch.object(transport.http.client, 'HTTPSConnection', side_effect=FakeConnection), ThreadPoolExecutor(max_workers=3) as executor:
            first = executor.submit(transport.get_xml, 'rss.arxiv.org', '/rss/first')
            try:
                self.assertTrue(first_requested.wait(2))
                second = executor.submit(transport.get_xml, 'rss.arxiv.org', '/rss/second')
                self.assertTrue(second_attempted.wait(2))
                other = executor.submit(transport.get_json, 'zenodo.org', '/api/records/2')
                self.assertTrue(other.result(timeout=2)['ok'])
                self.assertFalse(first_closed.is_set())
                self.assertFalse(second_requested.wait(0.15))
            finally:
                release_first.set()
            self.assertTrue(first.result(timeout=5)['ok'])
            self.assertTrue(second.result(timeout=5)['ok'])
            self.assertEqual(overlap, [False])

    def test_arxiv_guard_contention_fails_with_bounded_wait_and_no_http(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {'NAIS_PUBLIC_RATE_DB': str(Path(directory) / 'rate.sqlite')}), \
                patch.object(transport, '_ARXIV_CONNECTION_WAIT_SECONDS', 0.05), patch.object(transport, '_reserve_slot'), \
                patch.object(transport.http.client, 'HTTPSConnection') as http:
            holder = sqlite3.connect(str(Path(directory) / 'rate.sqlite') + '.arxiv-connection')
            holder.execute('CREATE TABLE guard (unused INTEGER)')
            holder.execute('BEGIN EXCLUSIVE')
            started = time.monotonic()
            try:
                result = transport.get_xml('rss.arxiv.org', '/rss/blocked')
                self.assertFalse(result['ok'])
                self.assertEqual(result['error'], 'CONNECTION_OR_RESPONSE_ERROR')
                http.assert_not_called()
                self.assertLess(time.monotonic() - started, 1)
            finally:
                holder.rollback()
                holder.close()

    def test_arxiv_http_error_releases_guard_after_connection_close(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {'NAIS_PUBLIC_RATE_DB': str(Path(directory) / 'rate.sqlite')}), \
                patch.object(transport, '_reserve_slot'), \
                patch.object(transport.http.client, 'HTTPSConnection', return_value=self.response(b'', status=429)) as http:
            result = transport.get_xml('rss.arxiv.org', '/rss/error')
            self.assertFalse(result['ok'])
            self.assertEqual(result['error'], 'HTTP_429')
            http.return_value.close.assert_called_once()
            # A separate connection immediately reacquires the guard after the failed request.
            guard = transport._arxiv_connection_guard('rss.arxiv.org')
            try:
                self.assertEqual(guard.execute('SELECT COUNT(*) FROM guard').fetchone(), (0,))
            finally:
                guard.rollback()
                guard.close()


if __name__ == '__main__':
    unittest.main()
