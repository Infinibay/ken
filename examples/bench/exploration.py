"""Benchmark the public compiled backend, optionally verifying raw Tree-sitter.

PYTHONPATH=.:src python -m examples.bench.exploration ../codex /tmp/ken-exploration --oracle
The three syntactic queries are not the 23-pattern GoF catalogue.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import resource
import statistics
from pathlib import Path

from ken.kql2.service import search
from ken.structural.frontend import parser_for

PREFIX = 'language "kql/2"; module bench; query q {'
QUERIES = {
    "if": PREFIX + 'node $n {kind:"if";} select $n.path,$n.start_byte,$n.end_byte;}',
    "return_contains_call": PREFIX
    + """node $n {kind:"return";}
        where exists(CodeNode $c | $c.kind == "call" and contains($n,$c));
        select $n.path,$n.start_byte,$n.end_byte;}""",
    "function_branch_return": PREFIX
    + """node $n {kind:"callable";}
        where exists(CodeNode $b | $b.kind == "if" and contains($n,$b));
        where exists(CodeNode $r | $r.kind == "return" and contains($n,$r));
        select $n.path,$n.start_byte,$n.end_byte;}""",
}


def fingerprint(rows):
    return hashlib.sha256(
        json.dumps(sorted(rows), separators=(",", ":")).encode()
    ).hexdigest()


def oracle(root, manifest):
    # Independent navigation: no stored arrays, compiled predicates or query planner.
    from ken.structural.frontend import CALLS, FUNCTIONS, LANGUAGES

    branches = {"if_statement", "if_expression", "elif_clause"}
    returns = {"return_statement", "return_expression"}
    result = {name: [] for name in QUERIES}
    for name, _ in manifest:
        source = (root / name).read_bytes()
        tree = parser_for(LANGUAGES[Path(name).suffix.lower()], name).parse(source)
        stack = [tree.root_node]
        while stack:
            node = stack.pop()
            stack.extend(reversed(node.named_children))
            if node.has_error or node.is_missing:
                continue
            row = [name, node.start_byte, node.end_byte]
            if node.type in branches:
                result["if"].append(row)
            if node.type not in returns | FUNCTIONS:
                continue
            kinds, pending = set(), list(node.named_children)
            while pending:
                child = pending.pop()
                if not child.has_error and not child.is_missing:
                    kinds.add(child.type)
                pending.extend(child.named_children)
            if node.type in returns and kinds & CALLS:
                result["return_contains_call"].append(row)
            if node.type in FUNCTIONS and kinds & branches and kinds & returns:
                result["function_branch_return"].append(row)
    return {
        name: {"rows": len(rows), "sha256": fingerprint(rows)}
        for name, rows in result.items()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("cache", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--oracle", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    from ken.kql2 import exploration

    directory = Path(exploration.__file__).parent
    implementation = hashlib.sha256()
    for file in sorted([*directory.glob("*.py"), directory / "ast.fbs"]):
        implementation.update(file.name.encode())
        implementation.update(file.read_bytes())
    environment = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ("flatbuffers", "numpy", "tree-sitter")
        },
        "engine_sha256": implementation.hexdigest(),
    }
    records, manifest = [], None
    for repeat in range(args.repeats):
        for name, query in QUERIES.items():
            result = search(
                args.root,
                query,
                backend="exploration",
                cache_directory=args.cache,
                profile=True,
            )
            analysis = result["analysis"]
            manifest = analysis.pop("manifest")
            record = {
                "repeat": repeat,
                "query": name,
                "rows": len(result["rows"]),
                "sha256": fingerprint(result["rows"]),
                "complete": result["complete"],
                "reason": result["reason"],
                "unknown_candidates": result["unknown_candidates"],
                "coverage_complete": result["coverage_complete"],
                "analysis": analysis,
            }
            records.append(record)
            print(json.dumps(record), flush=True)
    report = {
        "environment": environment,
        "source_units": len(manifest),
        "manifest_sha256": fingerprint(manifest),
        "root": str(args.root.resolve()),
        "records": records,
        "warm_query_median_ms": {
            name: statistics.median(
                r["analysis"]["query_ms"] for r in records if r["query"] == name
            )
            for name in QUERIES
        },
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        / (1024**2 if platform.system() == "Darwin" else 1024),
    }
    if args.oracle:
        report["oracle"] = oracle(args.root.resolve(), manifest)
        assert all(
            report["oracle"][r["query"]] == {"rows": r["rows"], "sha256": r["sha256"]}
            for r in records
        )
    args.cache.mkdir(parents=True, exist_ok=True)
    (args.cache / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
