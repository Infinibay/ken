"""Serial public-only comparison orchestrator. Never opens a Gold path."""
from __future__ import annotations
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from ettin_cpu import sha


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--public-cases',type=Path,required=True)
    p.add_argument('--source-metadata',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--reuse-baseline',type=Path)
    p.add_argument('--baseline-only',action='store_true')
    p.add_argument('--local-call-evidence',action='store_true')
    p.add_argument('--preflight',action='store_true');args=p.parse_args()
    if args.baseline_only and args.reuse_baseline:
        p.error('--baseline-only regenerates cards and cannot reuse an earlier baseline')
    arms=('baseline',) if args.baseline_only else ('baseline','17m','32m','68m')
    w=args.workspace.resolve();frozen=w/'output/frozen/cpu-rank-consensus-v97b'
    args.output.mkdir(parents=True,exist_ok=False)
    scripts=Path(__file__).parent
    source_files=[scripts/n for n in ('verifiable_compare.py','verifiable_cpu_run.py',
        'verifiable_pieces.py','ettin_cpu.py','cpu-verifiable-pieces-v98.md',
        'contextual_run.py','source_view_assets.py','verifiable_catalog.py','test_verifiable_pieces.py',
        'verifiable_guard.py','verifiable_grading.py','verifiable_blind_inputs.py',
        'verifiable_report.py','test_verifiable_grading.py','test_verifiable_owned_definitions.py',
        'test_verifiable_evidence_budget.py','verifiable_dependencies.py',
        'test_verifiable_dependencies.py','test_verifiable_scope_evidence.py',
        'verifiable-lexical-scope-v114.md')]
    source_files += [w/'output/models/ettin-all-onnx-v98'/size/'assembly.json'
                     for size in ('17m','32m','68m')]
    source_files += [w/'output/analysis/verifiable-pieces-catalog-v98/receipt.json',
        w/'output/analysis/c-source-reindex-v66c/registration.json',
        w/'output/analysis/c-source-reindex-v66c/context-registration.json',
        w/'output/analysis/source7-context-views-ranking-v69/registration.json',
        w/'output/models/static-comparison-registration.json',
        w/'output/models/es-en-cpu-registration-v21.json',
        w/'output/models/cpu-context-registration-v42.json']
    pins={str(path.resolve()):sha(path) for path in source_files}
    sys.path.insert(0,str(frozen/'src'))
    from verifiable_guard import verify_source_preparation
    roots,preparation=verify_source_preparation(w,args.source_metadata)
    # No public query bytes are opened until the complete source guard succeeds.
    cases=[json.loads(x) for x in args.public_cases.read_text().splitlines()]
    if not args.preflight:
        from collections import Counter
        assert len(cases)==200 and len({c['id'] for c in cases})==200
        assert Counter(c['target_kind'] for c in cases)==dict.fromkeys(('class','module','symbol','file'),50)
        for kind in ('class','module','symbol','file'):
            rows=[c for c in cases if c['target_kind']==kind]
            assert Counter(c['language'] for c in rows)=={'en':30,'es':20}
            assert Counter(c['query_style'] for c in rows)=={'behavior':40,'qualified_lookup':10}
    engine_receipt=sha(frozen/'SOURCE-MANIFEST.json')
    metadata={'scope':'public-only ALL cases selected arms, serial full prepared pipeline',
        'public_cases_sha256':sha(args.public_cases),'source_metadata_sha256':sha(args.source_metadata/'manifest.json'),
        'engine_manifest_sha256':engine_receipt,'preparation':preparation,
        'source_files':pins,'preflight':args.preflight,'arms':arms,'runs':[],
        'local_call_evidence':args.local_call_evidence}
    (args.output/'registration.json').write_text(json.dumps(metadata,indent=2))
    environment=dict(os.environ,PYTHONPATH=str(frozen/'src')+os.pathsep+str(scripts.resolve()),
        TOKENIZERS_PARALLELISM='false',HF_HUB_OFFLINE='1',OMP_NUM_THREADS='1',
        OPENBLAS_NUM_THREADS='1',VECLIB_MAXIMUM_THREADS='1',CUDA_VISIBLE_DEVICES='')
    source=w/'output/analysis/c-source-reindex-v66c'
    source_reg=json.loads((source/'registration.json').read_text())
    repos=sorted({c['repo_id'] for c in cases})
    # A previously closed byte-exact baseline may be reused for an adapter-only
    # correction. Its original timing and provenance remain explicitly labeled.
    schedule=[('baseline',r) for r in repos]
    if args.reuse_baseline:
        prior=json.loads((args.reuse_baseline/'registration.json').read_text())
        if (prior.get('status')!='ALL outputs closed without Gold or quality grading'
            or prior['public_cases_sha256']!=metadata['public_cases_sha256']
            or prior.get('local_call_evidence',False)!=args.local_call_evidence
            or prior['engine_manifest_sha256']!=engine_receipt):
            raise ValueError('incompatible closed baseline')
        for path,value in prior['source_files'].items():
            if sha(path)!=value:raise ValueError('prior baseline control changed')
        for repo in repos:
            out=args.output/'baseline'/repo;out.mkdir(parents=True,exist_ok=False)
            for name,value in prior['closed_workers']['baseline'][repo].items():
                src=args.reuse_baseline/'baseline'/repo/name
                if sha(src)!=value:raise ValueError('prior baseline output changed')
                shutil.copyfile(src,out/name)
        metadata['baseline_reuse']={'source_comparison_sha256':sha(args.reuse_baseline/'registration.json'),
            'scope':'unchanged baseline answers/pools and ORIGINAL timing reused; no new baseline timing claimed'}
        schedule=[]
        (args.output/'registration.json').write_text(json.dumps(metadata,indent=2))
    for i,repo in enumerate(repos):
        if args.baseline_only:break
        sizes=['17m','32m','68m'];sizes=sizes[i%3:]+sizes[:i%3]
        schedule.extend((size,repo) for size in sizes)
    for arm,repo in schedule:
        out=args.output/arm/repo;out.parent.mkdir(parents=True,exist_ok=True)
        requestfile=args.output/('requests-'+repo+'.jsonl')
        if not requestfile.exists():requestfile.write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n'
            for c in cases if c['repo_id']==repo))
        original=source/'indices'/(repo+'.db')
        if sha(original)!=source_reg['source_repos'][repo]['new_source_index_sha256']:
            raise ValueError('original source index changed')
        index=out.parent/(repo+'-index.db')
        src=sqlite3.connect(f'file:{original}?mode=ro',uri=True);dst=sqlite3.connect(index)
        src.backup(dst);dst.close();src.close()
        command=[sys.executable,str(scripts/'verifiable_cpu_run.py'),'--workspace',str(w),
            '--requests',str(requestfile),'--root',roots[repo],'--index',str(index),
            '--output',str(out),'--source-metadata',str(args.source_metadata),
            '--catalog-receipt',str(w/'output/analysis/verifiable-pieces-catalog-v98/receipt.json')]
        if args.local_call_evidence:command+=['--local-call-evidence']
        if arm!='baseline':command+=['--model',str(w/'output/models/ettin-all-onnx-v98'/arm/'assembly.json'),
            '--expected-pools',str(args.output/'baseline'/repo/'pools.jsonl')]
        start=time.perf_counter()
        with (out.parent/(repo+'-stdout.log')).open('w') as stdout,(out.parent/(repo+'-stderr.log')).open('w') as stderr:
            result=subprocess.run(command,env=environment,cwd=w,stdout=stdout,stderr=stderr)
        metadata['runs'].append({'arm':arm,'repo':repo,'returncode':result.returncode,
                                'wall_ms':(time.perf_counter()-start)*1000})
        (args.output/'registration.json').write_text(json.dumps(metadata,indent=2))
        print(json.dumps(metadata['runs'][-1]),flush=True)
        if result.returncode:raise RuntimeError('worker failed; preserved run/logs '+str(out))
        for path,value in pins.items():
            if sha(path)!=value:raise ValueError('producer changed during registered run')
        # Disposable copied indexes are not research evidence; their original pin is retained.
        for suffix in ('','-wal','-shm'):
            path=Path(str(index)+suffix)
            if path.exists():path.unlink()
    for arm in arms:
        rows=[];timings=[];resources=[]
        for repo in repos:
            out=args.output/arm/repo
            rows.extend(map(json.loads,(out/'answers.jsonl').read_text().splitlines()))
            perf=json.loads((out/'performance.json').read_text());timings.extend(perf['timings'])
            resources.append({k:perf[k] for k in ('repo','indexed_files','asset_load_ms','warmup_ms',
                                                  'peak_rss_native','rss_unit','heavy_imports')})
        assert len(rows)==len(cases) and {r['id'] for r in rows}=={c['id'] for c in cases}
        path=args.output/arm/'answers.jsonl';path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
        (args.output/arm/'performance.json').write_text(json.dumps({'timings':timings,'processes':resources},indent=2))
    metadata['closed']={arm:{'answers_sha256':sha(args.output/arm/'answers.jsonl'),
        'performance_sha256':sha(args.output/arm/'performance.json')} for arm in arms}
    metadata['closed_workers']={arm:{repo:{name:sha(args.output/arm/repo/name)
        for name in ('answers.jsonl','pools.jsonl','performance.json')} for repo in repos}
        for arm in arms}
    metadata['status']='ALL outputs closed without Gold or quality grading'
    (args.output/'registration.json').write_text(json.dumps(metadata,indent=2))


if __name__=='__main__':main()
