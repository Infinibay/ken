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
    parser.add_argument("--saved", default=None, metavar="MODULE", help="Execute a module saved in this project's Ken DB")
    parser.add_argument("--save", action="store_true", help="Save query_file as a reusable module without executing it")
    parser.add_argument("--description", default=None, help="Description for --save")
    parser.add_argument("--expected-revision", default=None, help="Current revision required when replacing a saved module")
    parser.add_argument("--explain", action="store_true", help="Validate and explain the query without scanning project files")
    parser.add_argument("--capabilities", action="store_true", help="List backend capabilities and syntax properties without scanning files")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--path", default=".")
    parser.add_argument("--query", default=None)
    parser.add_argument("--cache-mb", type=float, default=None)
    parser.add_argument("--timeout-ms", type=float, default=None,
                        help="Prepared query budget including compilation, execution and local transport; indexing waits separately")
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
    from .syntax import parse

    def emit(value):
        print(json.dumps(value, ensure_ascii=False, indent=2) if getattr(args, "json", False)
              else render_compact(value, diagnostics=bool(args.profile or args.explain)))

    try:
        if getattr(args, "capabilities", False):
            from .explanation import capabilities

            emit(capabilities())
            return 0
        from .module_inputs import validate_entry

        source = args.query_file.read_text() if args.query_file is not None else None
        validate_entry(source, args.saved)
        if args.save:
            if source is None or args.explain or args.library:
                raise ValueError("--save requires a module file and cannot be combined with --explain or --library; save imports first")
            from .registry import ModuleRegistry

            saved = ModuleRegistry(args.root).save(source, description=args.description, expected_revision=args.expected_revision)
            print(json.dumps(saved.to_dict(), indent=2))
            return 0
        if args.description is not None or args.expected_revision is not None:
            raise ValueError("--description and --expected-revision require --save")
        libraries = {}
        for path in args.library:
            library_source = path.read_text()
            module = parse(library_source, str(path)).module
            if module in libraries:
                raise ValueError("duplicate library module: " + module)
            libraries[module] = library_source
        if getattr(args, "explain", False):
            from .explanation import explain

            emit(explain(source, saved_query=args.saved, root=args.root, query_name=args.query,
                         backend=args.backend, libraries=libraries))
            return 0
        from .automatic import search

        result = search(
            args.root,
            source,
            **({"saved_query":args.saved} if args.saved else {}),
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
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}) if getattr(args, "json", False)
              else f"error: {exc}", file=sys.stderr)
        return 2
    from ken.checks.report import query_view
    emit(result if getattr(args, "json", False) or args.profile else query_view(result))
    return 0 if result["complete"] else 3
