"""One convex feature-ranker control, complete source binding and whole-repo exclusion."""
import gc,hashlib,itertools,json,resource,sys,time
from importlib.metadata import version
from pathlib import Path
import ken
import numpy as np
R=Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
E=Path(ken.__file__).resolve().parents[2]
sys.path.insert(0,str(E/'experiments/search-engine'))
from replay import load_pools
from replay_parent import validate_replay_parent
from action_evidence import FEATURES as EXTRA_FEATURES
from ken.bench.numeric_export import export_numeric_ranker
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.model import CodeMatch,SearchRequest
from ken.retrieval.evidence import complete_evidence
from ken.retrieval.presentation import present
from ken.retrieval.numeric_ranker import NumericRanker
O=R/'output/analysis/query-actions-ranking-v90';O.mkdir(exist_ok=False)
P=R/'output/analysis/c-source-reindex-v66c';F=R/'output/analysis/context-views-features-source7-v69';V=R/'output/analysis/context-views-source7-v69';B=R/'output/analysis/source7-context-views-ranking-v69';D=R/'output/analysis/source7-ranking-v66c/training-matrix.npz'
def sha(path):
    with Path(path).open('rb')as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()
array_sha=lambda a:hashlib.sha256(memoryview(np.ascontiguousarray(a)).cast('B')).hexdigest()
receipt=verify_frozen_source(E);assert receipt=='d0fa6e6e3b80eb432d19b73449211e7cee26df235b976e59f91f7594c43f6259'
assert sha(F/'registration.json')=='74bd9b403b052d6106730857c6a7498a6f98d05d0c8e4417cd048908027c04d2'
assert sha(V/'registration.json')=='d4ee096ad988d8e87811275299039f95afc65cc472c5da4e4211e725ba999554'
assert sha(B/'registration.json')=='9bb0d87b2f5306c7b3eee1a6484e271c6b3cfdb182fc3d408663bef6344fe814'
assert sha(D)=='06c66ff3a3ea4c8cf6af7100df287dd41718a9f63558840e56adea22bbb890ff'
roots={k:Path(v)for k,v in json.loads((R/'experiments/search-engine/datasets/roots-development.json').read_text()).items()}
source=json.loads((V/'registration.json').read_text());index=json.loads((P/'registration.json').read_text());features_registration=json.loads((F/'registration.json').read_text());producer=json.loads((B/'registration.json').read_text())
features=tuple(features_registration['features']);assert len(features)==251
A=R/'output/analysis/query-actions-features-v90';prepared_source=json.loads((A/'registration.json').read_text())
assert prepared_source['complete']and prepared_source['source_phase_complete']and len(prepared_source['source_repos'])==len(prepared_source['query_repos'])==16
assert prepared_source['engine_receipt']==receipt and prepared_source['controller_sha256']=='96e01d57ff8b73f1ef59102bb9bfc0061a95934a8111fbb8de83824903c22bc8'
assert all(sha(p)==h for p,h in prepared_source['inputs'].items())
assert tuple(prepared_source['extra_features'])==EXTRA_FEATURES and len(EXTRA_FEATURES)==33
features=(*features,*EXTRA_FEATURES);assert len(features)==284
K=R/'output/analysis/core-ranker-v18/registration.json';assert sha(K)=='97ce68f706158a4ee2a6c83e401a307b5ea0728aa3b1a4afa3846637963346d9'
parameters=json.loads(K.read_text())['parameters']

source_bindings={}
for repo in sorted(roots):
    files=index['source_repos'][repo]['file_hashes'];assert len(files)==index['source_repos'][repo]['indexed_files']
    assert all(sha(roots[repo]/p)==digest for p,digest in files.items())
    meta=source['source_repos'][repo]
    paths={P/'indices'/(repo+'.db'):index['source_repos'][repo]['new_source_index_sha256'],P/'context'/(repo+'.db'):meta['base_full_context_sha256'],V/(repo+'-source.db'):meta['source_db_sha256'],V/(repo+'-vectors.npy'):meta['vectors_sha256']}
    assert all(sha(p)==digest for p,digest in paths.items());source_bindings.update({str(p):digest for p,digest in paths.items()})
assert sum(len(m['file_hashes'])for m in index['source_repos'].values())==6314
for repo in roots:
    p=A/'source'/(repo+'.db');assert sha(p)==prepared_source['source_repos'][repo]['word_database_sha256'];source_bindings[str(p)]=sha(p)
parent_bindings=validate_replay_parent(F,P);assert len(parent_bindings)==51
requests={}
for path in sorted((P/'requests').glob('*.jsonl')):
    for row in map(json.loads,path.read_text().splitlines()):
        assert row['id']not in requests;requests[row['id']]=row
counts={}
with (P/'candidates.jsonl').open()as stream:
    for row in map(json.loads,stream):
        assert row['id']not in counts
        pool=row['candidates'];counts[row['id']]=(len(pool),bool(len(pool)==1 and pool[0]['signals'].get('exact')))
assert len(requests)==400 and requests.keys()==counts.keys()
with np.load(D)as original:old={key:original[key]for key in('x','qid','repo','y')}
assert set(old['qid'])==set(requests)and np.isin(old['y'],(0,1)).all()
prior={qid:np.flatnonzero(old['qid']==qid)for qid in requests}
matrices=[];qids=[];repositories=[];labels=[];bindings={str(p):sha(p)for p in(D,F/'registration.json',V/'registration.json',B/'registration.json',P/'registration.json',B/'contract_body251/scores.npy',E/'experiments/search-engine/cpu-query-actions-v90.md',E/'experiments/search-engine/query_actions.py',E/'experiments/search-engine/action_evidence.py',E/'experiments/search-engine/cpu-query-actions-v90-supplement.md')}
bindings[str(A/'registration.json')]=sha(A/'registration.json');bindings[str(K)]=sha(K)
assert sha(B/'contract_body251/scores.npy')=='c9b192923fd4e3b9b2b621c3b2192c17bfd0c7fcc7baaf2e74dbb1dab83088c3'
old_scores=np.load(B/'contract_body251/scores.npy');baseline=[]
for repo in sorted(roots):
    path=F/(repo+'.npz');assert sha(path)==features_registration['query_repos'][repo]['output_sha256'];bindings[str(path)]=sha(path)
    with np.load(path)as loaded:data={name:loaded[name]for name in('x','qid','index')}
    extra_path=A/(repo+'.npz');meta=prepared_source['query_repos'][repo];assert sha(extra_path)==meta['output_sha256']and sha(path)==meta['parent251_sha256'];bindings[str(extra_path)]=sha(extra_path)
    with np.load(extra_path)as loaded:extra={name:loaded[name]for name in('x','qid','index')}
    assert np.array_equal(data['qid'],extra['qid'])and np.array_equal(data['index'],extra['index'])and extra['x'].shape==(len(data['x']),33)
    data['x']=np.column_stack((data['x'],extra['x']))

    for qid,group in itertools.groupby(range(len(data['qid'])),key=lambda i:str(data['qid'][i])):
        rows=np.array(list(group));before=prior[qid]
        assert len(rows)==len(before)==counts[qid][0] and requests[qid]['repo_id']==repo and all(old['repo'][before]==repo)
        assert np.array_equal(data['index'][rows],np.arange(len(rows)))and np.array_equal(data['x'][rows,:235],old['x'][before])
        matrices.append(data['x'][rows]);baseline.extend(old_scores[before]);labels.extend(old['y'][before]);qids.extend([qid]*len(rows));repositories.extend([repo]*len(rows))
X=np.concatenate(matrices);qids=np.array(qids);repositories=np.array(repositories);labels=np.array(labels);baseline=np.array(baseline)
assert X.shape==(167360,284)and np.isfinite(X).all()
del old,prior,old_scores,data,matrices;gc.collect()
rows={qid:np.flatnonzero(qids==qid)for qid in requests};choices={}
for qid in sorted(requests):
    positions=rows[qid];assert np.array_equal(positions,np.arange(positions[0],positions[-1]+1))
    eligible=labels[positions];reason='exact_bypass'if counts[qid][1]else'no_positive'if not eligible.any()else'no_negative'if eligible.all()else None
    choices[qid]={'repo':requests[qid]['repo_id'],'rows':len(positions),'positive':int(eligible.sum()),'public_group_kind':reason or 'mixed','feature_sha256':array_sha(X[positions]),'label_sha256':array_sha(eligible)}
manifest={'scope':'One fixed284 action-evidence LambdaRank control90; all400 original queries, raw251 exact prefix, original eligibility and ALLanchor acceptance unchanged; no additional encoder','engine_receipt':receipt,'script_sha256':sha(__file__),'inputs':bindings,'source_bindings':source_bindings,'parent_bindings':parent_bindings,'features':features,'parameters':parameters,'matrix_sha256':array_sha(X),'labels_sha256':array_sha(labels),'public_groups':choices,'training_sets':{},'pre_fit_ready':False,'folds':[],'results':{},'runtime':{p:version(p)for p in('numpy','lightgbm')}}
for held in sorted(roots):
    train=np.flatnonzero(repositories!=held);test=np.flatnonzero(repositories==held)
    query_ids=list(dict.fromkeys(qids[train]));assert len(query_ids)==375 and all(requests[q]['repo_id']!=held for q in query_ids)
    sizes=np.array([len(list(g))for _,g in itertools.groupby(qids[train])]);assert sizes.sum()==len(train)and len(sizes)==375
    path=O/(held+'-training-rows.npz');np.savez(path,rows=train,group=sizes)
    manifest['training_sets'][held]={'sha256':sha(path),'training_repositories':sorted(set(repositories[train])),'query_ids':query_ids,'feature_sha256':array_sha(X[train]),'label_sha256':array_sha(labels[train]),'rows':len(train),'groups':375}
    assert manifest['training_sets'][held]['training_repositories']==sorted(set(roots)-{held})
manifest['pre_fit_ready']=True;(O/'registration.json').write_text(json.dumps(manifest,indent=2));print(json.dumps({'pre_fit_ready':True,'features':284,'queries':400,'folds':16,'waiting_for':str(O/'PRE-FIT-REVIEW-ACCEPTED.json')}),flush=True)
while True:
    try:
        accepted=json.loads((O/'PRE-FIT-REVIEW-ACCEPTED.json').read_text())
        if accepted['engine_receipt']==receipt and accepted['controller_sha256']==manifest['script_sha256']and accepted['pre_fit_registration_sha256']==sha(O/'registration.json'):break
    except(FileNotFoundError,json.JSONDecodeError):pass
    time.sleep(5)
assert all(sha(p)==h for p,h in bindings.items())and all(sha(p)==h for p,h in source_bindings.items())
from lightgbm import LGBMRanker
scores=np.zeros(len(X));profiles={}
for held in sorted(roots):
    record=manifest['training_sets'][held];path=O/(held+'-training-rows.npz');assert sha(path)==record['sha256']
    with np.load(path)as loaded:train,group=loaded['rows'],loaded['group']
    assert all(repositories[train]!=held)and array_sha(X[train])==record['feature_sha256']and array_sha(labels[train])==record['label_sha256']
    fitted=LGBMRanker(objective='lambdarank',verbosity=-1,**parameters)
    try:fitted.fit(X[train],labels[train],group=group,feature_name=list(features))
    except Exception:
        (O/(held+'-training-failure.json')).write_text(json.dumps({'held_out':held,'training_record':record},indent=2));raise
    native=O/(held+'-native.json');native.write_text(json.dumps(fitted.booster_.dump_model(),separators=(',',':')))
    model=export_numeric_ranker(fitted.booster_.dump_model(),features=features);selected=repositories==held
    assert np.array_equal(model.predict(X[selected]),fitted.booster_.predict(X[selected]))
    destination=O/(held+'-numeric.json');destination.write_text(json.dumps(model.to_dict(),separators=(',',':')));restored=NumericRanker.from_dict(json.loads(destination.read_text()))
    scores[selected]=restored.predict(X[selected]);assert np.array_equal(scores[selected],fitted.booster_.predict(X[selected]));profiles[held]=restored.fingerprint
    manifest['folds'].append({'held_out':held,'training_repositories':record['training_repositories'],'training_queries':375,'iterations':fitted.booster_.current_iteration(),'native_sha256':sha(native),'model_sha256':sha(destination),'model_fingerprint':restored.fingerprint})
    assert fitted.booster_.current_iteration()==160
    (O/'registration.json').write_text(json.dumps(manifest,indent=2));print(json.dumps({'fold_fitted':held,'features':284}),flush=True);del fitted;gc.collect()
np.save(O/'scores.npy',scores);responses={mode:[]for mode in('baseline','actions')}
for repo in sorted(roots):
    pools=load_pools(P,requests,repositories=[repo]);native=NumericRanker.from_dict(json.loads((B/'contract_body251'/(repo+'-numeric.json')).read_text()));assert native.features==features[:251]
    for qid in sorted(pools):
        pool=pools[qid];selected=rows[qid];assert len(pool)==len(selected)
        for mode,values,profile in(('baseline',baseline[selected],native.fingerprint),('actions',scores[selected],profiles[repo])):
            order=sorted(range(len(pool)),key=lambda i:(-pool[i].signals.get('exact',0),-values[i],i))
            matches=[CodeMatch(pool[i].entity,float(values[i]),pool[i].passages,pool[i].passages[0].source_hash,pool[i].signals,pool[i].owned_regions)for i in order]
            request=SearchRequest(**requests[qid]['request']);matches=complete_evidence(matches,roots[repo],request)
            responses[mode].append({'id':qid,**present(matches,roots[repo],request,profile_version=profile).to_dict()})
    del pools,pool,matches;gc.collect()
assert all(sha(p)==digest for p,digest in bindings.items())and all(sha(p)==digest for p,digest in source_bindings.items())and parent_bindings==validate_replay_parent(F,P)and verify_frozen_source(E)==receipt
assert all(sha(roots[repo]/p)==digest for repo in roots for p,digest in index['source_repos'][repo]['file_hashes'].items())
assert not any(name in sys.modules for name in('torch','transformers','sentence_transformers'))
from ken.bench.retrieval import evaluate
casefile=E/'experiments/search-engine/datasets/development.jsonl';assert sha(casefile)=='e68275872ea3cd14abb7499c4b6a38cc99908a8ce75bd7709a549f392972fc63';cases=list(map(json.loads,casefile.read_text().splitlines()))
for mode,values in responses.items():
    assert len(values)==len({v['id']for v in values})==400
    report=evaluate(cases,values,roots=roots)
    if mode=='baseline':assert report['strict_top1']=={'hits':286,'total':400,'rate':.715}and report['identity_top1']=={'hits':298,'total':400,'rate':.745}
    (O/(mode+'-responses.jsonl')).write_text(''.join(json.dumps(v,ensure_ascii=False)+'\n'for v in values));(O/(mode+'-report.json')).write_text(json.dumps(report,indent=2))
    manifest['results'][mode]={'strict':report['strict_top1'],'identity':report['identity_top1'],'missing':report['missing_response_ids']};print(json.dumps({'mode':mode,**manifest['results'][mode]}),flush=True)
manifest['peak_rss_native']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;manifest['complete']=True
(O/'registration.json').write_text(json.dumps(manifest,indent=2))
