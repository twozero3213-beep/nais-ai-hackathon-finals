"""case95 discovery starting points, not an exhaustive academic classification.

Each query is a bounded sample from Crossref, never coverage of an entire field.
User keywords remain unrestricted to this list. No popularity/quality ranking.
"""

# [작성: 문헌 범위 담당] 2026-09-29 case95 / 6개 예시 한계→30 세부분야 / UI와 정기수집이 같은 목록 재사용.
FIELDS = {
    'mathematics': {'group':'자연과학','label':'수학·통계','query':'mathematics statistics'},
    'physics': {'group':'자연과학','label':'물리·천문','query':'physics astronomy'},
    'chemistry': {'group':'자연과학','label':'화학','query':'chemistry'},
    'biology': {'group':'자연과학','label':'생명과학·유전학','query':'biology genetics'},
    'earth': {'group':'자연과학','label':'지구·기후·환경','query':'earth climate environment'},
    'computing': {'group':'공학·기술','label':'컴퓨터·AI·보안','query':'computer artificial intelligence cybersecurity'},
    'electrical': {'group':'공학·기술','label':'전기·전자·통신','query':'electrical electronics telecommunications'},
    'mechanical': {'group':'공학·기술','label':'기계·로봇·항공','query':'mechanical robotics aerospace'},
    'civil': {'group':'공학·기술','label':'건축·토목·도시','query':'civil engineering architecture urban'},
    'materials': {'group':'공학·기술','label':'소재·화공·에너지','query':'materials chemical engineering energy'},
    'basic_medicine': {'group':'의약·보건','label':'기초의학','query':'biomedical physiology pathology'},
    'clinical': {'group':'의약·보건','label':'임상의학·치의학','query':'clinical medicine dentistry'},
    'health': {'group':'의약·보건','label':'공중보건·간호','query':'public health nursing'},
    'pharmacy': {'group':'의약·보건','label':'약학·약물개발','query':'pharmacology drug discovery'},
    'psychology': {'group':'의약·보건','label':'심리·뇌과학','query':'psychology neuroscience'},
    'agriculture': {'group':'농수·식품','label':'농업·작물','query':'agriculture crop science'},
    'food': {'group':'농수·식품','label':'식품·영양','query':'food science nutrition'},
    'forestry': {'group':'농수·식품','label':'산림·생태','query':'forestry ecology'},
    'veterinary': {'group':'농수·식품','label':'수의·축산','query':'veterinary animal science'},
    'marine': {'group':'농수·식품','label':'해양·수산','query':'marine science fisheries'},
    'economy': {'group':'사회과학','label':'경제·금융','query':'economics finance'},
    'business': {'group':'사회과학','label':'경영·조직','query':'business management organization'},
    'education': {'group':'사회과학','label':'교육·학습','query':'education learning'},
    'society': {'group':'사회과학','label':'사회·미디어','query':'sociology communication media'},
    'law': {'group':'사회과학','label':'법·정치·행정','query':'law political science public administration'},
    'history': {'group':'인문·예술','label':'역사·고고학','query':'history archaeology'},
    'language': {'group':'인문·예술','label':'언어·문학','query':'linguistics literature'},
    'philosophy': {'group':'인문·예술','label':'철학·윤리','query':'philosophy ethics'},
    'culture': {'group':'인문·예술','label':'종교·문화','query':'religion cultural studies'},
    'arts': {'group':'인문·예술','label':'예술·디자인·음악','query':'arts design music'},
}
