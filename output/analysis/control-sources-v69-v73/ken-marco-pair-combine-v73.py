"""Join both genuine bound pair controls; never consult relevance references."""
import hashlib
import json
import sys
import time
from pathlib import Path
import numpy as np
import ken
ROOT = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
ENGINE = Path(ken.__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE/'experiments/search-engine'))
from replay_parent import validate_replay_parent
from ken.bench.source_receipts import verify_frozen_source
BASE = ROOT/'output/analysis/c-source-reindex-v66c'
PARENT = ROOT/'output/analysis/context-views-features-source7-v69'
SOURCES = [ROOT/f'output/analysis/marco-pair-features-v73-{model}' for model in ('tiny', 'mini')]
OUT = ROOT/'output/analysis/marco-pair-features-v73-combined'
OUT.mkdir(exist_ok=False)

def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

receipt = verify_frozen_source(ENGINE)
while True:
    try:
        regs = [json.loads((s/'registration.json').read_text()) for s in SOURCES]
        if all(len(r['query_repos']) == 16 and r.get('query_input_bindings_sha256') for r in regs):
            break
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    time.sleep(5)
bindings = [validate_replay_parent(PARENT, BASE, extension=s) for s in SOURCES]
assert all(len(b) == 68 for b in bindings)
assert regs[0]['source_repos'] == regs[1]['source_repos']
text_bindings = []
for source, reg in zip(SOURCES, regs):
    assert sha(source/'query-input-bindings.jsonl') == reg['query_input_bindings_sha256']
    text_bindings.append(list(map(json.loads, (source/'query-input-bindings.jsonl').read_text().splitlines())))
assert text_bindings[0] == text_bindings[1] and len(text_bindings[0]) == 800
assert len({(r['id'], r['view']) for r in text_bindings[0]}) == 800
manifest = {'scope': 'ALL400 complete251parent+Tiny8+Mini8; two CPU pair controls; no labels',
    'script_sha256': sha(__file__), 'engine_receipt': receipt,
    'source_repos': regs[0]['source_repos'], 'query_repos': {},
    'parent_features_registration_sha256': sha(PARENT/'registration.json'),
    'input_bindings': bindings,
    'control_registrations': {str(s/'registration.json'): sha(s/'registration.json') for s in SOURCES},
    'features': [*regs[0]['features'], *regs[1]['features'][251:]]}
assert len(manifest['features']) == 267
for repo in sorted(regs[0]['query_repos']):
    with np.load(SOURCES[0]/f'{repo}.npz') as tiny, np.load(SOURCES[1]/f'{repo}.npz') as mini:
        assert np.array_equal(tiny['qid'], mini['qid']) and np.array_equal(tiny['index'], mini['index'])
        assert np.array_equal(tiny['x'][:, :251], mini['x'][:, :251])
        matrix = np.column_stack((tiny['x'], mini['x'][:, 251:]))
        assert matrix.shape == (len(tiny['qid']), 267) and np.isfinite(matrix).all()
        np.savez_compressed(OUT/f'{repo}.npz', x=matrix, qid=tiny['qid'], index=tiny['index'])
    manifest['query_repos'][repo] = {'queries': 25, 'rows': len(matrix),
        'parent_features_sha256': sha(PARENT/f'{repo}.npz'), 'output_sha256': sha(OUT/f'{repo}.npz')}
(OUT/'query-input-bindings.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in text_bindings[0]))
manifest['query_input_bindings_sha256'] = sha(OUT/'query-input-bindings.jsonl')
(OUT/'registration.json').write_text(json.dumps(manifest, indent=2))
validate_replay_parent(PARENT, BASE, extension=OUT)
assert bindings == [validate_replay_parent(PARENT, BASE, extension=s) for s in SOURCES]
assert verify_frozen_source(ENGINE) == receipt
print('both400 controls combined; complete267prefix/row binding validated', flush=True)
