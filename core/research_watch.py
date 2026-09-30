"""Bounded Crossref metadata checks; no full-text crawling, model call or verdict."""
import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import json
from pathlib import Path
import re
from urllib.parse import quote

from core.research_corpus import strict_json

MAX_BYTES = 1024 * 1024


def _valid_snapshot(item):
    return (isinstance(item, dict) and {'doi', 'title', 'updates', 'relations'} <= item.keys()
            and isinstance(item['doi'], str) and bool(item['doi'])
            and (isinstance(item['title'], str) or
                 isinstance(item['title'], list) and all(isinstance(x, str) for x in item['title']))
            and isinstance(item['updates'], list) and isinstance(item['relations'], dict)
            and isinstance(item.get('type', ''), str))


# [작성: 운영·보안] 2026-09-29 case93 / DOI→공식 서지; 임의 URL·무제한 응답 방지; test_case93_watch.
def fetch_metadata(doi):
    if not isinstance(doi, str) or len(doi)>200 or not re.fullmatch(r'10\.\d{4,9}/[^\s]+',doi):
        raise ValueError('DOI 형식이 필요합니다. URL이나 파일 경로는 받지 않습니다.')
    connection = http.client.HTTPSConnection('api.crossref.org',timeout=15)
    try:
        connection.request('GET','/works/'+quote(doi,safe=''),headers={'User-Agent':'NAIS-ResearchWatch/93','Accept':'application/json'})
        response=connection.getresponse()
        if response.status!=200:
            raise ValueError('서지 조회 실패: HTTP '+str(response.status)+' · 재시도는 자동 실행하지 않습니다.')
        raw=response.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:raise ValueError('서지 응답 크기 초과')
        try:
            payload=strict_json(raw)
            json.dumps(payload,allow_nan=False)
        except (ValueError,TypeError):
            raise ValueError('서지 응답 형식 오류') from None
        item=payload.get('message') if isinstance(payload,dict) else None
        if not isinstance(item,dict):raise ValueError('서지 응답 형식 오류')
        if str(item.get('DOI','')).lower()!=doi.lower():raise ValueError('응답 DOI 불일치')
        if not isinstance(item.get('title',[]),list):raise ValueError('서지 응답 필드 형식 오류')
        result={'doi':doi.lower(),'title':item.get('title',[]),'updates':item.get('update-to',[]),
                'relations':item.get('relation',{}),'type':item.get('type','')}
        if not _valid_snapshot(result):raise ValueError('서지 응답 필드 형식 오류')
        result['source_response_sha256']=hashlib.sha256(raw).hexdigest()
        return result
    except (OSError, http.client.HTTPException, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('서지 연결 또는 응답 형식을 확인할 수 없습니다.') from None
    finally:
        connection.close()


# [작성: 운영·통계] 2026-09-29 case93 / 현재·이전서지→변경알림; 메타데이터를 논문 판정으로 오인하지 않음; test_case93_watch.
def compare_metadata(current, previous):
    if not _valid_snapshot(current) or (previous is not None and not _valid_snapshot(previous)):
        raise ValueError('저장한 서지 스냅샷 형식이 아닙니다.')
    required={'doi','title','updates','relations'}
    if previous is not None and previous['doi']!=current['doi']:raise ValueError('다른 DOI의 기록입니다.')
    keys=required | {'type'}
    changed=[] if previous is None else sorted(k for k in keys if current.get(k)!=previous.get(k))
    return {'schema':1,'checked_at':datetime.now(timezone.utc).isoformat(),'doi':current['doi'],
            'state':'BASELINE' if previous is None else ('METADATA_CHANGED' if changed else 'UNCHANGED'),
            'changed_fields':changed,'current':current,'approved':False,'executed':False,
            'limitations':['Crossref에 등록된 제목·관계·정정 연결만 대조합니다. 전체 논문 변경이나 모든 철회를 탐지하지 않습니다.',
                           '변경 없음은 논문이 옳다는 뜻이 아닙니다. 서지 변경은 원문 확인을 위한 알림입니다.']}


# [작성: 운영] 2026-09-29 case93 / 예약실행용 1회 명령; 실패 시 기존 보고 보존; test_case93_watch + 공식 API smoke.
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--doi',required=True)
    parser.add_argument('--previous',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    previous=None
    if args.previous and args.previous.exists():
        with args.previous.open('rb') as handle:raw=handle.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:raise ValueError('이전 기록 크기 초과')
        previous=json.loads(raw)['current']
    report=compare_metadata(fetch_metadata(args.doi),previous)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temp=args.output.with_name(args.output.name+'.tmp')
    with temp.open('x',encoding='utf-8') as handle:
        json.dump(report,handle,ensure_ascii=False,indent=2,allow_nan=False)
    temp.replace(args.output)
    print(report['state'])


if __name__=='__main__':main()
