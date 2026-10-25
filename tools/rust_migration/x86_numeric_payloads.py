"""Completeness and identity contracts for independently recorded observations."""
import math,re
from .native_json import same_value
from .context_compare import RUNTIME,core_for_platform
from .x86_numeric_alignment import SOURCE as ALIGN_SOURCE,SOURCE_SHA as ALIGN_SHA
from .x86_numeric_context import SOURCE as CONTEXT_SOURCE,SOURCE_SHA as CONTEXT_SHA
BLAS_SHA='05c9f9eb89ee68a4b9d673184fa91c99587e736392c0c2d49180a8aa5303d080'
COVERAGE={'mean','minimum','quartile','above50','above70','weighted'}
def require(ok,message):
    if not ok:raise ValueError(message)
def finite(value):return type(value)in(int,float)and math.isfinite(value)
def vector(value,count):return isinstance(value,list)and len(value)==count and all(finite(x)for x in value)
def coverage(value):
    require(isinstance(value,dict)and set(value)==COVERAGE and all(finite(x)for x in value.values()),'finite complete coverage required')
    require(0<=value['above50']<=1 and 0<=value['above70']<=1,'coverage threshold fractions invalid')
def alignment(python,native,case,mode):
    rows=case['input']['query']['rows'];columns=case['input']['documents']['rows']
    require(set(python)=={'source','source_sha256','numpy','blas','similarities','maxima','coverage'},'Python alignment fields differ')
    require(python['source']==ALIGN_SOURCE and python['source_sha256']==ALIGN_SHA and python['numpy']=='2.4.4','Python alignment identity differs')
    matrix=python['similarities'];require(isinstance(matrix,list)and len(matrix)==rows and all(vector(row,columns)for row in matrix),'Python alignment matrix shape differs')
    require(vector(python['maxima'],rows)and same_value(python['maxima'],[max(row)for row in matrix]),'Python maxima missing or inconsistent')
    coverage(python['coverage']);blas=python['blas']
    require(isinstance(blas,dict)and set(blas)=={'core','config','sha256'}and isinstance(blas['core'],str)and bool(blas['core'].strip())and isinstance(blas['config'],str)and blas['config'].startswith('OpenBLAS 0.3.31')and blas['sha256']==BLAS_SHA,'BLAS identity incomplete')
    if mode=='haswell':require(blas['core']=='Haswell','Haswell intervention selected another kernel')
    require(set(native)=={'format','platform','cases','metrics'}and native['format']=='ken-numeric-owner-probe/1'and native['platform']=='linux','native alignment identity differs')
    require(isinstance(native['cases'],list)and len(native['cases'])==1,'native alignment cases missing')
    row=native['cases'][0];require(set(row)=={'id','kind','family','result'}and all(same_value(row[k],case[k])for k in('id','kind','family')),'native alignment input identity differs')
    result=row['result'];require(set(result)=={'rows','columns','dtype','values','coverage'}and type(result['rows'])is int and type(result['columns'])is int and(result['rows'],result['columns'],result['dtype'])==(rows,columns,'float32')and vector(result['values'],rows*columns),'native alignment matrix shape/dtype differs')
    coverage(result['coverage'])

def context_native(value,request,frozen):
    core=core_for_platform(request['runtime_registration'],'Linux','x86_64')
    require(set(value)=={'artifacts','compatible_identity','dimension','prepare_ns','results','runtime'},'native context fields differ')
    require(same_value(value['runtime'],RUNTIME|dict(native_core=core)),'native context runtime differs')
    require(type(value['dimension'])is int and value['dimension']==frozen['dimension']==768,'native context dimension differs')
    require(same_value(value['artifacts'],frozen['artifacts'])and same_value(value['compatible_identity'],{k:frozen[k]for k in('spec','spec_key','tokenizer_revision')}),'native context model identity differs')
    require(type(value['prepare_ns'])is int and value['prepare_ns']>0,'native context preparation missing')
    require(isinstance(value['results'],list)and len(value['results'])==len(request['cases']),'native context cases missing')
    wanted={c['id']:r for c,r in zip(frozen['cases'],frozen['results'],strict=True)}
    for row,case in zip(value['results'],request['cases'],strict=True):
        require(set(row)=={'id','calls','providers','session_loaded','load_ns','inference_ns','peak_after_load_bytes','peak_after_inference_bytes'}and row['id']==case['id'],'native context history differs')
        require(row['providers']==['CPUExecutionProvider']and row['session_loaded']is True,'native CPU session differs')
        require(all(type(row[k])is int and row[k]>=0 for k in('load_ns','inference_ns','peak_after_load_bytes','peak_after_inference_bytes')),'native context measurements invalid')
        require(isinstance(row['calls'],list)and len(row['calls'])==2 and same_value(row['calls'][0],wanted[case['id']]['calls'][0]),'native context token inputs differ')
        values=row['calls'][1]
        if case['id']!='empty-query':
            require(isinstance(values,list)and len(values)==1,'native context passage shape differs');values=values[0]
        require(vector(values,768),'native context vector incomplete')

def context_python(value,name):
    mode='adapter'if name=='context-adapter'else name.split('-')[1];threads=1 if mode=='adapter'else int(name.split('-')[2])
    require(set(value)=={'mode','threads','source','source_sha256','ort','ort_build','cases'},'Python context fields differ')
    require(value['mode']==mode and type(value['threads'])is int and value['threads']==threads,'Python context mode/threads differ')
    require(value['source']==CONTEXT_SOURCE and value['source_sha256']==CONTEXT_SHA and value['ort']=='1.25.1'and isinstance(value['ort_build'],str)and bool(value['ort_build'].strip()),'Python context source/runtime identity differs')
