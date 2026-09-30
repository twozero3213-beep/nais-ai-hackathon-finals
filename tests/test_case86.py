"""Visible evidence lineage and measured registration burden; no human labels."""
from pathlib import Path
import json
import hashlib
import pytest
from core import research_corpus as corpus
from streamlit.testing.v1 import AppTest
from core import portfolio_workspace as workspace

ROOT = Path(__file__).resolve().parents[1]


# [작성: 전문가4·7] 2026-09-28 case86
# 무엇을: 인용·방법·분모·결과의 동일 입력 결속 / 왜: 요약 숫자만으로 재현 경로를 알 수 없음 / 입력·출력: 실제7주장 -> 추적7행 / 검증: 구현전실패·구현후통과.
def test_evidence_chain_is_bound_to_inspected_metadata():
    report = workspace.machine_evidence_review()
    chain = {r['claim_id']: r for r in report['evidence_chain']}
    assert len(chain) == 7
    row = chain['COVID-FAIR-MEAN']
    assert row['method'] == 'mean' and row['observations_used'] == 5700
    assert row['preprocessing_kind'] == 'numeric_not_equal_projection'
    assert row['human_approval'] is False
    assert row['source_quote'] and len(row['source_sha256']) == 64
    assert chain['WINE-RED-N']['action'] == 'BLOCK'
    assert chain['WINE-RED-N']['value'] is None
    assert chain['WINE-RED-N']['source_kind'] == 'metadata_extract'
    assert all(r['metadata_sha256'] == next(c['metadata_sha256'] for c in report['input_snapshot']['claims'] if c['claim_id']==r['claim_id']) for r in chain.values())


# [작성: 전문가4·확장설계] 2026-09-28 case86
# 무엇을: 논문 단위 등록량과 분모 / 왜: 차단자료를 확장성공으로 세지 않기 / 입력·출력: 실제등록 -> 4참조·3산술쌍·7주장 / 검증: 손계산 합계2+2+2+1=7.
def test_registration_inventory_does_not_call_blocked_papers_successes():
    report = workspace.machine_evidence_review()
    rows = report['registration_inventory']
    assert len(rows) == 4
    assert sorted(r['claims'] for r in rows) == [1, 2, 2, 2]
    assert sum(r['arithmetic_matches'] for r in rows) == 5
    assert sum(r['blocked'] for r in rows) == 2
    assert sum(r['metadata_bytes'] for r in rows) == sum(len(json.dumps(c['metadata'], ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')) for c in report['input_snapshot']['claims'])
    assert all(r['registration_seconds'] is None for r in rows)


# [작성: 전문가4] 2026-09-28 case86
# 무엇을: 최종검사 뒤 메타데이터 재읽기 방지 / 왜: 검사한 설명과 다른 설명 결합 금지 / 입력·출력: 뒤늦은 파서 대체 -> 검사한3쌍 유지 / 검증: case85에서는1쌍으로오집계.
def test_review_does_not_reread_metadata_after_integrity_check(monkeypatch):
    alternate = json.loads((ROOT/'data/evaluation/public_reproduction_cases.json').read_text(encoding='utf-8'))
    for c in alternate['cases']:
        c['paper_url'] = 'https://example.invalid/replaced-after-check'
    monkeypatch.setattr(workspace, '_load_json', lambda raw: alternate)
    report = workspace.machine_evidence_review()
    assert report['public_counts']['pairs_with_arithmetic'] == 3


# [작성: 전문가1·2] 2026-09-28 case86
# 무엇을: 화면에서 추적표와 확장부담 확인 / 왜: 실제 구현의 채택가치를 심사자에게 노출 / 입력·출력: 평가준비실 -> 두 표 / 검증: AppTest 예외·필드·표시.
def test_trace_and_registration_tables_are_visible(monkeypatch):
    monkeypatch.setenv('EVIDENCE_GATE_LOCAL_MODE', '1')
    # [수정: 0 이영] 2026-10-01 00:17 KST — 실제 팀 준비실에서 근거/등록 표를 검사한다. 원문·결측·설정 바이트 기대는 유지한다.
    app=AppTest.from_file(str(ROOT/'0_이영_팀작업실.py'), default_timeout=60).run()
    app.radio(key='workspace_view').set_value('평가 준비실').run()
    app.button(key='machine_evidence_run').click().run()
    assert not app.exception
    assert any(x.label == '주장별 원문·실행 경로' for x in app.expander)
    assert any(x.label == '논문별 등록 부담과 지원 범위' for x in app.expander)
    tables = [x.value for x in app.dataframe]
    assert any('원문 인용' in t.columns and '결측 처리' in t.columns for t in tables)
    assert any('설정 바이트' in t.columns for t in tables)


# [작성: 전문가4·7] 2026-09-28 case86
# 무엇을: PMC 묶음 입력 경계 / 왜: 정식 원문 응답 호환·논문 혼합 방지 / 입력·출력: XML -> 단락 또는 차단 / 검증: 단일·다중·변조.
def test_pmc_articleset_single_article_and_tamper():
    raw=b'<pmc-articleset><article><front><article-meta><article-id pub-id-type="doi">10.1234/demo</article-id></article-meta></front><body><p>Original evidence</p></body></article></pmc-articleset>'
    record={'doi':'10.1234/demo','fulltext_sha256':hashlib.sha256(raw).hexdigest()}
    assert corpus.xml_passages(raw,record)[0][0]['text']=='Original evidence'
    with pytest.raises(ValueError,match='hash'):corpus.xml_passages(raw+b' ',record)


# [작성: 전문가4·7] 2026-09-28 case86
# 무엇을: 다중 논문 혼입 차단 / 왜: 첫 논문 임의선택 금지 / 입력·출력: 두 논문 -> 거부 / 검증: 정확한 오류.
def test_pmc_articleset_multiple_articles_rejected():
    raw=b'<pmc-articleset><article/><article/></pmc-articleset>'
    with pytest.raises(ValueError,match='Exactly one article'):
        corpus.xml_passages(raw,{'doi':'10.1234/demo','fulltext_sha256':hashlib.sha256(raw).hexdigest()})


# [작성: 자료통합·통계 담당] 2026-09-28 case86
# 무엇을: 실제 원문 쌍 읽기 / 왜: AI 분류와 재계산 결론 분리 / 입력·출력: 고정 사례 -> 본문·관계 / 검증: 비승인·미실행 유지.
def test_teammate_pair_is_read_only_and_linked():
    inventory=json.loads((ROOT/'data/paper_expansion/inventory.json').read_text(encoding='utf-8'))
    pair=next(p for p in inventory['pairs'] if p['pair_id']=='N3-11814')
    result=corpus.read_correction_pair(ROOT,pair)
    assert result['relationship']=='NOTICE_LINKS_TO_ORIGINAL'
    assert result['analysis_status']=='NOT_EXECUTED' and result['human_approval'] is False
    assert result['documents']['original']['passages'] and result['documents']['notice']['passages']
    assert result['documents']['notice']['doi']=='10.1038/sdata.2017.119'


# [작성: 전문가4·7] 2026-09-28 case86
# 무엇을: 메타데이터와 파일 변조 방어 / 왜: 검증 후 재열람도 안전 / 입력·출력: 잘못된 DOI·경로·해시 -> 차단 / 검증: 세 변형.
def test_teammate_pair_rejects_forged_identity_and_paths():
    import copy
    inventory=json.loads((ROOT/'data/paper_expansion/inventory.json').read_text(encoding='utf-8'))
    pair=next(p for p in inventory['pairs'] if p['pair_id']=='N3-11814')
    for field,value in [('doi','10.1234/wrong'),('path','../outside.xml'),('fulltext_sha256','0'*64)]:
        edited=copy.deepcopy(pair);edited['documents']['original'][field]=value
        with pytest.raises(ValueError):corpus.read_correction_pair(ROOT,edited)


# [작성: 자료통합 담당] 2026-09-28 case86
# 무엇을: 동일 DOI 자기쌍 차단 / 왜: N3-30524가 같은 XML을 양쪽 원문으로 셈 / 입력·출력: 동일 DOI -> 차단 / 검증: 수정 전 실패.
def test_teammate_self_pair_is_not_a_comparison():
    inventory=json.loads((ROOT/'data/paper_expansion/inventory.json').read_text(encoding='utf-8'))
    pair=next(p for p in inventory['pairs'] if p['pair_id']=='N3-11814')
    pair['notice_doi']=pair['doi']
    pair['documents']['notice']=dict(pair['documents']['original'])
    with pytest.raises(ValueError,match='Same DOI'):
        corpus.read_correction_pair(ROOT,pair)


# [작성: 자료통합·검증 담당] 2026-09-28 case86
# 무엇을: 흡수한 자료 전수검사 / 왜: 목록 수와 검증 수 혼동 금지 / 입력·출력: 178쌍 -> 331문서·159완전쌍 / 검증: 전수 해시·DOI·면허.
def test_all_teammate_documents_are_valid_and_not_execution_results():
    inventory=json.loads((ROOT/'data/paper_expansion/inventory.json').read_text(encoding='utf-8'))
    assert len(inventory['pairs'])==178
    results=[corpus.read_correction_pair(ROOT,p) for p in inventory['pairs']]
    assert sum(len(r['documents']) for r in results)==331
    assert sum(len(r['documents'])==2 for r in results)==159
    assert all(r['analysis_status']=='NOT_EXECUTED' for r in results)


# [작성: UX·검증 담당] 2026-09-28 case86
# 무엇을: 원문 쌍 열람 동선 / 왜: 수집물이 앱에서 실제 활용되어야 함 / 입력·출력: 화면 버튼 -> 본문 / 검증: 예외 없음·비실행 안내.
def test_teammate_pair_browser_runs(monkeypatch):
    monkeypatch.setenv('EVIDENCE_GATE_LOCAL_MODE','1')
    # [수정: 0 이영] 2026-10-01 00:17 KST — 팀 근거 검색의 읽기 전용 쌍 열람 경로를 새 팀 진입점에 연결한다.
    app=AppTest.from_file(str(ROOT/'0_이영_팀작업실.py'),default_timeout=60).run()
    app.radio(key='workspace_view').set_value('논문 근거 검색').run()
    app.button(key='correction_pair_read').click().run()
    assert not app.exception
    assert any('재계산은 실행하지 않았습니다' in x.value for x in app.info)
