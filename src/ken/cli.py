"""Command-line entrypoint for installing, querying, and serving ken.

Subcommand layout:

    ken install [PATH]                  install + initial index
    ken reinstall [PATH]                reinstall CLI + re-apply project install
    ken status [PATH]                   show project state
    ken rank [QUERY...]                 print ranked context for a query
    ken explain [QUERY...]              explain rank scoring for a query
    ken search-files QUERY              semantic file search
    ken search-symbols QUERY            semantic symbol search
    ken bench DATASET.jsonl             evaluate ranker recall on labeled prompts
    ken reembed [--model NAME]         re-encode all embeddings (e.g. new model)
    ken default-model [NAME]            show/set the embedding model for new projects
    ken models                          list available embedding models
    ken remember TOPIC CONTENT          save a reusable finding
    ken forget TOPIC                    delete a saved finding
    ken findings                        list saved findings
    ken recall QUERY                    search saved findings
    ken tools  [NAME] [ARGS...]         run an MCP tool directly (--list, --help)
    ken serve  [PATH]                   start the daemon
    ken hook session-start              hooks invoked by coding agents
    ken hook session-end
    ken hook user-prompt
    ken hook tool-call --phase pre|post
    ken hook stop
    ken uninstall [PATH]

Interactive commands either read the local SQLite index directly
(`search-*`, `remember`, `recall`) or ask the daemon for ranked context
(`rank`, `explain`). Hook subcommands always read JSON from stdin and
degrade quietly on daemon errors so agent workflows are not blocked by
context collection.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from ken import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ken")
    parser.add_argument("--version", action="version", version=f"ken {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_install = sub.add_parser("install", help="install ken into a project")
    p_install.add_argument(
        "path", nargs="?", default=".", help="project path (default: cwd)"
    )
    p_install.add_argument(
        "-q", "--quiet", action="store_true", help="suppress per-file index output"
    )
    p_install.add_argument(
        "--claude",
        action="store_true",
        help="explicitly install Claude Code hooks and MCP config (default)",
    )
    p_install.add_argument(
        "--codex",
        action="store_true",
        help="force project-local Codex hooks and MCP config installation",
    )
    p_install.add_argument(
        "--opencode",
        action="store_true",
        help="register ken as an MCP server in the project's opencode.json (or opencode.jsonc)",
    )
    p_install.add_argument(
        "--embed",
        action="store_true",
        help="compute file and symbol embeddings during install instead of lazily",
    )
    p_install.add_argument(
        "--embed-limit",
        type=int,
        default=None,
        help="with --embed, eagerly embed at most N prioritized files; index the rest structurally",
    )
    p_install.add_argument(
        "--no-wire",
        action="store_true",
        help="index only; skip wiring Claude/Codex/OpenCode hooks and MCP config "
        "(for external hosts that drive the daemon directly)",
    )

    p_reinstall = sub.add_parser(
        "reinstall",
        help="reinstall ken from this checkout and re-apply project wiring",
    )
    p_reinstall.add_argument(
        "path", nargs="?", default=".", help="project path (default: cwd)"
    )
    p_reinstall.add_argument(
        "-q", "--quiet", action="store_true", help="suppress install output"
    )
    p_reinstall.add_argument(
        "--no-project",
        action="store_true",
        help="only reinstall the ken CLI; do not run `ken install PATH` afterwards",
    )
    p_reinstall.add_argument(
        "--claude",
        action="store_true",
        help="pass --claude to the project install step",
    )
    p_reinstall.add_argument(
        "--codex",
        action="store_true",
        help="pass --codex to the project install step",
    )
    p_reinstall.add_argument(
        "--opencode",
        action="store_true",
        help="pass --opencode to the project install step",
    )
    p_reinstall.add_argument(
        "--embed",
        action="store_true",
        help="pass --embed to the project install step",
    )
    p_reinstall.add_argument(
        "--embed-limit",
        type=int,
        default=None,
        help="with --embed, eagerly embed at most N prioritized files during project install",
    )

    p_status = sub.add_parser("status", help="show ken project status")
    p_status.add_argument(
        "path", nargs="?", default=".", help="project path (default: cwd)"
    )
    p_status.add_argument(
        "--json", action="store_true", help="print machine-readable status"
    )

    p_rank = sub.add_parser("rank", help="print ranked context for a query")
    p_rank.add_argument("query", nargs="*", help="query text (default: latest prompt)")
    p_rank.add_argument("--path", default=".", help="project path (default: cwd)")
    p_rank.add_argument("-v", "--verbose", type=int, choices=(0, 1, 2), default=1)
    p_rank.add_argument("--max-chars", type=int, help="cap rendered context size")
    p_rank.add_argument(
        "--stats", action="store_true", help="print context size stats to stderr"
    )
    p_rank.add_argument("--json", action="store_true", help="print raw JSON response")

    p_explain = sub.add_parser("explain", help="explain rank scoring for a query")
    p_explain.add_argument(
        "query", nargs="*", help="query text (default: latest prompt)"
    )
    p_explain.add_argument("--path", default=".", help="project path (default: cwd)")
    p_explain.add_argument(
        "--json", action="store_true", help="print raw JSON response"
    )

    p_search_files = sub.add_parser(
        "search-files", help="semantic search over indexed files"
    )
    p_search_files.add_argument("query", nargs="+", help="query text")
    p_search_files.add_argument(
        "--path", default=".", help="project path (default: cwd)"
    )
    p_search_files.add_argument("-n", "--limit", type=int, default=8)
    p_search_files.add_argument(
        "--json", action="store_true", help="print raw JSON response"
    )

    p_search_symbols = sub.add_parser(
        "search-symbols", help="semantic search over indexed symbols"
    )
    p_search_symbols.add_argument("query", nargs="+", help="query text")
    p_search_symbols.add_argument(
        "--path", default=".", help="project path (default: cwd)"
    )
    p_search_symbols.add_argument("-n", "--limit", type=int, default=10)
    p_search_symbols.add_argument(
        "--json", action="store_true", help="print raw JSON response"
    )

    p_bench = sub.add_parser("bench", help="evaluate ranker recall on a JSONL dataset")
    p_bench.add_argument("dataset", help="JSONL rows with prompt + expected_files")
    p_bench.add_argument("--path", default=".", help="project path (default: cwd)")
    p_bench.add_argument("--top", type=int, default=8, help="ranked files to evaluate")
    p_bench.add_argument(
        "--max-chars", type=int, default=0, help="optional render budget"
    )
    p_bench.add_argument(
        "--fail-under-case-recall",
        type=float,
        default=None,
        help="exit non-zero if case recall is below this 0..1 threshold",
    )
    p_bench.add_argument(
        "--fail-under-expected-file-recall",
        type=float,
        default=None,
        help="exit non-zero if expected-file recall is below this 0..1 threshold",
    )
    p_bench.add_argument(
        "--explain-misses",
        action="store_true",
        help="include missed expected files and top ranked reasons per case",
    )
    p_bench.add_argument(
        "--json", action="store_true", help="print machine-readable metrics"
    )

    p_reembed = sub.add_parser(
        "reembed", help="re-encode all embeddings with the current embedding model"
    )
    p_reembed.add_argument("--path", default=".", help="project path (default: cwd)")
    p_reembed.add_argument(
        "--model",
        default=None,
        help="embedding model to switch to (sets KEN_EMBED_MODEL for this run)",
    )
    p_reembed.add_argument(
        "--check",
        action="store_true",
        help="only verify the stored embeddings match the live model (probe vector)",
    )
    p_reembed.add_argument(
        "--json", action="store_true", help="print machine-readable result"
    )

    p_vectors = sub.add_parser(
        "vectors", help="inspect, migrate or compact the memory-mapped vector store"
    )
    p_vectors.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=("status", "verify", "migrate", "compact"),
        help=(
            "status: sizes and coverage · verify: cross-check slots against rows · "
            "migrate: move inline vectors into the store · compact: reclaim leaked slots"
        ),
    )
    p_vectors.add_argument("--path", default=".", help="project path (default: cwd)")
    p_vectors.add_argument(
        "--json", action="store_true", help="print machine-readable result"
    )

    p_default_model = sub.add_parser(
        "default-model",
        help="show or set the embedding model used for NEW projects",
    )
    p_default_model.add_argument(
        "model",
        nargs="?",
        default=None,
        help="model to set as the default for new projects (omit to show current)",
    )
    p_default_model.add_argument(
        "--clear",
        action="store_true",
        help="reset to ken's built-in default",
    )

    p_models = sub.add_parser("models", help="list available embedding models")
    p_models.add_argument(
        "--json", action="store_true", help="print machine-readable list"
    )

    p_remember = sub.add_parser("remember", help="save a reusable finding")
    p_remember.add_argument("topic", help="short lookup key")
    p_remember.add_argument("content", help="finding content")
    p_remember.add_argument("--path", default=".", help="project path (default: cwd)")
    p_remember.add_argument(
        "--tag", action="append", default=[], help="tag for the finding"
    )
    p_remember.add_argument(
        "--kind",
        choices=("finding", "persistent_rule", "experimental_finding", "hypothesis"),
        help="explicit finding kind (stored as a reserved kind:<value> tag)",
    )
    p_remember.add_argument(
        "--json", action="store_true", help="print raw JSON response"
    )

    p_forget = sub.add_parser("forget", help="delete a saved finding by exact topic")
    p_forget.add_argument("topic", help="exact finding topic to delete")
    p_forget.add_argument("--path", default=".", help="project path (default: cwd)")
    p_forget.add_argument("--json", action="store_true", help="print raw JSON response")

    p_findings = sub.add_parser("findings", help="list saved findings")
    p_findings.add_argument("--path", default=".", help="project path (default: cwd)")
    p_findings.add_argument("-n", "--limit", type=int, default=20)
    p_findings.add_argument("--tag", help="filter by exact tag")
    p_findings.add_argument(
        "--json", action="store_true", help="print raw JSON response"
    )

    p_recall = sub.add_parser("recall", help="semantic search over saved findings")
    p_recall.add_argument("query", nargs="+", help="query text")
    p_recall.add_argument("--path", default=".", help="project path (default: cwd)")
    p_recall.add_argument("-n", "--limit", type=int, default=5)
    p_recall.add_argument(
        "--min-score",
        type=float,
        default=0.25,
        help="minimum cosine similarity to return; use 0 to show nearest neighbors",
    )
    p_recall.add_argument("--json", action="store_true", help="print raw JSON response")

    p_related = sub.add_parser(
        "related-findings", help="findings related to a topic in the findings graph"
    )
    p_related.add_argument(
        "topic", help="finding topic (exact, else nearest by recall)"
    )
    p_related.add_argument("--path", default=".", help="project path (default: cwd)")
    p_related.add_argument("-n", "--limit", type=int, default=8)
    p_related.add_argument(
        "--min-weight", type=float, default=0.3, help="minimum edge weight"
    )
    p_related.add_argument(
        "--json", action="store_true", help="print raw JSON response"
    )

    p_file_findings = sub.add_parser(
        "file-findings", help="saved findings that reference a file"
    )
    p_file_findings.add_argument("file", help="project-relative file path")
    p_file_findings.add_argument(
        "--path", default=".", help="project path (default: cwd)"
    )
    p_file_findings.add_argument("-n", "--limit", type=int, default=15)
    p_file_findings.add_argument(
        "--expand", action="store_true", help="also include graph neighbors"
    )
    p_file_findings.add_argument(
        "--json", action="store_true", help="print raw JSON response"
    )

    p_fgraph = sub.add_parser("findings-graph", help="findings graph maintenance")
    fgraph_sub = p_fgraph.add_subparsers(dest="fgraph_cmd", required=True)
    p_fgraph_rebuild = fgraph_sub.add_parser(
        "rebuild", help="drop and recompute the findings graph"
    )
    p_fgraph_rebuild.add_argument(
        "--path", default=".", help="project path (default: cwd)"
    )
    p_fgraph_rebuild.add_argument(
        "--json", action="store_true", help="print raw JSON response"
    )

    p_serve = sub.add_parser("serve", help="run the ken daemon")
    p_serve.add_argument(
        "path", nargs="?", default=".", help="project path (default: cwd)"
    )
    p_serve.add_argument(
        "--background",
        action="store_true",
        help="redirect logs to .ken/daemon.log (used when spawned by a hook)",
    )

    p_hook = sub.add_parser("hook", help="hook handlers invoked by coding agents")
    hook_sub = p_hook.add_subparsers(dest="hook_cmd", required=True)
    hook_sub.add_parser("session-start")
    hook_sub.add_parser("session-end")
    hook_sub.add_parser("user-prompt")
    hook_sub.add_parser("stop")
    p_tool = hook_sub.add_parser("tool-call")
    p_tool.add_argument("--phase", choices=("pre", "post"), required=True)

    p_mcp = sub.add_parser("mcp", help="run as MCP stdio server")
    p_mcp.add_argument(
        "path", nargs="?", default=".", help="project path (default: cwd)"
    )

    p_tools = sub.add_parser(
        "tools",
        help="invoke a ken MCP tool directly from the CLI",
        description=(
            "Run any tool the ken MCP server exposes, without an agent.\n\n"
            "  ken tools                     list available tools\n"
            "  ken tools <name> --help       show a tool's parameters\n"
            "  ken tools <name> [ARGS...]    run the tool and print JSON\n\n"
            "The <name> may be given with or without the 'ken_' prefix "
            "(e.g. 'grep' or 'ken_grep'). Required parameters are positional; "
            "optional ones are --flags mirroring the tool's schema."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_tools.add_argument("--path", default=".", help="project path (default: cwd)")
    p_tools.add_argument(
        "--list", action="store_true", help="list available tools and exit"
    )
    p_tools.add_argument(
        "--compact", action="store_true", help="print result as single-line JSON"
    )
    p_tools.add_argument(
        "tool", nargs="?", help="tool name (with or without the ken_ prefix)"
    )
    p_tools.add_argument(
        "tool_args",
        nargs=argparse.REMAINDER,
        help="arguments for the tool; run `ken tools <name> --help` to see them",
    )

    p_uninstall = sub.add_parser("uninstall", help="remove ken hooks from a project")
    p_uninstall.add_argument(
        "path", nargs="?", default=".", help="project path (default: cwd)"
    )
    p_uninstall.add_argument(
        "--keep-db", action="store_true", help="don't delete .ken/ken.db"
    )

    args = parser.parse_args(argv)

    if (
        args.cmd in {"install", "reinstall"}
        and args.embed_limit is not None
        and not args.embed
    ):
        parser.error("--embed-limit requires --embed")

    if args.cmd == "install":
        from ken.install import install

        install(
            Path(args.path),
            verbose=not args.quiet,
            force_claude=args.claude,
            force_codex=args.codex,
            force_opencode=args.opencode,
            embed=args.embed,
            embed_limit=args.embed_limit,
            no_wire=args.no_wire,
        )
        return 0

    if args.cmd == "reinstall":
        return _reinstall_cli(
            Path(args.path),
            quiet=args.quiet,
            project=not args.no_project,
            force_claude=args.claude,
            force_codex=args.codex,
            force_opencode=args.opencode,
            embed=args.embed,
            embed_limit=args.embed_limit,
        )

    if args.cmd == "status":
        from ken.status import show_status

        return show_status(Path(args.path), as_json=args.json)

    if args.cmd == "rank":
        return _rank_cli(
            Path(args.path),
            " ".join(args.query),
            args.verbose,
            max_chars=args.max_chars,
            as_json=args.json,
            stats=args.stats,
        )

    if args.cmd == "explain":
        return _explain_cli(Path(args.path), " ".join(args.query), as_json=args.json)

    if args.cmd == "search-files":
        return _search_cli(
            Path(args.path),
            " ".join(args.query),
            args.limit,
            kind="files",
            as_json=args.json,
        )

    if args.cmd == "search-symbols":
        return _search_cli(
            Path(args.path),
            " ".join(args.query),
            args.limit,
            kind="symbols",
            as_json=args.json,
        )

    if args.cmd == "reembed":
        return _reembed_cli(
            Path(args.path),
            model=args.model,
            check_only=args.check,
            as_json=args.json,
        )

    if args.cmd == "vectors":
        return _vectors_cli(Path(args.path), args.action, as_json=args.json)

    if args.cmd == "default-model":
        return _default_model_cli(model=args.model, clear=args.clear)

    if args.cmd == "models":
        return _models_cli(as_json=args.json)

    if args.cmd == "bench":
        return _bench_cli(
            Path(args.path),
            Path(args.dataset),
            top=args.top,
            max_chars=args.max_chars,
            fail_under_case_recall=args.fail_under_case_recall,
            fail_under_expected_file_recall=args.fail_under_expected_file_recall,
            explain_misses=args.explain_misses,
            as_json=args.json,
        )

    if args.cmd == "remember":
        return _remember_cli(
            Path(args.path),
            args.topic,
            args.content,
            tags=args.tag,
            kind=args.kind,
            as_json=args.json,
        )

    if args.cmd == "forget":
        return _forget_cli(Path(args.path), args.topic, as_json=args.json)

    if args.cmd == "findings":
        return _findings_cli(
            Path(args.path),
            args.limit,
            tag=args.tag,
            as_json=args.json,
        )

    if args.cmd == "related-findings":
        return _related_findings_cli(
            Path(args.path),
            args.topic,
            limit=args.limit,
            min_weight=args.min_weight,
            as_json=args.json,
        )

    if args.cmd == "file-findings":
        return _file_findings_cli(
            Path(args.path),
            args.file,
            limit=args.limit,
            expand=args.expand,
            as_json=args.json,
        )

    if args.cmd == "findings-graph":
        return _findings_graph_cli(Path(args.path), args.fgraph_cmd, as_json=args.json)

    if args.cmd == "recall":
        return _recall_cli(
            Path(args.path),
            " ".join(args.query),
            args.limit,
            args.min_score,
            as_json=args.json,
        )

    if args.cmd == "serve":
        from ken.serve import serve

        return serve(Path(args.path), background=args.background)

    if args.cmd == "hook":
        from ken.hook import dispatch_hook

        return dispatch_hook(args)

    if args.cmd == "mcp":
        from ken.mcp.server import run as run_mcp

        return run_mcp(Path(args.path))

    if args.cmd == "tools":
        return _tools_cli(
            Path(args.path),
            args.tool,
            args.tool_args,
            list_only=args.list,
            compact=args.compact,
        )

    if args.cmd == "uninstall":
        from ken.install_uninstall import uninstall

        return uninstall(Path(args.path), keep_db=args.keep_db)

    parser.error(f"unknown command: {args.cmd}")
    return 2


def _reinstall_cli(
    project_path: Path,
    *,
    quiet: bool,
    project: bool,
    force_claude: bool,
    force_codex: bool,
    force_opencode: bool,
    embed: bool,
    embed_limit: int | None,
) -> int:
    repo_root = Path(__file__).resolve().parents[2]
    if not (repo_root / "pyproject.toml").is_file():
        print(
            "error: cannot locate ken source checkout for editable reinstall",
            file=sys.stderr,
        )
        return 1
    uv = shutil.which("uv")
    if uv is None:
        print("error: uv is required for `ken reinstall`", file=sys.stderr)
        return 1

    reinstall_cmd = [
        uv,
        "tool",
        "install",
        "--editable",
        str(repo_root),
        "--force",
        "--reinstall",
        "--refresh",
    ]
    stdout = subprocess.DEVNULL if quiet else None
    stderr = subprocess.DEVNULL if quiet else None
    try:
        subprocess.run(reinstall_cmd, check=True, stdout=stdout, stderr=stderr)
    except subprocess.CalledProcessError as exc:
        print(
            f"error: CLI reinstall failed with exit code {exc.returncode}",
            file=sys.stderr,
        )
        return int(exc.returncode or 1)

    if not project:
        return 0

    ken = shutil.which("ken")
    if ken is None:
        print("error: ken was reinstalled but is not on PATH", file=sys.stderr)
        return 1
    install_cmd = [ken, "install", str(project_path)]
    if quiet:
        install_cmd.append("--quiet")
    if force_claude:
        install_cmd.append("--claude")
    if force_codex:
        install_cmd.append("--codex")
    if force_opencode:
        install_cmd.append("--opencode")
    if embed:
        install_cmd.append("--embed")
    if embed_limit is not None:
        install_cmd.extend(["--embed-limit", str(embed_limit)])
    try:
        subprocess.run(install_cmd, check=True, stdout=stdout, stderr=stderr)
    except subprocess.CalledProcessError as exc:
        print(
            f"error: project install failed with exit code {exc.returncode}",
            file=sys.stderr,
        )
        return int(exc.returncode or 1)
    return 0


def _read_hook_payload() -> dict:
    """Read a JSON hook payload from stdin.

    Returns an empty dict if stdin is closed, empty, or invalid. Hook
    handlers treat that as missing optional signal rather than as a hard
    failure because context collection must never block the agent.
    """
    if sys.stdin.isatty():
        return {}
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _rank_cli(
    project_path: Path,
    query: str,
    verbose: int,
    *,
    max_chars: int | None,
    as_json: bool,
    stats: bool,
) -> int:
    from ken.daemon import client as daemon_client

    payload: dict[str, Any] = {"query": query.strip(), "verbose": verbose}
    if max_chars is not None:
        payload["max_chars"] = max_chars
    resp = daemon_client.post(
        project_path.resolve(),
        "/rank",
        payload,
    )
    return _print_daemon_response(resp, "context_block", as_json=as_json, stats=stats)


def _explain_cli(project_path: Path, query: str, *, as_json: bool) -> int:
    from ken.daemon import client as daemon_client

    resp = daemon_client.post(
        project_path.resolve(), "/explain", {"query": query.strip()}
    )
    return _print_daemon_response(resp, None, as_json=as_json)


def _print_daemon_response(
    resp: dict[str, Any] | None,
    text_key: str | None,
    *,
    as_json: bool,
    stats: bool = False,
) -> int:
    if resp is None:
        print("error: daemon unreachable", file=sys.stderr)
        return 1
    if as_json:
        print(json.dumps(resp, indent=2))
        return 0 if resp.get("ok") else 1
    if not resp.get("ok"):
        print(f"error: {resp.get('error', 'request failed')}", file=sys.stderr)
        return 1
    if text_key:
        print(resp.get(text_key, ""))
        if stats:
            print(_format_rank_stats(resp), file=sys.stderr)
    else:
        print(json.dumps(resp, indent=2))
    return 0


def _format_rank_stats(resp: dict[str, Any]) -> str:
    block = str(resp.get("context_block") or "")
    chars = int(resp.get("context_chars") or len(block))
    est_tokens = int(
        resp.get("context_est_tokens") or ((chars + 3) // 4 if chars else 0)
    )
    return (
        f"context: {chars} chars, "
        f"~{est_tokens} tokens; "
        f"files={int(resp.get('files') or 0)}, "
        f"symbols={int(resp.get('symbols') or 0)}, "
        f"findings={int(resp.get('findings') or 0)}"
    )


def _search_cli(
    project_path: Path, query: str, limit: int, *, kind: str, as_json: bool
) -> int:
    from ken import _paths
    from ken.db import connect
    from ken.search import (
        format_file_hits,
        format_symbol_hits,
        search_files,
        search_symbols,
    )

    root = _paths.find_project_root(project_path.resolve()) or project_path.resolve()
    db_path = _paths.db_path(root)
    if not db_path.is_file():
        print(f"error: no .ken project at {root}", file=sys.stderr)
        return 1
    with connect(db_path) as conn:
        if kind == "files":
            hits = search_files(conn, query, limit=limit, project_root=root)
            rendered = format_file_hits(hits)
        else:
            hits = search_symbols(conn, query, limit=limit, project_root=root)
            rendered = format_symbol_hits(hits)
    if as_json:
        print(json.dumps(hits, indent=2))
    elif rendered:
        print(rendered)
    return 0


def _remember_cli(
    project_path: Path,
    topic: str,
    content: str,
    *,
    tags: list[str],
    kind: str | None,
    as_json: bool,
) -> int:
    from ken.memory import remember

    root, db_path = _resolve_project_db(project_path)
    if db_path is None:
        print(f"error: no .ken project at {root}", file=sys.stderr)
        return 1
    from ken.db import connect

    with connect(db_path) as conn:
        resp = remember(conn, topic, content, tags=tags, kind=kind)
    if as_json:
        print(json.dumps(resp, indent=2))
    elif resp.get("ok"):
        print(f"remembered: {resp['topic']}")
    else:
        print(f"error: {resp.get('error', 'remember failed')}", file=sys.stderr)
    return 0 if resp.get("ok") else 1


def _forget_cli(project_path: Path, topic: str, *, as_json: bool) -> int:
    from ken.db import connect
    from ken.memory import forget

    root, db_path = _resolve_project_db(project_path)
    if db_path is None:
        print(f"error: no .ken project at {root}", file=sys.stderr)
        return 1
    with connect(db_path) as conn:
        resp = forget(conn, topic)
    if as_json:
        print(json.dumps(resp, indent=2))
    elif resp.get("deleted", 0):
        print(f"forgot: {resp['topic']}")
    else:
        print(f"not found: {resp['topic']}", file=sys.stderr)
    return 0 if resp.get("deleted", 0) else 1


def _findings_cli(
    project_path: Path,
    limit: int,
    *,
    tag: str | None,
    as_json: bool,
) -> int:
    from ken.db import connect
    from ken.memory import format_recall_hits, list_findings

    root, db_path = _resolve_project_db(project_path)
    if db_path is None:
        print(f"error: no .ken project at {root}", file=sys.stderr)
        return 1
    with connect(db_path) as conn:
        hits = list_findings(conn, limit=limit, tag=tag)
    if as_json:
        print(json.dumps(hits, indent=2))
    else:
        rendered = format_recall_hits([{**hit, "score": 0.0} for hit in hits])
        if rendered:
            print(rendered)
    return 0


def _recall_cli(
    project_path: Path,
    query: str,
    limit: int,
    min_score: float,
    *,
    as_json: bool,
) -> int:
    from ken.db import connect
    from ken.memory import format_recall_hits, recall

    root, db_path = _resolve_project_db(project_path)
    if db_path is None:
        print(f"error: no .ken project at {root}", file=sys.stderr)
        return 1
    with connect(db_path) as conn:
        hits = recall(conn, query, limit=limit, min_score=min_score)
    if as_json:
        print(json.dumps(hits, indent=2))
    else:
        rendered = format_recall_hits(hits)
        if rendered:
            print(rendered)
        else:
            print(f"no relevant findings (min_score={min_score:.3f})")
    return 0


def _related_findings_cli(
    project_path: Path,
    topic: str,
    *,
    limit: int,
    min_weight: float,
    as_json: bool,
) -> int:
    from ken.db import connect
    from ken.findings_graph import related_findings

    root, db_path = _resolve_project_db(project_path)
    if db_path is None:
        print(f"error: no .ken project at {root}", file=sys.stderr)
        return 1
    with connect(db_path) as conn:
        result = related_findings(conn, topic, limit=limit, min_weight=min_weight)
    if as_json:
        print(json.dumps(result, indent=2))
        return 0
    neighbors = result.get("neighbors", [])
    if not neighbors:
        print(result.get("note", "no related findings"))
        return 0
    for n in neighbors:
        links = ", ".join(f"{e['type']} {e['weight']:.2f}" for e in n["edges"])
        print(f"{n['best_weight']:.2f}  {n['topic']}  [{links}]")
    return 0


def _file_findings_cli(
    project_path: Path,
    file_path: str,
    *,
    limit: int,
    expand: bool,
    as_json: bool,
) -> int:
    from ken.db import connect
    from ken.findings_graph import file_findings

    root, db_path = _resolve_project_db(project_path)
    if db_path is None:
        print(f"error: no .ken project at {root}", file=sys.stderr)
        return 1
    with connect(db_path) as conn:
        result = file_findings(
            conn, file_path, expand=expand, limit=limit, project_root=root
        )
    if as_json:
        print(json.dumps(result, indent=2))
        return 0
    findings = result.get("findings", [])
    if not findings:
        print(result.get("note", "no findings reference this file"))
        return 0
    for f in findings:
        print(f"{f['topic']}\n    {f['content']}")
    for r in result.get("related", []):
        print(f"~ {r['topic']} ({r['weight']:.2f})")
    return 0


def _findings_graph_cli(project_path: Path, subcmd: str, *, as_json: bool) -> int:
    from ken.db import connect
    from ken.findings_graph import ensure_finding_graph, rebuild_finding_graph

    root, db_path = _resolve_project_db(project_path)
    if db_path is None:
        print(f"error: no .ken project at {root}", file=sys.stderr)
        return 1
    with connect(db_path) as conn:
        try:
            ensure_finding_graph(conn)
            conn.execute("BEGIN IMMEDIATE")
            result = rebuild_finding_graph(conn)
            conn.execute("COMMIT")
        except Exception as exc:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            print(f"error: rebuild failed: {exc}", file=sys.stderr)
            return 1
        edges = conn.execute("SELECT COUNT(*) AS n FROM cr_finding_edges").fetchone()[
            "n"
        ]
        refs = conn.execute("SELECT COUNT(*) AS n FROM cr_finding_refs").fetchone()["n"]
    result = {**result, "edges": int(edges), "refs": int(refs)}
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"findings graph rebuilt: {result['refs']} refs, {result['edges']} edges")
    return 0


def _vectors_cli(project_path: Path, action: str, *, as_json: bool) -> int:
    """`ken vectors` — the maintenance surface for the memory-mapped store."""
    from ken import _paths
    from ken.db import connect, init_schema
    from ken.embedder import active_model, configure_for_project, get_embedder
    from ken.vectors import SPACES, VectorStore, VectorStoreError, compact
    from ken.vectors import migrate_inline_vectors, reclaim_database, vectors_dir

    root = project_path.resolve()
    db = _paths.db_path(root)
    if not db.is_file():
        print(f"error: no ken index at {root}", file=sys.stderr)
        return 1
    conn = connect(db)
    init_schema(conn)
    configure_for_project(conn)
    try:
        dim = int(get_embedder().dim)
    except Exception as exc:
        print(f"error: cannot load the embedder ({exc})", file=sys.stderr)
        return 1

    def say(msg: str) -> None:
        if not as_json:
            print(f"  {msg}")

    result: dict[str, Any] = {"action": action, "path": str(root), "dim": dim}
    try:
        if action == "migrate":
            if not as_json:
                print(f"[vectors] moving inline vectors into {vectors_dir(root)}")
            moved = migrate_inline_vectors(
                conn, root, dim=dim, model=active_model(), progress=say
            )
            result["moved"] = moved
            if sum(moved.values()):
                # The migration only NULLs the column; without this the file
                # keeps every freed page and the user sees no space back.
                if not as_json:
                    print("[vectors] reclaiming freed pages (VACUUM)…")
                try:
                    before, after = reclaim_database(conn)
                    result["db_bytes_before"] = before
                    result["db_bytes_after"] = after
                    if not as_json and before:
                        print(
                            f"[vectors] ken.db {before / 1e6:,.1f} MB "
                            f"-> {after / 1e6:,.1f} MB"
                        )
                except sqlite3.Error as exc:
                    result["vacuum_error"] = str(exc)
                    if not as_json:
                        print(f"[vectors] VACUUM skipped ({exc}); vectors moved fine")
            elif not as_json:
                print("[vectors] nothing to move")
        elif action == "compact":
            if not as_json:
                print("[vectors] renumbering live vectors into a dense prefix")
            result["compacted"] = compact(conn, root, dim=dim, progress=say)
        else:
            report: dict[str, Any] = {}
            for space, table in SPACES.items():
                inline = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE embedding IS NOT NULL"
                ).fetchone()[0]
                try:
                    store = VectorStore(root, space, dim=dim)
                except VectorStoreError as exc:
                    report[space] = {"error": str(exc), "inline": inline}
                    continue
                try:
                    info = store.verify(conn) if action == "verify" else {}
                    info["inline_pending"] = inline
                    info["bytes"] = store.bytes_on_disk()
                    report[space] = info
                finally:
                    store.close()
            result["spaces"] = report
    except VectorStoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    if as_json:
        print(json.dumps(result, indent=2))
        return 0
    if action in ("status", "verify"):
        for space, info in result["spaces"].items():
            if "error" in info:
                print(f"{space:<20} {info['error']}")
                continue
            size = info["bytes"] / 1e6
            line = f"{space:<20} {size:>9,.1f} MB"
            if action == "verify":
                line += (
                    f"  referenced={info['referenced']:,} free={info['free']:,} "
                    f"leaked={info['leaked']:,} out_of_range={info['out_of_range']:,}"
                )
            if info["inline_pending"]:
                line += f"  [{info['inline_pending']:,} still inline — run `ken vectors migrate`]"
            print(line)
    return 0


def _reembed_cli(
    project_path: Path,
    *,
    model: str | None,
    as_json: bool,
    check_only: bool = False,
) -> int:
    """Re-encode every stored embedding, optionally switching model."""
    import os

    from ken.db import connect
    from ken.reembed import reembed, stored_embedding_info, validate_embeddings

    root, db_path = _resolve_project_db(project_path)
    if db_path is None:
        print(f"error: no .ken project at {root}", file=sys.stderr)
        return 1
    if model:
        os.environ["KEN_EMBED_MODEL"] = model

    if check_only:
        with connect(db_path) as conn:
            report = validate_embeddings(conn)
        if as_json:
            print(json.dumps(report, indent=2))
        elif report.get("ok"):
            print(
                f"ok: embeddings match live model '{report['live_model']}' "
                f"(dim={report.get('live_dim')}, probe cosine={report.get('probe_cosine')})"
            )
        else:
            print(f"stale: {report.get('reason')}", file=sys.stderr)
        return 0 if report.get("ok") else 1

    with connect(db_path) as conn:
        prev_model, prev_dim = stored_embedding_info(conn)
        if not as_json:
            print(
                f"previous: model={prev_model or 'unknown'} dim={prev_dim or 'unknown'}"
            )
        try:
            result = reembed(conn, progress=None if as_json else print)
        except Exception as exc:  # pragma: no cover - surfaced to the user
            print(f"error: re-embedding failed: {exc}", file=sys.stderr)
            return 1

    if as_json:
        print(
            json.dumps({"ok": True, "previous_model": prev_model, **result}, indent=2)
        )
    else:
        total = sum(v for k, v in result.items() if isinstance(v, int))
        print(
            f"re-encoded {total} embeddings with {result['model']} "
            f"(dim={result['dim']})"
        )
        if prev_dim and result["dim"] and prev_dim != result["dim"]:
            print(f"note: dimension changed {prev_dim} -> {result['dim']}")
    return 0


def _default_model_cli(*, model: str | None, clear: bool) -> int:
    """Show or set the embedding model used for NEW projects (user-level).

    Existing projects are pinned to their own model and are never changed by
    this — switch one deliberately with ``ken reembed --model <name>``.
    """
    from ken.embedder import (
        RECOMMENDED_MODEL,
        _config_path,
        get_user_default_model,
        recommended_model,
        set_user_default_model,
    )

    if clear:
        path = set_user_default_model(None)
        print("cleared; new projects will use ken's built-in default:")
        print(f"  {RECOMMENDED_MODEL}")
        print(f"(config: {path})")
        return 0

    if model:
        path = set_user_default_model(model)
        print(f"default model for new projects set to:\n  {model}")
        print(f"(config: {path})")
        print(
            "existing projects are unaffected — switch one with: "
            "ken reembed --model <name>"
        )
        return 0

    if get_user_default_model():
        print(f"default model for new projects: {recommended_model()}")
        print(f"  source: your config ({_config_path()})")
    else:
        print(f"default model for new projects: {recommended_model()}")
        print("  source: ken built-in default (no override set)")
        print("  set one with:  ken default-model <model>")
    return 0


# Curated torch-backend models (not in fastembed) worth surfacing — the
# benchmark's top performers. The torch backend can load any sentence-
# transformers model, so this is a hint list, not an exhaustive one.
_TORCH_MODELS = (
    (
        "Qwen/Qwen3-Embedding-0.6B",
        1024,
        1200,
        "multilingual · best quality in ken's benchmark",
    ),
    ("BAAI/bge-m3", 1024, 4400, "multilingual"),
)


def _models_cli(*, as_json: bool) -> int:
    """List embedding models: the fastembed catalog (drop-in) plus a few
    curated torch-backend models."""
    from ken.embedder import LEGACY_MODEL, recommended_model

    try:
        from fastembed import TextEmbedding

        supported = TextEmbedding.list_supported_models()
    except Exception as exc:  # pragma: no cover - fastembed always present
        print(f"error: could not load the fastembed model list: {exc}", file=sys.stderr)
        return 1

    default = recommended_model()
    rows = []
    for m in supported:
        name = m.get("model")
        desc = str(m.get("description") or "")
        rows.append(
            {
                "model": name,
                "dim": m.get("dim"),
                "mb": round((m.get("size_in_GB") or 0) * 1024),
                "multilingual": "multilingual" in desc.lower()
                or "multilingual" in str(name).lower(),
                "backend": "fastembed",
            }
        )
    rows.sort(key=lambda r: (r["dim"] or 0, r["mb"] or 0, str(r["model"])))

    if as_json:
        torch_rows = [
            {"model": n, "dim": d, "mb": mb, "multilingual": True, "backend": "torch"}
            for (n, d, mb, _desc) in _TORCH_MODELS
        ]
        print(
            json.dumps(
                {
                    "default": default,
                    "legacy": LEGACY_MODEL,
                    "models": rows + torch_rows,
                },
                indent=2,
            )
        )
        return 0

    print("fastembed models — drop-in, no extra deps (ken reembed --model <name>):\n")
    print(f"  {'dim':>4} {'MB':>6}  model")
    for r in rows:
        tags = []
        if r["model"] == default:
            tags.append("← default")
        elif r["model"] == LEGACY_MODEL:
            tags.append("(old default)")
        if r["multilingual"]:
            tags.append("[multilingual]")
        suffix = "   " + " ".join(tags) if tags else ""
        print(f"  {str(r['dim']):>4} {r['mb']:>6}  {r['model']}{suffix}")

    print(
        "\ntorch backend — opt-in, `pip install ken-rank[torch]` (any sentence-transformers model):\n"
    )
    print(f"  {'dim':>4} {'MB':>6}  model")
    for name, dim, mb, desc in _TORCH_MODELS:
        print(f"  {dim:>4} {mb:>6}  {name}   [{desc}]")

    # The static table is its own category: no network to run, no extra
    # dependency, and it is only usable when its artifact is on the machine —
    # so listing it unconditionally would advertise something a user may not be
    # able to select.
    from ken.embedder import STATIC_MODEL
    from ken.embedder.static_head import artifact_available

    if artifact_available(STATIC_MODEL):
        tag = "   ← default" if default == STATIC_MODEL else ""
        print("\nstatic table — a lookup and a sum, no model to run:\n")
        print(f"  {'dim':>4} {'MB':>6}  model")
        print(f"  {1024:>4} {23:>6}  {STATIC_MODEL}{tag}")

    print("\nSet the default for NEW projects:  ken default-model <model>")
    print("Switch THIS project:               ken reembed --model <model>")
    return 0


def _bench_cli(
    project_path: Path,
    dataset_path: Path,
    *,
    top: int,
    max_chars: int,
    fail_under_case_recall: float | None,
    fail_under_expected_file_recall: float | None,
    explain_misses: bool,
    as_json: bool,
) -> int:
    from ken.db import connect
    from ken.embedder import get_embedder
    from ken.ranker import rank
    from ken.ranker.output import render_block

    root, db_path = _resolve_project_db(project_path)
    if db_path is None:
        print(f"error: no .ken project at {root}", file=sys.stderr)
        return 1
    try:
        cases = _load_bench_cases(dataset_path)
    except OSError as exc:
        print(
            f"error: cannot read benchmark dataset {dataset_path}: {exc}",
            file=sys.stderr,
        )
        return 1
    if not cases:
        print(f"error: no valid benchmark cases in {dataset_path}", file=sys.stderr)
        return 1

    embedder = get_embedder()
    rows: list[dict[str, Any]] = []
    hit_cases = 0
    total_expected = 0
    found_expected = 0
    total_chars = 0
    with connect(db_path) as conn:
        for idx, case in enumerate(cases, start=1):
            prompt = str(case["prompt"])
            expected = set(case["expected_files"])
            result = rank(
                conn,
                agent_id="__ken_bench__",
                current_iteration=0,
                prompt=prompt,
                prompt_embedding=embedder.embed_query(prompt),
                top_files=max(1, top),
                project_root=root,
            )
            ranked = [it.target for it in result.files[:top]]
            ranked_details = [
                {
                    "path": it.target,
                    "score": round(float(it.score), 3),
                    "reason": it.reason,
                }
                for it in result.files[:top]
            ]
            hits = sorted(expected & set(ranked))
            misses = sorted(expected - set(ranked))
            block = render_block(
                conn,
                result,
                verbose=0,
                max_chars=max_chars if max_chars > 0 else None,
            )
            chars = len(block)
            row = {
                "case": idx,
                "prompt": prompt,
                "expected_files": sorted(expected),
                "ranked_files": ranked,
                "hits": hits,
                "hit": bool(hits),
                "context_chars": chars,
                "context_est_tokens": (chars + 3) // 4 if chars else 0,
            }
            if explain_misses:
                row["misses"] = misses
                row["ranked_details"] = ranked_details
            rows.append(row)
            hit_cases += 1 if hits else 0
            total_expected += len(expected)
            found_expected += len(hits)
            total_chars += chars

    metrics = {
        "ok": True,
        "cases": len(rows),
        "top": top,
        "case_recall": round(hit_cases / len(rows), 4),
        "expected_file_recall": round(found_expected / total_expected, 4)
        if total_expected
        else 0.0,
        "avg_context_chars": round(total_chars / len(rows), 1),
        "avg_context_est_tokens": round(((total_chars + 3) // 4) / len(rows), 1),
        "results": rows,
    }
    failed: list[str] = []
    if (
        fail_under_case_recall is not None
        and metrics["case_recall"] < fail_under_case_recall
    ):
        failed.append(
            f"case_recall {metrics['case_recall']:.4f} < {fail_under_case_recall:.4f}"
        )
    if (
        fail_under_expected_file_recall is not None
        and metrics["expected_file_recall"] < fail_under_expected_file_recall
    ):
        failed.append(
            "expected_file_recall "
            f"{metrics['expected_file_recall']:.4f} < {fail_under_expected_file_recall:.4f}"
        )
    if failed:
        metrics["ok"] = False
        metrics["failures"] = failed
    if as_json:
        print(json.dumps(metrics, indent=2))
    else:
        print(
            f"cases={metrics['cases']} top={top} "
            f"case_recall={metrics['case_recall']:.2%} "
            f"expected_file_recall={metrics['expected_file_recall']:.2%} "
            f"avg_context≈{metrics['avg_context_est_tokens']} tokens"
        )
        for row in rows:
            status = "hit" if row["hit"] else "miss"
            print(
                f"{row['case']}. {status}: {row['prompt']} "
                f"expected={row['expected_files']} hits={row['hits']}"
            )
            if explain_misses and row.get("misses"):
                print(f"   misses={row['misses']}")
                for detail in row.get("ranked_details", [])[:3]:
                    print(
                        f"   top: {detail['path']} "
                        f"score={detail['score']} reason={detail['reason']}"
                    )
        for failure in failed:
            print(f"FAIL: {failure}", file=sys.stderr)
    return 1 if failed else 0


def _load_bench_cases(dataset_path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with dataset_path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise SystemExit(
                    f"invalid JSON on {dataset_path}:{line_no}: {exc}"
                ) from exc
            prompt = row.get("prompt")
            expected = row.get("expected_files")
            if not isinstance(prompt, str) or not prompt.strip():
                raise SystemExit(
                    f"{dataset_path}:{line_no}: prompt must be a non-empty string"
                )
            if not isinstance(expected, list) or not all(
                isinstance(p, str) and p for p in expected
            ):
                raise SystemExit(
                    f"{dataset_path}:{line_no}: expected_files must be a non-empty string list"
                )
            cases.append({"prompt": prompt.strip(), "expected_files": expected})
    return cases


def _tools_cli(
    project_path: Path,
    tool_name: str | None,
    tool_argv: list[str],
    *,
    list_only: bool,
    compact: bool,
) -> int:
    """Dispatch `ken tools ...` — a thin CLI over the MCP tool registry.

    The tool list, descriptions, and per-parameter schemas are read live
    from the same ``FastMCP`` object ``ken mcp`` serves, so this stays in
    sync with the MCP surface automatically — there is no second list of
    tools to maintain.
    """
    from ken.mcp import server as mcp_server

    registry = {t.name: t for t in mcp_server.mcp._tool_manager.list_tools()}

    if list_only or not tool_name:
        _print_tools_list(registry)
        return 0

    tool = registry.get(tool_name) or registry.get(f"ken_{tool_name}")
    if tool is None:
        import difflib

        print(f"error: unknown tool {tool_name!r}", file=sys.stderr)
        candidates = list(registry) + [
            n[len("ken_") :] for n in registry if n.startswith("ken_")
        ]
        suggestions = difflib.get_close_matches(tool_name, candidates, n=3, cutoff=0.5)
        if suggestions:
            print(f"did you mean: {', '.join(suggestions)}", file=sys.stderr)
        else:
            print("run `ken tools` to list available tools", file=sys.stderr)
        return 2

    tool_parser = _build_tool_parser(tool)
    ns = tool_parser.parse_args(tool_argv)
    props = tool.parameters.get("properties", {})
    kwargs = {name: getattr(ns, name) for name in props if hasattr(ns, name)}

    from ken import _paths

    root = _paths.find_project_root(project_path.resolve()) or project_path.resolve()
    if not _paths.meta_path(root).is_file():
        print(f"error: no .ken project at {root}", file=sys.stderr)
        return 1
    mcp_server._PROJECT_ROOT = root

    try:
        result = tool.fn(**kwargs)
        if tool.is_async:
            import asyncio

            result = asyncio.run(result)
    except Exception as exc:  # surface tool errors as a clean CLI failure
        print(f"error: {tool.name} failed: {exc}", file=sys.stderr)
        return 1

    if compact:
        print(json.dumps(result, default=str))
    else:
        print(json.dumps(result, indent=2, default=str))
    return 0


def _print_tools_list(registry: dict[str, Any]) -> None:
    width = max((len(n) for n in registry), default=0)
    for name in sorted(registry):
        summary = _first_doc_line(registry[name].description)
        print(f"  {name:<{width}}  {summary}")
    print("\nRun `ken tools <name> --help` for a tool's parameters.")


def _first_doc_line(text: str | None) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _tool_schema_core(prop: dict[str, Any]) -> dict[str, Any]:
    """Collapse an ``anyOf: [T, null]`` (Optional[T]) schema to just ``T``."""
    if "anyOf" in prop:
        for variant in prop["anyOf"]:
            if variant.get("type") != "null":
                return variant
    return prop


def _tool_py_type(json_type: str | None):
    return {"integer": int, "number": float, "string": str}.get(json_type, str)


def _build_tool_parser(tool: Any) -> argparse.ArgumentParser:
    """Build an argparse parser for one tool from its JSON schema.

    Required parameters become positionals (in schema order); optional
    ones become ``--flags`` whose defaults mirror the function signature.
    This gives every tool a real ``--help`` for free.
    """
    props: dict[str, Any] = tool.parameters.get("properties", {})
    required = set(tool.parameters.get("required", []))
    parser = argparse.ArgumentParser(
        prog=f"ken tools {tool.name}",
        description=(tool.description or "").strip() or None,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    for name, prop in props.items():
        core = _tool_schema_core(prop)
        json_type = core.get("type")
        default = prop.get("default")
        is_required = name in required
        flag = "--" + name.replace("_", "-")

        if json_type == "boolean":
            parser.add_argument(
                flag,
                dest=name,
                action=argparse.BooleanOptionalAction,
                default=default,
                help=f"boolean (default: {default})",
            )
        elif json_type == "array":
            item_type = _tool_py_type(core.get("items", {}).get("type"))
            if is_required:
                parser.add_argument(
                    name, nargs="+", type=item_type, help="list (required)"
                )
            else:
                parser.add_argument(
                    flag,
                    dest=name,
                    nargs="*",
                    type=item_type,
                    default=default,
                    help="space-separated list",
                )
        else:
            py_type = _tool_py_type(json_type)
            if is_required:
                parser.add_argument(
                    name, type=py_type, help=f"{json_type or 'string'} (required)"
                )
            else:
                parser.add_argument(
                    flag,
                    dest=name,
                    type=py_type,
                    default=default,
                    help=f"{json_type or 'string'} (default: {default!r})",
                )
    return parser


def _resolve_project_db(project_path: Path) -> tuple[Path, Path | None]:
    from ken import _paths

    root = _paths.find_project_root(project_path.resolve()) or project_path.resolve()
    db_path = _paths.db_path(root)
    return root, db_path if db_path.is_file() else None
