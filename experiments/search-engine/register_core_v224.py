"""Download a preregistered CORE pilot; do not interpret relevance labels."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import json
import subprocess

from public_benchmarks_v222 import checked_path, core_documents, sha

w = Path.cwd()
out = w / 'output/development/repoqa-core-v222'
registration = json.loads((out / 'registration.json').read_text())
revision = registration['core']['dataset_commit']
info = json.loads(Path('/private/tmp/ken-core-info-v222.json').read_text())
assert info['sha'] == revision
repos = registration['core']['pilot_repositories']
levels = registration['core']['levels']
files = [item for item in info['siblings']
         if any(item['rfilename'].startswith(f'data/{level}/SWE-bench_Verified/{repo}/')
                for level in levels for repo in repos)
         and item['rfilename'].rsplit('/', 1)[-1] in {'corpus.jsonl', 'queries.jsonl', 'qrels.jsonl'}]
assert len(files) == 18
raw = out / 'core-raw'
raw.mkdir(exist_ok=False)
def download(item):
    relative = item['rfilename']
    target = checked_path(raw, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['curl', '-fLsS', '--retry', '2',
        f'https://huggingface.co/datasets/zhangfw123/CORE-Bench/resolve/{revision}/{relative}',
        '-o', str(target)], check=True)
    assert target.stat().st_size == item['size'], relative
    digest = sha(target)
    if 'lfs' in item:
        assert digest == item['lfs']['sha256'], relative
    return relative, digest
with ThreadPoolExecutor(max_workers=6) as pool:
    raw_pins = dict(pool.map(download, files))

requests, snapshots, document_maps = [], {}, {}
for level in levels:
    for repo in repos:
        folder = raw / f'data/{level}/SWE-bench_Verified/{repo}'
        documents = [json.loads(line) for line in (folder / 'corpus.jsonl').read_text().splitlines()]
        queries = [json.loads(line) for line in (folder / 'queries.jsonl').read_text().splitlines()]
        assert all(set(d) == {'_id', 'text'} for d in documents)
        for query in queries:
            identity = f'{level}/SWE-bench_Verified/{repo}/{query["_id"]}'
            identifier = hashlib.sha256(identity.encode()).hexdigest()[:24]
            group = level.lower() + '--' + repo + '--' + identifier
            root = out / 'core-snapshots' / group
            root.mkdir(parents=True)
            eligible = query.get('filtered_corpus_id', [d['_id'] for d in documents])
            mapped = core_documents(documents, eligible)
            pins = {}
            for name, document in mapped.items():
                target = checked_path(root, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(document['text'].encode('utf-8'))
                pins[name] = sha(target)
            snapshots[group] = {'source_pins': pins, 'repo': repo, 'level': level,
                'candidate_documents': len(mapped), 'public_query_id': query['_id'],
                'raw_folder': str(folder), 'eligibility': 'Original filtered_corpus_id; all allowed documents, no qrels filtering',
                'original_paths_available': False}
            document_maps[group] = {path: item['id'] for path, item in mapped.items()}
            requests.append({'id': identifier, 'repo_id': group, 'root': str(root),
                'query': query['text'], 'scope': 'files', 'piece_kind': 'file'})
assert len(requests) == registration['core']['queries_expected'] == 18
def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
(out / 'core-requests.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in requests))
write(out / 'core-sources.json', snapshots)
write(out / 'core-document-map.json', document_maps)
write(out / 'core-registration.json', {'queries': len(requests), 'repositories': len(repos), 'levels': levels,
    'requests_sha256': sha(out / 'core-requests.jsonl'), 'sources_sha256': sha(out / 'core-sources.json'),
    'document_map_sha256': sha(out / 'core-document-map.json'), 'raw_file_pins': raw_pins,
    'script_sha256': sha(Path(__file__)), 'relevance_labels_interpreted': False,
    'complete_CORE_Bench': False, 'reserve': 'CLOSED'})
print(json.dumps({'queries': len(requests), 'snapshots': len(snapshots), 'selected_repos': repos,
                  'raw_bytes': sum(item['size'] for item in files)}))
