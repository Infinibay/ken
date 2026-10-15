"""Source-only lexical catalogs for ALL16 original source7 repositories."""
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import gc
import hashlib
import json
from pathlib import Path
import resource
import sqlite3
import sys
import time

import ken
R = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
E = Path(ken.__file__).resolve().parents[2]
sys.path.insert(0, str(E/'experiments/search-engine'))
from lexical_context import LEXICAL_CONTEXT_VERSION, build_lexical_contexts
from ken.retrieval.passages import EXTRACTOR_VERSION
from ken.bench.source_receipts import verify_frozen_source
from ken.parsers import detect_language
from ken.retrieval.storage import generation, load_passage_map


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument('--engine-receipt', required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
receipt = verify_frozen_source(E)
assert receipt == args.engine_receipt
P = R/'output/analysis/c-source-reindex-v66c'
assert sha(P/'registration.json') == '17ac3c3c26170f8929b2cc1a21fe9a7e036603452929c73a435a07e88628dd6a'
parent = json.loads((P/'registration.json').read_text())
roots_path = E/'experiments/search-engine/datasets/roots-development.json'
roots = {k: Path(v) for k,v in json.loads(roots_path.read_text()).items()}
assert len(roots) == 16 and roots.keys() == parent['source_repos'].keys()
O = args.output; O.mkdir(exist_ok=False)
inputs = {str(p): sha(p) for p in (P/'registration.json', roots_path,
    E/'experiments/search-engine/lexical_context.py', E/'experiments/search-engine/cpu-lexical-context-v95.md')}
manifest = {'scope': 'ALL16 source7 lexical callable catalogs before queries/labels; no model/ranking/evidence/fit/quality change',
    'script_sha256': sha(__file__), 'engine_receipt': receipt, 'inputs': inputs,
    'context_version': LEXICAL_CONTEXT_VERSION, 'extractor_version': EXTRACTOR_VERSION, 'repos': {}}
(O/'registration.json').write_text(json.dumps(manifest, indent=2))
for repo, root in sorted(roots.items()):
    started = time.perf_counter(); metadata = parent['source_repos'][repo]
    index = P/'indices'/f'{repo}.db'
    assert sha(index) == metadata['new_source_index_sha256']
    inputs[str(index)] = sha(index)
    connection = sqlite3.connect(f'file:{index}?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    files = {row['path']: row['language'] for row in connection.execute('SELECT path,language FROM ci_files ORDER BY path')}
    assert files.keys() == metadata['file_hashes'].keys()
    original = load_passage_map(connection); gen = generation(connection); connection.close()
    by_file = defaultdict(list)
    for passage in original.values(): by_file[passage.entity.path].append(passage)
    assert set(by_file) <= set(files)
    counts = Counter(); reasons = Counter(); records = []
    path = O/f'{repo}-contexts.jsonl'
    with path.open('w') as output:
        for name, language in files.items():
            source = (root/name).read_bytes(); digest = hashlib.sha256(source).hexdigest()
            assert digest == metadata['file_hashes'][name]
            passages = by_file.get(name, [])
            detected = detect_language(Path(name))
            if not passages:
                record = {'path': name, 'source_hash': digest, 'contexts': 0, 'status': 'no_indexed_passages'}
            elif detected is None:
                assert not any(p.entity.kind != 'module' for p in passages)
                record = {'path': name, 'source_hash': digest, 'contexts': 0, 'status': 'no_canonical_language_parser'}
            else:
                catalog = build_lexical_contexts(source, passages, path=name, language=language,
                    generation=f'{inputs[str(index)]}:g{gen}', expected_source_hash=digest)
                for context in catalog.contexts.values():
                    output.write(json.dumps(asdict(context), ensure_ascii=False, separators=(',', ':'))+'\n')
                record = {'path': name, 'source_hash': digest, 'contexts': len(catalog.contexts),
                    'diagnostics': [asdict(d) for d in catalog.diagnostics], 'status': 'source_checked'}
                counts['syntax_scopes'] += sum(len(c.scopes) for c in catalog.contexts.values())
                counts['parts'] += sum(len(c.parts) for c in catalog.contexts.values())
                reasons.update(d.reason for d in catalog.diagnostics)
            counts['contexts'] += record['contexts']; counts[record['status']] += 1
            records.append(record)
    assert len(records) == metadata['indexed_files']
    inventory = O/f'{repo}-source-inventory.json'; inventory.write_text(json.dumps(records, indent=2))
    assert all(sha(root/name) == digest for name,digest in metadata['file_hashes'].items())
    assert sha(index) == inputs[str(index)]
    manifest['repos'][repo] = {'files': len(files), 'owners': len({p.entity for p in original.values()}),
        'generation': gen, 'source_index_sha256': inputs[str(index)], 'contexts_sha256': sha(path),
        'inventory_sha256': sha(inventory), 'counts': dict(counts), 'diagnostic_reasons': dict(reasons),
        'ms': (time.perf_counter()-started)*1000}
    (O/'registration.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'lexical_source_complete': repo, **manifest['repos'][repo]}), flush=True)
    del original, by_file, passages, source, records; gc.collect()
assert len(manifest['repos']) == 16
assert sum(v['files'] for v in manifest['repos'].values()) == 6314
assert sum(v['owners'] for v in manifest['repos'].values()) == 50967
assert all(sha(path) == digest for path,digest in inputs.items())
assert verify_frozen_source(E) == receipt
assert not any(name in sys.modules for name in ('torch', 'transformers', 'onnxruntime', 'lightgbm'))
manifest.update(complete=True, peak_rss_native=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
(O/'registration.json').write_text(json.dumps(manifest, indent=2))
