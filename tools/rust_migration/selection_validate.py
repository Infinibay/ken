"""Exact selection data and traces, with fixed bounds only for declared float fields."""
from __future__ import annotations
import copy,json,math
from pathlib import Path
from .index_validate import same_value,require,source_identity
from .native_json import NativeJsonCapture,identity
from .retrieval_validate import prepare_runtime,ERROR_KINDS
FORMAT='ken-search-selection-probe/1'

def close(a,b,bound):
    require(type(a)in(int,float)and type(b)in(int,float)and math.isfinite(a)and math.isfinite(b),'selection numeric category differs')
    require(abs(a-b)<=bound+bound*abs(a),'selection score exceeds fixed arithmetic bound')

def normalize(a,b,kind):
    if isinstance(a,dict):
        require(isinstance(b,dict)and a.keys()==b.keys(),'selection output fields differ')
        for key in a:
            if key=='signals':
                require(isinstance(b[key],dict)and a[key].keys()==b[key].keys(),'selection measurements differ')
                for name in a[key]:close(a[key][name],b[key][name],1e-6 if name.startswith('cosine_')else 1e-12)
                a[key]=b[key]=None
            elif key=='score'and kind=='rank':close(a[key],b[key],1e-12);a[key]=b[key]=None
            elif key in('original','expanded')and kind=='context'and isinstance(a[key],list):
                require(isinstance(b[key],list)and len(a[key])==len(b[key]),'contextual owner scores incomplete')
                for x,y in zip(a[key],b[key],strict=True):close(x,y,1e-6)
                a[key]=b[key]=None
            else:normalize(a[key],b[key],kind)
    elif isinstance(a,list):
        require(isinstance(b,list)and len(a)==len(b),'selection list membership differs')
        for x,y in zip(a,b,strict=True):normalize(x,y,kind)

def compare_case(expected,actual):
    try:
        require(expected['id']==actual['id']and expected['kind']==actual['kind'],'selection identity/order differs')
        if 'error'in expected:
            trace={k:expected[k]for k in('query_calls','judge_calls')if k in expected}
            require(set(actual)=={'id','kind','error',*trace},'selection failure trace/fields differ')
            require(actual['error']['kind']==ERROR_KINDS[expected['error']['type']]and expected['error']['message']in actual['error']['message'],'selection failure category/reason differs')
            require(all(same_value(v,actual[k])for k,v in trace.items()),'selection failure model call order differs')
        else:
            require(set(actual)=={'id','kind','result'},'unexpected selection output summary')
            a,b=copy.deepcopy(expected['result']),copy.deepcopy(actual['result']);normalize(a,b,expected['kind'])
            require(same_value(a,b),'complete selection owner/evidence or model call order differs')
        return []
    except(KeyError,TypeError,ValueError,IndexError)as error:return[str(error)]

def compare_observations(reference,actual):
    try:
        require(actual['format']==FORMAT and len(reference['cases'])==len(actual['cases']),'selection protocol/inventory differs')
        return [a['id']+': '+error for a,b in zip(reference['cases'],actual['cases'],strict=True)for error in compare_case(a,b)]
    except(KeyError,TypeError,ValueError)as error:return[str(error)]

def requests(reference):
    return dict(format=FORMAT,legacy_runtime=reference['legacy_runtime'],cases=[{k:c[k]for k in('id','kind','input')}for c in reference['cases']])

def run_capture(repo:Path,binary:Path,reference:dict,out:Path):
    sources=source_identity(repo)
    with NativeJsonCapture(binary,out,repo=repo,prefix='ken-selection-native-')as capture:
        prepare_runtime(capture);actual=capture.run(requests(reference))
    (out/'SOURCES.json').write_text(json.dumps(sources,indent=2)+'\n')
    (out/'BUILD.json').write_text(json.dumps(dict(format='ken-selection-build/1',sources=sources,native_sha256=identity(binary)['sha256']),indent=2)+'\n')
    errors=compare_observations(reference,actual)
    if errors:raise ValueError(errors)
    return actual
