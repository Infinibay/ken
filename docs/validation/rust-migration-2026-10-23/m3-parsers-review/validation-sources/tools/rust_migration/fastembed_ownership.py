"""External source repair/removal with a live native process and independent files."""
from __future__ import annotations
import argparse,json,os,platform,shutil,stat,tempfile
from pathlib import Path
from .fastembed_compare import (ROOT,FRAME_FIELDS,_batches,_positive,_preparation,_shape,_state,_vectors,
    _oracle_inputs,fingerprint,native_producer)
from .fastembed_process import NativeProbeProcess,decode_frames,digest
from .fastembed_reference import read_chunk,write_chunk,source_state

MODELS=['BAAI/bge-small-en-v1.5','sentence-transformers/all-MiniLM-L6-v2',
    'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2','Qdrant/clip-ViT-B-32-text','jinaai/jina-embeddings-v3']


def _exact(left,right)->bool:
    if type(left)is not type(right):return False
    if type(right)is dict:return set(left)==set(right)and all(_exact(left[k],right[k])for k in right)
    if type(right)is list:return len(left)==len(right)and all(_exact(a,b)for a,b in zip(left,right,strict=True))
    return left==right


def ownership_requests(name:str,case:dict)->list[dict]:
    return [dict(id=name+':ownership-'+suffix,operation=operation,
        **(case['input']if operation=='embed'else{}))
        for suffix,operation in [('cold','status'),('bad','prepare'),('failed','status'),('repaired','prepare'),
                                ('before','embed'),('after','embed'),('final','status')]]


def ownership_errors(definition:dict,case:dict,wanted:dict,frames:object,facts:object,process:object,
                     producer:dict,core:dict,*,native_sha256:str,registry_sha256:str)->list[str]:
    try:
        name=definition['name'];dimension=definition['dimension'];requests=ownership_requests(name,case)
        if type(frames)is not list or [r.get('id')if type(r)is dict else None for r in frames]!=[r['id']for r in requests]:return ['ownership frame coverage mismatch']
        cold={'device':'unknown','model_loaded':False,'dim':dimension};ready=dict(cold,device='cpu',model_loaded=True)
        expected_facts={'failed_owned_roots':0,'prepared_owned_roots':1,'source_removed':True,
            'owned_artifacts':{path:{**pin,'mode':0o444,'regular':True,'nlink':1,'independent_inode':True}for path,pin in definition['assets']['artifacts'].items()}}
        errors=[]
        if not _exact(facts,expected_facts):errors.append('false cleanup/source-removal/private-file ownership facts')
        if (type(process)is not dict or process.get('native_exit')!=0 or process.get('outside_checkout')is not True
                or process.get('native_children')!=[]or process.get('owned_after_exit')!=[]
                or process.get('exec_attempts')!=(1 if core['os']=='linux'else None)
                or process.get('native_sha256')!=native_sha256 or process.get('core_sha256')!=core['sha256']
                or process.get('registry_sha256')!=registry_sha256 or not _positive(process.get('native_process_wall_ns'))):errors.append('invalid actual native process/exec/binary/core witness')
        if len({r['constructor_ns']for r in frames})!=1:errors.append('one native encoder lifetime required')
        peak=0
        for index,(request,row)in enumerate(zip(requests,frames,strict=True)):
            before=cold if index<=3 else ready;after=cold if index<3 else ready
            if (set(row)!=FRAME_FIELDS|({'error'}if index==1 else{'result'})or row['format']!='ken-fastembed-frame/1'
                    or row['operation']!=request['operation']or row['model']!=name or row['producer']!=producer
                    or row['model_fingerprint']!=fingerprint(definition)or row['assets_fingerprint']!=fingerprint(definition['assets'])
                    or not _positive(row['constructor_ns'])or not _positive(row['elapsed_ns'])
                    or not _state(row['before'],before,dimension)or not _state(row['state'],after,dimension)
                    or not _preparation(row,definition,core)):
                errors.append(request['id']+': invalid actual request/state/preparation');continue
            if type(row['memory'])is not dict or set(row['memory'])!={'before','after'}:errors.append('invalid ownership memory phases')
            else:
                for phase in ('before','after'):
                    sample=row['memory'][phase]
                    if (type(sample)is not dict or set(sample)!={'reported_hwm_bytes','observed_peak_bytes'}or not _positive(sample['reported_hwm_bytes'])):errors.append('invalid ownership memory sample');continue
                    peak=max(peak,sample['reported_hwm_bytes'])
                    if sample['observed_peak_bytes']!=peak:errors.append('false ownership memory envelope')
            if index==1:
                error=row['error']
                if (type(error)is not dict or set(error)!={'type','kind','message'}or error['type']!='ModelError'
                        or error['kind']!='artifact'or 'tokenizer_config.json'not in error['message']):errors.append('real last-artifact failure missing')
            elif request['operation']=='embed':
                if not _vectors(wanted,row['result'],dimension,len(case['input']['texts']))or not _batches(wanted['batches'],row['result']['batches']):errors.append('ownership vectors/tokens/type/shape changed')
            elif row['result']!={'prepared':index>=3}:errors.append('false prepare/status result')
        if frames[4].get('result')!=frames[5].get('result'):errors.append('native owned rows changed after source removal')
        return errors
    except (KeyError,ValueError,TypeError,IndexError,AttributeError,OverflowError)as error:return ['malformed ownership proof: '+str(error)]


def _owned_files(work:Path,snapshot:Path,definition:dict)->dict:
    roots=list(work.iterdir())
    if len(roots)!=1:raise ValueError('exactly one private prepared file owner required')
    root=roots[0]
    if stat.S_IMODE(root.stat().st_mode)!=0o700:raise ValueError('private owner mode must be0700')
    records={}
    for name in definition['assets']['artifacts']:
        path=root/name;metadata=path.lstat();source=(snapshot/name).stat()
        records[name]={'bytes':metadata.st_size,'sha256':digest(path),'mode':stat.S_IMODE(metadata.st_mode),
            'regular':stat.S_ISREG(metadata.st_mode),'nlink':metadata.st_nlink,
            'independent_inode':(metadata.st_dev,metadata.st_ino)!=(source.st_dev,source.st_ino)}
    return records


def verify_fastembed_ownership(reference,prepared,out:Path,*,library:Path|None=None)->dict:
    from .preparation import context_environment
    from .fastembed_sources import source_lease
    out=out.resolve();out.mkdir(parents=True,exist_ok=False)
    receipt={'format':'ken-fastembed-ownership/1','platform':platform.system(),'architecture':platform.machine(),
        'passed':False,'errors':[],'models':[],'FastEmbed_accepted':False,'M2_accepted':False}
    try:
        catalogue,cases,originals,core=_oracle_inputs(reference,prepared)
        library=library or Path(context_environment().get('KEN_ORT_LIBRARY',''))
        if not library.is_absolute()or digest(library)!=core['sha256']:raise ValueError('registered native core required')
        producer=native_producer();native_sha=digest(prepared.probe);registry_sha=digest(prepared.registry)
        receipt.update(native_sha256=native_sha,registry_sha256=registry_sha,producer=producer,core_identity=core)
        for index,name in enumerate(MODELS):
            definition=next(m for m in catalogue['models']if m['name']==name)
            original=next(r for r in originals if r['model']==name)
            case=next(c for c in cases if c['model']==name and c['id'].endswith(':mixed_queries'))
            with source_lease(prepared,definition,copies=3)as leased:
                wanted=next(r for r in original['results']if r['id']==case['id']);before=source_state(leased.sources,definition)
                with tempfile.TemporaryDirectory(prefix='ken-fastembed-mutable-source-')as temporary:
                    sources=Path(temporary)/'sources';snapshot=sources/definition['assets']['model_id'].replace('/','--')/definition['assets']['revision'];snapshot.mkdir(parents=True)
                    for path in definition['assets']['artifacts']:
                        target=snapshot/path;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(Path(before['snapshot'])/path,target)
                    bad=snapshot/'tokenizer_config.json';correct=bad.read_bytes()
                    if not correct:raise ValueError('nonempty actual tokenizer config required')
                    bad.write_bytes(bytes([correct[0]^1])+correct[1:])
                    requests=ownership_requests(name,case);destination=out/f'{index:02}'
                    with NativeProbeProcess(prepared.probe,prepared.registry,sources,library,name,destination)as process:
                        process.send(requests[0]);process.send(requests[1]);facts={'failed_owned_roots':len(list(process.work.iterdir()))}
                        failed=process.send(requests[2])
                        if failed.get('state',{}).get('model_loaded')is not False:raise ValueError('failed preparation became ready')
                        bad.write_bytes(correct);repaired=process.send(requests[3])
                        if repaired.get('state',{}).get('model_loaded')is not True:raise ValueError('real source repair did not prepare')
                        facts.update(prepared_owned_roots=len(list(process.work.iterdir())),owned_artifacts=_owned_files(process.work,snapshot,definition))
                        process.send(requests[4]);shutil.rmtree(snapshot);facts['source_removed']=not snapshot.exists();process.send(requests[5]);process.send(requests[6])
                    raw=process.stdout.read_text();stderr=process.stderr.read_text();after=source_state(leased.sources,definition)
                    errors=ownership_errors(definition,case,wanted,decode_frames(raw),facts,process.report,producer,core,native_sha256=native_sha,registry_sha256=registry_sha)
                    if before!=after:errors.append('canonical model source changed')
                    record={'format':'ken-fastembed-ownership-record/1','model':name,'requests':requests,'stdout':raw,'stderr':stderr,
                        'process':process.report,'facts':facts,'canonical_before':before,'canonical_after':after,'producer':producer}
                    chunk=write_chunk(destination,'ownership',record)
                    if read_chunk(destination,chunk)!=record:raise ValueError('ownership raw authentication/roundtrip failed')
                    process.stdout.unlink();process.stderr.unlink()
                    receipt['models'].append({'model':name,'directory':f'{index:02}','record':chunk,'errors':errors})
                    if errors:raise ValueError(name+': '+'; '.join(errors))
                    print(f'{index+1}/5 {name}: actual failed copy/repair/source removal/owned vectors/drop GREEN',flush=True)
        if [m['model']for m in receipt['models']]!=MODELS:raise ValueError('all five ownership families required')
        receipt['passed']=True
    except (OSError,ValueError,TypeError,KeyError,IndexError,AttributeError,TimeoutError,RuntimeError)as error:receipt['errors'].append(str(error))
    (out/'summary.json').write_text(json.dumps(receipt,indent=2,allow_nan=False)+'\n');return receipt


def main()->int:
    from .preparation import PreparedNativeFastEmbed
    from .reference import Reference
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['reference','probe','sources','registry','library','out']:parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();result=verify_fastembed_ownership(Reference.load(args.reference),PreparedNativeFastEmbed(args.probe.resolve(),args.sources.resolve(),args.registry.resolve()),args.out,library=args.library.resolve())
    print(json.dumps({'passed':result['passed'],'models':len(result['models']),'errors':result['errors']}));return 0 if result['passed']else 1


if __name__=='__main__':raise SystemExit(main())
