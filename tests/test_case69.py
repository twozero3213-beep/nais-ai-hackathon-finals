"""[작성: 전문가4·7] 2026-09-27 case69 / 검색 캐시·확장 후보의 실제 실패 재현."""
import copy
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
import core.research_corpus as rc


# [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: 표/잘린단어/동의어 경계 fixture / 입력·출력: tmp→root,corpus / 검증: 옵션 기본값 비교.
@pytest.fixture
def enhanced(tmp_path):
    (tmp_path/'data').mkdir()
    text='x '*996+'uniqueboundarytoken improves evidence'
    raw=('<article><front><article-meta><article-id pub-id-type="doi">10.1234/option</article-id></article-meta></front><body><sec><p>'+text+'</p><p>Alpha ending.</p><p>Beta starting with reproducibility.</p><table-wrap id="T1"><caption>Trial table</caption><table><thead><tr><th>Measure</th><th>Value</th></tr></thead><tbody><tr><td>Uniquetablemarker</td><td>7</td></tr></tbody></table></table-wrap></sec></body></article>').encode()
    (tmp_path/'data/p.xml').write_bytes(raw)
    row={'doi':'10.1234/option','title':'Option study','field':'statistics','source_group':'existing600','fulltext_status':rc.ARCHIVED,'relative_fulltext_path':'p.xml','fulltext_sha256':hashlib.sha256(raw).hexdigest(),'license':'CC BY','raw_data_download_status':'NOT_TESTED','reproduction_status':'NOT_TESTED','source_url':'https://doi.org/10.1234/option'}
    (tmp_path/'data/combined_papers_index.json').write_text(json.dumps({'papers':[row]}))
    corpus=rc.build_corpus(tmp_path)
    return tmp_path,corpus,corpus['papers'][0]['split']


# [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: 기본값 보존·명시 표후보 / 입력·출력: query→표 위치 / 검증: fail-before.
def test_table_opt_in(enhanced):
    root,c,split=enhanced
    assert rc.search_corpus(c,'Uniquetablemarker',split,root=root)==[]
    found=rc.search_corpus(c,'Uniquetablemarker',split,root=root,include_tables=True)
    assert found and found[0]['evidence_level']=='TABLE_CANDIDATE'
    assert '7' in found[0]['text'] and 'table' in found[0]['locator']
    assert found[0]['automatic_execution'] is False


# [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: 잘린단어/인접문단 보완 / 입력·출력: query→경계후보 / 검증: 기본본문불변.
def test_boundary_context_opt_in(enhanced):
    root,c,split=enhanced
    found=rc.search_corpus(c,'Alpha Beta',split,root=root,boundary_context=True)
    assert found[0]['rank_score']==1 and found[0]['evidence_level']=='BOUNDARY_CANDIDATE'
    assert len(found[0]['source_locators'])==2
    assert rc.search_corpus(c,'uniqueboundarytoken',split,root=root)==[]
    restored=rc.search_corpus(c,'uniqueboundarytoken',split,root=root,boundary_context=True)
    assert restored and restored[0]['source_ranges'][0]['normalized_start']==1840


# [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: 수동한영동의어 출처 표시 / 입력·출력: query→확장검색 / 검증: default off.
def test_synonyms_explicit(enhanced):
    root,c,split=enhanced
    assert rc.search_corpus(c,'재현성',split,root=root)==[]
    found=rc.search_corpus(c,'재현성',split,root=root,expand_synonyms=True)
    assert found and 'reproducibility' in found[0]['expanded_terms']
    assert found[0]['synonym_source']=='NAIS_MANUAL_TERMS_case69_1'


# [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: warm원문검사·동일mtime변조 / 입력·출력: 변조→BLOCK / 검증: 캐시fallback 없음.
def test_warm_bytes_change_same_mtime_blocks(enhanced):
    root,c,split=enhanced;rc.search_corpus(c,'Beta',split,root=root)
    p=root/'data/p.xml';before=p.stat();raw=p.read_bytes();p.write_bytes(raw.replace(b'Beta',b'Zeta'));os.utime(p,ns=(before.st_atime_ns,before.st_mtime_ns))
    with pytest.raises(ValueError):rc.search_corpus(c,'Beta',split,root=root)


# [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: 가변결과·다중호출 격리 / 입력·출력: 4queries→일관 결과 / 검증: thread/변조.
def test_threads_and_result_mutation(enhanced):
    root,c,split=enhanced
    jobs=[('Beta',split),('Alpha',split),('Beta','validation' if split=='development' else 'development'),('trial',split)]
    # [작성: 전문가4·7] 2026-09-27 case69 / 목적: 혼합분리요청 / 입력·출력: job→후보 / 검증: 동시결과일치.
    def run(job):return rc.search_corpus(c,job[0],job[1],root=root,include_tables=True)
    expected=[run(job) for job in jobs]
    with ThreadPoolExecutor(max_workers=4) as pool:actual=list(pool.map(run,jobs))
    assert actual==expected
    actual[0][0]['text']='forged'
    assert run(jobs[0])==expected[0]
    bad=copy.deepcopy(c);bad['passages'][0]['text']='forged'
    with pytest.raises(ValueError):rc.search_corpus(bad,'Beta',split,root=root)


# [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: warm도 원문byte 읽음·cold만 재파싱 / 입력·출력: 반복검증→계수 / 검증: 캐시 안전성.
def test_cache_reads_bytes_every_time(enhanced,monkeypatch):
    root,c,split=enhanced;rc._VALIDATED.clear();calls=[];reads=[]
    original=rc._assemble_corpus;read=Path.read_bytes
    # [작성: 전문가4·7] 2026-09-27 case69 / 목적: 재구성계수 / 입력·출력: snapshot→corpus / 검증: cold1회.
    def assemble(*args):calls.append(1);return original(*args)
    # [작성: 전문가4·7] 2026-09-27 case69 / 목적: 매요청원문읽기계수 / 입력·출력: path→bytes / 검증: warm읽음.
    def read_bytes(path):
        if path.suffix=='.xml':reads.append(str(path))
        return read(path)
    monkeypatch.setattr(rc,'_assemble_corpus',assemble);monkeypatch.setattr(Path,'read_bytes',read_bytes)
    first=rc.validate_corpus(c,root);second=rc.validate_corpus(c,root)
    assert len(calls)==1 and len(reads)==2
    assert first['source_files_hashed']==second['source_files_hashed']==1
    assert not first['reconstruction_cache_hit'] and second['reconstruction_cache_hit']


# [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: 같은 경로의 다른root·실패캐시 격리 / 입력·출력: 복사/변조→BLOCK / 검증: 캐시회피 불가.
def test_root_isolation_and_failed_cache(enhanced,tmp_path):
    import shutil
    root,c,split=enhanced;rc._VALIDATED.clear();rc.search_corpus(c,'Beta',split,root=root)
    other=tmp_path/'other';shutil.copytree(root/'data',other/'data')
    assert rc.validate_corpus(c,other)['reconstruction_cache_hit'] is False
    bad=copy.deepcopy(c);bad['passages'][0]['text']='forged Beta';bad['content_sha256']=rc.fingerprint({k:v for k,v in bad.items() if k!='content_sha256'})
    size=len(rc._VALIDATED)
    with pytest.raises(ValueError):rc.search_corpus(bad,'Beta',split,root=other)
    assert len(rc._VALIDATED)==size


# [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: hash한bytes와파싱bytes동일성 / 입력·출력: 읽은직후파일교체→snapshot또는차단 / 검증: TOCTOU.
def test_cold_uses_hashed_snapshot(enhanced,monkeypatch):
    root,c,split=enhanced;rc._VALIDATED.clear();original=Path.read_bytes;changed=[]
    # [작성: 전문가4·7] 2026-09-27 case69 / 목적: 읽기직후교체경합 / 입력·출력: path→기존bytes / 검증: 재읽기없음.
    def swap_after_read(path):
        raw=original(path)
        if path.suffix=='.xml' and not changed:
            changed.append(1);path.write_bytes(raw.replace(b'Beta',b'Zeta'))
        return raw
    monkeypatch.setattr(Path,'read_bytes',swap_after_read)
    first=rc.search_corpus(c,'Beta',split,root=root)
    assert first and 'Beta' in first[0]['text']
    with pytest.raises(ValueError):rc.search_corpus(c,'Beta',split,root=root)


# [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: 작은합성입력5배확대에도검사생략없음 / 입력·출력: 약5배XML→검사byte계수 / 검증: 900실측과별개.
def test_small_synthetic_fivefold_bytes(enhanced):
    root,c,split=enhanced;p=root/'data/p.xml';raw=p.read_bytes();larger=raw.replace(b'</sec>',b'<p>'+b'z'*(4*len(raw))+b'</p></sec>')
    manifest=root/'data/combined_papers_index.json';value=json.loads(manifest.read_text());value['papers'][0]['fulltext_sha256']=hashlib.sha256(larger).hexdigest();p.write_bytes(larger);manifest.write_text(json.dumps(value))
    grown=rc.build_corpus(root);report=rc.validate_corpus(grown,root)
    assert report['source_bytes_hashed']==len(larger)>5*len(raw)
    assert grown['summary']['passages']>c['summary']['passages']


# [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: snapshot생성전부터전체검색직렬화 / 입력·출력:4요청→순차검증 / 검증: 동시최대1.
def test_search_serializes_before_snapshot(enhanced,monkeypatch):
    import time
    root,c,split=enhanced;active=[0];peaks=[];original=rc._search_corpus
    # [작성: 전문가4·7] 2026-09-27 case69 / 목적: snapshot직전동시실행관찰 / 입력·출력: 요청→실제검색 / 검증: 최대1.
    def observe(*args,**kwargs):
        active[0]+=1;peaks.append(active[0]);time.sleep(.01)
        try:return original(*args,**kwargs)
        finally:active[0]-=1
    monkeypatch.setattr(rc,'_search_corpus',observe)
    with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(lambda _:rc.search_corpus(c,'Beta',split,root=root),range(4)))
    assert max(peaks)==1 and all(result==results[0] for result in results)
