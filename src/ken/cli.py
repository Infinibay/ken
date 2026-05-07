"""Command-line entrypoint for installing, querying, and serving ken.

Subcommand layout:

    ken install [PATH]                  install + initial index
    ken status [PATH]                   show project state
    ken rank [QUERY...]                 print ranked context for a query
    ken explain [QUERY...]              explain rank scoring for a query
    ken search-files QUERY              semantic file search
    ken search-symbols QUERY            semantic symbol search
    ken bench DATASET.jsonl             evaluate ranker recall on labeled prompts
    ken remember TOPIC CONTENT          save a reusable finding
    ken recall QUERY                    search saved findings
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
import sys
from pathlib import Path
from typing import Any

from ken import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ken")
    parser.add_argument("--version", action="version", version=f"ken {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_install = sub.add_parser("install", help="install ken into a project")
    p_install.add_argument("path", nargs="?", default=".", help="project path (default: cwd)")
    p_install.add_argument("-q", "--quiet", action="store_true", help="suppress per-file index output")
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

    p_status = sub.add_parser("status", help="show ken project status")
    p_status.add_argument("path", nargs="?", default=".", help="project path (default: cwd)")
    p_status.add_argument("--json", action="store_true", help="print machine-readable status")

    p_rank = sub.add_parser("rank", help="print ranked context for a query")
    p_rank.add_argument("query", nargs="*", help="query text (default: latest prompt)")
    p_rank.add_argument("--path", default=".", help="project path (default: cwd)")
    p_rank.add_argument("-v", "--verbose", type=int, choices=(0, 1, 2), default=1)
    p_rank.add_argument("--max-chars", type=int, help="cap rendered context size")
    p_rank.add_argument("--stats", action="store_true", help="print context size stats to stderr")
    p_rank.add_argument("--json", action="store_true", help="print raw JSON response")

    p_explain = sub.add_parser("explain", help="explain rank scoring for a query")
    p_explain.add_argument("query", nargs="*", help="query text (default: latest prompt)")
    p_explain.add_argument("--path", default=".", help="project path (default: cwd)")
    p_explain.add_argument("--json", action="store_true", help="print raw JSON response")

    p_search_files = sub.add_parser("search-files", help="semantic search over indexed files")
    p_search_files.add_argument("query", nargs="+", help="query text")
    p_search_files.add_argument("--path", default=".", help="project path (default: cwd)")
    p_search_files.add_argument("-n", "--limit", type=int, default=8)
    p_search_files.add_argument("--json", action="store_true", help="print raw JSON response")

    p_search_symbols = sub.add_parser("search-symbols", help="semantic search over indexed symbols")
    p_search_symbols.add_argument("query", nargs="+", help="query text")
    p_search_symbols.add_argument("--path", default=".", help="project path (default: cwd)")
    p_search_symbols.add_argument("-n", "--limit", type=int, default=10)
    p_search_symbols.add_argument("--json", action="store_true", help="print raw JSON response")

    p_bench = sub.add_parser("bench", help="evaluate ranker recall on a JSONL dataset")
    p_bench.add_argument("dataset", help="JSONL rows with prompt + expected_files")
    p_bench.add_argument("--path", default=".", help="project path (default: cwd)")
    p_bench.add_argument("--top", type=int, default=8, help="ranked files to evaluate")
    p_bench.add_argument("--max-chars", type=int, default=0, help="optional render budget")
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
    p_bench.add_argument("--json", action="store_true", help="print machine-readable metrics")

    p_remember = sub.add_parser("remember", help="save a reusable finding")
    p_remember.add_argument("topic", help="short lookup key")
    p_remember.add_argument("content", help="finding content")
    p_remember.add_argument("--path", default=".", help="project path (default: cwd)")
    p_remember.add_argument("--tag", action="append", default=[], help="tag for the finding")
    p_remember.add_argument("--json", action="store_true", help="print raw JSON response")

    p_recall = sub.add_parser("recall", help="semantic search over saved findings")
    p_recall.add_argument("query", nargs="+", help="query text")
    p_recall.add_argument("--path", default=".", help="project path (default: cwd)")
    p_recall.add_argument("-n", "--limit", type=int, default=5)
    p_recall.add_argument("--json", action="store_true", help="print raw JSON response")

    p_serve = sub.add_parser("serve", help="run the ken daemon")
    p_serve.add_argument("path", nargs="?", default=".", help="project path (default: cwd)")
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
    p_mcp.add_argument("path", nargs="?", default=".", help="project path (default: cwd)")

    p_uninstall = sub.add_parser("uninstall", help="remove ken hooks from a project")
    p_uninstall.add_argument("path", nargs="?", default=".", help="project path (default: cwd)")
    p_uninstall.add_argument("--keep-db", action="store_true", help="don't delete .ken/ken.db")

    args = parser.parse_args(argv)

    if args.cmd == "install" and args.embed_limit is not None and not args.embed:
        parser.error("--embed-limit requires --embed")

    if args.cmd == "install":
        from ken.install import install

        install(
            Path(args.path),
            verbose=not args.quiet,
            force_claude=args.claude,
            force_codex=args.codex,
            embed=args.embed,
            embed_limit=args.embed_limit,
        )
        return 0

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

    if args.cmd == "bench":
        return _bench_cli(
            Path(args.path),
            Path(args.dataset),
            top=args.top,
            max_chars=args.max_chars,
            fail_under_case_recall=args.fail_under_case_recall,
            fail_under_expected_file_recall=args.fail_under_expected_file_recall,
            as_json=args.json,
        )

    if args.cmd == "remember":
        return _remember_cli(
            Path(args.path),
            args.topic,
            args.content,
            tags=args.tag,
            as_json=args.json,
        )

    if args.cmd == "recall":
        return _recall_cli(
            Path(args.path), " ".join(args.query), args.limit, as_json=args.json
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

    if args.cmd == "uninstall":
        from ken.install_uninstall import uninstall

        return uninstall(Path(args.path), keep_db=args.keep_db)

    parser.error(f"unknown command: {args.cmd}")
    return 2


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

    resp = daemon_client.post(project_path.resolve(), "/explain", {"query": query.strip()})
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
    est_tokens = int(resp.get("context_est_tokens") or ((chars + 3) // 4 if chars else 0))
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
            hits = search_files(conn, query, limit=limit)
            rendered = format_file_hits(hits)
        else:
            hits = search_symbols(conn, query, limit=limit)
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
    as_json: bool,
) -> int:
    from ken.memory import remember

    root, db_path = _resolve_project_db(project_path)
    if db_path is None:
        print(f"error: no .ken project at {root}", file=sys.stderr)
        return 1
    from ken.db import connect

    with connect(db_path) as conn:
        resp = remember(conn, topic, content, tags=tags)
    if as_json:
        print(json.dumps(resp, indent=2))
    elif resp.get("ok"):
        print(f"remembered: {resp['topic']}")
    else:
        print(f"error: {resp.get('error', 'remember failed')}", file=sys.stderr)
    return 0 if resp.get("ok") else 1


def _recall_cli(project_path: Path, query: str, limit: int, *, as_json: bool) -> int:
    from ken.db import connect
    from ken.memory import format_recall_hits, recall

    root, db_path = _resolve_project_db(project_path)
    if db_path is None:
        print(f"error: no .ken project at {root}", file=sys.stderr)
        return 1
    with connect(db_path) as conn:
        hits = recall(conn, query, limit=limit)
    if as_json:
        print(json.dumps(hits, indent=2))
    else:
        rendered = format_recall_hits(hits)
        if rendered:
            print(rendered)
    return 0


def _bench_cli(
    project_path: Path,
    dataset_path: Path,
    *,
    top: int,
    max_chars: int,
    fail_under_case_recall: float | None,
    fail_under_expected_file_recall: float | None,
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
        print(f"error: cannot read benchmark dataset {dataset_path}: {exc}", file=sys.stderr)
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
            hits = sorted(expected & set(ranked))
            block = render_block(
                conn,
                result,
                verbose=0,
                max_chars=max_chars if max_chars > 0 else None,
            )
            chars = len(block)
            rows.append(
                {
                    "case": idx,
                    "prompt": prompt,
                    "expected_files": sorted(expected),
                    "ranked_files": ranked,
                    "hits": hits,
                    "hit": bool(hits),
                    "context_chars": chars,
                    "context_est_tokens": (chars + 3) // 4 if chars else 0,
                }
            )
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
                raise SystemExit(f"invalid JSON on {dataset_path}:{line_no}: {exc}") from exc
            prompt = row.get("prompt")
            expected = row.get("expected_files")
            if not isinstance(prompt, str) or not prompt.strip():
                raise SystemExit(f"{dataset_path}:{line_no}: prompt must be a non-empty string")
            if not isinstance(expected, list) or not all(
                isinstance(p, str) and p for p in expected
            ):
                raise SystemExit(
                    f"{dataset_path}:{line_no}: expected_files must be a non-empty string list"
                )
            cases.append({"prompt": prompt.strip(), "expected_files": expected})
    return cases


def _resolve_project_db(project_path: Path) -> tuple[Path, Path | None]:
    from ken import _paths

    root = _paths.find_project_root(project_path.resolve()) or project_path.resolve()
    db_path = _paths.db_path(root)
    return root, db_path if db_path.is_file() else None
