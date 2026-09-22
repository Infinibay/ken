"""Dump the graph-profile facts one Ruby fixture publishes. Diagnosis aid only."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))

from ken.structural.frontend import lower_source  # noqa: E402
from ken.structural.semantic import link_project  # noqa: E402
from ken.structural.query_view import query_graph  # noqa: E402
from structural.gof_sources_ruby import RUBY  # noqa: E402

WANTED = ('HAS_FIELD', 'HAS_METHOD', 'HAS_PARAMETER', 'HAS_CALL', 'RECEIVER', 'CALLEE_NAME',
          'DELEGATES_TO', 'WRITES', 'READS', 'ASSIGNMENT_TARGET', 'RETURNS_NEW', 'RETURNS_VALUE',
          'RESULT', 'INSTANCE_OF', 'ITERATED_CALL', 'ITERATES_CALLS', 'CONDITIONAL_DELEGATION',
          'SUBTYPE_OF', 'TYPE', 'OVERRIDES', 'INSERTED_VALUE', 'INSERTS_INTO', 'STORED_VALUE',
          'FINAL_MEMBER_INPUT', 'ALLOCATES_TYPE', 'RETURNS_CALL', 'ADVANCES_ITERATOR', 'YIELD',
          'PASSES_SELF_TO', 'INSTANCE_RECEIVER')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture')
    parser.add_argument('--all', action='store_true')
    args = parser.parse_args()
    index = query_graph(link_project([lower_source(RUBY[args.fixture], 'ruby', args.fixture + '.rb')]))
    graph = index.ir
    for fact in graph.facts:
        if not args.all and fact.relation not in WANTED:
            continue
        subject = graph.entities[fact.subject].name if fact.subject in graph.entities else fact.subject
        obj = graph.entities[fact.object].name if fact.object in graph.entities else fact.object
        print(f'{fact.relation:22s} {subject:20s} -> {obj:20s} {fact.attrs}')


if __name__ == '__main__':
    main()
