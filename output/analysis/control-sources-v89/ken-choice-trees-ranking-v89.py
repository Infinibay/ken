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
from listwise_linear import RankGroup,prepare_listwise
from choice_loss import QueryChoiceLoss
from ken.bench.numeric_export import export_numeric_ranker
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.model import CodeMatch,SearchRequest
from ken.retrieval.evidence import complete_evidence
from ken.retrieval.presentation import present
from ken.retrieval.numeric_ranker import NumericRanker
O=R/'output/analysis/choice-trees-ranking-v89';O.mkdir(exist_ok=False)
P=R/'output/analysis/c-source-reindex-v66c';F=R/'output/analysis/context-views-features-source7-v69';V=R/'output/analysis/context-views-source7-v69';B=R/'output/analysis/source7-context-views-ranking-v69';D=R/'output/analysis/source7-ranking-v66c/training-matrix.npz'
def sha(path):
    with Path(path).open('rb')as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()
array_sha=lambda a:hashlib.sha256(memoryview(np.ascontiguousarray(a)).cast('B')).hexdigest()
receipt=verify_frozen_source(E);assert receipt=='5ab6da502c32b858383bec48b06e37b571ef7a74d4e2ae405ffff9f1755273c2'
assert sha(F/'registration.json')=='74bd9b403b052d6106730857c6a7498a6f98d05d0c8e4417cd048908027c04d2'
assert sha(V/'registration.json')=='d4ee096ad988d8e87811275299039f95afc65cc472c5da4e4211e725ba999554'
assert sha(B/'registration.json')=='9bb0d87b2f5306c7b3eee1a6484e271c6b3cfdb182fc3d408663bef6344fe814'
assert sha(D)=='06c66ff3a3ea4c8cf6af7100df287dd41718a9f63558840e56adea22bbb890ff'
roots={k:Path(v)for k,v in json.loads((R/'experiments/search-engine/datasets/roots-development.json').read_text()).items()}
source=json.loads((V/'registration.json').read_text());index=json.loads((P/'registration.json').read_text());features_registration=json.loads((F/'registration.json').read_text());producer=json.loads((B/'registration.json').read_text())
features=tuple(features_registration['features']);assert len(features)==251
source_bindings={}
for repo in sorted(roots):
    files=index['source_repos'][repo]['file_hashes'];assert len(files)==index['source_repos'][repo]['indexed_files']
    assert all(sha(roots[repo]/p)==digest for p,digest in files.items())
    meta=source['source_repos'][repo]
    paths={P/'indices'/(repo+'.db'):index['source_repos'][repo]['new_source_index_sha256'],P/'context'/(repo+'.db'):meta['base_full_context_sha256'],V/(repo+'-source.db'):meta['source_db_sha256'],V/(repo+'-vectors.npy'):meta['vectors_sha256']}
    assert all(sha(p)==digest for p,digest in paths.items());source_bindings.update({str(p):digest for p,digest in paths.items()})
assert sum(len(m['file_hashes'])for m in index['source_repos'].values())==6314
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
matrices=[];qids=[];repositories=[];labels=[];bindings={str(p):sha(p)for p in(D,F/'registration.json',V/'registration.json',B/'registration.json',P/'registration.json',B/'contract_body251/scores.npy',E/'experiments/search-engine/cpu-choice-trees-v89.md',E/'experiments/search-engine/listwise_linear.py',E/'experiments/search-engine/choice_loss.py')}
assert sha(B/'contract_body251/scores.npy')=='c9b192923fd4e3b9b2b621c3b2192c17bfd0c7fcc7baaf2e74dbb1dab83088c3'
old_scores=np.load(B/'contract_body251/scores.npy');baseline=[]
for repo in sorted(roots):
    path=F/(repo+'.npz');assert sha(path)==features_registration['query_repos'][repo]['output_sha256'];bindings[str(path)]=sha(path)
    with np.load(path)as loaded:data={name:loaded[name]for name in('x','qid','index')}
    for qid,group in itertools.groupby(range(len(data['qid'])),key=lambda i:str(data['qid'][i])):
        rows=np.array(list(group));before=prior[qid]
        assert len(rows)==len(before)==counts[qid][0] and requests[qid]['repo_id']==repo and all(old['repo'][before]==repo)
        assert np.array_equal(data['index'][rows],np.arange(len(rows)))and np.array_equal(data['x'][rows,:235],old['x'][before])
        matrices.append(data['x'][rows]);baseline.extend(old_scores[before]);labels.extend(old['y'][before]);qids.extend([qid]*len(rows));repositories.extend([repo]*len(rows))
X=np.concatenate(matrices);qids=np.array(qids);repositories=np.array(repositories);labels=np.array(labels);baseline=np.array(baseline)
assert X.shape==(167360,251)and np.isfinite(X).all()
del old,prior,old_scores,data,matrices;gc.collect()
rows={qid:np.flatnonzero(qids==qid)for qid in requests};groups=[];choices={}
for qid in sorted(requests):
    positions=rows[qid];assert np.array_equal(positions,np.arange(positions[0],positions[-1]+1))
    eligible=labels[positions];reason='exact_bypass'if counts[qid][1]else'no_positive'if not eligible.any()else'no_negative'if eligible.all()else None
    choices[qid]={'repo':requests[qid]['repo_id'],'rows':len(positions),'positive':int(eligible.sum()),'skip_reason':reason,'feature_sha256':array_sha(X[positions]),'label_sha256':array_sha(eligible)}
    if reason is None:groups.append(RankGroup(requests[qid]['repo_id'],qid,X[positions[0]:positions[-1]+1],eligible))
manifest={'scope':'Query-choice251 tree ranking89, fixed16whole-repo excluded folds; all400 strict unchanged; no additional encoder or default/private claim','engine_receipt':receipt,'script_sha256':sha(__file__),'protocol_sha256':sha(E/'experiments/search-engine/cpu-choice-trees-v89.md'),'inputs':bindings,'source_bindings':source_bindings,'parent_bindings':parent_bindings,'features':features,'matrix_sha256':array_sha(X),'labels_sha256':array_sha(labels),'training_groups':choices,'normalizers':{},'pre_fit_ready':False,'folds':[],'results':{},'runtime':{p:version(p)for p in('numpy','lightgbm')},'parameters':{'num_boost_round':160,'num_leaves':15,'min_data_in_leaf':40,'lambda_l2':2.,'learning_rate':.08,'seed':42,'data_random_seed':42,'feature_fraction_seed':42,'bagging_seed':42,'num_threads':1,'deterministic':True,'force_col_wise':True,'boost_from_average':False,'verbosity':-1,'metric':'None','device_type':'cpu'},'numerical_hessian_floor':1e-12,'readout':'choice_trees_only'}
for held in sorted(roots):
    prepared=prepare_listwise(groups,excluded_repositories={held})
    assert set(prepared.repositories)==set(roots)-{held} and all(requests[q]['repo_id']!=held for q in prepared.query_ids)
    path=O/(held+'-normalizer.npz');np.savez(path,means=prepared.means,scales=prepared.scales)
    manifest['normalizers'][held]={'sha256':sha(path),'training_repositories':prepared.repositories,'query_ids':prepared.query_ids,'normalized_matrix_sha256':array_sha(prepared.values),'targets_sha256':array_sha(prepared.targets),'starts_sha256':array_sha(prepared.starts),'rows':len(prepared.values)}
    del prepared;gc.collect()
manifest['pre_fit_ready']=True
(O/'registration.json').write_text(json.dumps(manifest,indent=2));print(json.dumps({'pre_fit_ready':True,'training_queries':len(groups),'waiting_for':str(O/'PRE-FIT-REVIEW-ACCEPTED.json')}),flush=True)
while True:
    try:
        accepted=json.loads((O/'PRE-FIT-REVIEW-ACCEPTED.json').read_text())
        if accepted['engine_receipt']==receipt and accepted['controller_sha256']==manifest['script_sha256']and accepted['pre_fit_registration_sha256']==sha(O/'registration.json'):break
    except(FileNotFoundError,json.JSONDecodeError):pass
    time.sleep(5)
assert all(sha(p)==digest for p,digest in bindings.items())and all(sha(p)==digest for p,digest in source_bindings.items())
from lightgbm import Dataset,train
scores=np.zeros(len(X));profiles={}
for held in sorted(roots):
    prepared=prepare_listwise(groups,excluded_repositories={held})
    reference=manifest['normalizers'][held]
    assert list(prepared.repositories)==list(reference['training_repositories'])and list(prepared.query_ids)==list(reference['query_ids'])
    assert array_sha(prepared.targets)==reference['targets_sha256']and array_sha(prepared.starts)==reference['starts_sha256']
    train_rows=np.concatenate([rows[qid]for qid in prepared.query_ids])
    assert all(repositories[train_rows]!=held)
    training_x=X[train_rows];training_y=labels[train_rows]
    loss=QueryChoiceLoss(prepared.targets,prepared.starts)
    counts=np.diff(np.r_[prepared.starts,len(prepared.targets)]);assert np.array_equal(training_y,prepared.targets)
    del prepared;gc.collect()
    dataset=Dataset(training_x,label=training_y,group=counts,feature_name=list(features),free_raw_data=False)
    trace=[]
    def objective(predictions,data):
        assert data is dataset
        gradient,diagonal=loss.derivatives(predictions)
        trace.append({'loss':loss.value(predictions),'max_abs_gradient':float(np.max(np.abs(gradient))),'floored_hessians':int(np.count_nonzero(diagonal<1e-12))})
        return gradient,np.maximum(diagonal,1e-12)
    params={**manifest['parameters'],'objective':objective}
    try:fitted=train(params,dataset,num_boost_round=160)
    except Exception:
        (O/(held+'-training-failure.json')).write_text(json.dumps({'held_out':held,'trace':trace},indent=2));raise
    assert len(trace)==160 and fitted.current_iteration()==160
    native_path=O/(held+'-native.json');native_path.write_text(json.dumps(fitted.dump_model(),separators=(',',':')))
    model=export_numeric_ranker(fitted.dump_model(),features=features)
    selected=repositories==held;test_values=X[selected]
    native_test=fitted.predict(test_values,num_threads=1)
    assert np.array_equal(model.predict(test_values),native_test)
    path=O/(held+'-numeric.json');path.write_text(json.dumps(model.to_dict(),separators=(',',':')))
    restored=NumericRanker.from_dict(json.loads(path.read_text()));assert np.array_equal(restored.predict(test_values),native_test)
    final_training=fitted.predict(training_x,num_threads=1);assert np.array_equal(restored.predict(training_x),final_training)
    np.savez(O/(held+'-final-training.npz'),rows=train_rows,scores=final_training)
    scores[selected]=native_test;profiles[held]=model.fingerprint
    fold={'held_out':held,'training_repositories':list(reference['training_repositories']),'query_ids':list(reference['query_ids']),'training_queries':len(reference['query_ids']),'training_rows':len(train_rows),'iterations':160,'model_sha256':sha(path),'native_model_sha256':sha(native_path),'final_training_sha256':sha(O/(held+'-final-training.npz')),'trace':trace,'final_training_loss':loss.value(final_training)}
    manifest['folds'].append(fold)
    (O/'registration.json').write_text(json.dumps(manifest,indent=2));print(json.dumps({'fold_fitted':held,'iterations':160,'final_training_loss':fold['final_training_loss']}),flush=True)
    del dataset,fitted,training_x,training_y,loss,final_training,test_values;gc.collect()
np.save(O/'scores.npy',scores);responses={mode:[]for mode in('baseline','choice_trees')}
for repo in sorted(roots):
    pools=load_pools(P,requests,repositories=[repo]);native=NumericRanker.from_dict(json.loads((B/'contract_body251'/(repo+'-numeric.json')).read_text()));assert native.features==features
    for qid in sorted(pools):
        pool=pools[qid];selected=rows[qid];assert len(pool)==len(selected)
        for mode,values,profile in(('baseline',baseline[selected],native.fingerprint),('choice_trees',scores[selected],profiles[repo])):
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
