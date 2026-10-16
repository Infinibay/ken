"""Materialize exact public revisions and reuse every original CORE query byte."""
from pathlib import Path
import argparse
import hashlib
import json

from native_sources_v235 import extract_revision, group_requests
from public_benchmarks_v222 import sha


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--archives', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    old, out = args.original.resolve(), args.out.resolve()
    original_registration = json.loads((old / 'core-registration.json').read_text())
    assert sha(old / 'core-requests.jsonl') == original_registration['requests_sha256']
    assert sha(old / 'core-sources.json') == original_registration['sources_sha256']
    rows = json.loads(args.archives.read_text())['rows']
    requests = [json.loads(x) for x in (old / 'core-requests.jsonl').read_text().splitlines()]
    groups = group_requests(requests, json.loads((old / 'core-sources.json').read_text()), rows)
    assert len(groups) == 11 and len(requests) == 18
    out.mkdir(exist_ok=False, parents=True)
    for group in groups:
        assert sha(Path(group['archive'])) == group['sha256']
        root = out / 'snapshots' / group['instance_id']
        group['source_pins'] = extract_revision(Path(group['archive']), root,
            group['repo'].split('/')[1] + '-' + group['base_commit'])
        assert len(group['source_pins']) == group['regular_files']
        group['root'] = str(root)
        group['query_sha256'] = hashlib.sha256(group['query'].encode()).hexdigest()
    (out / 'native-requests.json').write_text(json.dumps(groups, indent=2, ensure_ascii=False) + '\n')
    prior = json.loads((old / 'registration.json').read_text())
    value = {
        **{k: prior[k] for k in ('engine', 'engine_commit', 'engine_manifest_sha256')},
        'original_requests_sha256': sha(old / 'core-requests.jsonl'),
        'original_sources_sha256': sha(old / 'core-sources.json'),
        'native_requests_sha256': sha(out / 'native-requests.json'),
        'archive_manifest_sha256': sha(args.archives),
        'unique_queries': len(groups), 'level_cases': len(requests),
        'routes': {'symbols': {'scope': 'symbols', 'piece_kind': 'symbol'},
                   'files': {'scope': 'files', 'piece_kind': 'file'}},
        'query_text': 'Exact original CORE public bug report, unchanged across routes',
        'latency': 'One fixed unrelated warmup, then first original query per fresh route process; preparation and warmup separate; errors retained',
        'grading': 'L2 responsible preexisting code unit independently curated; L3 CORE positive context units/fragments. Exact source identity OR full specific anchor in faithful evidence; file-only separate. Native slots, no rescue or dedup.',
        'hardware': 'CPUExecutionProvider only; one native revision at a time',
        'concurrency': 'Other preexisting benchmark jobs may compete; timings not isolated',
        'reserve': 'CLOSED', 'release': False, 'engine_frozen': True,
        'code_executed_from_donors': False,
    }
    (out / 'registration.json').write_text(json.dumps(value, indent=2) + '\n')


if __name__ == '__main__':
    main()
