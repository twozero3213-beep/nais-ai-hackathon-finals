"""Re-run a registered calculation from an exported task report; no network or approvals."""
import argparse
import json
from pathlib import Path

from core.research_corpus import strict_json
from core.research_cases import run_case
from tools.change_impact import _digest


def replay_report(path):
    # Untrusted report selects only an allowlisted case; its paths/code are never executed.
    with Path(path).open('rb') as handle:
        raw = handle.read(256 * 1024 + 1)
    if len(raw) > 256 * 1024:
        raise ValueError('REPORT_TOO_LARGE')
    report = strict_json(raw)
    calculation = report['latest_run']['calculation']
    provenance = calculation['provenance']
    if not provenance or report.get('case_id') != calculation['case_id']:
        raise ValueError('REPORT_BINDING_MISSING')
    result = run_case(calculation['case_id'], expected_provenance=provenance)
    # Comparing fresh rows detects changed/tampered historical values without trusting them.
    return {'case_id': result['case_id'], 'approved': False, 'fresh_calculation': result,
            # Exact JSON replay preserves bool/int/float types; no new numerical tolerance here.
            'historical_rows_match': _digest(result['rows']) == _digest(calculation['rows']),
            'scope': 'Local registered arithmetic only; not paper truth or human approval.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    try:
        result = replay_report(args.report)
    except (ValueError, OSError, KeyError, TypeError, UnicodeError, RecursionError):
        print(json.dumps({'status':'BLOCKED', 'approved':False,
                          'reason':'보고서 형식·입력 지문·등록 조건을 확인하지 못했습니다.'}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    good_rows = bool(result['fresh_calculation']['rows']) and all(
        row.get('status') in {'ARITHMETIC_MATCH','COEFFICIENT_MATCH'} for row in result['fresh_calculation']['rows'])
    return 0 if good_rows and result['historical_rows_match'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
