"""Independent source-only/synthetic review; never read real capture outputs."""
import ast
import copy
import hashlib
import io
import json
import sys
import tempfile
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path

R = Path('/Users/andres/Projects/ken/output/search-engine-2026-10-14/workspace')
S = R / 'output/analysis/core-native-grade-v235/source'
N = R / 'output/development/core-native-v235'
W = Path('/private/tmp/ken-core-native-grader-review-v235')

def forbid_real_capture(event, args):
    if event == 'open' and isinstance(args[0], (str, bytes)):
        p = Path(args[0]).resolve()
        if p.is_relative_to((N / 'capture').resolve()):
            raise AssertionError('Independent review may not open real capture files')

sys.addaudithook(forbid_real_capture)
sys.path.insert(0, str(S))
from native_units_v235 import correct_piece, correct_file
from native_grading_v235 import validate_result, score_slots, verify_capture
import grade_native_v235 as grader

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

checks = []
def check(name, value):
    assert value, name
    checks.append(name)

def rejects(name, callback, expected=(ValueError, AssertionError, KeyError, TypeError)):
    try:
        callback()
    except expected:
        checks.append(name)
    else:
        raise AssertionError('Accepted invalid probe: ' + name)

registration = json.loads((N / 'registration.json').read_text())
original = json.loads((N / 'grader-registration.json').read_text())
amendment = json.loads((N / 'grader-integrity-amendment-v235.json').read_text())
check('amendment binds preserved original registration', amendment['original_registration_sha256'] == sha(N / 'grader-registration.json'))
for name, digest in amendment['source_pins'].items():
    check('amended source pin: ' + name, sha(S / name) == digest)
for name, change in amendment['changes'].items():
    check('amendment old/new chain: ' + name,
          original['source_pins'][name] == change['before'] and
          amendment['source_pins'][name] == change['after'])
for name, digest in original['source_pins'].items():
    if name not in amendment['changes']:
        check('unchanged original pin: ' + name, amendment['source_pins'][name] == digest)
check('amendment declares no predictions or engine change', amendment['predictions_read'] is False and amendment['engine_changed'] is False)
engine_path = Path(registration['engine'])
check('engine manifest exact pinned bytes', sha(engine_path / 'SOURCE-MANIFEST.json') == registration['engine_manifest_sha256'])
engine_files = json.loads((engine_path / 'SOURCE-MANIFEST.json').read_text())['files']
check('all frozen engine files exact without importing engine', len(engine_files) == 425 and all(sha(engine_path / name) == digest for name, digest in engine_files.items()))

# Reconstruct the exact original pure guard module from the amended bytes. Its hash
# must match the preserved original registration before using it for red/green.
historical = (S / 'native_grading_v235.py').read_text()
historical = historical.replace("    if any(not isinstance(span.get('content'), str) for span in result.get('evidence', [])):\n        raise ValueError('evidence must include visible content')\n", '')
historical = historical.replace('def verify_capture(destination, required_paths=()):', 'def verify_capture(destination):')
historical = historical.replace("    if not closure.get('response_pins'):\n        raise ValueError('empty capture manifest')\n    if set(required_paths) - closure['response_pins'].keys():\n        raise ValueError('unpinned consumed capture path')\n", '')
check('historical guard reconstruction matches original exact SHA', hashlib.sha256(historical.encode()).hexdigest() == original['source_pins']['native_grading_v235.py'])
(W / 'native-grading-original-reconstructed.py').write_text(historical)
historical_module = {}
exec(compile(historical, str(W / 'native-grading-original-reconstructed.py'), 'exec'), historical_module)

groups = json.loads((N / 'native-requests.json').read_text())
refs_path = R / 'output/analysis/core-native-references-v235.json'
refs = json.loads(refs_path.read_text())
check('sealed reference hash', sha(refs_path) == '4e854dd5744a0c94ccc0c938fc6c18968b7f3b5c564e39386e1296e5a05bbbb0')
check('native public requests hash', sha(N / 'native-requests.json') == registration['native_requests_sha256'])
check('exact fixed two routes', registration['routes'] == {'symbols': {'scope': 'symbols', 'piece_kind': 'symbol'}, 'files': {'scope': 'files', 'piece_kind': 'file'}})
check('eleven unique revisions and queries', len(groups) == len({g['instance_id'] for g in groups}) == 11)
cases = [c for g in groups for c in g['cases']]
check('eighteen unique level-specific cases', len(cases) == len({c['id'] for c in cases}) == len(refs['cases']) == 18)
check('case IDs equal sealed references', {c['id'] for c in cases} == set(refs['cases']))
check('L2 eleven and L3 seven', Counter(c['level'] for c in cases) == {'LEVEL-2': 11, 'LEVEL-3': 7})
source_count, target_count, symbol_count = 0, 0, 0
target_kinds = Counter()
symbol_cache = {}
for group in groups:
    root = Path(group['root'])
    check('query text SHA: ' + group['instance_id'], hashlib.sha256(group['query'].encode()).hexdigest() == group['query_sha256'])
    for name, digest in group['source_pins'].items():
        assert sha(root / name) == digest
        source_count += 1
    for case in group['cases']:
        ref = refs['cases'][case['id']]
        assert (ref['query_id'], ref['level']) == (group['instance_id'], case['level'])
        grader.validate_targets(ref['targets'], group)
        for target in ref['targets']:
            target_count += 1
            target_kinds[target['kind']] += 1
            assert len(target['anchor_ranges']) == 1
            anchor = target['anchor_ranges'][0]
            assert target['start_line'] <= anchor['start_line'] <= anchor['end_line'] <= target['end_line']
            if target['kind'] not in {'function', 'method', 'class'}:
                continue
            p = root / target['path']
            if p not in symbol_cache:
                definitions = []
                def walk(node, parents=()):
                    current = parents
                    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                        kind = 'class' if isinstance(node, ast.ClassDef) else ('method' if parents and parents[-1][1] == 'class' else 'function')
                        definitions.append(('.'.join([n for n, _ in parents] + [node.name]), kind, node.lineno, node.end_lineno,
                                            min([node.lineno] + [d.lineno for d in node.decorator_list])))
                        current = (*parents, (node.name, kind))
                    for child in ast.iter_child_nodes(node):
                        walk(child, current)
                walk(ast.parse(p.read_bytes()))
                symbol_cache[p] = definitions
            assert (target['qualname'], target['kind'], target['start_line'], target['end_line'],
                    target.get('declaration_start_line', target['start_line'])) in symbol_cache[p]
            symbol_count += 1
check('all source file hashes match current native snapshots', source_count == 1812)
check('all 141 target ranges and native full lexical identities pass', target_count == 141 and symbol_count == 100)

with tempfile.TemporaryDirectory(prefix='synthetic-', dir=W) as temp:
    root = Path(temp)
    code = root / 'code.py'
    code.write_bytes(b'@decorator\r\ndef good():\r\n    return 42\r\n')
    digest = sha(code)
    target = {'path': 'code.py', 'source_sha256': digest, 'kind': 'function', 'qualname': 'good',
              'declaration_start_line': 1, 'start_line': 2, 'end_line': 3,
              'anchor_ranges': [{'start_line': 2, 'end_line': 3}], 'rationale': 'synthetic responsibility'}
    result = {'path': 'code.py', 'source_hash': digest, 'stale': False,
              'entity': {'kind': 'function', 'qualname': 'good'},
              'entity_span': {'start_line': 2, 'end_line': 3}, 'evidence': []}
    pins = {'code.py': digest}
    no_content = copy.deepcopy(result); no_content['evidence'] = [{'start_line': 2, 'end_line': 3}]
    check('RED original accepts anchor coordinates without visible content', historical_module['validate_result'](no_content, root, pins) and correct_piece(no_content, target))
    rejects('GREEN amended rejects anchor coordinates without visible content', lambda: validate_result(no_content, root, pins), (ValueError,))
    manifest_probe = root / 'manifest-probe'; manifest_probe.mkdir()
    (manifest_probe / 'closure.json').write_text(json.dumps({'all_outputs_closed': True, 'response_pins': {}}))
    check('RED original accepts empty closure manifest', historical_module['verify_capture'](manifest_probe)['all_outputs_closed'])
    rejects('GREEN amended rejects empty closure manifest', lambda: verify_capture(manifest_probe), (ValueError,))
    unrelated = manifest_probe / 'unrelated.json'; unrelated.write_text('[]')
    (manifest_probe / 'closure.json').write_text(json.dumps({'all_outputs_closed': True, 'response_pins': {'unrelated.json': sha(unrelated)}}))
    check('RED original accepts closure pinning no consumed response', historical_module['verify_capture'](manifest_probe)['all_outputs_closed'])
    rejects('GREEN amended rejects closure missing consumed response', lambda: verify_capture(manifest_probe, required_paths=['symbols.json']), (ValueError,))
    check('exact symbol without evidence accepted', validate_result(result, root, pins) and correct_piece(result, target))
    r = copy.deepcopy(result); r['entity_span']['start_line'] = 1
    check('decorator start accepted', correct_piece(r, target))
    for field, value in [('kind', 'method'), ('qualname', 'other')]:
        r = copy.deepcopy(result); r['entity'][field] = value
        check('wrong symbol ' + field + ' rejected', not correct_piece(r, target))
    for field, value in [('start_line', 0), ('start_line', 3), ('end_line', 2)]:
        r = copy.deepcopy(result); r['entity_span'][field] = value
        check('wrong symbol extent ' + field + str(value) + ' rejected', not correct_piece(r, target))
    for field, value in [('path', 'other.py'), ('source_hash', '0' * 64), ('stale', True), ('stale', None)]:
        r = copy.deepcopy(result); r[field] = value
        check('wrong source identity ' + field + str(value) + ' rejected', not correct_piece(r, target) and not correct_file(r, target))
    fragment = {**target, 'kind': 'fragment', 'qualname': None}
    check('fragment cannot pass through container identity', not correct_piece(result, fragment))
    r = copy.deepcopy(result); r['entity'] = {'kind': 'module', 'qualname': None}
    check('matching file alone is not piece hit', correct_file(r, target) and not correct_piece(r, target))
    r['evidence'] = [{'start_line': 2, 'end_line': 3, 'content': 'def good():\n    return 42'}]
    check('faithful complete visible anchor passes independent of container kind', validate_result(r, root, pins) and correct_piece(r, fragment))
    split = copy.deepcopy(r); split['evidence'] = [{'start_line': 2, 'end_line': 2, 'content': 'def good():'},
                                                {'start_line': 3, 'end_line': 3, 'content': '    return 42'}]
    check('anchor split over excerpts is conservative miss', validate_result(split, root, pins) and not correct_piece(split, fragment))
    for evidence in [{'start_line': 2, 'end_line': 3}, {'start_line': 2, 'end_line': 3, 'content': None},
                     {'start_line': 2, 'end_line': 3, 'content': 42}, {'start_line': 2, 'end_line': 3, 'content': 'forged'},
                     {'start_line': 0, 'end_line': 3, 'content': 'bad'}]:
        bad = copy.deepcopy(r); bad['evidence'] = [evidence]
        rejects('reject malformed or forged visible evidence ' + str(len(checks)), lambda: validate_result(bad, root, pins))
    rejects('stale result is integrity error', lambda: validate_result({**result, 'stale': True}, root, pins))
    rejects('bad source hash is integrity error', lambda: validate_result({**result, 'source_hash': '0' * 64}, root, pins))
    check('native rank2 preserved without dedup or rescue', score_slots([{'other': True}, result], [target], correct_piece)['first_relevant_rank'] == 2)
    check('rank11 outside native cap misses', score_slots([{'other': True}] * 10 + [result], [target], correct_piece)['hit10'] == 0)
    check('empty error remains miss', score_slots([], [target], correct_piece) == {'hit1': 0, 'hit10': 0, 'first_relevant_rank': None})
    check('unresolved empty targets remain miss', score_slots([result], [], correct_piece)['hit10'] == 0)

    # Fully synthetic integration run of the scorer, with fake source/engine/closures only.
    fake = root / 'fake-run'; fake.mkdir()
    engine = root / 'fake-engine'; engine.mkdir()
    (engine / 'SOURCE-MANIFEST.json').write_text(json.dumps({'files': {}}))
    synthetic_groups, synthetic_refs, response_pins = [], {}, {}
    capture = fake / 'capture'; capture.mkdir()
    for i in range(11):
        instance = 'synthetic-' + str(i)
        group_cases = [{'id': instance + '-L2', 'level': 'LEVEL-2'}]
        if i < 7:
            group_cases.append({'id': instance + '-L3', 'level': 'LEVEL-3'})
        group = {'instance_id': instance, 'root': str(root), 'source_pins': pins, 'query_sha256': 'synthetic', 'cases': group_cases}
        synthetic_groups.append(group)
        for c in group_cases:
            synthetic_refs[c['id']] = {'query_id': instance, 'level': c['level'], 'targets': [target]}
        folder = capture / instance; folder.mkdir()
        wrong = copy.deepcopy(result); wrong['entity']['qualname'] = 'unrelated'
        # Symbol route: first query rank2, second query error, the rest exact symbol.
        symbol_response = {'id': instance, 'results': [wrong, result] if i == 0 else ([] if i == 1 else [result]),
                           'elapsed_ms': 1., 'error': 'synthetic error' if i == 1 else None}
        # File route: same correct path but no identity/anchor, except first query's complete visible anchor.
        file_response = {'id': instance, 'results': [r if i == 0 else wrong], 'elapsed_ms': 2., 'error': None}
        preparation = {'elapsed_ms': 1., 'rss_unit': 'B', 'peak_rss_native': 100, 'index_bytes_before_query': 10}
        for name, payload in [('symbols.json', symbol_response), ('files.json', file_response), ('preparation.json', preparation)]:
            p = folder / name; p.write_text(json.dumps(payload)); response_pins[str(p.relative_to(capture))] = sha(p)
    requests_path = fake / 'native-requests.json'; requests_path.write_text(json.dumps(synthetic_groups))
    (fake / 'registration.json').write_text(json.dumps({'routes': registration['routes'], 'unique_queries': 11,
        'native_requests_sha256': sha(requests_path), 'engine': str(engine), 'engine_manifest_sha256': sha(engine / 'SOURCE-MANIFEST.json')}))
    (capture / 'closure.json').write_text(json.dumps({'all_outputs_closed': True, 'groups': 11,
        'requests_sha256': sha(requests_path), 'response_pins': response_pins}))
    fake_refs = root / 'synthetic-refs.json'; fake_refs.write_text(json.dumps({'cases': synthetic_refs}))
    old_argv = sys.argv
    try:
        sys.argv = ['grade_native_v235.py', '--out', str(fake), '--references', str(fake_refs), '--reference-sha256', sha(fake_refs)]
        with redirect_stdout(io.StringIO()):
            grader.main()
    finally:
        sys.argv = old_argv
    report = json.loads((fake / 'report-v235.json').read_text())
    check('synthetic scorer keeps 18 cases per route', len(report['cases']) == 36 and report['level_case_count'] == 18)
    check('synthetic scorer keeps L2/L3 denominators', all(report['routes'][route]['LEVEL-2']['piece']['cases'] == 11 and report['routes'][route]['LEVEL-3']['piece']['cases'] == 7 for route in registration['routes']))
    check('synthetic scorer separates fixed routes and piece/file', report['routes']['symbols']['combined_descriptive_only']['piece']['top10_hits'] == 16
          and report['routes']['files']['combined_descriptive_only']['piece']['top10_hits'] == 2
          and report['routes']['files']['combined_descriptive_only']['file']['top10_hits'] == 18)
    check('synthetic scorer counts query error without omitting L2/L3', report['routes']['symbols']['performance']['query_errors'] == 1
          and sum(bool(c['error']) for c in report['cases']) == 2)
    check('synthetic scorer preserves rank2', all(c['piece']['first_relevant_rank'] == 2 for c in report['cases'] if c['route'] == 'symbols' and c['query_id'] == 'synthetic-0'))
    check('synthetic report labels combined result descriptive only', all('combined_descriptive_only' in report['routes'][route] for route in registration['routes']) and report['official_core_metric'] is False)
    try:
        sys.argv = ['grade_native_v235.py', '--out', str(fake), '--references', str(fake_refs), '--reference-sha256', sha(fake_refs)]
        rejects('synthetic report cannot be overwritten', grader.main, (AssertionError,))
    finally:
        sys.argv = old_argv

check('review did not import retrieval or models', not any(m == 'ken' or m.startswith('ken.') or m.split('.')[0] in {'torch', 'onnxruntime', 'tokenizers'} for m in sys.modules))
output = {'passed_checks': len(checks), 'checks': checks, 'source_files_verified': source_count,
          'targets_verified': target_count, 'target_kinds': dict(target_kinds), 'full_lexical_symbols_verified': symbol_count,
          'source_pins': amendment['source_pins'], 'real_capture_open_guard_enabled': True,
          'real_predictions_read': False, 'synthetic_scorer_integration_runs': 1,
          'exact_historical_guard_sha256': hashlib.sha256(historical.encode()).hexdigest(),
          'red_green_regressions': 3, 'frozen_engine_files_hashed_without_import': len(engine_files)}
(W / 'audit-results.json').write_text(json.dumps(output, indent=2) + '\n')
print(json.dumps({k: output[k] for k in ('passed_checks', 'source_files_verified', 'targets_verified', 'full_lexical_symbols_verified', 'real_predictions_read', 'synthetic_scorer_integration_runs')}))
