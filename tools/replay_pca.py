"""Replay an explicitly confirmed PCA claim against any UTF-8 CSV.

Usage: python tools/replay_pca.py --csv DATA.csv --contract CONTRACT.json
Exit 0: arithmetic match only; 1: arithmetic mismatch; 2: BLOCK.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.pca_verification import verify_pca_csv


# [작성: 전문가5] 2026-09-25 case60
# 무엇을: 임의 CSV의 명시 PCA 계약을 재계산하는 CLI / 왜: 논문별 계산 코드 없이 별도 실행 가능 / 입력·출력: CSV·JSON 경로 -> 결정적 JSON·종료 코드 / 검증: tests/test_case60_pca.py의 명세 부재 BLOCK 및 손계산 사례.
# [수정: 전문가4] 2026-09-25 case60
# 종류: 오류수정 | 재현 방법: 계약 JSON에 비UTF-8 바이트 입력 / 변경 전: traceback·종료 1 / 변경 후: BLOCK JSON·종료 2 / 왜: 잘못된 계약은 실행 실패보다 명시 차단되어야 함 / 영향: 정상 계약의 산술 결과 불변.
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', type=Path, required=True)
    parser.add_argument('--contract', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.contract is None:
        result = {'action': 'BLOCK', 'reason': '확인된 PCA 분석 계약이 필요합니다.',
                  'source_scope_verified': False, 'full_paper_reproduced': False}
    else:
        try:
            contract = json.loads(args.contract.read_text(encoding='utf-8'))
            result = verify_pca_csv(args.csv.read_bytes(), contract)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            result = {'action': 'BLOCK', 'reason': f'입력 파일 또는 JSON 오류: {type(error).__name__}',
                      'source_scope_verified': False, 'full_paper_reproduced': False}
    output = json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2) + '\n'
    if args.output:
        args.output.write_text(output, encoding='utf-8')
    print(output, end='')
    return {'ARITHMETIC_MATCH': 0, 'ARITHMETIC_MISMATCH': 1}.get(result['action'], 2)


if __name__ == '__main__':
    raise SystemExit(main())
