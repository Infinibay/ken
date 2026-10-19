"""Check exact contextual inputs/identities before bounded raw-vector parity."""
from __future__ import annotations

import argparse
import json
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
from .context_reference import TOLERANCES, capture, context_cases, snapshot_state, stderr_errors
from .model_compare import _audit, _sha, _vector
from .reference import Reference

ROOT=Path(__file__).resolve().parents[2]
GOLDEN=ROOT/'docs/validation/rust-migration-2026-10-18/m2-context/reference.json'
RUNTIME_REGISTRATION=GOLDEN.with_name('runtime-libraries.json')

RUNTIME={'engine':'rust','ken_models':'0.18.0','tokenizers':'0.22.2',
         'ort':'2.0.0-rc.14','device':'cpu','intra_threads':2,'inter_threads':1}


def select_oracle(document:dict,system:str,architecture:str)->dict:
    result=document.get('platforms',{}).get(f'{system}/{architecture}')
    if (not isinstance(result,dict) or result.get('platform')!=system
            or result.get('architecture')!=architecture):
        raise ValueError('no matching original platform/architecture oracle')
    return result


def compare_output(expected:dict,actual:object,core:dict)->list[str]:
    if not isinstance(actual,dict):return ['native contextual output must be an object']
    errors=[]
    for key in ['dimension','artifacts']:
        errors.extend(_differences(expected[key],actual.get(key),key))
    identity={k:expected[k] for k in ['spec','spec_key','tokenizer_revision']}
    errors.extend(_differences(identity,actual.get('compatible_identity'),'compatible_identity'))
    runtime=actual.get('runtime')
    if not isinstance(runtime,dict) or any(runtime.get(k)!=v for k,v in RUNTIME.items()):
        errors.append('incorrect actual native runtime')
    if not isinstance(runtime,dict) or runtime.get('native_core')!=core:
        errors.append('native core identity mismatch')
    if type(actual.get('prepare_ns')) is not int or actual['prepare_ns']<=0:
        errors.append('missing model-byte preparation measurement')
    return errors+compare_histories(expected,actual.get('results'))


def checked_vector(want,got,dimension,path):
    errors=_vector(want,want,dimension,TOLERANCES,path+'.original')
    return errors or _vector(want,got,dimension,TOLERANCES,path)


def compare_histories(expected:dict,rows:object)->list[str]:
    errors=[]
    if not isinstance(rows,list) or [r.get('id') if isinstance(r,dict) else None for r in rows]!=[c['id'] for c in expected['cases']]:
        return errors+['missing/duplicated/reordered/unexpected context histories']
    for case,wanted,result in zip(expected['cases'],expected['results'],rows,strict=True):
        for key in ['session_loaded','providers']:
            errors.extend(_differences(wanted[key],result.get(key),f"{case['id']}.{key}"))
        fields=['load_ns','inference_ns','peak_after_load_bytes','peak_after_inference_bytes']
        if any(type(result.get(k)) is not int or result[k]<=0 for k in fields):
            errors.append('invalid contextual phase measurement')
        elif result['peak_after_inference_bytes']<result['peak_after_load_bytes']:
            errors.append('decreasing process peak')
        values=result.get('calls')
        if not isinstance(values,list) or len(values)!=len(case['calls']):
            errors.append('missing or extra contextual calls');continue
        if len(wanted['calls'])!=len(case['calls']):raise ValueError('original call coverage mismatch')
        for index,(call,want,got) in enumerate(zip(case['calls'],wanted['calls'],values,strict=True)):
            path=f"{case['id']}.calls[{index}]"
            if call['op']=='tokens':
                if (not isinstance(got,dict) or set(got)!={'ids','attention_mask'}
                    or any(not isinstance(got.get(k),list) or any(type(v) is not int for v in got[k])
                           for k in ['ids','attention_mask']) or got!=want):
                    errors.append(f'{path}: exact IDs/mask differ')
            elif call['op']=='query':errors.extend(checked_vector(want,got,expected['dimension'],path))
            elif call['op']=='passages':
                if not isinstance(got,list) or len(got)!=len(want):errors.append(f'{path}: row count mismatch');continue
                for row,(a,b) in enumerate(zip(want,got,strict=True)):
                    errors.extend(checked_vector(a,b,expected['dimension'],f'{path}[{row}]'))
            else:errors.append('unknown context operation')
    return errors


def core_for_platform(registration:dict,system:str,architecture:str)->dict:
    target={('Darwin','arm64'):('macos','aarch64'),('Linux','aarch64'):('linux','aarch64')}.get((system,architecture))
    if registration.get('format')!='ken-native-onnx/1' or target is None:
        raise ValueError('unregistered native runtime platform')
    rows=[r for r in registration.get('libraries',[]) if (r.get('os'),r.get('arch'))==target]
    if len(rows)!=1:raise ValueError('ambiguous or missing native runtime platform')
    return rows[0]


def compare(reference:Reference,native:Path,snapshot:Path,library:Path,out:Path)->dict:
    out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    receipt={'format':'ken-context-parity/1','platform':platform.system(),'architecture':platform.machine(),
        'passed':False,'errors':[],'native_children':[],'outside_checkout':False,'M2_accepted':False}
    try:
        if not native.is_absolute() or not native.is_file() or not os.access(native,os.X_OK):
            raise ValueError('explicit executable context probe required')
        with native.open('rb') as file:
            if file.read(4) not in (b'\x7fELF',b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe'):
                raise ValueError('native executable required; interpreter scripts rejected')
        document=json.loads(GOLDEN.read_text())
        golden=select_oracle(document,receipt['platform'],receipt['architecture'])
        if document['cases']!=context_cases() or golden['cases']!=document['cases'] or document['tolerances']!=TOLERANCES:
            raise ValueError('fixed contextual cases/tolerances changed')
        registration=json.loads(RUNTIME_REGISTRATION.read_text())
        core=core_for_platform(registration,receipt['platform'],receipt['architecture'])
        definition=json.loads((reference.root/'src/ken/embedder/data/code-context-int8.json').read_text())
        if definition!=golden['definition'] or snapshot_state(snapshot,definition)!=golden['artifacts']:
            raise ValueError('registered contextual artifacts/definition changed')
        if not library.is_absolute() or not library.is_file() or library.stat().st_size!=core['bytes'] or _sha(library)!=core['sha256']:
            raise ValueError('native runtime byte identity mismatch')
        core_audit=out/'core-audit';core_audit.mkdir(exist_ok=True)
        receipt.update(native_sha256=_sha(native),case_ids=[c['id'] for c in golden['cases']],
            artifacts=golden['artifacts'],oracle_sha256=_sha(GOLDEN),runtime_registration_sha256=_sha(RUNTIME_REGISTRATION),
            dependency_audit=_audit(native,out),core_dependency_audit=_audit(library,core_audit))
        if not receipt['dependency_audit']['passed'] or not receipt['core_dependency_audit']['passed']:
            raise ValueError('executable or core dependency audit failed')
        with tempfile.TemporaryDirectory(prefix='ken-context-process-') as directory:
            root=Path(directory); copies=[]
            for name in ['original','native']:
                destination=root/name/definition['revision'];destination.mkdir(parents=True)
                for path in definition['artifacts']:
                    target=destination/path;target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(snapshot/path,target)
                copies.append(destination)
            expected=capture(reference,copies[0],out/'oracle.json',definition=definition,cases=golden['cases'])
            for key in ['definition','artifacts','spec','spec_key','tokenizer_revision','cases','tolerances']:
                receipt['errors'].extend(_differences(golden[key],expected[key],'original.'+key))
            if expected['oracle']['runtime']!=golden['oracle']['runtime']:
                raise ValueError('original runtime differs from pre-port oracle')
            receipt['errors'].extend(compare_histories(golden,expected['results']))
            copied=root/'context-probe';shutil.copy2(native,copied)
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
            request={'registration':definition,'snapshot':str(copies[1]),'runtime_registration':registration,
                     'library':str(core_copy),'cases':golden['cases']}
            started=time.monotonic_ns()
            process=subprocess.run(command,cwd=root,env={'PATH':str(sentinels),'HOME':str(root),
                'TOKENIZERS_PARALLELISM':'false'},input=json.dumps(request),text=True,capture_output=True,timeout=600)
            receipt.update(native_exit=process.returncode,native_wall_ns=time.monotonic_ns()-started,
                outside_checkout=True,native_children=child_log.read_text().splitlines() if child_log.exists() else [])
            (out/'native.stdout.json').write_text(process.stdout);(out/'native.stderr.log').write_text(process.stderr)
            receipt['errors'].extend(stderr_errors(process.stderr,receipt['platform']))
            if process.returncode or receipt['native_children']:raise ValueError('native context failed or executed children')
            actual=json.loads(process.stdout)
            receipt['errors'].extend(compare_output(expected,actual,core))
            receipt.update(runtime=actual.get('runtime'),reference_runtime=expected['oracle']['runtime'],
                core_identity=core,stderr=process.stderr,stderr_warning_count=int(bool(process.stderr)))
            if receipt['platform']=='Linux':
                lines=[line for line in (out/'native-exec.trace').read_text().splitlines() if re.search(r'\bexecve(?:at)?\(',line)]
                receipt['exec_attempts']=len(lines)
                if len(lines)!=1 or str(copied) not in lines[0]:receipt['errors'].append('only initial exec allowed')
            for destination in [*copies,snapshot]:
                if snapshot_state(destination,definition)!=golden['artifacts']:receipt['errors'].append('model data changed')
            if _sha(core_copy)!=core['sha256'] or _sha(library)!=core['sha256']:receipt['errors'].append('native core changed')
            if _sha(copied)!=receipt['native_sha256'] or _sha(native)!=receipt['native_sha256']:receipt['errors'].append('native executable changed')
    except (OSError,ValueError,KeyError,TypeError,IndexError,subprocess.SubprocessError) as error:
        receipt['errors'].append(str(error))
    receipt['passed']=not receipt['errors']
    (out/'summary.json').write_text(json.dumps(receipt,indent=2,allow_nan=False)+'\n')
    return receipt


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['reference','native','snapshot','library','out']:parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    result=compare(Reference.load(args.reference),args.native,args.snapshot,args.library,args.out)
    print(json.dumps({'passed':result['passed'],'errors':result['errors']}))
    return int(not result['passed'])


if __name__=='__main__':raise SystemExit(main())
