"""Capture ALL native decisions with closed-pool parity before any Gold analysis."""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import time

import ken
from ken.bench.source_receipts import verify_frozen_source
from ettin_cpu import sha
from verifiable_guard import verify_source_preparation
from verifiable_pieces import canonical


def main():
    parser=argparse.ArgumentParser()
    for name in ('workspace','comparison','public-cases','source-metadata','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    roots,preparation=verify_source_preparation(args.workspace,args.source_metadata)
    engine=Path(ken.__file__).resolve().parents[2]
    source_receipt=verify_frozen_source(engine)
    previous=json.loads((args.comparison/'registration.json').read_text())
    if previous['status']!='ALL outputs closed without Gold or quality grading':
        raise ValueError('closed native comparison required')
    if sha(args.public_cases)!=previous['public_cases_sha256']:
        raise ValueError('public queries changed')
    for path,expected in previous['source_files'].items():
        if sha(path)!=expected:raise ValueError('closed model/source input changed')
    cases=[json.loads(line) for line in args.public_cases.read_text().splitlines()]
    if len(cases)!=200 or len({c['id'] for c in cases})!=200:
        raise ValueError('ALL200 unique development cases required')
    pins={str(args.public_cases.resolve()):sha(args.public_cases),
          str((args.comparison/'registration.json').resolve()):sha(args.comparison/'registration.json')}
    for repo,files in previous['closed_workers']['baseline'].items():
        path=args.comparison/'baseline'/repo/'pools.jsonl'
        if sha(path)!=files['pools.jsonl']:raise ValueError('native pool changed')
        pins[str(path.resolve())]=sha(path)
    args.output.mkdir(parents=True,exist_ok=False)
    registration={'scope':'Native actual feature/branch diagnostics only; unchanged ranking, no Gold or quality selection',
        'source_receipt':source_receipt,'base_source_preparation':preparation,'input_pins':pins,
        'status':'registered before query replay','closed':{},'queries':200,
        'policy':'ALL200 exact complete v114 pool digests; all owners and canonical piece groups; no neural reranker; no expected answer in runtime',
        'timing_scope':'diagnostic capture pipeline; excludes trace export; no local-call enrichment or default-latency certification'}
    (args.output/'registration.json').write_text(json.dumps(registration,indent=2))
    for repo in sorted({c['repo_id'] for c in cases}):
        requests=args.output/('requests-'+repo+'.jsonl')
        requests.write_text(''.join(canonical(c)+'\n' for c in cases if c['repo_id']==repo))
        target=args.output/repo
        command=[sys.executable,str(Path(__file__).with_name('verifiable_cpu_run.py')),
                 '--workspace',str(args.workspace),'--requests',str(requests),
                 '--root',roots[repo],'--index',str(args.workspace/'output/analysis/c-source-reindex-v66c/indices'/(repo+'.db')),
                 '--output',str(target),'--catalog-receipt',str(args.workspace/'output/analysis/verifiable-pieces-catalog-v98/receipt.json'),
                 '--source-metadata',str(args.source_metadata),'--expected-pools',str(args.comparison/'baseline'/repo/'pools.jsonl'),
                 '--capture-ranking']
        started=time.perf_counter()
        with (args.output/(repo+'-stdout.log')).open('w') as stdout,(args.output/(repo+'-stderr.log')).open('w') as stderr:
            result=subprocess.run(command,stdout=stdout,stderr=stderr,check=False)
        print(json.dumps({'repo':repo,'returncode':result.returncode,'wall_ms':(time.perf_counter()-started)*1000}),flush=True)
        if result.returncode:raise ValueError('diagnostic worker failed: '+repo)
        performance=json.loads((target/'performance.json').read_text())
        traces=target/'ranking-traces.jsonl'
        if sha(traces)!=performance['ranking_trace_sha256']:
            raise ValueError('trace output changed')
        ids=[json.loads(line)['id'] for line in traces.open()]
        if set(ids)!={c['id'] for c in cases if c['repo_id']==repo} or len(ids)!=len(set(ids)):
            raise ValueError('incomplete or duplicate diagnostic output')
        registration['closed'][repo]={name:sha(target/name) for name in
            ('answers.jsonl','pools.jsonl','performance.json','ranking-traces.jsonl')}
    for path,expected in pins.items():
        if sha(path)!=expected:raise ValueError('registered input changed during replay')
    if verify_frozen_source(engine)!=source_receipt:
        raise ValueError('instrumented producer changed during replay')
    registration['status']='ALL200 native ranking traces closed without Gold'
    (args.output/'registration.json').write_text(json.dumps(registration,indent=2))
    print(json.dumps({'queries':200,'status':registration['status'],
                      'registration_sha256':sha(args.output/'registration.json')}),flush=True)


if __name__=='__main__':main()
