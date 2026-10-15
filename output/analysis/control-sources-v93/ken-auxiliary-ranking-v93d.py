"""One original251 control with independently curated96 auxiliary training queries."""
import argparse,gc,hashlib,itertools,json,resource,sys,time
from importlib.metadata import version
from pathlib import Path
import ken
import numpy as np
R=Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
E=Path(ken.__file__).resolve().parents[2]
sys.path.insert(0,str(E/'experiments/search-engine'))
from replay import load_pools
from replay_parent import validate_replay_parent
from ken.bench.dataset import load_dataset
from ken.bench.owner_eligibility import eligible_owner
from ken.bench.retrieval import request_for_case
from ken.bench.numeric_export import export_numeric_ranker
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.model import CodeMatch,SearchRequest,Span,merge_spans
from ken.retrieval.evidence import complete_evidence
from ken.retrieval.presentation import present
from ken.retrieval.numeric_ranker import NumericRanker
parser=argparse.ArgumentParser()
for name in ('aux-pools','aux-cases','output'):parser.add_argument('--'+name,type=Path,required=True)
for name in ('aux-cases-sha256','aux-registration-sha256'):parser.add_argument('--'+name,required=True)
args=parser.parse_args();O=args.output;O.mkdir(exist_ok=False)

P=R/'output/analysis/c-source-reindex-v66c';F=R/'output/analysis/context-views-features-source7-v69';V=R/'output/analysis/context-views-source7-v69';B=R/'output/analysis/source7-context-views-ranking-v69';D=R/'output/analysis/source7-ranking-v66c/training-matrix.npz'
def sha(path):
    with Path(path).open('rb')as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()
array_sha=lambda a:hashlib.sha256(memoryview(np.ascontiguousarray(a)).cast('B')).hexdigest()
receipt=verify_frozen_source(E);assert receipt=='4ebee803348ded840b948be0912e58924faf6ae218cd107d1cbb6963cd2f892d'
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
matrices=[];qids=[];repositories=[];labels=[];bindings={str(p):sha(p)for p in(D,F/'registration.json',V/'registration.json',B/'registration.json',P/'registration.json',B/'contract_body251/scores.npy',E/'experiments/search-engine/cpu-auxiliary-training-v93.md')}
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
rows={qid:np.flatnonzero(qids==qid)for qid in requests};choices={}
for qid in sorted(requests):
    positions=rows[qid];assert np.array_equal(positions,np.arange(positions[0],positions[-1]+1))
    eligible=labels[positions];reason='exact_bypass'if counts[qid][1]else'no_positive'if not eligible.any()else'no_negative'if eligible.all()else None
    choices[qid]={'repo':requests[qid]['repo_id'],'rows':len(positions),'positive':int(eligible.sum()),'public_group_kind':reason or 'mixed','feature_sha256':array_sha(X[positions]),'label_sha256':array_sha(eligible)}

Q=args.aux_pools;assert sha(Q/'registration.json')==args.aux_registration_sha256
auxiliary=json.loads((Q/'registration.json').read_text())
assert auxiliary['complete']and auxiliary['source_phase_complete']and auxiliary['engine_receipt']==receipt
assert len(auxiliary['repos'])==len(auxiliary['source_repos'])==8
assert auxiliary['script_sha256']=='27de73dc01642cc4b17a08b9f1c286e353b05ac456c6bf5ec2a550923a488bcb'
assert auxiliary['worker_sha256']=='eea1bbdae068245e78906f92e79e7c391e6a3bc4d1e12a2c31ed80b35af8b97d'
assert all(sha(p)==h for p,h in auxiliary['inputs'].items())
assert sha(Q/'candidates.jsonl')==auxiliary['candidates_sha256']
S=Path(auxiliary['source_root']);assert sha(S/'registration.json')==auxiliary['source_registration_sha256']
aux_source=json.loads((S/'registration.json').read_text());assert aux_source['complete']and aux_source['engine_receipt']==receipt
assert len(aux_source['source_repos'])==len(aux_source['context_repos'])==len(aux_source['views_repos'])==8
assert aux_source['script_sha256']=='48809026d6ea68306c64605a708d2dd51c21ab8a70c4a0f0be175f95c9c0ee61'
assert all(sha(p)==h for p,h in aux_source['inputs'].items())
aux_roots={v['name']:Path(v['root'])for v in aux_source['repositories']}
assert set(aux_roots)==set(auxiliary['repos'])and set(aux_roots).isdisjoint(roots)
AUX=Path('/private/tmp/ken-search-auxiliary-training-20261015').resolve()
sealed_receipt=AUX/'receipt-auxiliary-training-v1.json';sealed_archive=AUX/'auxiliary-training-pilot-v1.sealed.tar.gz';sealed_file=AUX/'pilot-v1/seal.json'
assert sha(sealed_receipt)=='bd84e1af801f271f7643a39f9010e1b8d11965e3a564a66ea814aee47c3fd7c7'
assert sha(sealed_archive)=='1d9152342ef3c9a547461c07775d25fc556f1937ab7c48ae35009f2d79bdfcf1'
assert sha(sealed_file)=='02d18ab1d6a603cc29d89ec3bc57087353f0d4139120d9a1f8e9944115970473'
sealed=json.loads(sealed_receipt.read_text());leaf=json.loads(sealed_file.read_text())
assert sealed['seal']['sha256']==sha(sealed_file)and sealed['sealed_archive']['sha256']==sha(sealed_archive)
assert sealed['cases']['sha256']==leaf['files']['cases.jsonl']['sha256']=='fa2f0499bfacf6ae2fbe29dc3e809c9144c701031d4f00fc07397e61af2f97a9'
assert sealed['requests']['sha256']==leaf['files']['requests.jsonl']['sha256']=='e2cd83b6d827b86c535600dec54d740a06e1d7ee2e11f1425daeb0ab5530e3ef'
assert args.aux_cases.resolve()==(AUX/'pilot-v1/cases.jsonl').resolve()and args.aux_cases_sha256==sealed['cases']['sha256']
curation_bindings={str(p):sha(p)for p in(sealed_receipt,sealed_archive,sealed_file)}
assert auxiliary['curation_bindings']==curation_bindings
assert auxiliary['inputs'][str(AUX/'pilot-v1/requests.jsonl')]==sealed['requests']['sha256']
aux_dataset=load_dataset(args.aux_cases);assert aux_dataset.sha256==args.aux_cases_sha256
aux_cases={c['id']:c for c in aux_dataset};assert len(aux_cases)==96 and set(aux_cases).isdisjoint(requests)
assert all(c['answerable']and c['purpose']=='implementation'for c in aux_cases.values())
assert sum(c['language']=='en'for c in aux_cases.values())==64 and sum(c['language']=='es'for c in aux_cases.values())==32
assert set(c['repo_id']for c in aux_cases.values())==set(aux_roots)
aux_public={}
for path in sorted((Q/'requests').glob('*.jsonl')):
 for r in map(json.loads,path.read_text().splitlines()):assert r['id']not in aux_public;aux_public[r['id']]=r
assert set(aux_public)==set(aux_cases)
assert all(r=={'id':qid,'repo_id':aux_cases[qid]['repo_id'],'request':request_for_case(aux_cases[qid])}for qid,r in aux_public.items())
aux_repos={v['name']:v for v in aux_source['repositories']}
aux_bindings={str(p):sha(p)for p in (Q/'registration.json',Q/'candidates.jsonl',S/'registration.json',args.aux_cases)}
aux_bindings.update(curation_bindings)
matrices=[X];qid_parts=[qids];repo_parts=[repositories];label_parts=[labels]
aux_choices={}
for repo in sorted(aux_roots):
 root=aux_roots[repo];record=auxiliary['repos'][repo];assert record['queries']==12 and record['exit_code']==0
 request_file=Q/'requests'/(repo+'.jsonl');assert sha(request_file)==record['requests_sha256']
 worker_dir=Q/'workers'/repo;worker_file=worker_dir/'registration.json'
 assert sha(worker_file)==record['worker_registration_sha256']
 worker=json.loads(worker_file.read_text())
 assert worker['complete']and worker['engine_receipt']==receipt and worker['script_sha256']==auxiliary['worker_sha256']
 assert tuple(worker['features'])==features and worker['features_sha256']==record['features_sha256']
 assert sha(worker_dir/'features.npz')==worker['features_sha256']
 assert sha(worker_dir/'candidates.jsonl')==worker['candidates_sha256']
 assert worker['source_registration_sha256']==auxiliary['source_registration_sha256']
 assert str(worker['generation'])==str(aux_source['context_repos'][repo]['generation'])
 expected_inputs={request_file,R/'output/models/static-comparison-registration.json',R/'output/models/es-en-cpu-registration-v21.json',R/'output/models/cpu-context-registration-v42.json',S/'indices'/(repo+'.db'),S/'context'/(repo+'.db')}
 assert set(worker['inputs'])=={str(path)for path in expected_inputs}
 assert worker['inputs'][str(request_file)]==record['requests_sha256']
 assert all(sha(path)==digest for path,digest in worker['inputs'].items())
 expected_views={S/'views'/(repo+'-source.db'),S/'views'/(repo+'-vectors.npy'),S/'views/registration.json',S/'views/model-registration.json'}
 assert set(worker['view_receipts'])=={str(path)for path in expected_views}
 assert all(sha(path)==digest for path,digest in worker['view_receipts'].items())
 aux_bindings.update(worker['inputs']);aux_bindings.update(worker['view_receipts']);aux_bindings[str(worker_file)]=sha(worker_file)

 assert sum(c['repo_id']==repo for c in aux_cases.values())==12
 assert all(c['repo_commit']==aux_repos[repo]['revision']for c in aux_cases.values()if c['repo_id']==repo)
 files=aux_source['source_repos'][repo]['file_hashes'];assert all(sha(root/p)==h for p,h in files.items())
 for c in aux_cases.values():
  if c['repo_id']!=repo:continue
  for alternative in c['alternatives']:
   assert files[alternative['path']]==alternative['source_hash']
   union=merge_spans(Span(a['start_line'],a['end_line'])for a in alternative['anchors'])
   assert sum(a.end_line-a.start_line+1 for a in union)<=40
 path=Q/(repo+'.npz');assert sha(path)==record['features_sha256'];aux_bindings[str(path)]=sha(path)
 auxiliary_index=Q/'indices'/(repo+'.db');assert sha(auxiliary_index)==aux_source['source_repos'][repo]['new_source_index_sha256'];aux_bindings[str(auxiliary_index)]=sha(auxiliary_index)
 with np.load(path)as loaded:data={name:loaded[name]for name in('x','qid','index')}
 assert data['x'].shape==(len(data['qid']),251)and np.isfinite(data['x']).all()
 pools=load_pools(Q,aux_public,repositories=[repo]);local_labels=[]
 for qid,positions in itertools.groupby(range(len(data['qid'])),key=lambda i:str(data['qid'][i])):
  selected=np.array(list(positions));pool=pools[qid]
  assert aux_cases[qid]['repo_id']==repo and np.array_equal(data['index'][selected],np.arange(len(pool)))
  assert len(pool)==len(selected)
  y=np.array([int(eligible_owner(c.entity,c.passages[0].source_hash,c.owned_regions,aux_cases[qid]['alternatives']))for c in pool])
  local_labels.extend(y)
  aux_choices[qid]={'repo':repo,'rows':len(selected),'positive':int(y.sum()),'feature_sha256':array_sha(data['x'][selected]),'label_sha256':array_sha(y)}
 matrices.append(data['x']);qid_parts.append(data['qid']);repo_parts.append(np.array([repo]*len(data['qid'])));label_parts.append(np.array(local_labels))
 del pools,pool,data;gc.collect()
assert len(aux_choices)==96
original_rows=len(X);X=np.concatenate(matrices);qids=np.concatenate(qid_parts);repositories=np.concatenate(repo_parts);labels=np.concatenate(label_parts)
assert X.shape[1]==251 and len(X)==len(qids)==len(repositories)==len(labels)and np.isfinite(X).all()and np.isin(labels,(0,1)).all()
assert set(qids)==set(requests)|set(aux_cases)
del matrices,qid_parts,repo_parts,label_parts;gc.collect()
K=R/'output/analysis/core-ranker-v18/registration.json';assert sha(K)=='97ce68f706158a4ee2a6c83e401a307b5ea0728aa3b1a4afa3846637963346d9'
parameters=json.loads(K.read_text())['parameters'];bindings[str(K)]=sha(K)
manifest={'scope':'One fixed original251 LambdaRank control93;96independent auxiliary TRAINING cases+375nonhelddevgroups per fold; only originalALL400evaluated, original eligibility/ALLanchors/budgets unchanged; no new encoder','engine_receipt':receipt,'script_sha256':sha(__file__),'inputs':bindings,'source_bindings':source_bindings,'parent_bindings':parent_bindings,'auxiliary_bindings':aux_bindings,'features':features,'parameters':parameters,'original_dev_rows':original_rows,'matrix_sha256':array_sha(X),'labels_sha256':array_sha(labels),'public_groups':choices,'auxiliary_groups':aux_choices,'training_sets':{},'pre_fit_ready':False,'folds':[],'results':{},'runtime':{p:version(p)for p in('numpy','lightgbm')}}
for held in sorted(roots):
 train=np.flatnonzero(repositories!=held);test=np.flatnonzero(repositories==held)
 query_ids=list(dict.fromkeys(qids[train]));assert len(query_ids)==471
 assert set(query_ids)==(set(requests)-{q for q in requests if requests[q]['repo_id']==held})|set(aux_cases)
 sizes=np.array([len(list(g))for _,g in itertools.groupby(qids[train])]);assert sizes.sum()==len(train)and len(sizes)==471
 path=O/(held+'-training-rows.npz');np.savez(path,rows=train,group=sizes)
 manifest['training_sets'][held]={'sha256':sha(path),'training_repositories':sorted(set(repositories[train])),'query_ids':query_ids,'feature_sha256':array_sha(X[train]),'label_sha256':array_sha(labels[train]),'rows':len(train),'groups':471}
 assert manifest['training_sets'][held]['training_repositories']==sorted((set(roots)-{held})|set(aux_roots))
manifest['pre_fit_ready']=True;(O/'registration.json').write_text(json.dumps(manifest,indent=2));print(json.dumps({'pre_fit_ready':True,'features':251,'evaluated_original_queries':400,'auxiliary_training_queries':96,'folds':16,'waiting_for':str(O/'PRE-FIT-REVIEW-ACCEPTED.json')}),flush=True)
while True:
    try:
        accepted=json.loads((O/'PRE-FIT-REVIEW-ACCEPTED.json').read_text())
        if accepted['engine_receipt']==receipt and accepted['controller_sha256']==manifest['script_sha256']and accepted['pre_fit_registration_sha256']==sha(O/'registration.json'):break
    except(FileNotFoundError,json.JSONDecodeError):pass
    time.sleep(5)
assert all(sha(p)==h for p,h in bindings.items())and all(sha(p)==h for p,h in source_bindings.items())and all(sha(p)==h for p,h in aux_bindings.items())
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
    manifest['folds'].append({'held_out':held,'training_repositories':record['training_repositories'],'training_queries':471,'iterations':fitted.booster_.current_iteration(),'native_sha256':sha(native),'model_sha256':sha(destination),'model_fingerprint':restored.fingerprint})
    assert fitted.booster_.current_iteration()==160
    (O/'registration.json').write_text(json.dumps(manifest,indent=2));print(json.dumps({'fold_fitted':held,'features':251}),flush=True);del fitted;gc.collect()
np.save(O/'scores.npy',scores);responses={mode:[]for mode in('baseline','auxiliary')}
for repo in sorted(roots):
    pools=load_pools(P,requests,repositories=[repo]);native=NumericRanker.from_dict(json.loads((B/'contract_body251'/(repo+'-numeric.json')).read_text()));assert native.features==features
    for qid in sorted(pools):
        pool=pools[qid];selected=rows[qid];assert len(pool)==len(selected)
        for mode,values,profile in(('baseline',baseline[selected],native.fingerprint),('auxiliary',scores[selected],profiles[repo])):
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
assert all(sha(p)==h for p,h in aux_bindings.items())
assert all(sha(aux_roots[repo]/path)==digest for repo in aux_roots for path,digest in aux_source['source_repos'][repo]['file_hashes'].items())
manifest['peak_rss_native']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;manifest['complete']=True
(O/'registration.json').write_text(json.dumps(manifest,indent=2))
