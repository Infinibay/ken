"""Compose FastEmbed's three gates with the complete current storage chain."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import re
import subprocess

from .fastembed_compare import ROOT, coverage_errors, native_producer, compare_fastembed
from .fastembed_ownership import MODELS, verify_fastembed_ownership
from .fastembed_reference import catalogue_snapshots
from .preparation import (PreparedNativeContext, PreparedNativeEttin, PreparedNativeTranslation,
    PreparedTranslationBuild, PreparedNativeStorage, PreparedNativeFastEmbed)
from .reference import Reference
from .storage_reference import storage_cases
from .storage_validate import STORAGE_GATES, STORAGE_KEYS, storage_fingerprints, storage_receipt_errors, validate_storage
from .table_validate import _binding_matches
from .validate import _digest, _sha, _write, bind_native_release

ORIGINAL=ROOT/'docs/validation/rust-migration-2026-10-20/m2-fastembed'
REGISTRY=ROOT/'crates/ken-models/resources/fastembed-catalog.json'
FASTEMBED_GATES=(*STORAGE_GATES,'fastembed_release','fastembed_parity','fastembed_ownership')
FASTEMBED_KEYS=STORAGE_KEYS|{'fastembed_registry','fastembed_cases','fastembed_oracle','fastembed_source_assets'}


def fastembed_input_fingerprints()->dict:
    catalogue=json.loads(REGISTRY.read_bytes())
    return {'fastembed_registry':_sha(REGISTRY),'fastembed_cases':_sha(ORIGINAL/'cases.json'),
        'fastembed_oracle':_digest([{'path':p.relative_to(ORIGINAL).as_posix(),'sha256':_sha(p)}
            for p in sorted(ORIGINAL.rglob('*')) if p.is_file()]),
        'fastembed_source_assets':_digest(catalogue_snapshots(catalogue))}


def fastembed_fingerprints(repo:Path,reference,artifact:Path,snapshot:Path|None,
                          ettin_source:Path|None,translation_source:Path|None)->dict:
    return storage_fingerprints(repo,reference,artifact,snapshot,ettin_source,translation_source)|fastembed_input_fingerprints()


def fastembed_receipt_errors(row:dict,fingerprints:dict)->list[str]:
    from .context_compare import core_for_platform,RUNTIME_REGISTRATION
    errors=[]
    try:
        if (row.get('scope')!='fastembed-local' or row.get('passed') is not True
                or row.get('execution_error') or row.get('M2_accepted') is not False
                or type(row.get('synthetic_fixture')) is not bool):errors.append('failed FastEmbed receipt')
        gates=row.get('gates',{});identities=row.get('fingerprints',{})
        if set(gates)!=set(FASTEMBED_GATES) or any(type(gates[k]) is not dict or gates[k].get('ran') is not True
                or gates[k].get('passed') is not True for k in FASTEMBED_GATES):errors.append('incomplete34FastEmbed gates')
        if (set(identities)!=FASTEMBED_KEYS or identities!=fingerprints
                or any(type(v) is not str or not re.fullmatch('[0-9a-f]{64}',v) for v in identities.values())):
            errors.append('stale or incomplete33FastEmbed fingerprints')
        if not str(row.get('rustc','')).startswith('rustc 1.95.0 '):errors.append('unregistered FastEmbed compiler')
        system,architecture=row['platform'],row['architecture']
        core=core_for_platform(json.loads(RUNTIME_REGISTRATION.read_bytes()),system,architecture)
        base=row['storage_base']
        errors+=storage_receipt_errors(base,[c['id'] for c in storage_cases()],{k:identities[k] for k in STORAGE_KEYS})
        if (any(base.get(k)!=row.get(k) for k in ['platform','architecture','rustc','synthetic_fixture'])
                or any(base['gates'].get(k)!=gates.get(k) for k in STORAGE_GATES)):
            errors.append('FastEmbed/storage base proof mismatch')
        parity=row['fastembed_parity'];ownership=row['fastembed_ownership'];binding=row['fastembed_release']
        catalogue=json.loads(REGISTRY.read_bytes());cases=json.loads((ORIGINAL/'cases.json').read_bytes())
        errors+=coverage_errors(catalogue,cases,[m['model'] for m in parity['models']])
        if parity.get('case_ids')!=[c['id'] for c in cases]:errors.append('wrong FastEmbed case coverage')
        if not _binding_matches(binding,parity) or gates.get('fastembed_release')!=binding:
            errors.append('FastEmbed probe is not bound to fresh release')
        if [m['model'] for m in ownership['models']]!=MODELS:errors.append('all five ownership families required')
        for proof,format in [(parity,'ken-fastembed-parity/1'),(ownership,'ken-fastembed-ownership/1')]:
            if (proof.get('format')!=format or proof.get('passed') is not True or proof.get('errors')!=[]
                    or proof.get('M2_accepted') is not False or proof.get('FastEmbed_accepted') is not False
                    or proof.get('platform')!=system or proof.get('architecture')!=architecture
                    or proof.get('producer')!=native_producer() or proof.get('core_identity')!=core
                    or proof.get('native_sha256')!=binding.get('built_sha256')
                    or proof.get('registry_sha256')!=identities['fastembed_registry']
                    or any(m.get('errors')!=[] for m in proof['models'])):errors.append('incomplete native FastEmbed process provenance')
        if (parity.get('cases_sha256')!=identities['fastembed_cases']
                or parity.get('reference_fingerprint')!=base['storage_parity']['reference_fingerprint']):
            errors.append('FastEmbed original identity mismatch')
        wanted={name:_sha(Path(__file__).with_name(name)) for name in ['fastembed_compare.py','fastembed_process.py']}
        if parity.get('tooling')!=wanted:errors.append('FastEmbed controller source drift')
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError) as error:
        errors.append('malformed FastEmbed receipt: '+str(error))
    return errors


def aggregate_fastembed(directory:Path,*,expected_fingerprints:dict|None=None)->dict:
    from .fastembed_evidence import execution_errors
    def current():return fastembed_fingerprints(ROOT,None,ROOT/'src/ken/embedder/data/ken__static-qwen3-r512-v2.npz',None,None,None)
    before=current() if expected_fingerprints is None else expected_fingerprints
    rows=[];errors=[]
    for path in sorted(directory.rglob('summary.json')):
        try:
            row=json.loads(path.read_bytes())
            if type(row) is dict and row.get('scope')=='fastembed-local':rows.append((path.parent,row))
        except (OSError,ValueError):errors.append('unreadable FastEmbed receipt: '+str(path))
    if sorted((r.get('platform',''),r.get('architecture','')) for _,r in rows)!=[('Darwin','arm64'),('Linux','aarch64')]:
        errors.append('exactly one registered macOS and Linux FastEmbed receipt required')
    signatures=[]
    for root,row in rows:
        if row.get('synthetic_fixture') is not False:
            errors.append('synthetic FastEmbed fixtures cannot certify acceptance');continue
        errors+=fastembed_receipt_errors(row,before)
        errors+=execution_errors(root,row)
        signatures.append((row.get('fingerprints'),row.get('rustc')))
    if signatures and any(s!=signatures[0] for s in signatures):errors.append('FastEmbed platform source/input/toolchain drift')
    if expected_fingerprints is None and current()!=before:errors.append('current FastEmbed inputs changed during aggregation')
    passed=not errors and len(rows)==2
    return {'scope':'fastembed-matrix','passed':passed,'errors':errors,'platforms':[r['platform'] for _,r in rows],
        'FastEmbed_accepted':passed,'Storage_accepted':passed,'M2_accepted':False,'fingerprints':before}


def validate_fastembed(repo:Path,reference:Reference,model_probe:Path,potion_snapshot:Path,table_probe:Path,artifact:Path,
        context:PreparedNativeContext,ettin:PreparedNativeEttin,translation:PreparedNativeTranslation,
        policy_probe:Path,storage:PreparedNativeStorage,fastembed:PreparedNativeFastEmbed,
        out:Path,baseline_dir:Path,original_manifest:Path)->int:
    from .fastembed_evidence import seal_execution,execution_errors
    repo=repo.resolve();out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    result={'scope':'fastembed-local','synthetic_fixture':False,'platform':platform.system(),'architecture':platform.machine(),
        'passed':False,'M2_accepted':False,'gates':{}}
    _write(out/'summary.json',result)
    try:
        fastembed.environment()
        if not fastembed.probe.is_file() or not os.access(fastembed.probe,os.X_OK):raise ValueError('explicit executable native FastEmbed probe required')
        if _sha(fastembed.registry)!=_sha(REGISTRY) or not fastembed.sources.is_dir():raise ValueError('registered FastEmbed catalogue and sources required')
        def fingerprints():return fastembed_fingerprints(repo,reference,artifact,context.snapshot,ettin.source,translation.source)
        before=fingerprints();result['fingerprints']=before
        validate_storage(repo,reference,model_probe,potion_snapshot,table_probe,artifact,context,ettin,translation,
            policy_probe,storage,out/'base',baseline_dir,original_manifest,fastembed=fastembed)
        base=json.loads((out/'base/summary.json').read_bytes())
        result.update(storage_base=base,gates=dict(base.get('gates',{})),rustc=base.get('rustc'))
        if base.get('execution_error'):result['execution_error']=base['execution_error']
        binding=bind_native_release(repo,fastembed.probe,'fastembed_probe') if result['gates'].get('release',{}).get('passed') is True else {'ran':False,'passed':False,'error':'fresh release build failed'}
        result['fastembed_release']=binding;result['gates']['fastembed_release']=binding
        if binding['passed']:
            parity=compare_fastembed(reference,fastembed,out/'fastembed-parity',library=context.library)
            result['fastembed_parity']=parity
            result['gates']['fastembed_parity']={'ran':True,'passed':parity.get('passed') is True and _binding_matches(binding,parity)}
            ownership=verify_fastembed_ownership(reference,fastembed,out/'fastembed-ownership',library=context.library)
            result['fastembed_ownership']=ownership
            result['gates']['fastembed_ownership']={'ran':True,'passed':ownership.get('passed') is True and _binding_matches(binding,ownership)}
        if before!=fingerprints() or base.get('fingerprints')!={k:before[k] for k in STORAGE_KEYS}:
            result['execution_error']='FastEmbed source/input/base drift during validation'
    except (OSError,ValueError,KeyError,TypeError,IndexError,subprocess.SubprocessError) as error:
        result['execution_error']=f'{type(error).__name__}: {error}'
    result['errors']=(['execution_error'] if result.get('execution_error') else [])+[
        k for k in FASTEMBED_GATES if result['gates'].get(k,{}).get('ran') is not True or result['gates'][k].get('passed') is not True]
    result['passed']=not result['errors']
    if result['passed']:
        result['errors']+=fastembed_receipt_errors(result,result['fingerprints'])
        if not result['errors']:
            try:
                result['execution_artifacts']=seal_execution(out);result['errors']+=execution_errors(out,result)
            except (OSError,ValueError,TypeError) as error:result['errors'].append('FastEmbed evidence: '+str(error))
        result['passed']=not result['errors']
    result['FastEmbed_local_accepted']=result['passed']
    _write(out/'summary.json',result);return int(not result['passed'])


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope',choices=['local','matrix'],default='local')
    parser.add_argument('--platform-receipts',type=Path);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--acquire-fastembed-sources',action='store_true',help='use and remove owned per-model source leases')
    names=['reference','model-probe','potion-snapshot','table-probe','artifact','context-probe','context-snapshot',
        'library','ettin-probe','ettin-source','translation-probe','translation-source','policy-probe','storage-probe',
        'fastembed-probe','fastembed-sources','fastembed-registry','baseline-dir','original-manifest','cmake','openblas-prefix']
    for name in names:parser.add_argument('--'+name,type=Path)
    args=parser.parse_args()
    if args.scope=='matrix':
        if args.platform_receipts is None:parser.error('matrix requires --platform-receipts')
        result=aggregate_fastembed(args.platform_receipts);_write(args.out/'summary.json',result);return int(not result['passed'])
    if any(getattr(args,n.replace('-','_')) is None for n in names if n not in ['cmake','openblas-prefix']):parser.error('local requires every native input and frozen reference/baseline')
    build=PreparedTranslationBuild(args.cmake,args.openblas_prefix) if args.cmake is not None else None
    return validate_fastembed(Path.cwd(),Reference.load(args.reference),args.model_probe,args.potion_snapshot,args.table_probe,args.artifact,
        PreparedNativeContext(args.context_snapshot,args.library,args.context_probe),PreparedNativeEttin(args.ettin_source,args.ettin_probe),
        PreparedNativeTranslation(args.translation_source,args.translation_probe,build),args.policy_probe,PreparedNativeStorage(args.storage_probe),
        PreparedNativeFastEmbed(args.fastembed_probe,args.fastembed_sources,args.fastembed_registry,acquire=args.acquire_fastembed_sources),args.out,args.baseline_dir,args.original_manifest)


if __name__=='__main__':raise SystemExit(main())
