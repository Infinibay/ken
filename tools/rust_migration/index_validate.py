"""Compare complete source histories, retaining explicit physical-vector audits."""
from __future__ import annotations
import copy,json,math,struct
from pathlib import Path
SLOT_COLUMNS={'ci_files':7,'ci_symbols':9,'ci_intent_sources':6}
BLOB_COLUMNS={'ci_files':6,'ci_symbols':8,'ci_intent_sources':5}
TABLES={'ci_files','ci_symbols','ci_imports','ci_intent_sources','ci_name_tokens','ci_passages','ci_passage_terms','ci_passage_lengths','ci_retrieval_files','ci_retrieval_embeddings','ci_passage_vectors','ci_vec_alloc','ci_vec_free','meta'}
# Already fixed before implementation by the M2 storage specification, 2026-10-19.
ABS=REL=1e-6
ERROR_KINDS={'IndexVersionError':'index_version','RuntimeError':'model','ValueError':'invalid','UnicodeEncodeError':'invalid','OperationalError':'sqlite','IntegrityError':'sqlite','FileNotFoundError':'io','PermissionError':'io'}
def require(condition,message):
    if not condition:raise ValueError(message)
from .native_json import same_value
def f32_blob(value):
    require(isinstance(value,dict)and set(value)=={'blob_hex'},'invalid vector blob shape')
    raw=bytes.fromhex(value['blob_hex']);require(len(raw)%4==0,'invalid F32 bytes')
    result=struct.unpack('<'+'f'*(len(raw)//4),raw);require(all(math.isfinite(n)for n in result),'nonfinite F32 bytes');return result
def close_vectors(left,right):
    require(isinstance(left,(list,tuple))and isinstance(right,(list,tuple))and len(left)==len(right),'vector dimensions differ')
    require(all(type(a)in(int,float)and type(b)in(int,float)and math.isfinite(a)and math.isfinite(b)and abs(a-b)<=ABS+REL*abs(a)for a,b in zip(left,right,strict=True)),'normalized vectors differ beyond the prior M2 bound')
def audit_legacy(snapshot,peaks):
    tables=snapshot['tables'];require(set(tables)==TABLES,'native SQL tables incomplete or unexpected')
    alloc={space:count for space,count in tables['ci_vec_alloc']};require(len(alloc)==len(tables['ci_vec_alloc'])and set(alloc)<=set(SLOT_COLUMNS),'unknown/duplicate allocation space')
    free={space:set()for space in SLOT_COLUMNS}
    for space,slot in tables['ci_vec_free']:
        require(space in free and type(slot)is int and 0<=slot<alloc.get(space,0),'invalid free slot')
        require(slot not in free[space],'duplicate free slot');free[space].add(slot)
    require(set(snapshot['legacy_vectors'])==set(SLOT_COLUMNS),'legacy observations incomplete')
    for table,column in SLOT_COLUMNS.items():
        rows=tables[table];observed=snapshot['legacy_vectors'][table];require(len(rows)==len(observed),'legacy owner observations incomplete');live=set()
        for row,actual in zip(rows,observed,strict=True):
            slot=row[column];require(actual['id']==row[0]and actual['slot']==slot,'observed vector owner/slot differs')
            if slot is not None:
                require(type(slot)is int and 0<=slot<alloc.get(table,0)and slot not in live and slot not in free[table],'invalid/duplicate/live-free slot ownership');live.add(slot)
            value=actual['value'];require(set(value)=={'vector'},'vector read failed or malformed')
            vector=value['vector'];blob=row[BLOB_COLUMNS[table]]
            if slot is None and blob is None:require(vector is None,'unexpected unowned vector')
            else:
                require(isinstance(vector,list)and len(vector)==3 and all(type(n)in(int,float)and math.isfinite(n)for n in vector),'invalid observed provided vector')
                if slot is None:
                    decoded=f32_blob(blob);require(len(decoded)==3 and struct.pack('<3f',*decoded)==struct.pack('<3f',*vector),'inline observation does not match actual blob')
        peaks[table]=max(peaks.get(table,0),len(live));high=alloc.get(table,0)
        require(type(high)is int and 0<=high<=2*peaks[table],'allocation growth exceeds bounded rollback-safe ownership')

def compare_case(original:dict,native:dict,definition:dict)->list[str]:
    try:
        require(original['id']==native['id']==definition['id'],'case identity differs')
        require(len(original['steps'])==len(native['steps'])==len(definition['operations']),'operation count differs')
        peaks_a={};peaks_b={};had_mapped=False
        for number,(expected,actual,operation)in enumerate(zip(original['steps'],native['steps'],definition['operations'],strict=True)):
            a=copy.deepcopy(expected);b=copy.deepcopy(actual)
            warnings=b.pop('warnings',[])
            if 'result'in b:warnings=b['result'].pop('warnings',warnings)
            require(isinstance(warnings,list)and all(isinstance(s,str)and s for s in warnings),'invalid warning diagnostics')
            fallback=a.get('result',{}).get('storage_fallback',False);require(bool(warnings)==fallback,'unexplained or missing storage fallback warning')
            if 'error'in a:
                require('error'in b,'original failure became success');left=a['error'];right=b['error'];require(ERROR_KINDS.get(left['type'])==right['kind'],'failure category differs')
                require(left['message']in right['message'],'failure reason differs');a['error']=b['error']=None
            else:require('result'in b and'error'not in b,'original success became failure')
            for value in(a,b):
                stats=value.get('result',{}).get('stats')
                if stats is not None:
                    elapsed=stats.pop('elapsed_s');require(type(elapsed)in(float,int)and math.isfinite(elapsed)and elapsed>=0,'invalid elapsed measurement')
            sa=a['snapshot'];sb=b['snapshot'];audit_legacy(sa,peaks_a);audit_legacy(sb,peaks_b)
            ta=sa['tables'];tb=sb['tables']
            # Every artifact attribute and link remains exact; only stored F32
            # normalization uses the previously approved arithmetic bound.
            require(len(ta['ci_retrieval_embeddings'])==len(tb['ci_retrieval_embeddings']),'embedding artifact count differs')
            for x,y in zip(ta['ci_retrieval_embeddings'],tb['ci_retrieval_embeddings'],strict=True):
                require(len(x)==len(y)==6,'embedding schema differs');close_vectors(f32_blob(x[5]),f32_blob(y[5]));x[5]=y[5]=None
            mapped=any(row[column]is not None for table,column in SLOT_COLUMNS.items()for row in ta[table])
            if mapped and not had_mapped:
                # Fresh unique-path histories must allocate their first slots
                # exactly; later commits may use M2's rollback-safe COW slots.
                require(ta['ci_vec_alloc']==tb['ci_vec_alloc']and ta['ci_vec_free']==tb['ci_vec_free'],'initial allocation metadata differs')
                for table,column in SLOT_COLUMNS.items():require([r[column]for r in ta[table]]==[r[column]for r in tb[table]],'initial slot ownership differs')
            for table,column in SLOT_COLUMNS.items():
                require(len(ta[table])==len(tb[table]),'canonical owner row count differs')
                for x,y in zip(ta[table],tb[table],strict=True):
                    require((x[column]is None)==(y[column]is None),'mapped/inline ownership changed');x[column]=y[column]=None
                va=sa['legacy_vectors'][table];vb=sb['legacy_vectors'][table]
                for x,y in zip(va,vb,strict=True):
                    xv=x['value']['vector'];yv=y['value']['vector']
                    if xv is not None:close_vectors(xv,yv)
                    else:require(yv is None,'unexpected vector')
                    x['slot']=y['slot']=None;x['value']=y['value']=None
            had_mapped|=mapped
            ta['ci_vec_alloc']=tb['ci_vec_alloc']=None;ta['ci_vec_free']=tb['ci_vec_free']=None
            require(same_value(a,b),f'complete operation {number} result/effects differ')
        return []
    except(KeyError,TypeError,ValueError,IndexError,struct.error)as error:return[str(error)]

def compare_scenarios(original:dict,native:dict)->list[str]:
    try:
        require(native['format']=='ken-index-probe/1','native history format differs')
        require(len(original['cases'])==len(native['cases'])==len(original['definitions']),'native histories missing')
        errors=[]
        for expected,actual,definition in zip(original['cases'],native['cases'],original['definitions'],strict=True):errors.extend(definition['id']+': '+error for error in compare_case(expected,actual,definition))
        return errors
    except(KeyError,TypeError,ValueError)as error:return[str(error)]

def source_identity(repo:Path)->dict:
    from .native_json import identity
    files=[repo/name for name in ('Cargo.toml','Cargo.lock','rust-toolchain.toml')]
    for crate in ('ken-index','ken-retrieval','ken-core','ken-syntax','ken-text','ken-program','ken-store','ken-models','ken-native-model-api','ken-search'):
        files.extend(p for p in sorted((repo/'crates'/crate).rglob('*'))if p.is_file())
    return {str(p.relative_to(repo)):identity(p)for p in files}

def requests(definitions:list[dict],legacy_runtime:dict,grammar_manifest:Path)->dict:
    for case in definitions:require(set(case)=={'id','operations'},'input-only case required')
    return dict(format='ken-index-probe/1',grammar_manifest=str(grammar_manifest),legacy_runtime=legacy_runtime,cases=definitions)
