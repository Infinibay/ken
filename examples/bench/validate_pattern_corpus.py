"""Audit external, labelled examples without importing or running their code.

Run with Ken's Python environment: python examples/bench/validate_pattern_corpus.py
--corpus /tmp/ken-pattern-corpus --output docs/structural-validation/labelled-corpus
Labels come from upstream directory names, not an independent correctness oracle.
No third-party source is copied into the report. Each example gets its own graph.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import time
import tomllib

from ken.structural.frontend import lower_source
from ken.structural.model import FactIndex
from ken.structural.query import QueryBudget
from ken.structural.rules import builtin_rules, execute_rules
from ken.structural.semantic import link_project

REPOS = {
    'across-languages': 'Eng-Elias/design-patterns-across-languages',
    'cpp-patterns': 'JakubVojvoda/design-patterns-cpp',
    'python-patterns': 'faif/python-patterns',
    'java-patterns': 'iluwatar/java-design-patterns',
    'guru-rust': 'RefactoringGuru/design-patterns-rust',
    'pandovski': 'ZoranPandovski/design-patterns',
    'go-patterns': 'tmrts/go-patterns',
    'php-patterns': 'DesignPatternsPHP/DesignPatternsPHP',
    'swift-patterns': 'ochococo/Design-Patterns-In-Swift',
}
EXT = {'.py': 'python', '.go': 'go', '.rs': 'rust', '.ts': 'typescript',
       '.js': 'javascript', '.java': 'java', '.cs': 'csharp', '.cpp': 'cpp',
       '.hpp': 'cpp', '.h': 'cpp'}
ALIASES = {'template': 'template-method', 'iterator-alt': 'iterator',
           'flyweight-with-metaclass': 'flyweight'}


def label(name):
    key = name.lower().replace('_', '-').replace(' ', '-')
    return ALIASES.get(key, key)


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, text=True).strip()


def source_file(path):
    p = Path(path)
    return (p.suffix in EXT and not p.name.startswith('test_')
            and not p.name.endswith(('_test.go', '.test.ts', '.spec.ts'))
            and not any(x in {'tests', 'test', 'node_modules', 'target'} for x in p.parts)
            and p.name not in {'jest.config.js', '__init__.py'})


def discover(root, name, tracked, gof):
    """Conservative boundaries; nested Pandovski projects are deferred explicitly."""
    cases = []

    def add(scope, expected, files):
        files = sorted(p for p in files if source_file(p))
        if files and expected in gof:
            cases.append({'scope': scope, 'expected': expected, 'files': files,
                          'languages': sorted({EXT[Path(p).suffix] for p in files})})

    if name == 'across-languages':
        for directory in sorted(root.glob('*/*/*/*')):
            if directory.name in {'python', 'go', 'typescript'}:
                scope = directory.relative_to(root).as_posix() + '/'
                add(scope, label(directory.parent.parent.name), [p for p in tracked if p.startswith(scope)])
    elif name == 'cpp-patterns':
        for p in tracked:
            if p.endswith('.cpp'):
                add(p, label(Path(p).parts[0]), [p])
    elif name == 'python-patterns':
        for p in tracked:
            if p.startswith('patterns/') and p.endswith('.py'):
                # "factory" and Borg are not silently relabelled as GoF variants.
                add(p, label(Path(p).stem), [p])
    elif name == 'java-patterns':
        for expected in sorted(gof):
            scope = expected + '/src/main/java/'
            add(scope, expected, [p for p in tracked if p.startswith(scope)])
    elif name == 'guru-rust':
        for cargo in sorted(root.glob('*/*/**/Cargo.toml')):
            scope = cargo.parent.relative_to(root).as_posix() + '/'
            expected = label(Path(scope).parts[1])
            config = tomllib.loads(cargo.read_text())
            bins = [b['path'] for b in config.get('bin', [])]
            if not bins:
                # A library is a collaborator, not an independent labelled example.
                continue
            files = [p for p in tracked if p.startswith(scope) and p.endswith('.rs')]
            visited = set()

            def dependencies(directory):
                directory = directory.resolve()
                directory.relative_to(root.resolve())
                if directory in visited:
                    return []
                visited.add(directory)
                data = tomllib.loads((directory / 'Cargo.toml').read_text())
                found = []
                for value in data.get('dependencies', {}).values():
                    if isinstance(value, dict) and 'path' in value:
                        dep = (directory / value['path']).resolve()
                        prefix = dep.relative_to(root.resolve()).as_posix() + '/'
                        found.extend(p for p in tracked if p.startswith(prefix) and p.endswith('.rs'))
                        found.extend(dependencies(dep))
                return found

            files = sorted(set(files + dependencies(cargo.parent)))
            if len(bins) > 1:
                # Other bin entry points are separate programs; modules are shared.
                for entry in bins:
                    add(scope + entry, expected, [p for p in files if p not in
                        {scope + b for b in bins if b != entry}])
            else:
                add(scope, expected, files)
    elif name == 'pandovski':
        for directory in sorted(root.glob('*/*/*')):
            if not directory.is_dir():
                continue
            scope = directory.relative_to(root).as_posix() + '/'
            files = [p for p in tracked if p.startswith(scope) and source_file(p)]
            # Only flat examples: do not combine independent nested implementations.
            if files and all(Path(p).parent == Path(scope) for p in files):
                add(scope, label(directory.parent.name), files)
    elif name == 'go-patterns':
        for p in tracked:
            if p.endswith('.go'):
                add(p, label(Path(p).parent.name), [p])
    return cases


def scan(root, case, registry):
    start = time.monotonic()
    files = []
    units = []
    for p in case['files']:
        path = root / p
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'not a regular source file: {path}')
        source = path.read_bytes()
        files.append({'path': p, 'sha256': hashlib.sha256(source).hexdigest()})
        units.append(lower_source(source, EXT[path.suffix], p))
    graph = link_project(units)
    budget = QueryBudget(max_matches=1000, max_rows=500000, max_states=100000, timeout_ms=5000)
    raw = execute_rules(FactIndex(graph), [r for r in registry if 'gof' in r.collections],
                        budget, registry=registry)
    matches = []
    for hit in raw['matches']:
        matches.append({'rule': hit['id'], 'variant': hit['variant'], 'status': hit['status'],
                        'roles': {k: {'name': graph.entities[v].name,
                                      'path': graph.entities[v].path, 'line': graph.entities[v].line}
                                  for k, v in hit['bindings'].items() if v in graph.entities}})
    return {**case, 'files': files, 'diagnostics': graph.diagnostics,
            'entities': len(graph.entities), 'facts': len(graph.facts),
            'elapsed_ms': round(1000 * (time.monotonic() - start), 2),
            'expected_found': any(m['rule'] == case['expected'] for m in matches),
            'matches': matches, 'outcomes': raw['outcomes']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    registry = builtin_rules()
    gof = {r.id for r in registry if 'gof' in r.collections}
    engine = Path(lower_source.__code__.co_filename).parent
    manifest = {'method': 'upstream labels; isolated example graphs; all 23 canonical GoF queries',
                'budget_per_query': {'max_matches': 1000, 'max_rows': 500000,
                                     'max_states': 100000, 'timeout_ms': 5000},
                'engine_sha256': {str(p.relative_to(engine)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted(engine.rglob('*')) if p.suffix in {'.py', '.toml'}},
                'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'repos': []}
    for name, upstream in REPOS.items():
        root = args.corpus / name
        tracked = git(root, 'ls-files').splitlines()
        cases = discover(root, name, tracked, gof)
        repo = {'name': name, 'url': 'https://github.com/' + upstream,
                'commit': git(root, 'rev-parse', 'HEAD'),
                'tracked_files': len(tracked),
                'extensions': dict(Counter(Path(p).suffix for p in tracked)),
                'license_files': [p for p in tracked if Path(p).name.lower().startswith(('license', 'copying'))],
                'cases': len(cases), 'selected_files': len({p for c in cases for p in c['files']}),
                'status': 'scanned subset' if cases else 'inventoried; unsupported structural frontend'}
        results = []
        for case in cases:
            try:
                result = scan(root, case, registry)
            except Exception as exc:
                result = {**case, 'error': repr(exc)}
            results.append(result)
            print(name, case['scope'], result.get('expected_found', result.get('error')), flush=True)
        repo['expected_found'] = sum(r.get('expected_found', False) for r in results)
        repo['errors'] = sum('error' in r for r in results)
        (args.output / (name + '.json')).write_text(json.dumps({'repo': repo, 'results': results}, indent=2) + '\n')
        manifest['repos'].append(repo)
        (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
