"""Reproduce bounded reachability cost on a small, highly convergent graph."""
import argparse
import hashlib
import json
import platform
import statistics
from pathlib import Path

from ken.structural.kenql import Engine, parse
from ken.structural.model import FactIndex, IR
from ken.structural.query import QueryBudget


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=10)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error('--samples must be positive')
    graph = IR('', '')
    previous = ['root']
    for depth in range(18):
        current = [f'{depth}:a', f'{depth}:b']
        for source in previous:
            for target in current:
                graph.add(source, 'VALUE_FLOW', target)
        previous = current
    text = 'query convergence { path "root" VALUE_FLOW{18,18} $end as $path; emit $end, $path; }'
    query, index = parse(text), FactIndex(graph)
    measurements = []
    for _ in range(args.samples):
        result = Engine(index, {}, QueryBudget(max_states=2000000, max_rows=2000000, timeout_ms=10000)).execute(query)
        assert result['complete']
        assert {m['bindings']['$end'] for m in result['matches']} == set(previous)
        measurements.append(result['stats'])
    from ken.structural import kenql
    report = {'python': platform.python_version(), 'platform': platform.platform(),
              'kenql_sha256': hashlib.sha256(Path(kenql.__file__).read_bytes()).hexdigest(),
              'query': text, 'vertices': 37, 'edges': len(graph.facts),
              'samples': measurements, 'p50_ms': statistics.median(x['elapsed_ms'] for x in measurements),
              'scope': 'Prepared synthetic graph search only; excludes parsing, indexing and repository construction.'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
