"""Exact source-piece observations, with only the approved feature-column bounds."""
from __future__ import annotations
import json,math,shutil
from copy import deepcopy
from pathlib import Path
from .index_validate import require,source_identity
from .native_json import NativeJsonCapture,identity
from .retrieval_validate import prepare_runtime
FORMAT='ken-source-piece-probe/1'
PREFIX='ken-source-pieces-native-'
SCOPE='native input parsing, disposable source scenarios, piece projection/ranking/presentation and registered resource loading, before output serialization'
GUARDS={'catalog_admission':'catalog source owner is invalid','assembly_admission':'retrieved member is outside the piece source'}
def portable_diagnostics(case):
    """Remove only macOS's lexical/canonical alias of the owned temp root."""
    value=case
    if case.get('family')=='presentation'and'result'in case:
        result=case['result'];response=result['response'];warnings=response['warnings']
        if any('/private{project}'in warning for warning in warnings):
            require(type(result['characters'])is int and result['characters']==len(json.dumps(response,ensure_ascii=False,separators=(',',':'))),'piece reported character count differs')
            value=deepcopy(case);new=value['result'];normalized=[warning.replace('/private{project}','{project}')for warning in warnings]
            new['response']['warnings']=normalized
            new['characters']-=sum(len(a)-len(b)for a,b in zip(warnings,normalized,strict=True))
    return value
def bound(case,path):
    if case['kind']=='piece_features'and len(path)==4 and path[:2]==('result','values'):
        return 1e-6 if case['input'].get('production')and path[-1]>=30 else 1e-12
    if case['kind']=='piece_rank'and len(path)==5 and path[:3]==('result','features','values'):
        return 1e-6 if case['input'].get('production')and path[-1]>=30 else 1e-12
    return None
def equal(expected,actual,case,path=()):
    if isinstance(expected,dict):
        require(isinstance(actual,dict)and expected.keys()==actual.keys(),'piece fields differ: '+str(path))
        for key in expected:equal(expected[key],actual[key],case,(*path,key))
    elif isinstance(expected,list):
        require(isinstance(actual,list)and len(expected)==len(actual),'piece rows/membership differ: '+str(path))
        for i,(a,b)in enumerate(zip(expected,actual,strict=True)):equal(a,b,case,(*path,i))
    elif type(expected)in(int,float):
        require(type(actual)in(int,float)and math.isfinite(expected)and math.isfinite(actual),'piece numeric category differs: '+str(path))
        if type(expected)is int:require(type(actual)is int and expected==actual,'piece integer metadata differs: '+str(path))
        else:
            tolerance=bound(case,path)
            if tolerance is None or expected==0:require(expected==actual and(expected!=0 or math.copysign(1,expected)==math.copysign(1,actual)),'exact piece outcome differs: '+str(path))
            else:require(abs(expected-actual)<=tolerance+tolerance*abs(expected),'piece feature exceeds fixed bound: '+str(path))
    else:require(type(expected)is type(actual)and expected==actual,'piece identity/category differs: '+str(path))
def compare_case(expected,actual):
    try:
        require(all(actual.get(k)==expected.get(k)for k in('id','family','kind')),'piece case identity/order differs')
        if expected['kind']in GUARDS:
            require(set(actual)=={'id','family','kind','error'}and actual['error']==dict(type='ValueError',message=GUARDS[expected['kind']]),'piece source admission guard differs')
        else:equal({k:v for k,v in portable_diagnostics(expected).items()if k!='input'},portable_diagnostics(actual),expected)
        return[]
    except(KeyError,TypeError,ValueError,IndexError)as error:return[str(error)]
def compare_observations(reference,actual):
    try:
        require(set(actual)=={'format','platform','machine','cases','metrics'},'unexpected piece protocol fields')
        runtime=reference['runtime'];system='macos'if runtime['system']=='Darwin'else'linux'
        require(actual['format']==FORMAT and actual['platform']==system and actual['machine']==runtime['machine'],'piece platform/protocol differs')
        metrics=actual['metrics'];require(set(metrics)=={'elapsed_s','max_rss_bytes','scope'}and metrics['scope']==SCOPE,'piece metrics scope differs')
        require(type(metrics['elapsed_s'])is float and math.isfinite(metrics['elapsed_s'])and metrics['elapsed_s']>=0 and type(metrics['max_rss_bytes'])is int and metrics['max_rss_bytes']>0,'piece usage absent/invalid')
        require(len(reference['cases'])==len(actual['cases']),'piece input inventory differs')
        return[a['id']+': '+e for a,b in zip(reference['cases'],actual['cases'],strict=True)for e in compare_case(a,b)]
    except(KeyError,TypeError,ValueError)as error:return[str(error)]
def requests(reference,resources):
    return dict(format=FORMAT,resources=resources,cases=[dict(id=c['id'],family=reference['family'],kind=c['kind'],input=c['input'])for c in reference['cases']])
def run_capture(repo:Path,binary:Path,reference:dict,out:Path):
    sources=source_identity(repo)
    with NativeJsonCapture(binary,out,repo=repo,prefix=PREFIX)as capture:
        prepare_runtime(capture)
        shutil.copytree(repo/'crates/ken-retrieval/resources/ranking',capture.root/'ranking')
        shutil.copyfile(repo/'src/ken/embedder/data/ken__static-qwen3-r512-v2.npz',capture.root/'static.npz')
        actual=capture.run(requests(reference,dict(ranking='ranking',static='static.npz')))
    (out/'SOURCES.json').write_text(json.dumps(sources,indent=2)+'\n')
    (out/'BUILD.json').write_text(json.dumps(dict(format='ken-piece-build/1',sources=sources,native_sha256=identity(binary)['sha256']),indent=2)+'\n')
    normalized=dict(reference,cases=[dict(c,family=reference['family'])for c in reference['cases']])
    errors=compare_observations(normalized,actual)
    if errors:raise ValueError(errors)
    return actual
