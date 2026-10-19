"""Compose28 current native gates without claiming complete M2 acceptance."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess

from .policy_compare import GOLDEN,ROOT,RUNTIME,compare_policy,differences,select_oracle
from .policy_reference import policy_cases,policy_prompts
from .preparation import PreparedNativeContext,PreparedNativeEttin,PreparedNativeTranslation,PreparedTranslationBuild,policy_environment
from .reference import Reference
from .table_validate import _binding_matches
from .translation_reference import translation_cases
from .translation_validate import TRANSLATION_KEYS,TRANSLATION_GATES,translation_fingerprints,translation_receipt_errors,validate_translation
from .validate import _sha,_write,bind_native_release

POLICY_KEYS=TRANSLATION_KEYS|{'policy_cases','policy_oracle'}
POLICY_GATES=(*TRANSLATION_GATES,'policy_release','policy_parity')


def policy_fingerprints(repo:Path,reference:Reference|None,artifact:Path,snapshot:Path|None,
                        ettin_source:Path|None,translation_source:Path|None)->dict:
    return translation_fingerprints(repo,reference,artifact,snapshot,ettin_source,translation_source)|{
        'policy_cases':_sha(GOLDEN.with_name('cases.json')),'policy_oracle':_sha(GOLDEN)}


def policy_receipt_errors(row:dict,expected_ids:list[str],fingerprints:dict)->list[str]:
    errors=[];system=row.get('platform');architecture=row.get('architecture')
    gates=row.get('gates',{});identities=row.get('fingerprints',{})
    if (row.get('scope')!='policy-local' or row.get('passed') is not True
            or row.get('execution_error') or row.get('M2_accepted') is not False):errors.append('failed policy receipt')
    if set(gates)!=set(POLICY_GATES) or any(not isinstance(gates.get(gate),dict)
            or gates[gate].get('ran') is not True or gates[gate].get('passed') is not True for gate in POLICY_GATES):
        errors.append('incomplete28policy gates')
    if (set(identities)!=POLICY_KEYS or identities!=fingerprints
            or any(not isinstance(v,str) or len(v)!=64 or any(c not in '0123456789abcdef' for c in v)
                   for v in identities.values())):errors.append('stale or incomplete26policy input fingerprints')
    if not str(row.get('rustc','')).startswith('rustc 1.95.0 '):errors.append('unregistered policy Rust compiler')
    if row.get('case_ids')!=expected_ids:errors.append('wrong policy history coverage')
    base=row.get('translation_base',{})
    errors.extend(translation_receipt_errors(base,[c['id'] for c in translation_cases()],
        {k:identities.get(k) for k in TRANSLATION_KEYS}))
    if (base.get('platform')!=system or base.get('architecture')!=architecture
            or base.get('rustc')!=row.get('rustc')
            or any(base.get('gates',{}).get(gate)!=gates.get(gate) for gate in TRANSLATION_GATES)):
        errors.append('policy/translation base proof mismatch')
    binding=row.get('policy_release',{});parity=row.get('policy_parity',{})
    if not _binding_matches(binding,parity) or gates.get('policy_release')!=binding:
        errors.append('policy executable is not bound to fresh release')
    if (parity.get('format')!='ken-model-policy-parity/1' or parity.get('passed') is not True
            or parity.get('errors')!=[] or parity.get('M2_accepted') is not False
            or type(parity.get('native_exit')) is not int or parity['native_exit']!=0
            or type(parity.get('native_wall_ns')) is not int or parity['native_wall_ns']<=0
            or parity.get('outside_checkout') is not True or parity.get('native_children')!=[]
            or parity.get('dependency_audit',{}).get('passed') is not True
            or parity.get('dependency_audit',{}).get('errors')!=[] or parity.get('stderr')!=''
            or parity.get('case_ids')!=expected_ids or parity.get('prompt_models')!=policy_prompts()):
        errors.append('incomplete native policy process proof')
    if parity.get('platform')!=system or parity.get('architecture')!=architecture:
        errors.append('policy process platform mismatch')
    if system=='Linux' and (type(parity.get('exec_attempts')) is not int or parity['exec_attempts']!=1):
        errors.append('Linux policy requires exactly1exec')
    for key,identity in [('oracle_sha256','policy_oracle'),('cases_sha256','policy_cases')]:
        if parity.get(key)!=identities.get(identity):errors.append('policy oracle/input fingerprint mismatch')
    golden=select_oracle(json.loads(GOLDEN.read_text()),system,architecture)
    errors.extend(differences(RUNTIME,parity.get('runtime'),'runtime'))
    errors.extend(differences(golden['oracle'],parity.get('reference_oracle'),'reference_oracle'))
    stamp=parity.get('reference_fingerprint')
    if not isinstance(stamp,str) or len(stamp)!=64 or any(c not in '0123456789abcdef' for c in stamp):
        errors.append('policy original manifest fingerprint required')
    if parity.get('reference_source_fingerprint')!=identities.get('reference_source'):
        errors.append('policy current original source fingerprint mismatch')
    return errors


def aggregate_policies(directory:Path,*,expected_fingerprints:dict|None=None)->dict:
    if expected_fingerprints is None:
        expected_fingerprints=policy_fingerprints(ROOT,None,
            ROOT/'src/ken/embedder/data/ken__static-qwen3-r512-v2.npz',None,None,None)
    rows=[];errors=[];ids=[c['id'] for c in policy_cases()]
    for path in sorted(directory.rglob('summary.json')):
        try:
            row=json.loads(path.read_text())
            if isinstance(row,dict) and row.get('scope')=='policy-local':rows.append(row)
        except (OSError,ValueError):errors.append('unreadable policy receipt: '+str(path))
    if sorted((r.get('platform',''),r.get('architecture','')) for r in rows)!=[('Darwin','arm64'),('Linux','aarch64')]:
        errors.append('exactly one registered macOS and Linux policy receipt required')
    signatures=[]
    for row in rows:
        try:errors.extend(policy_receipt_errors(row,ids,expected_fingerprints))
        except (ValueError,TypeError,KeyError,AttributeError,IndexError) as error:errors.append('malformed policy receipt: '+str(error))
        signatures.append((row.get('fingerprints',{}),row.get('rustc')))
    if signatures and any(signature!=signatures[0] for signature in signatures):errors.append('policy platform source/input/toolchain drift')
    passed=not errors and len(rows)==2
    return {'scope':'policy-matrix','passed':passed,'errors':errors,'platforms':[r.get('platform') for r in rows],
        'Policy_accepted':passed,'M2_accepted':False,'fingerprints':expected_fingerprints}


def validate_policy(repo:Path,reference:Reference,model_probe:Path,potion_snapshot:Path,table_probe:Path,artifact:Path,
                    context:PreparedNativeContext,ettin:PreparedNativeEttin,translation:PreparedNativeTranslation,
                    policy_probe:Path,out:Path,baseline_dir:Path,original_manifest:Path)->int:
    repo=repo.resolve();out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    result={'scope':'policy-local','platform':platform.system(),'architecture':platform.machine(),
        'passed':False,'M2_accepted':False,'gates':{}}
    _write(out/'summary.json',result)
    try:
        policy_environment(policy_probe)
        if not policy_probe.is_file() or not os.access(policy_probe,os.X_OK):
            raise ValueError('explicit executable prepared native policy probe required')
        def fingerprints():return policy_fingerprints(repo,reference,artifact,context.snapshot,ettin.source,translation.source)
        before=fingerprints();result['fingerprints']=before
        validate_translation(repo,reference,model_probe,potion_snapshot,table_probe,artifact,context,ettin,translation,
            out/'base',baseline_dir,original_manifest,policy_probe=policy_probe)
        base=json.loads((out/'base/summary.json').read_text())
        result.update(translation_base=base,gates=dict(base.get('gates',{})),rustc=base.get('rustc'))
        if base.get('execution_error'):result['execution_error']=base['execution_error']
        binding=(bind_native_release(repo,policy_probe,'model_policy_probe') if result['gates'].get('release',{}).get('passed') is True
            else {'ran':False,'passed':False,'error':'fresh release build failed'})
        result['policy_release']=binding;result['gates']['policy_release']=binding
        if binding['passed']:
            parity=compare_policy(reference,policy_probe,out/'policy-parity')
            result.update(policy_parity=parity,case_ids=parity.get('case_ids',[]))
            result['gates']['policy_parity']={'ran':True,'passed':parity.get('passed') is True
                and _binding_matches(binding,parity) and result['case_ids']==[c['id'] for c in policy_cases()]}
        if before!=fingerprints():result['execution_error']='policy source/input drift during validation'
        if base.get('fingerprints')!={k:before[k] for k in TRANSLATION_KEYS}:
            result['execution_error']='policy/translation base source/input drift'
    except (OSError,ValueError,KeyError,TypeError,IndexError,subprocess.SubprocessError) as error:
        result['execution_error']=f'{type(error).__name__}: {error}'
    result['errors']=(['execution_error'] if result.get('execution_error') else [])+[
        gate for gate in POLICY_GATES if result['gates'].get(gate,{}).get('ran') is not True
        or result['gates'][gate].get('passed') is not True]
    result['passed']=not result['errors'];result['Policy_local_accepted']=result['passed']
    _write(out/'summary.json',result);return int(not result['passed'])


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope',choices=['local','matrix'],default='local')
    parser.add_argument('--platform-receipts',type=Path);parser.add_argument('--out',type=Path,required=True)
    names=['reference','model-probe','potion-snapshot','table-probe','artifact','context-probe','context-snapshot',
        'library','ettin-probe','ettin-source','native','source','policy-probe','baseline-dir','original-manifest']
    for name in names+['cmake','openblas-prefix']:parser.add_argument('--'+name,type=Path)
    args=parser.parse_args()
    if args.scope=='matrix':
        if not args.platform_receipts:parser.error('matrix requires platform-receipts')
        result=aggregate_policies(args.platform_receipts);_write(args.out/'summary.json',result)
        print(json.dumps({'passed':result['passed'],'errors':result['errors']}));return int(not result['passed'])
    if not all(getattr(args,name.replace('-','_')) for name in names):
        parser.error('local requires all explicit prepared native/model/baseline inputs')
    build=PreparedTranslationBuild(args.cmake,args.openblas_prefix) if args.cmake is not None else None
    return validate_policy(Path.cwd(),Reference.load(args.reference),args.model_probe,args.potion_snapshot,args.table_probe,args.artifact,
        PreparedNativeContext(args.context_snapshot,args.library,args.context_probe),PreparedNativeEttin(args.ettin_source,args.ettin_probe),
        PreparedNativeTranslation(args.source,args.native,build),args.policy_probe,args.out,args.baseline_dir,args.original_manifest)


if __name__=='__main__':raise SystemExit(main())
