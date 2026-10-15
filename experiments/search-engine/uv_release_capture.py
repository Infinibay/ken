"""Capture the installed PyPI tool's native answers, without opening Gold.

Usage: controller with --workspace/--source-metadata/--public-cases/--output.
Workers run with the uv tool interpreter in Python isolated mode. They cannot
import the experimental Ken source through PYTHONPATH or an editable install.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def restore_source_snapshot(root, source, rows):
    """Restore the installer's gitignore edit; reject any other source change."""
    changed=[]
    for row in rows:
        relative=Path(row['path'])
        if sha(root/relative)==row['source_hash']:continue
        if relative!=Path('.gitignore'):
            raise ValueError('unexpected source mutation by native install')
        if sha(source/relative)!=row['source_hash']:
            raise ValueError('pinned original snapshot changed')
        shutil.copyfile(source/relative,root/relative)
        changed.append(relative)
    return changed


def verify_install(origin):
    import ken
    from importlib.metadata import version
    package=Path(ken.__file__).resolve().parent
    if str(package/'__init__.py')!=origin['module'] or version('ken-rank')!=origin['version']:
        raise ValueError('uv tool import origin/version changed')
    for relative,expected in origin['package_files'].items():
        if sha(package.parent/relative)!=expected:
            raise ValueError('installed package differs from verified published wheel')
    return package


def worker(args):
    origin=json.loads((args.output/'installed-origin.json').read_text())
    package=verify_install(origin)
    from ken.install import install
    from ken.embedder import active_model
    from ken.mcp import server
    from ken.db import connect
    root=args.output/'repos'/args.repo
    result_dir=args.output/'native'/args.repo
    result_dir.mkdir(parents=True,exist_ok=False)
    requests=read_rows(args.output/('requests-'+args.repo+'.jsonl'))
    start=time.perf_counter()
    installation=install(root,embed=True,no_wire=True,verbose=False)
    roots=json.loads((args.source_metadata/'roots.json').read_text())
    rows=[r for r in read_rows(args.source_metadata/'file-hashes-draft.jsonl') if r['repo_id']==args.repo]
    restored=restore_source_snapshot(root,Path(roots[args.repo]),rows)
    if restored:
        # Native install appends .ken/ before indexing. Reapply its own native
        # indexer to the restored snapshot so both arms search identical bytes.
        from ken.indexer import index_files
        from ken.embedder import get_embedder
        with connect(installation.db_path) as conn:
            index_files(conn,root,restored,embedder=get_embedder())
    index_ms=(time.perf_counter()-start)*1000
    server._PROJECT_ROOT=root
    for scope in ('files','symbols'):
        server.ken_find(query='find code that prepares a value',scope=scope,limit=10)
    timings=[]
    with (result_dir/'answers.jsonl').open('w') as stream:
        for case in requests:
            scope='files' if case['target_kind'] in {'module','file'} else 'symbols'
            start=time.perf_counter();error=None
            try:
                native=server.ken_find(query=case['query'],scope=scope,limit=10)
                if not isinstance(native,list):error='native tool returned a non-list result'
            except Exception as exc:
                native=None;error=type(exc).__name__+': '+str(exc)
            row={'id':case['id'],'scope':scope,'native':native,'error':error}
            encoded=json.dumps(row,ensure_ascii=False,separators=(',',':'))
            timings.append({'id':case['id'],'ms':(time.perf_counter()-start)*1000})
            stream.write(encoded+'\n');stream.flush()
    with connect(installation.db_path) as conn:
        counts={table:conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                for table in ('ci_files','ci_symbols')}
        coverage={table:conn.execute('SELECT COUNT(*) FROM '+table+
                    ' WHERE embedding IS NOT NULL OR vec_slot IS NOT NULL').fetchone()[0]
                  for table in ('ci_files','ci_symbols')}
    perf={'repo':args.repo,'model':active_model(),'module':str(package/'__init__.py'),
          'restored_install_metadata':[str(p) for p in restored],
          'index_ms':index_ms,'counts':counts,'embedded':coverage,'timings':timings,
          'peak_rss_native':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
          'rss_unit':'bytes' if sys.platform=='darwin' else 'KiB'}
    verify_install(origin)
    if any(sha(root/r['path'])!=r['source_hash'] for r in rows):
        raise ValueError('source snapshot changed during native queries')
    (result_dir/'performance.json').write_text(json.dumps(perf,indent=2))
    print(json.dumps({'repo':args.repo,'queries':len(requests),'counts':counts,
                      'errors':sum(bool(r['error']) for r in read_rows(result_dir/'answers.jsonl'))}),flush=True)


def controller(args):
    from verifiable_guard import verify_source_preparation
    roots,preparation=verify_source_preparation(args.workspace,args.source_metadata)
    public_sha=sha(args.public_cases)
    prior=args.workspace/'output/development/verifiable-pieces-v102'
    comparison=json.loads((prior/'registration.json').read_text())
    if public_sha!=comparison['public_cases_sha256']:
        raise ValueError('not the same public200 corpus as the84%/98.5% run')
    for repo,files in comparison['closed_workers']['baseline'].items():
        for name,expected in files.items():
            if sha(prior/'baseline'/repo/name)!=expected:raise ValueError('current arm changed')
    origin=args.output/'installed-origin.json'
    source=Path(__file__).parent
    pins={str(path.resolve()):sha(path) for path in
          [Path(__file__),source/'uv_release_identity.py',source/'test_uv_release_identity.py',
           origin,args.output/'after-uv-receipt.toml',args.output/'pypi-metadata.json',
           args.output/'ken_rank-0.17.0-py3-none-any.whl']}
    registration={'scope':'installed published Ken native identity top1/top10 vs frozen experimental84/98.5',
        'version':'0.17.0','public_cases_sha256':public_sha,'source_preparation':preparation,
        'current_comparison_sha256':sha(prior/'registration.json'),'pins':pins,
        'scope_policy':{'class':'symbols','symbol':'symbols','module':'files','file':'files'},
        'policy':'exact original query, native ten positions, no expansion/filter/promotion/evidence augmentation',
        'snapshot_policy':'restore install gitignore append and reindex that file with published native indexer before queries',
        'runs':[],'status':'registered before native queries; no Gold is read by this producer'}
    regpath=args.output/'registration.json'
    with regpath.open('x') as stream:stream.write(json.dumps(registration,indent=2))
    cases=read_rows(args.public_cases)
    if len(cases)!=200 or len({c['id'] for c in cases})!=200:raise ValueError('not ALL200')
    source_rows=read_rows(args.source_metadata/'file-hashes-draft.jsonl')
    # Copy only the complete pinned tracked snapshot; native install owns its
    # disposable indexes and applies the published admission rules itself.
    for row in source_rows:
        repo=row['repo_id'];relative=row['path'];root=Path(roots[repo]).resolve()
        src=(root/relative).resolve();dst=args.output/'repos'/repo/relative
        if not src.is_relative_to(root) or sha(src)!=row['source_hash']:
            raise ValueError('source snapshot changed')
        dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
        if sha(dst)!=row['source_hash']:raise ValueError('source copy differs')
    environment=dict(os.environ,KEN_CONFIG_DIR=str(args.output/'isolated-config'),
        KEN_CACHE_DIR=str(args.output/'isolated-cache'),KEN_INDEX_WORKERS='0',
        TOKENIZERS_PARALLELISM='false',HF_HUB_OFFLINE='1',OMP_NUM_THREADS='1',
        OPENBLAS_NUM_THREADS='1',VECLIB_MAXIMUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1')
    for name in ('KEN_STATIC_HEAD','KEN_EMBED_MODEL','PYTHONPATH'):
        environment.pop(name,None)
    for repo in sorted(roots):
        request_path=args.output/('requests-'+repo+'.jsonl')
        request_path.write_text(''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in cases if c['repo_id']==repo))
        with (args.output/(repo+'-stdout.log')).open('w') as stdout,(args.output/(repo+'-stderr.log')).open('w') as stderr:
            start=time.perf_counter()
            result=subprocess.run([str(args.python),'-I','-B',str(Path(__file__).resolve()),
                '--worker','--repo',repo,'--output',str(args.output),
                '--source-metadata',str(args.source_metadata.resolve())],env=environment,
                cwd=args.output,stdout=stdout,stderr=stderr)
        registration['runs'].append({'repo':repo,'returncode':result.returncode,
                                     'wall_ms':(time.perf_counter()-start)*1000})
        regpath.write_text(json.dumps(registration,indent=2))
        print(json.dumps(registration['runs'][-1]),flush=True)
        if result.returncode:raise RuntimeError('native worker failed; logs preserved '+repo)
        for path,expected in pins.items():
            if sha(path)!=expected:raise ValueError('registered producer/input changed')
    closed={};answers=[]
    for repo in sorted(roots):
        folder=args.output/'native'/repo
        closed[repo]={name:sha(folder/name) for name in ('answers.jsonl','performance.json')}
        answers.extend(read_rows(folder/'answers.jsonl'))
    if len(answers)!=200 or {r['id'] for r in answers}!={r['id'] for r in cases}:
        raise ValueError('missing/duplicate output')
    (args.output/'native-answers.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in answers))
    registration.update(status='ALL200 native answers closed without Gold',closed=closed,
                        answers_sha256=sha(args.output/'native-answers.jsonl'))
    regpath.write_text(json.dumps(registration,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--worker',action='store_true');p.add_argument('--repo')
    for name in ('workspace','source-metadata','public-cases','output','python'):
        p.add_argument('--'+name,type=Path,required=name=='output')
    args=p.parse_args()
    if args.worker:worker(args)
    else:controller(args)
