"""Exact native query histories, authenticated preparation and process evidence."""
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
from .ettin_reference import source_state
from .model_compare import _audit, _sha
from .reference import Reference
from .translation_reference import capture, translation_cases

ROOT=Path(__file__).resolve().parents[2]
GOLDEN=ROOT/'docs/validation/rust-migration-2026-10-19/m2-translation/reference.json'
RAW_GOLDEN=GOLDEN.with_name('raw-reference.json')
RUNTIME={'engine':'rust','ken_models':'0.18.0'}


def select_oracle(document:dict,system:str,architecture:str)->dict:
    if (system,architecture) not in [('Darwin','arm64'),('Linux','aarch64')]:
        raise ValueError('registered translation platform/architecture required')
    rows=[r for r in document.get('oracles',[]) if r.get('platform')==system and r.get('architecture')==architecture]
    if len(rows)!=1:raise ValueError('one unambiguous local original translation oracle required')
    return rows[0]


def native_identity(system:str,architecture:str='aarch64',*,backend:str|None=None)->dict:
    if system not in ('Darwin','Linux'):raise ValueError('registered native translation platform required')
    result={'ct2rs_crate':'0.10.1','ctranslate2_source':'4.8.2','sentencepiece_crate':'0.13.2',
        'sentencepiece_source':'0.2.1','float_backend':'Accelerate' if system=='Darwin' else 'OpenBLAS0.3.26',
        'int8_backend':'Ruy','configured_device':'cpu','configured_compute_type':'int8','intra_threads':2,
        'inter_threads':1,'observed_replicas':1,'beam_size':1,'max_input_length':1024,'max_decoding_length':256}
    if architecture=='x86_64':
        if system!='Linux'or backend not in('DNNL','MKL'):raise ValueError('explicit registered x86 CPU backend required')
        del result['ct2rs_crate']
        result.update(native_binding='ken-translation/1',float_backend=backend,int8_backend=backend)
    elif architecture not in('aarch64','arm64'):raise ValueError('registered native translation architecture required')
    return result


def _positive(value:object)->bool:
    return type(value) is int and value>0


def preparation_errors(expected:dict,actual:object)->list[str]:
    return _differences({'fresh_cache':True,'reused_without_source':True,
        'source_artifacts':expected['source_artifacts'],'artifacts':expected['prepared_artifacts'],
        'recipe_key':expected['recipe_sha256']},actual,'preparation')


def _memory_errors(expected:dict,actual:object)->list[str]:
    if not isinstance(actual,list):return ['memory sample history required']
    phases=[r['phase'] for r in expected['memory_samples']]
    if [r.get('phase') if isinstance(r,dict) else None for r in actual]!=phases:
        return ['missing, reordered or unexpected memory phases']
    peak=0;errors=[]
    for row in actual:
        if set(row)!={'phase','reported_hwm_bytes','observed_peak_bytes'}:
            errors.append('unexpected memory sample fields');continue
        raw=row['reported_hwm_bytes'];observed=row['observed_peak_bytes']
        if not _positive(raw) or not _positive(observed):
            errors.append('positive integer memory samples required');continue
        peak=max(peak,raw)
        if observed!=peak:errors.append('observed peak differs from exact retained raw maximum')
    return errors


def _native_error(case:dict,wanted:dict)->dict:
    if wanted['type']=='RuntimeError':
        return {'type':'ModelError','kind':'inference','message':wanted['message']}
    if wanted['type']=='ValueError' and case.get('missing_assets'):
        return {'type':'ModelError','kind':'artifact','message':
            'model artifact missing or changed: explicit translation source required for preparation'}
    if wanted['type']=='ValueError' and case.get('corrupt_artifact'):
        return {'type':'ModelError','kind':'artifact','message':
            'model artifact missing or changed: '+case['corrupt_artifact']}
    raise ValueError('unregistered original translation failure')


def _history_errors(expected:dict,actual:object,*,native:bool,backend:str|None=None)->list[str]:
    cases=expected['cases'];wanted=expected['results'];ids=[c['id'] for c in cases]
    if (not isinstance(actual,list) or [r.get('id') if isinstance(r,dict) else None for r in actual]!=ids
            or [r.get('id') for r in wanted]!=ids):return ['missing, duplicated, reordered or unexpected translation histories']
    errors=[]
    for case,want,row in zip(cases,wanted,actual,strict=True):
        name=case['id']
        if set(row)!={'id','calls','constructor_ns','identity','revision','actual_runtime'}:
            errors.append(name+': unexpected result fields')
        if not _positive(row.get('constructor_ns')):errors.append(name+': invalid constructor measurement')
        for key in ['identity','revision']:
            errors.extend(_differences(want[key],row.get(key),name+'.'+key))
        runtime=(native_identity(expected['platform'],expected['architecture'],backend=backend) if want['calls'][-1]['runtime_loaded'] else None) if native else want['actual_runtime']
        errors.extend(_differences(runtime,row.get('actual_runtime'),name+'.actual_runtime'))
        calls=row.get('calls')
        if not isinstance(calls,list) or len(calls)!=len(want['calls']) or len(calls)!=len(case['queries']):
            errors.append(name+': wrong call count');continue
        for index,(a,b) in enumerate(zip(want['calls'],calls,strict=True)):
            path=f'{name}.calls[{index}]'
            if not isinstance(b,dict):errors.append(path+': call object required');continue
            if not _positive(b.get('wall_ns')):errors.append(path+': invalid call measurement')
            wanted_call={k:v for k,v in a.items() if k!='wall_ns'}
            if native and 'error' in wanted_call:wanted_call['error']=_native_error(case,wanted_call['error'])
            errors.extend(_differences(wanted_call,{k:v for k,v in b.items() if k!='wall_ns'},path))
    return errors


def compare_output(expected:dict,actual:object,*,backend:str|None=None)->list[str]:
    if not isinstance(actual,dict):return ['native translation output must be an object']
    if set(actual)!={'format','preparation','prepare_ns','runtime','memory_samples','results'}:
        return ['missing or unexpected native translation output fields']
    try:
        errors=_differences('ken-translation-native/1',actual['format'],'format')
        errors.extend(preparation_errors(expected,actual['preparation']))
        errors.extend(_differences(RUNTIME,actual['runtime'],'runtime'))
        if not _positive(actual['prepare_ns']):errors.append('invalid native preparation measurement')
        errors.extend(_memory_errors(expected,actual['memory_samples']))
        return errors+_history_errors(expected,actual['results'],native=True,backend=backend)
    except (ValueError,TypeError,KeyError,IndexError,AttributeError) as error:
        return [f'malformed native translation history: {error}']


def compare_reference(expected:dict,actual:dict,*,reference_fingerprint:str|None=None)->list[str]:
    try:
        errors=[]
        for key in ['format','platform','architecture','definition','cases','source_artifacts',
                    'prepared_artifacts','recipe_sha256','boundary_characterization','reference_fingerprint','oracle']:
            wanted=reference_fingerprint if key=='reference_fingerprint' and reference_fingerprint is not None else expected[key]
            errors.extend(_differences(wanted,actual.get(key),'original.'+key))
        if not _positive(actual.get('prepare_ns')):errors.append('invalid original preparation measurement')
        errors.extend(_memory_errors(expected,actual.get('memory_samples')))
        return errors+_history_errors(expected,actual.get('results'),native=False)
    except (ValueError,TypeError,KeyError,IndexError,AttributeError) as error:
        return [f'malformed original translation history: {error}']


def dependency_errors(linked:str,system:str)->list[str]:
    errors=[];names=set()
    if system=='Darwin':
        for line in linked.splitlines()[1:]:
            fields=line.split()
            if not fields:continue
            path=fields[0];name=Path(path).name;names.add(name)
            if path=='/System/Library/Frameworks/Accelerate.framework/Versions/A/Accelerate':continue
            if path not in ['/usr/lib/libSystem.B.dylib','/usr/lib/libc++.1.dylib','/usr/lib/libiconv.2.dylib']:
                errors.append('unregistered macOS dependency: '+path)
        if not {'Accelerate','libSystem.B.dylib','libc++.1.dylib'}<=names:
            errors.append('Accelerate and ordinary C++/system dependencies required')
    elif system=='Linux':
        allowed={'linux-vdso.so.1','libgomp.so.1','libstdc++.so.6','libm.so.6','libgcc_s.so.1','libc.so.6','ld-linux-aarch64.so.1'}
        for line in linked.splitlines():
            fields=line.split()
            if not fields:continue
            name=Path(fields[0]).name;names.add(name)
            if name not in allowed:errors.append('unregistered Linux dependency: '+name)
            path=fields[2] if len(fields)>2 and fields[1]=='=>' else fields[0]
            if name!='linux-vdso.so.1' and not path.startswith(('/lib/','/usr/lib/')):
                errors.append('ordinary system dependency path required: '+path)
        if not {'libgomp.so.1','libstdc++.so.6','libc.so.6','ld-linux-aarch64.so.1'}<=names:
            errors.append('explicit Linux OpenMP/C++/system dependencies required')
    else:errors.append('unregistered native dependency platform')
    return errors


def compare(reference:Reference,native:Path,source:Path,out:Path)->dict:
    out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    receipt={'format':'ken-translation-parity/1','platform':platform.system(),'architecture':platform.machine(),
        'passed':False,'errors':[],'native_children':[],'outside_checkout':False,'M2_accepted':False}
    try:
        if not native.is_absolute() or not native.is_file() or not os.access(native,os.X_OK):
            raise ValueError('explicit executable translation probe required')
        with native.open('rb') as stream:
            if stream.read(4) not in (b'\x7fELF',b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe'):
                raise ValueError('native executable required; interpreter scripts rejected')
        document=json.loads(GOLDEN.read_text());golden=select_oracle(document,receipt['platform'],receipt['architecture'])
        fixed_cases=json.loads(GOLDEN.with_name('cases.json').read_text())
        if _differences(translation_cases(),fixed_cases) or _differences(fixed_cases,golden['cases']):
            raise ValueError('fixed translation histories changed')
        definition=json.loads((reference.root/'src/ken/embedder/data/es-en-ct2-int8.json').read_text())
        if not source.is_absolute() or _differences(golden['definition'],definition) or source_state(source,definition['source'])!=golden['source_artifacts']:
            raise ValueError('registered translation definition/source bytes changed')
        audit=_audit(native,out)
        dependency_checks=dependency_errors((out/'dependencies.log').read_text(),receipt['platform'])
        audit.update(passed=audit['passed'] and not dependency_checks,errors=dependency_checks)
        receipt.update(native_sha256=_sha(native),oracle_sha256=_sha(GOLDEN),raw_oracle_sha256=_sha(RAW_GOLDEN),
            case_ids=[c['id'] for c in golden['cases']],dependency_audit=audit)
        if not audit['passed']:raise ValueError('native translation dependency audit failed')
        with tempfile.TemporaryDirectory(prefix='ken-translation-process-') as directory:
            root=Path(directory);copies=[]
            for name in ['original-source','native-source']:
                destination=root/name/definition['source']['revision'];destination.mkdir(parents=True)
                for name in definition['source']['artifacts']:shutil.copy2(source/name,destination/name)
                copies.append(destination)
            cache=root/'native-prepared'/definition['derived']['revision']
            if os.path.lexists(cache):raise ValueError('fresh native translation destination required')
            copied=root/'translation-probe';shutil.copy2(native,copied)
            sentinels=root/'sentinel-path';sentinels.mkdir();children=root/'children.log'
            for name in ['python','python3','ken','sh','bash','zsh']:
                shim=sentinels/name
                shim.write_text(f"#!/bin/sh\nprintf '%s\\n' {shlex.quote(name)} >> {shlex.quote(str(children))}\nexit 97\n")
                shim.chmod(0o755)
            command=[str(copied)]
            if receipt['platform']=='Linux':
                tracer=shutil.which('strace')
                if not tracer:raise ValueError('Linux translation proof requires actual strace')
                command=[tracer,'-f','-e','trace=execve,execveat','-o',str(out/'native-exec.trace'),*command]
            request={'registration':definition,'source':str(copies[1]),'cache':str(cache),'cases':golden['cases']}
            (out/'native.request.json').write_text(json.dumps(request,indent=2)+'\n')
            started=time.monotonic_ns()
            process=subprocess.run(command,cwd=root,env={'PATH':str(sentinels),'HOME':str(root)},
                input=json.dumps(request,allow_nan=False),text=True,capture_output=True,timeout=600)
            receipt.update(native_exit=process.returncode,native_wall_ns=time.monotonic_ns()-started,
                outside_checkout=True,native_children=children.read_text().splitlines() if children.exists() else [])
            (out/'native.stdout.json').write_text(process.stdout);(out/'native.stderr.log').write_text(process.stderr)
            receipt['stderr']=process.stderr
            if process.stderr:receipt['errors'].append('unexpected native translation stderr')
            if process.returncode or receipt['native_children']:raise ValueError('native translation failed or executed children')
            actual=json.loads(process.stdout);receipt['errors'].extend(compare_output(golden,actual))
            if receipt['platform']=='Linux':
                lines=[line for line in (out/'native-exec.trace').read_text().splitlines() if re.search(r'\bexecve(?:at)?\(',line)]
                receipt['exec_attempts']=len(lines)
                if len(lines)!=1 or str(copied) not in lines[0]:receipt['errors'].append('only initial translation exec allowed')
            if receipt['errors']:raise ValueError('native translation differs from frozen original')
            loaded=[row['actual_runtime'] for row in actual['results'] if row['actual_runtime'] is not None]
            if not loaded:raise ValueError('actual native translation session identity required')
            receipt['native_identity']=loaded[0]
            expected=capture(reference,copies[0],out/'oracle.json',definition=definition,cases=golden['cases'])
            receipt['errors'].extend(compare_reference(golden,expected,reference_fingerprint=reference.fingerprint))
            receipt['errors'].extend(compare_output(expected,actual))
            receipt.update(preparation=actual['preparation'],runtime=actual['runtime'],reference_runtime=expected['oracle']['runtime'])
            for destination in [source,*copies]:
                if source_state(destination,definition['source'])!=golden['source_artifacts']:
                    receipt['errors'].append('translation source artifacts changed')
            for name,record in golden['prepared_artifacts'].items():
                path=cache/name
                if not path.is_file() or path.stat().st_size!=record['bytes'] or _sha(path)!=record['sha256']:
                    receipt['errors'].append('native published translation cache changed')
            if _sha(copied)!=receipt['native_sha256'] or _sha(native)!=receipt['native_sha256']:
                receipt['errors'].append('native translation executable changed')
    except (OSError,ValueError,KeyError,TypeError,IndexError,OverflowError,subprocess.SubprocessError) as error:
        receipt['errors'].append(str(error))
    receipt['passed']=not receipt['errors']
    (out/'summary.json').write_text(json.dumps(receipt,indent=2,allow_nan=False)+'\n')
    return receipt


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['reference','native','source','out']:parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    result=compare(Reference.load(args.reference),args.native,args.source,args.out)
    print(json.dumps({'passed':result['passed'],'errors':result['errors']}))
    return int(not result['passed'])


if __name__=='__main__':raise SystemExit(main())
