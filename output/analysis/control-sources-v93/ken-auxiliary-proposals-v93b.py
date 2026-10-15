"""Seal all96 public251 inference pools before auxiliary training references."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import ken
R = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
E = Path(ken.__file__).resolve().parents[2]
from ken.bench.source_receipts import verify_frozen_source


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


parser = argparse.ArgumentParser()
for name in ('source', 'requests', 'output'):
    parser.add_argument('--'+name, type=Path, required=True)
for name in ('source-registration-sha256', 'requests-sha256'):
    parser.add_argument('--'+name, required=True)
args = parser.parse_args()
S = args.source; O = args.output
receipt = verify_frozen_source(E)
assert receipt == '4ebee803348ded840b948be0912e58924faf6ae218cd107d1cbb6963cd2f892d'
worker = Path('/private/tmp/ken-auxiliary-features-worker-v93b.py')
assert sha(worker) == 'eea1bbdae068245e78906f92e79e7c391e6a3bc4d1e12a2c31ed80b35af8b97d'
assert sha(S/'registration.json') == args.source_registration_sha256
source = json.loads((S/'registration.json').read_text())
assert source['complete'] and source['engine_receipt'] == receipt
assert source['script_sha256'] == '48809026d6ea68306c64605a708d2dd51c21ab8a70c4a0f0be175f95c9c0ee61'
assert len(source['source_repos']) == len(source['context_repos']) == len(source['views_repos']) == 8
assert all(sha(path) == digest for path, digest in source['inputs'].items())
assert args.requests.resolve().is_relative_to(Path('/private/tmp/ken-search-auxiliary-training-20261015').resolve())
assert sha(args.requests) == args.requests_sha256
rows = list(map(json.loads, args.requests.read_text().splitlines()))
assert len(rows) == len({r['id'] for r in rows}) == 96
assert all(set(r) == {'id', 'repo_id', 'request'} for r in rows)
assert all(set(r['request']) == {'query', 'purpose', 'target', 'limit', 'max_chars'} and
    r['request']['purpose'] == 'auto' and r['request']['target'] == 'symbol' and
    r['request']['limit'] == 10 and r['request']['max_chars'] == 12000 and
    isinstance(r['request']['query'], str) and r['request']['query'].strip() for r in rows)
assert {r['repo_id'] for r in rows} == set(source['source_repos'])
assert all(sum(r['repo_id'] == repo for r in rows) == 12 for repo in source['source_repos'])
O.mkdir(exist_ok=False)
for name in ('requests', 'workers', 'indices'):
    (O/name).mkdir()
manifest = {'scope': 'ALL96 sealed auxiliary publicrequests and unchanged live251features before label preparation; no numericmodel or references',
    'engine_receipt': receipt, 'script_sha256': sha(__file__), 'worker_sha256': sha(worker),
    'source_registration_sha256': args.source_registration_sha256, 'source_root': str(S),
    'inputs': {str(args.requests): args.requests_sha256, str(S/'registration.json'): args.source_registration_sha256},
    'source_repos': source['source_repos'], 'repos': {}, 'source_phase_complete': True}
for repo in sorted(source['source_repos']):
    path = S/'indices'/f'{repo}.db'; expected = source['source_repos'][repo]['new_source_index_sha256']
    assert sha(path) == expected
    shutil.copyfile(path, O/'indices'/f'{repo}.db'); assert sha(O/'indices'/f'{repo}.db') == expected
(O/'registration.json').write_text(json.dumps(manifest, indent=2))
environment = dict(os.environ, PYTHONPATH=str(E/'src'), KEN_INDEX_WORKERS='0', HF_HUB_OFFLINE='1',
    OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1', TOKENIZERS_PARALLELISM='false', CUDA_VISIBLE_DEVICES='')
with (O/'candidates.jsonl').open('w') as output:
    for repo in sorted(source['source_repos']):
        public = [row for row in rows if row['repo_id'] == repo]
        request_file = O/'requests'/f'{repo}.jsonl'
        request_file.write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in public))
        folder = O/'workers'/repo; started = time.perf_counter()
        with (O/'workers'/f'{repo}-stdout.log').open('w') as stdout, (O/'workers'/f'{repo}-stderr.log').open('w') as stderr:
            result = subprocess.run([sys.executable, str(worker), '--source', str(S), '--repo', repo,
                '--source-registration-sha256', args.source_registration_sha256, '--requests', str(request_file),
                '--requests-sha256', sha(request_file), '--output', str(folder)], env=environment, stdout=stdout, stderr=stderr)
        if result.returncode:
            raise RuntimeError(f'auxiliary93 worker {repo} exited {result.returncode}; no query exclusion, partial artifacts retained')
        saved = list(map(json.loads, (folder/'candidates.jsonl').read_text().splitlines()))
        assert len(saved) == len({row['id'] for row in saved}) == 12
        assert {row['id'] for row in saved} == {row['id'] for row in public}
        output.write((folder/'candidates.jsonl').read_text()); output.flush()
        shutil.copyfile(folder/'features.npz', O/f'{repo}.npz')
        worker_record = json.loads((folder/'registration.json').read_text())
        assert worker_record['complete'] and worker_record['engine_receipt'] == receipt
        manifest['repos'][repo] = {'queries': 12, 'rows': sum(len(row['candidates']) for row in saved),
            'requests_sha256': sha(request_file), 'features_sha256': sha(O/f'{repo}.npz'),
            'worker_registration_sha256': sha(folder/'registration.json'), 'exit_code': result.returncode,
            'ms': (time.perf_counter()-started)*1000}
        (O/'registration.json').write_text(json.dumps(manifest, indent=2))
        print(json.dumps({'prepared_repository': repo, 'queries': 12, 'rows': manifest['repos'][repo]['rows']}), flush=True)
assert len(manifest['repos']) == 8
assert all(sha(path) == digest for path, digest in manifest['inputs'].items())
assert verify_frozen_source(E) == receipt and sha(worker) == manifest['worker_sha256']
manifest.update(complete=True, candidates_sha256=sha(O/'candidates.jsonl'))
(O/'registration.json').write_text(json.dumps(manifest, indent=2))
