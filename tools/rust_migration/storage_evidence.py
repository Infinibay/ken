"""Authenticate the complete storage/policy execution tree once, then parse owned bytes."""
from __future__ import annotations
import json
from pathlib import Path
import re
from . import policy_evidence as policy
from .policy_compare import differences,dependency_errors
from .storage_compare import GOLDEN,select_oracle,compare_reference,compare_output

FORMAT='ken-storage-execution/1'
def seal_execution(root:Path)->dict:return policy.seal_execution(root,format=FORMAT)

def execution_errors(root:Path,row:dict)->list[str]:
    try:
        files=policy.authenticate_manifest(row.get('execution_artifacts',{}),lambda name:policy._read(root,name),format=FORMAT)
        return _proof_errors(files,row)
    except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError) as error:
        return ['storage execution evidence: '+str(error)]

def _proof_errors(files:dict[str,bytes],row:dict)->list[str]:
    def required(name):
        if name not in files:raise ValueError('unlisted required storage execution artifact: '+name)
        return files[name]
    def document(name):return json.loads(required(name))
    def equal(name,value):
        if differences(value,document(name),name):raise ValueError('raw/embedded storage proof differs: '+name)
    from .storage_validate import storage_receipt_errors
    errors=storage_receipt_errors(row,row['case_ids'],row['fingerprints'])
    equal('base/summary.json',row['policy_base'])
    # Nested manifests use the same authenticated owned buffers, never another disk read.
    base=policy.authenticate_manifest(row['policy_base'].get('execution_artifacts',{}),lambda name:required('base/'+name))
    errors+=policy._proof_errors(base,row['policy_base'])
    parity=row['storage_parity'];equal('storage-parity/summary.json',parity)
    original=document('storage-parity/oracle.json')
    golden=select_oracle(json.loads(GOLDEN.read_bytes()),row['platform'],row['architecture'])
    errors+=compare_reference(golden,original,reference_fingerprint=parity['reference_fingerprint'])
    errors+=differences(parity['reference_oracle'],original.get('oracle'),'raw storage provenance')
    output=document('storage-parity/native.stdout.json');errors+=compare_output(original,output)
    errors+=differences(parity['metrics'],output.get('metrics'),'raw storage metrics')
    cases=json.loads(GOLDEN.with_name('cases.json').read_bytes())['cases']
    errors+=differences({'cases':[{'id':c['id'],'input':c['input']} for c in cases]},document('storage-parity/native.request.json'),'raw storage request')
    for name in ['native.stderr.log','oracle.stderr.log']:
        if required('storage-parity/'+name)!=b'':errors.append('unexpected raw storage stderr')
    for prefix in ['storage-parity/','storage-recovery/']:
        errors+=dependency_errors(required(prefix+'dependencies.log').decode(),row['platform'])
        if not required(prefix+'cargo-tree.log').startswith(b'ken-store '):errors.append('storage dependency tree must identify ken-store')
    if row['platform']=='Linux' and len(re.findall(r'\bexecve(?:at)?\(',required('storage-parity/native-exec.trace').decode()))!=1:errors.append('one native storage exec required')
    recovery=row['storage_recovery'];equal('storage-recovery/summary.json',recovery)
    for case in recovery['cases']:
        prefix='storage-recovery/'+case['id']+'/'
        for state in ['before','after','final','repeat']:
            equal(prefix+'original.'+state+'.json',{'oracle':recovery['reference_oracle'],'data':case[state]})
            if required(prefix+'original.'+state+'.stderr.log')!=b'':errors.append('unexpected original recovery stderr')
        for execution in case['executions']:
            name=prefix+execution['role'];equal(name+'.execution.json',execution)
            if required(name+'.stdout.log').decode()!=execution['stdout'] or required(name+'.stderr.log').decode()!=execution['stderr']:errors.append('raw recovery command output differs')
            if row['platform']=='Linux' and len(re.findall(r'\bexecve(?:at)?\(',required(name+'.trace').decode()))!=1:errors.append('one native recovery role exec required')
    return errors
