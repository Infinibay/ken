"""Shared public and module CLI for explicit KQL2 queries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ken.presentation import render_compact


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="print the complete result as JSON")
    parser.add_argument("query_file", type=Path, nargs="?")
    parser.add_argument("--explain", action="store_true", help="Validate and explain the query without scanning project files")
    parser.add_argument("--capabilities", action="store_true", help="List backend capabilities and syntax properties without scanning files")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--path", default=".")
    parser.add_argument("--query", default=None)
    parser.add_argument("--cache-mb", type=float, default=None)
    parser.add_argument("--timeout-ms", type=float, default=None,
                        help="Total search budget including compilation, indexing, and execution")
    parser.add_argument("--max-states", type=int, default=None)
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--library", type=Path, action="append", default=[])
    parser.add_argument("--reference", action="store_true")
    parser.add_argument(
        "--backend",
        choices=("indexed", "exploration"),
        default="indexed",
        help="exploration compiles syntax queries to FlatBuffers tree walks",
    )
    parser.add_argument(
        "--cache-directory",
        type=Path,
        default=None,
        help="Override the exploration cache directory",
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Execute and report operator costs, bypassing cached results",
    )


def dispatch(args: argparse.Namespace) -> int:
    from .service import search
    from .syntax import parse

    def emit(value):
        print(json.dumps(value, ensure_ascii=False, indent=2) if getattr(args, "json", False)
              else render_compact(value, diagnostics=bool(args.profile or args.explain)))

    try:
        if getattr(args, "capabilities", False):
            from .explanation import capabilities

            emit(capabilities())
            return 0
        if args.query_file is None:
            raise ValueError("a query file is required unless --capabilities is selected")
        libraries = {}
        for path in args.library:
            source = path.read_text()
            module = parse(source, str(path)).module
            if module in libraries:
                raise ValueError("duplicate library module: " + module)
            libraries[module] = source
        if getattr(args, "explain", False):
            from .explanation import explain

            emit(explain(args.query_file.read_text(), query_name=args.query,
                         backend=args.backend, libraries=libraries))
            return 0
        result = search(
            args.root,
            args.query_file.read_text(),
            query_name=args.query,
            path=args.path,
            cache_mb=args.cache_mb,
            timeout_ms=args.timeout_ms,
            max_states=args.max_states,
            max_rows=args.max_rows,
            reference=args.reference,
            libraries=libraries,
            profile=args.profile,
            backend=getattr(args, "backend", "indexed"),
            cache_directory=getattr(args, "cache_directory", None),
        )
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}) if getattr(args, "json", False)
              else f"error: {exc}", file=sys.stderr)
        return 2
    from ken.checks.report import query_view
    emit(result if getattr(args, "json", False) or args.profile else query_view(result))
    return 0 if result["complete"] else 3
