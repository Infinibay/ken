"""Freeze public RepoQA requests and exact shipped source, with separate references."""
from pathlib import Path
import gzip
import json
import subprocess

from public_benchmarks_v222 import checked_path, repoqa_request, sha

w = Path.cwd()
out = w / 'output/development/repoqa-core-v222'
out.mkdir(exist_ok=False)
source = Path('/private/tmp/ken-repoqa-2024-06-23-v222.json.gz')
engine = w / 'output/frozen/bounded-symbol-ranking-v214'
engine_pin = 'b9e86b7fe4e7a405f94c47a1f157b97765eed97f3581f356f927d738e0f79079'
assert sha(engine / 'SOURCE-MANIFEST.json') == engine_pin
data = json.load(gzip.open(source))
requests, references, roots = [], {}, {}
for language, repositories in data.items():
    assert len(repositories) == 10
    for repository in repositories:
        repo_id = language + '--' + repository['repo'].replace('/', '__')
        root = out / 'repoqa-snapshots' / repo_id
        root.mkdir(parents=True)
        pins = {}
        for path, content in repository['content'].items():
            target = checked_path(root, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.encode('utf-8'))
            pins[path] = sha(target)
        assert len(repository['needles']) == 10
        for number, needle in enumerate(repository['needles']):
            row = repoqa_request(language, repository['repo'], number, needle, root)
            requests.append(row)
            references[row['id']] = {'language': language, 'repo': repository['repo'],
                **{key: needle[key] for key in ('name', 'path', 'start_line', 'end_line', 'start_byte', 'end_byte')}}
        roots[repo_id] = {'commit': repository['commit_sha'], 'source_pins': pins,
                         'scope': 'Entire shipped content snapshot, not a cloned full upstream repo'}
assert len(requests) == len(references) == 600
def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
(out / 'repoqa-requests.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in requests))
write(out / 'repoqa-references.json', references)
write(out / 'repoqa-sources.json', roots)
write(out / 'registration.json', {
    'status': 'Registered before any new benchmark search outputs',
    'engine_manifest_sha256': engine_pin, 'engine': str(engine),
    'engine_commit': '8ce6b00c3a653e2effa46ec02b7acedd4c100501',
    'repoqa': {'dataset': '2024-06-23', 'dataset_sha256': sha(source),
        'evaluator_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd='/private/tmp/ken-repoqa-public-v222', text=True).strip(),
        'queries': 600, 'repositories': 60, 'requests_sha256': sha(out / 'repoqa-requests.jsonl'),
        'sources_sha256': sha(out / 'repoqa-sources.json'),
        'variant': 'retrieval over entire shipped repository content; original unmodified descriptions',
        'scoring': 'Exact path + function leaf + definition end; decorator start may precede reference by <=10 lines. No file-only or class credit. Native returned slots, no dedup.',
        'official_llm_snf_score': False},
    'core': {'dataset_commit': '23da5d97a8a4495d4bd6d5616aa86d5a12a60699',
        'evaluator_commit': '5d00cdcaade77796fa6e5ac4852404002029c00a',
        'pilot_repositories': ['mwaskom__seaborn', 'pallets__flask', 'psf__requests'],
        'levels': ['LEVEL-2', 'LEVEL-3'], 'queries_expected': 18,
        'selection': 'Three smallest shipped SWE-bench Verified corpus unions by total bytes across both levels; selected before outputs or qrels inspection.',
        'adapter': 'One exact original corpus text per opaque UUID .txt file; public filtered_corpus_id determines snapshot eligibility. No reconstructed original path or invented code language.',
        'full_benchmark': False, 'official_complete_group_score': False,
        'metric': 'Original binary qrels, NDCG@10 and relevant-document Recall@10; any-relevant Hit@1/10 separately. Normal API provides ten slots; Recall@100 not claimed.'},
    'search': {'scope_repoqa': 'symbols', 'scope_core': 'files', 'piece_kind': 'explicit benchmark task kind',
        'limit': 10, 'max_chars': 12000, 'purpose': 'auto', 'reranker_tokens': 1024,
        'configuration': 'Unmodified frozen production engine; no new model or tuning'},
    'timing': 'Observed CPU wall time and process peak RSS. Separate preparation. Other benchmark jobs may run concurrently; no isolated latency/speedup claim.',
    'closure': 'Each entire benchmark track closes before its first scoring. Failed queries stay in denominator.',
    'reserve': 'CLOSED', 'release': False})
print(json.dumps({'repoqa_queries': len(requests), 'repoqa_repos': len(roots), 'core_pilot_queries': 18}))
