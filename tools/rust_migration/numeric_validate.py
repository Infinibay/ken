"""Complete numeric observations; only declared arithmetic has a fixed bound."""
from __future__ import annotations
import json,math
from pathlib import Path
from .index_validate import require,source_identity
from .native_json import NativeJsonCapture,identity
from .retrieval_validate import prepare_runtime
FORMAT='ken-numeric-owner-probe/1'
PREFIX='ken-numeric-native-'
SCOPE='native input parsing, bounded numerical/feature/ranking operations and registered resource loading, before output serialization'
INTEGER_FIELDS={'schema','feature_version','evidence_version','attempt','rank','proposal_index','definition_ordinal','start_line','end_line','implementation_start_line','feature_index','tree_index','rows','columns','trees','entries','capacity','compressed_bytes','decoded_bytes'}
def bound(case,path):
    """Only complete declared arithmetic projections receive a tolerance."""
    p=tuple('*'if type(v)is int else v for v in path)
    family=case.get('family','');kind=case['kind']
    if kind=='production_compose'and p==('result','trace','owners','*','feature_values','*'):return 1e-6
    if family=='owner-ranking'and len(p)==6 and p[0]=='result'and p[1]in('trace','with_query','restored')and p[2:]==('owners','*','feature_values','*'):return 1e-12
    if family in('features','features-edges','features-math-edges'):
        if kind in('evidence','feature_context')and p==('result','values','*','*'):return 1e-12
        if kind in('base','coverage')and len(p)==3 and p[:2]==('result','*'):return 1e-12
    summaries={'mean','minimum','quartile','weighted'}
    arithmetic=(kind in('similarities','coverage')and(p==('result','values','*')or len(p)==3 and p[:2]==('result','coverage')and p[-1]in summaries)
                or kind=='summarize'and len(p)==2 and p[0]=='result'and p[-1]in summaries
                or kind=='maxima'and len(p)==3 and p[:2]==('result','*')and p[-1]in summaries)
    if family in('alignment','alignment-edges')and arithmetic:
        data=case['input'];kind=case['kind'];numbers=data.get('documents')if kind in('similarities','coverage')else data.get('similarities',data.get('maxima',{}))
        dtype='float32'if kind in('similarities','coverage')and data['query']['dtype']==numbers['dtype']=='float32'else numbers.get('dtype')if kind not in('similarities','coverage')else'float64'
        if path[-1]=='weighted'and data['weights']['dtype']!='float32':return 1e-12
        return 1e-6 if dtype=='float32'else 1e-12
    return None
def equal(a,b,case,path=()):
    if isinstance(a,dict):
        require(isinstance(b,dict)and a.keys()==b.keys(),'numeric fields differ: '+str(path))
        for key in a:equal(a[key],b[key],case,(*path,key))
    elif isinstance(a,list):
        require(isinstance(b,list)and len(a)==len(b),'numeric rows/membership differ: '+str(path))
        for i,(x,y)in enumerate(zip(a,b,strict=True)):equal(x,y,case,(*path,i))
    elif type(a)in(int,float):
        require(type(b)in(int,float)and math.isfinite(a)and math.isfinite(b),'numeric category differs: '+str(path))
        if path and path[-1]in INTEGER_FIELDS:require(type(a)is type(b)and a==b,'numeric metadata differs: '+str(path))
        else:
            tolerance=bound(case,path)
            if tolerance is None:require(a==b and(a!=0 or math.copysign(1,a)==math.copysign(1,b)),'exact numeric outcome differs: '+str(path))
            else:require(abs(a-b)<=tolerance+tolerance*abs(a),'numeric value exceeds fixed bound: '+str(path))
    else:require(type(a)is type(b)and a==b,'numeric identity/category differs: '+str(path))
def compare_case(expected,actual):
    try:
        require(actual.get('family')==expected.get('family'),'numeric family identity differs')
        fields={k:v for k,v in expected.items()if k not in('input','family')}
        actual={k:v for k,v in actual.items()if k!='family'}
        if expected['kind']=='evidence_admission':
            require(set(actual)=={'id','kind','error','encoder_calls','stemmer_calls'}and actual['id']==expected['id']and actual['kind']=='evidence_admission','source guard observation differs')
            require(actual['error']['type']=='ValueError'and actual['error']['message']=='ranking description source is stale'and actual['encoder_calls']==actual['stemmer_calls']==[],'source admission reached a model or lost its guard')
        else:equal(fields,actual,expected)
        return[]
    except(KeyError,TypeError,ValueError,IndexError)as error:return[str(error)]
def compare_observations(reference,actual):
    try:
        require(actual['format']==FORMAT and len(reference['cases'])==len(actual['cases']),'numeric protocol/inventory differs')
        return[a['id']+': '+e for a,b in zip(reference['cases'],actual['cases'],strict=True)for e in compare_case(a,b)]
    except(KeyError,TypeError,ValueError)as error:return[str(error)]
def requests(reference,resources):
    return dict(format=FORMAT,resources=resources,cases=[{k:c[k]for k in('id','family','kind','input')}for c in reference['cases']])
def run_capture(repo:Path,binary:Path,reference:dict,out:Path):
    import shutil
    sources=source_identity(repo)
    with NativeJsonCapture(binary,out,repo=repo,prefix=PREFIX)as capture:
        prepare_runtime(capture)
        shutil.copytree(repo/'crates/ken-retrieval/resources/ranking',capture.root/'ranking')
        shutil.copyfile(repo/'src/ken/embedder/data/ken__static-qwen3-r512-v2.npz',capture.root/'static.npz')
        actual=capture.run(requests(reference,dict(ranking='ranking',static='static.npz')))
    (out/'SOURCES.json').write_text(json.dumps(sources,indent=2)+'\n')
    (out/'BUILD.json').write_text(json.dumps(dict(format='ken-numeric-build/1',sources=sources,native_sha256=identity(binary)['sha256']),indent=2)+'\n')
    errors=compare_observations(reference,actual)
    if errors:raise ValueError(errors)
    return actual
