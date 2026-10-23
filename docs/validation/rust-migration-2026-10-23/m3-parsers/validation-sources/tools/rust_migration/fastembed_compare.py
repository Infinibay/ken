"""Native FastEmbed: exact inputs/identity/state, fixed per-platform F32 parity."""
from __future__ import annotations

import hashlib,json,math,re
from pathlib import Path

from .fastembed_reference import fastembed_cases,known_original_failure,validate_model_record

ROOT=Path(__file__).resolve().parents[2]
FRAME_FIELDS={'format','id','operation','model','producer','model_fingerprint','assets_fingerprint',
              'constructor_ns','before','state','preparation','elapsed_ns','memory'}


def fingerprint(value:object)->str:
    # Accepted ModelAssets/model declarations use Python's default separators.
    return hashlib.sha256(json.dumps(value,ensure_ascii=True,sort_keys=True,allow_nan=False).encode()).hexdigest()


def native_producer()->dict:
    paths=[*sorted((ROOT/'crates/ken-models/src').rglob('*.rs')),
        ROOT/'Cargo.toml',ROOT/'Cargo.lock',ROOT/'crates/ken-models/Cargo.toml',
        ROOT/'crates/ken-models/examples/fastembed_probe.rs',
        ROOT/'crates/ken-models/examples/support/mod.rs',
        ROOT/'crates/ken-models/examples/support/observed_peak.rs',
        ROOT/'docs/validation/rust-migration-2026-10-18/m2-context/runtime-libraries.json']
    files={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()for path in paths}
    return {'engine':'rust','ken_models':'0.18.0','tokenizers':'0.22.2','ort':'2.0.0-rc.14','api':25,
            'source_sha256':hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            'source_files':len(files)}


def provenance_errors(expected:dict,actual:object)->list[str]:
    return []if type(actual)is dict and actual==expected else['stale or malformed native/source/oracle provenance']


def coverage_errors(catalogue:dict,cases:object,models:object)->list[str]:
    try:
        names=[model['name']for model in catalogue['models']]
        if (catalogue['format']!='ken-fastembed-catalog/1'or len(names)!=30 or len({n.lower()for n in names})!=30
                or models!=names or type(cases)is not list or len(cases)!=300 or cases!=fastembed_cases(names)):
            return ['complete ordered30model/300case catalogue required']
        return []
    except (KeyError,TypeError,AttributeError):return ['malformed catalogue/case coverage']


def _positive(value:object)->bool:return type(value)is int and value>0


def _state(value:object,want:dict,dimension:int)->bool:
    return (type(value)is dict and set(value)=={'device','model_loaded','dim'}
        and type(value['model_loaded'])is bool and type(value['dim'])is int
        and want['dim']in (384,dimension) and value==dict(want,dim=dimension))


def _preparation(frame:dict,definition:dict,core:dict)->bool:
    loaded=frame['state']['model_loaded'];asset=fingerprint(definition['assets'])
    expected={'device':'cpu'if loaded else'unknown','configured_providers':['CPUExecutionProvider']if loaded else[],
        'attempts':[{'providers':['CPUExecutionProvider'],'error':None}]if loaded else[],
        'runtime':core if loaded else None,'model_fingerprint':fingerprint(definition),
        'declared_artifacts_fingerprint':asset,'verified_artifacts_fingerprint':asset if loaded else None,
        'notices':definition['advisories']}
    return type(frame['preparation'])is dict and frame['preparation']==expected


def _shape(value:object)->bool:
    return type(value)is list and all(type(n)is int and n>=0 for n in value)


def _batches(expected:list,actual:object)->bool:
    if type(actual)is not list or len(actual)!=len(expected):return False
    for wanted,got in zip(expected,actual,strict=True):
        if (type(got)is not dict or set(got)!={'inputs','output_shape','output_dtype'}
                or got['output_dtype']!='float32'or not _shape(got['output_shape'])
                or got['output_shape']!=wanted['outputs'][0]['shape']or type(got['inputs'])is not dict
                or set(got['inputs'])!=set(wanted['inputs'])):return False
        for name,tensor in got['inputs'].items():
            want=wanted['inputs'][name]
            if (type(tensor)is not dict or set(tensor)!={'shape','values'}or not _shape(tensor['shape'])
                    or tensor['shape']!=want['shape']or type(tensor['values'])is not list
                    or len(tensor['values'])!=math.prod(tensor['shape'])
                    or any(type(n)is not int or not -(2**63)<=n<2**63 for n in tensor['values'])
                    or tensor['values']!=want['values']):return False
    return True


def _vectors(expected:dict,actual:object,dimension:int,count:int)->bool:
    import numpy as np
    if (type(actual)is not dict or set(actual)!={'shape','vectors_f32le_hex','batches'}
            or not _shape(actual['shape'])or actual['shape']!=[count,dimension]
            or type(actual['vectors_f32le_hex'])is not str
            or re.fullmatch('[0-9a-f]*',actual['vectors_f32le_hex'])is None
            or len(actual['vectors_f32le_hex'])!=count*dimension*8):return False
    want=np.frombuffer(bytes.fromhex(expected['vectors_f32le_hex']),dtype='<f4').astype(np.float64)
    got=np.frombuffer(bytes.fromhex(actual['vectors_f32le_hex']),dtype='<f4').astype(np.float64)
    return bool(np.isfinite(got).all()and got.shape==want.shape and np.all(np.abs(got-want)<=1e-6+1e-6*np.abs(want)))


def _native_known_failure(definition:dict,original:dict,frame:dict,system:str)->bool:
    error=frame.get('error')
    return (known_original_failure(definition,original['error'],system)and type(error)is dict
        and set(error)=={'type','kind','message'}and error['type']=='ModelError'and error['kind']=='inference'
        and type(error['message'])is str and all(marker in error['message']for marker in (
            'GetIndexFromName','Attempting to get index by a name which does not exist:',
            'InsertedPrecisionFreeCast_/encoder/layer.11/attention/output/LayerNorm/Constant_output_0',
            'for node: /embeddings/LayerNorm/Mul/SimplifiedLayerNormFusion/')))


def compare_model(definition:dict,cases:list,original:dict,frames:object,producer:dict,core:dict)->list[str]:
    """Pure comparison; it does not attest that fixture data was executed."""
    try:
        validate_model_record(original,definition,cases)
        name=definition['name'];dimension=definition['dimension']
        ids=[name+':control-cold',*[case['id']for case in cases],name+':control-final']
        if type(frames)is not list or [f.get('id')if type(f)is dict else None for f in frames]!=ids:
            return ['missing, duplicated, reordered or unexpected native histories']
        if len({f['constructor_ns']for f in frames})!=1:return ['one actual constructor required']
        errors=[];peak=0
        for index,frame in enumerate(frames):
            prefix=frame['id'];control=index in (0,len(frames)-1)
            want=original['results'][0]if index==0 else original['results'][-1]if control else original['results'][index-1]
            before=want['before']if index==0 or not control else want['state'];after=before if control else want['state']
            failed=not control and'error'in want
            if (set(frame)!=FRAME_FIELDS|({'error'}if failed else{'result'})or frame['format']!='ken-fastembed-frame/1'
                    or frame['model']!=name or frame['model_fingerprint']!=fingerprint(definition)
                    or frame['assets_fingerprint']!=fingerprint(definition['assets'])or frame['producer']!=producer
                    or not _positive(frame['constructor_ns'])or not _positive(frame['elapsed_ns'])
                    or frame['operation']!=('status'if control else'embed')):
                errors.append(prefix+': native identity/format/operation/producer/measurement mismatch');continue
            if not _state(frame['before'],before,dimension)or not _state(frame['state'],after,dimension):
                errors.append(prefix+': native lazy state or registered dimension mismatch');continue
            if not _preparation(frame,definition,core):errors.append(prefix+': unaccredited preparation/runtime/provider metadata')
            memory=frame['memory']
            if type(memory)is not dict or set(memory)!={'before','after'}:errors.append(prefix+': invalid memory phases')
            else:
                for phase in ('before','after'):
                    sample=memory[phase]
                    if (type(sample)is not dict or set(sample)!={'reported_hwm_bytes','observed_peak_bytes'}
                            or not _positive(sample['reported_hwm_bytes'])):errors.append(prefix+': invalid memory sample');continue
                    peak=max(peak,sample['reported_hwm_bytes'])
                    if type(sample['observed_peak_bytes'])is not int or sample['observed_peak_bytes']!=peak:errors.append(prefix+': false observed memory envelope')
            if control:
                if frame['result']!={'prepared':after['model_loaded']}or type(frame['result']['prepared'])is not bool:errors.append(prefix+': invalid status result')
            elif failed:
                if not _native_known_failure(definition,want,frame,original['platform']):errors.append(prefix+': unregistered or unrelated native error')
            elif (not _vectors(want,frame['result'],dimension,len(cases[index-1]['input']['texts']))
                    or not _batches(want['batches'],frame['result']['batches'])):
                errors.append(prefix+': vectors/tokens/mask/type/output shape differ')
        return errors
    except (KeyError,ValueError,TypeError,IndexError,AttributeError,OverflowError)as error:
        return ['malformed native FastEmbed history: '+str(error)]


def _oracle_inputs(reference,prepared):
    import platform
    from .reference import verify_reference
    from .fastembed_reference import read_chunk
    from .context_compare import core_for_platform,RUNTIME_REGISTRATION
    from .preparation import PreparedNativeFastEmbed
    if not isinstance(prepared,PreparedNativeFastEmbed):raise ValueError('typed PreparedNativeFastEmbed required')
    prepared.environment()
    if verify_reference(reference.root,reference.manifest_path):raise ValueError('frozen original drift')
    base=ROOT/'docs/validation/rust-migration-2026-10-20/m2-fastembed'
    audit=json.loads((base/'reference-snapshot-audit.json').read_bytes())
    for row in audit['source_rows']:
        if hashlib.sha256((reference.root/row['path']).read_bytes()).hexdigest()!=row['sha256']:raise ValueError('original application source drift')
    index=json.loads((base/'reference-index.json').read_bytes());registry=prepared.registry.read_bytes();cases_bytes=(base/'cases.json').read_bytes()
    if hashlib.sha256(registry).hexdigest()!=index['registry_sha256']or hashlib.sha256(cases_bytes).hexdigest()!=index['cases_sha256']:raise ValueError('frozen registry/cases changed')
    catalogue=json.loads(registry);cases=json.loads(cases_bytes)
    if coverage_errors(catalogue,cases,[m['name']for m in catalogue['models']]):raise ValueError('complete frozen corpus required')
    system,architecture=platform.system(),platform.machine();matches=[p for p in index['platforms']if(p['platform'],p['architecture'])==(system,architecture)]
    if len(matches)!=1:raise ValueError('one matching registered original platform required')
    platform_index=matches[0];directory=base/platform_index['directory'];raw=(directory/'index.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=platform_index['index_sha256']:raise ValueError('original platform index changed')
    model_index=json.loads(raw)
    if ([r['model']for r in model_index['models']]!=[m['name']for m in catalogue['models']]
            or model_index['registry_sha256']!=index['registry_sha256']or model_index['cases_sha256']!=index['cases_sha256']):raise ValueError('original index model/source coverage mismatch')
    for name,digest in model_index['tooling'].items():
        if hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()!=digest:raise ValueError('original capture tooling changed')
    core=core_for_platform(json.loads(RUNTIME_REGISTRATION.read_bytes()),system,architecture)
    records=[read_chunk(directory,row['record'])for row in model_index['models']]
    for definition,record in zip(catalogue['models'],records,strict=True):
        validate_model_record(record,definition,[c for c in cases if c['model']==definition['name']])
    return catalogue,cases,records,core


def compare_fastembed(reference,prepared,out:Path,*,library:Path|None=None)->dict:
    """Execute each model in a new native process, never send expected results."""
    import platform,time
    from .fastembed_process import NativeProbeProcess,digest,decode_frames
    from .fastembed_reference import source_state,native_request,write_chunk,read_chunk
    from .model_compare import _audit
    from .preparation import context_environment
    from .fastembed_sources import source_lease
    out=out.resolve();out.mkdir(parents=True,exist_ok=False)
    receipt={'format':'ken-fastembed-parity/1','platform':platform.system(),'architecture':platform.machine(),
        'passed':False,'errors':[],'models':[],'case_ids':[],'FastEmbed_accepted':False,'M2_accepted':False}
    try:
        catalogue,cases,originals,core=_oracle_inputs(reference,prepared)
        if library is None:
            value=context_environment().get('KEN_ORT_LIBRARY')
            if value is None:raise ValueError('explicit prepared native core required')
            library=Path(value)
        if not library.is_absolute()or library.stat().st_size!=core['bytes']or digest(library)!=core['sha256']:raise ValueError('registered native core bytes required')
        native=prepared.probe;producer=native_producer()
        audits={}
        for role,path in [('binary',native),('core',library)]:
            destination=out/(role+'-audit');destination.mkdir();audits[role]=_audit(path,destination)
        if not all(r['passed']for r in audits.values()):raise ValueError('native executable/core dependency audit failed')
        tooling={name:digest(Path(__file__).with_name(name))for name in ['fastembed_compare.py','fastembed_process.py']}
        receipt.update(native_sha256=digest(native),registry_sha256=digest(prepared.registry),
            cases_sha256=digest(ROOT/'docs/validation/rust-migration-2026-10-20/m2-fastembed/cases.json'),
            producer=producer,core_identity=core,dependency_audits=audits,tooling=tooling,
            reference_fingerprint=reference.fingerprint)
        for index,(definition,original)in enumerate(zip(catalogue['models'],originals,strict=True)):
            name=definition['name'];model_cases=[c for c in cases if c['model']==name];destination=out/f'{index:02}';
            with source_lease(prepared,definition,copies=2)as leased:
                before=source_state(leased.sources,definition)
                requests=[{'id':name+':control-cold','operation':'status'},*[native_request(case)for case in model_cases],{'id':name+':control-final','operation':'status'}]
                with NativeProbeProcess(native,prepared.registry,leased.sources,library,name,destination)as process:
                    for request in requests:process.send(request)
                raw=process.stdout.read_text();stderr=process.stderr.read_text();frames=decode_frames(raw)
                errors=compare_model(definition,model_cases,original,frames,producer,core)
                after=source_state(leased.sources,definition)
            if after!=before:errors.append('canonical source changed')
            record={'format':'ken-fastembed-native-record/1','model':name,'requests':requests,'stdout':raw,'stderr':stderr,
                'process':process.report,'source_before':before,'source_after':after,'producer':producer,
                'oracle_sha256':hashlib.sha256(json.dumps(original,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()}
            chunk=write_chunk(destination,'native',record)
            if read_chunk(destination,chunk)!=record:raise ValueError('native raw chunk failed roundtrip authentication')
            # These exact strings now live in the authenticated raw record; avoid
            # retaining a second vector copy in loose stdout/stderr files.
            process.stdout.unlink();process.stderr.unlink()
            item={'model':name,'record':chunk,'directory':f'{index:02}','cases':len(model_cases),
                'vector_rows':sum(len(c['input']['texts'])for c,r in zip(model_cases,original['results'],strict=True)if'error'not in r),
                'native_process_wall_ns':process.report['native_process_wall_ns'],'errors':errors}
            receipt['models'].append(item);receipt['case_ids'].extend(c['id']for c in model_cases)
            if errors:raise ValueError(name+': '+'; '.join(errors))
            if native_producer()!=producer or any(digest(Path(__file__).with_name(name))!=sha for name,sha in tooling.items()):raise ValueError('native or capture tooling changed during capture')
            print(f'{index+1}/30 {name}: exact inputs + same-platform vectors GREEN',flush=True)
        if coverage_errors(catalogue,cases,[m['model']for m in receipt['models']]):raise ValueError('native corpus coverage incomplete')
        receipt['passed']=True
    except (OSError,ValueError,TypeError,KeyError,IndexError,AttributeError,TimeoutError,RuntimeError)as error:
        receipt['errors'].append(str(error))
    (out/'summary.json').write_text(json.dumps(receipt,indent=2,allow_nan=False)+'\n')
    return receipt


def main()->int:
    import argparse
    from .preparation import PreparedNativeFastEmbed
    from .reference import Reference
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['reference','probe','sources','registry','library','out']:parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    result=compare_fastembed(Reference.load(args.reference),PreparedNativeFastEmbed(args.probe.resolve(),args.sources.resolve(),args.registry.resolve()),args.out,library=args.library.resolve())
    print(json.dumps({'passed':result['passed'],'models':len(result['models']),'errors':result['errors']}))
    return 0 if result['passed']else 1


if __name__=='__main__':raise SystemExit(main())
