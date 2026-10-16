"""Integrity checks and aggregation for native CORE capture."""
import json

from public_benchmarks_v222 import sha, checked_path


def validate_result(result, root, source_pins):
    path = result['path']
    if path not in source_pins or result.get('stale') is not False:
        raise ValueError('unknown path or stale result')
    source = checked_path(root, path)
    if sha(source) != source_pins[path] or result.get('source_hash') != source_pins[path]:
        raise ValueError('result source hash mismatch')
    if any(not isinstance(span.get('content'), str) for span in result.get('evidence', [])):
        raise ValueError('evidence must include visible content')
    lines = source.read_bytes().decode('utf-8').splitlines()
    for span in [result['entity_span'], *result.get('evidence', [])]:
        start, end = span['start_line'], span['end_line']
        if not 1 <= start <= end <= len(lines):
            raise ValueError('result range outside source')
        if 'content' in span and span['content'] != '\n'.join(lines[start-1:end]):
            raise ValueError('result evidence differs from source')
    return True


def score_slots(results, targets, predicate):
    rank = next((i for i, result in enumerate(results[:10], 1)
                 if any(predicate(result, target) for target in targets)), None)
    return {'hit1': int(rank == 1), 'hit10': int(rank is not None),
            'first_relevant_rank': rank}


def verify_capture(destination, required_paths=()):
    path = destination / 'closure.json'
    if not path.exists():
        raise ValueError('capture not closed')
    closure = json.loads(path.read_text())
    if not closure.get('all_outputs_closed'):
        raise ValueError('capture not closed')
    if not closure.get('response_pins'):
        raise ValueError('empty capture manifest')
    if set(required_paths) - closure['response_pins'].keys():
        raise ValueError('unpinned consumed capture path')
    for name, digest in closure['response_pins'].items():
        if sha(checked_path(destination, name)) != digest:
            raise ValueError('closed capture changed: ' + name)
    return closure
