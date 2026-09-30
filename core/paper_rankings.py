"""PLOS-reported usage, citation search, and search trends remain separate metrics."""
from datetime import datetime, timezone, timedelta
import http.client
import re
from urllib.parse import urlencode, quote
import streamlit as st
from core.research_corpus import strict_json
from core.paper_discovery import _plain
from core.research_tasks_ui import scoped_key


# [작성: 지표 검증 담당] 2026-09-29 case95 / PLOS 최근30일 필드→출처별순위 / 색인일 오래되면 실시간으로 부르지 않는다.
def fetch_view_rankings():
    params={'q':'*:*','fq':'doc_type:full AND article_type:"Research Article"',
        'fl':'id,title_display,publication_date,counter_total_all,counter_total_month,timestamp',
        'rows':10,'sort':'counter_total_month desc','wt':'json'}
    path='/search?'+urlencode(params)
    connection=http.client.HTTPSConnection('api.plos.org',timeout=15)
    try:
        connection.request('GET',path,headers={'User-Agent':'NAIS-ResearchRankings/95','Accept':'application/json'})
        response=connection.getresponse()
        if response.status!=200:raise ValueError('PLOS_UNAVAILABLE')
        raw=response.read(1024*1024+1)
        if len(raw)>1024*1024:raise ValueError('PLOS_OVERSIZE')
        payload=strict_json(raw)['response'];records=payload['docs']
        if not isinstance(records,list) or len(records)>10:raise ValueError('PLOS_INVALID')
        items=[]
        for record in records:
            doi=record.get('id');value=record.get('counter_total_month')
            if not isinstance(doi,str) or not re.fullmatch(r'10\.1371/[A-Za-z0-9._/-]{1,180}',doi):continue
            if type(value) is not int or value<0:continue
            title=_plain(record.get('title_display',''),600)
            if not title:continue
            indexed=record.get('timestamp');age=None
            try:
                stamp=datetime.fromisoformat(indexed.replace('Z','+00:00'))
                if stamp.tzinfo is not None:age=(datetime.now(timezone.utc)-stamp).total_seconds()/86400
            except (AttributeError,TypeError,ValueError):pass
            items.append({'doi':doi,'title':title,'views_30_days':value,
                'indexed_at':indexed if isinstance(indexed,str) and len(indexed)<60 else None,
                'freshness_verified':age is not None and 0<=age<=30,'url':'https://doi.org/'+quote(doi,safe='/')})
        items.sort(key=lambda row:row['views_30_days'],reverse=True)
        return {'source':'https://api.plos.org'+path,'checked_at':datetime.now(timezone.utc).isoformat(),
            'scope':'PLOS research articles only; counter_total_month, not unique readers',
            'metrics_window_end':None,'items':items,
            'limitations':['조회수는 고유 독자 수가 아닙니다.','API가 지표 집계기간의 종료일을 별도로 제공하지 않아 현재 최근 30일이라고 확정할 수 없습니다.']}
    except Exception:
        raise ValueError('PLOS_UNAVAILABLE_OR_INVALID') from None
    finally:connection.close()


def render_rankings(actor):
    st.title('어떤 연구에 관심이 모였을까요?')
    st.write('인용은 연구에서의 참고, 조회는 읽기 활동, 검색어는 사회적 관심입니다. 서로 합쳐 점수를 만들지 않습니다.')
    metric=st.radio('관심 지표',['논문 인용 수','논문 조회수 · PLOS','급상승 검색어 · Google'],horizontal=True,key=scoped_key(actor,'ranking_metric'))
    if metric=='논문 인용 수':
        st.info('최근 1년 또는 3년 안에 발행된 논문을 현재 누적 인용 수로 정렬합니다. 최근 1년 동안 발생한 인용 수를 뜻하지는 않습니다.')
        if st.button('분야·검색어를 정해 인용순 보기',key=scoped_key(actor,'ranking_citations')):
            st.session_state[scoped_key(actor,'discovery_mode')]='최근 1년 발행 · 인용 많은 순'
            st.session_state[scoped_key(actor,'home_next')]='논문 둘러보기';st.rerun()
        return
    if metric=='급상승 검색어 · Google':
        from core.research_trends import render_research_trends
        from core.research_digest_remote import load_digest
        digest,source,error=load_digest()
        geo=st.session_state.get(scoped_key(actor,'google_trends_geo'),'KR')
        entry=next((row for row in (digest or {}).get('entries',[]) if row['id']=='trends:'+geo),None)
        if entry:
            st.caption(source + ' · 보관된 정기 조회 결과')
            if entry['status']=='error':st.warning('최근 정기 조회에 실패했습니다. 마지막 성공 자료를 표시합니다.')
        render_research_trends(actor,initial_result=entry['data'] if entry else None)
        return
    st.caption('PLOS 공식 API의 counter_total_month 기준입니다. 모든 출판사·모든 논문의 조회 순위가 아닙니다.')
    key=scoped_key(actor,'view_rankings')
    if st.button('PLOS 조회 지표 불러오기',key=key+'_load'):
        try:st.session_state[key]=fetch_view_rankings();st.session_state.pop(key+'_error',None)
        except ValueError:st.session_state[key+'_error']=True
    if st.session_state.get(key+'_error'):st.warning('지표를 새로 가져오지 못했습니다. 이전 자료가 있으면 과거 보관 결과로 표시합니다.')
    data=st.session_state.get(key)
    if not data:return
    st.warning('지표의 집계 종료일이 제공되지 않았습니다. 아래는 API 제공값 순서이며, 현재 실시간 인기순위로 해석할 수 없습니다.')
    previous_value=None;rank=0
    for index,item in enumerate(data['items']):
        if item['views_30_days']!=previous_value:rank=index+1
        previous_value=item['views_30_days']
        with st.container(border=True):
            st.caption(f"제공값 {rank}위 · 30일 조회 필드 {item['views_30_days']:,}회")
            st.write(item['title'])
            from core.title_translation import korean_title
            translated=korean_title(item['title'])
            st.write(translated) if translated else st.caption('한국어 번역 준비 중')
            st.caption('최종 색인: '+str(item['indexed_at'] or '미제공'))
            if not item['freshness_verified']:st.caption('오래되었거나 날짜가 불명확한 지표 · 현재 순위 확인 불가')
            st.link_button('논문 원문 보기',item['url'],key=key+'_doi_'+str(index))
