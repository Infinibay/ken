"""Bind cached source features to their original request/pool row identities."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np


def validate_replay_parent(parent: Path, pools: Path, *,
                           extension: Path | None = None) -> dict[str, str]:
    receipts: dict[str, str] = {}

    def fingerprint(path: Path) -> str:
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        receipts[str(path)] = digest
        return digest

    parent_registration = parent/'registration.json'
    pool_registration = pools/'registration.json'
    record = json.loads(parent_registration.read_text())
    source = json.loads(pool_registration.read_text())
    fingerprint(parent_registration)
    extended = None
    if extension is not None:
        extended = json.loads((extension/'registration.json').read_text())
        fingerprint(extension/'registration.json')
        if (extended['parent_features_registration_sha256'] != fingerprint(parent_registration)
                or set(extended['query_repos']) != set(record['query_repos'])
                or extended['features'][:len(record['features'])] != record['features']):
            raise ValueError('feature extension must preserve its complete registered parent')
    candidates_file = pools/'candidates.jsonl'
    for path in (pool_registration, candidates_file):
        if record['public_inputs'][str(path)] != fingerprint(path):
            raise ValueError('cached feature requests/pool source differs from its registered parent')
    candidate_rows = [json.loads(line) for line in candidates_file.read_text().splitlines()]
    candidates = {row['id']: row['candidates'] for row in candidate_rows}
    if len(candidates) != len(candidate_rows) or set(record['query_repos']) != set(source['repos']):
        raise ValueError('unique candidate IDs and complete parent repositories required')
    request_ids: set[str] = set()
    for repo in sorted(record['query_repos']):
        requests = pools/'requests'/f'{repo}.jsonl'
        baseline, extra = pools/f'{repo}.npz', parent/f'{repo}.npz'
        if (fingerprint(requests) != source['repos'][repo]['requests_sha256']
                or fingerprint(baseline) != source['repos'][repo]['features_sha256']
                or fingerprint(extra) != record['query_repos'][repo]['output_sha256']):
            raise ValueError('cached feature input artifact changed')
        rows = [json.loads(line) for line in requests.read_text().splitlines()]
        for row in rows:
            if (set(row) != {'id', 'repo_id', 'request'} or row['repo_id'] != repo
                    or row['id'] in request_ids or row['id'] not in candidates):
                raise ValueError('original unique public request identity required')
            request_ids.add(row['id'])
        with np.load(baseline) as original, np.load(extra) as child:
            if (original['x'].ndim != 2 or child['x'].ndim != 2
                    or original['qid'].ndim != 1 or child['qid'].ndim != 1
                    or original['index'].shape != original['qid'].shape
                    or child['index'].shape != child['qid'].shape
                    or len(original['x']) != len(original['qid'])):
                raise ValueError('cached feature matrices and row identity arrays required')
            width = original['x'].shape[1]
            if (len(record['features']) < width
                    or child['x'].shape != (len(original['qid']), len(record['features']))
                    or not np.array_equal(original['qid'], child['qid'])
                    or not np.array_equal(original['index'], child['index'])
                    or not np.array_equal(original['x'], child['x'][:, :width])
                    or not np.isfinite(child['x']).all()):
                raise ValueError('cached feature rows, qids or baseline prefix changed')
            if set(original['qid']) - {row['id'] for row in rows}:
                raise ValueError('feature row refers to a different original request')
            for row in rows:
                selected = np.flatnonzero(original['qid'] == row['id'])
                if not np.array_equal(original['index'][selected],
                                      np.arange(len(candidates[row['id']]))):
                    raise ValueError('feature rows differ from original canonical candidate order')
            if extension is not None and extended is not None:
                path = extension/f'{repo}.npz'
                metadata = extended['query_repos'][repo]
                if (fingerprint(path) != metadata['output_sha256']
                        or fingerprint(extra) != metadata['parent_features_sha256']):
                    raise ValueError('feature extension input artifact changed')
                with np.load(path) as appended:
                    if (appended['x'].ndim != 2
                            or appended['x'].shape != (len(child['qid']), len(extended['features']))
                            or not np.array_equal(appended['qid'], child['qid'])
                            or not np.array_equal(appended['index'], child['index'])
                            or not np.array_equal(appended['x'][:, :len(record['features'])], child['x'])
                            or not np.isfinite(appended['x']).all()):
                        raise ValueError('feature extension rows or complete parent prefix changed')
    if request_ids != set(candidates):
        raise ValueError('cached parent must retain every original request, including empty pools')
    # Guard read/check races as well as long-lived stale cached files.
    for receipt_path, digest in receipts.items():
        with Path(receipt_path).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise ValueError('cached feature input changed while validating')
    return receipts
