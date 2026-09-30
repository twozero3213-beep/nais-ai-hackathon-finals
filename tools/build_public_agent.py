"""case105 build only the four whitelisted public discovery snapshots."""
import json
import argparse
from core.public_agent import build_public_files, public_handoff_text

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--handoff-text', action='store_true',
                        help='Print the verified existing four-file AI handoff without rebuilding.')
    args = parser.parse_args()
    if args.handoff_text:
        print(public_handoff_text(), end='')
    else:
        print(json.dumps(build_public_files(), sort_keys=True))
