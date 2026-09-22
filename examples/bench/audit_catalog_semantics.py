"""Replay labelled source counterexamples without executing the source programs.

The output separates the oracle for the selected variant from matches of sibling
variants. Incomplete searches and parser failures never count as negative results.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from ken.structural.frontend import lower_source
from ken.structural.kenql import Engine, query_graph
from ken.structural.model import IR_VERSION
from ken.structural.query import QueryBudget
from ken.structural.rules import builtin_rules, query_registry
from ken.structural.semantic import link_project


def audit(cases):
    started = time.perf_counter()
    registry = builtin_rules()
    by_id = {r.id: r for r in registry}
    compiled = query_registry(registry)
    registry_seconds = time.perf_counter() - started
    budget = QueryBudget(max_matches=200, max_rows=500000, max_states=100000, timeout_ms=3000)
    results = []
    for case in cases:
        case_started = time.perf_counter()
        parent = by_id[case['rule']]
        names = [parent.id]
        names += [parent.id+'#'+v['id'] for v in parent.variants if v['status']=='ready']
        names += [parent.id+'.'+o['id'] for o in parent.operations if o['status']=='ready']
        graph = link_project([lower_source(case['source'], case['language'], case['id'])])
        lowered = time.perf_counter()
        index = query_graph(graph)
        indexed = time.perf_counter()
        outcomes = {}
        for name in names:
            out = Engine(index, compiled, budget, 'strict').execute(compiled[name])
            outcomes[name] = {key: out[key] for key in ['complete', 'unknown', 'stats']}
            outcomes[name]['matches'] = [{'bindings': m['bindings'], 'confidence': m.get('confidence')}
                                        for m in out['matches']]
        target = parent.id+'#'+case['variant'] if case.get('variant') else parent.id
        outcome = outcomes[target]
        actual = bool(outcome['matches'])
        verdict = ('invalid' if graph.diagnostics else 'incomplete' if not outcome['complete'] else
                   'TP' if actual and case['expected'] else 'FP' if actual else
                   'FN' if case['expected'] else 'TN')
        results.append({'id': case['id'], 'rule': parent.id, 'target': target, 'kind': case['kind'],
                        'language': case['language'], 'expected': case['expected'], 'actual': actual,
                        'verdict': verdict, 'why': case['why'], 'diagnostics': graph.diagnostics,
                        'source_sha256': hashlib.sha256(case['source'].encode()).hexdigest(),
                        'timing_seconds': {'lower_and_link': lowered-case_started,
                                           'query_projection': indexed-lowered,
                                           'queries': time.perf_counter()-indexed,
                                           'total': time.perf_counter()-case_started},
                        'outcomes': outcomes})
    root = Path(lower_source.__code__.co_filename).parent
    return {'schema': 'ken-adversarial-catalog-audit/1', 'ir_version': IR_VERSION,
            'base_commit': subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(),
            'python': sys.version, 'platform': sys.platform,
            'engine_sha256': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted(root.rglob('*')) if p.suffix in {'.py','.toml'}},
            'budget': asdict(budget), 'registry_seconds': registry_seconds,
            'elapsed_seconds': time.perf_counter()-started,
            'counts': dict(Counter(r['verdict'] for r in results)), 'results': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = audit(json.loads(args.cases.read_text()))
    report['cases_sha256'] = hashlib.sha256(args.cases.read_bytes()).hexdigest()
    report['runner_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report['counts'], sort_keys=True), flush=True)
    for result in report['results']:
        if result['verdict'] in {'FP','FN','invalid','incomplete'}:
            print(result['verdict'], result['id'], result['target'], flush=True)


if __name__ == '__main__':
    main()
