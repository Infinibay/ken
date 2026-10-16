"""Public-only, prepared complete Ken + typed cards + optional Ettin CPU worker.

Gold and grading are deliberately absent. Every neural arm reruns retrieval and
asserts the complete shared-pool digest before exposing its top answer.
"""
from __future__ import annotations

import argparse
import json
import platform
import resource
import sqlite3
import sys
import time
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import ken
from ken.bench.source_receipts import verify_frozen_source
from ken.bench.static_embeddings import StaticEmbeddingControl
from ken.db import connect
from ken.retrieval.candidates import owner_passages,owner_descriptions,retrieve_contextual
from ken.retrieval.contextual import ContextualRetriever,OwnerVectorSnapshot
from ken.retrieval.embedding_store import retrieval_snapshot
from ken.retrieval.model import EntityKey,SearchRequest
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.owner_ranking import EvidenceReranker
from ken.retrieval.profile import ContextualRetrieval,EvidenceRanking,RetrievalProfile
from contextual_run import CPUContextEncoder
from source_view_assets import load_source_views
from verifiable_pieces import SourceCatalog,piece_pool,card_text,canonical,digest
from verifiable_dependencies import LocalCallEvidence,enrich_card
from ettin_cpu import CPUReranker,sha


class PreparedKen:
    def __init__(self,workspace,repo,root,index):
        self.root=Path(root)
        p=workspace/'output/analysis/c-source-reindex-v66c'
        static=next(r for r in json.loads((workspace/'output/models/static-comparison-registration.json').read_text())
                    if r['model_id']=='minishlab/potion-code-16M-v2')
        self.words=StaticEmbeddingControl(Path(static['root']),static)
        from ken.retrieval.query_expansion import LocalQueryExpansion
        tr=json.loads((workspace/'output/models/es-en-cpu-registration-v21.json').read_text())
        self.expansion=LocalQueryExpansion(Path(tr['root']),tr)
        numeric=workspace/'output/analysis/source7-context-views-ranking-v69/contract_body251'
        reg=json.loads((numeric.parent/'registration.json').read_text())
        fold=next(x for x in reg['modes']['contract_body251']['folds'] if x['held_out']==repo)
        model=NumericRanker.from_dict(json.loads((numeric/(repo+'-numeric.json')).read_text()))
        if repo in fold['training_repos'] or model.fingerprint!=fold['model_fingerprint']:
            raise ValueError('repo exclusion/model pin failed')
        self.ranker=EvidenceReranker(model,self.words,expand_query=self.expansion,
                                    expansion_revision=self.expansion.revision)
        original=workspace/'output/models/cpu-context-registration-v42.json'
        context=CPUContextEncoder(json.loads(original.read_text()))
        self.conn=connect(index)
        c=sqlite3.connect(f'file:{p/"context"/(repo+".db")}?mode=ro',uri=True)
        encoded=c.execute('SELECT o.entity,o.source_hash,v.vector FROM owners o '
                          'JOIN vectors v ON o.text_hash=v.hash ORDER BY o.entity').fetchall();c.close()
        prepared=json.loads((p/'context-registration.json').read_text())
        with retrieval_snapshot(self.conn) as snapshot:
            if str(snapshot.generation)!=str(prepared['repos'][repo]['generation']):
                raise ValueError('source generation differs from context vectors')
            vectors=OwnerVectorSnapshot(context.spec,snapshot.generation,
                tuple(EntityKey(**json.loads(r[0])) for r in encoded),tuple(r[1] for r in encoded),
                np.stack([np.frombuffer(r[2],dtype=np.float32) for r in encoded]))
        del encoded
        v=workspace/'output/analysis/context-views-source7-v69'
        views,self.view_receipts=load_source_views(index=v/(repo+'-source.db'),
            vectors=v/(repo+'-vectors.npy'),registration=v/'registration.json',
            model_registration=v/'model-registration.json',repo=repo,source=vectors,
            original_registration=original,full_context_index=p/'context'/(repo+'.db'))
        self.runtime=ContextualRetriever(context,vectors,source_views=views)
        self.profile=RetrievalProfile(self.words.spec,self.words.spec,
            contextual=ContextualRetrieval(context.spec,view_model=views.model),
            evidence=EvidenceRanking(model.fingerprint,self.words.spec,self.expansion.revision,
                feature_version=self.ranker.feature_version,evidence_version=3))
        self.catalog=SourceCatalog(root,owner_passages(self.conn))
        self.indexed_files=self.conn.execute('SELECT COUNT(*) FROM ci_files').fetchone()[0]

    def pool(self,case,*,trace=None):
        request=SearchRequest(case['query'],target='file' if case['target_kind'] in {'module','file'}
                              else 'symbol',limit=20,max_chars=12000,piece_kind=case['target_kind'])
        with retrieval_snapshot(self.conn):
            self.ranker.validate(self.profile.evidence)
            candidates,expanded=retrieve_contextual(self.conn,self.root,request,self.profile,
                runtime=self.runtime,expand_query=self.ranker.prepare_query,
                encoders={'identity':self.words,'behavior':self.words})
            diagnostics={'trace':trace} if trace is not None else {}
            matches=self.ranker.rank(request,candidates,owner_descriptions(self.conn,candidates),
                expanded_query=expanded,evidence_version=3,**diagnostics)
        cards=piece_pool(matches,case['target_kind'],expanded,self.catalog)
        exact=len(candidates)==1 and bool(candidates[0].signals.get('exact'))
        return cards,expanded,exact,len(candidates)


def main():
    p=argparse.ArgumentParser()
    for name in ('workspace','requests','root','index','output','catalog-receipt','source-metadata'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--model',type=Path);p.add_argument('--expected-pools',type=Path)
    p.add_argument('--local-call-evidence',action='store_true')
    p.add_argument('--capture-ranking',action='store_true')
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    # Controller and direct callers both verify the ALL-source gate before requests.
    from verifiable_guard import verify_source_preparation
    prepared_roots,preparation=verify_source_preparation(args.workspace,args.source_metadata)
    cases=[json.loads(x) for x in args.requests.read_text().splitlines()]
    if not cases or len({c['id'] for c in cases})!=len(cases) or len({c['repo_id'] for c in cases})!=1:
        raise ValueError('unique public cases from one repo required')
    repo=cases[0]['repo_id'];engine=Path(ken.__file__).resolve().parents[2]
    if Path(prepared_roots[repo]).resolve()!=args.root.resolve():raise ValueError('root differs from preparation')
    receipt=verify_frozen_source(engine)
    expected={r['id']:r for r in map(json.loads,args.expected_pools.read_text().splitlines())} if args.expected_pools else None
    if args.capture_ranking and args.model:raise ValueError('ranking trace is a native-only diagnostic')
    if bool(args.model or args.capture_ranking)!=bool(expected):
        raise ValueError('neural/diagnostic arm requires sealed baseline pools')
    if args.capture_ranking:
        from ken.retrieval.ranking_trace import RankingTrace
        from ranking_diagnostics import piece_order
    started=time.perf_counter()
    runtime=PreparedKen(args.workspace,repo,args.root,args.index)
    dependencies=LocalCallEvidence(runtime.catalog) if args.local_call_evidence else None
    inventory=runtime.catalog.source_inventory()
    catalog_receipt=json.loads(args.catalog_receipt.read_text())
    inventory_bytes=''.join(canonical(r)+'\n' for r in inventory).encode()
    import hashlib
    if hashlib.sha256(inventory_bytes).hexdigest()!=catalog_receipt['repos'][repo]['inventory_sha256']:
        raise ValueError('catalog differs from source-only pre-query preparation')
    del inventory,inventory_bytes
    model=CPUReranker(json.loads(args.model.read_text())) if args.model else None
    load_ms=(time.perf_counter()-started)*1000
    started=time.perf_counter()
    # Prepares projections/source matrix and CPU kernels using source-free queries.
    runtime.pool({'query':'find code that prepares a value','target_kind':'symbol'})
    runtime.ranker.prepare_query('¿Dónde convierte un valor de entrada?')
    if model:model.score('find a stored value',['class Cache:\n    def get(self,key): return self.data[key]']*10)
    warmup_ms=(time.perf_counter()-started)*1000
    record={'scope':'ALL public queries complete prepared experimental typed-card pipeline; CPU',
        'repo':repo,'engine_receipt':receipt,'engine_root':str(engine),'cases_sha256':sha(args.requests),
        'catalog_receipt_sha256':sha(args.catalog_receipt),'worker_sha256':sha(__file__),
        'model_registration_sha256':sha(args.model) if args.model else None,
        'indexed_files':runtime.indexed_files,'asset_load_ms':load_ms,'warmup_ms':warmup_ms,
        'machine':platform.machine(),'platform':platform.platform(),'python':sys.version,
        'profile':runtime.profile.to_dict(),'timings':[]}
    try:
        with ((args.output/'answers.jsonl').open('w') as answers,
              (args.output/'pools.jsonl').open('w') as pools,
              ((args.output/'ranking-traces.jsonl').open('w') if args.capture_ranking else nullcontext()) as trace_output):
            for case in cases:
                started=time.perf_counter()
                trace=RankingTrace(request_id=case['id']) if args.capture_ranking else None
                cards,expanded,exact,count=runtime.pool(case,trace=trace)
                pool_ms=(time.perf_counter()-started)*1000
                pool_hash=digest({'cards':cards,'expanded':expanded,'exact':exact})
                if expected and expected[case['id']]['pool_sha256']!=pool_hash:
                    raise ValueError('shared pool/card mismatch: '+case['id'])
                neural={};scores=None;order=list(range(len(cards)))
                if model and cards and not exact:
                    scores,neural=model.score(expanded,[card_text(c) for c in cards[:10]])
                    order=order[:10]
                    order=sorted(order,key=lambda i:(-scores[i],i))
                card=cards[order[0]] if order else None
                if dependencies is not None:
                    enrich_started=time.perf_counter()
                    card=enrich_card(card,expanded,runtime.catalog,dependencies)
                    neural['local_call_evidence_ms']=(time.perf_counter()-enrich_started)*1000
                answer={'id':case['id'],'pool_sha256':pool_hash,
                        'card':card,'top_index':order[0] if order else None}
                serialized=canonical(answer)
                # Includes common retrieval/card preparation, model tokenization/inference,
                # selection and canonical answer serialization; excludes diagnostic pool dump.
                elapsed=(time.perf_counter()-started)*1000
                record['timings'].append({'id':case['id'],'target_kind':case['target_kind'],
                    'ms':elapsed,'pool_ms':pool_ms,'candidate_owners':count,'typed_candidates':len(cards),
                    'exact_bypass':exact,**neural})
                answers.write(serialized+'\n');answers.flush()
                pools.write(canonical({'id':case['id'],'pool_sha256':pool_hash,'expanded':expanded,
                    'exact':exact,'cards':cards} if not model else {'id':case['id'],
                    'pool_sha256':pool_hash,'order':order,'scores':scores})+'\n');pools.flush()
                if trace_output is not None:
                    before_export=time.perf_counter()
                    diagnostic=trace.to_dict(include_query=True)
                    pieces=piece_order(diagnostic['owners'],case['target_kind'],runtime.catalog)
                    if [p['unit'] for p in pieces[:20]]!=[c['unit'] for c in cards]:
                        raise ValueError('observed owner grouping differs from actual returned pieces')
                    diagnostic.update(id=case['id'],target_kind=case['target_kind'],
                                      pool_sha256=pool_hash,pieces=pieces)
                    trace_output.write(canonical(diagnostic)+'\n');trace_output.flush()
                    record['timings'][-1]['trace_export_ms']=(time.perf_counter()-before_export)*1000
        record['peak_rss_native']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        record['rss_unit']='bytes' if sys.platform=='darwin' else 'KiB'
        record['heavy_imports']=[m for m in ('torch','transformers','sentence_transformers') if m in sys.modules]
        if record['heavy_imports'] or verify_frozen_source(engine)!=receipt:raise ValueError('runtime/source policy failed')
        if any(sha(path)!=value for path,value in runtime.view_receipts.items()):raise ValueError('source views changed')
        record['answers_sha256']=sha(args.output/'answers.jsonl');record['pools_sha256']=sha(args.output/'pools.jsonl')
        if args.capture_ranking:
            record['ranking_trace_sha256']=sha(args.output/'ranking-traces.jsonl')
            record['ranking_trace_scope']='Actual native feature matrix/order; full piece projection; no Gold; export excluded from query ms'
        (args.output/'performance.json').write_text(json.dumps(record,indent=2))
        print(json.dumps({'repo':repo,'queries':len(cases),'peak_rss_native':record['peak_rss_native'],
            'p50_ms':float(np.median([x['ms'] for x in record['timings']]))}),flush=True)
    finally:runtime.conn.close()


if __name__=='__main__':main()
