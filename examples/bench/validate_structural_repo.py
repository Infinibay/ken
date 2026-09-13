"""Read-only real-repository validation; never imports or executes target code.

Example: python examples/bench/validate_structural_repo.py ../infinidev --prefix src/ --output /tmp/infinidev.json
Python generators are independently located with ast; this checks syntax coverage,
not whether the generator implements the intent of the GoF Iterator pattern.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import fnmatch
import json
import subprocess
import time
from pathlib import Path
from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.model import FactIndex
from ken.structural.rules import builtin_rules, execute_rules, named_rule, SavedRule, select_rules
from ken.structural.query import QueryBudget

EXTENSIONS = {'.py': 'python', '.go': 'go', '.rs': 'rust', '.ts': 'typescript', '.js': 'javascript', '.java': 'java', '.cs': 'csharp', '.cpp': 'cpp'}
EXCLUDED = {'tests', 'testdata', 'benchmarks', 'tools', 'internal', 'zaptest', 'target', 'node_modules', '.venv', '__pycache__'}


def generators(source: bytes, path: str) -> set[tuple[str, str, int]]:
    tree = ast.parse(source)
    found = set()
    def visit(node, owner=None):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            owner = node
        elif isinstance(node, (ast.ClassDef, ast.Lambda)):
            owner = None
        if isinstance(node, (ast.Yield, ast.YieldFrom)) and owner:
            found.add((path, owner.name, owner.lineno))
        for child in ast.iter_child_nodes(node):
            visit(child, owner)
    visit(tree)
    return found


def validate(root: Path, prefix: str, exclude_globs: list[str] | None = None,
             collections: list[str] | None = None) -> dict:
    tracked = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], cwd=root, text=True).splitlines()
    paths = sorted({p for p in tracked if p.startswith(prefix) and Path(p).suffix in EXTENSIONS
                    and not any(fnmatch.fnmatchcase(p, pattern) for pattern in exclude_globs or [])
                    and not p.endswith('_test.go') and not any(x in EXCLUDED for x in Path(p).parts)})
    units, manifests, oracle, ast_errors = [], [], set(), []
    start = time.monotonic()
    for path in paths:
        file = root / path
        if not file.is_file() or file.is_symlink():
            continue
        source = file.read_bytes()
        language = EXTENSIONS[file.suffix]
        units.append(lower_source(source, language, path))
        manifests.append({'path': path, 'sha256': hashlib.sha256(source).hexdigest(), 'language': language})
        if language == 'python':
            try: oracle |= generators(source, path)
            except (SyntaxError, UnicodeError) as exc: ast_errors.append({'path': path, 'error': str(exc)})
    graph = link_project(units)
    del units
    result = {'repo': root.name, 'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
              'scope': prefix, 'exclude_globs': exclude_globs or [], 'excluded_components': sorted(EXCLUDED), 'files': manifests, 'diagnostics': graph.diagnostics,
              'analysis_ms': round((time.monotonic()-start)*1000, 2), 'entities': len(graph.entities), 'facts': len(graph.facts), 'rules': {}}
    engine_root = Path(lower_source.__code__.co_filename).parent
    result['engine'] = {'ir_version': graph.version, 'source_sha256': {
        str(p.relative_to(engine_root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(engine_root.rglob('*')) if p.suffix in {'.py', '.toml'}
    }}
    print(root.name, 'files', len(manifests), 'entities', len(graph.entities), flush=True)
    registry = builtin_rules()
    index = FactIndex(graph)
    budget = QueryBudget(max_matches=1000, max_rows=500000, max_states=100000, timeout_ms=5000)
    result['budget'] = {'max_matches':1000, 'max_rows':500000, 'max_states':100000, 'timeout_ms':5000}
    selected = [r for r in registry if 'gof' in r.collections] + [named_rule(id, registry) for id in ['gof.iterator', 'gof.builder', 'iterator#generator', 'iterator#delegated-generator']]
    if collections:
        selected = select_rules(registry, collections=collections)
    result['collections'] = collections or ['gof']
    selected.append(SavedRule('syntax.generators', 'query generators { callable(generator: true) as $iterator; emit $iterator; }'))
    # Share graph normalization and registry compilation across the batch;
    # every root still receives its own independent budget.
    raw = execute_rules(index, selected, budget, registry=registry)
    for rule in selected:
        try:
            matches = []
            for hit in raw['matches']:
                if hit['id'] != rule.id:
                    continue
                roles = {k: {'name': graph.entities[v].name, 'path': graph.entities[v].path,
                              'line': graph.entities[v].line, 'kind': graph.entities[v].kind}
                         for k, v in hit['bindings'].items() if v in graph.entities}
                matches.append({'roles': roles, 'variant': hit['variant'], 'status': hit['status']})
            result['rules'][rule.id] = {'outcome': raw['outcomes'][rule.id], 'matches': matches}
            print(root.name, rule.id, len(matches), raw['outcomes'][rule.id]['complete'], flush=True)
        except Exception as exc:
            result['rules'][rule.id] = {'error': repr(exc)}
    actual = set()
    for key in ['syntax.generators']:
        for hit in result['rules'][key].get('matches', []):
            for role in hit['roles'].values():
                if role['path'].endswith('.py'):
                    actual.add((role['path'], role['name'], role['line']))
    result['python_generator_oracle'] = {'expected': sorted(oracle), 'detected': sorted(actual),
        'missing': sorted(oracle-actual), 'unexpected': sorted(actual-oracle), 'parse_errors': ast_errors}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--prefix', default='')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exclude-glob', action='append', default=[])
    parser.add_argument('--collection', action='append', default=[])
    args = parser.parse_args()
    result = validate(args.root.resolve(), args.prefix, args.exclude_glob, args.collection)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
