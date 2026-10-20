"""External mutation facts and actual responses must agree; fixtures certify no run."""
from copy import deepcopy
import pytest
from test_fastembed_compare import fixture,CORE
from tools.rust_migration.fastembed_ownership import ownership_errors


def ownership_fixture():
    definition,cases,original,frames,producer=fixture();name=definition['name']
    cold=frames[0];ready=frames[2]
    steps=[]
    for suffix,operation,loaded in [('cold','status',False),('bad','prepare',False),('failed','status',False),('repaired','prepare',True),('before','embed',True),('after','embed',True),('final','status',True)]:
        row=deepcopy(ready if loaded else cold);row['id']=name+':ownership-'+suffix;row['operation']=operation
        if suffix=='repaired':row['before']=deepcopy(cold['state'])
        elif loaded:row['before']=deepcopy(ready['state'])
        if operation!='embed':row['result']={'prepared':loaded}
        if suffix=='bad':row.pop('result');row['error']={'type':'ModelError','kind':'artifact','message':'model artifact missing or changed: tokenizer_config.json'}
        steps.append(row)
    facts={'failed_owned_roots':0,'prepared_owned_roots':1,'source_removed':True,'owned_artifacts':{name:{**pin,'mode':0o444,'regular':True,'nlink':1,'independent_inode':True}for name,pin in definition['assets']['artifacts'].items()}}
    process={'native_exit':0,'outside_checkout':True,'native_children':[],'exec_attempts':None,'owned_after_exit':[],'native_sha256':'1'*64,'core_sha256':CORE['sha256'],'registry_sha256':'2'*64,'native_process_wall_ns':1}
    return definition,cases[1],original['results'][1],steps,facts,process,producer


def test_valid_synthetic_ownership_facts_and_returned_rows():
    args=ownership_fixture()
    assert ownership_errors(*args,CORE,native_sha256='1'*64,registry_sha256='2'*64)==[]


@pytest.mark.parametrize('mutation',['before_vector','after_vector','ready_before_repair','failed_files','source_exists','hardlink','mode','wrong_hash','children','exit','stale_binary','extra_row'])
def test_false_ownership_claims_are_rejected(mutation):
    definition,case,wanted,frames,facts,process,producer=ownership_fixture()
    if mutation=='before_vector':frames[4]['result']['vectors_f32le_hex']='00000000'+frames[4]['result']['vectors_f32le_hex'][8:]
    elif mutation=='after_vector':frames[5]['result']['vectors_f32le_hex']='00000000'+frames[5]['result']['vectors_f32le_hex'][8:]
    elif mutation=='ready_before_repair':frames[1]['state']['model_loaded']=True
    elif mutation=='failed_files':facts['failed_owned_roots']=1
    elif mutation=='source_exists':facts['source_removed']=False
    elif mutation=='hardlink':next(iter(facts['owned_artifacts'].values()))['independent_inode']=False
    elif mutation=='mode':next(iter(facts['owned_artifacts'].values()))['mode']=0o644
    elif mutation=='wrong_hash':next(iter(facts['owned_artifacts'].values()))['sha256']='0'*64
    elif mutation=='children':process['native_children']=['python']
    elif mutation=='exit':process['native_exit']=1
    elif mutation=='stale_binary':process['native_sha256']='0'*64
    elif mutation=='extra_row':frames[5]['result']['shape'][0]+=1
    assert ownership_errors(definition,case,wanted,frames,facts,process,producer,CORE,native_sha256='1'*64,registry_sha256='2'*64)


def test_ownership_facts_keep_boolean_and_integer_wire_types():
    definition,case,wanted,frames,facts,process,producer=ownership_fixture()
    facts['source_removed']=1
    assert ownership_errors(definition,case,wanted,frames,facts,process,producer,CORE,native_sha256='1'*64,registry_sha256='2'*64)
