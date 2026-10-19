"""Current storage acceptance adds three gates to the complete policy chain."""
from __future__ import annotations
import json
import argparse
import os
from pathlib import Path
import platform
import re
import subprocess
from .policy_compare import differences
from .policy_reference import policy_cases
from .policy_validate import POLICY_GATES,POLICY_KEYS,policy_fingerprints,policy_receipt_errors,validate_policy
from .preparation import PreparedNativeContext,PreparedNativeEttin,PreparedNativeTranslation,PreparedNativeStorage,PreparedTranslationBuild,storage_environment
from .reference import Reference
from .storage_compare import GOLDEN,ROOT,RUNTIME,select_oracle,compare_storage
from .storage_reference import storage_cases
from .storage_recovery import CASES,recovery_receipt_errors,verify_recovery
from .table_validate import _binding_matches
from .validate import _sha,_write,bind_native_release

STORAGE_KEYS=POLICY_KEYS|{'storage_cases','storage_oracle','storage_recovery_cases'}
STORAGE_GATES=(*POLICY_GATES,'storage_release','storage_parity','storage_recovery')

def storage_fingerprints(repo:Path,reference,artifact:Path,snapshot:Path|None,ettin_source:Path|None,translation_source:Path|None)->dict:
    return policy_fingerprints(repo,reference,artifact,snapshot,ettin_source,translation_source)|{
        'storage_cases':_sha(GOLDEN.with_name('cases.json')),'storage_oracle':_sha(GOLDEN),'storage_recovery_cases':_sha(CASES)}

def storage_receipt_errors(row:dict,expected_ids:list[str],fingerprints:dict)->list[str]:
    try:
        errors=[];gates=row.get('gates',{});identities=row.get('fingerprints',{})
        system=row.get('platform');architecture=row.get('architecture')
        if (row.get('scope')!='storage-local' or row.get('passed') is not True
                or row.get('execution_error') or row.get('M2_accepted') is not False
                or type(row.get('synthetic_fixture')) is not bool):errors.append('failed storage receipt')
        if set(gates)!=set(STORAGE_GATES) or any(not isinstance(gates.get(k),dict) or gates[k].get('ran') is not True or gates[k].get('passed') is not True for k in STORAGE_GATES):errors.append('incomplete31storage gates')
        if (set(identities)!=STORAGE_KEYS or identities!=fingerprints
                or any(not isinstance(v,str) or not re.fullmatch('[0-9a-f]{64}',v) for v in identities.values())):
            errors.append('stale or incomplete29storage input fingerprints')
        if not str(row.get('rustc','')).startswith('rustc 1.95.0 '):errors.append('unregistered storage Rust compiler')
        if row.get('case_ids')!=expected_ids:errors.append('wrong storage history coverage')
        policy=row.get('policy_base',{})
        errors+=policy_receipt_errors(policy,[c['id'] for c in policy_cases()],{k:identities.get(k) for k in POLICY_KEYS})
        if (any(policy.get(k)!=row.get(k) for k in ['platform','architecture','rustc'])
                or any(policy.get('gates',{}).get(k)!=gates.get(k) for k in POLICY_GATES)):
            errors.append('storage/policy base proof mismatch')
        binding=row.get('storage_release',{});parity=row.get('storage_parity',{});recovery=row.get('storage_recovery',{})
        if not _binding_matches(binding,parity) or gates.get('storage_release')!=binding:
            errors.append('storage probe is not bound to fresh release')
        driver=binding.get('recovery_driver',{})
        if (driver.get('ran') is not True or driver.get('passed') is not True
                or driver.get('built_sha256')!=recovery.get('driver_sha256')
                or driver.get('supplied_sha256')!=recovery.get('driver_sha256')):
            errors.append('recovery driver is not bound to fresh release')
        if (parity.get('format')!='ken-storage-parity/1' or parity.get('passed') is not True
                or parity.get('errors')!=[] or parity.get('M2_accepted') is not False
                or type(parity.get('native_exit')) is not int or parity['native_exit']!=0
                or any(type(parity.get(k)) is not int or parity[k]<=0 for k in ['native_wall_ns','original_wall_ns'])
                or parity.get('outside_checkout') is not True or parity.get('native_children')!=[]
                or parity.get('dependency_audit',{}).get('passed') is not True
                or parity.get('dependency_audit',{}).get('errors')!=[] or parity.get('stderr')!=''
                or parity.get('case_ids')!=expected_ids or type(parity.get('compatibility_count')) is not int
                or parity['compatibility_count']!=23 or type(parity.get('correction_count')) is not int or parity['correction_count']!=9):
            errors.append('incomplete native storage process proof')
        errors+=differences(RUNTIME,parity.get('runtime'),'storage runtime')
        metrics=parity.get('metrics',{})
        if set(metrics)!={'peak_rss_bytes','elapsed_ns'} or any(type(v) is not int or v<=0 for v in metrics.values()):errors.append('measured native storage RSS/time required')
        if system=='Linux' and (type(parity.get('exec_attempts')) is not int or parity['exec_attempts']!=1):errors.append('Linux storage requires exactly1exec')
        for proof in [parity,recovery]:
            if proof.get('platform')!=system or proof.get('architecture')!=architecture:errors.append('storage process platform mismatch')
        golden=select_oracle(json.loads(GOLDEN.read_bytes()),system,architecture)
        errors+=differences(golden['oracle'],parity.get('reference_oracle'),'storage original provenance')
        stamp=parity.get('reference_fingerprint')
        if not isinstance(stamp,str) or not re.fullmatch('[0-9a-f]{64}',stamp):errors.append('verified original storage manifest fingerprint required')
        for proof in [parity,recovery]:
            if proof.get('reference_fingerprint')!=stamp or proof.get('reference_source_fingerprint')!=identities.get('reference_source'):errors.append('storage original source/manifest identity mismatch')
        if (parity.get('oracle_sha256')!=identities.get('storage_oracle') or parity.get('cases_sha256')!=identities.get('storage_cases')
                or recovery.get('cases_sha256')!=identities.get('storage_recovery_cases')):errors.append('storage frozen input fingerprint mismatch')
        errors+=recovery_receipt_errors(recovery)
        return errors
    except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError) as error:
        return ['malformed storage receipt: '+str(error)]

def aggregate_storage(directory:Path,*,expected_fingerprints:dict|None=None)->dict:
    from .storage_evidence import execution_errors
    if expected_fingerprints is None:
        expected_fingerprints=storage_fingerprints(ROOT,None,ROOT/'src/ken/embedder/data/ken__static-qwen3-r512-v2.npz',None,None,None)
    rows=[];roots=[];errors=[]
    for path in sorted(directory.rglob('summary.json')):
        try:
            row=json.loads(path.read_bytes())
            if isinstance(row,dict) and row.get('scope')=='storage-local':rows.append(row);roots.append(path.parent)
        except (OSError,ValueError):errors.append('unreadable storage receipt: '+str(path))
    if sorted((r.get('platform',''),r.get('architecture','')) for r in rows)!=[('Darwin','arm64'),('Linux','aarch64')]:errors.append('exactly one registered macOS and Linux storage receipt required')
    signatures=[]
    for root,row in zip(roots,rows,strict=True):
        if row.get('synthetic_fixture') is not False:
            errors.append('synthetic storage fixtures cannot certify runtime acceptance');continue
        errors+=storage_receipt_errors(row,[c['id'] for c in storage_cases()],expected_fingerprints)
        errors+=execution_errors(root,row)
        signatures.append((row.get('fingerprints',{}),row.get('rustc')))
    if signatures and any(signature!=signatures[0] for signature in signatures):errors.append('storage platform source/input/toolchain drift')
    passed=not errors and len(rows)==2
    return {'scope':'storage-matrix','passed':passed,'errors':errors,'platforms':[r.get('platform') for r in rows],
            'Storage_accepted':passed,'Policy_accepted':passed,'M2_accepted':False,'fingerprints':expected_fingerprints}


def validate_storage(repo:Path,reference:Reference,model_probe:Path,potion_snapshot:Path,table_probe:Path,artifact:Path,
                     context:PreparedNativeContext,ettin:PreparedNativeEttin,translation:PreparedNativeTranslation,
                     policy_probe:Path,storage:PreparedNativeStorage,out:Path,baseline_dir:Path,original_manifest:Path)->int:
    from .storage_evidence import seal_execution,execution_errors
    repo=repo.resolve();out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    result={'scope':'storage-local','synthetic_fixture':False,'platform':platform.system(),'architecture':platform.machine(),
            'passed':False,'M2_accepted':False,'gates':{}}
    _write(out/'summary.json',result)
    try:
        storage_environment(storage);driver=storage.probe.with_name('storage_recovery_driver')
        if any(not p.is_file() or not os.access(p,os.X_OK) for p in [storage.probe,driver]):
            raise ValueError('explicit executable prepared storage probe and recovery driver required')
        def fingerprints():return storage_fingerprints(repo,reference,artifact,context.snapshot,ettin.source,translation.source)
        before=fingerprints();result['fingerprints']=before
        validate_policy(repo,reference,model_probe,potion_snapshot,table_probe,artifact,context,ettin,translation,
                        policy_probe,out/'base',baseline_dir,original_manifest,storage=storage)
        base=json.loads((out/'base/summary.json').read_bytes())
        result.update(policy_base=base,gates=dict(base.get('gates',{})),rustc=base.get('rustc'))
        if base.get('execution_error'):result['execution_error']=base['execution_error']
        if result['gates'].get('release',{}).get('passed') is True:
            binding=bind_native_release(repo,storage.probe,'storage_probe')
            driver_binding=bind_native_release(repo,driver,'storage_recovery_driver')
            binding.update(passed=binding['passed'] and driver_binding['passed'],recovery_driver=driver_binding)
        else:binding={'ran':False,'passed':False,'error':'fresh release build failed'}
        result['storage_release']=binding;result['gates']['storage_release']=binding
        if binding['passed']:
            parity=compare_storage(reference,storage.probe,out/'storage-parity')
            result.update(storage_parity=parity,case_ids=parity.get('case_ids',[]))
            result['gates']['storage_parity']={'ran':True,'passed':parity.get('passed') is True and _binding_matches(binding,parity)
                and result['case_ids']==[c['id'] for c in storage_cases()]}
            recovery=verify_recovery(reference,driver,out/'storage-recovery');result['storage_recovery']=recovery
            result['gates']['storage_recovery']={'ran':True,'passed':recovery.get('passed') is True
                and driver_binding['built_sha256']==recovery.get('driver_sha256') and not recovery_receipt_errors(recovery)}
        if before!=fingerprints():result['execution_error']='storage source/input drift during validation'
        if base.get('fingerprints')!={k:before[k] for k in POLICY_KEYS}:result['execution_error']='storage/policy base source/input drift'
    except (OSError,ValueError,KeyError,TypeError,IndexError,subprocess.SubprocessError) as error:
        result['execution_error']=f'{type(error).__name__}: {error}'
    result['errors']=(['execution_error'] if result.get('execution_error') else [])+[
        gate for gate in STORAGE_GATES if result['gates'].get(gate,{}).get('ran') is not True or result['gates'][gate].get('passed') is not True]
    result['passed']=not result['errors'];result['Storage_local_accepted']=result['passed']
    if result['passed']:
        result['errors']+=storage_receipt_errors(result,[c['id'] for c in storage_cases()],result['fingerprints'])
        if not result['errors']:
            try:
                result['execution_artifacts']=seal_execution(out);result['errors']+=execution_errors(out,result)
            except (OSError,ValueError,TypeError) as error:result['errors'].append('storage evidence: '+str(error))
        result['passed']=not result['errors'];result['Storage_local_accepted']=result['passed']
    _write(out/'summary.json',result);return int(not result['passed'])


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope',choices=['local','matrix'],default='local')
    parser.add_argument('--platform-receipts',type=Path);parser.add_argument('--out',type=Path,required=True)
    names=['reference','model-probe','potion-snapshot','table-probe','artifact','context-probe','context-snapshot',
           'library','ettin-probe','ettin-source','native','source','policy-probe','storage-probe','baseline-dir','original-manifest']
    for name in names+['cmake','openblas-prefix']:parser.add_argument('--'+name,type=Path)
    args=parser.parse_args()
    if args.scope=='matrix':
        if not args.platform_receipts:parser.error('matrix requires platform-receipts')
        result=aggregate_storage(args.platform_receipts);_write(args.out/'summary.json',result)
        print(json.dumps({'passed':result['passed'],'errors':result['errors']}));return int(not result['passed'])
    if not all(getattr(args,n.replace('-','_')) for n in names):parser.error('local requires all explicit prepared native/model/baseline inputs')
    build=PreparedTranslationBuild(args.cmake,args.openblas_prefix) if args.cmake is not None else None
    return validate_storage(Path.cwd(),Reference.load(args.reference),args.model_probe,args.potion_snapshot,args.table_probe,args.artifact,
        PreparedNativeContext(args.context_snapshot,args.library,args.context_probe),PreparedNativeEttin(args.ettin_source,args.ettin_probe),
        PreparedNativeTranslation(args.source,args.native,build),args.policy_probe,PreparedNativeStorage(args.storage_probe),args.out,args.baseline_dir,args.original_manifest)

if __name__=='__main__':raise SystemExit(main())
