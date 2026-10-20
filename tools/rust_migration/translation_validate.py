"""Compose26 fresh native gates; translation acceptance never closes all M2."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import platform
import subprocess

from .compare import _differences
from .ettin_reference import ettin_cases, source_state
from .ettin_validate import ETTIN_KEYS, ETTIN_GATES, ettin_fingerprints, ettin_receipt_errors, validate_ettin
from .preparation import PreparedNativeFastEmbed,fastembed_environment,PreparedNativeStorage,storage_environment
from .preparation import PreparedNativeContext, PreparedNativeEttin, PreparedNativeTranslation, PreparedTranslationBuild, translation_environment
from .reference import Reference
from .table_validate import _binding_matches
from .translation_build import build_proof, inspect_prerequisites, proof_errors
from .translation_compare import GOLDEN, RAW_GOLDEN, ROOT, RUNTIME, compare, native_identity, preparation_errors, select_oracle
from .translation_reference import translation_cases
from .validate import _digest, _sha, _write, bind_native_release

TRANSLATION_KEYS=ETTIN_KEYS|{'translation_cases','translation_oracle','translation_raw_oracle',
    'translation_registration','translation_source_assets','translation_prepared_assets'}
TRANSLATION_GATES=(*ETTIN_GATES,'translation_release','translation_preparation','translation_parity')


def translation_fingerprints(repo:Path,reference:Reference|None,artifact:Path,snapshot:Path|None,
                             ettin_source:Path|None,source:Path|None)->dict:
    registration=repo/'src/ken/embedder/data/es-en-ct2-int8.json';definition=json.loads(registration.read_text())
    assets=source_state(source,definition['source']) if source is not None else definition['source']['artifacts']
    return ettin_fingerprints(repo,reference,artifact,snapshot,ettin_source)|{
        'translation_cases':_sha(GOLDEN.with_name('cases.json')),'translation_oracle':_sha(GOLDEN),
        'translation_raw_oracle':_sha(RAW_GOLDEN),'translation_registration':_sha(registration),
        'translation_source_assets':_digest(assets),'translation_prepared_assets':_digest(definition['derived']['artifacts'])}


def translation_receipt_errors(row:dict,expected_ids:list[str],fingerprints:dict)->list[str]:
    errors=[];system=row.get('platform');architecture=row.get('architecture');gates=row.get('gates',{});identities=row.get('fingerprints',{})
    if (row.get('scope')!='translation-local' or row.get('passed') is not True or row.get('execution_error')
            or row.get('M2_accepted') is not False):errors.append('failed translation receipt')
    if any(not isinstance(gates.get(gate),dict) or gates[gate].get('ran') is not True
           or gates[gate].get('passed') is not True for gate in TRANSLATION_GATES):errors.append('incomplete26gates')
    if (set(identities)!=TRANSLATION_KEYS or identities!=fingerprints or any(not isinstance(v,str) or len(v)!=64
            or any(c not in '0123456789abcdef' for c in v) for v in identities.values())):
        errors.append('stale or incomplete translation source/input fingerprints')
    if not str(row.get('rustc','')).startswith('rustc 1.95.0 '):errors.append('unregistered Rust compiler')
    if row.get('case_ids')!=expected_ids:errors.append('wrong translation history coverage')
    base=row.get('ettin_base',{})
    errors.extend(ettin_receipt_errors(base,[c['id'] for c in ettin_cases()],
        {k:identities.get(k) for k in ETTIN_KEYS}))
    if (base.get('platform')!=system or base.get('architecture')!=architecture or base.get('rustc')!=row.get('rustc')
            or any(base.get('gates',{}).get(gate)!=gates.get(gate) for gate in ETTIN_GATES)):
        errors.append('translation/Ettin base proof mismatch')
    binding=row.get('translation_release',{});parity=row.get('translation_parity',{})
    if not _binding_matches(binding,parity) or gates.get('translation_release')!=binding:
        errors.append('translation executable is not bound to fresh release')
    errors.extend(proof_errors(binding.get('native_build'),system,architecture))
    if (parity.get('format')!='ken-translation-parity/1' or parity.get('passed') is not True or parity.get('errors')!=[]
            or parity.get('M2_accepted') is not False or parity.get('native_exit')!=0
            or type(parity.get('native_wall_ns')) is not int or parity['native_wall_ns']<=0
            or parity.get('outside_checkout') is not True or parity.get('native_children')!=[]
            or parity.get('dependency_audit',{}).get('passed') is not True or parity.get('dependency_audit',{}).get('errors')!=[]
            or parity.get('stderr')!='' or parity.get('case_ids')!=expected_ids):errors.append('incomplete native translation process proof')
    if parity.get('platform')!=system or parity.get('architecture')!=architecture:errors.append('translation process platform mismatch')
    if system=='Linux' and parity.get('exec_attempts')!=1:errors.append('Linux translation requires exactly1exec')
    for key,identity in [('oracle_sha256','translation_oracle'),('raw_oracle_sha256','translation_raw_oracle')]:
        if parity.get(key)!=identities.get(identity):errors.append('translation oracle fingerprint mismatch')
    golden=select_oracle(json.loads(GOLDEN.read_text()),system,architecture)
    errors.extend(_differences(RUNTIME,parity.get('runtime'),'runtime'))
    errors.extend(_differences(native_identity(system),parity.get('native_identity'),'native_identity'))
    errors.extend(_differences(golden['oracle']['runtime'],parity.get('reference_runtime'),'reference_runtime'))
    errors.extend(preparation_errors(golden,parity.get('preparation')))
    return errors


def aggregate_translations(directory:Path,*,expected_ids:list[str]|None=None,expected_fingerprints:dict|None=None)->dict:
    expected_ids=[c['id'] for c in translation_cases()] if expected_ids is None else expected_ids
    if expected_fingerprints is None:
        expected_fingerprints=translation_fingerprints(ROOT,None,ROOT/'src/ken/embedder/data/ken__static-qwen3-r512-v2.npz',None,None,None)
    rows=[];errors=[]
    for path in sorted(directory.rglob('summary.json')):
        try:
            row=json.loads(path.read_text())
            if isinstance(row,dict) and row.get('scope')=='translation-local':rows.append(row)
        except (OSError,ValueError):errors.append('unreadable translation receipt: '+str(path))
    if sorted((r.get('platform',''),r.get('architecture','')) for r in rows)!=[('Darwin','arm64'),('Linux','aarch64')]:
        errors.append('exactly one registered macOS and Linux translation receipt required')
    signatures=[]
    for row in rows:
        try:errors.extend(translation_receipt_errors(row,expected_ids,expected_fingerprints))
        except (ValueError,TypeError,KeyError,AttributeError,IndexError) as error:errors.append('malformed translation receipt: '+str(error))
        signatures.append((row.get('fingerprints',{}),row.get('rustc')))
    if signatures and any(s!=signatures[0] for s in signatures):errors.append('translation platform source/input/toolchain drift')
    passed=not errors and len(rows)==2
    return {'scope':'translation-matrix','passed':passed,'errors':errors,'platforms':[r.get('platform') for r in rows],
        'Translation_accepted':passed,'M2_accepted':False,'fingerprints':expected_fingerprints}


def _build_inputs(translation:PreparedNativeTranslation)->PreparedTranslationBuild:
    if translation.build is not None:return translation.build
    env=translation_environment(translation)
    if 'CMAKE' not in env:raise ValueError('explicit prepared CMake required')
    prefix=None
    if platform.system()=='Linux':
        if any(k not in env for k in ['DEP_OPENBLAS_LIBRARY','DEP_OPENBLAS_INCLUDE','PKG_CONFIG_PATH']):
            raise ValueError('all explicit Linux OpenBLAS build prerequisites required')
        prefix=Path(env['DEP_OPENBLAS_LIBRARY']).parent
        if any(env.get(k)!=v for k,v in PreparedTranslationBuild(Path(env['CMAKE']),prefix).environment().items()):
            raise ValueError('inconsistent prepared Linux OpenBLAS paths')
    return PreparedTranslationBuild(Path(env['CMAKE']),prefix)


def validate_translation(repo:Path,reference:Reference,model_probe:Path,potion_snapshot:Path,table_probe:Path,artifact:Path,
                         context:PreparedNativeContext,ettin:PreparedNativeEttin,translation:PreparedNativeTranslation,
                         out:Path,baseline_dir:Path,original_manifest:Path,*,policy_probe:Path|None=None,storage:PreparedNativeStorage|None=None,fastembed:PreparedNativeFastEmbed|None=None)->int:
    repo=repo.resolve();out=out.resolve();out.mkdir(parents=True,exist_ok=True)
    result={'scope':'translation-local','platform':platform.system(),'architecture':platform.machine(),
        'passed':False,'M2_accepted':False,'gates':{}}
    _write(out/'summary.json',result)
    try:
        native_build=_build_inputs(translation)
        translation=replace(translation,build=native_build)
        initial_inputs=inspect_prerequisites(native_build)
        def fingerprints():return translation_fingerprints(repo,reference,artifact,context.snapshot,ettin.source,translation.source)
        before=fingerprints();result['fingerprints']=before
        validate_ettin(repo,reference,model_probe,potion_snapshot,table_probe,artifact,context,ettin,out/'base',
            baseline_dir,original_manifest,translation=translation,policy_probe=policy_probe,storage=storage,fastembed=fastembed)
        base=json.loads((out/'base/summary.json').read_text())
        result.update(ettin_base=base,gates=dict(base.get('gates',{})),rustc=base.get('rustc'))
        if base.get('execution_error'):result['execution_error']=base['execution_error']
        binding=(bind_native_release(repo,translation.probe,'translation_probe') if result['gates'].get('release',{}).get('passed') is True
                 else {'ran':False,'passed':False,'error':'fresh release build failed'})
        if binding['passed']:
            logs=[p for p in (out/'base').rglob('release.log') if _sha(p)==base['gates']['release'].get('sha256')]
            if len(logs)!=1:raise ValueError('one authenticated current release build log required')
            proof=build_proof(repo,logs[0],native_build)
            if {k:proof[k] for k in ['cmake','openblas']}!=initial_inputs:raise ValueError('native build prerequisites changed during validation')
            binding['native_build']=proof
        result['translation_release']=binding;result['gates']['translation_release']=binding
        if binding['passed']:
            parity=compare(reference,translation.probe,translation.source,out/'translation-parity')
            result.update(translation_parity=parity,case_ids=parity.get('case_ids',[]))
            bound=parity.get('passed') is True and _binding_matches(binding,parity)
            golden=select_oracle(json.loads(GOLDEN.read_text()),result['platform'],result['architecture'])
            result['gates']['translation_preparation']={'ran':True,'passed':bound and not preparation_errors(golden,parity.get('preparation'))}
            result['gates']['translation_parity']={'ran':True,'passed':bound and result['case_ids']==[c['id'] for c in translation_cases()]}
        if before!=fingerprints():result['execution_error']='translation source/input drift during validation'
        if base.get('fingerprints')!={k:before[k] for k in ETTIN_KEYS}:result['execution_error']='translation/Ettin base source/input drift'
    except (OSError,ValueError,KeyError,TypeError,IndexError,subprocess.SubprocessError) as error:
        result['execution_error']=f'{type(error).__name__}: {error}'
    result['errors']=(['execution_error'] if result.get('execution_error') else [])+[
        gate for gate in TRANSLATION_GATES if result['gates'].get(gate,{}).get('ran') is not True or result['gates'][gate].get('passed') is not True]
    result['passed']=not result['errors'];result['Translation_local_accepted']=result['passed']
    _write(out/'summary.json',result)
    return int(not result['passed'])


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope',choices=['local','matrix'],default='local');parser.add_argument('--platform-receipts',type=Path)
    names=['reference','model-probe','potion-snapshot','table-probe','artifact','context-probe','context-snapshot','library',
           'ettin-probe','ettin-source','native','source','baseline-dir','original-manifest']
    for name in names+['cmake','openblas-prefix']:parser.add_argument('--'+name,type=Path)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    if args.scope=='matrix':
        if not args.platform_receipts:parser.error('matrix requires platform-receipts')
        result=aggregate_translations(args.platform_receipts);_write(args.out/'summary.json',result)
        print(json.dumps({'passed':result['passed'],'errors':result['errors']}));return int(not result['passed'])
    if not all(getattr(args,name.replace('-','_')) for name in names):parser.error('local requires all explicit model/runtime/baseline inputs')
    build=PreparedTranslationBuild(args.cmake,args.openblas_prefix) if args.cmake is not None else None
    return validate_translation(Path.cwd(),Reference.load(args.reference),args.model_probe,args.potion_snapshot,args.table_probe,args.artifact,
        PreparedNativeContext(args.context_snapshot,args.library,args.context_probe),PreparedNativeEttin(args.ettin_source,args.ettin_probe),
        PreparedNativeTranslation(args.source,args.native,build),args.out,args.baseline_dir,args.original_manifest)


if __name__=='__main__':raise SystemExit(main())
