"""Explain why one rule matches or misses one source, without executing the source.

Usage:
  .venv/bin/python examples/bench/diagnose_pattern_case.py \
      --rule gof.mediator --language ruby --file sample.rb [--dump]

Prints the rule outcome per entry, the variant that matched, and (with --dump)
the graph facts the published queries read. This is a diagnosis aid: it never
turns a missing fact into a negative result.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from ken.structural.frontend import lower_source
from ken.structural.query import QueryBudget
from ken.structural.rules import builtin_rules, execute_rules
from ken.structural.semantic import link_project

DUMP_RELATIONS = ('HAS_METHOD', 'HAS_FIELD', 'HAS_PARAMETER', 'CALLS', 'HAS_CALL', 'RECEIVER',
                  'SUBTYPE_OF', 'IMPLEMENTS', 'EXTENDS', 'INSTANCE_OF', 'RETURNS_NEW',
                  'RETURNS_VALUE', 'WRITES', 'READS', 'DELEGATES_TO', 'CONDITIONAL_DELEGATION')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rule', required=True)
    parser.add_argument('--language', required=True)
    parser.add_argument('--file', type=Path, required=True)
    parser.add_argument('--dump', action='store_true')
    parser.add_argument('--max-facts', type=int, default=60)
    args = parser.parse_args()

    unit = lower_source(args.file.read_bytes(), args.language, args.file.name)
    graph = link_project([unit])
    registry = builtin_rules()
    rules = [r for r in registry if r.id == args.rule or 'gof.' + r.id == args.rule]
    if not rules:
        raise SystemExit(f'unknown rule: {args.rule}')
    result = execute_rules(graph, rules, QueryBudget(timeout_ms=5000, max_states=500000), registry=registry)
    print(f'diagnostics={graph.diagnostics} entities={len(graph.entities)} facts={len(graph.facts)}')
    for rule_id, outcome in result['outcomes'].items():
        print(f"  OUTCOME {rule_id} complete={outcome['complete']} unknown={outcome['unknown']} "
              f"matches={len([m for m in result['matches'] if m['id'] == rule_id])}")
    for hit in result['matches']:
        roles = {k: graph.entities[v].name for k, v in hit['bindings'].items() if v in graph.entities}
        print(f"  MATCH {hit['id']} variant={hit.get('variant')} status={hit['status']} roles={roles}")

    if args.dump:
        print('\nrelations:')
        print(' ', dict(Counter(f.relation for f in graph.facts if not f.relation.startswith('_'))))
        for relation in DUMP_RELATIONS:
            rows = [f for f in graph.facts if f.relation == relation][:args.max_facts]
            if not rows:
                continue
            print(f'\n{relation} ({len([f for f in graph.facts if f.relation == relation])}):')
            for fact in rows:
                subject = graph.entities[fact.subject].name if fact.subject in graph.entities else fact.subject
                obj = graph.entities[fact.object].name if fact.object in graph.entities else fact.object
                extra = {k: v for k, v in (fact.attrs or {}).items()
                         if k in {'execution', 'kind', 'name', 'type', 'receiver', 'generator',
                                  'static', 'constructor', 'position'}}
                entity_kinds = ''
                if fact.relation.startswith('HAS_') and fact.object in graph.entities:
                    entity_kinds = f"[{graph.entities[fact.object].kind}]"
                print(f'  {subject} -> {obj}{entity_kinds} {extra}')


if __name__ == '__main__':
    main()
