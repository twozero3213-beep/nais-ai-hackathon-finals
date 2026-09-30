"""[전문가4] 2026-09-27 case66: 기존 오프라인 검증기를 재사용하여 50+250+300의 분모·교차중복 검사."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys


# [전문가4] 2026-09-27 case66: CLI 검증을 먼저 통과해야 수량·중복 합계 검증으로 진행.
def verify(project):
    public = Path('data/public_papers')
    technical = Path('data/research_fields/technical')
    applied = Path('data/research_fields/applied')
    commands = [
        ['tools.collect_public_papers', '--verify-only', '--target', '50', '--output', str(public)],
        ['tools.collect_research_fields', '--verify-only', '--profile', 'technical', '--per-field', '50', '--output', str(technical), '--exclude-json', str(public / 'papers50.json')],
        ['tools.collect_research_fields', '--verify-only', '--profile', 'applied', '--per-field', '30', '--output', str(applied), '--exclude-json', str(public / 'papers50.json'), '--exclude-json', str(technical / 'papers.json')],
    ]
    for command in commands:
        subprocess.run([sys.executable, '-m', *command], cwd=project, check=True)
    spec = importlib.util.spec_from_file_location('public_collector', project / 'tools/collect_public_papers.py')
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)
    groups = [json.loads((project / public / 'papers50.json').read_text(encoding='utf-8'))]
    for profile, path in [('technical', technical), ('applied', applied)]:
        obj = json.loads((project / path / 'papers.json').read_text(encoding='utf-8'))
        assert obj['profile'] == profile
        groups.append(obj['papers'])
    assert [len(group) for group in groups] == [50, 250, 300]
    records = [row for group in groups for row in group]
    dois = [row['doi'].strip().lower().removeprefix('https://doi.org/') for row in records]
    assert len(dois) == len(set(dois)) == 600
    assert len({row['pmcid'].upper() for row in records}) == 600
    assert not set(dois) & {value.lower() for value in collector.EXCLUDED}
    assert all(row['raw_data_download_status'] == 'NOT_TESTED' for row in records)
    assert all(row.get('reproducibility_status', row.get('reproduction_status')) == 'NOT_TESTED' for row in records)
    return {'status': 'PASS', 'counts': {'public': 50, 'technical': 250, 'applied': 300}, 'unique_doi': 600, 'unique_pmcid': 600, 'excluded_old_dois': len(collector.EXCLUDED), 'raw_data_download': 'NOT_TESTED', 'reproduction': 'NOT_TESTED'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('project', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.project.resolve()), indent=2))
