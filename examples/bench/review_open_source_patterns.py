"""Replay a manually reviewed oracle on pinned, local open-source examples.

Labels name an expected entity and pattern, independently of upstream directory
names. Sources are parsed only. Unknown/incomplete results are separate outcomes.
"""
from __future__ import annotations
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import time

from ken.structural.frontend import lower_source
from ken.structural.semantic import link_project
from ken.structural.query_view import query_graph
from ken.structural.relational import Executor
from ken.structural.query import QueryBudget
from ken.structural.rules import builtin_rules, query_registry
from ken.structural.model import IR_VERSION
from validate_pattern_corpus import EXT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    labels = json.loads(args.labels.read_text())
    registry = query_registry(builtin_rules())
    indexes = {}
    results = []
    for case in labels['cases']:
        root = (args.corpus / case['repo']).resolve()
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
        if revision != case['revision']:
            raise ValueError(f"revision mismatch: {case['repo']}")
        key = (case['repo'], tuple(f['path'] for f in case['files']))
        if key not in indexes:
            units = []
            start = time.perf_counter()
            for item in case['files']:
                path = (root / item['path']).resolve()
                if not path.is_relative_to(root):
                    raise ValueError('source outside repository')
                content = path.read_bytes()
                if sha256(content).hexdigest() != item['sha256']:
                    raise ValueError(f'source changed: {path}')
                units.append(lower_source(content, EXT[path.suffix], item['path']))
            index = query_graph(link_project(units))
            indexes[key] = index, (time.perf_counter() - start) * 1000
        index, build_ms = indexes[key]
        start = time.perf_counter()
        # Accuracy replay runs to completion. Resource ceilings belong in the
        # separate performance suite, not in this manually labelled oracle.
        outcome = Executor(index, registry, QueryBudget()).execute(registry[case['rule']])
        query_ms = (time.perf_counter() - start) * 1000
        selected = [m for m in outcome['matches']
                    if any(v in index.ir.entities and index.ir.entities[v].name == case['entity']
                           for v in m['bindings'].values())]
        actual = bool(selected)
        verdict = ('ambiguous' if case.get('ambiguous') else
                   'invalid' if index.ir.diagnostics else 'incomplete' if not outcome['complete'] else
                   'unknown' if not actual and outcome['unknown'] else
                   ('TP' if actual else 'FN') if case['expected'] else ('FP' if actual else 'TN'))
        results.append({**case, 'actual': actual, 'verdict': verdict, 'complete': outcome['complete'],
                        'unknown': outcome['unknown'], 'diagnostics': index.ir.diagnostics,
                        'build_ms': build_ms, 'query_ms': query_ms, 'stats': outcome['stats'],
                        'matches': selected})
        print(verdict, case['id'], flush=True)
    report = {'schema': 'ken-reviewed-open-source/1', 'ir_version': IR_VERSION,
              'budget': {'max_rows': None, 'max_states': None, 'max_matches': None, 'timeout_ms': None},
              'labels_sha256': sha256(args.labels.read_bytes()).hexdigest(),
              'runner_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'counts': dict(Counter(r['verdict'] for r in results)), 'results': results}
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(report['counts'])


if __name__ == '__main__':
    main()
