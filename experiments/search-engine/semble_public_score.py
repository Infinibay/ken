"""Use Semble's original scorer; adapting returned units never changes rank slots."""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

from benchmarks.data import load_repo_specs, load_tasks
from benchmarks.metrics import ndcg_at_k, target_rank


def locations(response, *, visible=False):
    results = []
    native = response.get('full_results')
    for row in native if native is not None else response.get('results', []):
        if native is not None:
            chunk = row['chunk']
            path, start, end = chunk['file_path'], chunk['start_line'], chunk['end_line']
            if visible:
                # Semble's display is a prefix, possibly of a partial first line.
                # This diagnostic is overlap only, not Ken's strict faithful-anchor gate.
                end = min(end, start + min(40, len(chunk['content'].splitlines())) - 1)
        else:
            path = row['path']
            span = (row.get('evidence') or [{}])[0] if visible else row['entity_span']
            start, end = span.get('start_line', 0), span.get('end_line', -1)
        # Retain an unmatchable placeholder for a missing range, never compress ranks.
        if start < 1 or end < start or row.get('stale'):
            path, start, end = '__invalid_returned_range__', 0, 0
        results.append(SimpleNamespace(chunk=SimpleNamespace(
            file_path=path, start_line=start, end_line=end)))
    if len(results) > 10:
        raise ValueError('producer returned more than the registered top ten')
    return results


def evaluate_rows(tasks, rows, *, visible=False):
    per_query = []
    repos, languages, categories = defaultdict(list), defaultdict(list), defaultdict(list)
    missing = errors = 0
    for i, task in enumerate(tasks):
        identifier = f'semble-{i:04d}'
        row = rows.get(identifier)
        missing += row is None
        errors += bool(row and row.get('error'))
        results = locations(row or {}, visible=visible)
        ranks = [rank for target in task.all_relevant
                 if (rank := target_rank(results, target)) is not None]
        value = ndcg_at_k(ranks, len(task.all_relevant), 10)
        per_query.append({'id': identifier, 'repo': task.repo, 'category': task.category,
            'ndcg10': value, 'relevant_ranks': ranks, 'n_relevant': len(task.all_relevant),
            'top1': int(1 in ranks), 'hit10': int(bool(ranks))})
        repos[task.repo].append(value)
        languages[task.language].append(value)
        categories[task.category].append(value)
    means = lambda groups: {k: sum(v)/len(v) for k, v in groups.items()}
    repo_means = means(repos)
    return {'queries': len(tasks), 'repos': len(repos), 'missing': missing, 'errors': errors,
        'macro_repo_ndcg10': sum(repo_means.values())/len(repo_means),
        'micro_query_ndcg10': sum(x['ndcg10'] for x in per_query)/len(tasks),
        'target_top1': sum(x['top1'] for x in per_query)/len(tasks),
        'target_hit10': sum(x['hit10'] for x in per_query)/len(tasks),
        'by_repo': repo_means, 'by_language_query_mean': means(languages),
        'by_category_query_mean': means(categories), 'per_query': per_query}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    parser.add_argument('--tool-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if Path(inspect.getfile(ndcg_at_k)).resolve() != (args.tool_root/'benchmarks/metrics.py').resolve():
        raise ValueError('scorer must be imported from the registered Semble checkout')
    tasks = load_tasks(load_repo_specs())  # ALL specs, never available_repo_specs filtering.
    outputs = {}
    input_hashes = {}
    for engine in ('ken', 'semble'):
        for path in sorted((args.run/engine).glob('*/responses.json')):
            input_hashes[path.relative_to(args.run).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
            for row in json.loads(path.read_text()):
                for mode, response in row['modes'].items():
                    target = outputs.setdefault(mode, {})
                    if row['id'] in target:
                        raise ValueError('duplicate query response')
                    target[row['id']] = response
    expected = {f'semble-{i:04d}' for i in range(len(tasks))}
    if set(outputs) != {'ken-symbol-api', 'ken-file-api', 'ken-symbol-role',
                        'ken-file-role', 'semble-native'}:
        raise ValueError('all registered comparison modes required')
    if any(set(rows)-expected for rows in outputs.values()):
        raise ValueError('unexpected query IDs')
    reports = {mode: evaluate_rows(tasks, rows) for mode, rows in outputs.items()}
    visible = {mode: evaluate_rows(tasks, rows, visible=True) for mode, rows in outputs.items()}
    sources = [args.tool_root/'benchmarks'/name for name in ('data.py', 'metrics.py', 'repos.json')]
    sources += sorted((args.tool_root/'benchmarks/annotations').glob('*.json'))
    report = {'protocol': 'semble-public-protocol-v1', 'queries': len(tasks),
        'adapter_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'response_sha256': input_hashes,
        'source_hashes': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        'native_unit': reports, 'visible_prefix_overlap': visible}
    args.output.write_text(json.dumps(report, indent=2))
    for mode, value in reports.items():
        print(json.dumps({'mode': mode, **{k: v for k, v in value.items()
            if not k.startswith('by_') and k != 'per_query'}}))


if __name__ == '__main__':
    main()
