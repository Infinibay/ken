"""A paired input-representation diagnostic, never an acceptance evaluation.

Keep each eligible document's bytes and UUID. Give parsable Python definitions
their native extension, using syntax alone and no reference labels.
"""
from collections import Counter
from pathlib import Path
import ast
import hashlib
import json
import os
import resource
import subprocess
import sys
import time


def is_python_definition(text):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return False
    return any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
               for node in ast.walk(tree))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def main():
    assert is_python_definition('def f():\n    return 1\n')
    assert is_python_definition('class C:\n    def m(self):\n        pass\n')
    assert is_python_definition('async def f():\n    return 1\n')
    assert not is_python_definition('How to define a function: def f()')
    assert not is_python_definition('"def f(): pass"')
    assert not is_python_definition('    def f(): pass')  # Do not repair raw snippets.
    assert not is_python_definition('x = 1\n')
    w = Path.cwd()
    base = w / 'output/development/repoqa-core-v222'
    dest = w / 'output/analysis/core-representation-v229'
    dest.mkdir(exist_ok=False)
    root = dest / 'project'
    (root / 'documents').mkdir(parents=True)
    registration = json.loads((base / 'registration.json').read_text())
    engine = Path(registration['engine'])
    assert sha(engine / 'SOURCE-MANIFEST.json') == registration['engine_manifest_sha256']
    for name, digest in json.loads((engine / 'SOURCE-MANIFEST.json').read_text())['files'].items():
        assert sha(engine / name) == digest
    sources = json.loads((base / 'core-sources.json').read_text())
    requests = [json.loads(line) for line in (base / 'core-requests.jsonl').read_text().splitlines()]
    matching = [r for r in requests if sources[r['repo_id']]['repo'] == 'pallets__flask'
                and sources[r['repo_id']]['level'] == 'LEVEL-2']
    assert len(matching) == 1
    public = matching[0]
    snapshot = sources[public['repo_id']]
    mapping, pins = {}, {}
    for name, digest in snapshot['source_pins'].items():
        path = Path(public['root']) / name
        assert sha(path) == digest
        data = path.read_bytes()
        native = is_python_definition(data.decode('utf-8'))
        relative = Path(name).with_suffix('.py' if native else '.txt').as_posix()
        target = root / relative
        assert relative not in pins
        target.write_bytes(data)
        assert sha(target) == digest
        pins[relative] = digest
        mapping[relative] = Path(name).stem
    assert len(pins) == snapshot['candidate_documents']
    request = public | {'root': str(root)}
    write(dest / 'registration.json', {
        'diagnostic_only': True, 'labels_already_exposed_in_original_pilot': True,
        'hypothesis': 'Native extensions restore symbol and role evidence lost by UUID.txt',
        'intervention': 'Only extension changes: AST-valid definition chunks .py; all others .txt',
        'held_constant': ['every candidate UUID', 'every text byte', 'query', 'file target',
                          'limit=10', 'max_chars=12000', '1024 reranker tokens', 'models', 'engine'],
        'not_restored': ['original paths', 'missing enclosing classes', 'original chunk boundaries'],
        'engine_manifest_sha256': registration['engine_manifest_sha256'],
        'script_sha256': sha(Path(__file__)), 'source_files': len(pins),
        'extensions': dict(Counter(Path(p).suffix for p in pins)),
        'classification_assertions_passed': 7, 'request': request,
        'no_reference_labels_read_by_worker': True, 'reserve': 'CLOSED'})
    write(dest / 'source-pins.json', pins)
    write(dest / 'document-map.json', mapping)
    sys.path.insert(0, str(engine / 'src'))
    import ken
    assert Path(ken.__file__).resolve().parents[2] == engine
    from ken.retrieval.public import find_best, render
    from ken.retrieval.connections import project_connection
    from ken.retrieval.best_resources import default_resources
    environment = os.environ | {'PYTHONPATH': str(engine / 'src'), 'PYTHONDONTWRITEBYTECODE': '1'}
    (root / '.ken').mkdir()
    (root / '.ken/search-context').symlink_to(base / 'core-context-cache', target_is_directory=True)
    started = time.perf_counter()
    with (dest / 'prepare.log').open('w') as log:
        subprocess.run([sys.executable, '-m', 'ken', 'retrieval', 'prepare', '--path', str(root), '--json'],
                       env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
    preparation_ms = (time.perf_counter() - started) * 1000
    with project_connection(root) as conn:
        paths = [r[0] for r in conn.execute('SELECT path FROM ci_files ORDER BY path')]
        assert set(paths) == set(pins)
        coverage = {'indexed_files': len(paths), 'symbol_count': conn.execute('SELECT COUNT(*) FROM ci_symbols').fetchone()[0],
                    'roles': dict(conn.execute('SELECT role, COUNT(*) FROM ci_passages GROUP BY role'))}
        warmup = find_best(conn, root, 'find code that prepares a value', scope='files', piece_kind='file')
        assert warmup.get('ok') is not False
        started = time.perf_counter()
        response = find_best(conn, root, public['query'], scope='files', piece_kind='file', limit=10, max_chars=12000)
        elapsed_ms = (time.perf_counter() - started) * 1000
        assert response.get('ok') is not False
        response['compact'] = render(response)
    for name, digest in pins.items():
        assert sha(root / name) == digest
    resources = default_resources()
    assert list(resources.neural.providers) == list(resources.context.providers) == ['CPUExecutionProvider']
    assert resources.neural._max_tokens == 1024
    assert not any(n in sys.modules for n in ['torch', 'transformers', 'sentence_transformers'])
    write(dest / 'response.json', response)
    write(dest / 'provenance.json', {'coverage': coverage, 'preparation_ms': preparation_ms,
        'query_ms': elapsed_ms, 'query_peak_rss_native': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'prepare_peak_rss_native': resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
        'rss_unit': 'bytes' if sys.platform == 'darwin' else 'KiB',
        'providers': list(resources.neural.providers), 'reranker_tokens': 1024,
        'engine_manifest_sha256': registration['engine_manifest_sha256'], 'reserve': 'CLOSED'})
    write(dest / 'closure.json', {'status': 'Closed before grading this intervention',
        'files': {p.name: sha(p) for p in dest.iterdir() if p.is_file() and p.name != 'closure.json'}})
    print(json.dumps({'closed': True, **coverage, 'preparation_ms': preparation_ms, 'query_ms': elapsed_ms}), flush=True)


if __name__ == '__main__':
    main()
