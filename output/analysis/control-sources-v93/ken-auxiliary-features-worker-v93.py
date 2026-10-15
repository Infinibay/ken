"""Source93 public requests to the unchanged live251 evidence features; no labels."""
import argparse
import gc
import hashlib
import json
from pathlib import Path
import resource
import sqlite3
import sys
import time

import ken
import numpy as np

R = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
E = Path(ken.__file__).resolve().parents[2]
sys.path.insert(0, str(E/'experiments/search-engine'))
from contextual_run import CPUContextEncoder
from source_view_assets import load_source_views
from ken.bench.source_receipts import verify_frozen_source
from ken.bench.static_embeddings import StaticEmbeddingControl
from ken.db import connect
from ken.retrieval.candidates import owner_descriptions, retrieve_contextual
from ken.retrieval.contextual import ContextualRetriever, OwnerVectorSnapshot
from ken.retrieval.contextual_features import CONTEXTUAL_FEATURES, SOURCE_VIEW_FEATURES, contextual_features
from ken.retrieval.embedding_store import retrieval_snapshot
from ken.retrieval.evidence_features import FEATURES, evidence_features
from ken.retrieval.model import EntityKey, SearchRequest
from ken.retrieval.owner_ranking import EvidenceReranker
from ken.retrieval.profile import ContextualRetrieval, EvidenceRanking, RetrievalProfile
from ken.retrieval.query_expansion import LocalQueryExpansion


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


parser = argparse.ArgumentParser()
for name in ('source', 'requests', 'output'):
    parser.add_argument('--'+name, type=Path, required=True)
parser.add_argument('--repo', required=True)
parser.add_argument('--source-registration-sha256', required=True)
parser.add_argument('--requests-sha256', required=True)
args = parser.parse_args()
S = args.source; O = args.output
assert sha(S/'registration.json') == args.source_registration_sha256
source = json.loads((S/'registration.json').read_text()); receipt = verify_frozen_source(E)
assert source['complete'] and source['engine_receipt'] == receipt
assert len(source['source_repos']) == len(source['context_repos']) == len(source['views_repos']) == 8
assert all(sha(path) == digest for path, digest in source['inputs'].items())
by_repo = {s['name']: s for s in source['repositories']}; assert args.repo in by_repo
root = Path(by_repo[args.repo]['root'])
assert root.resolve().is_relative_to(Path('/private/tmp/ken-search-auxiliary-training-20261015/repos').resolve())
assert all(sha(root/path) == digest for path, digest in source['source_repos'][args.repo]['file_hashes'].items())
assert sha(args.requests) == args.requests_sha256
rows = list(map(json.loads, args.requests.read_text().splitlines()))
assert len(rows) == len({r['id'] for r in rows}) == 12
assert all(set(r) == {'id', 'repo_id', 'request'} and r['repo_id'] == args.repo for r in rows)
O.mkdir(exist_ok=False)
static_path = R/'output/models/static-comparison-registration.json'
translation_path = R/'output/models/es-en-cpu-registration-v21.json'
context_path = R/'output/models/cpu-context-registration-v42.json'
registration = next(r for r in json.loads(static_path.read_text()) if r['model_id'] == 'minishlab/potion-code-16M-v2')
words = StaticEmbeddingControl(Path(registration['root']), registration)
translation = json.loads(translation_path.read_text()); expansion = LocalQueryExpansion(Path(translation['root']), translation)
context = CPUContextEncoder(json.loads(context_path.read_text()))
index = S/'indices'/f'{args.repo}.db'; full = S/'context'/f'{args.repo}.db'
assert sha(index) == source['source_repos'][args.repo]['new_source_index_sha256']
assert sha(full) == source['context_repos'][args.repo]['context_index_sha256']
conn = connect(index)
db = sqlite3.connect(f'file:{full}?mode=ro', uri=True)
encoded = db.execute('SELECT o.entity,o.source_hash,v.vector FROM owners o JOIN vectors v ON o.text_hash=v.hash ORDER BY o.entity').fetchall(); db.close()
with retrieval_snapshot(conn) as snapshot:
    generation = snapshot.generation
    assert str(generation) == str(source['context_repos'][args.repo]['generation'])
    vectors = OwnerVectorSnapshot(context.spec, generation, tuple(EntityKey(**json.loads(r[0])) for r in encoded),
        tuple(r[1] for r in encoded), np.stack([np.frombuffer(r[2], dtype=np.float32) for r in encoded]))
del encoded
views, view_receipts = load_source_views(index=S/'views'/f'{args.repo}-source.db',
    vectors=S/'views'/f'{args.repo}-vectors.npy', registration=S/'views/registration.json',
    model_registration=S/'views/model-registration.json', repo=args.repo, source=vectors,
    original_registration=context_path, full_context_index=full)
runtime = ContextualRetriever(context, vectors, source_views=views)
profile = RetrievalProfile(words.spec, words.spec, contextual=ContextualRetrieval(context.spec, view_model=views.model),
    evidence=EvidenceRanking(hashlib.sha256(b'auxiliary93-proposals-only-no-numeric-model').hexdigest(),
        words.spec, expansion.revision, feature_version=3, evidence_version=3))
names = (*FEATURES, *CONTEXTUAL_FEATURES, *SOURCE_VIEW_FEATURES); assert len(names) == 251
manifest = {'scope': 'ALL12 auxiliary publicrequests, live source7/full/view proposals and original251features; no labels/references/numericmodel/fit',
    'script_sha256': sha(__file__), 'engine_receipt': receipt, 'generation': generation, 'profile': profile.to_dict(),
    'features': names, 'source_registration_sha256': sha(S/'registration.json'),
    'inputs': {str(p): sha(p) for p in (args.requests, static_path, translation_path, context_path, index, full)},
    'view_receipts': view_receipts, 'timings': [], 'exact_bypass_ids': []}
(O/'registration.json').write_text(json.dumps(manifest, indent=2))
values, qids, indexes = [], [], []
with (O/'candidates.jsonl').open('w') as output:
    for row in rows:
        started = time.perf_counter(); request = SearchRequest(**row['request'])
        candidates, expanded = retrieve_contextual(conn, root, request, profile, runtime=runtime,
            expand_query=expansion, encoders={'identity': words, 'behavior': words})
        descriptions = owner_descriptions(conn, candidates)
        matrix = evidence_features(request, candidates, descriptions, encoder=words,
            stem_words=EvidenceReranker.stem_words, expanded_query=expanded)
        exact = len(candidates) == 1 and bool(candidates[0].signals.get('exact'))
        extra = np.zeros((1, len(CONTEXTUAL_FEATURES)+len(SOURCE_VIEW_FEATURES))) if exact else contextual_features(candidates, source_views=True).values
        numeric = np.column_stack((matrix.values, extra))
        assert numeric.shape == (len(candidates), 251) and len(candidates) and np.isfinite(numeric).all()
        if exact: manifest['exact_bypass_ids'].append(row['id'])
        values.extend(numeric); qids.extend([row['id']]*len(candidates)); indexes.extend(range(len(candidates)))
        saved = {'id': row['id'], 'expanded_query': expanded, 'candidates': [
            {'path': c.entity.path, 'entity': c.entity.to_dict(), 'signals': c.signals, 'passages': [
                {'start_line': p.span.start_line, 'end_line': p.span.end_line, 'signals': p.signals} for p in c.passages]} for c in candidates]}
        output.write(json.dumps(saved, ensure_ascii=False)+'\n'); output.flush()
        manifest['timings'].append({'id': row['id'], 'candidates': len(candidates), 'ms': (time.perf_counter()-started)*1000})
        print(json.dumps({'prepared_query': row['id'], 'candidates': len(candidates)}), flush=True)
        context.calls.clear(); gc.collect()
np.savez_compressed(O/'features.npz', x=np.asarray(values).reshape(-1, 251), qid=qids, index=indexes)
with retrieval_snapshot(conn) as snapshot: assert snapshot.generation == generation
conn.close()
assert all(sha(path) == digest for path, digest in manifest['inputs'].items())
assert all(sha(path) == digest for path, digest in view_receipts.items())
assert sha(S/'registration.json') == args.source_registration_sha256 and verify_frozen_source(E) == receipt
assert all(sha(root/path) == digest for path, digest in source['source_repos'][args.repo]['file_hashes'].items())
assert not any(name in sys.modules for name in ('torch', 'transformers', 'sentence_transformers'))
manifest.update(complete=True, features_sha256=sha(O/'features.npz'), candidates_sha256=sha(O/'candidates.jsonl'),
    peak_rss_native=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
(O/'registration.json').write_text(json.dumps(manifest, indent=2))
