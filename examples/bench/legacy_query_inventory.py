"""Which published queries still speak the legacy graph profile, and what they need.

Usage::

    .venv/bin/python examples/bench/legacy_query_inventory.py
    .venv/bin/python examples/bench/legacy_query_inventory.py --pattern builder --relations

Every saved query is KQL 2 text. A *migrated* query names its subject with nested
selectors (``type``/``method``/``field``/``call``) and states behaviour with public
predicates (``possible_call``, ``returns_new``, ...) or BODY effects. A legacy query
instead spells out ``edge RELATION(...)`` joins and ``walk`` traversals, which is the
IR's own vocabulary: it leaks the graph schema into the catalogue.

This inventory is the work list. For each legacy entry it reports the raw relations it
reads, split into four buckets:

* ``selector``  the relation is published by a nested selector (``HAS_METHOD`` ...).
* ``predicate`` a public predicate already states it (``possible_call`` ...).
* ``body``      BODY can state it as an effect (assignment, retained call, construct).
* ``missing``   no KQL 2 form exists yet: the language needs a design.
"""
from __future__ import annotations

import argparse
import collections
import re
from pathlib import Path

from ken.structural.rules import builtin_rules

LEGACY = re.compile(r'\b(?:edge|walk)\s+([A-Z_]+)\s*\(')

SELECTOR = {
    'ENTITY', 'CLASS', 'INTERFACE', 'HAS_METHOD', 'HAS_FIELD', 'HAS_PARAMETER',
    'HAS_OPERATION', 'TYPE', 'DECLARES', 'OPERATION', 'OWNED_BY',
}
PREDICATE = {
    'POSSIBLE_CALL', 'CALLS', 'OVERRIDES', 'SUBTYPE_OF', 'IMPLEMENTS', 'EXTENDS',
    'RETURNS_NEW', 'RETURNS_SELF', 'RETURNS_TYPE', 'RETURNS', 'READS', 'WRITES',
    'WRITES_ELEMENT', 'ITERATES_CALLS', 'DELEGATES_TO', 'FORWARDS_SLOT',
    'NOMINAL_ROOT', 'FINAL_MEMBER_INPUT', 'RETURNS_VALUE', 'MEMBER_FLOW_STATUS',
    'BINDING_FLOW_STATUS',
}
BODY = {
    'HAS_CALL', 'RECEIVER', 'CALLEE_VALUE', 'ARGUMENT', 'VALUE', 'LOADED_FROM',
    'ASSIGNMENT_TARGET', 'ASSIGNED_FROM', 'STORES_VALUE', 'ALLOCATES_TYPE',
    'RETURNS_VALUE', 'INSTANCE_OF', 'CONSTRUCTS',
}


def entries():
    for rule in builtin_rules():
        if not rule.source:
            continue
        group = 'modern' if 'modern_patterns' in str(rule.source) else 'gof'
        for item in (rule.to_dict(), *rule.variants, *rule.operations):
            if item.get('query'):
                yield group, rule.id, item.get('id', 'default'), item['query']


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pattern', help='only this rule id')
    parser.add_argument('--relations', action='store_true', help='list every relation per entry')
    parser.add_argument('--missing', action='store_true', help='only entries with a missing primitive')
    arguments = parser.parse_args()

    total = migrated = 0
    pending: dict[tuple[str, str], list[tuple[str, set[str]]]] = collections.defaultdict(list)
    frequency: collections.Counter = collections.Counter()
    buckets: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)

    for group, rule, entry, query in entries():
        if arguments.pattern and rule != arguments.pattern:
            continue
        total += 1
        relations = set(LEGACY.findall(query))
        if not relations:
            migrated += 1
            continue
        frequency.update(relations)
        for relation in relations:
            bucket = ('selector' if relation in SELECTOR else
                      'predicate' if relation in PREDICATE else
                      'body' if relation in BODY else 'missing')
            buckets[group][bucket] += 1
        pending[(group, rule)].append((entry, relations))

    print(f'entries {total}  native KQL 2 {migrated}  legacy {total - migrated}')
    print()
    for group in ('gof', 'modern'):
        counts = buckets[group]
        if counts:
            print(f'{group}: ' + '  '.join(f'{k} {v}' for k, v in sorted(counts.items())))
    print()
    print('pending by pattern (entries | most frequent relations):')
    for (group, rule), items in sorted(pending.items(), key=lambda kv: -len(kv[1])):
        common = collections.Counter(r for _, relations in items for r in relations)
        summary = ', '.join(f'{name}' for name, _ in common.most_common(8))
        print(f'  {group:6s} {rule:26s} {len(items):3d}  {summary}')
        if arguments.relations:
            for entry, relations in items:
                print(f'          {entry:22s} {", ".join(sorted(relations))}')

    if arguments.missing:
        print()
        print('entries whose relations have no KQL 2 form yet:')
        for (group, rule), items in sorted(pending.items()):
            for entry, relations in items:
                missing = sorted(r for r in relations
                                 if r not in SELECTOR and r not in PREDICATE and r not in BODY)
                if missing:
                    print(f'  {rule}#{entry:24s} {", ".join(missing)}')


if __name__ == '__main__':
    main()
