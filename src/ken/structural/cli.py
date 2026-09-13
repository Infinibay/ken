"""CLI surface for graph queries, pattern/bug catalogues, and IR inspection."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import service
from .catalog import catalog
from .query import QueryBudget


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser("structural", help="query structural IR, GoF patterns and bug signatures")
    commands = parser.add_subparsers(dest="structural_command", required=True)
    for name in ("ir", "search", "patterns", "bugs", "catalog", "rules", "save-rule"):
        p = commands.add_parser(name)
        p.add_argument("--path", default=".", help="project root")
        p.add_argument("--scope", default=".", help="file or directory within the project")
        p.add_argument("--cache-mb", type=float, default=None, help="cache cap in MB; 0 disables; default 500")
        p.add_argument("--limit", type=int, default=100, help="maximum matches per rule")
        p.add_argument("--timeout-ms", type=int, default=2000, help="query budget per rule")
        if name in {"search", "save-rule"}:
            group = p.add_mutually_exclusive_group(required=name == "save-rule")
            p.add_argument("--evidence-mode", choices=["strict", "possible"], default="strict")
            group.add_argument("--query", help="selector or graph query")
            group.add_argument("--query-file", type=Path, help="UTF-8 query file")
        if name in {"search", "rules"}:
            p.add_argument("--rule", action="append", help="saved rule id (repeatable)")
            p.add_argument("--collection", action="append", help="collection name (repeatable)")
            p.add_argument("--tag", action="append", help="tag (repeatable)")
            p.add_argument("--rules-file", action="append", help="versioned rule library within the project")
        if name == "save-rule":
            p.add_argument("id")
            p.add_argument("--name", default="")
            p.add_argument("--description", default="")
            p.add_argument("--tag", action="append", default=[])
            p.add_argument("--collection", action="append", default=[])
            p.add_argument("--severity", default=None)
            p.add_argument("--recommendation", default="")
            p.add_argument("--overwrite", action="store_true")
        if name == "patterns":
            p.add_argument("--pattern", action="append", help="catalogue id (repeatable); omitted searches all 23")
        if name == "ir":
            p.add_argument("--view", choices=["source", "query", "instructions"], default="query", help="source facts, KenQL graph or instruction IR")
            p.add_argument("--format", choices=["json", "text"], default="json", help="text is available for the instruction view")
            p.add_argument("--symbol", default="", help="restrict entities/operations to a named symbol")


def dispatch(args: argparse.Namespace) -> int:
    command = args.structural_command
    root = Path(args.path).resolve()
    budget = QueryBudget(max_matches=args.limit, timeout_ms=args.timeout_ms)
    result: dict[str, Any]
    if command == "catalog":
        from .effects import BUG_RULES
        result = {"patterns": catalog(), "bugs": {k: {"description": v[0], "severity": v[1]} for k, v in BUG_RULES.items()}}
    elif command == "rules":
        from .rules import load_rules, select_rules
        rules = select_rules(load_rules(root, args.rules_file), args.rule, args.collection, args.tag)
        result = {"rules": [r.to_dict() for r in rules]}
    elif command == "save-rule":
        from .rules import SavedRule, save_rule
        query = args.query_file.read_text(encoding="utf-8") if args.query_file else args.query
        rule = SavedRule(args.id, query, args.name, args.description, args.tag, args.collection,
                         args.severity, args.recommendation)
        saved = save_rule(root, rule, overwrite=args.overwrite)
        result = {"ok": True, "path": str(saved), "rule": rule.to_dict()}
    elif command == "search":
        query = args.query_file.read_text() if args.query_file else args.query
        result = service.search(root, query or "", path=args.scope, cache_mb=args.cache_mb, budget=budget,
                                rule_ids=args.rule, collections=args.collection, tags=args.tag, rule_files=args.rules_file, evidence_mode=args.evidence_mode)
    elif command == "patterns":
        result = service.patterns(root, args.pattern, path=args.scope, cache_mb=args.cache_mb, budget=budget)
    elif command == "bugs":
        result = service.bugs(root, path=args.scope, cache_mb=args.cache_mb, budget=budget)
    else:
        if args.format == 'text' and args.view != 'instructions':
            raise ValueError('--format text requires --view instructions')
        graph, analysis = service.build_project(root, path=args.scope, cache_mb=args.cache_mb)
        if args.view == 'instructions':
            from .instruction_lowering import lower_instructions
            program = lower_instructions(graph)
            if args.symbol:
                program.functions = [f for f in program.functions if f.name == args.symbol]
            if args.format == 'text':
                print(program.format(), end='')
            else:
                print(json.dumps({'ok': True, 'ir': program.to_dict(), 'analysis': analysis}, indent=2, ensure_ascii=False))
            return 0
        if args.view == "query":
            from .kenql import query_graph
            graph = query_graph(graph).ir
        data = graph.to_dict()
        if args.symbol:
            roots = [e.id for e in graph.entities.values() if e.name == args.symbol]
            selected = {e.id for e in graph.entities.values() if any(e.id == r or e.id.startswith(r + "/") for r in roots)}
            data["entities"] = {k: v for k, v in data["entities"].items() if k in selected}
            data["operations"] = [v for v in data["operations"] if v["owner"] in selected]
            data["facts"] = [v for v in data["facts"] if v["subject"] in selected or v["object"] in selected]
        result = {"ok": True, "ir": data, "analysis": analysis}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0
