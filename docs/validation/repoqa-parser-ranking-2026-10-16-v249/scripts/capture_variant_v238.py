"""Capture one frozen RepoQA variant; source/query inputs contain no answers."""
from pathlib import Path
import argparse
import importlib.metadata
import json
import os
import resource
import shutil
import sqlite3
import subprocess
import sys
import time
import hashlib


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def write(path,value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n');temporary.replace(path)


def backup(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True) as src,sqlite3.connect(target) as dst:
        src.backup(dst)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);parser.add_argument('--group')
    args=parser.parse_args();out=args.out.resolve();registration=json.loads((out/'registration.json').read_text())
    engine=Path(registration['engine']);assert sha(engine/'SOURCE-MANIFEST.json')==registration['engine_manifest_sha256']
    for name,digest in json.loads((engine/'SOURCE-MANIFEST.json').read_text())['files'].items():assert sha(engine/name)==digest,name
    assert sha(out/'repoqa-requests.jsonl')==registration['requests_sha256']
    assert sha(out/'repoqa-sources.json')==registration['sources_sha256']
    requests=[json.loads(x) for x in (out/'repoqa-requests.jsonl').read_text().splitlines()]
    sources=json.loads((out/'repoqa-sources.json').read_text());capture=out/'capture';producer=Path(__file__).resolve()
    environment=os.environ|{'PYTHONPATH':str(engine/'src'),'PYTHONDONTWRITEBYTECODE':'1','HF_HUB_OFFLINE':'1',
        'HF_HUB_CACHE':str(Path.cwd()/'output/models/portable-public-hub-v143'),
        'KEN_CACHE_DIR':str(Path.cwd()/'output/models/portable-public-prepared-v143'),'KEN_INDEX_WORKERS':'0',
        'OPENBLAS_NUM_THREADS':'1','VECLIB_MAXIMUM_THREADS':'1','OMP_NUM_THREADS':'1'}
    if args.group is None:
        capture.mkdir(exist_ok=False);pins={}
        write(capture/'registration.json',{'producer_sha256':sha(producer),'registration_sha256':sha(out/'registration.json'),
            'labels_in_workers':False,'reserve':'CLOSED'})
        for number,group_id in enumerate(sorted(sources),1):
            started=time.perf_counter()
            with (capture/(group_id+'.log')).open('w') as log:
                result=subprocess.run([sys.executable,str(producer),'--out',str(out),'--group',group_id],
                    env=environment,stdout=log,stderr=subprocess.STDOUT)
            folder=capture/group_id
            if result.returncode:
                folder.mkdir(exist_ok=True)
                write(folder/'responses.json',[{'id':r['id'],'results':[],'error':f'worker exit {result.returncode}'} for r in requests if r['repo_id']==group_id])
                write(folder/'failure.json',{'exit':result.returncode})
            pins.update({p.relative_to(capture).as_posix():sha(p) for p in folder.iterdir() if p.is_file()})
            status={'closed':number,'total':len(sources),'group':group_id,'exit':result.returncode,'elapsed_s':time.perf_counter()-started}
            write(capture/'progress.json',status);print(json.dumps(status),flush=True)
        assert sha(producer)==json.loads((capture/'registration.json').read_text())['producer_sha256']
        write(capture/'closure.json',{'queries':len(requests),'response_pins':pins,'all_outputs_closed':True,
            'worker_sha256':sha(producer),'requests_sha256':registration['requests_sha256']})
        return
    folder=capture/args.group;folder.mkdir(exist_ok=False);group=[r for r in requests if r['repo_id']==args.group]
    source=sources[args.group];root=Path(group[0]['root']);original=Path(source['original_root']);root.mkdir(parents=True,exist_ok=False)
    for name,digest in source['source_pins'].items():
        assert sha(original/name)==digest
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original/name,target)
    (root/'.ken').mkdir();backup(original/'.ken/ken.db',root/'.ken/ken.db')
    if (original/'.ken/search-context/vectors.db').is_file():
        backup(original/'.ken/search-context/vectors.db',root/'.ken/search-context/vectors.db')
    if (original/'.ken/vectors').is_dir():shutil.copytree(original/'.ken/vectors',root/'.ken/vectors')
    write(folder/'ownership.json',{'root':str(root),'original':str(original),'state_copied_then_owned':True,'no_shared_mutable_files':True})
    started=time.perf_counter()
    with (folder/'prepare.log').open('w') as log:
        subprocess.run([sys.executable,'-m','ken','retrieval','prepare','--path',str(root),'--json'],env=environment,stdout=log,stderr=subprocess.STDOUT,check=True)
    preparation_ms=(time.perf_counter()-started)*1000
    prepare_peak=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    import ken
    assert Path(ken.__file__).resolve().parents[2]==engine
    from ken.retrieval.public import find_best,render
    from ken.retrieval.connections import project_connection
    from ken.retrieval.best_resources import default_resources
    responses=[]
    with project_connection(root) as conn:
        indexed=[row[0] for row in conn.execute('SELECT path FROM ci_files')];assert set(indexed)<=source['source_pins'].keys()
        write(folder/'index-coverage.json',{'source_files':len(source['source_pins']),'indexed_files':len(indexed),'not_indexed':sorted(source['source_pins'].keys()-set(indexed))})
        owners=[dict(zip(('path','kind','qualname','start_line','end_line','passages'),row)) for row in conn.execute(
            'SELECT f.path,s.kind,s.qualname,s.line_start,s.line_end,COUNT(p.id) FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id LEFT JOIN ci_passages p ON p.symbol_id=s.id GROUP BY s.id ORDER BY f.path,s.line_start')]
        write(folder/'indexed-owners.json',owners)
        started=time.perf_counter();warmup=find_best(conn,root,'find code that prepares a value',scope='symbols',piece_kind='symbol');assert warmup.get('ok') is not False
        warmup_ms=(time.perf_counter()-started)*1000
        for request in group:
            before=resource.getrusage(resource.RUSAGE_SELF);started=time.perf_counter()
            try:
                value=find_best(conn,root,request['query'],scope=request['scope'],piece_kind=request['piece_kind'],limit=10,max_chars=12000)
                if value.get('ok') is False:raise ValueError(str(value))
                assert len(value['results'])<=10 and not any(r.get('stale') for r in value['results'])
                compact=render(value);json.dumps(value,ensure_ascii=False,separators=(',',':'))
            except Exception as error:value={'results':[],'error':f'{type(error).__name__}: {error}'};compact=value['error']
            after=resource.getrusage(resource.RUSAGE_SELF)
            responses.append({'id':request['id'],**value,'compact':compact,'elapsed_ms':(time.perf_counter()-started)*1000,
                'cpu_ms':((after.ru_utime+after.ru_stime)-(before.ru_utime+before.ru_stime))*1000})
            write(folder/'progress.json',{'captured':len(responses),'queries':len(group)})
    resources=default_resources();assert list(resources.neural.providers)==list(resources.context.providers)==['CPUExecutionProvider']
    assert resources.neural._max_tokens==1024
    heavy=[name for name in ('torch','transformers','sentence_transformers') if name in sys.modules];assert not heavy
    for name,digest in source['source_pins'].items():assert sha(root/name)==digest
    write(folder/'responses.json',responses)
    write(folder/'provenance.json',{'complete':True,'preparation_ms':preparation_ms,'warmup_ms':warmup_ms,
        'providers':list(resources.neural.providers),'reranker_tokens':1024,'heavy_imports':heavy,
        'query_process_peak_rss_native':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'prepare_child_peak_rss_native':prepare_peak,
        'rss_unit':'bytes' if sys.platform=='darwin' else 'KiB','worker_sha256':sha(producer),
        'engine_manifest_sha256':registration['engine_manifest_sha256'],
        'runtime':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()}})
    shutil.rmtree(root/'.ken')


if __name__=='__main__':main()
