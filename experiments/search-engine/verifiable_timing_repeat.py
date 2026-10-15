"""One preregistered all200 baseline timing repeat; no Gold or quality tuning."""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from ettin_cpu import sha


def main():
    parser = argparse.ArgumentParser()
    for name in ('workspace', 'comparison', 'source-metadata', 'pre-repeat', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    comparison = json.loads((args.comparison / 'registration.json').read_text())
    if comparison.get('status') != 'ALL outputs closed without Gold or quality grading':
        raise ValueError('original serial model measurements must finish first')
    prerepeat = json.loads(args.pre_repeat.read_text())
    if prerepeat['queries_sha256'] != comparison['public_cases_sha256']:
        raise ValueError('repeat belongs to other queries')
    for path, expected in comparison['source_files'].items():
        if sha(path) != expected:
            raise ValueError('frozen runtime/model/control changed')
    scripts = args.workspace / 'output/frozen/verifiable-pieces-v98/experiments/search-engine'
    frozen = args.workspace / 'output/frozen/cpu-rank-consensus-v97b'
    source = args.workspace / 'output/analysis/c-source-reindex-v66c'
    source_reg = json.loads((source / 'registration.json').read_text())
    roots = json.loads((args.source_metadata / 'roots.json').read_text())
    environment = dict(os.environ, PYTHONPATH=str(frozen / 'src') + os.pathsep + str(scripts),
        TOKENIZERS_PARALLELISM='false', HF_HUB_OFFLINE='1', OMP_NUM_THREADS='1',
        OPENBLAS_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1', CUDA_VISIBLE_DEVICES='')
    args.output.mkdir(parents=True, exist_ok=False)
    receipt = {'scope': 'ALL200 baseline timing repeat, original timing retained; unchanged cards/answers',
        'pre_repeat_sha256': sha(args.pre_repeat),
        'comparison_sha256': sha(args.comparison / 'registration.json'),
        'script_sha256': sha(__file__), 'workers': {}}
    for repo in sorted(comparison['closed_workers']['baseline']):
        original = source / 'indices' / (repo + '.db')
        if sha(original) != source_reg['source_repos'][repo]['new_source_index_sha256']:
            raise ValueError('source index changed')
        index = args.output / (repo + '-index.db')
        src = sqlite3.connect(f'file:{original}?mode=ro', uri=True)
        dst = sqlite3.connect(index)
        src.backup(dst)
        dst.close()
        src.close()
        output = args.output / repo
        command = [sys.executable, str(scripts / 'verifiable_cpu_run.py'),
            '--workspace', str(args.workspace), '--requests', str(args.comparison / ('requests-' + repo + '.jsonl')),
            '--root', roots[repo], '--index', str(index), '--output', str(output),
            '--source-metadata', str(args.source_metadata), '--catalog-receipt',
            str(args.workspace / 'output/analysis/verifiable-pieces-catalog-v98/receipt.json')]
        with (args.output / (repo + '-stdout.log')).open('w') as stdout, (
                args.output / (repo + '-stderr.log')).open('w') as stderr:
            subprocess.run(command, env=environment, cwd=args.workspace, stdout=stdout, stderr=stderr, check=True)
        pins = comparison['closed_workers']['baseline'][repo]
        for name in ('answers.jsonl', 'pools.jsonl'):
            if sha(output / name) != pins[name]:
                raise ValueError('repeat changed a fixed answer/pool; original retained')
        receipt['workers'][repo] = {name: sha(output / name)
            for name in ('answers.jsonl', 'pools.jsonl', 'performance.json')}
        (args.output / 'registration.json').write_text(json.dumps(receipt, indent=2))
        print(json.dumps({'repo': repo, 'unchanged_answers_and_pools': True}), flush=True)
        for suffix in ('', '-wal', '-shm'):
            path = Path(str(index) + suffix)
            if path.exists():
                path.unlink()
    receipt['status'] = 'ALL200 timing repeat closed; all original answers/pools exact'
    (args.output / 'registration.json').write_text(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
