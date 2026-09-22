"""Reproducible parser/indexed/graph workloads, optionally against saved modules.

Before modifying the implementation, copy syntax/parser.py, execution.py and
structural/relational.py into a baseline directory. Pass --baseline-dir to load
those implementations beside the current ones and alternate measurement order.
No source parsing, disk/result-cache hits or external projects are timed here.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import statistics
import sys
import time
from hashlib import sha256
from pathlib import Path

from ken.kql2.compiler import compile
from ken.kql2.execution import execute
from ken.kql2.graph import relational_plan
from ken.kql2.syntax import parse
from ken.structural.model import IR, Entity, Fact, FactIndex
from ken.structural.relational import Executor
from ken.structural_store import Store

HEADER = 'language "kql/2"; module bench; '


def load_baseline(directory: Path, filename: str, package: str):
    spec = importlib.util.spec_from_file_location(
        package + "._refactor_baseline", directory / filename
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def measure(functions, repeats):
    for fn in functions.values():
        fn()
    samples = {name: [] for name in functions}
    for iteration in range(repeats):
        names = list(functions)
        if iteration % 2:
            names.reverse()
        for name in names:
            start = time.perf_counter()
            functions[name]()
            samples[name].append((time.perf_counter() - start) * 1000)
    return {
        name: {"median_ms": statistics.median(values), "samples_ms": values}
        for name, values in samples.items()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path)
    parser.add_argument("--nodes", type=int, default=500)
    parser.add_argument("--repeats", type=int, default=31)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.nodes < 1 or args.repeats < 1:
        parser.error("nodes and repeats must be positive")
    parsers, indexed, graph_engines = (
        {"current": parse},
        {"current": execute},
        {"current": Executor},
    )
    if args.baseline_dir:
        parsers["baseline"] = load_baseline(
            args.baseline_dir, "parser.py", "ken.kql2.syntax"
        ).parse
        indexed["baseline"] = load_baseline(
            args.baseline_dir, "execution.py", "ken.kql2"
        ).execute
        graph_engines["baseline"] = load_baseline(
            args.baseline_dir, "relational.py", "ken.structural"
        ).Executor
    queries = {
        "lookup": f'query q {{ class $c {{ name: "C{args.nodes - 1}"; method $m {{}} }} select $c.name,$m.name; }}',
        "scan": "query q { class $c { method $m {} } select $c.name,$m.name; }",
        "filter": 'query q { class $c { method $m {} } where $c.name != "missing" and $m.name == "work"; select $c.name; }',
        "properties": "query q { class $c { method $m { static: false; } } where $m.static == false; select $m.name,$m.static; }",
    }
    for query in queries.values():
        trees = [fn(HEADER + query) for fn in parsers.values()]
        assert all(tree == trees[0] for tree in trees)
    report = {
        "nodes_per_kind": args.nodes,
        "repeats": args.repeats,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "queries": queries,
        "workloads": {},
        "limitations": [
            "Synthetic warm in-process workloads; no universal speedup claim.",
            "No frontend parsing, project acquisition, disk/result cache or BODY workload.",
            "Timing assertions are deliberately excluded; semantic equality is asserted.",
            "Parse sample is 120 parses (30 repetitions of four queries).",
        ],
    }
    report["workloads"]["parse"] = measure(
        {
            name: lambda fn=fn: [
                fn(HEADER + q) for _ in range(30) for q in queries.values()
            ]
            for name, fn in parsers.items()
        },
        args.repeats,
    )
    ir = IR("bench.py", "python")
    for i in range(args.nodes):
        c, m = f"c{i}", f"m{i}"
        ir.entities[c] = Entity(c, "CLASS", f"C{i}", ir.path, 1, 4)
        ir.entities[m] = Entity(m, "CALLABLE", "work", ir.path, 2, 3, {"static": False})
        ir.facts.extend(
            (
                Fact(c, "ENTITY", "CLASS", {"name": f"C{i}"}),
                Fact(m, "ENTITY", "CALLABLE", {"name": "work"}),
                Fact(c, "HAS_METHOD", m),
            )
        )
    with Store() as store:
        unit = store.put_unit("corpus", ir, "fixed", "bench")
        snapshot = store.publish([unit], expected_parent=None)
        for name, source in queries.items():
            program = compile(parse(HEADER + source))
            outcomes = [fn(program, store, snapshot) for fn in indexed.values()]
            for result in outcomes:
                assert result.complete
                assert result.rows == outcomes[0].rows
                assert result.unknown_candidates == outcomes[0].unknown_candidates
                assert result.states == outcomes[0].states
                assert result.scanned_nodes == outcomes[0].scanned_nodes
            timings = measure(
                {
                    key: lambda fn=fn, program=program: fn(program, store, snapshot)
                    for key, fn in indexed.items()
                },
                args.repeats,
            )
            report["workloads"][name] = {
                **timings,
                "rows": len(outcomes[0].rows),
                "states": outcomes[0].states,
                "scanned": outcomes[0].scanned_nodes,
            }
    graph_query = 'query q { edge ENTITY($c,"CLASS"); edge HAS_METHOD($c,$m); edge ENTITY($m,"CALLABLE") {name:"work";}; select $c,$m; }'
    plan = relational_plan(compile(parse(HEADER + graph_query)))
    graph = FactIndex(ir)
    results = [engine(graph, {}).execute(plan) for engine in graph_engines.values()]
    assert all(
        result["complete"] and result["matches"] == results[0]["matches"]
        for result in results
    )
    report["queries"]["graph_join"] = graph_query
    report["workloads"]["graph_join"] = measure(
        {
            name: lambda engine=engine: engine(graph, {}).execute(plan)
            for name, engine in graph_engines.items()
        },
        args.repeats,
    )
    files = sorted(
        [
            *Path("src/ken/kql2").rglob("*.py"),
            *Path("src/ken/structural").glob("relational*.py"),
        ]
    )
    report["code_hashes"] = {
        str(path): sha256(path.read_bytes()).hexdigest() for path in files
    }
    if args.baseline_dir:
        report["baseline_hashes"] = {
            path.name: sha256(path.read_bytes()).hexdigest()
            for path in args.baseline_dir.glob("*.py")
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                name: {
                    key: round(value["median_ms"], 4)
                    for key, value in workload.items()
                    if isinstance(value, dict)
                }
                for name, workload in report["workloads"].items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
