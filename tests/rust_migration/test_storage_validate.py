"""Synthetic receipt fixtures test validation only; they cannot certify a real run."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from test_policy_validate import _policy_row,_execution_fixture as policy_fixture
from test_storage_compare import native
from tools.rust_migration.storage_compare import GOLDEN,RUNTIME,select_oracle
from tools.rust_migration.storage_validate import STORAGE_GATES,STORAGE_KEYS,storage_receipt_errors,aggregate_storage
from tools.rust_migration.storage_evidence import execution_errors,seal_execution
from tools.rust_migration.policy_evidence import seal_execution as seal_policy
from tools.rust_migration.policy_reference import policy_cases

RECOVERY=GOLDEN.with_name('recovery-cases.json')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def event_prefix(case):
    if case['operation']=='inline':return [{'phase':'migrated','space':'ci_files','count':1}]
    events=[{'phase':'compacted','space':space,'before':5,'after':2} for space in ['ci_files','ci_symbols','ci_intent_sources']]
    for phase in ['staging_ready','journal_published','backup_renamed','new_published','database_committed']:
        events.append({'phase':phase})
        if phase==case['barrier']:return events
    raise AssertionError(case)

def recovery_row(base,driver):
    document=json.loads(RECOVERY.read_bytes());cases=[]
    for case in document['cases']:
        executions=[]
        for role in case['roles']:
            events=(event_prefix(case) if role=='interrupted' else
                    [{'phase':'migrated','space':'ci_files','count':1},{'recovered':True}] if role=='resume' else [{'recovered':True}])
            executions.append({'role':role,'exit':-9 if role=='interrupted' else 0,'stderr':'',
                               'stdout':''.join(json.dumps(e)+'\n' for e in events),
                               'exec_attempts':1 if base['platform']=='Linux' else None})
        cases.append({'id':case['id'],'executions':executions,'before':deepcopy(document['states'][case['before']]),
                      'after':deepcopy(document['states'][case['after']]),'final':deepcopy(document['states'][case['final']]),
                      'repeat':deepcopy(document['states'][case['final']])})
    return {'format':'ken-storage-recovery/1','platform':base['platform'],'architecture':base['architecture'],
            'passed':True,'errors':[],'M2_accepted':False,'driver_sha256':driver,'cases_sha256':sha(RECOVERY),
            'outside_checkout':True,'native_children':[],'dependency_audit':{'passed':True,'errors':[]},
            'reference_oracle':deepcopy(base['reference_oracle']),'reference_fingerprint':base['reference_fingerprint'],
            'reference_source_fingerprint':base['reference_source_fingerprint'],'cases':cases}

def storage_row(folder):
    policy=_policy_row(folder);system=policy['platform'];arch=policy['architecture']
    expected=select_oracle(json.loads(GOLDEN.read_bytes()),system,arch)
    fingerprints=policy['fingerprints']|{'storage_cases':sha(GOLDEN.with_name('cases.json')),
                                       'storage_oracle':sha(GOLDEN),'storage_recovery_cases':sha(RECOVERY)}
    binding={'ran':True,'passed':True,'built_sha256':'d'*64,'supplied_sha256':'d'*64}
    parity={'format':'ken-storage-parity/1','platform':system,'architecture':arch,'passed':True,'errors':[],
            'M2_accepted':False,'native_exit':0,'native_wall_ns':1,'original_wall_ns':1,'outside_checkout':True,
            'native_children':[],'stderr':'','native_sha256':'d'*64,'dependency_audit':{'passed':True,'errors':[]},
            'oracle_sha256':fingerprints['storage_oracle'],'cases_sha256':fingerprints['storage_cases'],
            'case_ids':[c['id'] for c in expected['results']],'compatibility_count':23,'correction_count':9,
            'runtime':deepcopy(RUNTIME),'metrics':{'peak_rss_bytes':1,'elapsed_ns':1},
            'reference_oracle':deepcopy(expected['oracle']),'reference_fingerprint':expected['reference_fingerprint'],
            'reference_source_fingerprint':fingerprints['reference_source']}
    if system=='Linux':parity['exec_attempts']=1
    recovery=recovery_row(parity,'e'*64)
    release=binding|{'recovery_driver':binding|{'built_sha256':'e'*64,'supplied_sha256':'e'*64}}
    return {'scope':'storage-local','synthetic_fixture':True,'platform':system,'architecture':arch,'passed':True,
            'M2_accepted':False,'rustc':policy['rustc'],'fingerprints':fingerprints,'policy_base':policy,
            'case_ids':parity['case_ids'],'storage_release':release,'storage_parity':parity,'storage_recovery':recovery,
            'gates':deepcopy(policy['gates'])|{'storage_release':release,'storage_parity':{'ran':True,'passed':True},
                                             'storage_recovery':{'ran':True,'passed':True}}}

def test_storage_receipt_contract_requires31_gates29_inputs_and_complete_recursive_proof():
    row=storage_row('linux');current=deepcopy(row['fingerprints']);ids=row['case_ids']
    assert len(STORAGE_GATES)==31 and len(STORAGE_KEYS)==29
    assert storage_receipt_errors(row,ids,current)==[]
    for gate in STORAGE_GATES:
        bad=deepcopy(row);bad['gates'][gate]['passed']=False;assert storage_receipt_errors(bad,ids,current),gate
    for key in STORAGE_KEYS:
        bad=deepcopy(row);bad['fingerprints'][key]='0'*64;assert storage_receipt_errors(bad,ids,current),key
    for path,value in [(['M2_accepted'],True),(['platform'],'Darwin'),(['architecture'],'x86_64'),
                       (['storage_parity','native_exit'],False),(['storage_parity','metrics','peak_rss_bytes'],0),
                       (['storage_parity','native_children'],['python']),(['storage_parity','runtime','sqlite'],'wrong'),
                       (['storage_release','recovery_driver','supplied_sha256'],'0'*64),
                       (['storage_recovery','outside_checkout'],False),(['storage_recovery','cases'],[]),
                       (['storage_recovery','cases',0,'executions',0,'exit'],0),
                       (['storage_recovery','cases',0,'executions',0,'exec_attempts'],True),
                       (['storage_recovery','cases',0,'after','spaces','ci_files',0,'vec_slot'],1),
                       (['storage_recovery','cases',3,'after','spaces','ci_files',0,'vector'],[0.0,0.0]),
                       (['policy_base','policy_parity','runtime','engine'],'python')]:
        bad=deepcopy(row);target=bad
        for key in path[:-1]:target=target[key]
        target[path[-1]]=value;assert storage_receipt_errors(bad,ids,current),path

def execution_fixture(root,row):
    policy_fixture(root/'base',row['policy_base'])
    row['gates'].update(deepcopy(row['policy_base']['gates']))
    def write(name,value):
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value if isinstance(value,bytes) else json.dumps(value).encode())
    original=select_oracle(json.loads(GOLDEN.read_bytes()),row['platform'],row['architecture'])
    write('storage-parity/oracle.json',original);write('storage-parity/native.stdout.json',native(original))
    write('storage-parity/native.request.json',{'cases':[{'id':c['id'],'input':c['input']} for c in json.loads(GOLDEN.with_name('cases.json').read_bytes())['cases']]})
    write('storage-parity/summary.json',row['storage_parity']);write('storage-parity/native.stderr.log',b'');write('storage-parity/oracle.stderr.log',b'')
    linked=(b'probe:\n\t/usr/lib/libSystem.B.dylib (compatibility version 1)\n' if row['platform']=='Darwin' else b'linux-vdso.so.1 (0x1)\nlibc.so.6 => /lib/aarch64-linux-gnu/libc.so.6 (0x1)\n/lib/ld-linux-aarch64.so.1 (0x1)\n')
    for prefix in ['storage-parity','storage-recovery']:
        write(prefix+'/dependencies.log',linked);write(prefix+'/cargo-tree.log',b'ken-store v0.18.0\n')
    if row['platform']=='Linux':write('storage-parity/native-exec.trace',b'1 execve("/tmp/storage", [], 0x0) = 0\n')
    write('storage-recovery/summary.json',row['storage_recovery'])
    for case in row['storage_recovery']['cases']:
        for state in ['before','after','final','repeat']:
            write(f'storage-recovery/{case["id"]}/original.{state}.json',{'oracle':row['storage_recovery']['reference_oracle'],'data':case[state]})
            write(f'storage-recovery/{case["id"]}/original.{state}.stderr.log',b'')
        for execution in case['executions']:
            prefix=f'storage-recovery/{case["id"]}/{execution["role"]}'
            write(prefix+'.execution.json',execution);write(prefix+'.stdout.log',execution['stdout'].encode());write(prefix+'.stderr.log',b'')
            if row['platform']=='Linux':write(prefix+'.trace',b'1 execve("/tmp/storage-recovery", [], 0x0) = 0\n')
    row['execution_artifacts']=seal_execution(root);write('summary.json',row)

@pytest.mark.parametrize('damage',['missing-output','changed-output','resealed-output','unlisted-trace',
    'missing-recovery','resealed-recovery','changed-nested','resealed-policy','missing-log','unsafe-path','symlink'])
def test_storage_evidence_authenticates_all_bytes_and_rechecks_semantics_after_resealing(tmp_path,damage):
    row=storage_row('linux');execution_fixture(tmp_path,row);assert execution_errors(tmp_path,row)==[]
    output=tmp_path/'storage-parity/native.stdout.json'
    if damage=='missing-output':output.unlink()
    elif damage in ('changed-output','resealed-output'):
        content=json.loads(output.read_bytes());content['results'][2]['output']['values'][0]='wrong';output.write_text(json.dumps(content))
        if damage=='resealed-output':row['execution_artifacts']=seal_execution(tmp_path)
    elif damage=='unlisted-trace':
        manifest=tmp_path/'execution-artifacts.json';data=json.loads(manifest.read_bytes());data['files']=[r for r in data['files'] if r['path']!='storage-recovery/compact-journal_published/recover.trace'];manifest.write_text(json.dumps(data));row['execution_artifacts']['sha256']=sha(manifest)
    elif damage=='missing-recovery':(tmp_path/'storage-recovery/compact-new_published/original.after.json').unlink()
    elif damage=='resealed-recovery':
        path=tmp_path/'storage-recovery/compact-database_committed/original.after.json';content=json.loads(path.read_bytes());content['data']['spaces']['ci_files'][0]['vector']=[0.0,0.0];path.write_text(json.dumps(content));row['execution_artifacts']=seal_execution(tmp_path)
    elif damage=='changed-nested':(tmp_path/'base/summary.json').write_text('{}')
    elif damage=='resealed-policy':
        path=tmp_path/'base/policy-parity/native.stdout.json';content=json.loads(path.read_bytes());content['results'][0]['recommended']='wrong';path.write_text(json.dumps(content));base=row['policy_base'];base['execution_artifacts']=seal_policy(tmp_path/'base');(tmp_path/'base/summary.json').write_text(json.dumps(base));row['execution_artifacts']=seal_execution(tmp_path)
    elif damage=='missing-log':(tmp_path/'base/base/base/base/base/base/python-full.log').unlink()
    elif damage=='unsafe-path':
        manifest=tmp_path/'execution-artifacts.json';data=json.loads(manifest.read_bytes());data['files'][0]['path']='../foreign';manifest.write_text(json.dumps(data));row['execution_artifacts']['sha256']=sha(manifest)
    else:
        foreign=tmp_path/'foreign';output.rename(foreign);output.symlink_to(foreign)
    assert execution_errors(tmp_path,row),damage

def test_storage_acceptance_rejects_synthetic_fixtures_and_authenticates_each_file_once(tmp_path,monkeypatch):
    from tools.rust_migration import policy_evidence as pe
    row=storage_row('macos');execution_fixture(tmp_path,row)
    reads={};original_read=pe._read
    def counted(root,name):
        reads[name]=reads.get(name,0)+1;assert reads[name]==1,name
        return original_read(root,name)
    monkeypatch.setattr(pe,'_read',counted)
    assert execution_errors(tmp_path,row)==[]
    assert aggregate_storage(tmp_path,expected_fingerprints=row['fingerprints'])['Storage_accepted'] is False

def test_missing_prepared_storage_probe_fails_before_prior_suites(tmp_path,monkeypatch):
    from tools.rust_migration import storage_validate as sv
    from tools.rust_migration.preparation import PreparedNativeContext,PreparedNativeEttin,PreparedNativeTranslation,PreparedNativeStorage
    from tools.rust_migration.reference import Reference
    import sys
    def forbidden(*args,**kwargs):raise AssertionError('missing storage input must fail before expensive prior suites')
    monkeypatch.setattr(sv,'validate_policy',forbidden)
    reference=Reference(tmp_path,tmp_path/'manifest','reference',Path(sys.executable))
    context=PreparedNativeContext(tmp_path/'context',tmp_path/'library',tmp_path/'context-probe')
    ettin=PreparedNativeEttin(tmp_path/'ettin',tmp_path/'ettin-probe');translation=PreparedNativeTranslation(tmp_path/'translation',tmp_path/'translation-probe')
    code=sv.validate_storage(tmp_path,reference,tmp_path/'model',tmp_path/'potion',tmp_path/'table',tmp_path/'table.npz',
        context,ettin,translation,tmp_path/'policy',PreparedNativeStorage(tmp_path/'missing'),tmp_path/'out',tmp_path/'baseline',tmp_path/'manifest')
    assert code==1
    row=json.loads((tmp_path/'out/summary.json').read_bytes())
    assert row['passed'] is False and row['M2_accepted'] is False and row['synthetic_fixture'] is False
    assert 'storage' in row['execution_error']
