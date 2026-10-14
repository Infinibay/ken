"""CPU-only development controls on a frozen candidate pool, never an acceptance run."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from ken.bench.dataset import load_dataset
from ken.bench.retrieval import evaluate, request_for_case
from ken.bench.ranking_controls import prefer_requested_role, select_requested_role_candidates
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.evidence import refine_evidence
from ken.retrieval.intent import interpret
from ken.retrieval.model import Candidate, SearchRequest
from ken.retrieval.presentation import present
from ken.retrieval.ranking import candidate_document, rank_candidates

from replay import load_pools


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('pool', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--control', choices=['rrf', 'role', 'colbert', 'colbert-role', 'colbert-role-windows','minilm','minilm-role','minilm-role-windows'], required=True)
    parser.add_argument('--model-path', type=Path)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--query-tokens', type=int, default=64)
    parser.add_argument('--rerank-limit', type=int, default=100)
    parser.add_argument('--rank-unit', choices=['entity','passage'], default='passage')
    parser.add_argument('--max-pair-tokens', type=int, default=512)
    parser.add_argument('--purpose-pool', action='store_true')
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    dataset = load_dataset(base/'datasets/development.jsonl')
    cases = {c['id']: c for c in dataset}
    roots = {k: Path(v) for k,v in json.loads((base/'datasets/roots-development.json').read_text()).items()}
    digest = hashlib.sha256((args.pool/'candidates.jsonl').read_bytes()).hexdigest()
    pools = load_pools(args.pool, cases)
    selected = [c for c in dataset if c['id'] in pools][:args.limit]
    if hashlib.sha256((args.pool/'candidates.jsonl').read_bytes()).hexdigest() != digest:
        raise ValueError('candidate pool changed during loading; freeze it before replay')
    args.output.mkdir(parents=True, exist_ok=False)
    provenance = {'control': args.control, 'dataset_sha256': dataset.sha256,
        'pool_sha256': digest, 'case_ids': [c['id'] for c in selected], 'device': 'cpu',
        'source_receipt_sha256': verify_frozen_source(base.parents[1]),
        'performance_scope': 'prepared candidate-pool control; excludes public retrieval, not an end-to-end certificate'}
    judge = None
    if args.control.startswith('colbert'):
        if args.model_path is None or args.cache is None:
            raise ValueError('explicit local model and document-cache paths required')
        import torch
        from experimental_encoders import ColbertControl
        torch.set_num_threads(2)
        judge = ColbertControl(args.model_path, args.cache, query_length=args.query_tokens)
        provenance.update(model_revision=judge.revision, query_tokens=args.query_tokens,
                          document_tokens=judge.document_length, torch_threads=torch.get_num_threads())
        # Preparation is source-document work, not a cached answer to a query.
        # This control prepares only its pool and cannot certify full-index latency.
        started = time.perf_counter()
        documents = []
        for c in selected:
            request = SearchRequest(**request_for_case(c)); intent = interpret(request)
            purpose = 'identity' if intent.identity else intent.purpose
            for candidate in pools[c['id']]:
                if candidate.signals.get('exact'):
                    continue
                for p in {p.span:p for p in candidate.passages}.values():
                    documents.append(candidate_document(Candidate(candidate.entity, [p]), purpose=purpose))
        unique = list(dict.fromkeys(documents))
        for start in range(0, len(unique), 128):
            judge.cache.get_many(unique[start:start+128])
            if start % 1024 == 0:
                print(json.dumps({'preparing_documents': start, 'of': len(unique)}), flush=True)
        provenance['prepare_ms'] = (time.perf_counter()-started)*1000
        provenance['prepared_unique_documents'] = len(unique)
    elif args.control.startswith('minilm'):
        from experimental_encoders import MiniLMOnnxControl
        judge = MiniLMOnnxControl(args.model_path, max_tokens=args.max_pair_tokens)
        provenance.update(model_revision=judge.revision, max_pair_tokens=args.max_pair_tokens,
                          providers=['CPUExecutionProvider'])
    provenance.update(rerank_limit=args.rerank_limit, rank_unit=args.rank_unit, purpose_pool=args.purpose_pool)
    responses, timings, misses = [], [], []
    for c in selected:
        request = SearchRequest(**request_for_case(c))
        before = judge.cache.misses if args.control.startswith('colbert') else 0
        started = time.perf_counter()
        try:
            candidates = (select_requested_role_candidates(request, pools[c['id']], limit=args.rerank_limit)
                          if args.purpose_pool else pools[c['id']])
            matches = rank_candidates(request, candidates, judge=judge, rerank_limit=args.rerank_limit, rank_unit=args.rank_unit)
            if args.control in ('role', 'colbert-role', 'colbert-role-windows','minilm-role','minilm-role-windows'):
                matches = prefer_requested_role(request, matches)
            if args.control.endswith('-windows'):
                matches = refine_evidence(matches, roots[c['repo_id']], request, judge=judge)
            result = present(matches, roots[c['repo_id']], request, profile_version=provenance.get('model_revision', args.control)).to_dict()
        except Exception as exc:
            result = {'results': [], 'error': f'{type(exc).__name__}: {exc}'}
        timings.append((time.perf_counter()-started)*1000)
        misses.append(judge.cache.misses-before if args.control.startswith('colbert') else 0)
        responses.append({'id': c['id'], **result})
        with (args.output/'responses.jsonl').open('a') as f:
            f.write(json.dumps(responses[-1], ensure_ascii=False)+'\n')
        if len(responses) % 25 == 0:
            partial = evaluate(selected[:len(responses)], responses, roots=roots)
            print(json.dumps({'completed':len(responses), 'planned':len(selected),
                              'strict':partial['strict_top1'], 'identity':partial['identity_top1']}), flush=True)
    report = evaluate(selected, responses, roots=roots)
    import resource
    provenance.update(timings_ms=timings, document_cache_misses=misses, peak_rss_native=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    (args.output/'provenance.json').write_text(json.dumps(provenance, indent=2))
    (args.output/'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({k:report[k] for k in ('strict_top1','identity_top1','strata')}), flush=True)


if __name__ == '__main__':
    main()
