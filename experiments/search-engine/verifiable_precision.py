"""One fixed FP32 precision control over closed cards, without reading Gold."""
from __future__ import annotations
import argparse
import json
import math
import resource
import sys
import time
from pathlib import Path


def precision_orders(scores, *, exact=False,total=None):
    total=len(scores) if total is None else total
    if total<len(scores):raise ValueError('scored prefix exceeds the retained candidate count')
    if not all(math.isfinite(score) for score in scores):raise ValueError('finite scores required')
    native=list(range(len(scores)))
    neural=sorted(native,key=lambda i:(-scores[i],i))
    if exact:neural=native
    inverse={index:rank for rank,index in enumerate(neural)}
    result={'fp32_raw':neural}
    for name,weight in (('fp32_rrf50',.5),('fp32_rrf25',.25)):
        result[name]=sorted(native,key=lambda i:(
            -((1-weight)/(61+i)+weight/(61+inverse[i])),i))
    return {name:order+list(range(len(scores),total)) for name,order in result.items()}


def main():
    from ettin_cpu import CPUReranker,sha
    from verifiable_pieces import card_text,digest
    p=argparse.ArgumentParser()
    for name in ('comparison','public-cases','model','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--reference-size',choices=('17m','32m','68m'),default='17m')
    p.add_argument('--neural-prefix',type=int,choices=(3,10),default=10)
    a=p.parse_args();reg=json.loads((a.comparison/'registration.json').read_text())
    if reg['status']!='ALL outputs closed without Gold or quality grading':raise ValueError('inputs not closed')
    if sha(a.public_cases)!=reg['public_cases_sha256']:raise ValueError('queries differ')
    assembly=json.loads(a.model.read_text())
    if assembly.get('encoder_precision')!='fp32':raise ValueError('FP32 control required')
    previous=next(path for path in reg['source_files'] if path.endswith(a.reference_size+'/assembly.json'))
    if sha(previous)!=reg['source_files'][previous]:raise ValueError('registered INT8 reference changed')
    int8=json.loads(Path(previous).read_text())
    identity=lambda r:(r['upstream']['model_id'],r['upstream']['revision'],r['tokenizer_sha256'])
    if identity(assembly)!=identity(int8):raise ValueError('not the same weights/tokenizer')
    pools=[]
    for repo,files in reg['closed_workers']['baseline'].items():
        path=a.comparison/'baseline'/repo/'pools.jsonl'
        if sha(path)!=files['pools.jsonl']:raise ValueError('closed input changed')
        pools.append(path)
    a.output.mkdir(parents=True,exist_ok=False)
    scripts=Path(__file__).parent
    import ettin_cpu,verifiable_pieces
    pins={str(path.resolve()):sha(path) for path in [Path(__file__),scripts/'test_verifiable_precision.py',
          Path(ettin_cpu.__file__),Path(verifiable_pieces.__file__),a.model,*pools]}
    receipt={'scope':'development FP32 same-weight reranking-only precision control; not complete Ken latency/RAM',
        'comparison_sha256':sha(a.comparison/'registration.json'),'public_cases_sha256':sha(a.public_cases),
        'model_sha256':sha(a.model),'input_pins':pins,'arms':['fp32_raw','fp32_rrf50','fp32_rrf25'],
        'policy':'same v102 top10 cards/expanded query/exact bypass; score only the fixed prefix, append unscored candidates unchanged; fixed RRF60 weights0.5 and0.25; no filter, training or Gold',
        'neural_prefix':a.neural_prefix,
        'status':'registered before queries'}
    (a.output/'registration.json').write_text(json.dumps(receipt,indent=2))
    cases={r['id']:r for r in map(json.loads,a.public_cases.read_text().splitlines())}
    if len(cases)!=200:raise ValueError('ALL200 required')
    started=time.perf_counter();model=CPUReranker(assembly);load_ms=(time.perf_counter()-started)*1000
    started=time.perf_counter();model.score('find a stored value',['def get(key): return data[key]']*10)
    warmup_ms=(time.perf_counter()-started)*1000
    seen=set();timings=[]
    with (a.output/'orders.jsonl').open('w') as output:
        for path in pools:
            with path.open() as stream:
                for line in stream:
                    row=json.loads(line);qid=row['id']
                    if qid not in cases or qid in seen:raise ValueError('unexpected/duplicate case')
                    if digest({k:row[k] for k in ('cards','expanded','exact')})!=row['pool_sha256']:
                        raise ValueError('input pool digest differs')
                    texts=[card_text(c) for c in row['cards'][:10]]
                    scored=texts[:a.neural_prefix]
                    started=time.perf_counter()
                    if row['exact'] or not scored:
                        scores=[0.]*len(scored);details={'token_ms':0,'inference_ms':0,'truncated_documents':0,'pair_tokens':[],'pad_id':50283}
                    else:scores,details=model.score(row['expanded'],scored)
                    if len(scores)!=len(scored) or details['pad_id']!=50283:raise ValueError('pair/padding scope differs')
                    orders=precision_orders(scores,exact=row['exact'],total=len(texts))
                    record={'id':qid,'pool_sha256':row['pool_sha256'],'scores':scores,'orders':orders}
                    encoded=json.dumps(record,separators=(',',':'))
                    timings.append({'id':qid,'ms':(time.perf_counter()-started)*1000,
                                    'exact_bypass':row['exact'],**details})
                    output.write(encoded+'\n');output.flush();seen.add(qid)
            print(json.dumps({'repo':path.parent.name,'closed_queries':len(seen)}),flush=True)
    if seen!=set(cases):raise ValueError('missing cases')
    for path,expected in pins.items():
        if sha(path)!=expected:raise ValueError('registered producer/input changed')
    heavy=[m for m in ('torch','transformers','sentence_transformers') if m in sys.modules]
    if heavy:raise ValueError('heavy runtime imported')
    (a.output/'performance.json').write_text(json.dumps({'scope':receipt['scope'],'asset_load_ms':load_ms,'warmup_ms':warmup_ms,
        'timings':timings,'peak_rss_native':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'rss_unit':'bytes' if sys.platform=='darwin' else 'KiB','heavy_imports':heavy},indent=2))
    receipt.update(status='ALL200 precision orders closed without Gold',orders_sha256=sha(a.output/'orders.jsonl'),
                   performance_sha256=sha(a.output/'performance.json'))
    (a.output/'registration.json').write_text(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
