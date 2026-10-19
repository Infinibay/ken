"""Compose the complete native profiles and require fresh Ettin preparation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform

from .compare import _differences
from .context_validate import CONTEXT_GATES,CONTEXT_KEYS,context_fingerprints,context_receipt_errors,validate_context
from .ettin_compare import GOLDEN,ROOT,RUNTIME,RUNTIME_REGISTRATION,compare,core_for_platform,preparation_errors,select_oracle
from .ettin_reference import ettin_cases,source_state,stderr_errors
from .preparation import PreparedNativeContext,PreparedNativeEttin,PreparedNativeTranslation
from .reference import Reference
from .table_validate import _binding_matches
from .validate import _digest,_sha,_write,bind_native_release

ETTIN_KEYS=CONTEXT_KEYS|{'ettin_cases','ettin_oracle','ettin_registration','ettin_source_assets','ettin_prepared_assets'}
ETTIN_GATES=(*CONTEXT_GATES,'ettin_release','ettin_preparation','ettin_parity')


def ettin_fingerprints(repo:Path,reference:Reference|None,artifact:Path,snapshot:Path|None,source:Path|None)->dict:
    registration=repo/'src/ken/embedder/data/ettin-68m-fp32.json'
    definition=json.loads(registration.read_text())
    original=definition['source']['artifacts']
    assets=source_state(source,definition['source']) if source is not None else original
    prepared={name:original[name] for name in ['tokenizer.json','config.json','tokenizer_config.json']}
    prepared['model.onnx']={key:definition['graph'][key] for key in ['bytes','sha256']}
    return context_fingerprints(repo,reference,artifact,snapshot)|{
        'ettin_cases':_sha(GOLDEN.with_name('cases.json')),'ettin_oracle':_sha(GOLDEN),
        'ettin_registration':_sha(registration),'ettin_source_assets':_digest(assets),
        'ettin_prepared_assets':_digest(prepared)}


def ettin_receipt_errors(row:dict,expected_ids:list[str],fingerprints:dict)->list[str]:
    errors=[];name=row.get('platform');identities=row.get('fingerprints',{});gates=row.get('gates',{})
    if (row.get('scope')!='ettin-local' or row.get('passed') is not True or row.get('execution_error')
            or row.get('M2_accepted') is not False):errors.append(f'failed Ettin receipt: {name}')
    if any(not isinstance(gates.get(gate),dict) or gates[gate].get('ran') is not True
           or gates[gate].get('passed') is not True for gate in ETTIN_GATES):errors.append(f'incomplete23gates: {name}')
    if (set(identities)!=ETTIN_KEYS or any(not isinstance(value,str) or len(value)!=64
            or any(c not in '0123456789abcdef' for c in value) for value in identities.values())
            or identities!=fingerprints):errors.append(f'stale or incomplete Ettin identities: {name}')
    if not str(row.get('rustc','')).startswith('rustc 1.95.0 '):errors.append(f'wrong compiler: {name}')
    if row.get('case_ids')!=expected_ids:errors.append(f'wrong Ettin histories: {name}')
    base=row.get('context_base',{})
    errors.extend(context_receipt_errors(base,expected_fingerprints={key:identities.get(key) for key in CONTEXT_KEYS}))
    if (base.get('platform')!=name or base.get('architecture')!=row.get('architecture')
            or base.get('rustc')!=row.get('rustc')
            or any(base.get('gates',{}).get(gate)!=gates.get(gate) for gate in CONTEXT_GATES)):
        errors.append(f'Ettin/context base proof mismatch: {name}')
    parity=row.get('ettin_parity',{})
    if not _binding_matches(row.get('ettin_release',{}),parity):errors.append(f'unbound Ettin executable: {name}')
    if (parity.get('format')!='ken-ettin-parity/1' or parity.get('passed') is not True or parity.get('errors')!=[]
            or parity.get('M2_accepted') is not False or parity.get('native_exit')!=0
            or type(parity.get('native_wall_ns')) is not int or parity['native_wall_ns']<=0
            or parity.get('outside_checkout') is not True or parity.get('native_children')!=[]
            or parity.get('dependency_audit',{}).get('passed') is not True
            or parity.get('core_dependency_audit',{}).get('passed') is not True
            or parity.get('case_ids')!=expected_ids):errors.append(f'missing native Ettin proof: {name}')
    if parity.get('platform')!=name or parity.get('architecture')!=row.get('architecture'):
        errors.append(f'Ettin process platform mismatch: {name}')
    if name=='Linux' and parity.get('exec_attempts')!=1:errors.append('Linux Ettin requires1initialexec')
    try:
        core=core_for_platform(json.loads(RUNTIME_REGISTRATION.read_text()),name,row.get('architecture'))
        golden=select_oracle(json.loads(GOLDEN.read_text()),name,row.get('architecture'))
        errors.extend(_differences(core,parity.get('core_identity'),'core_identity'))
        errors.extend(_differences(RUNTIME|{'native_core':core},parity.get('runtime'),'runtime'))
        errors.extend(_differences(golden['oracle']['runtime'],parity.get('reference_runtime'),'reference_runtime'))
        errors.extend(preparation_errors(golden,parity.get('preparation')))
    except (ValueError,KeyError,TypeError) as error:errors.append(str(error))
    stderr=parity.get('stderr')
    if (not isinstance(stderr,str) or stderr_errors(stderr,name)
            or type(parity.get('stderr_warning_count')) is not int
            or parity['stderr_warning_count']!=int(bool(stderr))):errors.append(f'invalid or unrecorded Ettin stderr: {name}')
    return errors


def aggregate_ettins(directory:Path,*,expected_ids:list[str]|None=None,expected_fingerprints:dict|None=None)->dict:
    rows=[];errors=[]
    expected_ids=[case['id'] for case in ettin_cases()] if expected_ids is None else expected_ids
    if expected_fingerprints is None:
        expected_fingerprints=ettin_fingerprints(ROOT,None,ROOT/'src/ken/embedder/data/ken__static-qwen3-r512-v2.npz',None,None)
    for path in sorted(directory.rglob('summary.json')):
        try:
            row=json.loads(path.read_text())
            if isinstance(row,dict) and row.get('scope')=='ettin-local':rows.append(row)
        except (OSError,ValueError):errors.append(f'unreadable Ettin receipt: {path}')
    if sorted((row.get('platform',''),row.get('architecture','')) for row in rows)!=[('Darwin','arm64'),('Linux','aarch64')]:
        errors.append('exactly one registered Linux and macOS architecture required')
    signatures=[]
    for row in rows:
        try:errors.extend(ettin_receipt_errors(row,expected_ids,expected_fingerprints))
        except (TypeError,KeyError,AttributeError,ValueError) as error:errors.append(f'malformed Ettin receipt: {error}')
        signatures.append((row.get('fingerprints',{}),row.get('rustc')))
    if signatures and any(value!=signatures[0] for value in signatures):errors.append('Ettin platform source/input/toolchain drift')
    passed=not errors and len(rows)==2
    return {'scope':'ettin-matrix','passed':passed,'errors':errors,'platforms':[row.get('platform') for row in rows],
        'Ettin_accepted':passed,'M2_accepted':False,'fingerprints':expected_fingerprints}


def validate_ettin(repo:Path,reference:Reference,model_probe:Path,potion_snapshot:Path,table_probe:Path,artifact:Path,
                   context:PreparedNativeContext,ettin:PreparedNativeEttin,out:Path,baseline_dir:Path,original_manifest:Path,*,translation:PreparedNativeTranslation|None=None,policy_probe:Path|None=None)->int:
    repo=repo.resolve();out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    result={'scope':'ettin-local','platform':platform.system(),'architecture':platform.machine(),
        'passed':False,'M2_accepted':False,'gates':{}}
    _write(out/'summary.json',result)
    try:
        def fingerprints():return ettin_fingerprints(repo,reference,artifact,context.snapshot,ettin.source)
        before=fingerprints();result['fingerprints']=before
        validate_context(repo,reference,model_probe,potion_snapshot,table_probe,artifact,context,out/'base',
                         baseline_dir,original_manifest,ettin=ettin,translation=translation,policy_probe=policy_probe)
        base=json.loads((out/'base/summary.json').read_text())
        result.update(context_base=base,gates=dict(base.get('gates',{})),rustc=base.get('rustc'))
        if base.get('execution_error'):result['execution_error']=base['execution_error']
        binding=(bind_native_release(repo,ettin.probe,'ettin_probe') if result['gates'].get('release',{}).get('passed') is True
                 else {'ran':False,'passed':False,'error':'fresh release build failed'})
        result['ettin_release']=binding;result['gates']['ettin_release']=binding
        if binding['passed']:
            parity=compare(reference,ettin.probe,ettin.source,context.library,out/'ettin-parity')
            result.update(ettin_parity=parity,case_ids=parity.get('case_ids',[]))
            bound=parity.get('passed') is True and _binding_matches(binding,parity)
            golden=select_oracle(json.loads(GOLDEN.read_text()),result['platform'],result['architecture'])
            result['gates']['ettin_preparation']={'ran':True,'passed':bound and not preparation_errors(golden,parity.get('preparation'))}
            result['gates']['ettin_parity']={'ran':True,'passed':bound and result['case_ids']==[case['id'] for case in ettin_cases()]}
        if before!=fingerprints():result['execution_error']='Ettin source/input drift during validation'
        if base.get('fingerprints')!={key:before[key] for key in CONTEXT_KEYS}:result['execution_error']='base source/input drift'
    except (OSError,ValueError,KeyError,TypeError,IndexError) as error:result['execution_error']=f'{type(error).__name__}: {error}'
    result['errors']=(['execution_error'] if result.get('execution_error') else [])+[
        gate for gate in ETTIN_GATES if result['gates'].get(gate,{}).get('ran') is not True or result['gates'][gate].get('passed') is not True]
    result['passed']=not result['errors'];result['Ettin_local_accepted']=result['passed']
    _write(out/'summary.json',result)
    return int(not result['passed'])


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope',choices=['local','matrix'],default='local')
    parser.add_argument('--platform-receipts',type=Path)
    names=['reference','model-probe','potion-snapshot','table-probe','artifact','context-probe','context-snapshot',
           'library','native','source','baseline-dir','original-manifest']
    for name in names:parser.add_argument('--'+name,type=Path)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    if args.scope=='matrix':
        if not args.platform_receipts:parser.error('matrix requires platform-receipts')
        result=aggregate_ettins(args.platform_receipts);_write(args.out/'summary.json',result)
        print(json.dumps({'passed':result['passed'],'errors':result['errors']}));return int(not result['passed'])
    if not all(getattr(args,name.replace('-','_')) for name in names):parser.error('local requires all explicit model/runtime/baseline inputs')
    return validate_ettin(Path.cwd(),Reference.load(args.reference),args.model_probe,args.potion_snapshot,args.table_probe,
        args.artifact,PreparedNativeContext(args.context_snapshot,args.library,args.context_probe),PreparedNativeEttin(args.source,args.native),
        args.out,args.baseline_dir,args.original_manifest)


if __name__=='__main__':raise SystemExit(main())
