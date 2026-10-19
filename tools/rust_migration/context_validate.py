"""Compose all native profiles and require fresh source-bound contextual proof."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform

from .context_compare import GOLDEN,RUNTIME_REGISTRATION,ROOT,RUNTIME,compare,core_for_platform
from .context_reference import context_cases,snapshot_state,stderr_errors
from .preparation import PreparedNativeContext
from .reference import Reference
from .table_reference import table_cases
from .table_validate import TABLE_KEYS,TABLE_GATES,_binding_matches,table_fingerprints,table_receipt_errors,validate_tables
from .validate import _digest,_sha,_write,bind_native_release

CONTEXT_KEYS=TABLE_KEYS|{'context_cases','context_oracle','context_registration','runtime_registration','context_assets'}
CONTEXT_GATES=(*TABLE_GATES,'context_release','context_parity')


def context_fingerprints(repo:Path,reference:Reference|None,artifact:Path,snapshot:Path|None)->dict:
    definition=json.loads((repo/'src/ken/embedder/data/code-context-int8.json').read_text())
    state=snapshot_state(snapshot,definition) if snapshot is not None else definition['artifacts']
    return table_fingerprints(repo,reference,artifact)|{
        'context_cases':_sha(GOLDEN.with_name('cases.json')),'context_oracle':_sha(GOLDEN),
        'context_registration':_sha(repo/'src/ken/embedder/data/code-context-int8.json'),
        'runtime_registration':_sha(RUNTIME_REGISTRATION),'context_assets':_digest(state)}


def aggregate_contexts(directory:Path,*,expected_ids:list[str]|None=None,table_case_ids:list[str]|None=None,
                       expected_fingerprints:dict|None=None)->dict:
    rows=[];errors=[]
    expected_ids=[c['id'] for c in context_cases()] if expected_ids is None else expected_ids
    table_case_ids=[c['id'] for c in table_cases()] if table_case_ids is None else table_case_ids
    if expected_fingerprints is None:
        expected_fingerprints=context_fingerprints(ROOT,None,ROOT/'src/ken/embedder/data/ken__static-qwen3-r512-v2.npz',None)
    registration=json.loads(RUNTIME_REGISTRATION.read_text())
    for path in sorted(directory.rglob('summary.json')):
        try:
            row=json.loads(path.read_text())
            if isinstance(row,dict) and row.get('scope')=='context-local':rows.append(row)
        except (OSError,ValueError):errors.append(f'unreadable context receipt: {path}')
    if sorted((r.get('platform',''),r.get('architecture','')) for r in rows)!=[('Darwin','arm64'),('Linux','aarch64')]:
        errors.append('exactly one registered Linux and macOS architecture required')
    signatures=[]
    for row in rows:
        name=row.get('platform');gates=row.get('gates',{});identities=row.get('fingerprints',{})
        if row.get('passed') is not True or row.get('execution_error') or row.get('M2_accepted') is not False:
            errors.append(f'failed context receipt: {name}')
        if any(not isinstance(gates.get(g),dict) or gates[g].get('ran') is not True
               or gates[g].get('passed') is not True for g in CONTEXT_GATES):errors.append(f'incomplete20gates: {name}')
        if (set(identities)!=CONTEXT_KEYS or any(not isinstance(v,str) or len(v)!=64
                or any(c not in '0123456789abcdef' for c in v) for v in identities.values())
                or identities!=expected_fingerprints):errors.append(f'stale or incomplete context identities: {name}')
        signatures.append((identities,row.get('rustc')))
        if not str(row.get('rustc','')).startswith('rustc 1.95.0 '):errors.append(f'wrong compiler: {name}')
        if row.get('case_ids')!=expected_ids:errors.append(f'wrong context histories: {name}')
        base=row.get('table_base',{})
        errors.extend(table_receipt_errors(base,table_case_ids))
        if (base.get('platform')!=name or base.get('architecture')!=row.get('architecture')
                or base.get('rustc')!=row.get('rustc') or base.get('fingerprints')!={k:identities.get(k) for k in TABLE_KEYS}
                or any(base.get('gates',{}).get(g)!=gates.get(g) for g in TABLE_GATES)):
            errors.append(f'context/base proof mismatch: {name}')
        parity=row.get('context_parity',{})
        if not _binding_matches(row.get('context_release',{}),parity):errors.append(f'unbound context executable: {name}')
        if (parity.get('passed') is not True or parity.get('outside_checkout') is not True
                or parity.get('native_children')!=[] or parity.get('dependency_audit',{}).get('passed') is not True
                or parity.get('core_dependency_audit',{}).get('passed') is not True):errors.append(f'missing native context proof: {name}')
        if name=='Linux' and parity.get('exec_attempts')!=1:errors.append('Linux context requires1initialexec')
        try:
            core=core_for_platform(registration,name,row.get('architecture'))
            runtime=parity.get('runtime',{})
            if (parity.get('core_identity')!=core or runtime.get('native_core')!=core
                    or any(runtime.get(k)!=v for k,v in RUNTIME.items())):errors.append(f'wrong actual core/runtime: {name}')
        except ValueError as error:errors.append(str(error))
        stderr=parity.get('stderr')
        if not isinstance(stderr,str) or stderr_errors(stderr,name) or parity.get('stderr_warning_count')!=int(bool(stderr)):
            errors.append(f'invalid or unrecorded context stderr: {name}')
    if signatures and any(s!=signatures[0] for s in signatures):errors.append('context platform source/input/toolchain drift')
    passed=not errors and len(rows)==2
    return {'scope':'context-matrix','passed':passed,'errors':errors,'platforms':[r.get('platform') for r in rows],
            'Context_accepted':passed,'M2_accepted':False,'fingerprints':expected_fingerprints}


def validate_context(repo:Path,reference:Reference,model_probe:Path,potion_snapshot:Path,table_probe:Path,
                     artifact:Path,context:PreparedNativeContext,out:Path,baseline_dir:Path,original_manifest:Path)->int:
    repo=repo.resolve();out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    result={'scope':'context-local','platform':platform.system(),'architecture':platform.machine(),
            'passed':False,'M2_accepted':False,'gates':{}}
    _write(out/'summary.json',result)
    try:
        def fingerprints():return context_fingerprints(repo,reference,artifact,context.snapshot)
        before=fingerprints();result['fingerprints']=before
        validate_tables(repo,reference,model_probe,potion_snapshot,table_probe,artifact,out/'base',baseline_dir,
                        original_manifest,context=context)
        base=json.loads((out/'base/summary.json').read_text())
        result.update(table_base=base,gates=dict(base.get('gates',{})),rustc=base.get('rustc'))
        if base.get('execution_error'):result['execution_error']=base['execution_error']
        binding=(bind_native_release(repo,context.probe,'context_probe') if result['gates'].get('release',{}).get('passed') is True
                 else {'ran':False,'passed':False,'error':'fresh release build failed'})
        result['context_release']=binding;result['gates']['context_release']=binding
        if binding['passed']:
            parity=compare(reference,context.probe,context.snapshot,context.library,out/'context-parity')
            result.update(context_parity=parity,case_ids=parity.get('case_ids',[]))
            result['gates']['context_parity']={'ran':True,'passed':parity['passed'] and _binding_matches(binding,parity)
                and result['case_ids']==[c['id'] for c in context_cases()]}
        if before!=fingerprints():result['execution_error']='context source/input drift during validation'
        if base.get('fingerprints')!={k:before[k] for k in TABLE_KEYS}:result['execution_error']='base source/input drift'
    except (OSError,ValueError,KeyError,TypeError,IndexError) as error:result['execution_error']=f'{type(error).__name__}: {error}'
    result['errors']=(['execution_error'] if result.get('execution_error') else [])+[
        g for g in CONTEXT_GATES if result['gates'].get(g,{}).get('ran') is not True or result['gates'][g].get('passed') is not True]
    result['passed']=not result['errors'];result['Context_local_accepted']=result['passed']
    _write(out/'summary.json',result)
    return int(not result['passed'])


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope',choices=['local','matrix'],default='local')
    parser.add_argument('--platform-receipts',type=Path)
    names=['reference','model-probe','potion-snapshot','table-probe','artifact','native','snapshot','library','baseline-dir','original-manifest']
    for name in names:parser.add_argument('--'+name,type=Path)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    if args.scope=='matrix':
        if not args.platform_receipts:parser.error('matrix requires platform-receipts')
        result=aggregate_contexts(args.platform_receipts);_write(args.out/'summary.json',result)
        print(json.dumps({'passed':result['passed'],'errors':result['errors']}));return int(not result['passed'])
    if not all(getattr(args,name.replace('-','_')) for name in names):parser.error('local requires all explicit model/runtime/baseline inputs')
    return validate_context(Path.cwd(),Reference.load(args.reference),args.model_probe,args.potion_snapshot,
        args.table_probe,args.artifact,PreparedNativeContext(args.snapshot,args.library,args.native),args.out,
        args.baseline_dir,args.original_manifest)


if __name__=='__main__':raise SystemExit(main())
