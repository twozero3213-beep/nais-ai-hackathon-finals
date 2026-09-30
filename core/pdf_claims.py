"""PDF claim extraction for case18.

The extractor is intentionally auditable and local: it preserves page number and source
sentence. It recognizes percentages, p-values and confidence-interval/significance language.
A future LLM extractor can replace candidate generation without changing verification.
"""
import io,re,math
from html.parser import HTMLParser
from pypdf import PdfReader
MAX_PDF_BYTES=50*1024*1024
MAX_PDF_PAGES=1000
MAX_PDF_TEXT_CHARS=10_000_000
PCT=re.compile(r'(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%')
# [수정: 0 이영 · Codex] 2026-09-30T22:51:29+09:00 — C08: 지수 전체와 부등호를 보존하며 잘린 숫자 토큰은 후보로 사용하지 않는다.
NUMBER=r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
NUMBER_END=r'(?![\w%]|\.\d)'
PVAL=re.compile(r'\bp\s*(<=|>=|[=<>≤≥])\s*('+NUMBER+r')'+NUMBER_END,re.I)
CORR=re.compile(r'\b(?:Pearson\s*)?r\s*=\s*(-?\d+(?:\.\d+)?)',re.I)
ORR=re.compile(r'\b(?:odds ratio|OR)\s*(?:of|=|:)\s*(-?\d+(?:\.\d+)?)',re.I)
BETA=re.compile(r'\b(?:age\s+)?coefficient\s*(?:was|=|:)\s*(-?\d+(?:\.\d+)?)',re.I)
# [수정: 전문가7] 2026-09-25 case47
# 종류: 오류수정 / 재현 방법: 95% CI from -0.4 to -0.1에서 구간 수치 누락 / 변경 전: 쉼표·대시 구분만 지원 / 변경 후: from/to와 confidence interval 표현 지원 / 왜: 명시된 구간을 후보에 보존 / 영향: 사람 확인 전 실행은 여전히 차단.
# [수정: 0 이영 · Codex] 2026-09-30T22:51:29+09:00 — C08: 명시된 신뢰수준·구간을 보존하고 99%/미상 구간을 ci95로 바꾸지 않는다.
CI=re.compile(r'(?:(?P<level>\d+(?:\.\d+)?)\s*%\s*)?(?:\bCI\b|confidence interval|신뢰구간)\s*(?:[:=]|from)?\s*[\[(]?\s*(?P<low>'+NUMBER+r')\s*(?:[,~–-]|to)\s*(?P<high>'+NUMBER+r')'+NUMBER_END,re.I)
ROWS=re.compile(r'(?<!\d)(\d[\d,]*)\s+(?:individual\s+penguins?|observations?|samples?|rows?)\b',re.I)
# [수정: 전문가7] 2026-09-25 case45
# 종류: 오류수정 / 재현 방법: R Journal HTML의 수식 n missing = 19가 후보에서 빠짐 / 변경 전: nmissing만 허용 / 변경 후: n missing·n_missing도 허용 / 왜: HTML 수식 공백 변환 / 영향: 결측 Claim은 여전히 사람 확인 전 차단.
MISSING_CELLS=re.compile(r'missing\s+values?.{0,70}?\bn(?:[\s_]*\{?missing\}?)?\s*=\s*(\d[\d,]*)',re.I)
# [수정: 전문가7] 2026-09-25 case46
# 종류: 오류수정 / 재현 방법: 그림 범례의 별표 p 임계값이 논문 주장으로 추출 / 변경 전: p값 후보 / 변경 후: 연속 범례 패턴 제외 / 왜: 실행 불가 표기 설명은 정량 Claim 아님 / 영향: 실제 사례 후보 수·위치 갱신.
SIGNIFICANCE_KEY=re.compile(r'(?:^|[;:])\s*\*+\s*p\s*[<=>]\s*0?\.\d+\s*;\s*\*+\s*p\s*[<=>]\s*0?\.\d+',re.I)


# [작성: 전문가7] 2026-09-25 case45
# 무엇을: extract_html_blocks / 왜: 원문 PDF를 새로 만들지 않고 공개 논문의 전체 HTML 문단·표를 검증 입력으로 사용 / 입력·출력: HTML bytes -> 위치 번호·텍스트 / 검증: tests/test_case45.py의 문단 위치와 실제 R Journal 원문.
def extract_html_blocks(data:bytes):
    class Blocks(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.active='';self.ignore=0;self.parts=[];self.blocks=[]
        def handle_starttag(self,tag,attrs):
            if tag in {'script','style','svg'}:self.ignore+=1
            if not self.ignore and not self.active and tag in {'p','tr','li','h1','h2','h3','h4','figcaption'}:
                self.active=tag;self.parts=[]
        def handle_data(self,value):
            if self.active and not self.ignore:self.parts.append(value)
        def handle_endtag(self,tag):
            if tag in {'script','style','svg'}:self.ignore=max(0,self.ignore-1)
            if tag==self.active:
                value=' '.join(' '.join(self.parts).split())
                if len(value)>=6:self.blocks.append(value)
                self.active='';self.parts=[]
    parser=Blocks()
    parser.feed(data.decode('utf-8-sig',errors='replace'))
    return list(enumerate(parser.blocks,start=1))

def extract_pdf_pages(data:bytes):
    if len(data)>MAX_PDF_BYTES: raise ValueError("PDF exceeds byte limit")
    r=PdfReader(io.BytesIO(data))
    if len(r.pages)>MAX_PDF_PAGES: raise ValueError("PDF exceeds page limit")
    out=[]; total=0
    for i,p in enumerate(r.pages):
        text=p.extract_text() or ""; total+=len(text)
        if total>MAX_PDF_TEXT_CHARS: raise ValueError("PDF extracted text exceeds limit")
        out.append((i+1,text))
    return out

def extract_pdf_text(data:bytes)->str:return "\n".join(t for _,t in extract_pdf_pages(data))

def _sentences(text):
    """Reconstruct wrapped PDF lines before sentence splitting.

    case20 BUGFIX: PDF line wrapping separated a Welch-test parenthesis from its claim.
    Joining whitespace first preserves one executable claim while decimal points remain safe.
    """
    normalized=" ".join(str(text).split())
    parts=re.split(r'(?<=[!?])\s+(?=[A-Z0-9가-힣])|(?<=\.)\s+(?=[A-Z가-힣])',normalized)
    return [x.strip() for x in parts if len(x.strip())>=6]

# [수정: 전문가7] 2026-09-25 case46
# 종류: 오류수정 / 재현 방법: 한 문장 두 백분율 중 첫 값만 후보가 되고 긴 원문은 잘림 / 변경 전: 한 값·300자 / 변경 후: 서로 다른 값 각각과 전체 문장 보존 / 왜: 원문 대응 누락 방지 / 영향: 후보 수 14→16, 후보가 곧 검증 성공은 아님.
def extract_numeric_claims(source,limit:int=50):
    pages=source if isinstance(source,list) else [(1,str(source))];out=[]
    for page,text in pages:
        for sent in _sentences(text):
            if SIGNIFICANCE_KEY.search(sent):continue
            # [수정: 전문가7] 2026-09-25 case47
            # 종류: 오류수정 / 재현 방법: 95% CI의 신뢰수준 95를 효과 백분율 Claim으로 추출 / 변경 전: 모든 %를 효과값으로 취급 / 변경 후: CI 바로 앞 신뢰수준은 값 후보에서 제외 / 왜: 방법 정보와 결과값 분리 / 영향: 정상 효과 백분율은 계속 후보.
            pcts=[m.group(1) for m in PCT.finditer(sent) if not re.match(r'\s*(?:CI\b|confidence interval\b|신뢰구간)',sent[m.end():],re.I)]
            pv=PVAL.search(sent);ci=CI.search(sent);corr=CORR.search(sent);orr=ORR.search(sent);beta=BETA.search(sent)
            # [수정: 0 이영 · Codex] 2026-09-30T22:51:29+09:00 — C08: 확률 범위와 유한 구간을 확인하되 원문·쪽은 그대로 유지한다.
            if pv and not (math.isfinite(float(pv.group(2))) and 0<=float(pv.group(2))<=1):pv=None
            bounds=(float(ci.group('low')),float(ci.group('high'))) if ci else None
            level=float(ci.group('level')) if ci and ci.group('level') else None
            if bounds and not all(math.isfinite(v) for v in bounds):ci=None;bounds=None;level=None
            rows=ROWS.search(sent);missing_cells=MISSING_CELLS.search(sent)
            low=sent.lower()
            # case24 BLIND-03 BUGFIX — WHY: headings/data notes that merely mention 'regression' and
            # PDF-extracted table blobs are not standalone quantitative claims. Fail closed rather
            # than manufacture a contract from layout noise.
            if 'results table' in low: continue
            # [수정: 전문가7] 2026-09-23
            # 종류: 검증방법추가
            # 변경 전: r=... 또는 p-value가 없는 자연어 상관 Claim은 추출 대상에서 빠질 수 있었음.
            # 변경 후: correlation/correlated/상관 표현도 inferential Claim 후보로 추출.
            # 왜: 실제 공개 논문의 방향성 상관 문장을 PDF 전체 extraction benchmark에 포함하기 위함.
            # 영향: 후보 수가 늘 수 있으므로 최종 실행은 Human Confirmation + fail-closed 규칙을 유지.
            inferential_marker=(corr or orr or beta or pv or ci or 'significant' in low or '유의' in low or 'correlation' in low or 'correlated' in low or '상관' in low or 'all subgroups' in low or 'all timepoints' in low)
            if not (pcts or inferential_marker or rows or missing_cells):continue
            # [수정: 전문가7] 2026-09-25 case45
            # 종류: 검증방법추가 / 재현 방법: 344 observations와 n_missing=19가 후보에서 빠짐 / 변경 전: 퍼센트·추론 수치만 추출 / 변경 후: 전체 행·결측 셀 수를 독립 Claim 후보로 보존 / 왜: 원문 분모 확인 / 영향: 사람 범위 확인 전 실행은 계속 차단.
            # [수정: 전문가7] 2026-09-25 case47
            # 종류: 오류수정 / 재현 방법: 95% CI가 검출돼도 95% 때문에 CI 후보가 사라짐 / 변경 전: 백분율 존재 시 CI 무시 / 변경 후: CI 후보를 백분율과 독립 보존 / 왜: 구간 근거 누락 방지 / 영향: 원문 문장·위치 보존.
            primary=("row_count",float(rows.group(1).replace(',',''))) if rows else (("missing_cells",float(missing_cells.group(1).replace(',',''))) if missing_cells else (("confidence_interval" if ci else ("p_value" if pv else "inferential"),None) if (not pcts or ci) else None))
            values=([primary] if primary else [])+[("percentage",float(p)) for p in dict.fromkeys(pcts)]
            for kind,value in values:
                out.append({"claim_id":f"C-{len(out)+1:02d}","text":sent,"value":value,"page":page,"claim_type":kind,"p_value":float(pv.group(2)) if pv else None,"p_operator":{"≤":"<=","≥":">="}.get(pv.group(1),pv.group(1)) if pv else "","reported_effect":float(corr.group(1)) if corr else (float(orr.group(1)) if orr else (float(beta.group(1)) if beta else None)),"effect_kind":"correlation_r" if corr else ("odds_ratio" if orr else ("regression_coefficient" if beta else "")),"reported_ci":bounds,"confidence_level":level,"ci95":bounds if level==95 else None})
                if len(out)>=limit:return out
    return out
