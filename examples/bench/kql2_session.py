"""Gate the public prepared KQL2 API, including compilation and JSON delivery.

Run against the frozen 500-file corpus from the performance study. Source
preparation occurs before query timers; responses are never cached.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import statistics
import sys
import time
from pathlib import Path

from ken.kql2 import QuerySession
from ken.kql2 import session as session_module
from ken.kql2.compilation import implementation_fingerprint

HEADER = 'language "kql/2"; module latency_case; '
CASES = {
    'lookup': (
        'query q {class $c {name:"ArtifactCache";} select $c.name,$c.path;}',
        [['ArtifactCache', 'src/ken/kql2/cache.py']],
    ),
    'missing': (
        'query q {class $c {name:"AbsentCacheForLatency";} select $c.name;}', [],
    ),
    'method': (
        'query q {class $c {name:"ArtifactCache"; method $m {name:"stats";}} select $c.name,$m.name;}',
        [['ArtifactCache', 'stats']],
    ),
    'parameter': (
        'query q {class $c {name:"ArtifactCache"; method $m {name:"get_or_compute"; param $p {position:0;}}} select $c.name,$p.name;}',
        [['ArtifactCache', 'key']],
    ),
    'ordering': (
        'query q {class $c {name:"ArtifactCache"; method $m {}} select $m.name; order by $m.name asc;}',
        [['__init__'], ['_evict'], ['clear'], ['configure'], ['get_or_compute'], ['stats']],
    ),
    'existence': (
        'query q {class $c {name:"ArtifactCache";} where exists(Callable $m | owns($c,$m) and $m.name == "stats"); select $c.name;}',
        [['ArtifactCache']],
    ),
    'nested': (
        'predicate Named(TypeDecl $c) {$c.name == "ArtifactCache"} '
        'predicate Inner(TypeDecl $c) {Named($c)} '
        'predicate Outer(TypeDecl $c) {Inner($c)} '
        'query q {class $c {name:"ArtifactCache";} where Outer($c); select $c.name,$c.path;}',
        [['ArtifactCache', 'src/ken/kql2/cache.py']],
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=30)
    parser.add_argument('--cache-mb', type=float, default=3000)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('repeats must be positive')
    root = args.root.resolve()
    engine_root = Path(session_module.__file__).resolve().parents[2]
    implementation_files = (
        'ken/kql2/session.py', 'ken/kql2/reporting.py', 'ken/kql2/compilation.py',
        'ken/kql2/catalog.py', 'ken/kql2/service.py', 'ken/kql2/request.py',
        'ken/kql2/__init__.py', 'ken/structural_store/store.py',
        'ken/structural_store/leases.py',
    )
    engine_sources = {path:hashlib.sha256((engine_root / path).read_bytes()).hexdigest()
                      for path in implementation_files}
    frozen = json.loads(args.manifest.read_text())['files']
    if len(frozen) != 500 or len({f['path'] for f in frozen}) != 500:
        parser.error('the frozen corpus must contain 500 unique files')
    for file in frozen:
        data = (root / file['path']).read_bytes()
        if len(data) != file['bytes'] or hashlib.sha256(data).hexdigest() != file['sha256']:
            parser.error('corpus differs from its frozen manifest: ' + file['path'])
    records = []
    started = time.perf_counter()
    with QuerySession(root, cache_mb=args.cache_mb, source_paths=[f['path'] for f in frozen]) as session:
        preparation_ms = (time.perf_counter() - started) * 1000
        for name, (body, expected) in CASES.items():
            for mode in ('novel', 'reused_plan'):
                for repeat in range(args.repeats):
                    module = f'latency_{name}_{mode}_{repeat}' if mode == 'novel' else f'latency_{name}_shared'
                    source = HEADER.replace('latency_case', module) + body
                    query_start = time.perf_counter()
                    encoded = session.search_json(source)
                    wall_ms = (time.perf_counter() - query_start) * 1000
                    result = json.loads(encoded)
                    analysis = result['analysis']
                    correct = (result['complete'] and result['coverage_complete']
                               and result['rows'] == expected and result['unknown_candidates'] == 0
                               and not result['results_truncated'] and result['reason'] is None)
                    passed = (correct and math.isfinite(wall_ms) and wall_ms <= 10
                              and analysis['parsed_units'] == 0 and analysis['reused_units'] == 500
                              and analysis['result_cache'] == 'disabled' and analysis['build_ms'] == 0
                              and (mode != 'novel' or analysis['compilation_cache']['status'] == 'miss'))
                    records.append({'case':name, 'mode':mode, 'repeat':repeat, 'wall_ms':wall_ms,
                                    'correct':correct, 'passed':passed,
                                    'rows':len(result['rows']), 'compilation_cache':analysis['compilation_cache']['status'],
                                    'semantic_sha256':hashlib.sha256(json.dumps(result['rows'],sort_keys=True).encode()).hexdigest()})
    summary = {}
    for name in CASES:
        for mode in ('novel', 'reused_plan'):
            selected = [r for r in records if r['case']==name and r['mode']==mode]
            values = [r['wall_ms'] for r in selected]
            summary[name+'/'+mode] = {'samples':len(values), 'median_ms':statistics.median(values),
                                    'max_ms':max(values), 'passed':all(r['passed'] for r in selected)}
    if any(hashlib.sha256((engine_root / path).read_bytes()).hexdigest() != expected
           for path,expected in engine_sources.items()):
        parser.error('implementation changed during measurement')
    report = {'passed':all(r['passed'] for r in records), 'threshold_ms':10,
              'files':frozen,'cache_mb':args.cache_mb,'preparation_ms':preparation_ms,
              'environment':{'python':sys.version,'platform':platform.platform()},
              'implementation':implementation_fingerprint(),'engine_sources_sha256':engine_sources,
              'summary':summary,'records':records,
              'cases':{name:{'source':HEADER+body,'expected_rows':expected} for name,(body,expected) in CASES.items()},
              'limits':['Frozen extracted Python corpus, not every 500-file repository.',
                        'Prepared source queries; this gate does not certify all graph/BODY/recursive queries.',
                        'Wall timer includes public API, compilation, execution and delivered JSON; client JSON parsing is excluded.',
                        'Index preparation and source updates occur outside the query timer.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':report['passed'],'queries':len(records),'summary':summary},indent=2))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
