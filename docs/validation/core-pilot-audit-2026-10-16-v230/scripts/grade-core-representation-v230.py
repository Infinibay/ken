"""Verify the closed paired input diagnostic before joining public qrels."""
from pathlib import Path
import hashlib
import json
import sys

w = Path.cwd()
base = w / 'output/development/repoqa-core-v222'
control = w / 'output/analysis/core-representation-v229'
dest = w / 'output/analysis/core-audit-report-v230/representation-control.json'
assert not dest.exists()
sys.path.insert(0, str(w / 'experiments/search-engine'))
from grade_public_v224 import load_closed_results


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


closure = json.loads((control / 'closure.json').read_text())
for name, digest in closure['files'].items():
    assert sha(control / name) == digest
registration = json.loads((control / 'registration.json').read_text())
core_registration = json.loads((base / 'core-registration.json').read_text())
assert sha(base / 'core-sources.json') == core_registration['sources_sha256']
assert sha(base / 'core-document-map.json') == core_registration['document_map_sha256']
requests = [json.loads(line) for line in (base / 'core-requests.jsonl').read_text().splitlines()]
assert sha(base / 'core-requests.jsonl') == core_registration['requests_sha256']
responses = load_closed_results(base / 'core-capture-v224', [r['id'] for r in requests])
request = registration['request']
source = json.loads((base / 'core-sources.json').read_text())[request['repo_id']]
baseline_map = json.loads((base / 'core-document-map.json').read_text())[request['repo_id']]
control_map = json.loads((control / 'document-map.json').read_text())
assert len(baseline_map) == len(control_map) == len(set(control_map.values())) == 1000
assert set(baseline_map.values()) == set(control_map.values())
original_hashes = {baseline_map[path]: digest for path, digest in source['source_pins'].items()}
control_hashes = json.loads((control / 'source-pins.json').read_text())
for path, identifier in control_map.items():
    assert sha(Path(request['root']) / path) == control_hashes[path] == original_hashes[identifier]
baseline = responses[request['id']]
response = json.loads((control / 'response.json').read_text())
qrels_path = Path(source['raw_folder']) / 'qrels.jsonl'
assert sha(qrels_path) == core_registration['raw_file_pins'][qrels_path.relative_to(base / 'core-raw').as_posix()]
gold = {r['corpus_id'] for r in map(json.loads, qrels_path.read_text().splitlines())
        if r['query_id'] == source['public_query_id'] and r['score'] > 0}
rows = []
for name, value, mapping in [('baseline-txt', baseline, baseline_map), ('native-extensions', response, control_map)]:
    order = [mapping[r['path']] for r in value['results']]
    ranks = [i + 1 for i, identifier in enumerate(order) if identifier in gold]
    top_path = next(path for path, identifier in control_map.items() if identifier == order[0])
    rows.append({'variant': name, 'reference_ranks': ranks, 'hit1': int(1 in ranks),
        'hit10': int(bool(ranks)), 'top1_id': order[0],
        'top1_first_source_line': (Path(request['root']) / top_path).read_text().splitlines()[0]})
result = {'query_id': source['public_query_id'], 'level': source['level'],
    'diagnostic_only': True, 'no_replacement_of_original_pilot': True,
    'all_1000_candidate_UUIDs_and_text_bytes_preserved': True, 'variants': rows,
    'control_provenance': json.loads((control / 'provenance.json').read_text()),
    'closure_sha256': sha(control / 'closure.json'),
    'registration_sha256': sha(control / 'registration.json'),
    'grader_sha256': sha(Path(__file__)), 'reserve': 'CLOSED'}
dest.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
