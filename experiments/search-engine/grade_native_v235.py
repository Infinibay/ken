"""Grade closed native outputs against independently pinned source references."""
from pathlib import Path
import argparse
import ast
import json
import statistics

from native_grading_v235 import validate_result, score_slots, verify_capture
from native_units_v235 import correct_file, correct_piece
from public_benchmarks_v222 import checked_path, sha


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    index = (len(ordered) - 1) * fraction
    low = int(index)
    return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (index - low)


def timing(rows):
    values = [r['elapsed_ms'] for r in rows if r.get('elapsed_ms') is not None]
    return {'measurements': len(values), 'unique_queries': len(rows),
            'p50_ms': statistics.median(values) if values else None,
            'p95_ms': percentile(values, .95), 'max_ms': max(values) if values else None}


def aggregate(rows, key):
    return {'cases': len(rows),
            'top1_hits': sum(r[key]['hit1'] for r in rows),
            'top10_hits': sum(r[key]['hit10'] for r in rows),
            'top1': sum(r[key]['hit1'] for r in rows) / len(rows),
            'top10': sum(r[key]['hit10'] for r in rows) / len(rows)}


def rss_bytes(provenance, field):
    value = provenance[field]
    return value * (1024 if provenance['rss_unit'] == 'KiB' else 1)


def validate_targets(targets, group):
    root = Path(group['root'])
    for target in targets:
        path = checked_path(root, target['path'])
        assert sha(path) == target['source_sha256'] == group['source_pins'][target['path']]
        lines = path.read_bytes().decode('utf-8').splitlines()
        assert 1 <= target['start_line'] <= target['end_line'] <= len(lines)
        assert target['kind'] in {'function', 'method', 'class', 'module', 'fragment'}
        assert target['rationale']
        for anchor in target.get('anchor_ranges', []):
            assert 1 <= anchor['start_line'] <= anchor['end_line'] <= len(lines)
        if target['kind'] == 'fragment':
            assert target.get('qualname') is None and target['anchor_ranges']
        elif target['kind'] in {'function', 'method', 'class'}:
            tree = ast.parse(path.read_bytes())
            allowed = (ast.ClassDef,) if target['kind'] == 'class' else (ast.FunctionDef, ast.AsyncFunctionDef)
            leaf = target['qualname'].split('.')[-1]
            nodes = [n for n in ast.walk(tree) if isinstance(n, allowed) and n.name == leaf
                     and n.lineno == target['start_line'] and n.end_lineno == target['end_line']]
            assert len(nodes) == 1, ('reference definition differs from source', target)
            node = nodes[0]
            declaration = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            assert declaration == target.get('declaration_start_line', target['start_line'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=Path.cwd() / 'output/development/core-native-v235')
    parser.add_argument('--references', type=Path, required=True)
    parser.add_argument('--reference-sha256', required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    assert sha(args.references) == args.reference_sha256
    references = json.loads(args.references.read_text())
    registration = json.loads((out / 'registration.json').read_text())
    groups = json.loads((out / 'native-requests.json').read_text())
    consumed = [group['instance_id'] + '/' + name for group in groups
                for name in ['preparation.json', *[r + '.json' for r in registration['routes']]]]
    consumed.extend(group['instance_id'] + '/' + route + '-provenance.json'
                    for group in groups for route in registration['routes']
                    if (out / 'capture' / group['instance_id'] / (route + '-provenance.json')).exists())
    closure = verify_capture(out / 'capture', required_paths=consumed)
    assert len(groups) == closure['groups'] == registration['unique_queries'] == 11
    assert sha(out / 'native-requests.json') == registration['native_requests_sha256'] == closure['requests_sha256']
    engine = Path(registration['engine'])
    assert sha(engine / 'SOURCE-MANIFEST.json') == registration['engine_manifest_sha256']
    for name, digest in json.loads((engine / 'SOURCE-MANIFEST.json').read_text())['files'].items():
        assert sha(engine / name) == digest
    case_refs = references['cases']
    assert set(case_refs) == {c['id'] for g in groups for c in g['cases']}
    report = {'variant': 'Native full original repository source; original unchanged CORE queries',
        'official_core_metric': False, 'engine_changed': False, 'reserve': 'CLOSED',
        'engine_manifest_sha256': registration['engine_manifest_sha256'],
        'references_sha256': args.reference_sha256, 'capture_closure_sha256': sha(out / 'capture/closure.json'),
        'query_count': 11, 'level_case_count': 18, 'routes': {}, 'preparation': [], 'cases': []}
    validated_results = 0
    for route in registration['routes']:
        route_rows, performance, provenance = [], [], []
        for group in groups:
            folder = out / 'capture' / group['instance_id']
            response = json.loads((folder / (route + '.json')).read_text())
            assert response['id'] == group['instance_id']
            assert len(response['results']) <= 10
            for result in response['results']:
                validate_result(result, Path(group['root']), group['source_pins'])
                validated_results += 1
            performance.append(response)
            provenance_path = folder / (route + '-provenance.json')
            if provenance_path.exists():
                prov = json.loads(provenance_path.read_text())
                assert prov['providers'] == ['CPUExecutionProvider'] and prov['reranker_tokens'] == 1024
                assert not prov['heavy_imports'] and prov['query_sha256'] == group['query_sha256']
                provenance.append(prov)
            for case in group['cases']:
                reference = case_refs[case['id']]
                assert reference['query_id'] == group['instance_id'] and reference['level'] == case['level']
                targets = reference['targets']
                # Empty unresolved target sets stay in the denominator as misses.
                validate_targets(targets, group)
                row = {'id': case['id'], 'query_id': group['instance_id'], 'level': case['level'], 'route': route,
                    'piece': score_slots(response['results'], targets, correct_piece),
                    'file': score_slots(response['results'], targets, correct_file),
                    'error': response.get('error'),
                    'top1': {k: response['results'][0].get(k) for k in ('path', 'entity', 'entity_span')}
                            if response['results'] else None}
                route_rows.append(row)
                report['cases'].append(row)
        report['routes'][route] = {
            level: {kind: aggregate([r for r in route_rows if r['level'] == level], kind)
                    for kind in ('piece', 'file')}
            for level in ('LEVEL-2', 'LEVEL-3')}
        report['routes'][route]['combined_descriptive_only'] = {k: aggregate(route_rows, k) for k in ('piece', 'file')}
        report['routes'][route]['performance'] = {
            'all_requests': timing(performance),
            'successful_requests': timing([r for r in performance if not r.get('error')]),
            'query_errors': sum(bool(r.get('error')) for r in performance),
            'query_process_peak_rss_bytes': max((rss_bytes(p, 'query_process_peak_rss_native') for p in provenance), default=None),
            'warmup_ms': [p['warmup_ms'] for p in provenance],
        }
    for group in groups:
        folder = out / 'capture' / group['instance_id']
        preparation = json.loads((folder / 'preparation.json').read_text())
        preparation['peak_rss_bytes'] = rss_bytes(preparation, 'peak_rss_native')
        report['preparation'].append({'query_id': group['instance_id'], **preparation})
    report['validated_results'] = validated_results
    report['preparation_summary'] = {
        'latency': timing(report['preparation']),
        'total_ms': sum(p['elapsed_ms'] for p in report['preparation']),
        'peak_rss_bytes': max(p['peak_rss_bytes'] for p in report['preparation']),
        'max_owned_index_bytes': max(p['index_bytes_before_query'] for p in report['preparation']),
        'shared_context_cache_bytes': sum(p.stat().st_size for p in (out / 'source-context-cache').rglob('*') if p.is_file()),
    }
    report['producer_pins'] = {p.name: sha(p) for p in Path(__file__).parent.glob('*.py')}
    target = out / 'report-v235.json'
    assert not target.exists(), 'Never overwrite a closed report'
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({k: report[k] for k in ('routes', 'preparation_summary', 'validated_results')}, indent=2))


if __name__ == '__main__':
    main()
