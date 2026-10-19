"""Check native preparation, exact paired inputs and bounded raw score parity."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import tempfile
import time

from .compare import _differences
from .context_compare import RUNTIME_REGISTRATION, core_for_platform, select_oracle
from .ettin_reference import TOLERANCES, capture, ettin_cases, source_state, stderr_errors
from .model_compare import _audit, _sha
from .reference import Reference

ROOT=Path(__file__).resolve().parents[2]
GOLDEN=ROOT/'docs/validation/rust-migration-2026-10-19/m2-ettin/reference.json'
RUNTIME={'engine':'rust','ken_models':'0.18.0','tokenizers':'0.22.2',
         'ort':'2.0.0-rc.14','device':'cpu','cpu_arena':True,'inter_threads':1}


def preparation_errors(expected:dict,actual:object)->list[str]:
    wanted={'fresh_cache':True,'reused_without_source':True,
        'source_artifacts':expected['source_artifacts'],'artifacts':expected['artifacts'],
        'recipe_key':hashlib.sha256(json.dumps(expected['definition'],sort_keys=True).encode()).hexdigest()}
    return _differences(wanted,actual,'preparation')


def _finite_number(value:object)->bool:
    if type(value) not in (int,float):return False
    try:return math.isfinite(value)
    except OverflowError:return False


def _positive_integer(value:object)->bool:
    return type(value) is int and value>0


def _score_errors(wanted:object,actual:object,call:dict,path:str)->list[str]:
    if not isinstance(wanted,dict) or not isinstance(actual,dict):return [path+': score object required']
    if 'error' in wanted:
        error=actual.get('error')
        if (set(actual)!={'error'} or not isinstance(error,dict) or set(error)!={'type','message'}
                or error['type']!='ModelError' or not isinstance(error['message'],str)
                or wanted['error']['message'] not in error['message']):
            return [path+': missing or unrelated native error']
        return []
    if set(actual)!={'scores','details'}:return [path+': scores and details required']
    scores=actual['scores'];expected_scores=wanted.get('scores')
    if (not isinstance(scores,list) or not isinstance(expected_scores,list)
            or len(scores)!=len(call['texts']) or len(scores)!=len(expected_scores)):
        return [path+': one raw score per document required']
    errors=[]
    for index,(a,b) in enumerate(zip(expected_scores,scores,strict=True)):
        if not _finite_number(a) or not _finite_number(b):
            errors.append(f'{path}.scores[{index}]: finite original and native values required')
        elif ((a==0 and b!=0) or abs(a-b)>TOLERANCES['atol']+TOLERANCES['rtol']*abs(a)):
            errors.append(f'{path}.scores[{index}]: raw logit differs')
    details=actual['details'];wanted_details=wanted['details']
    if not isinstance(details,dict) or set(details)!=set(wanted_details):
        return errors+[path+': missing or unexpected details fields']
    for field,want in wanted_details.items():
        got=details[field]
        if field in ('token_ms','inference_ms'):
            if not _finite_number(got) or got<0 or (not call['texts'] and got!=0):
                errors.append(f'{path}.details.{field}: invalid timing')
        else:errors.extend(_differences(want,got,f'{path}.details.{field}'))
    return errors


def compare_histories(expected:dict,rows:object,prepare_peak:int)->list[str]:
    cases=expected['cases'];wanted=expected['results']
    ids=[c['id'] for c in cases]
    if (not isinstance(rows,list) or [r.get('id') if isinstance(r,dict) else None for r in rows]!=ids
            or len(wanted)!=len(cases) or [r.get('id') for r in wanted]!=ids):
        return ['missing, duplicated, reordered or unexpected Ettin histories']
    errors=[];previous_peak=prepare_peak
    for case,want,row in zip(cases,wanted,rows,strict=True):
        path=case['id']
        for field in ['session_loaded','providers','cpu_arena','intra_threads','inter_threads']:
            errors.extend(_differences(want[field],row.get(field),f'{path}.{field}'))
        measures=['constructor_ns','calls_ns','peak_before_calls_bytes','peak_after_calls_bytes',
                  'reported_hwm_before_calls_bytes','reported_hwm_after_calls_bytes']
        if any(not _positive_integer(row.get(field)) for field in measures):
            errors.append(path+': invalid native phase measurement')
        else:
            before=max(previous_peak,row['reported_hwm_before_calls_bytes'])
            after=max(before,row['reported_hwm_after_calls_bytes'])
            if row['peak_before_calls_bytes']!=before or row['peak_after_calls_bytes']!=after:
                errors.append(path+': observed peak differs from retained raw reports')
            previous_peak=after
        calls=row.get('calls')
        if not isinstance(calls,list) or len(calls)!=len(case['calls']) or len(want['calls'])!=len(case['calls']):
            errors.append(path+': missing or extra calls');continue
        for index,(call,a,b) in enumerate(zip(case['calls'],want['calls'],calls,strict=True)):
            location=f'{path}.calls[{index}]'
            if call['op'] in ('tokens','pair_fits'):errors.extend(_differences(a,b,location))
            elif call['op']=='score':errors.extend(_score_errors(a,b,call,location))
            else:errors.append(location+': unknown operation')
    return errors


def compare_output(expected:dict,actual:object,core:dict)->list[str]:
    if not isinstance(actual,dict):return ['native Ettin output must be an object']
    if set(actual)!={'artifacts','preparation','prepare_ns','peak_after_prepare_bytes',
                     'reported_hwm_after_prepare_bytes','runtime','results'}:
        return ['missing or unexpected native Ettin output fields']
    errors=_differences(expected['artifacts'],actual.get('artifacts'),'artifacts')
    errors.extend(preparation_errors(expected,actual.get('preparation')))
    errors.extend(_differences(RUNTIME|{'native_core':core},actual.get('runtime'),'runtime'))
    for field in ['prepare_ns','peak_after_prepare_bytes','reported_hwm_after_prepare_bytes']:
        if not _positive_integer(actual.get(field)):errors.append('invalid '+field)
    peak=actual.get('peak_after_prepare_bytes')
    if peak!=actual.get('reported_hwm_after_prepare_bytes'):
        errors.append('initial observed peak differs from its raw report')
    return errors+compare_histories(expected,actual.get('results'),peak if _positive_integer(peak) else 0)


def compare_reference(expected:dict,actual:dict)->list[str]:
    errors=[]
    for key in ['format','platform','architecture','definition','source_artifacts','artifacts','cases','tolerances']:
        errors.extend(_differences(expected[key],actual.get(key),'original.'+key))
    oracle=actual.get('oracle',{})
    if oracle.get('frozen_import') is not True:errors.append('original import escaped frozen tree')
    errors.extend(_differences(expected['oracle']['runtime'],oracle.get('runtime'),'original.runtime'))
    rows=actual.get('results');ids=[c['id'] for c in expected['cases']]
    if not isinstance(rows,list) or [r.get('id') if isinstance(r,dict) else None for r in rows]!=ids:
        return errors+['incorrect original history coverage']
    for case,want,row in zip(expected['cases'],expected['results'],rows,strict=True):
        for field in ['session_loaded','providers','cpu_arena','intra_threads','inter_threads']:
            errors.extend(_differences(want[field],row.get(field),f"original.{case['id']}.{field}"))
        calls=row.get('calls')
        if not isinstance(calls,list) or len(calls)!=len(case['calls']):
            errors.append('incorrect original call coverage');continue
        for index,(call,a,b) in enumerate(zip(case['calls'],want['calls'],calls,strict=True)):
            path=f"original.{case['id']}.calls[{index}]"
            if call['op']=='score' and 'error' not in a:errors.extend(_score_errors(a,b,call,path))
            else:errors.extend(_differences(a,b,path))
    return errors


def compare(reference:Reference,native:Path,source:Path,library:Path,out:Path)->dict:
    out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    receipt={'format':'ken-ettin-parity/1','platform':platform.system(),'architecture':platform.machine(),
        'passed':False,'errors':[],'native_children':[],'outside_checkout':False,'M2_accepted':False}
    try:
        if not native.is_absolute() or not native.is_file() or not os.access(native,os.X_OK):
            raise ValueError('explicit executable Ettin probe required')
        with native.open('rb') as file:
            if file.read(4) not in (b'\x7fELF',b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe'):
                raise ValueError('native executable required; interpreter scripts rejected')
        document=json.loads(GOLDEN.read_text());golden=select_oracle(document,receipt['platform'],receipt['architecture'])
        if (_differences(ettin_cases(),document['cases']) or _differences(document['cases'],golden['cases'])
                or _differences(TOLERANCES,document['tolerances'])):
            raise ValueError('fixed Ettin histories/tolerances changed')
        definition=json.loads((reference.root/'src/ken/embedder/data/ettin-68m-fp32.json').read_text())
        if _differences(golden['definition'],definition) or source_state(source,definition['source'])!=golden['source_artifacts']:
            raise ValueError('registered Ettin source/definition changed')
        registration=json.loads(RUNTIME_REGISTRATION.read_text())
        core=core_for_platform(registration,receipt['platform'],receipt['architecture'])
        if not library.is_absolute() or not library.is_file() or library.stat().st_size!=core['bytes'] or _sha(library)!=core['sha256']:
            raise ValueError('native core byte identity mismatch')
        core_audit=out/'core-audit';core_audit.mkdir(exist_ok=True)
        receipt.update(native_sha256=_sha(native),oracle_sha256=_sha(GOLDEN),
            runtime_registration_sha256=_sha(RUNTIME_REGISTRATION),case_ids=[c['id'] for c in golden['cases']],
            dependency_audit=_audit(native,out),core_dependency_audit=_audit(library,core_audit))
        if not receipt['dependency_audit']['passed'] or not receipt['core_dependency_audit']['passed']:
            raise ValueError('executable or core dependency audit failed')
        with tempfile.TemporaryDirectory(prefix='ken-ettin-process-') as directory:
            root=Path(directory);copies=[]
            for name in ['original-source','native-source']:
                destination=root/name/definition['source']['revision'];destination.mkdir(parents=True)
                for path in definition['source']['artifacts']:
                    target=destination/path;target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(source/path,target)
                copies.append(destination)
            cache=root/'native-prepared'
            if os.path.lexists(cache):raise ValueError('fresh native destination required')
            copied=root/'ettin-probe';shutil.copy2(native,copied)
            core_copy=root/'native-core';shutil.copy2(library,core_copy)
            sentinels=root/'sentinel-path';sentinels.mkdir();child_log=root/'children.log'
            for name in ['python','python3','ken','sh','bash','zsh']:
                shim=sentinels/name
                shim.write_text(f"#!/bin/sh\nprintf '%s\\n' {shlex.quote(name)} >> {shlex.quote(str(child_log))}\nexit 97\n")
                shim.chmod(0o755)
            command=[str(copied)]
            if receipt['platform']=='Linux':
                tracer=shutil.which('strace')
                if not tracer:raise ValueError('Linux requires actual strace')
                command=[tracer,'-f','-e','trace=execve,execveat','-o',str(out/'native-exec.trace'),*command]
            request={'registration':definition,'source':str(copies[1]),'cache':str(cache),
                'runtime_registration':registration,'library':str(core_copy),'cases':golden['cases']}
            started=time.monotonic_ns()
            process=subprocess.run(command,cwd=root,env={'PATH':str(sentinels),'HOME':str(root),
                'TOKENIZERS_PARALLELISM':'false'},input=json.dumps(request,allow_nan=False),text=True,capture_output=True,timeout=600)
            receipt.update(native_exit=process.returncode,native_wall_ns=time.monotonic_ns()-started,
                outside_checkout=True,native_children=child_log.read_text().splitlines() if child_log.exists() else [])
            (out/'native.stdout.json').write_text(process.stdout);(out/'native.stderr.log').write_text(process.stderr)
            receipt['errors'].extend(stderr_errors(process.stderr,receipt['platform']))
            if process.returncode or receipt['native_children']:raise ValueError('native Ettin failed or executed children')
            actual=json.loads(process.stdout)
            receipt['errors'].extend(compare_output(golden,actual,core))
            if receipt['platform']=='Linux':
                lines=[line for line in (out/'native-exec.trace').read_text().splitlines() if re.search(r'\bexecve(?:at)?\(',line)]
                receipt['exec_attempts']=len(lines)
                if len(lines)!=1 or str(copied) not in lines[0]:receipt['errors'].append('only initial exec allowed')
            # Reject an invalid candidate before paying for a fresh full original
            # replay. Both the frozen pre-port oracle and a fresh original must
            # still match before this receipt can pass.
            if receipt['errors']:raise ValueError('native evidence differs from frozen original')
            receipt.update(preparation=actual['preparation'],runtime=actual['runtime'],core_identity=core,
                stderr=process.stderr,stderr_warning_count=int(bool(process.stderr)))
            expected=capture(reference,copies[0],out/'oracle.json',definition=definition,cases=golden['cases'])
            receipt['errors'].extend(compare_reference(golden,expected))
            receipt['errors'].extend(compare_output(expected,actual,core))
            receipt['reference_runtime']=expected['oracle']['runtime']
            for destination in [source,*copies]:
                if source_state(destination,definition['source'])!=golden['source_artifacts']:
                    receipt['errors'].append('source artifacts changed')
            for name,artifact in golden['artifacts'].items():
                path=cache/(definition['graph']['path'] if name=='model.onnx' else name)
                if not path.is_file() or path.stat().st_size!=artifact['bytes'] or _sha(path)!=artifact['sha256']:
                    receipt['errors'].append('native published cache differs')
            if _sha(core_copy)!=core['sha256'] or _sha(library)!=core['sha256']:receipt['errors'].append('native core changed')
            if _sha(copied)!=receipt['native_sha256'] or _sha(native)!=receipt['native_sha256']:receipt['errors'].append('native executable changed')
    except (OSError,ValueError,KeyError,TypeError,IndexError,OverflowError,subprocess.SubprocessError) as error:
        receipt['errors'].append(str(error))
    receipt['passed']=not receipt['errors']
    (out/'summary.json').write_text(json.dumps(receipt,indent=2,allow_nan=False)+'\n')
    return receipt


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['reference','native','source','library','out']:parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    result=compare(Reference.load(args.reference),args.native,args.source,args.library,args.out)
    print(json.dumps({'passed':result['passed'],'errors':result['errors']}))
    return int(not result['passed'])


if __name__=='__main__':raise SystemExit(main())
