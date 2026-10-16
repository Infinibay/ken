"""Public-only runner for prelocked datasets and immutable engine variants.

This caller reuses each frozen engine's actual retrieval, piece model, tokenizer,
ONNX scorer and fusion. It never imports references or scores expected answers.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

import ken
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.intent import requested_piece_path
from ken.retrieval.model import SearchRequest
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.piece_ranking import PieceReranker
from ken.retrieval.ranking_trace import RankingTrace
from ken.retrieval.reranker_fusion import fused_reranker_order
from ettin_cpu import CPUReranker, sha
from piece_candidates import candidates_from_trace
from piece_complete_run import load_compact_policy
from ranking_diagnostics import piece_order
from verifiable_cpu_run import PreparedKen
from verifiable_guard import verify_source_preparation
from verifiable_pieces import canonical, digest


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def main():
    p = argparse.ArgumentParser()
    for name in ('workspace', 'lock', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--variant', required=True)
    p.add_argument('--repo')
    args = p.parse_args(); w = args.workspace.resolve()
    lock = json.loads(args.lock.read_text()); variant = lock['variants'][args.variant]
    engine = Path(ken.__file__).resolve().parents[2]
    if engine != Path(variant['engine_root']).resolve() or verify_frozen_source(engine) != variant['source_receipt']:
        raise ValueError('loaded engine differs from prelocked variant')
    if sha(__file__) != lock['runner_sha256']:
        raise ValueError('evaluation caller changed after lock')
    for path, expected in lock['input_pins'].items():
        if sha(path) != expected:
            raise ValueError('prelocked public input/asset changed')
    roots, preparation = verify_source_preparation(w, Path(lock['source_metadata']))
    cases = rows(lock['public_cases'])
    if len(cases) != lock['queries'] or len({r['id'] for r in cases}) != len(cases):
        raise ValueError('unexpected or duplicate public queries')
    if any('acceptable_units' in r or 'expected' in r or 'gold' in r for r in cases):
        raise ValueError('references may not enter the public producer')
    args.output.mkdir(parents=True, exist_ok=False)
    if args.repo is None:
        registration = {'scope': 'Original200 development-only generic-model candidate; old data may overlap training; no new200or privateGold in producer',
            'lock_sha256': sha(args.lock), 'variant': args.variant, 'variant_policy': variant,
            'runner_sha256': sha(__file__), 'preparation': preparation,
            'status': 'registered before public queries', 'closed': {}}
        (args.output / 'registration.json').write_text(json.dumps(registration, indent=2))
        for repo in sorted({c['repo_id'] for c in cases}):
            if repo not in roots:
                raise ValueError('unprepared repository')
            command = [sys.executable, __file__, '--workspace', str(w), '--lock', str(args.lock),
                '--output', str(args.output / repo), '--variant', args.variant, '--repo', repo]
            with (args.output / (repo + '.log')).open('w') as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
            registration['closed'][repo] = {name: sha(args.output / repo / name)
                for name in ('answers.jsonl', 'performance.json')}
            print(json.dumps({'variant': args.variant, 'repo': repo, 'closed': True}), flush=True)
        if sha(__file__) != lock['runner_sha256'] or verify_frozen_source(engine) != variant['source_receipt']:
            raise ValueError('producer changed during validation')
        registration['status'] = 'ALL original-development outputs closed without Gold'
        (args.output / 'registration.json').write_text(json.dumps(registration, indent=2))
        return

    repo = args.repo; cases = [c for c in cases if c['repo_id'] == repo]
    if not cases or repo not in roots:
        raise ValueError('empty/unprepared repository')
    compact, _ = load_compact_policy(w)
    piece_root = w / 'output/development/piece-path-identity-control-v126'
    piece_reg = json.loads((piece_root / 'registration.json').read_text())
    if variant.get('piece_numeric_model'):
        numeric = NumericRanker.from_dict(json.loads(Path(variant['piece_numeric_model']).read_text()))
        if numeric.fingerprint != variant['piece_numeric_fingerprint']:
            raise ValueError('generic piece forest differs from prospective pin')
    else:
        fold = next(f for f in piece_reg['folds'] if f['held_out'] == repo)
        numeric = NumericRanker.from_dict(json.loads((piece_root / (repo + '-numeric.json')).read_text()))
        if repo in fold['training_repos'] or numeric.fingerprint != fold['model_fingerprint']:
            raise ValueError('repository-excluded piece forest differs')
    started = time.perf_counter()
    runtime = PreparedKen(w, repo, roots[repo], w / 'output/analysis/c-source-reindex-v66c/indices' / (repo + '.db'))
    ranker = PieceReranker(numeric, runtime.words, stem_words=runtime.ranker.stem_words)
    neural = CPUReranker(json.loads(Path(lock['neural_registration']).read_text()), **variant['neural_kwargs'])
    load_ms = (time.perf_counter() - started) * 1000
    inventory = ''.join(canonical(r) + '\n' for r in runtime.catalog.source_inventory()).encode()
    catalog_receipt = json.loads((w / 'output/analysis/verifiable-pieces-catalog-v98/receipt.json').read_text())
    if hashlib.sha256(inventory).hexdigest() != catalog_receipt['repos'][repo]['inventory_sha256']:
        raise ValueError('actual source catalog differs from authenticated preparation')
    del inventory
    started = time.perf_counter()
    runtime.pool({'query': 'find code that prepares a value', 'target_kind': 'symbol'}, card_builder=compact.piece_pool)
    runtime.ranker.prepare_query('¿Dónde convierte un valor de entrada?')
    neural.score('find a stored value', ['def get(key): return data[key]'] * 10)
    warmup_ms = (time.perf_counter() - started) * 1000
    timings = []; cache = {}
    try:
        with (args.output / 'answers.jsonl').open('w') as output:
            for case in cases:
                started = time.perf_counter(); cpu_started = time.process_time()
                trace = RankingTrace(request_id=case['id'])
                cards, expanded, exact, count = runtime.pool(case, trace=trace, card_builder=compact.piece_pool)
                data = trace.to_dict(include_query=True)
                data['pieces'] = piece_order(data['owners'], case['target_kind'], runtime.catalog)
                if [c['unit'] for c in cards] != [p['unit'] for p in data['pieces'][:20]]:
                    raise ValueError('source piece projection differs from actual cards')
                candidates = candidates_from_trace(data, runtime.catalog, cache)
                request = SearchRequest(case['query'], piece_kind=case['target_kind'])
                ranked = ranker.rank(request, candidates, expanded_query=expanded)
                by_identity = {canonical(c['unit']): i for i, c in enumerate(cards[:10])}
                existing = [by_identity[canonical({'target_kind': m.piece.kind, 'path': m.piece.path,
                    'entity': m.piece.entity.to_dict() if m.piece.entity else None,
                    'module_name': compact.module_name(m.piece.path) if m.piece.kind == 'module' else None})]
                    for m in ranked]
                if exact:
                    scores = [0.] * len(existing); fused = list(range(len(existing)))
                    details = {'inference_ms': 0., 'token_ms': 0., 'pair_tokens': [], 'truncated_documents': 0}
                else:
                    scores, details = neural.score(expanded, [compact.card_text(cards[i]) for i in existing])
                    fused = fused_reranker_order(scores)
                order = [existing[i] for i in fused]
                named = requested_piece_path(request)
                if named:
                    order.sort(key=lambda i: cards[i]['unit']['path'] != named)
                if sorted(order) != list(range(min(10, len(cards)))):
                    raise ValueError('top10 membership changed')
                selected = cards[order[0]] if order else None
                if selected is not None:
                    compact.validate_card(selected, runtime.catalog)
                result = {'id': case['id'], 'repo_id': repo, 'target_kind': case['target_kind'],
                    'card': selected, 'units': [cards[i]['unit'] for i in order],
                    'native_units': [c['unit'] for c in cards[:10]], 'piece_order': existing,
                    'neural_scores_in_piece_order': scores,
                    'pool_sha256': digest({'cards': cards, 'expanded': expanded, 'exact': exact})}
                encoded = canonical(result)
                timings.append({'id': case['id'], 'ms': (time.perf_counter() - started) * 1000,
                    'cpu_ms': (time.process_time() - cpu_started) * 1000,
                    'target_kind': case['target_kind'], 'exact_bypass': exact, 'candidate_owners': count, **details})
                output.write(encoded + '\n'); output.flush()
                del trace, data, candidates, ranked
        if verify_frozen_source(engine) != variant['source_receipt'] or sha(__file__) != lock['runner_sha256']:
            raise ValueError('source/producer changed')
        if any(sha(path) != expected for path, expected in lock['input_pins'].items()):
            raise ValueError('prelocked input changed during validation')
        if any(sha(path) != expected for path, expected in runtime.view_receipts.items()):
            raise ValueError('prepared source views changed')
        heavy = [m for m in ('torch', 'transformers', 'sentence_transformers') if m in sys.modules]
        if heavy or neural.session.get_providers() != ['CPUExecutionProvider']:
            raise ValueError('CPU-only lightweight runtime requirement failed')
        performance = {'repo': repo, 'source_receipt': variant['source_receipt'], 'variant_policy': variant,
            'indexed_files': runtime.indexed_files, 'asset_load_ms': load_ms, 'warmup_ms': warmup_ms,
            'timings': timings, 'peak_rss_native': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'rss_unit': 'bytes' if sys.platform == 'darwin' else 'KiB', 'platform': platform.platform(),
            'heavy_imports': heavy, 'providers': neural.session.get_providers()}
        (args.output / 'performance.json').write_text(json.dumps(performance, indent=2))
    finally:
        runtime.conn.close()


if __name__ == '__main__':
    main()
