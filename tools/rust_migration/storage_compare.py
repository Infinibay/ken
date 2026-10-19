"""Typed storage parity against independently frozen original operations."""
from __future__ import annotations
import json
from pathlib import Path
import re
import os
import platform
import shlex
import shutil
import subprocess
import tempfile
import time
from .model_compare import _audit,_sha
from .policy_compare import differences
from .policy_compare import dependency_errors
from .storage_reference import logical_storage_differences,capture_storage,storage_cases
from .reference import Reference
from .validate import _digest

ROOT=Path(__file__).resolve().parents[2]
GOLDEN=ROOT/'docs/validation/rust-migration-2026-10-19/m2-storage/reference.json'
RUNTIME={'engine':'rust','ken_store':'0.18.0','sqlite':'3.53.2','format':1,
         'dtype':'float32','little_endian':True,'model_runtime_needed':False}
CORRECTIONS={
    **{'correction-manifest-'+name:{'rejected':True,'manifest_unchanged':True}
       for name in ['space','dtype','capacity','model']},
    **{'correction-'+name:{'rejected':True,'segments_unchanged':True}
       for name in ['norm-overflow','nan','inf']},
    'correction-sql-error':{'migration_rejected':True,'column_present':False,'schema_unchanged':True},
    'correction-compaction-interruption':{'interrupted':True,'complete_mapping':True,
                                        'original_references':True,'journal_absent':True},
}

def select_oracle(document:dict,system:str,architecture:str)->dict:
    if (system,architecture) not in [('Darwin','arm64'),('Linux','aarch64')]:
        raise ValueError('registered storage platform/architecture required')
    if (document.get('format')!='ken-storage-original-oracles/1'
            or document.get('native_storage_implemented') is not False
            or document.get('logical_outputs_equal') is not True
            or document.get('numeric_contract')!={'atol':1e-6,'rtol':1e-6,
                'rule':'abs(actual-reference) <= atol + rtol*abs(reference)','finite_valid_data':True}):
        raise ValueError('independent pre-native storage oracle and original numeric contract required')
    rows=document.get('oracles',[])
    if (len(rows)!=2 or sorted((r['platform'],r['architecture']) for r in rows)
            !=[('Darwin','arm64'),('Linux','aarch64')]):
        raise ValueError('one original storage oracle per registered platform required')
    if logical_storage_differences(rows[0]['results'],rows[1]['results']):
        raise ValueError('valid original storage histories disagree')
    return next(r for r in rows if (r['platform'],r['architecture'])==(system,architecture))

def _measurements(expected:dict,actual:object,path:str)->list[str]:
    if not isinstance(actual,dict) or set(expected)!=set(actual):return [path+': measurement fields differ']
    errors=[]
    for key,value in actual.items():
        if key=='segment_sha256':
            if (not isinstance(value,dict) or set(value)!=set(expected[key])
                    or any(not isinstance(v,str) or not re.fullmatch('[0-9a-f]{64}',v) for v in value.values())):
                errors.append(path+': invalid segment hash measurements')
        elif type(value) is not int or value<0:errors.append(path+': nonnegative byte count required')
    return errors

def compare_output(expected:dict,actual:object)->list[str]:
    if not isinstance(actual,dict) or set(actual)!={'format','runtime','results','metrics'}:
        return ['native storage root fields differ']
    errors=differences('ken-storage-native/1',actual['format'],'format')+differences(RUNTIME,actual['runtime'],'runtime')
    metrics=actual['metrics']
    if (not isinstance(metrics,dict) or set(metrics)!={'peak_rss_bytes','elapsed_ns'}
            or any(type(value) is not int or value<=0 for value in metrics.values())):
        errors.append('positive measured native RSS/time required')
    rows=actual['results']
    errors+=logical_storage_differences(expected['results'],rows)
    if not isinstance(rows,list) or len(rows)!=len(expected['results']):return errors
    for want,got in zip(expected['results'],rows,strict=True):
        if not isinstance(got,dict) or set(got)!=set(want):continue
        errors+=_measurements(want['measurements'],got['measurements'],want['id']+'.measurements')
        if want['classification']=='integrity-correction':
            errors+=differences(CORRECTIONS[want['id']],got['output'],want['id']+'.correction')
    return errors

def compare_reference(expected:dict,actual:object,*,reference_fingerprint:str|None=None)->list[str]:
    wanted=expected if reference_fingerprint is None else expected|{'reference_fingerprint':reference_fingerprint}
    if not isinstance(actual,dict) or set(actual)!=set(wanted):return ['original storage fields differ']
    errors=differences({k:v for k,v in wanted.items() if k!='results'},
                       {k:v for k,v in actual.items() if k!='results'},'original')
    errors+=logical_storage_differences(wanted['results'],actual['results'])
    if isinstance(actual['results'],list) and len(actual['results'])==len(wanted['results']):
        for want,got in zip(wanted['results'],actual['results'],strict=True):
            if not isinstance(got,dict) or set(got)!=set(want):continue
            errors+=_measurements(want['measurements'],got['measurements'],want['id']+'.measurements')
            if want['classification']=='integrity-correction':
                errors+=differences(want['output'],got['output'],want['id']+'.observed-original-defect')
    return errors


def compare_storage(reference:Reference,probe:Path,out:Path)->dict:
    out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    receipt={'format':'ken-storage-parity/1','platform':platform.system(),'architecture':platform.machine(),
             'passed':False,'errors':[],'native_children':[],'outside_checkout':False,'M2_accepted':False}
    try:
        if not probe.is_absolute() or not probe.is_file() or not os.access(probe,os.X_OK):
            raise ValueError('explicit executable native storage probe required')
        with probe.open('rb') as stream:
            if stream.read(4) not in (b'\x7fELF',b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe'):
                raise ValueError('native storage executable required; interpreter scripts rejected')
        golden=select_oracle(json.loads(GOLDEN.read_bytes()),receipt['platform'],receipt['architecture'])
        cases_path=GOLDEN.with_name('cases.json');cases=json.loads(cases_path.read_bytes())
        contract=json.loads(GOLDEN.read_bytes())['numeric_contract']|{'exact_fields':'all other primitive types/IDs/slots/SQLite BLOBs/shape/order'}
        if differences(storage_cases(),cases['cases']) or cases.get('numeric_contract')!=contract:
            raise ValueError('frozen storage inputs or numeric contract changed')
        audit=_audit(probe,out,package='ken-store')
        checks=dependency_errors((out/'dependencies.log').read_text(),receipt['platform'])
        audit.update(passed=audit['passed'] and not checks,errors=checks)
        receipt.update(native_sha256=_sha(probe),oracle_sha256=_sha(GOLDEN),cases_sha256=_sha(cases_path),
                       case_ids=[c['id'] for c in cases['cases']],dependency_audit=audit,
                       compatibility_count=sum(c['classification']=='compatibility' for c in cases['cases']),
                       correction_count=sum(c['classification']=='integrity-correction' for c in cases['cases']))
        if not audit['passed']:raise ValueError('native storage dependency audit failed')
        original_started=time.monotonic_ns();fresh=capture_storage(reference,out/'oracle.json')
        receipt['original_wall_ns']=time.monotonic_ns()-original_started
        receipt['errors'].extend(compare_reference(golden,fresh,reference_fingerprint=reference.fingerprint))
        source=[r for r in json.loads(reference.manifest_path.read_bytes())['files'] if r['path'].startswith('src/ken/')]
        receipt.update(reference_oracle=fresh['oracle'],reference_fingerprint=fresh['reference_fingerprint'],reference_source_fingerprint=_digest(source))
        if receipt['errors']:raise ValueError('fresh storage original differs from frozen oracle')
        with tempfile.TemporaryDirectory(prefix='ken-storage-native-process-') as directory:
            root=Path(directory);copied=root/'storage-probe';shutil.copy2(probe,copied)
            sentinels=root/'sentinel-path';sentinels.mkdir();children=root/'children.log'
            for name in ['python','python3','ken','sh','bash','zsh']:
                shim=sentinels/name;shim.write_text(f"#!/bin/sh\nprintf '%s\\n' {shlex.quote(name)} >> {shlex.quote(str(children))}\nexit 97\n");shim.chmod(0o755)
            request={'cases':[{'id':c['id'],'input':c['input']} for c in cases['cases']]}
            (out/'native.request.json').write_text(json.dumps(request,indent=2)+'\n')
            command=[str(copied)]
            if receipt['platform']=='Linux':
                tracer=shutil.which('strace')
                if not tracer:raise ValueError('Linux storage proof requires actual strace')
                command=[tracer,'-f','-e','trace=execve,execveat','-o',str(out/'native-exec.trace'),*command]
            started=time.monotonic_ns()
            child=subprocess.run(command,input=json.dumps(request,allow_nan=False),text=True,capture_output=True,cwd=root,env={'PATH':str(sentinels),'HOME':str(root)},timeout=30)
            receipt.update(native_exit=child.returncode,native_wall_ns=time.monotonic_ns()-started,outside_checkout=True,
                           native_children=children.read_text().splitlines() if children.exists() else [],stderr=child.stderr)
            (out/'native.stdout.json').write_text(child.stdout);(out/'native.stderr.log').write_text(child.stderr)
            if child.returncode or child.stderr or receipt['native_children']:
                raise ValueError('native storage failed, wrote stderr or executed children')
            actual=json.loads(child.stdout);receipt['errors'].extend(compare_output(fresh,actual))
            receipt.update(runtime=actual.get('runtime'),metrics=actual.get('metrics'))
            if receipt['platform']=='Linux':
                lines=[line for line in (out/'native-exec.trace').read_text().splitlines() if re.search(r'\bexecve(?:at)?\(',line)]
                receipt['exec_attempts']=len(lines)
                if len(lines)!=1 or str(copied) not in lines[0]:receipt['errors'].append('only initial storage exec allowed')
            if _sha(copied)!=receipt['native_sha256'] or _sha(probe)!=receipt['native_sha256']:receipt['errors'].append('native storage executable changed')
            if _sha(GOLDEN)!=receipt['oracle_sha256'] or _sha(cases_path)!=receipt['cases_sha256']:receipt['errors'].append('storage oracle/inputs changed during comparison')
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError,OverflowError,subprocess.SubprocessError) as error:
        receipt['errors'].append(str(error))
    receipt['passed']=not receipt['errors']
    (out/'summary.json').write_text(json.dumps(receipt,indent=2,allow_nan=False)+'\n')
    return receipt
