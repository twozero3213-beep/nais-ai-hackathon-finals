"""[작성: 전문가4·7] 2026-09-27 case68 / 검증 가능한 로컬 논문 검색 CLI; 분석 실행 없음."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.research_corpus import build_corpus, validate_corpus, search_corpus, strict_json


# [작성: 전문가4·7] 2026-09-27 case68 / 무엇·왜: 빌드/검증/검색 재현 명령 / 입력·출력: CLI→JSON / 검증: 실제900.
# [수정:전문가4·7] 2026-09-27 case69 / 종류:검증방법추가 / 재현방법: CLI 확장 후보 조회 / 변경전: 기본 검색만 / 변경후: 표·경계·동의어 명시 flags / 왜: 재현 가능한 선택 / 영향: 미지정 기본값 유지.
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['build', 'verify', 'search'])
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--corpus', default='data/research_corpus/corpus.json')
    parser.add_argument('--query', default=''); parser.add_argument('--split', choices=['development', 'validation'], default='development')
    parser.add_argument('--mode', choices=['passages', 'bibliography'], default='passages')
    # [작성: 전문가4·7] 2026-09-27 case69 / 무엇·왜: 확장후보 명시옵션 / 입력·출력: CLI flags→search / 검증: 기본호환.
    parser.add_argument('--include-tables', action='store_true')
    parser.add_argument('--boundary-context', action='store_true')
    parser.add_argument('--expand-synonyms', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(); path = args.root / args.corpus
    if args.command == 'build':
        corpus = build_corpus(args.root); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(corpus, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        result = {'status': 'BUILT', **corpus['summary'], 'content_sha256': corpus['content_sha256']}
    else:
        corpus = strict_json(path.read_bytes())
        result = validate_corpus(corpus, args.root) if args.command == 'verify' else search_corpus(corpus, args.query, args.split, args.mode, root=args.root,include_tables=args.include_tables,boundary_context=args.boundary_context,expand_synonyms=args.expand_synonyms)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output: args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(text + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__': main()
