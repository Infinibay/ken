"""Bounded source-only structural search benchmark; target code is never executed.

Example:
 python examples/bench/validate_search_pipeline.py --case retry /tmp/ken-pattern-corpus/java-patterns retry/src/main/java/ --repeats 5 --output /tmp/pipeline.json

Selected tracked sources are copied into a disposable directory so cold/warm
cache measurements never write into the upstream checkout. Cold means empty IR
SQLite cache, not cold operating-system pages or a fresh Python interpreter.
"""
from __future__ import annotations

import argparse
from collections import Counter
import cProfile
import gc
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import platform
import pstats
import resource
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

from ken.structural import lower_instructions
from ken.structural.cache import DEFAULT_CACHE_MB
from ken.structural.frontend import LANGUAGES, lower_source
from ken.structural.kenql import Engine, parse, query_graph
from ken.structural.model import FactIndex, IR_VERSION
from ken.structural.query import QueryBudget
from ken.structural.rules import builtin_rules, execute_rules, named_rule, query_registry, select_rules
from ken.structural.semantic import link_project
from ken.structural.service import _parser_versions, build_project, search


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def engine_manifest():
    root = Path(lower_source.__code__.co_filename).parent
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.suffix in {'.py', '.toml'}}


def percentiles(values):
    ordered = sorted(values)
    return {'samples_ms': values, 'p50_ms': ordered[math.ceil(len(ordered)*.50)-1],
            'p95_ms': ordered[math.ceil(len(ordered)*.95)-1], 'min_ms': ordered[0], 'max_ms': ordered[-1]}


def timed(samples, phase, fn):
    started = time.perf_counter_ns()
    result = fn()
    samples.setdefault(phase, []).append(round((time.perf_counter_ns()-started)/1_000_000, 3))
    return result


def fingerprint(matches):
    return digest(sorted((m['id'], sorted(m['bindings'].items())) for m in matches))


def profile(fn):
    profiler = cProfile.Profile()
    profiler.runcall(fn)
    stats = pstats.Stats(profiler)
    rows = []
    for (file, line, name), (primitive, calls, own, cumulative, _) in stats.stats.items():
        rows.append({'file': file, 'line': line, 'function': name, 'calls': calls,
                     'primitive_calls': primitive, 'self_ms': round(own*1000, 3),
                     'cumulative_ms': round(cumulative*1000, 3)})
    return sorted(rows, key=lambda r: r['cumulative_ms'], reverse=True)[:25]


def validate(name, root, prefix, repeats, max_files, budget, diagnostics=True):
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    eligible = sorted(p for p in tracked if p and p.startswith(prefix) and Path(p).suffix.lower() in LANGUAGES
                      and not (root/p).is_symlink() and (root/p).is_file())
    paths = eligible[:max_files]
    if not paths:
        raise ValueError(f'{name}: no selected source files')
    sources = [(p, LANGUAGES[Path(p).suffix.lower()], (root/p).read_bytes()) for p in paths]
    registry = builtin_rules()
    selected = select_rules(registry, collections=['gof', 'modern'])
    compiled = query_registry(registry)
    roots = {r.id: parse(r.query) for r in selected}
    samples, runs = {}, []
    # Grammar initialization is excluded consistently; cold/warm below refers
    # only to disposable disk IR caches, and bytes are already in OS page cache.
    for language in {language for _, language, _ in sources}:
        lower_source(b'', language, 'warmup')
    with tempfile.TemporaryDirectory(prefix='ken-search-pipeline-') as directory:
        stage = Path(directory)
        for path, _, content in sources:
            destination = stage/path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)

        def graph_only():
            return link_project([lower_source(content, language, path) for path, language, content in sources])

        def prepared(index):
            return {rid: Engine(index, compiled, budget, 'strict').execute(query) for rid, query in roots.items()}

        for iteration in range(repeats):
            print(name, 'sample', iteration+1, '/', repeats, flush=True)
            units = timed(samples, 'parse_lower', lambda: [lower_source(content, language, path) for path, language, content in sources])
            graph = timed(samples, 'semantic_link', lambda: link_project(units))
            index = timed(samples, 'source_index', lambda: FactIndex(graph))
            projected = timed(samples, 'query_projection_index', lambda: query_graph(graph))
            program = timed(samples, 'instruction_export', lambda: lower_instructions(graph))
            timed(samples, 'instruction_verify', program.verify)
            raw = timed(samples, 'prepared_engine_rules', lambda: prepared(projected))
            batch = timed(samples, 'public_execute_rules', lambda: execute_rules(index, selected, budget, registry=registry))
            cache = stage/'.ken'/'structural-cache.sqlite'
            if cache.exists():
                cache.unlink()
            cold = timed(samples, 'cold_public_search', lambda: search(stage, collections=['gof','modern'], cache_mb=DEFAULT_CACHE_MB, budget=budget))
            warm = timed(samples, 'warm_public_search', lambda: search(stage, collections=['gof','modern'], cache_mb=DEFAULT_CACHE_MB, budget=budget))
            _, warm_analysis = timed(samples, 'warm_build_project_only', lambda: build_project(stage, cache_mb=DEFAULT_CACHE_MB))
            signatures = {key: fingerprint(result['matches']) for key, result in [('batch', batch), ('cold', cold), ('warm', warm)]}
            raw_matches = [{**match, 'id': rid} for rid, outcome in raw.items() for match in outcome['matches']]
            signatures['prepared'] = fingerprint(raw_matches)
            runs.append({'fingerprints': signatures, 'equivalent_matches': len(set(signatures.values())) == 1,
                         'batch_complete': batch['complete'], 'cold_complete': cold['complete'], 'warm_complete': warm['complete'],
                         'outcomes': batch['outcomes'], 'matches_by_rule': dict(sorted(Counter(m['id'] for m in batch['matches']).items())),
                         'cold_analysis': cold['analysis'], 'warm_analysis': warm['analysis'], 'warm_build_analysis': warm_analysis})
        profile_results = {
            'parse_link': profile(graph_only),
            'public_execute_rules': profile(lambda: execute_rules(index, selected, budget, registry=registry)),
            'warm_public_search': profile(lambda: search(stage, collections=['gof','modern'], cache_mb=DEFAULT_CACHE_MB, budget=budget)),
        } if diagnostics else {}
        peak = None
        if diagnostics:
            tracemalloc.start()
            measured_graph = graph_only()
            measured_index = query_graph(measured_graph)
            measured_program = lower_instructions(measured_graph)
            measured_program.verify()
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            del measured_graph, measured_index, measured_program
        source_json_bytes = len(json.dumps(graph.to_dict(), separators=(',', ':')).encode())
        query_json_bytes = len(json.dumps(projected.ir.to_dict(), separators=(',', ':')).encode())
        instructions_json_bytes = len(json.dumps(program.to_dict(), separators=(',', ':')).encode())
        instruction_status = dict(Counter(f.status for f in program.functions))
    return {'name': name, 'root': str(root), 'commit': subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
            'prefix': prefix, 'eligible_files': len(eligible), 'selected_files': len(paths), 'scope_truncated': len(eligible)>len(paths),
            'files': [{'path':p,'language':language,'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()} for p,language,content in sources],
            'source_bytes': sum(len(content) for _,_,content in sources), 'rules': [r.id for r in selected],
            'rule_count': len(selected), 'cache_budget_bytes': DEFAULT_CACHE_MB*1_000_000,
            'sizes': {'entities':len(graph.entities),'operations':len(graph.operations),'source_facts':len(graph.facts),
                      'query_facts':len(projected.ir.facts),'source_json_bytes':source_json_bytes,'query_json_bytes':query_json_bytes,
                      'instructions_json_bytes':instructions_json_bytes,'instruction_functions':len(program.functions),
                      'instruction_status':instruction_status,'python_allocations_peak_build_projection_export_bytes':peak},
            'timings': {key:percentiles(values) for key,values in samples.items()}, 'runs':runs, 'profiles':profile_results}


def all_definitions(name, root, prefix, max_files, budget):
    """One source-only smoke pass, kept separate from root-query percentiles."""
    tracked = subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
    eligible = sorted(p for p in tracked if p and p.startswith(prefix) and Path(p).suffix.lower() in LANGUAGES
                      and not (root/p).is_symlink() and (root/p).is_file())
    paths = eligible[:max_files]
    if not paths:
        raise ValueError(f'{name}: no selected source files')
    sources = [(p,LANGUAGES[Path(p).suffix.lower()],(root/p).read_bytes()) for p in paths]
    graph = link_project([lower_source(content,language,path) for path,language,content in sources])
    registry = builtin_rules()
    selected = []
    for rule in select_rules(registry,collections=['gof','modern']):
        selected.append(rule)
        selected.extend(named_rule(rule.id+'#'+v['id'],registry) for v in rule.variants if v['status']=='ready')
        selected.extend(named_rule(rule.id+'.'+o['id'],registry) for o in rule.operations if o['status']=='ready')
    assert len({r.id for r in selected}) == len(selected)
    index = FactIndex(graph)
    started = time.perf_counter_ns()
    result = execute_rules(index,selected,budget,registry=registry)
    elapsed = (time.perf_counter_ns()-started)/1_000_000
    print(name,'definitions',len(selected),'complete',result['complete'],flush=True)
    return {'name':name,'root':str(root),'prefix':prefix,'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
            'files':[{'path':p,'language':language,'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()} for p,language,content in sources],
            'scope_truncated':len(eligible)>len(paths),'diagnostics':graph.diagnostics,'definitions':[r.id for r in selected],
            'definition_count':len(selected),'elapsed_ms':round(elapsed,3),'complete':result['complete'],
            'matches_by_definition':dict(sorted(Counter(m['id'] for m in result['matches']).items())),
            'outcomes':result['outcomes'],'fingerprint':fingerprint(result['matches']),
            'slowest':sorted([{'id':rid,**outcome} for rid,outcome in result['outcomes'].items()],
                             key=lambda row:row['stats']['elapsed_ms'],reverse=True)[:5]}


def query_index_probe(name, root, prefix, max_files, budget, repeats):
    """Alternating one-pass eager query-index experiment; semantic passes stay lazy."""
    from ken.structural import kenql

    class EagerIndex:
        # Original single-pass implementation; benchmark-local, never installed.
        def __init__(self, ir):
            self.ir = ir
            self.by_relation, self.by_subject, self.by_object = {}, {}, {}
            for fact in ir.facts:
                self.by_relation.setdefault(fact.relation, []).append(fact)
                self.by_subject.setdefault((fact.relation, fact.subject), []).append(fact)
                self.by_object.setdefault((fact.relation, fact.object), []).append(fact)

        def rows(self, relation, subject=None, object=None):
            rows = self.by_relation.get(relation, [])
            if subject is not None:
                rows = self.by_subject.get((relation, subject), [])
            if object is not None:
                other = self.by_object.get((relation, object), [])
                if subject is None or len(other) < len(rows):
                    rows = other
            return rows

    tracked = subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
    eligible = sorted(p for p in tracked if p and p.startswith(prefix) and Path(p).suffix.lower() in LANGUAGES
                      and not (root/p).is_symlink() and (root/p).is_file())
    paths = eligible[:max_files]
    if not paths:
        raise ValueError(f'{name}: no selected source files')
    sources = [(p,LANGUAGES[Path(p).suffix.lower()],(root/p).read_bytes()) for p in paths]
    registry = builtin_rules()
    selected = select_rules(registry,collections=['gof','modern'])
    original_index = kenql.FactIndex
    timings = {'lazy':{},'eager-query-only':{}}
    results, active, gc_start = [], None, {}

    def gc_timing(phase, info):
        generation = info['generation']
        if phase == 'start':
            gc_start[generation] = time.perf_counter_ns()
        elif active is not None:
            active['count'] += 1
            active['generations'][str(generation)] += 1
            active['elapsed_ms'] += (time.perf_counter_ns()-gc_start.get(generation,time.perf_counter_ns()))/1_000_000

    def measured(policy, phase, fn):
        nonlocal active
        active = {'count':0,'generations':{'0':0,'1':0,'2':0},'elapsed_ms':0.0}
        result = timed(timings[policy],phase,fn)
        counts, active = active, None
        counts['elapsed_ms'] = round(counts['elapsed_ms'],3)
        return result, counts

    with tempfile.TemporaryDirectory(prefix='ken-query-index-probe-') as directory:
        stage = Path(directory)
        for path, _, content in sources:
            destination = stage/path
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_bytes(content)
        graph, analysis = build_project(stage,cache_mb=DEFAULT_CACHE_MB)
        index = FactIndex(graph)
        gc.callbacks.append(gc_timing)
        try:
            for iteration in range(repeats):
                order = ['lazy','eager-query-only'] if iteration%2 == 0 else ['eager-query-only','lazy']
                for policy in order:
                    kenql.FactIndex = original_index if policy == 'lazy' else EagerIndex
                    batch, batch_gc = measured(policy,'public_execute_rules',lambda:execute_rules(index,selected,budget,registry=registry))
                    warm, warm_gc = measured(policy,'warm_public_search',lambda:search(stage,collections=['gof','modern'],cache_mb=DEFAULT_CACHE_MB,budget=budget))
                    results.append({'iteration':iteration,'policy':policy,'batch_complete':batch['complete'],'warm_complete':warm['complete'],
                                    'batch_fingerprint':fingerprint(batch['matches']),'warm_fingerprint':fingerprint(warm['matches']),
                                    'batch_gc':batch_gc,'warm_gc':warm_gc,'warm_cache':warm['analysis']['cache']})
                print(name,'paired query-index sample',iteration+1,'/',repeats,flush=True)
        finally:
            kenql.FactIndex = original_index
            gc.callbacks.remove(gc_timing)
    return {'name':name,'root':str(root),'prefix':prefix,'files':[{'path':p,'language':language,'sha256':hashlib.sha256(content).hexdigest()} for p,language,content in sources],
            'scope_truncated':len(eligible)>len(paths),'analysis':analysis,'rules':[r.id for r in selected],
            'method':'Alternate policies in one process; one retained source graph; no export/tracemalloc; GC enabled with timing callbacks; only kenql.FactIndex replaced for eager policy',
            'timings':{policy:{phase:percentiles(values) for phase,values in phases.items()} for policy,phases in timings.items()},'runs':results}


def main():
    global query_graph
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', nargs=3, action='append', required=True, metavar=('NAME','ROOT','PREFIX'))
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--max-files', type=int, default=40)
    parser.add_argument('--no-diagnostics', action='store_true', help='Omit separate cProfile/tracemalloc passes for faster paired timing runs')
    parser.add_argument('--require-stable', action='store_true', help='Fail after saving evidence if engine sources changed during the run')
    parser.add_argument('--all-definitions-only', action='store_true', help='One separate smoke pass of roots, ready variants and operations; no percentiles or cache benchmark')
    parser.add_argument('--eager-query-endpoints', action='store_true', help='Temporary experiment: materialize both endpoint indexes after query projection; does not edit the engine')
    parser.add_argument('--query-index-probe', action='store_true', help='Compare lazy versus original eager constructor only for query views; alternating batch/warm-search samples with GC timings')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1 or args.max_files < 1:
        parser.error('repeats and max-files must be positive')
    if sum([args.all_definitions_only,args.eager_query_endpoints,args.query_index_probe]) > 1:
        parser.error('choose at most one experimental/smoke mode')
    if args.eager_query_endpoints:
        from ken.structural import kenql
        original_query_graph = query_graph

        def eager_query_graph(ir):
            index = original_query_graph(ir)
            index.by_subject
            index.by_object
            return index

        query_graph = kenql.query_graph = eager_query_graph
    budget = QueryBudget(max_matches=1000, max_rows=500000, max_states=100000, timeout_ms=2000)
    initial = engine_manifest()
    report = {'schema':'ken-search-pipeline/1','ir_version':IR_VERSION,'python':sys.version,'platform':platform.platform(),
              'started_utc':datetime.now(timezone.utc).isoformat(),
              'engine_root':str(Path(lower_source.__code__.co_filename).parent),
              'parser_versions':_parser_versions(),'budget_per_query':asdict(budget),'engine_sha256':initial,
              'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'method':{'percentiles':'nearest rank; p95 is max for five samples', 'precision':'not evaluated',
                        'cold':'empty disposable SQLite IR cache; warm parser/interpreter and OS pages',
                        'timed_stages':'overlapping independent measurements, not additive',
                        'profile_and_memory':'separate untimed passes; Python allocation peak excludes prior graph allocations',
                        'diagnostics_enabled':not (args.no_diagnostics or args.all_definitions_only or args.query_index_probe)}, 'cases':[]}
    report['mode'] = 'all-definitions-smoke' if args.all_definitions_only else 'query-index-probe' if args.query_index_probe else 'root-pipeline-distribution'
    report['query_index_policy'] = ('alternating-lazy-eager-query-only' if args.query_index_probe else
                                    'eager-endpoints-experiment' if args.eager_query_endpoints else 'engine-default')
    for name, root, prefix in args.case:
        case = (query_index_probe(name,Path(root).resolve(),prefix,args.max_files,budget,args.repeats) if args.query_index_probe else
                all_definitions(name,Path(root).resolve(),prefix,args.max_files,budget) if args.all_definitions_only else
                validate(name,Path(root).resolve(),prefix,args.repeats,args.max_files,budget,not args.no_diagnostics))
        report['cases'].append(case)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2)+'\n')
    report['engine_unchanged_during_run'] = initial == engine_manifest()
    report['finished_utc'] = datetime.now(timezone.utc).isoformat()
    report['process_maxrss'] = {'value':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'unit':'bytes' if sys.platform=='darwin' else 'KiB',
                                'scope':'cumulative whole benchmark process; not per case'}
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    if args.require_stable and not report['engine_unchanged_during_run']:
        raise SystemExit('engine changed during benchmark; report saved but not stable')


if __name__ == '__main__':
    main()
