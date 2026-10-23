"""Representative factory role calls, with independent retained original outputs."""
from __future__ import annotations
import argparse,gzip,json,os
from pathlib import Path
import platform
from .integration_process import run_factory
from .integration_capture import digest
from .fastembed_process import decode_frames


def role_cases(repo:Path,system:str)->list[dict]:
    validation=repo/'docs/validation';platform_key='Darwin/arm64'if system=='macos'else'Linux/aarch64'
    rows=[]
    for name,folder,file in [('static','rust-migration-2026-10-18/m2-table','reference.json'),('potion','rust-migration-2026-10-18/m2-static','potion-reference.json')]:
        path=validation/folder/file;document=json.loads(path.read_bytes())
        case=next(c for c in document['cases']if c['id']=='spanish');gold=next(r for r in document['results']if r['id']=='spanish')
        query=case['calls'][-1]['text']
        rows.append({'name':name,'reference':path,'calls':[{'id':'count','call':{'operation':'count','text':query}},
            {'id':'spanish','call':{'operation':'query','text':query}},
            {'id':'concurrent','call':{'operation':'concurrent_query','text':query,'workers':8}}],
            'expected':{'count':gold['calls'][1],'vectors':[gold['calls'][-1]]},
            'tolerances':document['tolerances']['float16']if name=='potion'else document['tolerances']})
    for name,folder,case_id in [('context','rust-migration-2026-10-18/m2-context','spanish-query'),('reranker','rust-migration-2026-10-19/m2-ettin','spanish')]:
        path=validation/folder/'reference.json';document=json.loads(path.read_bytes());original=document['platforms'][platform_key]
        case=next(c for c in document['cases']if c['id']==case_id);gold=next(r for r in original['results']if r['id']==case_id)
        call=case['calls'][-1]
        operation={'operation':'query','text':call['text']}if name=='context'else{
            'operation':'score','query':call['query'],'documents':call['texts'],'purpose':'implementation'}
        expected={'vectors':[gold['calls'][-1]],'tokens':gold['calls'][0]}if name=='context'else{'scores':gold['calls'][-1]['scores']}
        rows.append({'name':name,'reference':path,'calls':[{'id':case_id,'call':operation}],'expected':expected,'tolerances':document['tolerances']})
    path=validation/'rust-migration-2026-10-19/m2-translation/reference.json';document=json.loads(path.read_bytes());original=next(r for r in document['oracles']if r['platform']==('Darwin'if system=='macos'else'Linux'))
    case=next(c for c in original['cases']if c['id']=='spanish');gold=next(r for r in original['results']if r['id']=='spanish')['calls'][0]
    rows.append({'name':'expansion','reference':path,'calls':[{'id':'english','call':{'operation':'expand','text':'Where are names normalized?'}},
        {'id':'spanish','call':{'operation':'expand','text':case['queries'][0]}}],'expected':gold})
    base=validation/'rust-migration-2026-10-20/m2-transformer-acceptance'/system/'base/fastembed-parity'
    summary=json.loads((base/'summary.json').read_bytes());model=next(r for r in summary['models']if r['model']=='sentence-transformers/all-MiniLM-L6-v2')
    path=base/model['directory']/model['record']['path'];record=json.loads(gzip.decompress(path.read_bytes()))
    call=next(c for c in record['requests']if c['id'].endswith(':mixed_passages'))
    gold=next(r for r in decode_frames(record['stdout'])if r['id']==call['id'])
    import struct
    shape=gold['result']['shape'];raw=bytes.fromhex(gold['result']['vectors_f32le_hex'])
    if len(shape)!=2 or len(raw)!=shape[0]*shape[1]*4:raise ValueError('invalid accepted vector shape')
    values=[v[0]for v in struct.iter_unpack('<f',raw)]
    vectors=[values[i*shape[1]:(i+1)*shape[1]]for i in range(shape[0])]
    rows.append({'name':'fastembed','reference':path,'calls':[{'id':'mixed-passages','call':{'operation':'passages','texts':call['texts']}}],
        'expected':{'vectors':vectors},'tolerances':{'atol':0.,'rtol':0.}})
    return rows


def capture_roles(repo:Path,probe:Path,out:Path)->dict:
    import numpy as np
    system='macos'if platform.system()=='Darwin'else'linux';rows=[]
    resources=repo/'crates/ken-models/resources'
    declarations={name:json.loads((resources/file).read_bytes())for name,file in {
        'potion':'potion-code-16M-v2.json','context':'code-context-int8.json','reranker':'ettin-68m-fp32.json','expansion':'es-en-ct2-int8.json'}.items()}
    for recipe in role_cases(repo,system):
        name=recipe['name'];legacy=json.loads((repo/'crates/ken-models/tests/fixtures/profile-identity/macos.json').read_bytes())['legacy_runtime']
        request={'format':'ken-model-factory-request/1','policy':'public'if name=='fastembed'else'offline','cache_root':str(out/'cache'),
            'private_parent':str(out/'private'),'bundled_npz':str(repo/'src/ken/embedder/data/ken__static-qwen3-r512-v2.npz'),
            'source_overrides':{},'device':{'kind':'cpu'},'fastembed_device':'cpu','cases':recipe['calls']}
        if name in('static','potion'):
            registration=json.loads((resources/'legacy-compatibility.json').read_bytes())['static_table']if name=='static'else declarations[name]
            model_id=registration['model_id'];revision=registration['sha256']if name=='static'else __import__('hashlib').sha256(json.dumps(registration,sort_keys=True).encode()).hexdigest()
            request['selection']={'kind':'encoder','spec':{'model_id':model_id,'revision':revision,'backend':'static'if name=='static'else'model2vec',
                'dtype':'float32'if name=='static'else'float16','sequence_length':512,'batch_size':16 if name=='static'else 1024},'legacy':legacy}
            if name=='potion':request['source_overrides'][model_id]=os.environ['KEN_POTION_SNAPSHOT']
        elif name=='fastembed':request['selection']={'kind':'legacy_encoder','name':'sentence-transformers/all-MiniLM-L6-v2'}
        else:
            request['selection']={'kind':name}
            declaration=declarations[name];assets=declaration['source']if'source'in declaration else declaration
            request['source_overrides'][assets['model_id']]=os.environ[{'context':'KEN_CONTEXT_SNAPSHOT','reranker':'KEN_ETTIN_SOURCE','expansion':'KEN_TRANSLATION_SOURCE'}[name]]
        if name in('context','reranker','fastembed'):
            request['onnx']={'registration':json.loads((repo/'docs/validation/rust-migration-2026-10-18/m2-context/runtime-libraries.json').read_bytes()),'library':os.environ['KEN_ORT_LIBRARY']}
        phases=['public','offline']if name=='fastembed'else['offline']
        for phase in phases:
            request['policy']=phase;output=out/(name+'-'+phase)
            observed=run_factory(probe,request,output,deadline_s=600)
            (output/'observed.receipt.json').write_text(json.dumps(observed['receipt'],indent=2)+'\n')
            actual=observed['actual'];frames=actual['rows'];expected=recipe['expected'];errors=[];maximum=0.
            if actual['initial_prepared']:errors.append('eager role preparation')
            def vectors(a,b):
                nonlocal maximum
                left=np.asarray(a,dtype=np.float32);right=np.asarray(b,dtype=np.float32)
                tol=recipe['tolerances']
                if left.shape!=right.shape or not np.isfinite(left).all()or not np.allclose(left,right,atol=tol['atol'],rtol=tol['rtol']):raise ValueError('original values differ')
                maximum=max(maximum,float(np.max(np.abs(left-right))))
                if 'cosine_min'in tol:
                    for l,r in zip(left.reshape(-1,left.shape[-1]),right.reshape(-1,right.shape[-1]),strict=True):
                        norm=np.linalg.norm(l)*np.linalg.norm(r)
                        if norm and float(np.dot(l,r)/norm)<tol['cosine_min']:raise ValueError('original cosine threshold differs')
            try:
                if name in('static','potion'):
                    if frames[0]['result']['count']!=expected['count']:raise ValueError('raw count differs')
                    vectors(frames[1]['result']['vectors'],expected['vectors'])
                    vectors(frames[2]['result']['vectors'],expected['vectors']*8)
                elif name=='context':
                    if frames[0]['result']['tokens']!=expected['tokens']:raise ValueError('context tokens differ')
                    vectors(frames[0]['result']['vectors'],expected['vectors'])
                elif name=='reranker':vectors([frames[0]['result']['scores']],[expected['scores']])
                elif name=='fastembed':vectors(frames[0]['result']['vectors'],expected['vectors'])
                else:
                    if frames[0]['result']['text']!='Where are names normalized?'or frames[0]['prepared']:raise ValueError('English laziness differs')
                    translation=frames[1]['result']
                    if translation['text']!=expected['output']:raise ValueError('translation output differs')
                    trace=translation['trace'];gold=expected['trace']
                    if trace['prepared']!=gold['prepared']or trace['hypotheses']!=gold['hypotheses']or trace['decoded']!=gold['decoded']:raise ValueError('raw translation differs')
                    if trace['tokens']['ids']!=gold['source_ids']or trace['tokens']['pieces_with_eos']!=gold['source_pieces_with_eos']:raise ValueError('translation tokens differ')
            except(KeyError,ValueError,TypeError)as error:errors.append(str(error))
            row={'name':name,'phase':phase,'passed':not errors,'errors':errors,'maximum_absolute_error':maximum,
                'request':digest(output/'inputs.json'),'stdout':digest(output/'stdout.json'),'reference':str(recipe['reference'].relative_to(repo)),'reference_identity':digest(recipe['reference'])}
            rows.append(row);(out/'capture-progress.json').write_text(json.dumps({'platform':system,'roles':rows,'M2_accepted':False},indent=2)+'\n')
            print(json.dumps(row),flush=True)
            if errors:raise ValueError('factory role rejected: '+name)
    summary={'format':'ken-factory-role-capture/1','platform':system,'roles':rows,'M2_accepted':False}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');return summary


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--repo',type=Path,required=True);parser.add_argument('--probe',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();capture_roles(args.repo.resolve(),args.probe.resolve(),args.out.resolve())

if __name__=='__main__':main()
