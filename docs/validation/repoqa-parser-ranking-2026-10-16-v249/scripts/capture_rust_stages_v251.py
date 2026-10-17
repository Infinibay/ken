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


def diagnose_stages(conn, root, group, responses, folder, resources):
    """Replay query inputs only, after measured calls; observations cannot affect rank."""
    from ken.retrieval.best_search import _prepared
    from ken.retrieval.candidates import owner_passages, owner_descriptions, retrieve_contextual
    from ken.retrieval.model import SearchRequest
    from ken.retrieval.piece_cards import build_piece_cards
    from ken.retrieval.ranking_trace import RankingTrace
    from ken.retrieval.storage import generation
    project = _prepared(conn, root, resources)
    owners = owner_passages(conn)
    inventory = [{'path': key.path, 'entity': key.to_dict(), 'entity_span':dict(zip(('start_line','end_line'),project.pieces.catalog.extent(key)))} for key in project.context.vectors.owners]
    write(folder/'context-owners.json', inventory)
    def identity(value):
        return [{'path':r['path'],'entity':r['entity'],'entity_span':r['entity_span'],'source_hash':r['source_hash']} for r in value.get('results',[])]
    diagnostics=[]
    for public, original in zip(group, responses, strict=True):
        record={'id':public['id']}
        try:
            request=SearchRequest(public['query'],target='symbol',piece_kind=public['piece_kind'],limit=10,max_chars=12000)
            candidates, expanded=retrieve_contextual(conn,root,request,resources.profile,runtime=project.context,
                expand_query=resources.owner_ranker.prepare_query,encoders={'identity':resources.words,'behavior':resources.words})
            trace=RankingTrace(request_id=public['id'])
            matches=resources.owner_ranker.rank(request,candidates,owner_descriptions(conn,candidates),expanded_query=expanded,evidence_version=3,trace=trace)
            cards=build_piece_cards(matches,'symbol',expanded,project.pieces.catalog)
            from dataclasses import replace
            detailed=project.pieces.search(replace(request,explain=True),matches,expanded_query=expanded,profile_version=resources.profile.fingerprint).to_dict()
            assert identity(detailed)==identity(original),'diagnostic replay changed result identities'
            contextual=project.context.score(public['query'],expanded,owners,generation=generation(conn),policy=resources.profile.contextual)
            record.update(expanded_query=expanded,
                contextual_original=[float(x) for x in contextual.original],contextual_expanded=[float(x) for x in contextual.expanded],
                proposals=[{'path':c.entity.path,'entity':c.entity.to_dict(),'signals':{k:float(v) for k,v in c.signals.items()}} for c in candidates],
                numeric_order=[{'path':m.entity.path,'entity':m.entity.to_dict(),'score':float(m.score),'signals':m.signals} for m in matches],
                numeric_trace=trace.to_dict(),native_cards=cards[:10],diagnostic_response=detailed,normal_identities_reproduced=True)
        except Exception as error:
            record['error']=f'{type(error).__name__}: {error}'
        diagnostics.append(record)
        write(folder/'stage-progress.json',{'captured':len(diagnostics),'queries':len(group)})
    write(folder/'stages.json',diagnostics)
    return sum('error' in record for record in diagnostics)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);parser.add_argument('--group');args=parser.parse_args()
    out=args.out.resolve();registration=json.loads((out/'registration.json').read_text());engine=Path(registration['engine'])
    assert registration['diagnostic_only'] and sha(engine/'SOURCE-MANIFEST.json')==registration['engine_manifest_sha256']
    for name,digest in json.loads((engine/'SOURCE-MANIFEST.json').read_text())['files'].items():assert sha(engine/name)==digest,name
    assert sha(out/'repoqa-requests.jsonl')==registration['requests_sha256'] and sha(out/'repoqa-sources.json')==registration['sources_sha256']
    original=Path(registration['original_capture']);assert sha(original/'closure.json')==registration['original_closure_sha256']
    requests=[json.loads(x) for x in (out/'repoqa-requests.jsonl').read_text().splitlines()];sources=json.loads((out/'repoqa-sources.json').read_text());capture=out/'capture';producer=Path(__file__).resolve()
    environment=os.environ|{'PYTHONPATH':str(engine/'src'),'PYTHONDONTWRITEBYTECODE':'1','HF_HUB_OFFLINE':'1',
        'HF_HUB_CACHE':str(Path.cwd()/'output/models/portable-public-hub-v143'),'KEN_CACHE_DIR':str(Path.cwd()/'output/models/portable-public-prepared-v143'),
        'KEN_INDEX_WORKERS':'0','OPENBLAS_NUM_THREADS':'1','VECLIB_MAXIMUM_THREADS':'1','OMP_NUM_THREADS':'1'}
    if args.group is None:
        while not Path(registration['serial_after_capture']).is_file():time.sleep(5)
        capture.mkdir(exist_ok=False);pins={}
        write(capture/'registration.json',{'producer_sha256':sha(producer),'registration_sha256':sha(out/'registration.json'),'labels_in_workers':False,'reserve':'CLOSED','diagnostic_only':True})
        for number,group_id in enumerate(sorted(sources),1):
            started=time.perf_counter()
            with (capture/(group_id+'.log')).open('w') as log:
                result=subprocess.run([sys.executable,str(producer),'--out',str(out),'--group',group_id],env=environment,stdout=log,stderr=subprocess.STDOUT)
            folder=capture/group_id;folder.mkdir(exist_ok=True)
            if result.returncode:write(folder/'stages.json',[{'id':r['id'],'error':f'worker exit {result.returncode}'} for r in requests if r['repo_id']==group_id])
            pins.update({p.relative_to(capture).as_posix():sha(p) for p in folder.iterdir() if p.is_file()})
            status={'closed':number,'total':len(sources),'group':group_id,'exit':result.returncode,'elapsed_s':time.perf_counter()-started}
            write(capture/'progress.json',status);print(json.dumps(status),flush=True)
        assert sha(producer)==json.loads((capture/'registration.json').read_text())['producer_sha256']
        write(capture/'closure.json',{'queries':len(requests),'diagnostic_only':True,'response_pins':pins,'all_outputs_closed':True,'worker_sha256':sha(producer)})
        return
    group_id=args.group;folder=capture/group_id;folder.mkdir(exist_ok=False);group=[r for r in requests if r['repo_id']==group_id]
    source=sources[group_id];root=Path(group[0]['root']);baseline_root=Path(source['original_root']);root.mkdir(parents=True,exist_ok=False)
    for name,digest in source['source_pins'].items():
        assert sha(baseline_root/name)==digest
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(baseline_root/name,target)
    (root/'.ken').mkdir();backup(baseline_root/'.ken/ken.db',root/'.ken/ken.db')
    cache=Path(source['context_cache_source']);assert sha(cache)==source['context_cache_sha256'];backup(cache,root/'.ken/search-context/vectors.db')
    if (baseline_root/'.ken/vectors').is_dir():shutil.copytree(baseline_root/'.ken/vectors',root/'.ken/vectors')
    started=time.perf_counter()
    with (folder/'prepare.log').open('w') as log:
        for command in ('index','prepare'):subprocess.run([sys.executable,'-m','ken','retrieval',command,'--path',str(root),'--json'],env=environment,stdout=log,stderr=subprocess.STDOUT,check=True)
    preparation_ms=(time.perf_counter()-started)*1000
    import ken
    assert Path(ken.__file__).resolve().parents[2]==engine
    from ken.retrieval.connections import project_connection
    from ken.retrieval.best_resources import default_resources
    resources=default_resources();response_path=original/group_id/'responses.json';assert sha(response_path)==registration['original_response_pins'][group_id]
    responses=json.loads(response_path.read_text());assert [r['id'] for r in group]==[r['id'] for r in responses]
    with project_connection(root) as conn:
        owners=[dict(zip(('path','kind','qualname','start_line','end_line','passages'),row)) for row in conn.execute('SELECT f.path,s.kind,s.qualname,s.line_start,s.line_end,COUNT(p.id) FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id LEFT JOIN ci_passages p ON p.symbol_id=s.id GROUP BY s.id ORDER BY f.path,s.line_start')]
        write(folder/'indexed-owners.json',owners)
        errors=diagnose_stages(conn,root,group,responses,folder,resources)
    assert list(resources.neural.providers)==list(resources.context.providers)==['CPUExecutionProvider'] and resources.neural._max_tokens==1024
    assert not any(name in sys.modules for name in ('torch','transformers','sentence_transformers'))
    for name,digest in source['source_pins'].items():assert sha(root/name)==digest
    write(folder/'provenance.json',{'complete':True,'diagnostic_only':True,'stage_errors':errors,'preparation_ms':preparation_ms,'providers':list(resources.neural.providers),'reranker_tokens':1024,'process_peak_rss_native':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'rss_unit':'bytes' if sys.platform=='darwin' else 'KiB','worker_sha256':sha(producer),'engine_manifest_sha256':registration['engine_manifest_sha256']})
    shutil.rmtree(root/'.ken')


if __name__=='__main__':main()
