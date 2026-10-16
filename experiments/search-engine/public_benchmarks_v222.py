"""Dataset adapters and piece identities; never import these in the search engine."""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checked_path(root: Path, name: str) -> Path:
    relative = Path(name)
    target = (root / relative).resolve()
    if relative.is_absolute() or not target.is_relative_to(root.resolve()):
        raise ValueError(f'unsafe snapshot path: {name}')
    return target


def repoqa_request(language: str, repo: str, number: int, needle: dict, root: Path) -> dict:
    identity = f'{language}/{repo}/{number}'
    return {'id': hashlib.sha256(identity.encode()).hexdigest()[:24],
            'repo_id': language + '--' + repo.replace('/', '__'), 'root': str(root),
            'query': needle['description'], 'scope': 'symbols', 'piece_kind': 'symbol'}


def core_documents(documents: list[dict], eligible: list[str]) -> dict[str, dict]:
    allowed = set(map(str, eligible))
    lookup = {str(d['_id']): d for d in documents}
    if len(lookup) != len(documents):
        raise ValueError('duplicate corpus IDs')
    if allowed - lookup.keys():
        raise ValueError('missing eligible corpus IDs')
    # Opaque UUID filenames are a filesystem adapter, not original source paths.
    result = {}
    for identifier in sorted(allowed):
        if not re.fullmatch(r'[A-Za-z0-9_-]+', identifier):
            raise ValueError('unsafe corpus identifier')
        result[f'documents/{identifier}.txt'] = {'id': identifier, 'text': lookup[identifier]['text']}
    return result


def repoqa_correct_piece(result: dict, reference: dict) -> bool:
    entity = result.get('entity', {})
    extent = result.get('entity_span', {})
    leaf = (entity.get('qualname') or '').replace('::', '.').rsplit('.', 1)[-1]
    expected = reference['name'].replace('::', '.').rsplit('.', 1)[-1]
    # Reference ranges are zero-based/end-exclusive; Ken's are one-based/inclusive.
    first, last = reference['start_line'] + 1, reference['end_line']
    return (result.get('path') == reference['path'] and result.get('piece_kind') == 'symbol'
            and entity.get('kind') in {'function', 'method', 'constructor'}
            and leaf == expected and extent.get('end_line') == last
            and first - 10 <= extent.get('start_line', -100) <= first)


def retrieval_metrics(order: list[str], relevant: dict[str, int], *, k: int = 10) -> dict:
    if len(set(order)) != len(order):
        raise ValueError('duplicate predictions')
    positives = {str(key): value for key, value in relevant.items() if value > 0}
    gains = [positives.get(identifier, 0) for identifier in order[:k]]
    dcg = sum(value / math.log2(rank + 2) for rank, value in enumerate(gains))
    ideal = sum(value / math.log2(rank + 2)
                for rank, value in enumerate(sorted(positives.values(), reverse=True)[:k]))
    hits = sum(value > 0 for value in gains)
    return {'hit1': int(bool(gains and gains[0] > 0)), 'hit10': int(hits > 0),
            'recall10': hits / len(positives) if positives else 0.,
            'ndcg10': dcg / ideal if ideal else 0.}
