"""Exact model-policy decisions from fresh original and independent native processes."""
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

from .model_compare import _audit, _sha
from .policy_reference import capture_policy, policy_cases, policy_prompts
from .reference import Reference
from .validate import _digest

ROOT=Path(__file__).resolve().parents[2]
GOLDEN=ROOT/'docs/validation/rust-migration-2026-10-19/m2-policy/reference.json'
RUNTIME={'engine':'rust','ken_models':'0.18.0','unicode':'15.0.0','model_runtime_needed':False}


def differences(expected:object,actual:object,path:str='output')->list[str]:
    """JSON equality includes primitive types: bool/int and int/float differ."""
    if type(expected) is not type(actual):return [path+': JSON type differs']
    if isinstance(expected,dict):
        if set(expected)!=set(actual):return [path+': missing or unexpected fields']
        return [error for key in expected for error in differences(expected[key],actual[key],path+'.'+key)]
    if isinstance(expected,list):
        if len(expected)!=len(actual):return [path+': sequence length differs']
        return [error for i,(want,got) in enumerate(zip(expected,actual,strict=True))
                for error in differences(want,got,f'{path}[{i}]')]
    return [] if expected==actual else [path+': value differs']


def select_oracle(document:dict,system:str,architecture:str)->dict:
    if (system,architecture) not in [('Darwin','arm64'),('Linux','aarch64')]:
        raise ValueError('registered policy platform/architecture required')
    if (document.get('format')!='ken-model-policy-oracles/1'
            or document.get('logical_outputs_equal') is not True):
        raise ValueError('independent frozen policy oracle document required')
    rows=document.get('oracles',[])
    if (len(rows)!=2 or sorted((r['platform'],r['architecture']) for r in rows)
            !=[('Darwin','arm64'),('Linux','aarch64')]):
        raise ValueError('one original policy oracle per registered platform required')
    for key in ['results','observations','prompts']:
        if differences(rows[0][key],rows[1][key]):
            raise ValueError('original policy logical outputs disagree')
    return next(row for row in rows if row['platform']==system and row['architecture']==architecture)


def compare_output(expected:dict,actual:object)->list[str]:
    return differences({'format':'ken-model-policy-native/1','runtime':RUNTIME,
        'results':expected['results'],'prompts':expected['prompts']},actual)


def compare_reference(expected:dict,actual:object,*,reference_fingerprint:str|None=None)->list[str]:
    # Capture verifies the current manifest before and after the original child.
    # Its ancillary checkout files need not equal the historical oracle checkout.
    wanted=expected if reference_fingerprint is None else expected|{'reference_fingerprint':reference_fingerprint}
    return differences(wanted,actual,'original')


def dependency_errors(linked:str,system:str)->list[str]:
    errors=[];names=set()
    if system=='Darwin':
        allowed={'/System/Library/Frameworks/Accelerate.framework/Versions/A/Accelerate',
            '/usr/lib/libSystem.B.dylib','/usr/lib/libc++.1.dylib','/usr/lib/libiconv.2.dylib'}
        for line in linked.splitlines()[1:]:
            fields=line.split()
            if not fields:continue
            path=fields[0];names.add(Path(path).name)
            if path not in allowed:errors.append('unregistered macOS policy dependency: '+path)
        if 'libSystem.B.dylib' not in names:errors.append('ordinary macOS system dependency required')
    elif system=='Linux':
        allowed={'linux-vdso.so.1','libgomp.so.1','libstdc++.so.6','libm.so.6',
            'libgcc_s.so.1','libc.so.6','ld-linux-aarch64.so.1'}
        for line in linked.splitlines():
            fields=line.split()
            if not fields:continue
            name=Path(fields[0]).name;names.add(name)
            if name not in allowed:errors.append('unregistered Linux policy dependency: '+name)
            path=fields[2] if len(fields)>2 and fields[1]=='=>' else fields[0]
            if name!='linux-vdso.so.1' and not path.startswith(('/lib/','/usr/lib/')):
                errors.append('ordinary policy system dependency path required: '+path)
        if not {'libc.so.6','ld-linux-aarch64.so.1'}<=names:errors.append('ordinary Linux system dependencies required')
    else:errors.append('unregistered policy dependency platform')
    return errors


def compare_policy(reference:Reference,probe:Path,out:Path)->dict:
    out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    receipt={'format':'ken-model-policy-parity/1','platform':platform.system(),'architecture':platform.machine(),
        'passed':False,'errors':[],'native_children':[],'outside_checkout':False,'M2_accepted':False}
    try:
        if not probe.is_absolute() or not probe.is_file() or not os.access(probe,os.X_OK):
            raise ValueError('explicit executable native policy probe required')
        with probe.open('rb') as stream:
            if stream.read(4) not in (b'\x7fELF',b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe'):
                raise ValueError('native policy executable required; interpreter scripts rejected')
        golden=select_oracle(json.loads(GOLDEN.read_text()),receipt['platform'],receipt['architecture'])
        cases_path=GOLDEN.with_name('cases.json');cases=json.loads(cases_path.read_text())
        if differences({'cases':policy_cases(),'prompts':policy_prompts()},cases):
            raise ValueError('frozen policy inputs changed')
        audit=_audit(probe,out)
        checks=dependency_errors((out/'dependencies.log').read_text(),receipt['platform'])
        audit.update(passed=audit['passed'] and not checks,errors=checks)
        receipt.update(native_sha256=_sha(probe),oracle_sha256=_sha(GOLDEN),cases_sha256=_sha(cases_path),
            case_ids=[c['id'] for c in cases['cases']],prompt_models=cases['prompts'],dependency_audit=audit)
        if not audit['passed']:raise ValueError('native policy dependency audit failed')
        fresh=capture_policy(reference,out/'oracle.json')
        receipt['errors'].extend(compare_reference(golden,fresh,reference_fingerprint=reference.fingerprint))
        source_rows=[row for row in json.loads(reference.manifest_path.read_text())['files']
                     if row['path'].startswith('src/ken/')]
        receipt.update(reference_oracle=fresh['oracle'],reference_fingerprint=fresh['reference_fingerprint'],
            reference_source_fingerprint=_digest(source_rows))
        if receipt['errors']:raise ValueError('fresh original policy differs from frozen oracle')
        with tempfile.TemporaryDirectory(prefix='ken-model-policy-process-') as directory:
            root=Path(directory);copied=root/'model-policy-probe';shutil.copy2(probe,copied)
            sentinels=root/'sentinel-path';sentinels.mkdir();children=root/'children.log'
            for name in ['python','python3','ken','sh','bash','zsh']:
                shim=sentinels/name
                shim.write_text(f"#!/bin/sh\nprintf '%s\\n' {shlex.quote(name)} >> {shlex.quote(str(children))}\nexit 97\n")
                shim.chmod(0o755)
            request={'cases':[{'id':c['id'],'input':c['input']} for c in cases['cases']],'prompts':cases['prompts']}
            (out/'native.request.json').write_text(json.dumps(request,indent=2)+'\n')
            command=[str(copied)]
            if receipt['platform']=='Linux':
                tracer=shutil.which('strace')
                if not tracer:raise ValueError('Linux policy proof requires actual strace')
                command=[tracer,'-f','-e','trace=execve,execveat','-o',str(out/'native-exec.trace'),*command]
            started=time.monotonic_ns()
            result=subprocess.run(command,input=json.dumps(request,allow_nan=False),text=True,capture_output=True,
                cwd=root,env={'PATH':str(sentinels),'HOME':str(root)},timeout=30)
            receipt.update(native_exit=result.returncode,native_wall_ns=time.monotonic_ns()-started,
                outside_checkout=True,native_children=children.read_text().splitlines() if children.exists() else [],stderr=result.stderr)
            (out/'native.stdout.json').write_text(result.stdout);(out/'native.stderr.log').write_text(result.stderr)
            if result.returncode or result.stderr or receipt['native_children']:
                raise ValueError('native policy failed, wrote stderr or executed children')
            actual=json.loads(result.stdout);receipt['errors'].extend(compare_output(fresh,actual))
            receipt['runtime']=actual.get('runtime')
            if receipt['platform']=='Linux':
                lines=[line for line in (out/'native-exec.trace').read_text().splitlines() if re.search(r'\bexecve(?:at)?\(',line)]
                receipt['exec_attempts']=len(lines)
                if len(lines)!=1 or str(copied) not in lines[0]:receipt['errors'].append('only initial policy exec allowed')
            if _sha(copied)!=receipt['native_sha256'] or _sha(probe)!=receipt['native_sha256']:
                receipt['errors'].append('native policy executable changed')
            if _sha(GOLDEN)!=receipt['oracle_sha256'] or _sha(cases_path)!=receipt['cases_sha256']:
                receipt['errors'].append('policy oracle/inputs changed during comparison')
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError,OverflowError,subprocess.SubprocessError) as error:
        receipt['errors'].append(str(error))
    receipt['passed']=not receipt['errors']
    (out/'summary.json').write_text(json.dumps(receipt,indent=2,allow_nan=False)+'\n')
    return receipt


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['reference','native','out']:parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();result=compare_policy(Reference.load(args.reference),args.native,args.out)
    print(json.dumps({'passed':result['passed'],'errors':result['errors']}));return int(not result['passed'])


if __name__=='__main__':raise SystemExit(main())
