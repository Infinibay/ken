"""Prospective fresh-process allocator probe; no engine edits or relevance access."""
import hashlib,json,platform,resource,sqlite3,subprocess,sys,time
from pathlib import Path
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer
import ken
R=Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
E=Path(ken.__file__).resolve().parents[2]
sys.path.insert(0,str(E/'experiments/search-engine'))
from ken.bench.source_receipts import verify_frozen_source
from contextual_run import registered_context_spec
A=R/'output/models/cpu-context-registration-v42.json'
Q=R/'output/analysis/coderank-public-queries-v31'
V=R/'output/analysis/context-views-source7-v69'
P=R/'output/analysis/c-source-reindex-v66c/requests'
X=R/'output/analysis/es-en-control-v16/queries.jsonl'
OUT=R/'output/analysis/cpu-memory-arena-v86'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()

def prepare():
    OUT.mkdir(exist_ok=False)
    assets=json.loads(A.read_text());assert sha(A)=='9de3e49ef29ce4672b5b77dfca0078a4eba82412a64c318cafe048b512787d7a'
    assert all(sha(Path(assets['root'])/name)==digest for name,digest in assets['artifacts'].items())
    bindings={str(p):sha(p)for p in(A,Q/'vectors.npz',Q/'registration.json',X,V/'registration.json',R/'output/analysis/query-input-recode-v64/registration.json',R/'experiments/search-engine/cpu-memory-arena-v86.md')}
    requests={}
    for p in sorted(P.glob('*.jsonl')):
        bindings[str(p)]=sha(p)
        for row in map(json.loads,p.read_text().splitlines()):
            assert row['id'] not in requests;requests[row['id']]=row
    expanded={row['id']:row['expanded']for row in map(json.loads,X.read_text().splitlines())}
    texts={}
    with np.load(Q/'vectors.npz')as cache:
        assert len(requests)==400 and set(requests)==set(cache['qid'])==set(expanded)
        for i,qid in enumerate(cache['qid']):
            for view,text in (('original',requests[qid]['request']['query']),('expanded',expanded[qid])):
                if text in texts:assert np.array_equal(texts[text],cache[view][i])
                else:texts[text]=cache[view][i]
    assert len(texts)==545
    samples=[];expected=[]
    reg=json.loads((V/'registration.json').read_text());assert len(reg['source_repos'])==16
    for repo,meta in sorted(reg['source_repos'].items()):
        dbp=V/(repo+'-source.db');vp=V/(repo+'-vectors.npy')
        assert sha(dbp)==meta['source_db_sha256']and sha(vp)==meta['vectors_sha256']
        bindings[str(dbp)],bindings[str(vp)]=sha(dbp),sha(vp)
        db=sqlite3.connect(f'file:{dbp}?mode=ro',uri=True)
        vectors=np.load(vp,mmap_mode='r')
        for order in('ASC','DESC'):
            idx,text_hash,text=db.execute(f"SELECT o.vector_index,t.text_hash,t.text FROM owners o JOIN texts t ON o.text_hash=t.text_hash WHERE view='implementation' ORDER BY length(t.text) {order},o.vector_index ASC LIMIT 1").fetchone()
            assert hashlib.sha256(text.encode()).hexdigest()==text_hash
            samples.append({'kind':'source','repo':repo,'index':idx,'text':text,'input':text});expected.append(vectors[idx].copy())
        db.close();del vectors
    for text,vector in sorted(texts.items()):
        samples.append({'kind':'query','text':text,'input':assets['query_prefix']+text});expected.append(vector)
    assert len(samples)==577
    (OUT/'samples.json').write_text(json.dumps(samples,ensure_ascii=False))
    np.save(OUT/'expected.npy',np.stack(expected))
    bindings[str(OUT/'samples.json')]=sha(OUT/'samples.json');bindings[str(OUT/'expected.npy')]=sha(OUT/'expected.npy')
    manifest={'scope':'Encoder-only CPU arena diagnostic, exact source/query inputs; no fitting/relevance/API certification','engine_receipt':verify_frozen_source(E),'script_sha256':sha(__file__),'inputs':bindings,'planned':577,'query_texts':545,'source_texts':32,'order':['default','off','off','default'],'runs':[],'complete':False}
    (OUT/'registration.json').write_text(json.dumps(manifest,indent=2))
    for ordinal,mode in enumerate(manifest['order']):
        subprocess.run([sys.executable,__file__,'worker',str(ordinal),mode],check=True)
        manifest['runs'].append(json.loads((OUT/(str(ordinal)+'-report.json')).read_text()))
        (OUT/'registration.json').write_text(json.dumps(manifest,indent=2))
    with np.load(OUT/'0-vectors.npz')as first:
        for ordinal in range(1,4):
            with np.load(OUT/(str(ordinal)+'-vectors.npz'))as other:
                assert first.files==other.files
                assert all(np.array_equal(first[k],other[k])for k in first.files)
    assert all(sha(p)==digest for p,digest in bindings.items())and verify_frozen_source(E)==manifest['engine_receipt']
    manifest['raw_and_unit_vectors_tokens_all_four_bit_exact']=True;manifest['complete']=True
    (OUT/'registration.json').write_text(json.dumps(manifest,indent=2))
    print(json.dumps({'complete':True,'runs':[{'mode':r['mode'],'peak_rss_native':r['peak_rss_native'],'p95_ms':r['p95_ms']}for r in manifest['runs']]}),flush=True)

def worker(ordinal,mode):
    manifest=json.loads((OUT/'registration.json').read_text());assert sha(__file__)==manifest['script_sha256']and verify_frozen_source(E)==manifest['engine_receipt']
    assert all(sha(p)==digest for p,digest in manifest['inputs'].items())
    samples=json.loads((OUT/'samples.json').read_text());expected=np.load(OUT/'expected.npy')
    assets=json.loads(A.read_text());assert assets['spec']=={**registered_context_spec(assets).__dict__}
    imported_peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
    assert options.enable_cpu_mem_arena is True
    if mode=='off':options.enable_cpu_mem_arena=False
    start=time.perf_counter()
    session=ort.InferenceSession(str(Path(assets['root'])/'onnx/model.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
    assert session.get_providers()==['CPUExecutionProvider']
    tokenizer=Tokenizer.from_file(str(Path(assets['root'])/'tokenizer.json'));tokenizer.no_padding();tokenizer.enable_truncation(max_length=512)
    initialized_peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;startup_ms=(time.perf_counter()-start)*1000
    raw,units,records=[],[],[];source_peak=None
    for i,sample in enumerate(samples):
        start=time.perf_counter();tokens=tokenizer.encode(sample['input']);inputs={'input_ids':np.array([tokens.ids],dtype=np.int64),'attention_mask':np.array([tokens.attention_mask],dtype=np.int64)}
        vector=session.run(['sentence_embedding'],inputs)[0][0];assert vector.shape==(768,)and vector.dtype==np.float32 and np.isfinite(vector).all()
        unit=(vector/np.linalg.norm(vector)).astype(np.float32);assert np.array_equal(unit,expected[i]),(ordinal,i,float(np.abs(unit-expected[i]).max()))
        ms=(time.perf_counter()-start)*1000;raw.append(vector);units.append(unit)
        records.append({'ordinal':i,'kind':sample['kind'],'input_sha256':hashlib.sha256(sample['input'].encode()).hexdigest(),'token_ids_sha256':hashlib.sha256(inputs['input_ids'].tobytes()).hexdigest(),'mask_sha256':hashlib.sha256(inputs['attention_mask'].tobytes()).hexdigest(),'tokens':len(tokens.ids),'ms':ms})
        if i==31:source_peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    np.savez(OUT/(ordinal+'-vectors.npz'),raw=np.stack(raw),unit=np.stack(units),token_ids_sha256=[r['token_ids_sha256']for r in records],mask_sha256=[r['mask_sha256']for r in records])
    assert not any(name in sys.modules for name in('torch','transformers','sentence_transformers'))
    report={'mode':mode,'arena':options.enable_cpu_mem_arena,'mem_pattern':options.enable_mem_pattern,'mem_reuse':options.enable_mem_reuse,'providers':session.get_providers(),'threads':[2,1],'count':len(records),'all_expected_unit_vectors_exact':True,'platform':platform.platform(),'runtime':ort.__version__,'import_peak_rss_native':imported_peak,'initialized_peak_rss_native':initialized_peak,'source_peak_rss_native':source_peak,'peak_rss_native':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'startup_ms':startup_ms,'p50_ms':float(np.percentile([r['ms']for r in records],50)),'p95_ms':float(np.percentile([r['ms']for r in records],95)),'max_ms':max(r['ms']for r in records),'vectors_sha256':sha(OUT/(ordinal+'-vectors.npz')),'records':records}
    (OUT/(ordinal+'-report.json')).write_text(json.dumps(report,indent=2));print(json.dumps({k:report[k]for k in('mode','count','peak_rss_native','p95_ms')}),flush=True)

if __name__=='__main__':
    if len(sys.argv)==1:prepare()
    else:worker(sys.argv[2],sys.argv[3])
