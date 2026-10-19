"""Bind policy acceptance to the complete execution proof, excluding runtime caches."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from .model_validate import FINGERPRINT_KEYS, REQUIRED_GATES
from .context_reference import stderr_errors
from .policy_compare import GOLDEN, compare_output, compare_reference, dependency_errors, differences, select_oracle

MANIFEST='execution-artifacts.json'
FORMAT='ken-policy-execution/1'
CHAIN=(('policy','translation_base'),('translation','ettin_base'),
       ('ettin','context_base'),('context','table_base'),('table',None))


def _digest(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()


def _read(root:Path,name:str)->bytes:
    relative=PurePosixPath(name)
    if (not isinstance(name,str) or relative.is_absolute() or not relative.parts
            or relative.as_posix()!=name or any(p in ('.','..') for p in relative.parts)):
        raise ValueError('unsafe execution artifact path')
    path=root
    for part in relative.parts:
        path=path/part
        if path.is_symlink():raise ValueError('symlink execution artifact: '+name)
    if not path.is_file():raise ValueError('missing execution artifact: '+name)
    return path.read_bytes()


def seal_execution(root:Path)->dict:
    """Seal saved outputs before the final root receipt; never hash that receipt itself.

    The disposable environment contains downloaded models/parser libraries rather
    than execution proof. It is excluded and need not be published or uploaded.
    """
    files=[]
    for path in sorted(root.rglob('*')):
        relative=path.relative_to(root).as_posix()
        if 'environment' in path.relative_to(root).parts or relative in ('summary.json',MANIFEST):continue
        if path.is_file() or path.is_symlink():
            data=_read(root,relative)
            files.append({'path':relative,'bytes':len(data),'sha256':_digest(data)})
    data=(json.dumps({'format':FORMAT,'files':files},indent=2)+'\n').encode()
    (root/MANIFEST).write_bytes(data)
    return {'artifact':MANIFEST,'sha256':_digest(data)}


def execution_errors(root:Path,row:dict)->list[str]:
    """Authenticate once, then parse/recompare the same owned bytes."""
    try:
        descriptor=row.get('execution_artifacts',{})
        if (set(descriptor)!={'artifact','sha256'} or descriptor['artifact']!=MANIFEST):
            raise ValueError('bound execution artifact manifest required')
        raw=_read(root,MANIFEST)
        if _digest(raw)!=descriptor['sha256']:raise ValueError('execution manifest hash differs')
        manifest=json.loads(raw)
        if set(manifest)!={'format','files'} or manifest['format']!=FORMAT or not isinstance(manifest['files'],list):
            raise ValueError('invalid execution artifact manifest')
        files={}
        for record in manifest['files']:
            if not isinstance(record,dict) or set(record)!={'path','bytes','sha256'}:
                raise ValueError('invalid execution artifact entry')
            name=record['path']
            if name in files or name in ('summary.json',MANIFEST):raise ValueError('duplicate or recursive execution artifact')
            data=_read(root,name)
            if (type(record['bytes']) is not int or record['bytes']!=len(data)
                    or not isinstance(record['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',record['sha256'])
                    or _digest(data)!=record['sha256']):
                raise ValueError('execution artifact hash/size differs: '+name)
            files[name]=data
        return _proof_errors(files,row)
    except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError) as error:
        return ['execution evidence: '+str(error)]


def _proof_errors(files:dict[str,bytes],row:dict)->list[str]:
    def required(name):
        if name not in files:raise ValueError('unlisted required execution artifact: '+name)
        return files[name]
    def document(name):return json.loads(required(name))
    def equal(name,expected):
        if differences(expected,document(name),name):raise ValueError('raw/embedded proof differs: '+name)
    def parity(prefix,kind,expected,*,directory=None):
        folder=prefix+(directory or kind+'-parity')+'/'
        equal(folder+'summary.json',expected)
        for name in ['oracle.json','native.stdout.json','native.stderr.log','dependencies.log','cargo-tree.log']:
            required(folder+name)
        stderr=required(folder+'native.stderr.log').decode()
        if kind in ('ettin','context'):
            if stderr!=expected.get('stderr','') or stderr_errors(stderr,row['platform']):
                raise ValueError('native stderr differs from registered core diagnostics: '+folder)
        elif stderr:raise ValueError('native stderr is not empty: '+folder)
        if row['platform']=='Linux':
            trace=required(folder+'native-exec.trace').decode()
            if len(re.findall(r'\bexecve(?:at)?\(',trace))!=1:
                raise ValueError('one native execution required: '+folder)
        if kind in ('policy','translation'):
            required(folder+'native.request.json')
            if required(folder+'oracle.stderr.log')!=b'':raise ValueError('original stderr is not empty: '+folder)
        if kind in ('ettin','context'):
            for name in ['dependencies.log','cargo-tree.log']:required(folder+'core-audit/'+name)
    node=row;prefix=''
    for kind,child in CHAIN:
        if prefix:equal(prefix+'summary.json',node)
        parity(prefix,kind,node[kind+'_parity'])
        if child:node=node[child];prefix+='base/'
    # Table receipts copy the model gates but do not embed the original model
    # receipt. Authenticate that separate saved receipt and bind its shared facts.
    model_prefix=prefix+'base/';model=document(model_prefix+'summary.json')
    if (model.get('scope')!='model-local' or model.get('passed') is not True
            or model.get('execution_error') or model.get('M2_accepted') is not False
            or any(model.get(k)!=row.get(k) for k in ['platform','architecture','rustc'])
            or model.get('fingerprints')!={k:row['fingerprints'][k] for k in FINGERPRINT_KEYS}
            or any(model.get('gates',{}).get(k)!=node['gates'].get(k) for k in REQUIRED_GATES)):
        raise ValueError('raw model/table base proof differs')
    parity(model_prefix,'model',model['model_parity'])
    for gate in model['gates'].values():
        if 'artifact' in gate:
            data=required(model_prefix+gate['artifact'])
            if 'sha256' in gate and _digest(data)!=gate['sha256']:
                raise ValueError('command log/receipt hash differs: '+gate['artifact'])
    for name in ['python-final.xml','parity-tests.xml','m1-parity.json','benchmark/cases.json']:
        required(model_prefix+name)
    benchmark=document(model_prefix+'benchmark/benchmark.json')
    if benchmark.get('passed') is not True:raise ValueError('failed raw benchmark')
    parity(model_prefix+'benchmark/','processes',document(model_prefix+'benchmark/processes/summary.json'),directory='processes')
    actual=document('policy-parity/oracle.json')
    golden=select_oracle(json.loads(GOLDEN.read_bytes()),row['platform'],row['architecture'])
    errors=compare_reference(golden,actual,reference_fingerprint=row['policy_parity']['reference_fingerprint'])
    errors+=differences(row['policy_parity']['reference_oracle'],actual.get('oracle'),'raw original identity')
    errors+=compare_output(actual,document('policy-parity/native.stdout.json'))
    cases=json.loads(GOLDEN.with_name('cases.json').read_bytes())
    request={'cases':[{'id':c['id'],'input':c['input']} for c in cases['cases']],'prompts':cases['prompts']}
    errors+=differences(request,document('policy-parity/native.request.json'),'raw policy request')
    errors+=dependency_errors(required('policy-parity/dependencies.log').decode(),row['platform'])
    return errors
