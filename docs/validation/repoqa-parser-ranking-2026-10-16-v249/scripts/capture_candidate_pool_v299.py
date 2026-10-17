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


def search_pool(conn, root, public, registration):
    from dataclasses import replace
    import numpy as np
    from ken.retrieval.best_search import _prepared
    from ken.retrieval.best_resources import default_resources
    from ken.retrieval.candidates import owner_passages, owner_descriptions, retrieve_contextual
    from ken.retrieval.model import SearchRequest, EntityKey
    from ken.retrieval.piece_cards import build_piece_cards, build_card, canonical, card_text
    from ken.retrieval.piece_candidates import assemble_pieces
    from ken.retrieval.piece_search import present_cards, _unit
    from ken.retrieval.description import describe_owner
    from ken.retrieval.symbol_ranking import complete_code_view
    from ken.retrieval.symbol_requirements import requirements, prefer_operations, is_test_case, prefer_explicit_code_terms
    from ken.retrieval.storage import generation
    resources=default_resources();project=_prepared(conn,root,resources);catalog=project.pieces.catalog
    request=SearchRequest(public['query'],target='symbol',piece_kind='symbol',limit=10,max_chars=12000)
    candidates,expanded=retrieve_contextual(conn,root,request,resources.profile,runtime=project.context,expand_query=resources.owner_ranker.prepare_query,encoders={'identity':resources.words,'behavior':resources.words})
    matches=resources.owner_ranker.rank(request,candidates,owner_descriptions(conn,candidates),expanded_query=expanded,evidence_version=3)
    native=build_piece_cards(matches,'symbol',expanded,catalog)[:10]
    pieces=assemble_pieces(matches,'symbol',catalog,project.pieces.descriptions)
    ranked=resources.piece_ranker.rank(request,pieces,expanded_query=expanded)
    by_unit={canonical(card['unit']):card for card in native}
    cards=[by_unit[canonical(_unit(m.piece.kind,m.piece.path,m.piece.entity))] for m in ranked]
    assert len(cards)==len(native)
    native_count=len(cards);keys=[EntityKey(path=c['unit']['path'],**c['unit']['entity']) for c in cards]
    contextual=project.context.score(request.query,expanded,owner_passages(conn),generation=generation(conn),policy=resources.profile.contextual)
    context_keys=[]
    for index in np.argsort(-np.maximum(contextual.original,contextual.expanded),kind='stable'):
        key=contextual.source.owners[int(index)]
        if catalog.primary(key,'symbol')==key:
            context_keys.append(key)
            if len(context_keys)==10:break
    for key in context_keys:
        if key not in keys:cards.append(build_card(key,'symbol',[key],expanded,catalog));keys.append(key)
    assert len(cards)<=20
    descriptions=[];texts=[];used=[]
    for key,card in zip(keys,cards,strict=True):
        if key not in project.pieces.descriptions:project.pieces.descriptions[key]=describe_owner(catalog.owners[key])
        description=project.pieces.descriptions[key];descriptions.append(description);text=complete_code_view(description)
        accepted=text is not None and resources.neural.pair_fits(expanded,text)
        texts.append(text if accepted else card_text(card));used.append(accepted)
    scores=[];details={'token_ms':0.,'inference_ms':0.,'truncated_documents':0,'pair_tokens':[],'api_calls':0}
    for start in range(0,len(texts),10):
        chunk,observed=resources.neural.score(expanded,texts[start:start+10]);scores.extend(chunk)
        for name in ('token_ms','inference_ms','truncated_documents'):details[name]+=observed[name]
        details['pair_tokens'].extend(observed['pair_tokens']);details['api_calls']+=1
        if 'pad_id' in observed:details['pad_id']=observed['pad_id']
    assert len(scores)==len(texts)<=20 and details['api_calls']<=2
    if not _CLOSED_SCORES:
        score_source=Path(registration['native_code_scores'])
        assert sha(score_source)==registration['native_code_scores_sha256']
        _CLOSED_SCORES.update(json.loads(score_source.read_text()))
    reference_scores=_CLOSED_SCORES[public['id']]
    delta=max((abs(float(scores[i])-reference_scores[canonical([keys[i].path,keys[i].to_dict()])]) for i in range(native_count)),default=0.)
    assert delta<=2e-5,('source-view logit parity',public['id'],delta)
    required=requirements(request)
    witnesses=[project.pieces.symbols.operations.for_owner(key) for key in keys] if required.operations else [frozenset() for _ in keys]
    def order_for(indices):
        order=sorted(indices,key=lambda i:-scores[i]);order=prefer_operations(required.operations,witnesses,order)
        if required.test_case:order.sort(key=lambda i:not is_test_case(keys[i],catalog))
        # The operator helper requires a full local permutation; use the subset's own projection.
        local=[descriptions[i].fields['executable'] for i in indices];positions={i:j for j,i in enumerate(indices)}
        local_order=prefer_explicit_code_terms(request.query,local,[positions[i] for i in order])
        return [indices[i] for i in local_order]
    native_order=order_for(list(range(native_count)));union_order=order_for(list(range(len(cards))))
    response=present_cards([cards[i] for i in union_order],request,catalog,profile_version=resources.profile.fingerprint).to_dict()
    control=present_cards([cards[i] for i in native_order],request,catalog,profile_version=resources.profile.fingerprint).to_dict()
    response['experiment']={'policy':'native10_plus_contextual10_single_source_view_v274','native_count':native_count,'candidate_count':len(cards),'neural_pairs':len(texts),'code_views_used':sum(used),'native_logit_max_abs_delta':delta,'neural':details,'native_single_view_control':control}
    return response


_CLOSED_SCORES={}


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
        while not Path(registration['serial_after_capture']).is_file():time.sleep(5)
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
    cache=Path(source.get('context_cache_source',str(original/'.ken/search-context/vectors.db')))
    if cache.is_file():
        if 'context_cache_sha256' in source:assert sha(cache)==source['context_cache_sha256']
        backup(cache,root/'.ken/search-context/vectors.db')
    if (original/'.ken/vectors').is_dir():shutil.copytree(original/'.ken/vectors',root/'.ken/vectors')
    write(folder/'ownership.json',{'root':str(root),'original':str(original),'state_copied_then_owned':True,'no_shared_mutable_files':True})
    started=time.perf_counter()
    with (folder/'prepare.log').open('w') as log:
        subprocess.run([sys.executable,'-m','ken','retrieval','index','--path',str(root),'--json'],env=environment,stdout=log,stderr=subprocess.STDOUT,check=True)
        subprocess.run([sys.executable,'-m','ken','retrieval','prepare','--path',str(root),'--json'],env=environment,stdout=log,stderr=subprocess.STDOUT,check=True)
    preparation_ms=(time.perf_counter()-started)*1000
    prepare_peak=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    import ken
    assert Path(ken.__file__).resolve().parents[2]==engine
    from ken.retrieval.public import find_best,render
    from ken.retrieval.connections import project_connection
    from ken.retrieval.best_resources import default_resources
    responses=[]
    stage_errors=0
    query_peak=0
    with project_connection(root) as conn:
        indexed=[row[0] for row in conn.execute('SELECT path FROM ci_files')];assert set(indexed)<=source['source_pins'].keys()
        write(folder/'index-coverage.json',{'source_files':len(source['source_pins']),'indexed_files':len(indexed),'not_indexed':sorted(source['source_pins'].keys()-set(indexed))})
        owners=[dict(zip(('path','kind','qualname','start_line','end_line','passages'),row)) for row in conn.execute(
            'SELECT f.path,s.kind,s.qualname,s.line_start,s.line_end,COUNT(p.id) FROM ci_symbols s JOIN ci_files f ON f.id=s.file_id LEFT JOIN ci_passages p ON p.symbol_id=s.id GROUP BY s.id ORDER BY f.path,s.line_start')]
        write(folder/'indexed-owners.json',owners)
        started=time.perf_counter();warmup=find_best(conn,root,'find code that prepares a value',scope='symbols',piece_kind='symbol');assert warmup.get('ok') is not False, warmup
        warmup_ms=(time.perf_counter()-started)*1000
        for request in group:
            before=resource.getrusage(resource.RUSAGE_SELF);started=time.perf_counter()
            try:
                value=search_pool(conn,root,request,registration)
                if value.get('ok') is False:raise ValueError(str(value))
                assert len(value['results'])<=10 and not any(r.get('stale') for r in value['results'])
                compact=render(value);json.dumps(value,ensure_ascii=False,separators=(',',':'))
            except Exception as error:value={'results':[],'error':f'{type(error).__name__}: {error}'};compact=value['error']
            after=resource.getrusage(resource.RUSAGE_SELF)
            responses.append({'id':request['id'],**value,'compact':compact,'elapsed_ms':(time.perf_counter()-started)*1000,
                'cpu_ms':((after.ru_utime+after.ru_stime)-(before.ru_utime+before.ru_stime))*1000})
            write(folder/'progress.json',{'captured':len(responses),'queries':len(group)})
        query_peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        write(folder/'timed-responses.json',responses)
        if registration['capture_stages']:
            stage_errors=diagnose_stages(conn,root,group,responses,folder,default_resources())
    resources=default_resources();assert list(resources.neural.providers)==list(resources.context.providers)==['CPUExecutionProvider']
    assert resources.neural._max_tokens==1024
    heavy=[name for name in ('torch','transformers','sentence_transformers') if name in sys.modules];assert not heavy
    for name,digest in source['source_pins'].items():assert sha(root/name)==digest
    write(folder/'responses.json',responses)
    write(folder/'provenance.json',{'complete':True,'preparation_ms':preparation_ms,'warmup_ms':warmup_ms,
        'providers':list(resources.neural.providers),'reranker_tokens':1024,'heavy_imports':heavy,
        'query_process_peak_rss_native':query_peak,'diagnostic_process_peak_rss_native':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'stage_errors':stage_errors,'prepare_child_peak_rss_native':prepare_peak,
        'rss_unit':'bytes' if sys.platform=='darwin' else 'KiB','worker_sha256':sha(producer),
        'engine_manifest_sha256':registration['engine_manifest_sha256'],
        'runtime':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()}})
    shutil.rmtree(root/'.ken')


if __name__=='__main__':main()
