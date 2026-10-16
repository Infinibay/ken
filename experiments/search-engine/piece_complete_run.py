"""Fresh complete CPU retrieval, requested-piece ranking and fixed neural fusion.

This producer has no reference/grading imports. Its controller closes ALL200
outputs before a separate report process is allowed to read development labels.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

import ken
import numpy as np
from ken.bench.source_receipts import verify_frozen_source
from ken.retrieval.intent import requested_piece_path
from ken.retrieval.model import SearchRequest
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.piece_ranking import PieceReranker
from ken.retrieval.ranking_trace import RankingTrace
from ken.retrieval.reranker_fusion import fused_reranker_order
from ettin_cpu import CPUReranker, sha
from piece_candidates import candidates_from_trace
from ranking_diagnostics import piece_order
from verifiable_cpu_run import PreparedKen
from verifiable_guard import verify_source_preparation
from verifiable_pieces import canonical, digest


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def load_compact_policy(workspace):
    """Use the already measured v102 ranking input projection, byte for byte."""
    path = workspace / 'output/frozen/verifiable-fp32-68m-control-v110/verifiable_pieces.py'
    expected = '2eee66d589d52c3f8b6146cd6069712939f83bdd062d868281d521b8dfba0a8e'
    if sha(path) != expected:
        raise ValueError('compact ranking-input projection changed')
    spec = importlib.util.spec_from_file_location('ken_compact_ranking_input_v102', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


def main():
    parser = argparse.ArgumentParser()
    for name in ('workspace', 'public-cases', 'source-metadata', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--repo')
    args = parser.parse_args(); w = args.workspace.resolve()
    engine = Path(ken.__file__).resolve().parents[2]
    source_receipt = verify_frozen_source(engine)
    roots, preparation = verify_source_preparation(w, args.source_metadata)
    compact, compact_path = load_compact_policy(w)
    piece_root = w / 'output/development/piece-path-identity-control-v126'
    piece_reg = json.loads((piece_root / 'registration.json').read_text())
    if piece_reg['status'] != 'ALL200 repository-excluded orders closed':
        raise ValueError('piece model control is not closed')
    neural_path = w / 'output/models/ettin-68m-fp32-complete-v110/assembly.json'
    neural_registration = json.loads(neural_path.read_text())
    if sha(neural_path) != 'f77bf04eeda31c567a294b3293ea371d461f42587991a7b235b0d724b428777f':
        raise ValueError('existing 68M model changed')
    old_root = w / 'output/development/verifiable-fp32-68m-control-v110'
    old_reg = json.loads((old_root / 'registration.json').read_text())
    if old_reg['status'] != 'ALL200 precision orders closed without Gold':
        raise ValueError('historical pool control is not closed')
    pins = {str(path): sha(path) for path in (compact_path, neural_path,
        piece_root / 'registration.json', piece_root / 'answers.jsonl',
        old_root / 'registration.json', args.public_cases)}
    for path, expected in old_reg['input_pins'].items():
        if path.endswith('/pools.jsonl'):
            if sha(path) != expected:
                raise ValueError('closed compact-card reference changed')
            pins[path] = expected
    for fold in piece_reg['folds']:
        path = piece_root / (fold['held_out'] + '-numeric.json')
        if sha(path) != fold['model_sha256'] or fold['held_out'] in fold['training_repos']:
            raise ValueError('repository exclusion/model receipt failed')
        pins[str(path)] = sha(path)
    cases = rows(args.public_cases)
    if len(cases) != 200 or len({c['id'] for c in cases}) != 200 or {c['repo_id'] for c in cases} != set(roots):
        raise ValueError('the complete original ALL200 query set is required')
    if sha(args.public_cases) != old_reg['public_cases_sha256']:
        raise ValueError('queries differ from the historical control')
    args.output.mkdir(parents=True, exist_ok=False)
    if args.repo is None:
        registration = {'scope': 'ALL200 exposed-development complete prepared CPU pipeline, repository-excluded piece forests; not private acceptance or public default',
            'policy': 'Single change from v133: neural intra-op CPU budget2 to4; keep batch1, tokens512, FP32 weights, candidates, forests and RRF60 weight0.5. Context encoder/translation remain CPU2 threads; fresh complete search, no Gold or score reuse.',
            'runtime_policy': {'batch_size': 1, 'intra_op_threads': 4, 'pair_limit': 512},
            'source_receipt': source_receipt, 'preparation': preparation, 'input_pins': pins,
            'timing_scope': 'Native retrieval, compact cards, actual trace projection, piece features/forest, fresh tokenization/inference, fixed fusion, source validation and answer serialization; prepared asset loading/warmup separate; diagnostic output excluded.',
            'status': 'registered before fresh queries; no Gold', 'closed': {}}
        (args.output / 'registration.json').write_text(json.dumps(registration, indent=2))
        for repo in sorted(roots):
            command = [sys.executable, __file__, '--workspace', str(w), '--public-cases', str(args.public_cases),
                '--source-metadata', str(args.source_metadata), '--output', str(args.output / repo), '--repo', repo]
            with (args.output / (repo + '.log')).open('w') as log:
                subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
            registration['closed'][repo] = {name: sha(args.output / repo / name)
                for name in ('answers.jsonl', 'orders.jsonl', 'performance.json')}
            print(json.dumps({'repo': repo, 'complete_cpu_worker_closed': True}), flush=True)
        if verify_frozen_source(engine) != source_receipt or any(sha(p) != v for p, v in pins.items()):
            raise ValueError('producer/input changed')
        registration['status'] = 'ALL200 complete CPU outputs closed without Gold'
        (args.output / 'registration.json').write_text(json.dumps(registration, indent=2))
        return

    repo = args.repo
    if repo not in roots:
        raise ValueError('unknown repository')
    cases = [c for c in cases if c['repo_id'] == repo]
    expected = {}
    for path in pins:
        if path.endswith('/' + repo + '/pools.jsonl'):
            expected.update({r['id']: r for r in rows(path)})
    if set(expected) != {c['id'] for c in cases}:
        raise ValueError('missing fixed native pool reference')
    piece_expected = {r['id']: r for r in rows(piece_root / 'answers.jsonl')}
    fold = next(f for f in piece_reg['folds'] if f['held_out'] == repo)
    numeric = NumericRanker.from_dict(json.loads((piece_root / (repo + '-numeric.json')).read_text()))
    if numeric.fingerprint != fold['model_fingerprint']:
        raise ValueError('piece model fingerprint mismatch')
    started = time.perf_counter()
    runtime = PreparedKen(w, repo, roots[repo], w / 'output/analysis/c-source-reindex-v66c/indices' / (repo + '.db'))
    ranker = PieceReranker(numeric, runtime.words, stem_words=runtime.ranker.stem_words)
    neural = CPUReranker(neural_registration,batch_size=1,intra_op_threads=4)
    load_ms = (time.perf_counter() - started) * 1000
    inventory_bytes = ''.join(canonical(r) + '\n' for r in runtime.catalog.source_inventory()).encode()
    import hashlib
    catalog = json.loads((w / 'output/analysis/verifiable-pieces-catalog-v98/receipt.json').read_text())
    if hashlib.sha256(inventory_bytes).hexdigest() != catalog['repos'][repo]['inventory_sha256']:
        raise ValueError('source catalog differs')
    del inventory_bytes
    started = time.perf_counter()
    runtime.pool({'query': 'find code that prepares a value', 'target_kind': 'symbol'}, card_builder=compact.piece_pool)
    runtime.ranker.prepare_query('¿Dónde convierte un valor de entrada?')
    neural.score('find a stored value', ['class Cache:\n    def get(self,key): return self.data[key]'] * 10)
    warmup_ms = (time.perf_counter() - started) * 1000
    timings = []; cache = {}
    try:
        with (args.output / 'answers.jsonl').open('w') as answers, (args.output / 'orders.jsonl').open('w') as orders:
            for case in cases:
                started = time.perf_counter()
                trace = RankingTrace(request_id=case['id'])
                cards, expanded, exact, count = runtime.pool(case, trace=trace, card_builder=compact.piece_pool)
                pool_hash = digest({'cards': cards, 'expanded': expanded, 'exact': exact})
                if pool_hash != expected[case['id']]['pool_sha256']:
                    raise ValueError('fresh native compact cards/pool differ: ' + case['id'])
                native_ms = (time.perf_counter() - started) * 1000
                stage = time.perf_counter()
                data = trace.to_dict(include_query=True)
                data['pieces'] = piece_order(data['owners'], case['target_kind'], runtime.catalog)
                if [p['unit'] for p in data['pieces'][:20]] != [c['unit'] for c in cards]:
                    raise ValueError('actual native trace and card projection disagree')
                candidates = candidates_from_trace(data, runtime.catalog, cache)
                request = SearchRequest(case['query'], piece_kind=case['target_kind'])
                ranked = ranker.rank(request, candidates, expanded_query=expanded)
                by_identity = {canonical(c['unit']): i for i, c in enumerate(cards[:10])}
                piece_indices = [by_identity[canonical({'target_kind': m.piece.kind, 'path': m.piece.path,
                    'entity': m.piece.entity.to_dict() if m.piece.entity else None,
                    'module_name': compact.module_name(m.piece.path) if m.piece.kind == 'module' else None})]
                    for m in ranked]
                if [cards[i]['unit'] for i in piece_indices] != piece_expected[case['id']]['units']:
                    raise ValueError('fresh piece model differs from its closed control: ' + case['id'])
                piece_ms = (time.perf_counter() - stage) * 1000
                texts = [compact.card_text(cards[i]) for i in piece_indices]
                if exact:
                    scores = [0.] * len(texts)
                    details = {'token_ms': 0., 'inference_ms': 0., 'pair_tokens': [], 'truncated_documents': 0}
                    fused = list(range(len(texts)))
                else:
                    scores, details = neural.score(expanded, texts)
                    fused = fused_reranker_order(scores)
                order = [piece_indices[i] for i in fused]
                named_path = requested_piece_path(request)
                if named_path:
                    order.sort(key=lambda i: cards[i]['unit']['path'] != named_path)
                if sorted(order) != list(range(min(10, len(cards)))):
                    raise ValueError('top10 membership changed')
                selected = cards[order[0]] if order else None
                if selected is not None:
                    compact.validate_card(selected, runtime.catalog)
                answer = {'id': case['id'], 'repo_id': repo, 'target_kind': case['target_kind'],
                    'pool_sha256': pool_hash, 'card': selected, 'units': [cards[i]['unit'] for i in order]}
                encoded = canonical(answer)
                elapsed = (time.perf_counter() - started) * 1000
                timings.append({'id': case['id'], 'target_kind': case['target_kind'], 'ms': elapsed,
                    'native_ms': native_ms, 'piece_ms': piece_ms, 'candidate_owners': count,
                    'exact_bypass': exact, **details})
                answers.write(encoded + '\n'); answers.flush()
                orders.write(canonical({'id': case['id'], 'native_units': [c['unit'] for c in cards[:10]],
                    'piece_order': piece_indices, 'piece_scores': [m.score for m in ranked],
                    'neural_scores_in_piece_order': scores, 'fusion_order_in_piece_order': fused,
                    'final_order': order}) + '\n'); orders.flush()
                del trace, data, candidates, ranked
        heavy = [m for m in ('torch', 'transformers', 'sentence_transformers') if m in sys.modules]
        if heavy or verify_frozen_source(engine) != source_receipt or any(sha(p) != v for p, v in pins.items()):
            raise ValueError('CPU/source/input policy failed')
        if any(sha(p) != v for p, v in runtime.view_receipts.items()):
            raise ValueError('source views changed')
        performance = {'scope': 'complete prepared CPU query, source-authenticated; warmup/load separate',
            'repo': repo, 'source_receipt': source_receipt, 'input_pins': pins,
            'indexed_files': runtime.indexed_files, 'asset_load_ms': load_ms, 'warmup_ms': warmup_ms,
            'platform': platform.platform(), 'machine': platform.machine(), 'python': sys.version,
            'timings': timings, 'peak_rss_native': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'rss_unit': 'bytes' if sys.platform == 'darwin' else 'KiB', 'heavy_imports': heavy,
            'providers': neural.session.get_providers()}
        (args.output / 'performance.json').write_text(json.dumps(performance, indent=2))
        print(json.dumps({'repo': repo, 'queries': len(cases), 'p50_ms': float(np.median([r['ms'] for r in timings])),
            'peak_rss_native': performance['peak_rss_native']}), flush=True)
    finally:
        runtime.conn.close()


if __name__ == '__main__':
    main()
