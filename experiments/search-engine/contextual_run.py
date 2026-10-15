"""Public-only live CPU search API worker; the parent owns strict grading."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import sqlite3
import sys
import time
from pathlib import Path
from importlib.metadata import version

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

import ken
from ken.bench.source_receipts import verify_frozen_source
from ken.bench.static_embeddings import StaticEmbeddingControl
from ken.db import connect
from ken.retrieval.contextual import ContextualRetriever, OwnerVectorSnapshot
from ken.retrieval.embedding_store import retrieval_snapshot
from ken.retrieval.model import EntityKey, SearchRequest
from ken.retrieval.numeric_ranker import NumericRanker
from ken.retrieval.owner_ranking import EvidenceReranker
from ken.retrieval.profile import ContextualRetrieval, EncoderSpec, EvidenceRanking, RetrievalProfile
from ken.retrieval.query_expansion import LocalQueryExpansion
from ken.retrieval.service import search


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def registered_context_spec(registration: dict) -> EncoderSpec:
    identity = {'model_id': registration['model_id'], 'upstream_revision': registration['upstream_revision'],
        'artifacts': registration['artifacts'], 'query_prefix': registration['query_prefix'],
        'document_projection': registration['document_projection'],
        'policy': 'CPU-raw-CLS-runtime-L2-no-padding-prefix512-batch1-v1',
        'runtime': {'numpy': np.__version__, 'onnxruntime': ort.__version__,
                    'tokenizers': version('tokenizers')}}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return EncoderSpec(registration['model_id'], digest, 'provided', sequence_length=512, batch_size=1)


class CPUContextEncoder:
    """Control-only adapter: pinned raw CLS, explicit CPU provider and no remote code."""
    def __init__(self, registration: dict):
        self.spec = EncoderSpec(**registration['spec'])
        if (self.spec != registered_context_spec(registration)
                or set(registration['artifacts']) != {'onnx/model.onnx', 'tokenizer.json'}):
            raise ValueError('contextual model registration differs from the actual CPU runtime')
        self.query_prefix = registration['query_prefix']
        self.calls: list[dict] = []
        root = Path(registration['root'])
        for name, digest in registration['artifacts'].items():
            if sha(root/name) != digest:
                raise ValueError('contextual model artifact changed')
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(root/'onnx/model.onnx'), sess_options=options,
                                           providers=['CPUExecutionProvider'])
        if self.session.get_providers() != ['CPUExecutionProvider']:
            raise ValueError('CPU contextual provider required')
        self.tokenizer = Tokenizer.from_file(str(root/'tokenizer.json'))
        self.tokenizer.no_padding()
        self.tokenizer.enable_truncation(max_length=512)

    def _encode(self, text: str) -> np.ndarray:
        started = time.perf_counter()
        tokens = self.tokenizer.encode(text)
        inputs = {'input_ids': np.array([tokens.ids], dtype=np.int64),
                  'attention_mask': np.array([tokens.attention_mask], dtype=np.int64)}
        vector = self.session.run(['sentence_embedding'], inputs)[0][0]
        if vector.shape != (768,) or not np.isfinite(vector).all():
            raise ValueError('invalid contextual embedding')
        self.calls.append({'tokens': len(tokens.ids), 'ms': (time.perf_counter()-started)*1000})
        return vector

    def embed_query(self, query: str) -> np.ndarray:
        return self._encode(self.query_prefix+query)

    def embed_passages(self, texts: list[str]) -> list[np.ndarray]:
        return [self._encode(text) for text in texts]


def main(*, expected_count: int | None = 25) -> None:
    parser = argparse.ArgumentParser()
    for name in ('requests', 'index', 'root', 'numeric-model', 'static-registration',
                 'translation-registration', 'context-registration', 'context-index',
                 'context-source-registration', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    for name in ('source-view-index', 'source-view-vectors', 'source-view-registration',
                 'source-view-model-registration'):
        parser.add_argument('--'+name, type=Path)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.requests.read_text().splitlines()]
    if (not rows or (expected_count is not None and len(rows) != expected_count)
            or any(set(r) != {'id', 'repo_id', 'request'} for r in rows)
            or len({r['id'] for r in rows}) != len(rows)
            or len({r['repo_id'] for r in rows}) != 1):
        raise ValueError('the registered nonempty unique public requests from one repository are required')
    args.output.mkdir(parents=True, exist_ok=False)
    engine_root = Path(ken.__file__).resolve().parents[2]
    receipt = verify_frozen_source(engine_root)
    started = time.perf_counter()
    registration = next(r for r in json.loads(args.static_registration.read_text())
                        if r['model_id'] == 'minishlab/potion-code-16M-v2')
    words = StaticEmbeddingControl(Path(registration['root']), registration)
    tr = json.loads(args.translation_registration.read_text())
    expansion = LocalQueryExpansion(Path(tr['root']), tr)
    model = NumericRanker.from_dict(json.loads(args.numeric_model.read_text()))
    expansions: list[dict] = []
    def expand_query(query: str) -> str:
        expanded = expansion(query)
        expansions.append({'original_sha256': hashlib.sha256(query.encode()).hexdigest(),
                           'expanded': expanded})
        return expanded
    ranker = EvidenceReranker(model, words, expand_query=expand_query,
                             expansion_revision=expansion.revision)
    view_args = (args.source_view_index, args.source_view_vectors, args.source_view_registration,
                 args.source_view_model_registration)
    if any(view_args) != all(view_args) or (ranker.feature_version == 3) != all(view_args):
        raise ValueError('the source-view model requires all of its registered source artifacts')
    context_registration = json.loads(args.context_registration.read_text())
    context = CPUContextEncoder(context_registration)
    prepared = json.loads(args.context_source_registration.read_text())
    if (prepared['graph_sha256'] != context_registration['artifacts']['onnx/model.onnx']
            or prepared['tokenizer_sha256'] != context_registration['artifacts']['tokenizer.json']
            or prepared['batch_size'] != 1 or prepared['sequence_length'] != 512
            or prepared['pooling'] != 'raw-CLS-explicit-L2'
            or prepared['document_projection'] != context_registration['document_projection']):
        raise ValueError('contextual source preparation differs from live query encoding')
    conn = connect(args.index)
    source = sqlite3.connect(f'file:{args.context_index}?mode=ro', uri=True)
    encoded = source.execute('SELECT o.entity,o.source_hash,v.vector FROM owners o '
                             'JOIN vectors v ON o.text_hash=v.hash ORDER BY o.entity').fetchall()
    source.close()
    repo = rows[0]['repo_id']
    with retrieval_snapshot(conn) as snapshot:
        if str(snapshot.generation) != str(prepared['repos'][repo]['generation']):
            raise ValueError('contextual source generation differs from prepared main index')
        vectors = OwnerVectorSnapshot(context.spec, snapshot.generation,
            tuple(EntityKey(**json.loads(r[0])) for r in encoded), tuple(r[1] for r in encoded),
            np.stack([np.frombuffer(r[2], dtype=np.float32) for r in encoded]))
    del encoded
    views = None
    view_receipts: dict[str, str] = {}
    if all(view_args):
        from source_view_assets import load_source_views

        views, view_receipts = load_source_views(index=args.source_view_index,
            vectors=args.source_view_vectors, registration=args.source_view_registration,
            model_registration=args.source_view_model_registration, repo=repo, source=vectors,
            original_registration=args.context_registration, full_context_index=args.context_index)
    runtime = ContextualRetriever(context, vectors, source_views=views)
    profile = RetrievalProfile(words.spec, words.spec, contextual=ContextualRetrieval(context.spec,
        view_model=views.model if views else None),
        evidence=EvidenceRanking(model.fingerprint, words.spec, expansion.revision,
                                 feature_version=ranker.feature_version, evidence_version=2))
    metadata = {'scope': f'ALL{len(rows)} live API + canonical JSON; public source/requests only; CPU; '
                         'one repo-excluded model; not default/acceptance/final uncontended certificate',
        'engine_root': str(engine_root), 'engine_receipt_sha256': receipt,
        'requests_sha256': sha(args.requests), 'numeric_model_sha256': sha(args.numeric_model),
        'context_index_sha256': sha(args.context_index),
        'source_preparation_sha256': sha(args.context_source_registration),
        'context_registration_sha256': sha(args.context_registration),
        'profile': profile.to_dict(), 'profile_sha256': profile.fingerprint,
        'encoder': words.identity, 'expansion': expansion.identity,
        'context': context_registration, 'asset_load_ms': (time.perf_counter()-started)*1000,
        'python': sys.version, 'platform': platform.platform(), 'machine': platform.machine(),
        'index': str(args.index), 'root': str(args.root), 'timings': [],
        'indexed_files': conn.execute('SELECT COUNT(*) FROM ci_files').fetchone()[0]}
    if view_receipts:
        metadata['source_view_artifacts'] = view_receipts
    (args.output/'registration.json').write_text(json.dumps(metadata, indent=2))
    try:
        encoders = {'identity': words, 'behavior': words}
        cold = time.perf_counter()
        search(conn, args.root, SearchRequest('prepare CPU source index for search'),
               profile=profile, encoders=encoders, owner_ranker=ranker, contextual_retriever=runtime)
        metadata['source_prepare_ms'] = (time.perf_counter()-cold)*1000
        with (args.output/'responses.jsonl').open('w') as output:
            for row in rows:
                request = SearchRequest(**row['request'])
                started = time.perf_counter()
                before = len(context.calls)
                before_expansion = len(expansions)
                try:
                    response = search(conn, args.root, request, profile=profile,
                        encoders=encoders, owner_ranker=ranker, contextual_retriever=runtime).to_dict()
                    json.dumps(response, ensure_ascii=False, separators=(',', ':'))
                except Exception as exc:
                    response = {'results': [], 'error': f'{type(exc).__name__}: {exc}'}
                metadata['timings'].append({'id': row['id'], 'ms': (time.perf_counter()-started)*1000,
                    'context_calls': context.calls[before:], 'expansions': expansions[before_expansion:]})
                output.write(json.dumps({'id': row['id'], **response}, ensure_ascii=False)+'\n')
                output.flush()
        metadata['peak_rss_native'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        metadata['heavy_runtimes_imported'] = sorted(name for name in (
            'torch', 'transformers', 'sentence_transformers') if name in sys.modules)
        if verify_frozen_source(engine_root) != receipt:
            raise ValueError('engine source changed during the run')
        if any(sha(Path(path)) != digest for path, digest in view_receipts.items()):
            raise ValueError('mapped source view artifacts changed during the run')
        (args.output/'performance.json').write_text(json.dumps(metadata, indent=2))
        print(json.dumps({'repo': repo, 'queries': len(rows),
                          'peak_rss_native': metadata['peak_rss_native']}), flush=True)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
