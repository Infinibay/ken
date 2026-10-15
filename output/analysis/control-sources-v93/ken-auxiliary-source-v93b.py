"""Prepare the complete auxiliary source corpus without opening any queries."""
import argparse
import collections
import dataclasses
import gc
import hashlib
import json
import os
from pathlib import Path
import resource
import sqlite3
import subprocess
import sys
import time

import ken
import numpy as np

R = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
E = Path(ken.__file__).resolve().parents[2]
sys.path.insert(0, str(E/'experiments/search-engine'))
from contextual_run import CPUContextEncoder, registered_context_spec
from ken.bench.source_receipts import verify_frozen_source
from ken.bench.static_embeddings import StaticEmbeddingControl
from ken.db import connect, init_schema
from ken.gitignore_filter import iter_files
from ken.retrieval.description import describe_owner
from ken.retrieval.indexing import index_project
from ken.retrieval.passages import EXTRACTOR_VERSION
from ken.retrieval.profile import active_profile
from ken.retrieval.source_views import SOURCE_VIEW_PROJECTION, owner_view_texts
from ken.retrieval.storage import load_passage_map


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def clean_pin(root, revision):
    assert subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip() == revision
    assert not subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain'], text=True)


def grouped(index):
    conn = connect(index)
    groups = collections.defaultdict(list)
    for passage in load_passage_map(conn).values():
        groups[passage.entity].append(passage)
    generation = conn.execute("SELECT value FROM meta WHERE key='retrieval_generation'").fetchone()[0]
    conn.close()
    return groups, generation


def normalized(vector):
    value = np.asarray(vector, dtype=np.float32)
    assert value.shape == (768,) and np.isfinite(value).all()
    norm = np.linalg.norm(value)
    assert np.isfinite(norm) and norm > 1e-9
    result = (value/norm).astype(np.float32)
    assert np.isclose(np.linalg.norm(result), 1., rtol=1e-5, atol=1e-5)
    return result


parser = argparse.ArgumentParser()
parser.add_argument('--metadata', type=Path, required=True)
parser.add_argument('--metadata-sha256', required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
receipt = verify_frozen_source(E)
assert receipt == '4ebee803348ded840b948be0912e58924faf6ae218cd107d1cbb6963cd2f892d'
expected_inputs = {
 R/'output/models/static-comparison-registration.json': 'e7127a2c645b75c493de9dd8826d9ecb8078dc7c758a86ca49f97b84f68aed1b',
 R/'output/models/cpu-context-registration-v42.json': '9de3e49ef29ce4672b5b77dfca0078a4eba82412a64c318cafe048b512787d7a',
 R/'output/analysis/c-source-reindex-v66c/indices/attrs.db': 'e64db6c1fa5be0181c77f712be2155d0971e1bbae6a6da0c15edc766da4afae1'}
assert all(sha(path) == digest for path, digest in expected_inputs.items())
AUX = Path('/private/tmp/ken-search-auxiliary-training-20261015').resolve()
assert args.metadata.resolve().is_relative_to(AUX) or args.metadata.resolve().is_relative_to(R/'output/analysis/auxiliary-training-data-v93')
assert sha(args.metadata) == args.metadata_sha256
metadata = json.loads(args.metadata.read_text())
assert set(metadata) == {'repositories', 'source_only_inputs', 'curation_seal_sha256', 'disjointness_verified'}
assert metadata['disjointness_verified'] is True
assert metadata['curation_seal_sha256'] in metadata['source_only_inputs'].values()
specs = metadata['repositories']; assert len(specs) == 8
assert len({s['name'] for s in specs}) == 8
assert all(set(s) == {'name', 'root', 'revision', 'license'} for s in specs)
assert all(Path(s['name']).name == s['name'] and s['name'] not in ('.', '..') for s in specs)
roots = {s['name']: Path(s['root']) for s in specs}
assert all(root.resolve().is_relative_to(AUX/'repos') for root in roots.values())
by_repo = {s['name']: s for s in specs}
assert all(s['license'] and len(s['revision']) == 40 for s in specs)
assert set(roots).isdisjoint(json.loads((R/'experiments/search-engine/datasets/roots-development.json').read_text()))
assert all(Path(path).resolve().is_relative_to(AUX) for path in metadata['source_only_inputs'])
assert all(sha(path) == digest for path, digest in metadata['source_only_inputs'].items())
assert os.environ.get('KEN_INDEX_WORKERS') == '0' and EXTRACTOR_VERSION == 7
receipt = verify_frozen_source(E)
O = args.output; O.mkdir(exist_ok=False)
for name in ('indices', 'context', 'views'):
    (O/name).mkdir()
static_path = R/'output/models/static-comparison-registration.json'
context_path = R/'output/models/cpu-context-registration-v42.json'
protocol = E/'experiments/search-engine/cpu-auxiliary-training-v93.md'
registration = next(r for r in json.loads(static_path.read_text()) if r['model_id'] == 'minishlab/potion-code-16M-v2')
words = StaticEmbeddingControl(Path(registration['root']), registration)
template = R/'output/analysis/c-source-reindex-v66c/indices/attrs.db'
conn = sqlite3.connect(f'file:{template}?mode=ro', uri=True); profile = active_profile(conn); conn.close()
assert profile.identity == profile.behavior == words.spec
manifest = {'scope': 'ALL8 auxiliary source7 indices/full/contextviews before any auxiliary query/ref text; no fit or evaluation',
    'script_sha256': sha(__file__), 'engine_receipt': receipt, 'protocol_sha256': sha(protocol),
    'repositories': specs, 'extractor_version': EXTRACTOR_VERSION, 'static_encoder': words.identity,
    'inputs': {str(p): sha(p) for p in (args.metadata, static_path, context_path, template, protocol)},
    'source_repos': {}, 'context_repos': {}, 'views_repos': {}}
(O/'registration.json').write_text(json.dumps(manifest, indent=2))
for repo, root in sorted(roots.items()):
    started = time.perf_counter(); clean_pin(root, by_repo[repo]['revision'])
    paths = list(iter_files(root))
    conn = connect(O/'indices'/f'{repo}.db'); init_schema(conn)
    stats = index_project(conn, root, paths, profile=profile, encoders={'identity': words, 'behavior': words})
    actual = [r[0] for r in conn.execute('SELECT path FROM ci_files ORDER BY path')]
    assert {r[0] for r in conn.execute('SELECT DISTINCT extractor_version FROM ci_retrieval_files')} == {7}
    conn.close()
    hashes = {p: sha(root/p) for p in actual}
    groups, generation = grouped(O/'indices'/f'{repo}.db')
    manifest['source_repos'][repo] = {'indexed_files': len(actual), 'file_hashes': hashes,
        'new_source_index_sha256': sha(O/'indices'/f'{repo}.db'), 'generation': generation,
        'owners': len(groups), 'passages': sum(map(len, groups.values())), 'stats': dataclasses.asdict(stats),
        'ms': (time.perf_counter()-started)*1000}
    assert hashes and groups
    (O/'registration.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'source7_complete': repo, 'files': len(actual), 'owners': len(groups)}), flush=True)
    del groups; gc.collect()
assert len(manifest['source_repos']) == 8

context_registration = json.loads(context_path.read_text()); context = CPUContextEncoder(context_registration)
prepared = {key: context_registration[key] for key in ('document_projection',)}
prepared.update(graph_sha256=context_registration['artifacts']['onnx/model.onnx'],
    tokenizer_sha256=context_registration['artifacts']['tokenizer.json'], pooling='raw-CLS-explicit-L2',
    batch_size=1, sequence_length=512, engine_receipt=receipt, repos={})
(O/'context-registration.json').write_text(json.dumps(prepared, indent=2))
for repo, root in sorted(roots.items()):
    started = time.perf_counter(); groups, generation = grouped(O/'indices'/f'{repo}.db')
    db = sqlite3.connect(O/'context'/f'{repo}.db')
    db.execute('CREATE TABLE vectors(hash TEXT PRIMARY KEY,text TEXT,vector BLOB)')
    db.execute('CREATE TABLE owners(entity TEXT PRIMARY KEY,text_hash TEXT,source_hash TEXT,role TEXT)')
    encoded = 0
    for i, entity in enumerate(sorted(groups, key=lambda e: (e.path, e.kind, e.qualname or '', e.owner or '', e.definition_ordinal))):
        desc = describe_owner(groups[entity])
        text = '\n'.join([entity.path, desc.fields['identity'], desc.fields['signature'],
            'Documentation: '+desc.fields['documentation'][:800], 'Source:', desc.fields['implementation']])
        key = hashlib.sha256(text.encode()).hexdigest()
        identity = json.dumps({'path': entity.path, **entity.to_dict()}, sort_keys=True, separators=(',', ':'))
        if db.execute('SELECT 1 FROM vectors WHERE hash=?', (key,)).fetchone() is None:
            vector = normalized(context.embed_passages([text])[0]); encoded += 1
            db.execute('INSERT INTO vectors VALUES (?,?,?)', (key, text, vector.tobytes()))
        db.execute('INSERT INTO owners VALUES (?,?,?,?)', (identity, key, desc.source_hash, groups[entity][0].role))
        if i % 512 == 0:
            db.commit(); print(json.dumps({'context_progress': repo, 'owners': i, 'total': len(groups)}), flush=True)
    db.commit(); db.close()
    row = {'owners': len(groups), 'unique_texts': encoded, 'generation': generation,
        'input_index_sha256': sha(O/'indices'/f'{repo}.db'), 'context_index_sha256': sha(O/'context'/f'{repo}.db'),
        'ms': (time.perf_counter()-started)*1000}
    prepared['repos'][repo] = row; manifest['context_repos'][repo] = row
    (O/'context-registration.json').write_text(json.dumps(prepared, indent=2))
    (O/'registration.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'full_context_complete': repo, 'owners': len(groups)}), flush=True)
    context.calls.clear(); del groups; gc.collect()
assert len(prepared['repos']) == 8

views_model = dict(context_registration, document_projection=SOURCE_VIEW_PROJECTION)
views_model['spec'] = dataclasses.asdict(registered_context_spec(views_model))
model_path = O/'views/model-registration.json'; model_path.write_text(json.dumps(views_model, indent=2))
views = {'scope': 'ALL8 auxiliary source7 owners, both existing ownsourceviews, beforequeries',
    'repositories': sorted(roots), 'projection': SOURCE_VIEW_PROJECTION, 'source_repos': {},
    'model_registration_sha256': sha(model_path), 'original_model_registration_sha256': sha(context_path), 'engine_receipt': receipt}
(O/'views/registration.json').write_text(json.dumps(views, indent=2))
for repo, root in sorted(roots.items()):
    started = time.perf_counter(); groups, generation = grouped(O/'indices'/f'{repo}.db')
    texts, by_hash, owner_rows = [], {}, []
    for entity, passages in groups.items():
        desc = describe_owner(passages)
        identity = json.dumps({'path': entity.path, **entity.to_dict()}, sort_keys=True, separators=(',', ':'))
        for name, text in owner_view_texts(desc).items():
            digest = hashlib.sha256(text.encode()).hexdigest()
            if digest not in by_hash: by_hash[digest] = len(texts); texts.append(text)
            row = by_hash[digest]; assert texts[row] == text
            owner_rows.append((identity, desc.source_hash, name, digest, row))
    assert len(owner_rows) == 2*len(groups)
    db = sqlite3.connect(O/'views'/f'{repo}-source.db')
    db.execute('CREATE TABLE owners(entity TEXT,source_hash TEXT,view TEXT,text_hash TEXT,vector_index INT,PRIMARY KEY(entity,view))')
    db.executemany('INSERT INTO owners VALUES (?,?,?,?,?)', owner_rows)
    db.execute('CREATE TABLE texts(vector_index INT PRIMARY KEY,text_hash TEXT,text TEXT)')
    db.executemany('INSERT INTO texts VALUES (?,?,?)', [(i, hashlib.sha256(t.encode()).hexdigest(), t) for i, t in enumerate(texts)])
    db.commit(); db.close()
    full = sqlite3.connect(f'file:{O/"context"/(repo+".db")}?mode=ro', uri=True)
    vector_path = O/'views'/f'{repo}-vectors.npy'
    vectors = np.lib.format.open_memmap(vector_path, mode='w+', dtype=np.float32, shape=(len(texts), 768))
    reused = encoded = 0
    for i, text in enumerate(texts):
        digest = hashlib.sha256(text.encode()).hexdigest()
        cached = full.execute('SELECT text,vector FROM vectors WHERE hash=?', (digest,)).fetchone()
        if cached is None: value = normalized(context.embed_passages([text])[0]); encoded += 1
        else: assert cached[0] == text; value = np.frombuffer(cached[1], dtype=np.float32); reused += 1
        assert value.shape == (768,) and np.isfinite(value).all() and np.isclose(np.linalg.norm(value), 1., atol=1e-5)
        vectors[i] = value
        if i % 512 == 0: vectors.flush(); print(json.dumps({'view_progress': repo, 'units': i, 'total': len(texts)}), flush=True)
    vectors.flush(); del vectors; full.close()
    files = {e.path: ps[0].source_hash for e, ps in groups.items()}
    assert all(sha(root/p) == h for p, h in files.items())
    row = {'owners': len(groups), 'units': len(owner_rows), 'unique_texts': len(texts),
        'source_files': files, 'source_generation': generation, 'base_full_context_sha256': sha(O/'context'/f'{repo}.db'),
        'source_db_sha256': sha(O/'views'/f'{repo}-source.db'), 'vectors_sha256': sha(vector_path),
        'reused_full_context_vectors': reused, 'encoded_new': encoded, 'ms': (time.perf_counter()-started)*1000}
    views['source_repos'][repo] = row; manifest['views_repos'][repo] = row
    (O/'views/registration.json').write_text(json.dumps(views, indent=2))
    (O/'registration.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'views_complete': repo, 'owners': len(groups)}), flush=True)
    context.calls.clear(); del groups, texts, by_hash, owner_rows; gc.collect()
assert len(views['source_repos']) == 8 and verify_frozen_source(E) == receipt
assert all(sha(p) == h for p, h in manifest['inputs'].items())
assert all(sha(p) == h for p, h in metadata['source_only_inputs'].items())
for repo, root in roots.items():
    clean_pin(root, by_repo[repo]['revision'])
    assert all(sha(root/p) == h for p, h in manifest['source_repos'][repo]['file_hashes'].items())
assert not any(name in sys.modules for name in ('torch', 'transformers', 'sentence_transformers'))
manifest.update(complete=True, peak_rss_native=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
(O/'registration.json').write_text(json.dumps(manifest, indent=2))
