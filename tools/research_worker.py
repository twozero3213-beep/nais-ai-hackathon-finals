"""Run due case95 research tasks once; an external scheduler invokes this module."""
import argparse
import json
from core.research_tasks import TaskStore


# 2026-09-29 case95: native scheduler + transactional task claims, no resident loop.
# The worker records reports in the same store used by the app; no external messages.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', help='Use the app research task database path.')
    args = parser.parse_args()
    try:
        runs = TaskStore(args.db).run_due()
    except (Exception, KeyboardInterrupt):
        # case105: failures must reach the scheduler without printing private exception details.
        print(json.dumps({'status': 'FAILED', 'error_code': 'WORKER_FAILED'}, ensure_ascii=False))
        return 1
    failed = sum(run['status'] != 'CHECKED_PARTIAL' for run in runs)
    print(json.dumps({'status': 'FAILED' if failed else 'COMPLETED', 'processed': len(runs), 'failed': failed}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
