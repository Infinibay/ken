"""Measure automatic CLI and actual MCP stdio delivery on the frozen corpus.

Process imports, MCP initialization/schema discovery and initial source indexing
are preparation. Each measured request includes compilation, freshness checks,
execution, local transport and the frontend's complete JSON delivery.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from importlib.metadata import version
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from examples.bench.kql2_session import CASES, HEADER
from ken.kql2 import automatic
from ken.kql2.compilation import implementation_fingerprint


def cli_request(route: str, root: Path, query_file: Path, cache_mb: float,
                saved_module: str | None = None) -> dict:
    command_started = time.perf_counter()
    child = subprocess.Popen([sys.executable, '-m', 'examples.bench.kql2_cli_request',
        route, str(root), str(query_file), str(cache_mb), *([saved_module] if saved_module else [])], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True)
    assert child.stdout is not None
    line = child.stdout.readline()
    if not line:
        _, errors = child.communicate(timeout=30)
        raise RuntimeError('CLI measurement child failed: ' + errors)
    envelope = json.loads(line)
    envelope['command_started_at'] = command_started
    envelope['process'] = child
    return envelope


async def measure(args: argparse.Namespace) -> dict:
    root = args.root.resolve()
    frozen = json.loads(args.manifest.read_text())['files']
    if len(frozen) != 500 or len({f['path'] for f in frozen}) != 500:
        raise ValueError('the frozen corpus must contain exactly 500 unique files')
    for file in frozen:
        data = (root / file['path']).read_bytes()
        if len(data) != file['bytes'] or hashlib.sha256(data).hexdigest() != file['sha256']:
            raise ValueError('corpus differs from manifest: ' + file['path'])
    source_root = Path(automatic.__file__).resolve().parents[2]
    engine_paths = list((source_root / 'ken/kql2').glob('*.py')) + [
        source_root / path for path in (
            'ken/mcp/server.py', 'ken/cli.py', 'ken/daemon/watcher.py',
            'ken/gitignore_filter.py', 'ken/checks/report.py', 'ken/structural_store/store.py',
            'ken/structural_store/leases.py',
        )
    ]
    engine_sources = {str(p.relative_to(source_root)):hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in engine_paths}
    benchmark_paths = [Path(__file__), Path(__file__).with_name('kql2_cli_request.py')]
    benchmark_sources = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in benchmark_paths}
    # Standalone KQL2 needs no metadata; the ordinary MCP entrypoint does.
    metadata = root / '.ken/meta.json'
    created_metadata = not metadata.exists()
    metadata.parent.mkdir(parents=True, exist_ok=True)
    if created_metadata:
        metadata.write_text('{}\n')
    records = []
    startup_samples = []
    cases = dict(CASES)
    registry_libraries = {}
    if args.saved_modules:
        from ken.kql2.registry import ModuleRegistry

        registry = ModuleRegistry(root)
        registry_libraries = {
            'benchmark.registry.types': 'language "kql/2"; module benchmark.registry.types; '
                'pattern Cache(in TypeDecl $c) {class $c {name:"ArtifactCache"; method $m {name:"stats";}}}',
            'benchmark.registry.conventions': 'language "kql/2"; module benchmark.registry.conventions; '
                'import benchmark.registry.types; pattern Match(in TypeDecl $c) {use benchmark.registry.types.Cache(c:$c);}',
        }
        for source in registry_libraries.values():
            registry.save(source)
        cases['imported_patterns'] = (
            'import benchmark.registry.conventions; query q {class $c {} '
            'use benchmark.registry.conventions.Match(c:$c); select $c.name,$c.path;}',
            CASES['lookup'][1],
        )
        for route in ('kql2_cli', 'tools_cli', 'mcp_stdio'):
            for name, (body, _) in cases.items():
                for mode in ('novel', 'reused_plan'):
                    for repeat in range(args.repeats if mode == 'novel' else 1):
                        suffix = str(repeat) if mode == 'novel' else 'shared'
                        module = f'frontend_{route}_{name}_{mode}_{suffix}'
                        registry.save(HEADER.replace('latency_case', module) + body)
        registry.save('language "kql/2"; module benchmark.registry.warm; query q {select 1;}')
    preparation_started = time.perf_counter()
    if args.saved_modules:
        automatic.search(root, saved_query='benchmark.registry.warm', cache_mb=args.cache_mb)
    else:
        automatic.search(root, HEADER + 'query q {select 1;}', cache_mb=args.cache_mb)
    initial_preparation_ms = (time.perf_counter() - preparation_started) * 1000
    parameters = StdioServerParameters(command=sys.executable,
        args=['-m', 'ken', 'mcp', str(root)], cwd=root,
        env={'PYTHONPATH':os.environ['PYTHONPATH']} if 'PYTHONPATH' in os.environ else None)
    try:
        with tempfile.TemporaryDirectory(prefix='ken-query-input-') as directory:
            query_file = Path(directory) / 'query.kql'
            query_file.write_text(HEADER.replace('latency_case', 'cli_startup') + CASES['lookup'][0])
            for _ in range(2):
                began = time.perf_counter()
                child = subprocess.run([sys.executable, '-m', 'ken.kql2', str(query_file),
                    '--root', str(root), '--cache-mb', str(args.cache_mb), '--timeout-ms', '10'],
                    capture_output=True, text=True, timeout=30)
                command_ms = (time.perf_counter() - began) * 1000
                if child.returncode:
                    raise RuntimeError('new CLI process failed: ' + child.stderr)
                result = json.loads(child.stdout)
                if not result['complete'] or result['rows'] != CASES['lookup'][1]:
                    raise ValueError('new CLI process returned an incorrect response')
                startup_samples.append({'command_ms':command_ms,
                    'automatic_client_ms':result['analysis']['total_ms'],
                    'outside_client_ms':command_ms - result['analysis']['total_ms'],
                    'session_pid':result['analysis']['session_pid']})
            mcp_started = time.perf_counter()
            async with stdio_client(parameters) as streams:
                async with ClientSession(*streams) as client:
                    await client.initialize()
                    await client.list_tools()
                    mcp_startup_ms = (time.perf_counter() - mcp_started) * 1000
                    for route in ('kql2_cli', 'tools_cli', 'mcp_stdio'):
                        for name, (body, expected) in cases.items():
                            for mode in ('novel', 'reused_plan'):
                                for repeat in range(args.repeats):
                                    suffix = str(repeat) if mode == 'novel' else 'shared'
                                    module = f'frontend_{route}_{name}_{mode}_{suffix}'
                                    source = HEADER.replace('latency_case', module) + body
                                    query_file.write_text(source)
                                    cli_startup_ms = 0.0
                                    started = time.perf_counter()
                                    if route != 'mcp_stdio':
                                        envelope = await asyncio.to_thread(cli_request,
                                            route, root, query_file, args.cache_mb,
                                            module if args.saved_modules else None)
                                        delivered = time.perf_counter()
                                        _, errors = await asyncio.to_thread(envelope['process'].communicate, timeout=30)
                                        if envelope['process'].returncode:
                                            raise RuntimeError('CLI measurement child failed: ' + errors)
                                        cli_startup_ms = (envelope['started_at'] - envelope['command_started_at']) * 1000
                                        started = envelope['started_at']
                                        wall_ms = (delivered - started) * 1000
                                        status = envelope['status']
                                        result = json.loads(envelope['output'])
                                    else:
                                        response = await client.call_tool('ken_find', {
                                            'scope':'structure', 'query_language':'kql/2',
                                            **({'saved_query':module} if args.saved_modules else {'query':source}),
                                            'cache_mb':args.cache_mb,
                                            'timeout_ms':10, 'full':True,
                                        })
                                        wall_ms = (time.perf_counter() - started) * 1000
                                        status = 1 if response.is_error else 0
                                        result = json.loads(response.content[0].text)
                                    analysis = result['analysis']
                                    correct = (status == 0 and result['complete']
                                        and result['coverage_complete'] and result['rows'] == expected
                                        and result['unknown_candidates'] == 0
                                        and not result['results_truncated'] and result['reason'] is None)
                                    ready = (analysis['parsed_units'] == 0
                                        and analysis['reused_units'] == 500
                                        and analysis['build_ms'] == 0
                                        and analysis['preparation_ms'] == 0
                                        and analysis['index_wait_ms'] == 0
                                        and analysis['startup_ms'] == 0
                                        and analysis['result_cache'] == 'disabled')
                                    record = {'route':route, 'case':name, 'mode':mode,
                                        'repeat':repeat, 'wall_ms':wall_ms, 'correct':correct,
                                        'started_at':started, 'finished_at':started + wall_ms / 1000,
                                        'cli_startup_ms':cli_startup_ms,
                                        'ready':ready, 'passed':correct and ready and math.isfinite(wall_ms) and wall_ms <= 10,
                                        'complete':result['complete'], 'reason':result['reason'],
                                        'analysis':analysis,
                                        'semantic_sha256':hashlib.sha256(json.dumps(result['rows'], sort_keys=True).encode()).hexdigest()}
                                    # Measurement receipts must not accumulate in the timed
                                    # SDK client's heap and induce artificial GC pressure.
                                    with (Path(directory) / 'records.jsonl').open('a') as receipt:
                                        receipt.write(json.dumps(record) + '\n')
                    records = [json.loads(line) for line in (Path(directory) / 'records.jsonl').read_text().splitlines()]
    finally:
        automatic.shutdown(root)
        if created_metadata:
            metadata.unlink()
    for path, expected in engine_sources.items():
        if hashlib.sha256((source_root / path).read_bytes()).hexdigest() != expected:
            raise ValueError('implementation changed during measurement: ' + path)
    for path in benchmark_paths:
        if hashlib.sha256(path.read_bytes()).hexdigest() != benchmark_sources[path.name]:
            raise ValueError('benchmark changed during measurement: ' + path.name)
    summary = {}
    for route in ('kql2_cli', 'tools_cli', 'mcp_stdio'):
        selected = [r for r in records if r['route'] == route]
        times = [r['wall_ms'] for r in selected]
        summary[route] = {'queries':len(times), 'median_ms':statistics.median(times),
            'max_ms':max(times), 'exceedances':sum(t > 10 for t in times),
            'correct':all(r['correct'] for r in selected),
            'ready':all(r['ready'] for r in selected), 'passed':all(r['passed'] for r in selected)}
    return {'passed':all(r['passed'] for r in records), 'threshold_ms':10,
        'files':frozen, 'cache_mb':args.cache_mb, 'summary':summary, 'records':records,
        'initial_preparation_ms':initial_preparation_ms, 'mcp_startup_ms':mcp_startup_ms,
        'new_cli_processes':startup_samples,
        'benchmark_sha256':benchmark_sources['kql2_frontends.py'],
        'cli_probe_sha256':benchmark_sources['kql2_cli_request.py'],
        'manifest_sha256':hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        'environment':{'python':sys.version, 'platform':platform.platform(), 'mcp_sdk':version('mcp')},
        'implementation':implementation_fingerprint(), 'engine_sources_sha256':engine_sources,
        'saved_modules':args.saved_modules, 'registry_libraries':registry_libraries,
        'cases':{name:{'source':HEADER+body, 'expected_rows':expected} for name,(body,expected) in cases.items()},
        'limits':['Frozen Python corpus; does not certify every repository or operator.',
                  'Process imports, MCP initialize/list_tools and initial indexing measured separately.',
                  'Each CLI timer starts in its actual handler in a new process and ends after stdout pipe delivery; startup is separate.',
                  'MCP timer surrounds actual SDK call_tool over stdio, including local query RPC and client validation.',
                  'No concurrent load during acceptance; source updates and waits are separately reported.']}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=30)
    parser.add_argument('--cache-mb', type=float, default=3000)
    parser.add_argument('--saved-modules', action='store_true',
                        help='Measure named registry queries and a transitive imported-pattern case')
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('repeats must be positive')
    report = asyncio.run(measure(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed':report['passed'], 'summary':report['summary']}, indent=2))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
