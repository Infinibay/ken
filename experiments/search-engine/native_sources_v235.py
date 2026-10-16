"""Exact native source projection and unchanged public query grouping."""
import tarfile
from pathlib import PurePosixPath

from public_benchmarks_v222 import sha


def extract_revision(archive, destination, root_name):
    destination.mkdir(parents=True, exist_ok=False)
    pins = {}
    with tarfile.open(archive, 'r:gz') as stream:
        for member in stream:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or path.parts[0] != root_name:
                raise ValueError(f'unsafe or unexpected archive path: {member.name}')
            if member.isdir():
                continue
            if not member.isfile() or len(path.parts) < 2:
                raise ValueError(f'unsupported archive member: {member.name}')
            relative = PurePosixPath(*path.parts[1:]).as_posix()
            if relative in pins or relative.split('/')[0] == '.ken':
                raise ValueError(f'duplicate or reserved path: {relative}')
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with stream.extractfile(member) as source:
                target.write_bytes(source.read())
            pins[relative] = sha(target)
    return pins


def group_requests(requests, sources, revisions):
    if len({r['id'] for r in requests}) != len(requests):
        raise ValueError('duplicate case IDs')
    grouped = {r['instance_id']: dict(r, cases=[]) for r in revisions}
    for request in requests:
        source = sources[request['repo_id']]
        group = grouped[source['public_query_id']]
        if 'query' in group and group['query'] != request['query']:
            raise ValueError('query text differs between levels')
        group['query'] = request['query']
        group['cases'].append({'id': request['id'], 'level': source['level']})
    if any(not g['cases'] for g in grouped.values()):
        raise ValueError('revision without original query')
    return [grouped[k] for k in sorted(grouped)]
