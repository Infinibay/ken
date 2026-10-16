"""Score only completely closed public captures; never imported by search workers."""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import math
from pathlib import Path
import statistics

from public_benchmarks_v222 import repoqa_correct_piece, repoqa_request, retrieval_metrics, sha


def correct_repoqa_piece(result: dict, reference: dict) -> bool:
    if not isinstance(result.get('entity'), dict) or not isinstance(result.get('entity_span'), dict):
        return False
    return repoqa_correct_piece(result, reference)


def load_closed_results(folder: Path, expected_ids: list[str]) -> dict[str, dict]:
    marker = folder / 'closure.json'
    if not marker.is_file():
        raise ValueError('capture not closed')
    closure = json.loads(marker.read_text())
    if closure['queries'] != len(expected_ids):
        raise ValueError('wrong closure denominator')
    responses = {}
    for name, digest in closure['response_pins'].items():
        path = (folder / name).resolve()
        if not path.is_relative_to(folder.resolve()) or sha(path) != digest:
            raise ValueError(f'closed artifact changed: {name}')
        if path.name != 'responses.json':
            continue
        for row in json.loads(path.read_text()):
            if row['id'] in responses:
                raise ValueError('duplicate response ID')
            responses[row['id']] = row
    if set(responses) != set(expected_ids):
        raise ValueError('missing or unknown response IDs')
    return responses


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * quantile
    lower = int(index)
    return ordered[lower] + (ordered[math.ceil(index)] - ordered[lower]) * (index - lower)


def aggregate(rows: list[dict], metrics: list[str]) -> dict:
    return {'queries': len(rows),
            **{key: statistics.mean(r[key] for r in rows) for key in metrics},
            'errors': sum(bool(r.get('error')) for r in rows)}


def costs(capture: Path, responses: dict[str, dict], additional: Path | None = None) -> dict:
    query_ms = [r['elapsed_ms'] for r in responses.values() if 'elapsed_ms' in r]
    provenance = [json.loads(path.read_text()) for path in capture.glob('*/provenance.json')]
    if additional is not None:
        provenance += [json.loads(path.read_text()) for path in additional.glob('*/provenance.json')]
    return {'timed_queries': len(query_ms), 'p50_ms': percentile(query_ms, .50),
        'p95_ms': percentile(query_ms, .95), 'max_ms': max(query_ms, default=None),
        'preparation_total_ms': sum(row['preparation_ms'] for row in provenance),
        'query_process_peak_rss_bytes': max((row['query_process_peak_rss_native'] *
            (1 if row['rss_unit'] == 'bytes' else 1024) for row in provenance), default=None),
        'preparation_child_peak_rss_bytes': max((row['prepare_child_peak_rss_native'] *
            (1 if row['rss_unit'] == 'bytes' else 1024) for row in provenance), default=None),
        'providers': sorted({provider for row in provenance for provider in row['providers']}),
        'note': 'Observed on CPU while other benchmark jobs may run concurrently; no isolated latency claim.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('track', choices=['repoqa', 'core'])
    args = parser.parse_args()
    out = Path.cwd() / 'output/development/repoqa-core-v222'
    registration = json.loads((out / 'registration.json').read_text())
    requests_path = out / f'{args.track}-requests.jsonl'
    track_registration = json.loads((out / 'core-registration.json').read_text()) if args.track == 'core' else registration['repoqa']
    assert sha(requests_path) == track_registration['requests_sha256']
    requests = [json.loads(line) for line in requests_path.read_text().splitlines()]
    capture = out / f'{args.track}-capture-v224'
    responses = load_closed_results(capture, [r['id'] for r in requests])
    # The sole predeclared infrastructure retry must close before the first label read.
    selected_pins = {'initial_closure_sha256': sha(capture / 'closure.json'),
                     'grader_sha256': sha(Path(__file__))}
    if args.track == 'repoqa':
        policy = json.loads((out / 'infra-retry-registration-v225.json').read_text())
        group = policy['eligible_group']
        retry = out / policy['replacement_capture']
        retry_ids = [r['id'] for r in requests if r['repo_id'] == group]
        replacements = load_closed_results(retry, retry_ids)
        assert all(responses[rid].get('error') for rid in retry_ids)
        responses.update(replacements)
        selected_pins['retry_closure_sha256'] = sha(retry / 'closure.json')
        selected_pins['retry_policy_sha256'] = sha(out / 'infra-retry-registration-v225.json')
    (out / f'{args.track}-final-selection-before-labels.json').write_text(json.dumps(selected_pins, indent=2) + '\n')
    rows, strata = [], collections.defaultdict(list)
    if args.track == 'repoqa':
        dataset = Path('/private/tmp/ken-repoqa-2024-06-23-v222.json.gz')
        assert sha(dataset) == track_registration['dataset_sha256']
        expected_references = {}
        for language, repositories in json.load(gzip.open(dataset)).items():
            for repository in repositories:
                for number, needle in enumerate(repository['needles']):
                    rid = repoqa_request(language, repository['repo'], number, needle, Path('/unused'))['id']
                    expected_references[rid] = {'language': language, 'repo': repository['repo'],
                        **{key: needle[key] for key in ('name', 'path', 'start_line', 'end_line', 'start_byte', 'end_byte')}}
        references = json.loads((out / 'repoqa-references.json').read_text())
        assert references == expected_references and set(references) == set(responses)
        metrics = ['top1_piece', 'top10_piece', 'mrr10_piece', 'ndcg10_piece', 'top1_file', 'top10_file']
        for request in requests:
            response = responses[request['id']]
            reference = references[request['id']]
            results = response.get('results', [])
            correct = [correct_repoqa_piece(item, reference) for item in results[:10]]
            ranks = [i + 1 for i, value in enumerate(correct) if value]
            rank = ranks[0] if ranks else None
            row = {'id': request['id'], 'repo_id': request['repo_id'], 'language': reference['language'],
                'top1_piece': int(bool(correct and correct[0])), 'top10_piece': int(bool(ranks)),
                'mrr10_piece': 1 / rank if rank else 0., 'ndcg10_piece': 1 / math.log2(rank + 1) if rank else 0.,
                'top1_file': int(bool(results and results[0]['path'] == reference['path'])),
                'top10_file': int(any(item['path'] == reference['path'] for item in results[:10])),
                'correct_ranks': ranks, 'error': response.get('error')}
            rows.append(row)
            strata[reference['language']].append(row)
        interpretation = 'Function identity over full shipped snapshots; derived retrieval metrics, not official long-context LLM SNF leaderboard score.'
    else:
        assert sha(out / 'core-sources.json') == track_registration['sources_sha256']
        source = json.loads((out / 'core-sources.json').read_text())
        assert sha(out / 'core-document-map.json') == track_registration['document_map_sha256']
        document_maps = json.loads((out / 'core-document-map.json').read_text())
        qrels_by_folder = {}
        metrics = ['hit1', 'hit10', 'recall10', 'ndcg10']
        for request in requests:
            response = responses[request['id']]
            snapshot = source[request['repo_id']]
            raw_folder = snapshot['raw_folder']
            if raw_folder not in qrels_by_folder:
                path = Path(raw_folder) / 'qrels.jsonl'
                raw_name = path.relative_to(out / 'core-raw').as_posix()
                assert sha(path) == track_registration['raw_file_pins'][raw_name]
                relevant = collections.defaultdict(dict)
                for line in path.read_text().splitlines():
                    item = json.loads(line)
                    assert item['score'] == 1, 'Binary official qrels expected'
                    relevant[str(item['query_id'])][str(item['corpus_id'])] = item['score']
                qrels_by_folder[raw_folder] = relevant
            relevant = qrels_by_folder[raw_folder][str(snapshot['public_query_id'])]
            mapping = document_maps[request['repo_id']]
            assert set(relevant) <= set(mapping.values()), 'Relevant document absent from public eligibility filter'
            order = [mapping[item['path']] for item in response.get('results', [])]
            row = {'id': request['id'], 'repo': snapshot['repo'], 'level': snapshot['level'],
                'query_id': snapshot['public_query_id'], 'relevant_docs': len(relevant), 'order': order,
                **retrieval_metrics(order, relevant), 'error': response.get('error')}
            rows.append(row)
            strata[snapshot['level']].append(row)
        interpretation = '18-case CPU pilot, three repositories, original text/UUID corpus through neutral .txt filesystem adapter and public snapshot eligibility. No full-group or native original-path claim; Recall@100 not measured.'
    report = {'track': args.track, 'interpretation': interpretation,
        'metrics': aggregate(rows, metrics), 'strata': {key: aggregate(group, metrics) for key, group in strata.items()},
        'costs': costs(capture, responses, retry if args.track == 'repoqa' else None),
        'rows': rows, 'capture_selection': selected_pins,
        'reserve': 'CLOSED', 'engine_tuned': False, 'release': False}
    (out / f'{args.track}-report-v224.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({key: report[key] for key in ['track', 'interpretation', 'metrics', 'strata', 'costs']}))


if __name__ == '__main__':
    main()
