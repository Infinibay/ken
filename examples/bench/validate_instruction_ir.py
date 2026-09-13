"""Export audit over {language: {sample_name: source_text}} JSON fixtures.

Only parses text; it never executes the supplied programs. Run separately with
each installed Ken version against the same fixture file for comparisons.
"""
import argparse
import collections
import hashlib
import json
import statistics
import time
from pathlib import Path

from ken.structural import lower_source, link_project, lower_instructions

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--fixtures', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
fixtures = json.loads(args.fixtures.read_text())
rows = []
for language, patterns in fixtures.items():
    for name, source in patterns.items():
        graph = link_project([lower_source(source, language, name)])
        measurements = []
        for n in range(12):
            start = time.perf_counter_ns()
            p = lower_instructions(graph)
            p.verify()
            elapsed = (time.perf_counter_ns() - start) / 1e6
            if n >= 2:
                measurements.append(elapsed)
        regions = [f.body for f in p.functions]
        codes, native = collections.Counter(), collections.Counter()
        for r in regions:
            for i in r.instructions:
                codes[i.opcode] += 1
                if i.opcode == 'native':
                    native[i.attrs['native_kind']] += 1
                regions.extend(i.regions)
        rows.append(dict(pattern=name, language=language,
            source_sha256=hashlib.sha256(source.encode()).hexdigest(), functions=len(p.functions),
            partial_functions=sum(f.status == 'partial' for f in p.functions),
            opcodes=codes, native=native, export_verify_median_ms=statistics.median(measurements)))
args.output.write_text(json.dumps({'source_version': p.source_version,
    'method': '10 export+verify samples after 2 warmups, prepared source graphs; does not measure query precision or end-to-end scan performance',
    'results': rows}, indent=2) + '\n')
