"""Replay kernel results with exact ordered ownership and fixed arithmetic bounds."""
from __future__ import annotations
import copy,math
from pathlib import Path
from .index_validate import same_value,require,source_identity
from .native_json import NativeJsonCapture,identity,load
FORMAT='ken-retrieval-kernel-probe/1'
ERROR_KINDS={'ValueError':'invalid','IndexVersionError':'index_version','KeyError':'invalid','TypeError':'invalid'}
def close(left,right,absolute,relative):
    if isinstance(left,dict)or isinstance(right,dict):require(same_value(left,right),'nonfinite numeric categories differ');return
    require(type(left)in(int,float)and type(right)is type(left)and math.isfinite(left)and math.isfinite(right),'numeric type/finite category differs')
    require(abs(left-right)<=absolute+relative*abs(left),'kernel score exceeds the predefined arithmetic bound')
def normalize_signals(left,right,absolute,relative):
    require(isinstance(left,dict)and isinstance(right,dict)and left.keys()==right.keys(),'kernel measurements missing or unexpected')
    for key in left:close(left[key],right[key],absolute,relative)
    return {key:None for key in left},{key:None for key in right}

def compare_case(expected:dict,actual:dict)->list[str]:
    try:
        require(expected['id']==actual['id']and expected['kind']==actual['kind'],'kernel case identity/order differs')
        if 'error'in expected:
            require(set(actual)=={'id','kind','error'}and actual['error']['kind']==ERROR_KINDS[expected['error']['type']],'kernel failure category differs')
            require(expected['error']['message']in actual['error']['message'],'kernel failure reason differs');return []
        require(set(actual)=={'id','kind','result'},'unexpected kernel output/claimed summary')
        left=copy.deepcopy(expected['result']);right=copy.deepcopy(actual['result']);kind=expected['kind']
        if kind=='bm25f':close(left,right,1e-12,1e-12);return []
        if kind=='postings':
            require(isinstance(left,dict)and isinstance(right,dict)and left.keys()==right.keys(),'posting membership differs')
            for key in left:left[key],right[key]=normalize_signals(left[key],right[key],1e-12,1e-12)
        elif kind in('dense','fusion'):
            require(isinstance(left,list)and isinstance(right,list)and len(left)==len(right),'source owner count differs')
            bound=1e-6 if kind=='dense'else 1e-12
            for a,b in zip(left,right,strict=True):
                a['signals'],b['signals']=normalize_signals(a['signals'],b['signals'],bound,bound)
                require(len(a['passages'])==len(b['passages']),'owned evidence count differs')
                for p,q in zip(a['passages'],b['passages'],strict=True):p['signals'],q['signals']=normalize_signals(p['signals'],q['signals'],bound,bound)
        require(same_value(left,right),'complete kernel data or owner/evidence ordering differs');return []
    except(KeyError,TypeError,ValueError,IndexError)as error:return[str(error)]

def compare_observations(reference:dict,actual:dict)->list[str]:
    try:
        require(actual['format']==FORMAT,'native kernel protocol differs')
        require(len(reference['cases'])==len(actual['cases']),'native kernel inventory incomplete')
        errors=[]
        for expected,observed in zip(reference['cases'],actual['cases'],strict=True):errors.extend(expected['id']+': '+e for e in compare_case(expected,observed))
        return errors
    except(KeyError,TypeError,ValueError)as error:return[str(error)]

def requests(cases:list[dict])->dict:
    values=[{key:case[key]for key in ('id','kind','input')}for case in cases]
    return dict(format=FORMAT,cases=values)

def run_capture(repo:Path,binary:Path,reference:dict,out:Path)->dict:
    sources=source_identity(repo)
    with NativeJsonCapture(binary,out,repo=repo,prefix='ken-retrieval-native-')as capture:actual=capture.run(requests(reference['cases']))
    (out/'SOURCES.json').write_text(__import__('json').dumps(sources,indent=2)+'\n')
    (out/'BUILD.json').write_text(__import__('json').dumps(dict(format='ken-retrieval-build/1',sources=sources,native_sha256=identity(binary)['sha256']),indent=2)+'\n')
    errors=compare_observations(reference,actual)
    if errors:raise ValueError(errors)
    return actual
