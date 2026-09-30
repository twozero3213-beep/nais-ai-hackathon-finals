"""Team bibliography integration: immutable original corpus, no XML promotion."""
import hashlib
import json
from pathlib import Path

import pytest
from core import research_corpus as rc

ROOT = Path(__file__).resolve().parents[1]


def fixture_root(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    row = {'doi': '10.1234/baseline', 'title': 'Baseline only', 'field': 'test',
           'source_group': 'faculty_publications', 'fulltext_status': 'CITATION_METADATA_ONLY',
           'raw_data_download_status': 'NOT_TESTED', 'reproduction_status': 'NOT_TESTED'}
    (data / 'combined_papers_index.json').write_text(json.dumps({'papers': [row]}), encoding='utf-8')
    addon = tmp_path / rc.TEAM_METADATA
    addon.parent.mkdir(parents=True)
    addon.write_bytes((ROOT / rc.TEAM_METADATA).read_bytes())
    return rc.build_corpus(tmp_path), addon


def test_real_doi_comparison_and_search_boundary(tmp_path):
    _, existing = rc.load_records(ROOT, rc.MANIFEST)
    rows = rc.load_team_metadata(ROOT, existing)
    assert len(existing) == 900 and len(rows) == 20
    assert not ({r['doi'] for r in rows} & {r['doi'] for r in existing})
    assert len({r['doi'] for r in rows}) == 20
    corpus, _ = fixture_root(tmp_path)
    paper = rc.load_team_metadata(tmp_path, corpus['papers'])[0]
    results = rc.search_corpus(corpus, 'hydrological', split=paper['split'], mode='bibliography', root=tmp_path)
    assert any(r['doi'] == paper['doi'] and r['evidence_level'] == 'BIBLIOGRAPHY_ONLY' for r in results)
    assert all(r['source_path'] is None and r['source_sha256'] is None and r['automatic_execution'] is False for r in results)
    assert not rc.search_corpus(corpus, 'hydrological', split=paper['split'], mode='passages', root=tmp_path)
    assert corpus['summary']['fulltext'] == 0 and corpus['summary']['records'] == 1
    assert sum(r['fulltext_block_reason'] == 'FULLTEXT_NOT_ACQUIRED' for r in rows) == 5


def test_duplicate_preserves_existing_fulltext_and_no_xml_read(tmp_path, monkeypatch):
    corpus, _ = fixture_root(tmp_path)
    row = rc.load_team_metadata(tmp_path, corpus['papers'])[0]
    existing = [dict(row, fulltext_status=rc.ARCHIVED, fulltext_sha256='a' * 64)]
    original = dict(existing[0])
    read = Path.read_bytes
    def metadata_only(path):
        assert path.suffix != '.xml'
        return read(path)
    monkeypatch.setattr(Path, 'read_bytes', metadata_only)
    rows = rc.load_team_metadata(tmp_path, existing)
    assert len(rows) == 19 and row['doi'] not in {r['doi'] for r in rows}
    assert existing[0] == original


def test_tamper_and_deletion_fail_closed(tmp_path):
    corpus, addon = fixture_root(tmp_path)
    addon.write_bytes(addon.read_bytes() + b' ')
    with pytest.raises(ValueError, match='hash mismatch'):
        rc.search_corpus(corpus, 'hydrological', mode='bibliography', root=tmp_path)
    (tmp_path / rc.MANIFEST).write_bytes((ROOT / rc.MANIFEST).read_bytes())
    addon.unlink()
    with pytest.raises(ValueError, match='Required team metadata missing'):
        rc.load_team_metadata(tmp_path, corpus['papers'])


@pytest.mark.parametrize('key,value', [('public_urls', ['file:///secret']), ('metadata_provenance', ['../escape']), ('fulltext_status', rc.ARCHIVED), ('automatic_execution', True)])
def test_boundary_validation_even_with_updated_digest(tmp_path, monkeypatch, key, value):
    corpus, addon = fixture_root(tmp_path)
    obj = json.loads(addon.read_bytes()); obj['papers'][0][key] = value
    raw = json.dumps(obj).encode(); addon.write_bytes(raw)
    monkeypatch.setattr(rc, 'TEAM_METADATA_SHA256', hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError): rc.load_team_metadata(tmp_path, corpus['papers'])
